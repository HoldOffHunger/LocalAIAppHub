// The Foreman page: a card per task with its progress, the night shift, the run in progress, and what each task found
const $ = (id) => document.getElementById(id);
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const page = { state: null, open: 0, board: "ongoing", stretch: 0 };  // board: Ongoing Jobs, or Completed Jobs (deployed ones); stretch: minutes the stop-time box has added

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children.filter((c) => c !== null && c !== undefined));
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

const send = (path, method, body) => api(path, { method, body: body ? JSON.stringify(body) : undefined }).then(render);
const fail = (error) => toast(error.message);

function toast(text) {
  const box = $("toast");
  box.textContent = text;
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (box.hidden = true), 3500);
}

const number = (n) => Number(n).toLocaleString();
const STEPS = [1, 10, 60, 600];  // the stop-time box's buttons, in minutes: +1 min, +10 min, +1 hr, +10 hr

function clock(when) {
  // The Foreman says "19:37", or a whole date and time; Ben reads 7:37 PM
  const date = when instanceof Date ? when : new Date(when.includes("T") ? when : `2000-01-01T${when}`);
  return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

function extras(progress) {
  // Whatever else the task reports about itself, as "typos 12 · clean texts 4,210"
  const shown = new Set(["done", "total", "percent", "complete", "error", "note", "checked", "left"]);
  return Object.entries(progress).filter(([key]) => !shown.has(key)).map(([key, value]) => `${key} ${typeof value === "number" ? number(value) : value}`).join(" · ");
}

function kindTitle(name) {
  return (page.state.kinds.find((kind) => kind.name === name) || { title: name }).title;
}

function taskState(task, run) {
  if (task.deployed) return [`Deployed ${task.deployed}`, "shipped"];
  if (run.running && run.task === task.id) return ["Working" + (run.until ? ` until ${clock(run.until)}` : ""), "on"];
  if (task.progress.complete) return ["Done", "done"];
  return task.active ? ["In the night shift", ""] : ["Paused", "off"];
}

function card(task, run) {
  const progress = task.progress || {};
  const [label, mood] = taskState(task, run);
  const percent = progress.percent ?? 0;
  const counts = progress.total ? `${number(progress.done)} / ${number(progress.total)}` : progress.error || progress.note || "no progress reported yet";
  const chip = el("span", { className: `chip ${mood}`, textContent: label });
  if (mood === "" || mood === "off") {
    // "Paused" and "In the night shift" are a switch: click to flip it
    chip.classList.add("toggle");
    chip.title = task.active ? "Click to take it out of the night shift" : "Click to put it back in the night shift";
    chip.onclick = (event) => { event.stopPropagation(); setActive(task.id, !task.active); };
  }
  const box = el("article", { className: `task ${mood}` },
    el("div", { className: "head" }, el("strong", { textContent: task.name }), chip),
    el("div", { className: "kind small dim", textContent: `${kindTitle(task.kind)} · ${task.target}` }),
    el("div", { className: "bar" }, el("div", { style: `width:${Math.min(percent, 100)}%` })),
    el("div", { className: "numbers" }, el("span", { className: "percent", textContent: `${percent}%` }), el("span", { textContent: counts })),
    el("div", { className: "small dim", textContent: extras(progress) }));
  box.onclick = () => openTask(task.id);
  return box;
}

function setText(node, text) {
  // Written only when it changes: rewriting the same text every refresh dropped whatever Ben had selected in it
  if (node.textContent !== text) node.textContent = text;
}

function render(state) {
  page.state = state;
  const run = state.run;
  const shown = state.tasks.filter((task) => !!task.deployed === (page.board === "completed"));
  const empty = page.board === "completed" ? "Nothing deployed yet. A task moves here once its results are live."
    : state.tasks.length ? "Every task is deployed. Add one to get the workers going." : "No tasks yet. Add one to get the workers going.";
  const cards = JSON.stringify([page.board, run.running, run.task, run.until, shown, state.kinds.map((kind) => kind.title)]);
  if (cards !== page.cards) {  // the cards are rebuilt only when something on them changed, for the same reason
    page.cards = cards;
    $("tasks").replaceChildren(...shown.map((task) => card(task, run)), ...(shown.length ? [] : [el("p", { className: "dim", textContent: empty })]));
  }
  setText($("show-ongoing"), `Ongoing Jobs (${state.tasks.length - state.tasks.filter((t) => t.deployed).length})`);
  setText($("show-completed"), `Completed Jobs (${state.tasks.filter((t) => t.deployed).length})`);
  const free = state.free_until ? `Free time until ${clock(state.free_until)} · ` : "";
  setText($("rest"), state.rest_minutes ? `Rest ${duration(state.rest_minutes)}` : "No rest");
  setText($("status-chip"), free + (run.running ? `Working: ${run.name}${run.until ? ` until ${clock(run.until)}` : ""}` : state.waiting || "Idle"));
  $("status-chip").classList.toggle("on", run.running);
  $("status-chip").classList.toggle("toggle", !!state.ends_at);
  $("status-chip").title = state.ends_at ? "Click to change the stop time" : "";
  if ($("stretch").open) showStretch();
  $("stop").hidden = !run.running && !state.free_until;
  $("free-box").hidden = run.running || !!state.free_until;
  const log = state.log.length ? state.log.join("\n")
    : run.running ? `${run.name} is working, but hasn't written to its log yet.` : "Nothing has run yet.";
  if ($("log").textContent !== log) {
    $("log").textContent = log;
    $("log").scrollTop = $("log").scrollHeight;  // follows the tail only when there's a new line, so it can be scrolled back and read
  }
  setText($("log-title"), run.log ? `Log · ${run.log}` : "Log");
  if (page.open && $("detail").open) fillProgress(state.tasks.find((task) => task.id === page.open));
}

// The stop-time box: nudge the stop time later (or back) without stopping and restarting by hand

function openStretch() {
  if (!page.state.ends_at) return;
  page.stretch = 0;
  $("stretch").showModal();
  showStretch();
}

function showStretch() {
  const ends = page.state.ends_at;
  if (!ends) { $("stretch").close(); return; }
  const target = new Date(new Date(ends).getTime() + page.stretch * 60000);
  const left = Math.round((target - Date.now()) / 60000);
  const sign = page.stretch < 0 ? "−" : "+";
  const change = Math.abs(page.stretch);
  $("stretch-old").textContent = clock(ends);
  $("stretch-new").textContent = page.stretch ? ` → ${clock(target)}` : "";
  $("stretch-change").textContent = page.stretch ? `${sign}${duration(change)}` : "";
  $("stretch-left").textContent = left > 0 ? `That's ${duration(left)} from now.` : "That's already gone by.";
  $("stretch-save").disabled = !page.stretch || left < 1;
  $("stretch-queue").replaceChildren(...rotation(page.state));
}

// The jobs the free time will work, in order, and where each stands this round: so "nothing to do" is never a surprise
function rotation(state) {
  const { worked = [], quick = [] } = state.rotation || {};
  const waiting = state.tasks.filter((task) => task.active && !task.deployed && !task.progress.complete);
  if (!waiting.length) return [el("li", { className: "dim", textContent: "Nothing: every active task is finished or deployed." })];
  return waiting.map((task) => {
    const working = state.run.running && state.run.task === task.id;
    const stand = working ? "working now" : quick.includes(task.id) ? "came straight back; sits out until the next window"
      : worked.includes(task.id) ? "had its turn this round" : "waiting its turn";
    const done = task.progress.percent !== undefined ? ` · ${task.progress.percent}%` : "";
    return el("li", { className: working ? "on" : quick.includes(task.id) ? "dim" : "" },
      el("span", { textContent: task.name }), el("span", { className: "dim", textContent: ` · ${stand}${done}` }));
  });
}

function duration(minutes) {
  const hours = Math.floor(minutes / 60), rest = minutes % 60;
  return [hours ? `${hours} hr` : "", rest || !hours ? `${rest} min` : ""].filter(Boolean).join(" ");
}

function stepButtons(sign) {
  return STEPS.map((step) => el("button", { type: "button", className: sign < 0 ? "quiet" : "", textContent: `${sign < 0 ? "−" : "+"}${duration(step)}`,
    onclick: () => { page.stretch += sign * step; showStretch(); } }));
}

function saveStretch(event) {
  event.preventDefault();
  send("/api/stretch", "POST", { minutes: page.stretch })
    .then(() => { $("stretch").close(); toast(`New stop time: ${clock(page.state.ends_at)}.`); }).catch(fail);
}

// Adding a task: pick the kind of work, then what it works on

function openAdd() {
  $("add-kind").replaceChildren(...page.state.kinds.map((kind) => el("option", { value: kind.name, textContent: kind.title })));
  pickKind();
  $("add-name").value = "";
  $("add").showModal();
}

function pickKind() {
  const kind = page.state.kinds.find((k) => k.name === $("add-kind").value);
  $("add-about").textContent = kind ? kind.description : "";
  $("add-target").replaceChildren(...(kind ? kind.targets : []).map((target) => el("option", { value: target, textContent: target })));
}

// One task, opened: rename it, run it for a while, read what it found

async function openTask(id) {
  const task = page.state.tasks.find((t) => t.id === id);
  page.open = id;
  $("detail-kind").textContent = `${kindTitle(task.kind)} · ${task.target}`;
  $("detail-name").value = task.name;
  $("detail-notes").value = task.notes;
  $("detail-active").checked = task.active;
  $("detail-deploy").textContent = task.deployed ? "Move back to Ongoing" : "Mark deployed";
  fillProgress(task);
  $("detail-results").textContent = "Loading…";
  $("detail").showModal();
  $("detail-results").textContent = (await api(`/api/tasks/${id}/results`).catch((e) => ({ text: e.message }))).text;
}

function fillProgress(task) {
  if (!task) return;
  const progress = task.progress || {};
  setText($("detail-progress"), progress.total
    ? `${progress.percent}% · ${number(progress.done)} of ${number(progress.total)} done${extras(progress) ? " · " + extras(progress) : ""}`
    : progress.error || progress.note || "");
}

function runTask(body) {
  send(`/api/tasks/${page.open}/run`, "POST", body).then(() => { $("detail").close(); toast("Working."); }).catch(fail);
}

function saveTask() {
  const body = { name: $("detail-name").value, notes: $("detail-notes").value, active: $("detail-active").checked };
  send(`/api/tasks/${page.open}`, "PATCH", body).then(() => toast("Saved.")).catch(fail);
}

function setActive(id, active) {
  send(`/api/tasks/${id}`, "PATCH", { active }).then(() => toast(active ? "Back in the night shift." : "Paused: out of the night shift.")).catch(fail);
}

function toggleDeployed() {
  // Deployed: its results are live, so it moves to Completed Jobs and the night shift leaves it alone
  const task = page.state.tasks.find((t) => t.id === page.open);
  const deployed = task.deployed ? "" : new Date().toLocaleDateString("en-CA");
  send(`/api/tasks/${page.open}`, "PATCH", { deployed })
    .then(() => { $("detail").close(); toast(deployed ? "Moved to Completed Jobs." : "Back in Ongoing Jobs."); }).catch(fail);
}

function showBoard(board) {
  page.board = board;
  $("show-ongoing").setAttribute("aria-pressed", board === "ongoing");
  $("show-completed").setAttribute("aria-pressed", board === "completed");
  if (page.state) render(page.state);
}

function deleteTask() {
  if (!confirm("Delete this task's card? What it found stays on disk in data/tasks/.")) return;
  send(`/api/tasks/${page.open}`, "DELETE").then(() => { $("detail").close(); page.open = 0; }).catch(fail);
}

// The night shift

function openShift() {
  const schedule = page.state.schedule;
  $("enabled").checked = schedule.enabled;
  $("start").value = schedule.start;
  $("end").value = schedule.end;
  const awake = schedule.mode === "until_awake";
  $("mode-window").checked = !awake;
  $("mode-awake").checked = awake;
  $("end").disabled = awake;
  $("days").replaceChildren(...DAYS.map((name, index) =>
    el("label", {}, el("input", { type: "checkbox", value: index, checked: schedule.days.includes(index) }), name)));
  $("shift").showModal();
}

function saveSchedule(event) {
  event.preventDefault();
  const days = [...$("days").querySelectorAll("input:checked")].map((box) => Number(box.value));
  const mode = $("mode-awake").checked ? "until_awake" : "window";
  const body = { enabled: $("enabled").checked, start: $("start").value, end: $("end").value, days, mode };
  send("/api/schedule", "PUT", body).then(() => { $("shift").close(); toast("Schedule saved."); }).catch(fail);
}

async function refresh() {
  try {
    render(await api("/api/state"));
  } catch (error) {
    $("status-chip").textContent = error.message;
  }
}

$("show-add").onclick = openAdd;
$("add-kind").onchange = pickKind;
$("add-save").onclick = (event) => {
  event.preventDefault();
  send("/api/tasks", "POST", { kind: $("add-kind").value, target: $("add-target").value, name: $("add-name").value })
    .then(() => { $("add").close(); toast("Task added."); }).catch(fail);
};
$("free").onclick = () => send("/api/free-time", "POST", { minutes: Number($("free-minutes").value) })
  .then(() => toast("Free time: they'll work the active tasks in order.")).catch(fail);
$("show-shift").onclick = openShift;
$("rest").onclick = () => { $("rest-minutes").value = page.state.rest_minutes ?? 5; $("rest-box").showModal(); };
$("rest-save").onclick = (event) => {
  event.preventDefault();
  const minutes = Number($("rest-minutes").value);
  send("/api/rest", "PUT", { minutes })
    .then(() => { $("rest-box").close(); toast(minutes ? `They'll rest ${duration(minutes)} between jobs.` : "No rest between jobs."); }).catch(fail);
};
$("status-chip").onclick = openStretch;
$("stretch-more").replaceChildren(...stepButtons(1));
$("stretch-less").replaceChildren(...stepButtons(-1));
$("stretch-save").onclick = saveStretch;
$("save-schedule").onclick = saveSchedule;
for (const id of ["mode-window", "mode-awake"]) $(id).onchange = () => { $("end").disabled = $("mode-awake").checked; };
$("stop").onclick = () => send("/api/stop", "POST").then(() => toast("Stopped.")).catch(fail);
$("detail-save").onclick = saveTask;
$("detail-hour").onclick = () => runTask({ minutes: 60 });
$("detail-run").onclick = () => runTask({ minutes: Number($("detail-minutes").value) || 30 });
$("detail-finish").onclick = () => runTask({});
$("detail-delete").onclick = deleteTask;
$("detail-deploy").onclick = toggleDeployed;
$("show-ongoing").onclick = () => showBoard("ongoing");
$("show-completed").onclick = () => showBoard("completed");
$("detail-active").onchange = () => setActive(page.open, $("detail-active").checked);  // saves at once, no "Save changes" needed
$("detail").addEventListener("close", () => (page.open = 0));
refresh();
setInterval(refresh, 4000);
