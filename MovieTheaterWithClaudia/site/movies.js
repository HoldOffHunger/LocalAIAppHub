// Ben's movies, from start.txt by way of /api/movies: picks, to-watch, then every tier he's rated.
const COLLAPSED_KEY = "movies-collapsed";
// Same order as the recommender's statuses run: checked and ready first, finished ones folded away
const PICK_GROUPS = [
  { status: "srt_pass", label: "Script checked: worth watching", open: true },
  { status: "proposed", label: "Waiting on a script check", open: true },
  { status: "watched", label: "Watched", open: false },
  { status: "srt_fail", label: "Script didn't hold up", open: false },
  { status: "dropped", label: "Dropped", open: false },
];
const $ = (id) => document.getElementById(id);

function loadCollapsed() {
  try { return new Set(JSON.parse(localStorage.getItem(COLLAPSED_KEY) || "[]")); } catch (error) { return new Set(); }
}

function saveCollapsed(collapsed) {
  try { localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...collapsed])); } catch (error) { /* private window */ }
}

function buildMovie(movie) {
  const item = document.createElement("li");
  item.className = "movie" + (movie.comments ? " with-comments" : "");
  item.dataset.search = movie.title.toLowerCase();
  const title = document.createElement("span");
  title.className = "title";
  title.textContent = movie.title;
  item.appendChild(title);
  if (movie.analysis) {
    item.appendChild(scoreBadge(movie.analysis));
    item.classList.add("has-analysis");
    item.addEventListener("click", () => item.classList.toggle("open"));
  } else if (movie.subtitles) {
    const badge = document.createElement("span");
    badge.className = "srt";
    badge.textContent = "subtitles ready";
    badge.title = "There's a matching .srt in _srt_for_claudia";
    item.appendChild(badge);
  }
  if (movie.comments) {
    const comments = document.createElement("div");
    comments.className = "comments";
    comments.textContent = movie.comments;
    item.appendChild(comments);
  }
  if (movie.analysis) item.appendChild(buildAnalysis(movie.analysis));  // Ben's words first, then Claudia's read
  return item;
}

function scoreBadge(analysis) {
  const badge = document.createElement("span");
  badge.className = "srt score-badge";
  badge.textContent = `script ${analysis.score}/10`;
  badge.title = "Claudia's read of the script; click for her notes";
  return badge;
}

function addList(box, heading, items) {
  if (!items.length) return;
  const title = document.createElement("div");
  title.className = "analysis-heading";
  title.textContent = heading;
  const list = document.createElement("ul");
  list.replaceChildren(...items.map((text) => Object.assign(document.createElement("li"), { textContent: text })));
  box.append(title, list);
}

function buildAnalysis(analysis) {
  const box = document.createElement("div");
  box.className = "analysis";
  const summary = document.createElement("p");
  summary.textContent = analysis.summary;
  box.appendChild(summary);
  addList(box, "Works", analysis.strengths);
  addList(box, "Doesn't", analysis.weaknesses);
  addList(box, "Themes", analysis.themes);
  return box;
}

function buildPick(pick) {
  const item = document.createElement("li");
  item.className = "movie with-comments";
  item.dataset.search = pick.title.toLowerCase();
  item.innerHTML = `<span class="title"></span><span class="srt"></span><div class="comments why"></div><div class="comments risk"></div>`;
  item.querySelector(".title").textContent = pick.title + (pick.year ? ` (${pick.year})` : "");
  item.querySelector(".srt").textContent = [pick.director, pick.round ? `round ${pick.round}` : ""].filter(Boolean).join(" · ");
  item.querySelector(".why").textContent = pick.why;
  item.querySelector(".risk").textContent = pick.risk ? "Risk: " + pick.risk : "";
  return item;
}

function buildPickGroup(group, picks) {
  const box = document.createElement("details");
  box.className = "pick-group";
  box.open = group.open;
  box.innerHTML = `<summary></summary><ul class="movies"></ul>`;
  box.querySelector("summary").textContent = `${group.label} (${picks.length})`;
  box.querySelector(".movies").replaceChildren(...picks.map(buildPick));
  return box;
}

function renderPicks(picks) {
  const groups = PICK_GROUPS.map((group) => [group, picks.filter((pick) => pick.status === group.status)]).filter(([, list]) => list.length);
  $("picks-list").replaceChildren(...groups.map(([group, list]) => buildPickGroup(group, list)));
  return groups.length > 0;
}

function buildTier(tier, collapsed) {
  const section = document.createElement("div");
  section.className = "tier" + (tier.rating >= 10 ? " top" : "") + (collapsed.has(tier.id) ? " collapsed" : "");
  section.innerHTML = `<div class="tier-head"><span class="score"></span><span class="count"></span></div>` +
    `<div class="tier-body"><p class="description"></p><ul class="movies"></ul></div>`;
  section.querySelector(".score").textContent = tier.label;
  section.querySelector(".count").textContent = tier.movies.length + (tier.movies.length === 1 ? " movie" : " movies");
  section.querySelector(".description").textContent = tier.description;
  section.querySelector(".movies").replaceChildren(...tier.movies.map(buildMovie));
  section.querySelector(".tier-head").addEventListener("click", () => toggleTier(section, tier.id));
  return section;
}

function toggleTier(section, tierId) {
  const collapsed = loadCollapsed();
  if (collapsed.has(tierId)) collapsed.delete(tierId);
  else collapsed.add(tierId);
  saveCollapsed(collapsed);
  section.classList.toggle("collapsed", collapsed.has(tierId));
}

function renderNotes(notes, hasPicks) {
  const picks = (notes.recommendations || "").trim();
  $("picks-body").innerHTML = picks ? window.renderMarkdown(picks) : hasPicks ? ""
    : `<p class="empty">No picks yet. They come once I've read your scripts and know what makes a movie land for you.</p>`;
  const taste = (notes.taste || "").trim();
  $("taste").hidden = !taste;
  if (taste) $("taste-body").innerHTML = window.renderMarkdown(taste);
}

function render(data) {
  const seen = data.tiers.filter((tier) => tier.rating !== null);
  const toWatch = data.tiers.find((tier) => tier.rating === null) || { description: "", movies: [] };
  const total = seen.reduce((sum, tier) => sum + tier.movies.length, 0);
  $("counts").textContent = `${total} seen · ${toWatch.movies.length} to watch`;
  $("to-watch-description").textContent = toWatch.description;
  $("to-watch-list").replaceChildren(...toWatch.movies.map(buildMovie));
  const collapsed = loadCollapsed();
  $("tiers").replaceChildren(...seen.map((tier) => buildTier(tier, collapsed)));
  renderNotes(data.notes || {}, renderPicks(data.picks || []));
}

function filter() {
  // Searching opens every tier for the moment, so a match in a collapsed one still shows
  const wanted = $("search").value.trim().toLowerCase();
  document.querySelectorAll(".movie").forEach((item) => { item.hidden = !!wanted && !item.dataset.search.includes(wanted); });
  document.querySelectorAll(".tier").forEach((tier) => {
    tier.hidden = !!wanted && !tier.querySelector(".movie:not([hidden])");
    tier.classList.toggle("searching", !!wanted);
  });
}

async function init() {
  $("search").addEventListener("input", filter);
  const data = await fetch("/api/movies").then((r) => r.json()).catch(() => ({ error: "The hub server didn't answer." }));
  if (data.error) {
    $("error").textContent = data.error;
    $("error").hidden = false;
  }
  if (data.tiers) render(data);
}

init();
