// ImageGen's page: a composer on the left, the gallery on the right, a viewer over the top.
"use strict";

const $ = (id) => document.getElementById(id);
const MAX_SIDE = 2048; // bigger pictures are shrunk here; Comfy scales them to a megapixel anyway

let kind = "image"; // or "video"
let references = []; // data URLs, in order: "image 1", "image 2", ...
let models = []; // every model, both kinds, from /api/models
let menu = null;
let pictures = [];
let viewing = null;
let shelf = "gallery"; // or "defects": the pictures Ben marked as badly made, of either kind
let fixing = ""; // the defect the composer is trying to repair, sent with the next picture
// The tags a defect can carry, and what Fix this asks the model to do about each
const DEFECTS = {
  hands: ["hands", "Fix the hands so each has five well-formed fingers."],
  limbs: ["limbs", "Fix the arms and legs so there are the right number, properly attached."],
  face: ["face", "Fix the face so it looks natural."],
  text: ["text", "Fix the lettering so it is clean and legible."],
  anatomy: ["anatomy", "Fix the body so its anatomy looks natural."],
  other: ["other", ""],
};
const pending = new Map(); // job id -> its placeholder tile

// ---- references ----

function maxReferences() {
  // a clip starts from one picture, and so does an SDXL picture
  const model = (models || []).find((item) => item.id === $("model").value);
  return kind === "video" ? 1 : (model && model.references) || 4;
}

function renderReferences() {
  $("refs").replaceChildren(...references.map((url, index) => {
    const tile = document.createElement("div");
    tile.className = "ref";
    tile.innerHTML = `<img alt=""><span class="tag">image ${index + 1}</span><button title="Remove">✕</button>`;
    tile.querySelector("img").src = url;
    tile.querySelector("button").onclick = (event) => {
      event.stopPropagation();
      references.splice(index, 1);
      renderReferences();
    };
    return tile;
  }));
  const editing = references.length > 0;
  const video = kind === "video";
  $("size-row").hidden = editing || video;
  $("size-note").hidden = !editing || video;
  $("video-row").hidden = !video;
  $("video-note").hidden = !video;
  if (video) {
    $("drop-hint").innerHTML = editing ? "The clip opens on this picture"
      : "Drop, paste or <u>pick</u> a picture for the clip to open on (optional)";
  } else {
    $("drop-hint").innerHTML = references.length >= maxReferences() ? "That's the most it takes at once"
      : editing ? "Add another, or say what to do with them"
      : "Drop, paste or <u>pick</u> pictures to work from (up to 4)";
  }
}

function shrink(blob) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const scale = Math.min(1, MAX_SIDE / Math.max(image.width, image.height));
      if (scale === 1 && /^image\/(png|jpeg|webp)$/.test(blob.type)) {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.readAsDataURL(blob);
      } else {
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(image.width * scale);
        canvas.height = Math.round(image.height * scale);
        canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/png"));
      }
      URL.revokeObjectURL(image.src);
    };
    image.onerror = () => reject(new Error("That doesn't look like a picture."));
    image.src = URL.createObjectURL(blob);
  });
}

async function addBlobs(blobs) {
  for (const blob of blobs) {
    if (references.length >= maxReferences()) break;
    if (!blob.type.startsWith("image/")) continue;
    try {
      references.push(await shrink(blob));
    } catch (error) {
      say(error.message, true);
    }
  }
  renderReferences();
}

async function addFromUrl(url) {
  const response = await fetch(url);
  if (response.ok) await addBlobs([await response.blob()]);
}

// ---- making pictures ----

function say(text, bad = false) {
  $("status").textContent = text;
  $("status").classList.toggle("bad", bad);
}

async function make() {
  const prompt = $("prompt").value.trim();
  if (!prompt) {
    say("Say what you'd like first, even for an edit.", true);
    $("prompt").focus();
    return;
  }
  const [width, height] = $("size").value.split("x").map(Number);
  const response = await fetch("/api/generate", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({kind, prompt, model: $("model").value, images: references, width, height,
      seconds: Number($("clip-length").value), size: $("clip-size").value, seed: $("seed").value.trim(), fixes: fixing}),
  });
  const result = await response.json();
  if (!response.ok) {
    say(result.error || "Something went wrong.", true);
    return;
  }
  fixing = "";
  say("");
  addPendingTile(result.job, prompt);
  watchJob(result.job);
}

function addPendingTile(jobId, prompt) {
  const tile = document.createElement("div");
  tile.className = "tile pending";
  tile.dataset.kind = kind; // made from the switch as it stood, so it shows under that side of the gallery
  tile.innerHTML = `<div class="clock">…</div><div class="bar"><div class="fill"></div></div>
    <div class="what"></div><div class="caption"></div>`;
  tile.querySelector(".caption").textContent = prompt;
  pending.set(jobId, tile);
  $("empty").hidden = true;
  $("gallery").prepend(tile);
}

async function watchJob(jobId) {
  const tile = pending.get(jobId);
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    let job;
    try {
      job = await (await fetch("/api/jobs/" + jobId)).json();
    } catch {
      continue; // the server blinked; keep waiting
    }
    const percent = job.percent || 0;
    tile.querySelector(".fill").style.width = percent + "%";
    tile.querySelector(".clock").textContent = job.state === "working" && job.elapsed !== undefined ? percent + "%" : "…";
    tile.querySelector(".what").textContent = (job.message || "") +
      (job.elapsed !== undefined ? " · " + Math.round(job.elapsed) + "s" : "");
    if (job.state === "done") {
      pending.delete(jobId);
      tile.remove();
      await loadGallery();
      return;
    }
    if (job.state === "failed" || job.error) {
      pending.delete(jobId);
      tile.remove();
      say(job.message || job.error, true);
      renderGallery();
      return;
    }
  }
}

// ---- gallery and viewer ----

async function loadGallery() {
  pictures = await (await fetch("/api/gallery")).json();
  renderGallery();
}

function renderGallery() {
  // The gallery follows the switch: Video shows the clips, Image the pictures. Defects show on their own shelf only.
  const defects = shelf === "defects";
  const shown = pictures.filter((picture) => defects ? picture.defect : !picture.defect && (picture.kind || "image") === kind);
  const making = defects ? [] : [...pending.values()].filter((tile) => tile.dataset.kind === kind);
  for (const button of $("shelves").querySelectorAll("button")) {
    button.classList.toggle("on", defects ? button.dataset.shelf === "defects" : button.dataset.shelf === kind);
  }
  const count = pictures.filter((picture) => picture.defect).length;
  $("defect-count").textContent = count ? String(count) : "";
  const tiles = shown.map((picture) => {
    const tile = document.createElement("div");
    tile.className = "tile";
    if (picture.kind === "video") {
      // Clips sit still on their first frame and play while the mouse is over them
      tile.innerHTML = `<video muted loop playsinline preload="metadata"></video><span class="play">▶ ${picture.length}s</span>
        <div class="caption"></div>`;
      const clip = tile.querySelector("video");
      clip.src = fileUrl(picture);
      tile.onmouseenter = () => clip.play().catch(() => {});
      tile.onmouseleave = () => { clip.pause(); clip.currentTime = 0; };
    } else {
      tile.innerHTML = `<img alt="" loading="lazy" draggable="true"><div class="caption"></div>`;
      tile.querySelector("img").src = fileUrl(picture);
    }
    tile.querySelector(".caption").textContent = picture.prompt;
    if (picture.defect) {
      const badge = document.createElement("span");
      badge.className = "defect-badge";
      badge.textContent = picture.defect.tags.join(" · ");
      tile.append(badge);
    }
    tile.onclick = () => openViewer(picture);
    return tile;
  });
  $("gallery").replaceChildren(...making, ...tiles);
  $("empty").hidden = tiles.length + making.length > 0;
  $("empty").textContent = defects ? "No defects. Mark a badly made picture from its viewer and it moves here."
    : kind === "video" ? "No clips yet. Your clips will gather here." : "Nothing yet. Your pictures will gather here.";
}

function fileUrl(picture) {
  return "/pictures/" + (picture.file || picture.id + ".png"); // pictures from before video have no "file"
}

function openViewer(picture) {
  viewing = picture;
  const video = picture.kind === "video";
  $("viewer-img").hidden = video;
  $("viewer-video").hidden = !video;
  if (video) {
    $("viewer-video").src = fileUrl(picture);
    $("viewer-video").play().catch(() => {});
  } else {
    $("viewer-img").src = fileUrl(picture);
  }
  $("v-use").hidden = video;
  $("viewer-prompt").textContent = picture.prompt;
  $("viewer-refs").replaceChildren(...picture.references.map((name) => {
    const image = document.createElement("img");
    image.src = "/references/" + name;
    image.title = "Worked from this";
    return image;
  }));
  const shape = picture.length ? `${picture.length}s ${picture.size} · `
    : picture.width ? `${picture.width}×${picture.height} · ` : "";
  const model = models.find((item) => item.id === modelOf(picture));
  const label = model ? model.label : modelOf(picture);
  const fixed = picture.fixes ? " · made to fix a defect" : "";
  $("viewer-meta").textContent = `${label} · ${shape}seed ${picture.seed} · ${picture.seconds}s · ${picture.created}${fixed}`;
  showDefect(picture);
  $("v-save").href = fileUrl(picture);
  $("v-save").download = "imagegen-" + fileUrl(picture).split("/").pop();
  $("viewer").hidden = false;
}

function closeViewer() {
  $("viewer-video").pause();
  $("viewer").hidden = true;
  viewing = null;
}

function usePrompt(picture, withSeed) {
  setKind(picture.kind || "image");
  $("prompt").value = picture.prompt;
  if (picture.length) {
    $("clip-length").value = String(picture.length);
    $("clip-size").value = picture.size;
  }
  const option = [...$("model").options].find((item) => item.value === modelOf(picture));
  if (option && !option.disabled) $("model").value = option.value;
  renderModelNote();
  if (withSeed) $("seed").value = picture.seed;
  if (picture.width) {
    const option = [...$("size").options].find((item) => item.value === `${picture.width}x${picture.height}`);
    if (option) $("size").value = option.value;
  }
}

$("v-use").onclick = async () => {
  const picture = viewing;
  closeViewer();
  await addFromUrl(fileUrl(picture));
  $("prompt").value = "";
  $("prompt").focus();
};
$("v-again").onclick = async () => {
  const picture = viewing;
  closeViewer();
  usePrompt(picture, false);
  references = [];
  for (const name of picture.references) await addFromUrl("/references/" + name);
  renderReferences();
  $("seed").value = "";
  $("prompt").focus();
};
$("v-seed").onclick = () => {
  usePrompt(viewing, true);
  closeViewer();
};
$("v-delete").onclick = async () => {
  if (!confirm(viewing.kind === "video" ? "Delete this clip for good?" : "Delete this picture for good?")) return;
  await fetch("/api/gallery/" + viewing.id, {method: "DELETE"});
  closeViewer();
  await loadGallery();
};
$("v-close").onclick = closeViewer;

// ---- defects: badly made pictures, kept apart and fixable ----

function showDefect(picture) {
  const marked = picture.defect;
  $("v-defect").hidden = !!marked;
  $("v-defect-form").hidden = true;
  $("v-defect-said").hidden = !marked;
  $("v-undefect").hidden = !marked;
  $("v-fix").hidden = !marked || picture.kind === "video"; // a clip can't be edited, only made again
  if (marked) $("v-defect-said").textContent = "Defect: " + marked.tags.join(", ") + (marked.note ? ` — ${marked.note}` : "");
}

function chosenTags() {
  return [...$("v-defect-tags").querySelectorAll("button.on")].map((button) => button.dataset.tag);
}

$("v-defect-tags").replaceChildren(...Object.entries(DEFECTS).map(([tag, [label]]) => {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.tag = tag;
  button.textContent = label;
  button.onclick = () => { button.classList.toggle("on"); $("v-defect-save").disabled = !chosenTags().length; };
  return button;
}));

$("v-defect").onclick = () => {
  $("v-defect").hidden = true;
  $("v-defect-form").hidden = false;
  for (const button of $("v-defect-tags").querySelectorAll("button")) button.classList.remove("on");
  $("v-defect-note").value = "";
  $("v-defect-save").disabled = true;
};

async function markDefect(picture, body) {
  const response = await fetch(`/api/gallery/${picture.id}/defect`, {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) { say(result.error || "Couldn't mark it.", true); return null; }
  pictures = pictures.map((item) => item.id === result.id ? result : item);
  renderGallery();
  return result;
}

$("v-defect-save").onclick = async () => {
  const marked = await markDefect(viewing, {tags: chosenTags(), note: $("v-defect-note").value});
  if (marked) { viewing = marked; showDefect(marked); }
};

$("v-undefect").onclick = async () => {
  const back = await markDefect(viewing, {defect: null});
  if (back) { viewing = back; showDefect(back); }
};

$("v-fix").onclick = async () => {
  // Into the composer as an edit, with a repair prompt from its tags; Klein 9B KV follows edits best
  const picture = viewing;
  closeViewer();
  setKind("image");
  references = [];
  await addFromUrl(fileUrl(picture));
  const asks = picture.defect.tags.map((tag) => DEFECTS[tag][1]).filter(Boolean);
  const note = picture.defect.note;
  if (note) asks.push(note[0].toUpperCase() + note.slice(1).replace(/\.?$/, "."));
  $("prompt").value = [...asks, "Keep everything else exactly the same."].join(" ");
  const better = [...$("model").options].find((option) => option.value === "klein-9b-kv" && !option.disabled);
  if (better) { $("model").value = better.value; renderModelNote(); }
  fixing = picture.id;
  say("Fixing a defect: change the prompt if you like, then make it.");
  $("prompt").focus();
};

for (const button of $("shelves").querySelectorAll("button")) {
  button.onclick = () => {
    if (button.dataset.shelf === "defects") {
      shelf = "defects";
      renderGallery();
    } else {
      setKind(button.dataset.shelf);
    }
  };
}
$("viewer").onclick = (event) => { if (event.target.id === "viewer") closeViewer(); };

// ---- setup banner: models still downloading, or Comfy still waking ----

async function checkStatus() {
  try {
    const status = await (await fetch("/api/status")).json();
    let text = "";
    // ComfyUI being off is normal now: it starts with the next picture
    if (status.missing_models.length) text = "Still waiting for model files: " + status.missing_models.join(", ");
    $("setup").textContent = text;
    $("setup").hidden = !text;
  } catch {
    // the server is restarting; try again next time
  }
}

// ---- the model menu ----

function modelOf(picture) {
  // pictures from before the menu say "strength" instead
  return picture.model || (picture.strength === "strong" ? "klein-9b-kv" : "klein-4b");
}

function fitText(model, vram) {
  if (model.fits === null) return "";
  return model.fits ? `fits in ${vram} GB` : `bigger than ${vram} GB, streams from RAM`;
}

async function loadModels() {
  let fresh;
  try {
    fresh = await (await fetch("/api/models")).json();
  } catch {
    return;
  }
  // Rebuilding the menu closes it if it's open, so only when something changed
  if (JSON.stringify(fresh.models) === JSON.stringify(models)) return;
  menu = fresh;
  models = menu.models;
  renderModelOptions($("model").value);
}

function renderModelOptions(wanted) {
  if (!menu) return;
  try { wanted = wanted || localStorage.getItem("imagegen-model-" + kind); } catch {}
  const choices = models.filter((model) => model.kind === kind);
  $("model").replaceChildren(...choices.map((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.disabled = model.missing.length > 0;
    const size = model.model_gb ? ` · ${model.model_gb} GB` : "";
    const fit = model.fits === null ? "" : model.fits ? " · fits" : " · streams from RAM";
    // 🔴 marks the uncensored models; a menu option can't hold a coloured dot of its own, but it can hold this one
    option.textContent = (model.uncensored ? "🔴 " : "") + `${model.label} · ${model.note}${size}${fit}` + (option.disabled ? " · not downloaded yet" : "");
    option.dataset.vram = menu.vram_gb;
    return option;
  }));
  const usable = choices.filter((model) => !model.missing.length).map((model) => model.id);
  $("model").value = usable.includes(wanted) ? wanted : menu.default[kind];
  renderModelNote();
}

function setKind(value) {
  shelf = "gallery"; // choosing what to make shows what that makes
  if (value === kind) { renderGallery(); return; }
  kind = value;
  for (const button of $("kind").querySelectorAll("button")) {
    const on = button.dataset.kind === value;
    button.classList.toggle("on", on);
    button.setAttribute("aria-checked", on);
  }
  references = references.slice(0, maxReferences());
  renderReferences();
  renderModelOptions("");
  $("make").firstChild.textContent = kind === "video" ? "Make the clip " : "Make it ";
  $("prompt").placeholder = kind === "video"
    ? "Snow drifts past a lantern-lit library window as the fox turns a page\n\n…or add a picture and say how it moves"
    : "A fox reading by lantern-light in an old library\n\n…or add a picture and say what to change: \"make it winter\"";
  try { localStorage.setItem("imagegen-kind", kind); } catch {}
  renderGallery();
}

for (const button of $("kind").querySelectorAll("button")) button.onclick = () => setKind(button.dataset.kind);

function renderModelNote() {
  const model = models.find((item) => item.id === $("model").value);
  const option = $("model").selectedOptions[0];
  if (!model || !option) return;
  const vram = option.dataset.vram;
  const fit = fitText(model, vram);
  $("model-note").innerHTML = "";
  if (model.missing.length) {
    $("model-note").textContent = "Waiting for: " + model.missing.join(", ");
    return;
  }
  const span = document.createElement("span");
  span.className = model.fits ? "fits" : "streams";
  span.textContent = fit;
  const sizes = model.encoder_gb ? `Model ${model.model_gb} GB, text reader ${model.encoder_gb} GB` : `Model ${model.model_gb} GB, all in one`;
  $("model-note").append(sizes + (fit ? " · " : ""), span);
  if (model.uncensored) {
    const dot = document.createElement("span");
    dot.className = "uncensored";
    dot.textContent = " · ● uncensored";
    $("model-note").append(dot);
  }
  if (model.references) $("model-note").append(` · works from words, or ${model.references} picture`);
}

$("model").onchange = () => {
  renderModelNote();
  references = references.slice(0, maxReferences());  // an SDXL model works from one picture at most
  renderReferences();
  try { localStorage.setItem("imagegen-model-" + kind, $("model").value); } catch {}
};

// ---- wiring ----

$("make").onclick = make;
$("prompt").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) make();
});
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && viewing) closeViewer(); });
$("seed-clear").onclick = () => { $("seed").value = ""; };
$("drop").onclick = () => $("file").click();
$("file").onchange = () => { addBlobs([...$("file").files]); $("file").value = ""; };
$("drop").addEventListener("dragover", (event) => { event.preventDefault(); $("drop").classList.add("over"); });
$("drop").addEventListener("dragleave", () => $("drop").classList.remove("over"));
$("drop").addEventListener("drop", (event) => {
  event.preventDefault();
  $("drop").classList.remove("over");
  if (event.dataTransfer.files.length) addBlobs([...event.dataTransfer.files]);
  else {
    // a picture dragged in from the gallery
    const url = event.dataTransfer.getData("text/uri-list") || event.dataTransfer.getData("text/plain");
    if (url && url.startsWith(location.origin)) addFromUrl(url);
  }
});
document.addEventListener("paste", (event) => {
  const blobs = [...event.clipboardData.items].filter((item) => item.type.startsWith("image/")).map((item) => item.getAsFile());
  if (blobs.length) {
    event.preventDefault();
    addBlobs(blobs);
  }
});
$("size").onchange = () => { try { localStorage.setItem("imagegen-size", $("size").value); } catch {} };
try {
  const size = localStorage.getItem("imagegen-size");
  if (size) $("size").value = size;
  if (localStorage.getItem("imagegen-kind") === "video") setKind("video");
} catch {}

renderReferences();
loadGallery();
checkStatus();
loadModels();
setInterval(() => { checkStatus(); loadModels(); }, 10000); // a download finishing, or Comfy waking with the card's size
