// Local Chat front end: conversations, streaming replies from Ollama, per-chat system prompts.
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var SETTING_KEYS = ["temperature", "top_p", "repeat_penalty", "num_ctx", "num_predict"];
  var state = { settings: {}, personas: [], conversations: [], current: null, abort: null, renderPending: false, pending: [] };

  function api(method, path, body) {
    var options = { method: method, headers: { "Content-Type": "application/json" } };
    if (body !== undefined) options.body = JSON.stringify(body);
    return fetch(path, options).then(function (response) { return response.json(); });
  }

  function newId() {
    var bytes = new Uint8Array(12);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, function (b) { return b.toString(16).padStart(2, "0"); }).join("");
  }

  function setStatus(text, isError) {
    $("status").textContent = text || "";
    $("status").className = isError ? "error" : "";
  }

  // ---------- conversations ----------

  function blankConversation() {
    var now = Date.now();
    return { id: newId(), title: "New chat", model: $("model-select").value || state.settings.model,
             persona_id: state.settings.persona_id || "", system_prompt: state.settings.system_prompt,
             style: personaMode(personaById(state.settings.persona_id)), folder: "", messages: [], created: now, updated: now };
  }

  function newConversation() {
    state.current = blankConversation();
    updateRoleplayButton();
    renderPersonaSelect();
    renderList();
    renderMessages();
    $("input").focus();
  }

  function openConversation(id) {
    if (state.abort) return;
    api("GET", "/api/conversations/" + id).then(function (conversation) {
      if (conversation.error) { setStatus(conversation.error, true); return; }
      state.current = conversation;
      if (conversation.model) selectModel(conversation.model);
      updateRoleplayButton();
      renderPersonaSelect();
      renderList();
      renderMessages();
    });
  }

  function saveConversation() {
    var conversation = state.current;
    if (!conversation || conversation.messages.length === 0) return Promise.resolve();
    conversation.updated = Date.now();
    conversation.model = $("model-select").value;
    return api("PUT", "/api/conversations/" + conversation.id, conversation).then(refreshList);
  }

  function deleteConversation(id) {
    if (!confirm("Delete this conversation?")) return;
    api("DELETE", "/api/conversations/" + id).then(function () {
      if (state.current && state.current.id === id) newConversation();
      refreshList();
    });
  }

  function renameConversation(id) {
    api("GET", "/api/conversations/" + id).then(function (conversation) {
      var title = prompt("Rename conversation", conversation.title);
      if (!title) return;
      conversation.title = title.trim();
      delete conversation.needs_title;
      if (state.current && state.current.id === id) { state.current.title = conversation.title; delete state.current.needs_title; }
      api("PUT", "/api/conversations/" + id, conversation).then(refreshList);
    });
  }

  function refreshList() {
    return api("GET", "/api/conversations").then(function (list) {
      state.conversations = list;
      warnIfOldServer(list);
      renderList();
    });
  }

  // Sections need the updated server.py; an old one still running in its window leaves "folder" out of the list.
  function warnIfOldServer(list) {
    if (list.length && !("folder" in list[0])) setStatus("Restart the server (close its window, run start.bat) to finish the update.", true);
  }

  // ---------- sidebar sections ----------
  // Chats are sorted by hand into sections by dragging. A chat that was never sorted goes by its mode.
  var FOLDERS = [{ id: "philosophize", label: "Philosophize" }, { id: "roleplay", label: "Roleplay" }, { id: "xxx", label: "XXX" }];
  var FOLDER_STYLES = { philosophize: "philosopher", roleplay: "roleplay", xxx: "roleplay" };

  function folderOf(summary) {
    var known = FOLDERS.some(function (f) { return f.id === summary.folder; });
    if (known) return summary.folder;
    return summary.style === "philosopher" ? "philosophize" : "roleplay";
  }

  function loadCollapsed() {
    try { return JSON.parse(localStorage.getItem("local-chat-collapsed") || "{}"); } catch (e) { return {}; }
  }

  function saveCollapsed(collapsed) {
    try { localStorage.setItem("local-chat-collapsed", JSON.stringify(collapsed)); } catch (e) { }
  }

  function toggleFolder(folderId) {
    var collapsed = loadCollapsed();
    collapsed[folderId] = !collapsed[folderId];
    saveCollapsed(collapsed);
    renderList();
  }

  function renderList() {
    var nav = $("conversation-list");
    var collapsed = loadCollapsed();
    nav.innerHTML = "";
    FOLDERS.forEach(function (folder) { nav.appendChild(buildFolder(folder, !!collapsed[folder.id])); });
  }

  function buildFolder(folder, isCollapsed) {
    var summaries = currentSummaries().filter(function (summary) { return folderOf(summary) === folder.id; });
    var section = document.createElement("div");
    section.className = "folder" + (isCollapsed ? " collapsed" : "");
    section.innerHTML = '<div class="folder-head"><button class="toggle"></button><button class="add" title="New chat here">+</button></div><div class="folder-items"></div>';
    section.querySelector(".toggle").textContent = (isCollapsed ? "▸ " : "▾ ") + folder.label + " (" + summaries.length + ")";
    section.querySelector(".toggle").onclick = function () { toggleFolder(folder.id); };
    section.querySelector(".add").onclick = function () { newConversationIn(folder.id); };
    var items = section.querySelector(".folder-items");
    summaries.forEach(function (summary) { items.appendChild(buildConversationRow(summary)); });
    if (summaries.length === 0) items.innerHTML = '<div class="folder-empty">Drag chats here</div>';
    section.dataset.folder = folder.id;
    return section;
  }

  // A new chat started from a section's + shows up there even before its first save.
  function currentSummaries() {
    var list = state.conversations.slice();
    var current = state.current;
    if (current && current.folder && !list.some(function (s) { return s.id === current.id; })) {
      list.unshift({ id: current.id, title: current.title, persona_id: current.persona_id, folder: current.folder, style: styleOf(current), unsaved: true });
    }
    return list;
  }

  // ---------- dragging chats between sections ----------
  // Plain pointer events: press on a chat, move a few pixels to pick it up, release over a section to drop it.
  var DRAG_THRESHOLD = 5;
  var drag = null;

  function startDrag(event, row, summary) {
    if (event.button !== 0 || summary.unsaved || event.target.closest("button")) return;
    drag = { id: summary.id, row: row, x: event.clientX, y: event.clientY, ghost: null };
    document.addEventListener("pointermove", moveDrag);
    document.addEventListener("pointerup", endDrag);
    document.addEventListener("pointercancel", cancelDrag);
  }

  function moveDrag(event) {
    if (!drag) return;
    if (!drag.ghost && Math.abs(event.clientX - drag.x) + Math.abs(event.clientY - drag.y) < DRAG_THRESHOLD) return;
    if (!drag.ghost) liftRow();
    event.preventDefault();
    drag.ghost.style.left = (event.clientX + 12) + "px";
    drag.ghost.style.top = (event.clientY + 6) + "px";
    highlightFolder(folderAt(event.clientX, event.clientY));
  }

  function liftRow() {
    drag.ghost = drag.row.cloneNode(true);
    drag.ghost.className = "conversation drag-ghost";
    document.body.appendChild(drag.ghost);
    drag.row.classList.add("dragging");
    document.body.classList.add("is-dragging");
  }

  function folderAt(x, y) {
    var element = document.elementFromPoint(x, y);
    return element ? element.closest(".folder") : null;
  }

  function highlightFolder(target) {
    Array.prototype.forEach.call(document.querySelectorAll(".folder"), function (folder) {
      folder.classList.toggle("drop-target", folder === target);
    });
  }

  function endDrag(event) {
    if (!drag) return;
    var lifted = !!drag.ghost;
    var target = lifted ? folderAt(event.clientX, event.clientY) : null;
    var id = drag.id;
    cancelDrag();
    if (lifted) suppressNextClick();
    if (target) moveConversation(id, target.dataset.folder);
  }

  function cancelDrag() {
    if (drag && drag.ghost) drag.ghost.remove();
    if (drag) drag.row.classList.remove("dragging");
    drag = null;
    highlightFolder(null);
    document.body.classList.remove("is-dragging");
    document.removeEventListener("pointermove", moveDrag);
    document.removeEventListener("pointerup", endDrag);
    document.removeEventListener("pointercancel", cancelDrag);
  }

  // Releasing a dragged chat also fires a click on it; that click shouldn't open the chat.
  function suppressNextClick() {
    var swallow = function (event) { event.stopPropagation(); event.preventDefault(); };
    document.addEventListener("click", swallow, true);
    setTimeout(function () { document.removeEventListener("click", swallow, true); }, 0);
  }

  function moveConversation(id, folderId) {
    if (!id) return;
    if (state.current && state.current.id === id) state.current.folder = folderId;
    var summary = state.conversations.filter(function (s) { return s.id === id; })[0];
    if (!summary) { renderList(); return; }
    summary.folder = folderId;
    renderList();
    api("GET", "/api/conversations/" + id).then(function (conversation) {
      if (conversation.error) return;
      conversation.folder = folderId;
      return api("PUT", "/api/conversations/" + id, conversation);
    }).then(refreshList);
  }

  function newConversationIn(folderId) {
    if (state.abort) return;
    newConversation();
    state.current.folder = folderId;
    if (!state.current.persona_id) setStyle(state.current, FOLDER_STYLES[folderId]);
    updateRoleplayButton();
    renderList();
  }

  function buildConversationRow(summary) {
    var row = document.createElement("div");
    row.className = "conversation" + (state.current && state.current.id === summary.id ? " active" : "");
    row.addEventListener("pointerdown", function (event) { startDrag(event, row, summary); });
    row.innerHTML = '<span class="title"></span><button title="Rename">&#9998;</button><button title="Delete">&#10005;</button>';
    row.querySelector(".title").textContent = summary.title;
    addPersonaTag(row.querySelector(".title"), summary.persona_id);
    row.querySelector(".title").onclick = function () { openConversation(summary.id); };
    row.querySelectorAll("button")[0].onclick = function () { renameConversation(summary.id); };
    row.querySelectorAll("button")[1].onclick = function () { deleteConversation(summary.id); };
    if (summary.unsaved) disableRow(row);
    return row;
  }

  function disableRow(row) {
    row.querySelector(".title").onclick = null;
    Array.prototype.forEach.call(row.querySelectorAll("button"), function (button) { button.hidden = true; });
  }

  // Chats with a personality are listed as "[Name] Title"; the name follows the personality if it is renamed.
  function addPersonaTag(title, personaId) {
    var persona = personaById(personaId);
    if (!persona) return;
    var tag = document.createElement("span");
    tag.className = "persona-tag";
    tag.textContent = "[" + persona.name + "] ";
    title.insertBefore(tag, title.firstChild);
  }

  // ---------- message rendering ----------

  function renderMessages() {
    var container = $("messages");
    container.innerHTML = "";
    var messages = state.current ? state.current.messages : [];
    if (messages.length === 0) {
      container.innerHTML = '<div class="empty"><h1>What shall we write?</h1><p>Your words stay on this machine.</p></div>';
      return;
    }
    messages.forEach(function (message, index) { container.appendChild(buildMessageElement(message, index)); });
    container.scrollTop = container.scrollHeight;
  }

  function buildMessageElement(message, index) {
    var element = document.createElement("div");
    element.className = "message " + message.role;
    element.dataset.index = index;
    element.innerHTML = '<div class="role"></div><div class="body"></div><div class="tools"></div>';
    element.querySelector(".role").textContent = message.role === "user" ? "You" : messageLabel(message);
    fillMessageBody(element.querySelector(".body"), message, false);
    addMessageTools(element.querySelector(".tools"), message, index);
    return element;
  }

  function fillMessageBody(body, message, streaming) {
    if (message.role === "user") { body.textContent = message.content; return; }
    var html = "";
    if (message.thinking) html += '<details class="thinking"><summary>Thinking</summary>' + escapeHtml(message.thinking) + "</details>";
    html += renderMarkdown(message.content);
    if (message.error) html += '<p class="error">' + escapeHtml(message.error) + "</p>";
    body.innerHTML = html;
    body.classList.toggle("cursor", streaming);
  }

  function addMessageTools(tools, message, index) {
    addTool(tools, "Copy", function () { navigator.clipboard.writeText(message.content); });
    if (message.role === "user") addTool(tools, "Edit", function () { editFrom(index); });
    addTool(tools, "Delete", function () { deleteMessage(index); });
    if (message.stats) {
      var stats = document.createElement("span");
      stats.className = "stats";
      stats.textContent = message.stats;
      tools.appendChild(stats);
    }
  }

  function addTool(tools, label, handler) {
    var button = document.createElement("button");
    button.textContent = label;
    button.onclick = handler;
    tools.appendChild(button);
  }

  function editFrom(index) {
    if (state.abort) return;
    $("input").value = state.current.messages[index].content;
    state.current.messages = state.current.messages.slice(0, index);
    renderMessages();
    autosize();
    $("input").focus();
  }

  function deleteMessage(index) {
    if (state.abort) return;
    state.current.messages.splice(index, 1);
    renderMessages();
    saveConversation();
  }

  function isNearBottom() {
    var container = $("messages");
    return container.scrollHeight - container.scrollTop - container.clientHeight < 120;
  }

  function scheduleStreamRender(message) {
    if (state.renderPending) return;
    state.renderPending = true;
    requestAnimationFrame(function () {
      state.renderPending = false;
      var elements = $("messages").querySelectorAll(".message.assistant");
      var last = elements[elements.length - 1];
      if (!last) return;
      var stick = isNearBottom();
      fillMessageBody(last.querySelector(".body"), message, !!state.abort);
      if (stick) $("messages").scrollTop = $("messages").scrollHeight;
    });
  }

  // ---------- generation ----------

  // ---------- roleplay mode ----------
  // Turn-based play: the model answers one beat at a time and hands the choice back to the user.
  var ROLEPLAY_PATTERN = /role[\s-]?play/i;
  var FINAL_SCENE_PATTERN = /final scene|the finale|the ending/i;
  // "full scene", "tons of detail", "a page of detail", "slow it down"... asks for one long, detailed turn without ending the story.
  var DETAIL_PATTERN = /full scene|in full|(tons|lots|loads) (and tons )?of\b.{0,40}detail|sensory detail|more detail|in detail|detailed|a (full )?page|long(er)? (scene|reply|turn)|slow (it )?down|don't rush|every (sensation|detail)/i;
  var ROLEPLAY_TURN_TOKENS = 900;
  var ROLEPLAY_DETAIL_TOKENS = 2400;
  var ROLEPLAY_RULES = "ROLEPLAY MODE. This is an interactive, turn-based roleplay game with the user.\n" +
    "- The user decides their own character's actions, words, and choices. Never invent new actions, dialogue, or decisions for that character.\n" +
    "- Do describe, in rich detail, what the user's character physically experiences while doing what the user wrote: sensations, sights, sounds, smells, tastes, and how their body feels.\n" +
    "- Respond to what the user just did: the immediate result, how the world and other characters react, and the next few moments. Then stop.\n" +
    "- Take one moment at a time and describe it fully. Never skip ahead, summarize, resolve the scene, or wrap up the encounter.\n" +
    "- End your turn at an open moment that invites the user's next choice. Do not list options unless asked.\n" +
    "- Write about a page per turn (300 to 500 words): vivid, concrete, and immersive. Never answer with just a few lines.\n" +
    "- Text in [square brackets] is an out-of-character direction from the user. Follow it exactly, including any request for more length or detail.\n" +
    "- When the user asks for a full or detailed scene, write a long passage (800 words or more) that stays in the moment, without ending the story.\n" +
    "- Only when the user asks for the final scene or ending may you bring things to a close.";
  var ROLEPLAY_TURN_REMINDER = "\n\n(Roleplay: reply with your next turn, about a page of vivid detail. Do not invent new actions or words for my character, and do not resolve the scene. Stop where I choose what happens next.)";
  var ROLEPLAY_DETAIL_REMINDER = "\n\n(Roleplay: I asked for a full, detailed scene. Write a long turn of 800 words or more. Slow down and describe it moment by moment: every sensation, sound, and physical detail, for both characters. Do not summarize, skip ahead, or end the story. Do not invent new decisions for my character.)";
  var ROLEPLAY_FINAL_REMINDER = "\n\n(Roleplay: this is the final scene. Write it out in full and bring the story to a close.)";

  // ---------- chat mode ----------
  // Plain text messaging, like a chat log: no narration, no actions, short lines in the character's own spelling.
  var CHAT_TURN_TOKENS = 300;
  var CHAT_RULES = "CHAT MODE. This is a live text chat, like IRC or a messaging app.\n" +
    "- Reply only with the words you would type into the chat. No narration, no actions, no *asterisks*, no descriptions of yourself or the room.\n" +
    "- Keep it short: usually one to three lines, the way people actually type in chat.\n" +
    "- Match the spelling, capitalization, punctuation, slang, and emoji habits of the example messages.\n" +
    "- Do not write the user's lines, and do not prefix your reply with your name.";
  var CHAT_TURN_REMINDER = "\n\n(Chat: reply with just your next chat message, in your own typing style. No narration or actions.)";
  var STYLE_LABELS = { "": "Mode: off", roleplay: "Mode: Roleplay", philosopher: "Mode: Philosopher", chat: "Mode: Chat" };
  var STYLE_ORDER = ["", "roleplay", "philosopher", "chat"];

  // ---------- philosopher mode ----------
  // A scene that is mostly conversation: about two-thirds spoken words, one-third action and narration.
  var PHILOSOPHER_RULES = "PHILOSOPHER MODE. This is a turn-based conversation between characters, set in a scene.\n" +
    "- About two-thirds of each reply is spoken dialogue: real conversation with ideas, questions, opinions, stories, and back-and-forth.\n" +
    "- About one-third is action and narration in *asterisks*: gestures, expressions, the setting, small physical moments between the lines.\n" +
    "- Think out loud and take ideas seriously. Agree, disagree, wonder, tease, and follow tangents the way a real person would.\n" +
    "- The user decides their own character's actions, words, and choices. Never invent new ones for that character.\n" +
    "- Respond to what the user just said or did, then stop at a natural point for them to answer.\n" +
    "- Write about a page per turn (250 to 450 words). Never answer with just a line or two.\n" +
    "- Text in [square brackets] is an out-of-character direction from the user. Follow it exactly, including any request for more length or detail.";
  var PHILOSOPHER_TURN_REMINDER = "\n\n(Philosopher: reply with your next turn, about a page, roughly two-thirds spoken conversation and one-third action and narration. Do not speak or act for my character.)";
  var PHILOSOPHER_DETAIL_REMINDER = "\n\n(Philosopher: I asked for a full, detailed turn. Write 700 words or more, still roughly two-thirds spoken conversation and one-third action and narration. Do not speak or act for my character.)";

  // Older chats stored roleplay as true/false.
  function styleOf(conversation) {
    if (!conversation) return "";
    if (conversation.style !== undefined) return conversation.style;
    return conversation.roleplay ? "roleplay" : "";
  }

  function setStyle(conversation, style) {
    conversation.style = style;
    delete conversation.roleplay;
  }

  function personaMode(persona) {
    return persona ? (persona.mode || "roleplay") : "";
  }

  function updateRoleplayButton() {
    var style = styleOf(state.current);
    $("toggle-roleplay").textContent = STYLE_LABELS[style];
    $("toggle-roleplay").classList.toggle("active", style !== "");
  }

  function toggleRoleplay() {
    if (!state.current) state.current = blankConversation();
    var next = STYLE_ORDER[(STYLE_ORDER.indexOf(styleOf(state.current)) + 1) % STYLE_ORDER.length];
    setStyle(state.current, next);
    updateRoleplayButton();
    saveConversation();
  }

  function examplesBlock(persona) {
    if (!persona || !persona.examples || persona.examples.length === 0) return "";
    return "Examples of how " + persona.name + " actually writes in chat. Match the voice, length, and spelling; never copy these lines verbatim.\n\n" +
      persona.examples.join("\n\n");
  }

  function personaIntro(persona) {
    if (!persona) return "";
    return persona.prompt.trim() || "You are " + persona.name + ". Stay in character as " + persona.name + ".";
  }

  // Personality profile and examples first, then the chat's own system prompt, then the mode's rules.
  function systemPromptFor(conversation) {
    var persona = personaById(conversation.persona_id);
    var style = styleOf(conversation);
    var parts = [personaIntro(persona), examplesBlock(persona), conversation.system_prompt || ""];
    if (style === "roleplay") parts.push(ROLEPLAY_RULES);
    if (style === "philosopher") parts.push(PHILOSOPHER_RULES);
    if (style === "chat") parts.push(CHAT_RULES);
    return parts.map(function (part) { return part.trim(); }).filter(Boolean).join("\n\n");
  }

  function applyPhilosopherTurn(request) {
    var last = request.messages[request.messages.length - 1];
    if (!last || last.role !== "user") return;
    var detailed = DETAIL_PATTERN.test(last.content);
    var tokens = detailed ? ROLEPLAY_DETAIL_TOKENS : ROLEPLAY_TURN_TOKENS;
    last.content += detailed ? PHILOSOPHER_DETAIL_REMINDER : PHILOSOPHER_TURN_REMINDER;
    if (request.num_predict < 0 || request.num_predict > tokens) request.num_predict = tokens;
  }

  function applyChatTurn(request) {
    var last = request.messages[request.messages.length - 1];
    if (!last || last.role !== "user") return;
    last.content += CHAT_TURN_REMINDER;
    if (request.num_predict < 0 || request.num_predict > CHAT_TURN_TOKENS) request.num_predict = CHAT_TURN_TOKENS;
  }

  // Small models drift from system prompts, so the turn rule is repeated on the latest user message (sent, never stored).
  function applyRoleplayTurn(request) {
    var last = request.messages[request.messages.length - 1];
    if (!last || last.role !== "user") return;
    var turn = roleplayTurnKind(last.content);
    last.content += turn.reminder;
    if (turn.tokens > 0 && (request.num_predict < 0 || request.num_predict > turn.tokens)) request.num_predict = turn.tokens;
  }

  // Final scene: no cap, close the story. Detailed: long cap, stay in the moment. Otherwise: about a page.
  function roleplayTurnKind(text) {
    if (FINAL_SCENE_PATTERN.test(text)) return { reminder: ROLEPLAY_FINAL_REMINDER, tokens: 0 };
    if (DETAIL_PATTERN.test(text)) return { reminder: ROLEPLAY_DETAIL_REMINDER, tokens: ROLEPLAY_DETAIL_TOKENS };
    return { reminder: ROLEPLAY_TURN_REMINDER, tokens: ROLEPLAY_TURN_TOKENS };
  }

  function buildRequest() {
    var conversation = state.current;
    var messages = [];
    var systemPrompt = systemPromptFor(conversation);
    if (systemPrompt) messages.push({ role: "system", content: systemPrompt });
    conversation.messages.forEach(function (m) {
      if (m.content || m.role === "user") messages.push({ role: m.role, content: m.content });
    });
    var request = { model: $("model-select").value, messages: messages };
    SETTING_KEYS.forEach(function (key) { request[key] = Number(state.settings[key]); });
    if (styleOf(conversation) === "roleplay") applyRoleplayTurn(request);
    if (styleOf(conversation) === "philosopher") applyPhilosopherTurn(request);
    if (styleOf(conversation) === "chat") applyChatTurn(request);
    return request;
  }

  function sendMessage(text) {
    if (state.abort || !text.trim()) return;
    if (!$("model-select").value) { setStatus("Pick a model first (ollama pull <model>).", true); return; }
    if (!state.current) state.current = blankConversation();
    if (state.current.messages.length === 0) {
      state.current.title = text.trim().slice(0, 60);
      state.current.needs_title = true;
    }
    if (ROLEPLAY_PATTERN.test(text) && styleOf(state.current) === "") {
      setStyle(state.current, "roleplay");
      updateRoleplayButton();
    }
    state.current.messages.push({ role: "user", content: text });
    $("input").value = "";
    autosize();
    generate();
  }

  function generate() {
    var request = buildRequest();
    var reply = { role: "assistant", content: "", thinking: "", model: request.model, persona: personaName(state.current) };
    state.current.messages.push(reply);
    state.abort = new AbortController();
    setBusy(true);
    renderMessages();
    fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
                         body: JSON.stringify(request), signal: state.abort.signal })
      .then(function (response) { return readStream(response, reply); })
      .catch(function (error) { if (error.name !== "AbortError") reply.error = String(error); })
      .then(function () { finishGeneration(reply); });
  }

  function readStream(response, reply) {
    if (!response.ok) return response.json().then(function (body) { reply.error = body.error || ("HTTP " + response.status); });
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    function pump() {
      return reader.read().then(function (chunk) {
        if (chunk.done) return;
        buffer += decoder.decode(chunk.value, { stream: true });
        var lines = buffer.split("\n");
        buffer = lines.pop();
        lines.forEach(function (line) { applyStreamLine(line, reply); });
        scheduleStreamRender(reply);
        return pump();
      });
    }
    return pump();
  }

  function applyStreamLine(line, reply) {
    if (!line.trim()) return;
    var data;
    try { data = JSON.parse(line); } catch (e) { return; }
    if (data.error) { reply.error = data.error; return; }
    if (data.message) {
      reply.content += data.message.content || "";
      reply.thinking += data.message.thinking || "";
    }
    if (data.done && data.eval_count) {
      var seconds = (data.eval_duration || 1) / 1e9;
      reply.stats = data.eval_count + " tokens · " + (data.eval_count / seconds).toFixed(1) + " tok/s";
    }
  }

  function finishGeneration(reply) {
    state.abort = null;
    if (!reply.thinking) delete reply.thinking;
    setBusy(false);
    renderMessages();
    if (!reply.error) saveConversation().then(function () { generateTitle(state.current); });
  }

  // After the first reply, ask the model for a short title. Skipped if the user already renamed the chat.
  function generateTitle(conversation) {
    if (!conversation || !conversation.needs_title || conversation.messages.length < 2) return;
    delete conversation.needs_title;
    var body = { model: $("model-select").value, user: conversation.messages[0].content, assistant: conversation.messages[1].content };
    api("POST", "/api/title", body).then(function (result) {
      if (result.title) conversation.title = result.title;
      return api("PUT", "/api/conversations/" + conversation.id, conversation);
    }).then(refreshList);
  }

  function stopGeneration() {
    if (state.abort) state.abort.abort();
  }

  function regenerate() {
    var messages = state.current ? state.current.messages : [];
    if (state.abort || messages.length === 0) return;
    if (messages[messages.length - 1].role === "assistant") messages.pop();
    if (messages.length === 0) return;
    generate();
  }

  function setBusy(busy) {
    $("send").hidden = busy;
    $("stop").hidden = !busy;
    $("regenerate").disabled = busy;
    $("continue").disabled = busy;
    setStatus(busy ? "Writing…" : "");
  }

  // ---------- personalities ----------

  function personaById(id) {
    return state.personas.filter(function (p) { return p.id === id; })[0] || null;
  }

  function personaName(conversation) {
    var persona = conversation ? personaById(conversation.persona_id) : null;
    return persona ? persona.name : "";
  }

  function messageLabel(message) {
    var model = message.model || state.current.model || "Assistant";
    return message.persona ? message.persona + " · " + model : model;
  }

  function fillPersonaOptions(select, includeNone) {
    select.innerHTML = "";
    if (includeNone) select.appendChild(new Option("No personality", ""));
    state.personas.forEach(function (p) { select.appendChild(new Option(p.name, p.id)); });
  }

  function renderPersonaSelect() {
    fillPersonaOptions($("persona-select"), true);
    $("persona-select").value = (state.current && personaById(state.current.persona_id)) ? state.current.persona_id : "";
  }

  function loadPersonas() {
    return api("GET", "/api/personas").then(function (personas) { state.personas = personas || []; });
  }

  function onPersonaChange() {
    if (!state.current) state.current = blankConversation();
    state.current.persona_id = $("persona-select").value;
    state.settings.persona_id = state.current.persona_id;
    if (state.current.persona_id) setStyle(state.current, personaMode(personaById(state.current.persona_id)));
    updateRoleplayButton();
    api("PUT", "/api/settings", { persona_id: state.current.persona_id });
    saveConversation();
  }

  function fillPersonaEditor(id) {
    var persona = personaById(id);
    $("persona-edit-select").value = persona ? persona.id : "";
    $("persona-name").value = persona ? persona.name : "";
    $("persona-prompt").value = persona ? persona.prompt : "";
    $("persona-mode").value = personaMode(persona) || "roleplay";
    $("persona-speakers").value = persona && persona.speakers ? persona.speakers.join(", ") : "";
    $("train-status").textContent = "";
    $("training").disabled = !persona;
    renderTraining(persona);
    loadSpeakers(persona);
  }

  function openPersonas() {
    state.pending = [];
    $("material-preview").hidden = true;
    fillPersonaOptions($("persona-edit-select"), false);
    fillPersonaEditor(state.personas.length ? state.personas[0].id : "");
    $("personas-dialog").showModal();
  }

  function newPersona() {
    var persona = { id: newId(), name: "New personality", prompt: "", mode: "chat" };
    state.personas.push(persona);
    fillPersonaOptions($("persona-edit-select"), false);
    fillPersonaEditor(persona.id);
    $("persona-name").select();
  }

  function deletePersona() {
    var id = $("persona-edit-select").value;
    if (!id || !confirm("Delete this personality? Chats using it will fall back to no personality.")) return;
    state.personas = state.personas.filter(function (p) { return p.id !== id; });
    savePersonas().then(function () { openPersonas(); });
  }

  // Copies the editor fields into the persona and saves everything; resolves with the saved persona.
  function storePersonaFields() {
    var persona = personaById($("persona-edit-select").value);
    if (!persona) return Promise.resolve(null);
    persona.name = $("persona-name").value.trim() || "Unnamed";
    persona.prompt = $("persona-prompt").value;
    persona.mode = $("persona-mode").value;
    persona.speakers = speakerList();
    return savePersonas().then(function () { return personaById(persona.id); });
  }

  function savePersona() {
    storePersonaFields().then(function (persona) {
      if (!persona) return;
      fillPersonaOptions($("persona-edit-select"), false);
      fillPersonaEditor(persona.id);
      setStatus("Saved " + persona.name);
    });
  }

  // ---------- training material ----------
  // "Prepare" picks real example lines from the material and shows them to the model; it does not change the model's weights.
  var QUALITY_STEPS = ["None", "Thin", "Okay", "Good", "Rich"];

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1048576).toFixed(1) + " MB";
  }

  function speakerList() {
    return $("persona-speakers").value.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
  }

  // Runs a material/training request against the saved persona and swaps in the persona the server returns.
  function personaRequest(buildFetch, busyText) {
    $("train-status").textContent = busyText;
    return storePersonaFields().then(function (persona) {
      if (!persona) return null;
      return buildFetch(persona).then(function (response) { return response.json(); }).then(function (updated) {
        if (updated.error) { $("train-status").textContent = updated.error; return null; }
        state.personas = state.personas.map(function (p) { return p.id === updated.id ? updated : p; });
        fillPersonaOptions($("persona-edit-select"), false);
        fillPersonaEditor(updated.id);
        return updated;
      });
    });
  }

  function uploadMaterial(name, text) {
    return personaRequest(function (persona) {
      return fetch("/api/personas/" + persona.id + "/materials?name=" + encodeURIComponent(name),
                   { method: "POST", headers: { "Content-Type": "text/plain; charset=utf-8" }, body: text });
    }, "Adding " + name + "…");
  }

  // New material waits in a preview (counts, speakers, optional summary) until it is added or skipped.
  function addMaterialFiles() {
    var files = Array.prototype.slice.call($("material-files").files);
    $("material-files").value = "";
    Promise.all(files.map(function (file) {
      return file.text().then(function (text) { return { name: file.name, text: text }; });
    })).then(function (items) { queueMaterial(items); });
  }

  function addPastedMaterial() {
    var text = $("material-paste").value;
    if (!text.trim()) return;
    queueMaterial([{ name: $("material-paste-name").value.trim() || "Pasted text", text: text }]);
    $("material-paste").value = "";
    $("material-paste-name").value = "";
    $("material-paste-box").hidden = true;
  }

  function queueMaterial(items) {
    var wasEmpty = state.pending.length === 0;
    state.pending = state.pending.concat(items);
    if (wasEmpty) showPreview();
    else updatePreviewCount();
  }

  function inspectMaterial(item, withSummary) {
    var query = withSummary ? "?summary=1&model=" + encodeURIComponent($("model-select").value) : "";
    return fetch("/api/materials/inspect" + query, { method: "POST", headers: { "Content-Type": "text/plain; charset=utf-8" }, body: item.text })
      .then(function (response) { return response.json(); });
  }

  function showPreview() {
    var item = state.pending[0];
    $("material-preview").hidden = !item;
    if (!item) return;
    $("preview-name").textContent = item.name;
    $("preview-meta").textContent = "Reading…";
    $("preview-speakers").textContent = "";
    $("preview-summary").textContent = "";
    $("preview-summarize").disabled = false;
    updatePreviewCount();
    inspectMaterial(item, false).then(function (info) { if (state.pending[0] === item) fillPreview(item, info); });
  }

  function fillPreview(item, info) {
    if (info.error) { $("preview-meta").textContent = info.error; return; }
    item.lines = info.lines;
    $("preview-meta").textContent = formatBytes(info.bytes) + " · " + info.lines.toLocaleString() + " chat lines" +
      (info.lines === 0 ? " (no lines like  <nick> text  or  Name: text  were found)" : "") + previewCountText();
    $("preview-speakers").textContent = info.speakers.length ? "Most active: " + info.speakers.slice(0, 8).map(function (s) {
      return s.name + " (" + s.count.toLocaleString() + ")";
    }).join(", ") : "";
    $("preview-summarize").disabled = info.lines === 0;
  }

  function previewCountText() {
    return state.pending.length > 1 ? " · 1 of " + state.pending.length + " waiting" : "";
  }

  function updatePreviewCount() {
    var meta = $("preview-meta").textContent.replace(/ · 1 of \d+ waiting$/, "");
    if (meta && meta !== "Reading…") $("preview-meta").textContent = meta + previewCountText();
  }

  function summarizePreview() {
    var item = state.pending[0];
    if (!item) return;
    $("preview-summarize").disabled = true;
    $("preview-summary").textContent = "Summarizing with " + $("model-select").value + "… (a big log can take a minute)";
    inspectMaterial(item, true).then(function (info) {
      if (state.pending[0] !== item) return;
      $("preview-summary").textContent = info.summary || info.error || "The model returned nothing.";
      $("preview-summarize").disabled = false;
    });
  }

  function acceptPreview() {
    var item = state.pending[0];
    if (!item) return;
    $("preview-add").disabled = true;
    uploadMaterial(item.name, item.text).then(function (updated) {
      $("preview-add").disabled = false;
      if (updated) nextPreview();
    });
  }

  function nextPreview() {
    state.pending.shift();
    showPreview();
  }

  function removeMaterial(material) {
    if (!confirm("Remove " + material.name + " from this personality's material?")) return;
    personaRequest(function (persona) {
      return fetch("/api/personas/" + persona.id + "/materials/" + material.id, { method: "DELETE" });
    }, "Removing…");
  }

  function trainPersona() {
    if (speakerList().length === 0) { $("train-status").textContent = "Pick whose voice to learn first."; return; }
    personaRequest(function (persona) {
      return fetch("/api/personas/" + persona.id + "/train", { method: "POST", headers: { "Content-Type": "application/json" },
                                                               body: JSON.stringify({ speakers: speakerList() }) });
    }, "Preparing…").then(function (updated) {
      if (updated) $("train-status").textContent = "Prepared.";
    });
  }

  function renderMaterials(persona) {
    var list = $("material-list");
    list.innerHTML = "";
    var materials = persona && persona.materials ? persona.materials : [];
    if (materials.length === 0) list.innerHTML = '<div class="material empty-note">No material yet. Add chat logs below.</div>';
    materials.forEach(function (material) {
      var row = document.createElement("div");
      row.className = "material";
      row.innerHTML = '<span class="name"></span><span class="meta"></span><button type="button" class="ghost">Remove</button>';
      row.querySelector(".name").textContent = material.name;
      row.querySelector(".meta").textContent = formatBytes(material.bytes) + " · " + material.lines.toLocaleString() + " chat lines";
      row.querySelector("button").onclick = function () { removeMaterial(material); };
      list.appendChild(row);
    });
  }

  function loadSpeakers(persona) {
    $("speaker-chips").innerHTML = "";
    if (!persona || !persona.materials || persona.materials.length === 0) return;
    api("GET", "/api/personas/" + persona.id + "/speakers").then(function (speakers) {
      if ($("persona-edit-select").value !== persona.id) return;
      speakers.forEach(function (speaker) { $("speaker-chips").appendChild(buildSpeakerChip(speaker)); });
    });
  }

  function buildSpeakerChip(speaker) {
    var chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip ghost";
    chip.dataset.name = speaker.name;
    chip.textContent = speaker.name + " (" + speaker.count.toLocaleString() + ")";
    chip.onclick = function () { toggleSpeaker(speaker.name); };
    markChip(chip);
    return chip;
  }

  function markChip(chip) {
    var chosen = speakerList().map(function (s) { return s.toLowerCase(); });
    chip.classList.toggle("on", chosen.indexOf(chip.dataset.name.toLowerCase()) >= 0);
  }

  function toggleSpeaker(name) {
    var speakers = speakerList();
    var at = speakers.map(function (s) { return s.toLowerCase(); }).indexOf(name.toLowerCase());
    if (at >= 0) speakers.splice(at, 1); else speakers.push(name);
    $("persona-speakers").value = speakers.join(", ");
    refreshChips();
  }

  function refreshChips() {
    Array.prototype.forEach.call($("speaker-chips").children, markChip);
  }

  function renderTraining(persona) {
    renderMaterials(persona);
    var training = persona ? persona.training : null;
    var examples = persona && persona.examples ? persona.examples : [];
    $("training-meter").innerHTML = "";
    $("training-meter").appendChild(buildMeter(persona, training));
    $("training-examples").hidden = examples.length === 0;
    $("training-examples-list").textContent = examples.join("\n\n");
  }

  function buildMeter(persona, training) {
    var meter = document.createElement("div");
    meter.className = "meter";
    if (!training) {
      meter.innerHTML = '<span class="advice"></span>';
      var hasMaterial = persona && persona.materials && persona.materials.length;
      meter.querySelector(".advice").textContent = hasMaterial ? "Not prepared yet. Pick whose voice, then Prepare." : "Not prepared. Add material, pick whose voice, then Prepare.";
      return meter;
    }
    var step = Math.max(0, QUALITY_STEPS.indexOf(training.level));
    meter.innerHTML = '<div><span class="level"></span> <span class="advice"></span></div><div class="bar"><div class="fill"></div></div><div class="detail hint"></div>';
    meter.querySelector(".level").textContent = "Example pool: " + training.level;
    meter.querySelector(".advice").textContent = training.advice;
    meter.querySelector(".fill").style.width = (step / (QUALITY_STEPS.length - 1) * 100) + "%";
    meter.querySelector(".detail").textContent = trainingDetail(training);
    if (training.stale) meter.appendChild(staleNote());
    return meter;
  }

  function trainingDetail(training) {
    return training.usable_lines.toLocaleString() + " usable lines in their voice, out of " + training.total_lines.toLocaleString() +
      " chat lines across " + training.materials + " file" + (training.materials === 1 ? "" : "s") + ". " +
      training.examples + " example" + (training.examples === 1 ? "" : "s") + " in use.";
  }

  function staleNote() {
    var note = document.createElement("div");
    note.className = "stale";
    note.textContent = "Material changed since this was prepared. Prepare again to use it.";
    return note;
  }

  function savePersonas() {
    return api("PUT", "/api/personas", state.personas).then(function (personas) {
      state.personas = personas;
      renderPersonaSelect();
      renderList();
    });
  }

  // ---------- models, settings, dialogs ----------

  function selectModel(name) {
    var select = $("model-select");
    if (!Array.prototype.some.call(select.options, function (o) { return o.value === name; })) {
      select.appendChild(new Option(name + " (not installed)", name));
    }
    select.value = name;
  }

  function loadModels() {
    return api("GET", "/api/models").then(function (result) {
      var select = $("model-select");
      select.innerHTML = "";
      result.models.forEach(function (name) { select.appendChild(new Option(name, name)); });
      if (result.error) setStatus(result.error, true);
      else if (result.models.length === 0) setStatus("No models installed. Run: ollama pull <model>", true);
      if (state.settings.model) selectModel(state.settings.model);
    });
  }

  function openSettings() {
    $("set-system").value = state.settings.system_prompt || "";
    SETTING_KEYS.forEach(function (key) { $("set-" + key).value = state.settings[key]; });
    $("settings-dialog").showModal();
  }

  function saveSettings() {
    var update = { system_prompt: $("set-system").value, model: $("model-select").value };
    SETTING_KEYS.forEach(function (key) { update[key] = Number($("set-" + key).value); });
    api("PUT", "/api/settings", update).then(function (settings) { state.settings = settings; });
  }

  function openSystemPrompt() {
    if (!state.current) state.current = blankConversation();
    $("chat-system").value = state.current.system_prompt || "";
    $("system-dialog").showModal();
  }

  function saveSystemPrompt() {
    state.current.system_prompt = $("chat-system").value;
    saveConversation();
  }

  function autosize() {
    var input = $("input");
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, window.innerHeight * 0.4) + "px";
  }

  function onModelChange() {
    state.settings.model = $("model-select").value;
    api("PUT", "/api/settings", { model: state.settings.model });
    if (state.current) state.current.model = state.settings.model;
  }

  function onInputKey(event) {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      sendMessage($("input").value);
    }
  }

  function bindEvents() {
    $("new-chat").onclick = newConversation;
    $("send").onclick = function () { sendMessage($("input").value); };
    $("stop").onclick = stopGeneration;
    $("regenerate").onclick = regenerate;
    $("continue").onclick = function () { sendMessage("Continue exactly where you left off."); };
    $("open-settings").onclick = openSettings;
    $("save-settings").onclick = saveSettings;
    $("edit-system").onclick = openSystemPrompt;
    $("toggle-roleplay").onclick = toggleRoleplay;
    $("persona-select").onchange = onPersonaChange;
    $("open-personas").onclick = openPersonas;
    $("persona-edit-select").onchange = function () { fillPersonaEditor($("persona-edit-select").value); };
    $("persona-new").onclick = newPersona;
    $("persona-delete").onclick = deletePersona;
    $("persona-save").onclick = savePersona;
    $("material-add-files").onclick = function () { $("material-files").click(); };
    $("material-files").onchange = addMaterialFiles;
    $("material-toggle-paste").onclick = function () { $("material-paste-box").hidden = !$("material-paste-box").hidden; };
    $("material-paste-add").onclick = addPastedMaterial;
    $("persona-train").onclick = trainPersona;
    $("preview-summarize").onclick = summarizePreview;
    $("preview-add").onclick = acceptPreview;
    $("preview-skip").onclick = nextPreview;
    $("persona-speakers").addEventListener("input", refreshChips);
    $("save-system").onclick = saveSystemPrompt;
    $("toggle-sidebar").onclick = function () { $("sidebar").classList.toggle("hidden"); };
    $("model-select").onchange = onModelChange;
    $("input").addEventListener("input", autosize);
    $("input").addEventListener("keydown", onInputKey);
  }

  function init() {
    bindEvents();
    api("GET", "/api/settings").then(function (settings) {
      state.settings = settings;
      return Promise.all([loadModels(), loadPersonas()]);
    }).then(refreshList).then(newConversation);
  }

  init();
})();
