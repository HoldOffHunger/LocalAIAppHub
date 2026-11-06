// The hub: a side panel of every app, each one kept loaded in its own frame so switching back finds it as it was.
const POLL_MS = 5000;
const STARTING_POLL_MS = 1500;
const LAST_APP_KEY = "hub-last-app";
const START_PATIENCE_MS = 90000;  // Autonoma loads her memory first; past this, something went wrong in its console

const hub = { apps: [], active: "", frames: {}, wasRunning: {}, starting: "", startedAt: 0, timer: 0 };
const $ = (id) => document.getElementById(id);

function frameUrl(app) {
  // The apps' cookies only reach them when the hub and the app share a host name, so match whichever one the hub was opened on
  if (!/^https?:/.test(app.url)) return app.url;
  const url = new URL(app.url);
  if (url.hostname === "127.0.0.1" || url.hostname === "localhost") url.hostname = location.hostname;
  return url.toString();
}

function appById(id) {
  return hub.apps.find((app) => app.id === id);
}

function remember(id) {
  try { localStorage.setItem(LAST_APP_KEY, id); } catch (error) { /* private window: just don't remember */ }
}

function recalled() {
  try { return localStorage.getItem(LAST_APP_KEY) || ""; } catch (error) { return ""; }
}

function buildRow(app) {
  const row = document.createElement("div");
  row.className = "app" + (app.running ? " up" : "") + (app.id === hub.active ? " active" : "");
  row.innerHTML = `<button class="pick"><span class="icon"></span><span class="name"></span><span class="dot"></span></button>` +
    `<button class="extra reload" title="Reload">↻</button><a class="extra open" title="Open in its own tab" target="_blank" rel="noopener">↗</a>`;
  row.querySelector(".pick").title = app.title;
  row.querySelector(".icon").textContent = app.icon;
  row.querySelector(".name").textContent = app.title;
  row.querySelector(".pick").addEventListener("click", () => show(app.id));
  row.querySelector(".reload").addEventListener("click", () => reload(app.id));
  row.querySelector(".open").href = frameUrl(app);
  return row;
}

function renderRail() {
  const list = $("app-list");
  list.replaceChildren(...hub.apps.map(buildRow));
}

function ensureFrame(app) {
  if (hub.frames[app.id]) return hub.frames[app.id];
  const frame = document.createElement("iframe");
  frame.title = app.title;
  if (app.allow) frame.allow = app.allow;  // e.g. Voice's "microphone; autoplay": a framed app can't ask for them otherwise
  frame.src = frameUrl(app);
  $("stage").appendChild(frame);
  hub.frames[app.id] = frame;
  return frame;
}

function dropFrame(id) {
  // An app that went away and came back has a new login link, so its old frame is stale
  if (!hub.frames[id]) return;
  hub.frames[id].remove();
  delete hub.frames[id];
}

function showOffline(app) {
  const starting = app.starting || hub.starting === app.id;
  $("offline-text").textContent = starting ? `Starting ${app.title}…` : `${app.title} isn't running.` +
    (app.can_start ? "" : " Start it the usual way, and it will appear here.") + (app.note ? " " + app.note : "");
  $("offline-start").hidden = !app.can_start || starting;
  $("offline").hidden = false;
}

function show(id) {
  const app = appById(id) || hub.apps[0];
  hub.active = app.id;
  remember(app.id);
  history.replaceState(null, "", "#" + app.id);
  Object.values(hub.frames).forEach((frame) => { frame.hidden = true; });
  $("offline").hidden = true;
  if (app.running) ensureFrame(app).hidden = false;
  else showOffline(app);
  document.title = app.title + " · App Hub";
  renderRail();
}

function reload(id) {
  dropFrame(id);
  refresh().then(() => show(id));
}

async function startActive() {
  hub.starting = hub.active;
  hub.startedAt = Date.now();
  showOffline(appById(hub.active));
  const reply = await fetch(`/api/apps/${hub.active}/start`, { method: "POST" }).then((r) => r.json())
    .catch(() => ({ error: "The hub server didn't answer." }));
  if (reply.error && reply.error !== "already running") stopWaiting(reply.error);
  schedule(STARTING_POLL_MS);
}

function stopWaiting(message) {
  hub.starting = "";
  showOffline(appById(hub.active));
  $("offline-text").textContent = message;
}

function noteChanges() {
  // Apps that just came up (or went down) get a fresh frame next time they're shown
  hub.apps.forEach((app) => {
    if (app.running !== hub.wasRunning[app.id]) dropFrame(app.id);
    if (app.running && hub.starting === app.id) hub.starting = "";
    hub.wasRunning[app.id] = app.running;
  });
}

async function refresh() {
  const apps = await fetch("/api/apps").then((r) => r.json()).catch(() => null);
  if (!apps) return;
  hub.apps = apps;
  noteChanges();
}

async function refreshGpu() {
  // The desk's view: who has the card now, and anyone else still holding a lease (a clip finishing, say)
  const gpu = await fetch("/api/gpu").then((r) => r.json()).catch(() => null);
  if (!gpu) return;
  const owner = gpu.leases.find((lease) => lease.app === gpu.owner);
  const others = gpu.leases.filter((lease) => lease.app !== gpu.owner).map((lease) => lease.title);
  let text = owner ? `${owner.title}, ${Math.max(1, Math.round(owner.minutes_left))} min` : "free";
  if (others.length) text += ` (+ ${others.join(", ")})`;
  if (!owner && gpu.autonoma_loaded.length) text = "Autonoma's model is loaded";
  $("gpu-text").textContent = text;
  $("gpu").classList.toggle("held", Boolean(owner) || gpu.autonoma_loaded.length > 0);
  $("gpu").title = "Who has the graphics card. " + (gpu.leases.length
    ? gpu.leases.map((lease) => `${lease.title}${lease.background ? " (background)" : ""}: ${lease.minutes_left} min left`).join("; ")
    : "Nobody has asked for it lately.");
  if (!$("kick-chat").disabled) $("kick-chat").hidden = !gpu.leases.some((lease) => lease.app === "chat" && !lease.background);
}

async function kickChat() {
  // The emergency button: Chat's lease and model go now, and the AI Workers needn't wait out the quiet time
  const button = $("kick-chat");
  button.disabled = true;
  button.textContent = "Kicking…";
  await fetch("/api/gpu/kick", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ app: "chat" }) }).catch(() => null);
  button.disabled = false;
  button.textContent = "Kick Chat off GPU";
  await refreshGpu();
}

function schedule(delay) {
  clearTimeout(hub.timer);
  hub.timer = setTimeout(tick, delay);
}

async function tick() {
  const stateOf = (app) => (app ? `${app.running}/${app.starting}` : "");
  const before = stateOf(appById(hub.active));
  await Promise.all([refresh(), refreshGpu()]);
  if (hub.starting && Date.now() - hub.startedAt > START_PATIENCE_MS) {
    const app = appById(hub.starting);
    hub.starting = "";
    if (hub.active === app.id) stopWaiting(`${app.title} still isn't answering. Its console window should say why.`);
  }
  if (stateOf(appById(hub.active)) !== before) show(hub.active);
  else renderRail();
  schedule(hub.starting || hub.apps.some((app) => app.starting) ? STARTING_POLL_MS : POLL_MS);
}

async function init() {
  $("offline-start").addEventListener("click", startActive);
  $("kick-chat").addEventListener("click", kickChat);
  window.addEventListener("hashchange", () => show(location.hash.slice(1)));
  await refresh();
  if (!hub.apps.length) return;
  show(location.hash.slice(1) || recalled() || "chat");
  refreshGpu();
  schedule(POLL_MS);
}

init();
