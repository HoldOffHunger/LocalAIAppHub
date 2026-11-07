// Voice: hold the button (or Space) and talk; let go, and Whisper writes down what you said, the writer answers, and
// Kokoro speaks the answer sentence by sentence while the rest is still being written. Talking over her stops her.

const $ = (id) => document.getElementById(id);
const page = { setup: null, threads: [], thread: null, recorder: null, holding: false, handsFree: false, hearing: false, noise: 0.01, stream: null, chunks: [], startedAt: 0,
               controller: null, queue: [], playing: null, streaming: false, speakingEl: null };

const statusLine = (text) => { $("status").textContent = text; };
const IDLE_HINTS = { hold: "Hold the button, or hold Space, and talk.",
                     toggle: "Click the button, or tap Space, to start talking; again to send.",
                     auto: "Click the button, or tap Space, to start hands-free: talk, pause, and she answers." };
const idleHint = () => IDLE_HINTS[$("talk-mode").value] || IDLE_HINTS.hold;
const shown = (text) => (text || "").replace(/<think>[\s\S]*?(<\/think>|$)/g, "").trim();

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `${response.status}`);
  return body;
}
const send = (path, method, body) => api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// ---------- the pickers ----------

function fillPickers() {
  const { models, voices, characters } = page.setup;
  $("character").replaceChildren(new Option("No character", ""), ...characters.map((c) => new Option(c.name, c.id)));
  $("model").replaceChildren(...models.map((m) => new Option(m, m)));
  // Grouped by accent and sex, and each says so itself too, since a closed menu only shows the option
  const groups = new Map();
  for (const voice of voices) {
    const label = `${voice.accent} · ${voice.sex}${voice.english ? "" : " (speaking English)"}`;
    if (!groups.has(label)) groups.set(label, document.createElement("optgroup"));
    groups.get(label).label = label;
    groups.get(label).append(new Option(`${voice.name}${voice.favourite ? " ★" : ""} · ${voice.sex}, ${voice.accent}`, voice.id));
  }
  $("voice").replaceChildren(...groups.values());
}

function showPicks(picks) {
  $("character").value = picks.character_id || "";
  $("model").value = picks.model || "";
  $("voice").value = picks.voice || "";
  $("speed").value = picks.speed || 1;
  $("speed-value").textContent = `${Number($("speed").value).toFixed(2)}×`;
}

function currentPicks() {
  return { character_id: $("character").value, model: $("model").value, voice: $("voice").value, speed: Number($("speed").value) };
}

async function pickChanged(event) {
  event.target.blur();  // so Space talks again rather than reopening the menu
  $("speed-value").textContent = `${Number($("speed").value).toFixed(2)}×`;
  if (event.target.id === "character") {
    // A character brings the voice it was last given
    const remembered = page.setup.character_voices[$("character").value];
    if (remembered) $("voice").value = remembered;
  }
  if (event.target.id === "voice" && $("character").value) page.setup.character_voices[$("character").value] = $("voice").value;
  if (page.thread) page.thread = await send(`/api/threads/${page.thread.id}`, "PATCH", currentPicks());
  if (event.target.id === "character") loadThreads();
}

// ---------- threads ----------

async function loadThreads() {
  page.threads = await api("/api/threads");
  const names = Object.fromEntries(page.setup.characters.map((c) => [c.id, c.name]));
  $("thread-list").replaceChildren(...page.threads.map((thread) => {
    const row = document.createElement("div");
    row.className = "thread" + (page.thread && page.thread.id === thread.id ? " active" : "");
    const title = document.createElement("span");
    title.className = "title";
    if (names[thread.character_id]) {
      const who = document.createElement("span");
      who.className = "who";
      who.textContent = names[thread.character_id] + " · ";
      title.append(who);
    }
    title.append(thread.title);
    title.onclick = () => openThread(thread.id);
    const remove = document.createElement("button");
    remove.textContent = "✕";
    remove.title = "Delete this voice chat and its recordings";
    remove.onclick = () => deleteThread(thread.id);
    row.append(title, remove);
    return row;
  }));
}

async function openThread(id) {
  stopAll();
  page.thread = await api(`/api/threads/${id}`);
  showPicks(page.thread);
  renderMessages();
  loadThreads();
}

async function newThread() {
  stopAll();
  page.thread = await send("/api/threads", "POST", currentPicks());
  showPicks(page.thread);
  renderMessages();
  loadThreads();
}

async function deleteThread(id) {
  if (!confirm("Delete this voice chat, and the recordings of her voice in it?")) return;
  await api(`/api/threads/${id}`, { method: "DELETE" });
  if (page.thread && page.thread.id === id) {
    page.thread = null;
    renderMessages();
  }
  loadThreads();
}

// ---------- the conversation ----------

function speakerName() {
  const character = page.setup.characters.find((c) => c.id === (page.thread || {}).character_id);
  return character ? character.name : "Voice";
}

function messageElement(role, text, audio) {
  const el = document.createElement("div");
  el.className = `message ${role}`;
  const label = document.createElement("div");
  label.className = "role";
  label.textContent = role === "user" ? "You said" : speakerName();
  if (audio && audio.length) label.append(replayButton(audio));
  const body = document.createElement("div");
  body.className = "body";
  body.textContent = text;
  el.append(label, body);
  return el;
}

function replayButton(urls) {
  const button = document.createElement("button");
  button.className = "replay";
  button.textContent = "▶ replay";
  button.onclick = () => { stopAll(); urls.forEach((url) => enqueue(url)); };
  return button;
}

function renderMessages() {
  const box = $("messages");
  if (!page.thread || !page.thread.messages.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.innerHTML = "Pick a character, a writer and a voice.<br>Then hold the button, or hold Space, and talk.";
    box.replaceChildren(empty);
    return;
  }
  box.replaceChildren(...page.thread.messages.map((m) =>
    messageElement(m.role, shown(m.content), (m.audio || []).map((name) => `/api/audio/${page.thread.id}/${name}`))));
  box.scrollTop = box.scrollHeight;
}

function addMessage(role, text) {
  if (!page.thread.messages.length) $("messages").replaceChildren();
  const el = messageElement(role, text);
  $("messages").append(el);
  $("messages").scrollTop = $("messages").scrollHeight;
  return el;
}

// ---------- the microphone ----------
// On 1 Nov 2026 the browser's default microphone was one of the PC's virtual ones (Virtual Desktop, Oculus, Steam
// Streaming), which send perfect silence: every recording came back "I didn't catch that." So the mic is picked here,
// remembered in this browser, and a meter shows whether it hears anything

const MIC_KEY = "voice.mic";
const SILENT = 0.003;  // loudest sample below this, and nothing was heard at all

function savedMic() {
  try { return localStorage.getItem(MIC_KEY) || ""; } catch { return ""; }
}

async function openMic() {
  if (page.stream) return page.stream;
  const wanted = $("mic").value || savedMic();
  const audio = { echoCancellation: true, noiseSuppression: true, ...(wanted ? { deviceId: { exact: wanted } } : {}) };
  try {
    page.stream = await navigator.mediaDevices.getUserMedia({ audio });
  } catch (error) {
    if (!wanted) throw error;
    page.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });  // it was unplugged
  }
  watchLevel(page.stream);
  await listMics();
  return page.stream;
}

async function listMics() {
  // Device names only show once the browser has been allowed the microphone
  const devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audioinput" && d.deviceId !== "communications");
  const using = page.stream && page.stream.getAudioTracks()[0].getSettings().deviceId;
  $("mic").replaceChildren(...devices.map((d) => new Option(d.label || "Microphone", d.deviceId === "default" ? "" : d.deviceId)));
  $("mic").value = devices.some((d) => d.deviceId === using) && using !== "default" ? using : savedMic();
}

function watchLevel(stream) {
  page.audioContext = page.audioContext || new AudioContext();
  page.audioContext.resume();  // a context made outside a click starts paused, and a paused meter would read silence
  const analyser = page.audioContext.createAnalyser();
  analyser.fftSize = 1024;
  page.audioContext.createMediaStreamSource(stream).connect(analyser);
  const samples = new Float32Array(analyser.fftSize);
  const bar = $("level").firstElementChild;
  (function tick() {
    if (page.stream !== stream) return;
    analyser.getFloatTimeDomainData(samples);
    const peak = samples.reduce((most, s) => Math.max(most, Math.abs(s)), 0);
    if (page.recorder) page.loudest = Math.max(page.loudest, peak);
    if (page.recorder && handsFree()) hearSpeech(peak);
    bar.style.width = `${Math.min(100, Math.sqrt(peak) * 140)}%`;
    requestAnimationFrame(tick);
  })();
}

async function micChanged() {
  $("mic").blur();
  try { localStorage.setItem(MIC_KEY, $("mic").value); } catch {}
  if (page.stream) page.stream.getTracks().forEach((track) => track.stop());
  page.stream = null;
  try {
    await openMic();
    statusLine("Say something: the bar beside Mic should move.");
  } catch (error) {
    statusLine("That microphone isn't available: " + error.message);
  }
}

// ---------- listening ----------

async function startTalking() {
  if (page.recorder || page.holding) return;
  page.holding = true;
  stopAll();  // talking over her stops her
  try {
    await openMic();
  } catch (error) {
    page.holding = false;
    statusLine("The microphone isn't available: " + error.message);
    return;
  }
  if (!page.holding) return;  // let go before the microphone was ready (the first time, while the browser asks)
  page.chunks = [];
  page.loudest = 0;
  page.recorder = new MediaRecorder(page.stream, { mimeType: "audio/webm;codecs=opus" });
  page.recorder.ondataavailable = (event) => event.data.size && page.chunks.push(event.data);
  page.recorder.start();
  page.startedAt = performance.now();
  page.speechAt = page.loudAt = 0;
  $("talk").classList.add(handsFree() ? "armed" : "recording");
  statusLine(handsFree() ? "Listening… talk whenever you like. Click the button to stop hands-free." : "Listening…");
}

async function stopTalking({ discard = false } = {}) {
  page.holding = false;
  const recorder = page.recorder;
  if (!recorder) return;
  page.recorder = null;
  $("talk").classList.remove("recording", "armed");
  const finished = new Promise((resolve) => { recorder.onstop = resolve; });
  recorder.stop();
  await finished;
  if (discard) return;
  if (performance.now() - page.startedAt < 400) {
    statusLine(toggling() ? "That was very short; say a little more." : "Hold the button while you talk.");
    return;
  }
  if (page.loudest < SILENT && page.audioContext && page.audioContext.state === "running") {
    statusLine(`“${$("mic").selectedOptions[0]?.textContent || "This microphone"}” sent only silence. Pick your microphone in the Mic menu.`);
    if (handsFree()) setHandsFree(false);
    return;
  }
  page.hearing = true;  // hands-free waits for this reply before it listens again
  try {
    if (!page.thread) await newThread();
    statusLine("Hearing you…");
    $("talk").classList.add("busy");
    const reply = await api(`/api/threads/${page.thread.id}/listen`, { method: "POST", body: new Blob(page.chunks, { type: "audio/webm" }) });
    if (!reply.text) {
      statusLine("I didn't catch that. Try again?");
      return;
    }
    await say(reply.text);
  } catch (error) {
    statusLine("Something went wrong: " + error.message);
  } finally {
    page.hearing = false;
    $("talk").classList.remove("busy");
    listenAgain();
  }
}

// ---------- hands-free ----------
// Turned on, it listens; when you've talked and then gone quiet for a moment, it sends what you said, she answers, and
// once she's finished speaking it listens again. It doesn't listen while she talks, so her voice from the speakers isn't
// taken for yours; click the button to turn it off, which also stops her

const QUIET_MS = 1300;  // this long below the speech line after talking, and you've finished
const LEAST_SPEECH_MS = 300;  // shorter bursts (a cough, a click) don't count as talking
const REARM_MS = 30000;  // nothing said for this long: start the recording afresh so it doesn't grow all evening

const handsFree = () => $("talk-mode").value === "auto" && page.handsFree;

function setHandsFree(on) {
  page.handsFree = on;
  $("talk").classList.toggle("hands-free", on);
  $("stop").disabled = !on && !page.streaming && !page.playing;
  if (on) return startTalking();
  stopAll();
  stopTalking({ discard: true });
  statusLine(idleHint());
}

function listenAgain() {
  // After she's finished (or after a miss), hands-free picks the microphone back up
  if (handsFree() && !page.recorder && !page.holding && !page.hearing && !page.streaming && !page.playing) startTalking();
}

function hearSpeech(peak) {
  // Called with every meter reading while hands-free is recording. The speech line rides above the room's own noise
  const now = performance.now();
  const line = Math.max(0.03, page.noise * 4);
  if (peak > line) {
    page.loudAt = now;
    page.speechAt = page.speechAt || now;
    $("talk").classList.add("recording");
  } else if (!page.speechAt) {
    page.noise = page.noise * 0.98 + peak * 0.02;
  }
  if (page.speechAt && page.loudAt - page.speechAt < LEAST_SPEECH_MS && now - page.loudAt > QUIET_MS) {
    page.speechAt = 0;  // just a blip
    $("talk").classList.remove("recording");
  }
  if (page.speechAt && page.loudAt - page.speechAt >= LEAST_SPEECH_MS && now - page.loudAt > QUIET_MS) {
    stopTalking();
  } else if (!page.speechAt && now - page.startedAt > REARM_MS) {
    stopTalking({ discard: true }).then(listenAgain);
  }
}

// ---------- the reply ----------

async function say(text) {
  addMessage("user", text);
  page.thread.messages.push({ role: "user", content: text });
  const el = addMessage("assistant", "");
  el.classList.add("speaking");
  page.speakingEl = el;
  const body = el.querySelector(".body");
  const audio = [];
  let written = "";
  page.controller = new AbortController();
  page.streaming = true;
  $("stop").disabled = false;
  statusLine(`${speakerName()} is thinking…`);
  try {
    const response = await fetch(`/api/threads/${page.thread.id}/say`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }), signal: page.controller.signal });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || response.status);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      const lines = pending.split("\n");
      pending = lines.pop();
      for (const line of lines.filter(Boolean)) {
        const event = JSON.parse(line);
        if (event.type === "text") {
          written += event.text;
          body.textContent = shown(written).replace(new RegExp(`^${speakerName().replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*:\\s*`), "");
          $("messages").scrollTop = $("messages").scrollHeight;
        } else if (event.type === "audio") {
          audio.push(event.url);
          enqueue(event.url);
        } else if (event.type === "error") {
          statusLine(event.error);
        }
      }
    }
  } catch (error) {
    if (error.name !== "AbortError") statusLine("Something went wrong: " + error.message);
  } finally {
    page.streaming = false;
    page.thread.messages.push({ role: "assistant", content: written });
    if (audio.length) el.querySelector(".role").append(replayButton(audio));
    settle();
    loadThreads();  // the first exchange names the thread
  }
}

function enqueue(url) {
  page.queue.push(url);
  if (!page.playing) playNext();
}

function playNext() {
  const url = page.queue.shift();
  if (!url) {
    page.playing = null;
    settle();
    return;
  }
  page.playing = new Audio(url);
  page.playing.volume = Number($("volume").value);
  page.playing.onended = playNext;
  page.playing.onerror = playNext;
  page.playing.play().catch(playNext);
  statusLine(`${speakerName()} is speaking…`);
  $("stop").disabled = false;
}

function settle() {
  // Back to waiting once she's finished writing and finished speaking
  if (page.streaming || page.playing) return;
  if (page.speakingEl) page.speakingEl.classList.remove("speaking");
  page.speakingEl = null;
  $("stop").disabled = !handsFree();  // hands-free keeps it lit: Stop is how you end it
  if (!page.recorder) statusLine(idleHint());
  listenAgain();
}

function stopAll() {
  if (page.controller) page.controller.abort();
  page.controller = null;
  page.queue = [];
  if (page.playing) page.playing.pause();
  page.playing = null;
  page.streaming = false;
  settle();
}

async function preview() {
  stopAll();
  statusLine("Warming up the voice…");
  const response = await fetch("/api/preview", { method: "POST", headers: { "Content-Type": "application/json" },
                                                 body: JSON.stringify({ voice: $("voice").value, speed: Number($("speed").value) }) });
  if (!response.ok) return statusLine("The voice didn't work.");
  enqueue(URL.createObjectURL(await response.blob()));
}

// ---------- wiring ----------

// Two ways to talk: hold the button (or Space) while talking, or click it (or tap Space) once to start and again to send.
// Remembered in this browser
const MODE_KEY = "voice.talkMode";
const toggling = () => $("talk-mode").value === "toggle";
function toggleTalking() {
  if (page.recorder || page.holding) stopTalking();
  else startTalking();
}
const autoMode = () => $("talk-mode").value === "auto";
const holdMode = () => !autoMode() && !toggling();
function showMode() {
  if (!autoMode() && page.handsFree) setHandsFree(false);
  $("talk").title = autoMode() ? "Click to turn hands-free on or off"
    : toggling() ? "Click to start talking, click again to send" : "Hold to talk";
  if (!page.recorder && !page.streaming && !page.playing) statusLine(idleHint());
}

const talk = $("talk");
talk.addEventListener("pointerdown", (event) => {
  event.preventDefault();
  if (autoMode()) return setHandsFree(!page.handsFree);
  if (toggling()) return toggleTalking();
  talk.setPointerCapture(event.pointerId);
  startTalking();
});
talk.addEventListener("pointerup", () => holdMode() && stopTalking());
talk.addEventListener("pointercancel", () => holdMode() && stopTalking());
const typing = (event) => ["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName) && event.target.type !== "range";
document.addEventListener("keydown", (event) => {
  if (event.code !== "Space" || typing(event)) return;
  event.preventDefault();
  if (event.repeat) return;
  if (autoMode()) setHandsFree(!page.handsFree);
  else if (toggling()) toggleTalking();
  else startTalking();
});
document.addEventListener("keyup", (event) => {
  if (event.code !== "Space" || typing(event)) return;
  event.preventDefault();
  if (holdMode()) stopTalking();
});
try { $("talk-mode").value = localStorage.getItem(MODE_KEY) || "hold"; } catch {}
$("talk-mode").addEventListener("change", () => {
  $("talk-mode").blur();
  try { localStorage.setItem(MODE_KEY, $("talk-mode").value); } catch {}
  showMode();
});
showMode();
$("stop").onclick = () => {
  // Hands-free: while she's thinking or speaking, Stop hushes her and it listens again; while it's only listening,
  // Stop ends hands-free
  if (handsFree() && !page.streaming && !page.playing && !page.hearing) setHandsFree(false);
  else stopAll();
};
$("mic").addEventListener("change", micChanged);

// Her volume, remembered in this browser; it turns her down mid-sentence too
const VOLUME_KEY = "voice.volume";
function showVolume() {
  $("volume-value").textContent = `${Math.round(Number($("volume").value) * 100)}%`;
  if (page.playing) page.playing.volume = Number($("volume").value);
}
try { $("volume").value = localStorage.getItem(VOLUME_KEY) ?? 1; } catch { $("volume").value = 1; }
showVolume();
$("volume").addEventListener("input", showVolume);
$("volume").addEventListener("change", () => {
  $("volume").blur();
  try { localStorage.setItem(VOLUME_KEY, $("volume").value); } catch {}
});
$("preview").onclick = preview;
$("new-thread").onclick = newThread;
for (const id of ["character", "model", "voice", "speed"]) $(id).addEventListener("change", pickChanged);
$("speed").addEventListener("input", () => { $("speed-value").textContent = `${Number($("speed").value).toFixed(2)}×`; });

(async function start() {
  statusLine("Loading the voices…");
  page.setup = await api("/api/setup");
  if (page.setup.problem) {
    $("problem").textContent = page.setup.problem;
    $("problem").hidden = false;
  }
  fillPickers();
  showPicks(page.setup.settings);
  listMics().catch(() => {});  // names show if the browser already has the microphone; otherwise after the first talk
  await loadThreads();
  if (page.threads.length) await openThread(page.threads[0].id);
  else renderMessages();
  statusLine(idleHint());
})();
