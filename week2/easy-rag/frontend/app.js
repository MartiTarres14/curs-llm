/**
 * EASY-RAG frontend. Talks only to this app's own backend — never to the
 * model, and it never sees an API key.
 *
 * It keeps the conversation as the *raw* turns the user typed. Retrieval and
 * template filling happen server-side, so what the panel on the right shows
 * is the real payload and the real similarities — not a guess made here.
 */

import { renderMarkdown, escapeHtml } from "./markdown.js";

const el = (id) => document.getElementById(id);

const dom = {
  main: document.querySelector("main"),
  messages: el("messages"),
  emptyState: el("empty-state"),
  form: el("composer"),
  input: el("input"),
  send: el("send"),
  streaming: el("streaming"),
  reset: el("reset"),
  toggleContext: el("toggle-context"),
  error: el("error"),
  modelBadge: el("model-badge"),
  ragBadge: el("rag-badge"),

  list: el("assistant-list"),
  railEmpty: el("rail-empty"),
  newAssistant: el("new-assistant"),

  bar: el("assistant-bar"),
  barName: el("assistant-name"),
  docCount: el("doc-count"),
  docMissing: el("doc-missing"),
  docFile: el("doc-file"),
  docUploadLabel: el("doc-upload-label"),
  docList: el("doc-list"),
  editAssistant: el("edit-assistant"),
  deleteAssistant: el("delete-assistant"),

  contextPanel: el("context"),
  retrievalSummary: el("retrieval-summary"),
  retrievalHits: el("retrieval-hits"),
  filledPrompt: el("filled-prompt"),
  contextMessages: el("context-messages"),
  tokPrompt: el("tok-prompt"),
  tokCompletion: el("tok-completion"),
  tokTotal: el("tok-total"),
  tokSession: el("tok-session"),
  tokNote: el("tok-note"),

  editor: el("editor"),
  editorForm: el("editor-form"),
  editorTitle: el("editor-title"),
  editorError: el("editor-error"),
  editorCancel: el("editor-cancel"),
  fName: el("f-name"),
  fSystem: el("f-system"),
  fTemplate: el("f-template"),
};

const state = {
  assistants: [],
  current: null, // the selected assistant object
  history: [], // raw user/assistant turns for the current assistant
  sessionTokens: 0,
  busy: false,
  ingesting: false,
  editing: null, // assistant being edited, or null when creating
  defaults: { system_prompt: "", prompt_template: "" },
  maxDocumentBytes: 10 * 1024 * 1024,
};

// ------------------------------------------------------------------- helpers

/** Read an error body the same way whether it is FastAPI's JSON or plain text. */
async function errorMessage(response) {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
    }
    return JSON.stringify(body);
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(await errorMessage(response));
  return response.status === 204 ? null : response.json();
}

function showError(message) {
  dom.error.textContent = message;
  dom.error.hidden = false;
}

function clearError() {
  dom.error.hidden = true;
  dom.error.textContent = "";
}

const plural = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;

// ----------------------------------------------------------------- rendering

function addBubble(role, { text = "", pending = false } = {}) {
  const bubble = document.createElement("div");
  bubble.className = `msg ${role}${pending ? " pending" : ""}`;

  const label = document.createElement("span");
  label.className = "role";
  label.textContent = role === "user" ? "You" : state.current?.name || "Assistant";

  const body = document.createElement("div");
  body.className = "body";
  if (role === "user") {
    // The user's own text is shown literally — no Markdown pass over input.
    body.innerHTML = escapeHtml(text).replace(/\n/g, "<br>");
  } else {
    body.innerHTML = renderMarkdown(text);
  }

  bubble.append(label, body);
  dom.messages.append(bubble);
  scrollToBottom();
  return { bubble, body };
}

/** The provenance footer under an answer: which chunks the answer came from. */
function attachProvenance(target, retrieval) {
  if (!retrieval) return;
  target.bubble.querySelector(".provenance")?.remove();

  const footer = document.createElement("div");
  footer.className = "provenance";

  const injected = retrieval.hits.filter((h) => h.injected);
  if (retrieval.refused || injected.length === 0) {
    target.bubble.classList.add("refused");
    const note = document.createElement("span");
    note.className = "prov-note";
    note.textContent =
      retrieval.hits.length === 0
        ? "no documents to retrieve from"
        : `nothing passed the threshold (best ${retrieval.hits[0].similarity.toFixed(3)} < ${retrieval.threshold})`;
    footer.append(note);
  } else {
    const note = document.createElement("span");
    note.className = "prov-note";
    note.textContent = "answered from:";
    footer.append(note);
    for (const hit of injected) {
      const chip = document.createElement("a");
      chip.className = "prov-chip";
      chip.href = hit.doc_url;
      chip.target = "_blank";
      chip.rel = "noopener";
      chip.title = `${hit.preview}\n\nopens the original document`;
      chip.textContent = `${hit.title} · #${hit.chunk_number} · ${hit.similarity.toFixed(3)}`;
      footer.append(chip);
    }
  }

  target.bubble.append(footer);
  scrollToBottom();
}

function scrollToBottom() {
  dom.messages.scrollTop = dom.messages.scrollHeight;
}

function renderList() {
  dom.list.replaceChildren();
  for (const assistant of state.assistants) {
    const item = document.createElement("li");

    const button = document.createElement("button");
    button.type = "button";
    button.className = assistant.id === state.current?.id ? "selected" : "";
    button.addEventListener("click", () => select(assistant.id));

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = assistant.name;

    const meta = document.createElement("span");
    meta.className = "meta";
    const docs = assistant.documents ?? [];
    const chunks = docs.reduce((sum, d) => sum + d.chunks, 0);
    meta.textContent = docs.length
      ? `${plural(docs.length, "doc")} · ${plural(chunks, "chunk")}`
      : "no documents";

    button.append(name, meta);
    item.append(button);
    dom.list.append(item);
  }
  dom.railEmpty.hidden = state.assistants.length > 0;
}

function renderBar() {
  const assistant = state.current;
  dom.bar.hidden = !assistant;
  dom.emptyState.hidden = Boolean(assistant);
  dom.input.disabled = !assistant;
  dom.send.disabled = !assistant || state.busy;
  if (!assistant) {
    dom.docList.hidden = true;
    return;
  }

  dom.barName.textContent = assistant.name;
  const docs = assistant.documents ?? [];
  dom.docCount.hidden = docs.length === 0;
  dom.docMissing.hidden = docs.length > 0;
  if (docs.length) {
    const chunks = docs.reduce((sum, d) => sum + d.chunks, 0);
    dom.docCount.textContent = `${plural(docs.length, "doc")} · ${plural(chunks, "chunk")}`;
  }
  renderDocList(docs);
}

function renderDocList(docs) {
  dom.docList.replaceChildren();
  dom.docList.hidden = docs.length === 0;
  for (const doc of docs) {
    const item = document.createElement("li");

    const link = document.createElement("a");
    link.href = doc.doc_url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = doc.filename;
    link.title = "opens the original document";

    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent =
      `${plural(doc.chunks, "chunk")} · ${doc.chunking_strategy} · ` +
      `${(doc.markdown_chars / 1000).toFixed(1)}k chars`;

    const mdLink = document.createElement("a");
    mdLink.className = "md-link";
    mdLink.href = doc.md_url;
    mdLink.target = "_blank";
    mdLink.rel = "noopener";
    mdLink.textContent = "md";
    mdLink.title = "the markdown distillation the chunks were cut from";

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "doc-remove";
    remove.textContent = "×";
    remove.title = "remove this document and its chunks";
    remove.addEventListener("click", () => removeDocument(doc.id));

    item.append(link, meta, mdLink, remove);
    dom.docList.append(item);
  }
}

function renderRetrieval(retrieval) {
  if (!retrieval) {
    dom.retrievalSummary.textContent = "—";
    dom.retrievalHits.replaceChildren();
    return;
  }

  dom.retrievalSummary.textContent =
    `top-${retrieval.top_k} over ${retrieval.threshold} — ` +
    (retrieval.refused ? "REFUSED, nothing injected" : `${retrieval.hits.filter((h) => h.injected).length} injected`);

  dom.retrievalHits.replaceChildren();
  for (const hit of retrieval.hits) {
    const item = document.createElement("li");
    item.className = hit.injected ? "injected" : "rejected";

    const mark = document.createElement("span");
    mark.className = "mark";
    mark.textContent = hit.injected ? "✓" : "✗";
    mark.title = hit.injected ? "injected into the prompt" : "below threshold — dropped";

    const sim = document.createElement("span");
    sim.className = "sim";
    sim.textContent = hit.similarity.toFixed(3);

    const source = document.createElement("a");
    source.href = hit.doc_url;
    source.target = "_blank";
    source.rel = "noopener";
    source.textContent = `${hit.title} · chunk ${hit.chunk_number}`;
    source.title = hit.preview;

    item.append(mark, sim, source);
    dom.retrievalHits.append(item);
  }
  if (retrieval.hits.length === 0) {
    const item = document.createElement("li");
    item.className = "rejected";
    item.textContent = "the collection is empty — upload a document";
    dom.retrievalHits.append(item);
  }
}

function renderContext(contextSent, filledPrompt) {
  dom.filledPrompt.textContent = filledPrompt ?? "—";

  dom.contextMessages.replaceChildren();
  for (const message of contextSent ?? []) {
    const item = document.createElement("li");

    const role = document.createElement("span");
    role.className = "role";
    role.textContent = message.role;

    const pre = document.createElement("pre");
    pre.textContent = message.content;

    item.append(role, pre);
    dom.contextMessages.append(item);
  }
}

function renderUsage(usage) {
  if (!usage) return;
  dom.tokPrompt.textContent = usage.prompt_tokens ?? "—";
  dom.tokCompletion.textContent = usage.completion_tokens ?? "—";
  dom.tokTotal.textContent = usage.total_tokens ?? "—";
  state.sessionTokens += usage.total_tokens ?? 0;
  dom.tokSession.textContent = state.sessionTokens;
  dom.tokNote.hidden = !usage.estimated;
}

function clearConversation() {
  state.history = [];
  state.sessionTokens = 0;
  dom.messages.replaceChildren();
  dom.contextMessages.replaceChildren();
  dom.filledPrompt.textContent = "—";
  renderRetrieval(null);
  for (const cell of [dom.tokPrompt, dom.tokCompletion, dom.tokTotal]) {
    cell.textContent = "—";
  }
  dom.tokSession.textContent = "0";
  dom.tokNote.hidden = true;
  clearError();
}

// ---------------------------------------------------------------- assistants

async function refresh(selectId = state.current?.id ?? null) {
  state.assistants = await api("/api/assistants");
  state.current = state.assistants.find((a) => a.id === selectId) ?? null;
  renderList();
  renderBar();
}

function select(id) {
  if (id === state.current?.id) return;
  state.current = state.assistants.find((a) => a.id === id) ?? null;
  clearConversation();
  renderList();
  renderBar();
  dom.input.focus();
}

function openEditor(assistant) {
  state.editing = assistant;
  dom.editorTitle.textContent = assistant ? "Edit assistant" : "New assistant";
  dom.fName.value = assistant?.name ?? "";
  dom.fSystem.value = assistant?.system_prompt ?? state.defaults.system_prompt;
  dom.fTemplate.value = assistant?.prompt_template ?? state.defaults.prompt_template;
  dom.editorError.hidden = true;
  dom.editor.showModal();
  dom.fName.focus();
}

async function saveAssistant(event) {
  event.preventDefault();
  const payload = {
    name: dom.fName.value.trim(),
    system_prompt: dom.fSystem.value.trim(),
    prompt_template: dom.fTemplate.value.trim(),
  };

  // Checked here too so the user sees it before a round trip; the backend
  // enforces the same rule, because it is the one that matters.
  const missing = ["{context}", "{user_input}"].filter(
    (slot) => !payload.prompt_template.includes(slot),
  );
  if (missing.length) {
    dom.editorError.textContent = `The prompt template must contain ${missing.join(" and ")}.`;
    dom.editorError.hidden = false;
    return;
  }

  const editing = state.editing;
  try {
    const saved = editing
      ? await api(`/api/assistants/${editing.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        })
      : await api("/api/assistants", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

    dom.editor.close();
    if (!editing) clearConversation();
    await refresh(saved.id);
    dom.input.focus();
  } catch (error) {
    dom.editorError.textContent = error.message;
    dom.editorError.hidden = false;
  }
}

async function deleteAssistant() {
  const assistant = state.current;
  if (!assistant) return;
  if (!confirm(`Delete "${assistant.name}", its documents and its collection?`)) return;

  try {
    await api(`/api/assistants/${assistant.id}`, { method: "DELETE" });
    clearConversation();
    await refresh(null);
  } catch (error) {
    showError(error.message);
  }
}

// ----------------------------------------------------------------- documents

async function onDocumentChosen() {
  const file = dom.docFile.files[0];
  if (!file || !state.current || state.ingesting) return;
  clearError();

  if (file.size > state.maxDocumentBytes) {
    showError(
      `That file is ${Math.round(file.size / 1024)} KB; the limit is ` +
        `${Math.round(state.maxDocumentBytes / 1024)} KB.`,
    );
    dom.docFile.value = "";
    return;
  }

  const body = new FormData();
  body.append("file", file);

  // Ingestion converts, chunks and embeds — it takes a while, say so.
  state.ingesting = true;
  dom.docUploadLabel.textContent = "Ingesting…";

  try {
    await api(`/api/assistants/${state.current.id}/documents`, { method: "POST", body });
    await refresh();
  } catch (error) {
    showError(error.message);
  } finally {
    state.ingesting = false;
    dom.docUploadLabel.textContent = "Upload document";
    // Cleared so re-picking the same filename fires "change" again.
    dom.docFile.value = "";
  }
}

async function removeDocument(docId) {
  if (!state.current) return;
  try {
    await api(`/api/assistants/${state.current.id}/documents/${docId}`, {
      method: "DELETE",
    });
    await refresh();
  } catch (error) {
    showError(error.message);
  }
}

// ------------------------------------------------------------------- sending

/**
 * `mine()` says whether the conversation this request started in is still the
 * one on screen. It gates the panels only — the reply itself still lands in
 * its own bubble, which may already have been cleared away.
 */
async function sendNonStreaming(id, body, target, mine) {
  const data = await api(`/api/assistants/${id}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (mine()) {
    renderRetrieval(data.retrieval);
    renderContext(data.context_sent, data.filled_prompt);
    renderUsage(data.usage);
  }
  target.body.innerHTML = renderMarkdown(data.reply);
  attachProvenance(target, data.retrieval);
  scrollToBottom();
  return data.reply;
}

async function sendStreaming(id, body, target, mine) {
  const response = await fetch(`/api/assistants/${id}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await errorMessage(response));

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answer = "";
  let failure = null;
  let retrieval = null;
  let repaintQueued = false;

  // Repaint at most once per frame: a fast stream would otherwise re-render the
  // whole Markdown body on every token.
  const repaint = () => {
    if (repaintQueued) return;
    repaintQueued = true;
    requestAnimationFrame(() => {
      repaintQueued = false;
      target.body.innerHTML = renderMarkdown(answer);
      scrollToBottom();
    });
  };

  const handle = (event) => {
    if (event.type === "delta") {
      answer += event.content;
      repaint();
    } else if (event.type === "context") {
      retrieval = event.retrieval;
      if (mine()) {
        renderRetrieval(event.retrieval);
        renderContext(event.context_sent, event.filled_prompt);
      }
    } else if (event.type === "usage") {
      if (mine()) renderUsage(event.usage);
    } else if (event.type === "error") {
      failure = event.message;
    }
  };

  const drain = (block) => {
    for (const line of block.split("\n")) {
      if (line.startsWith("data:")) handle(JSON.parse(line.slice(5)));
    }
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Events are separated by a blank line; keep any partial tail for next read.
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop();
    blocks.forEach(drain);
  }

  // A final event that arrived without its trailing blank line.
  if (buffer.trim()) drain(buffer);

  if (failure) throw new Error(failure);

  target.body.innerHTML = renderMarkdown(answer);
  attachProvenance(target, retrieval);
  scrollToBottom();
  return answer;
}

async function submit() {
  if (state.busy || !state.current) return;

  const text = dom.input.value.trim();
  if (!text) return;

  clearError();

  // Captured because the user can switch assistants while the answer is in
  // flight. clearConversation() then hands state.history a fresh array, and
  // everything below must keep working on the conversation it started in.
  const assistantId = state.current.id;
  const history = state.history;
  const mine = () => state.history === history;

  const userBubble = addBubble("user", { text });
  const assistantBubble = addBubble("assistant", { pending: true });

  history.push({ role: "user", content: text });

  setBusy(true);
  dom.input.value = "";
  autoGrow();

  try {
    const send = dom.streaming.checked ? sendStreaming : sendNonStreaming;
    const reply = await send(assistantId, { messages: history }, assistantBubble, mine);
    history.push({ role: "assistant", content: reply });
    assistantBubble.bubble.classList.remove("pending");
  } catch (error) {
    // Roll back so the history stays a clean alternating transcript and the
    // user can just press Send again.
    history.pop();
    assistantBubble.bubble.remove();
    userBubble.bubble.remove();
    if (mine()) {
      dom.input.value = text;
      autoGrow();
      showError(error.message || String(error));
    }
  } finally {
    setBusy(false);
    dom.input.focus();
  }
}

function setBusy(busy) {
  state.busy = busy;
  dom.send.disabled = busy || !state.current;
  dom.send.textContent = busy ? "…" : "Send";
}

// --------------------------------------------------------------------- setup

function autoGrow() {
  dom.input.style.height = "auto";
  dom.input.style.height = `${dom.input.scrollHeight}px`;
}

async function loadHealth() {
  const health = await api("/api/health");
  dom.modelBadge.textContent = `${health.model} · ${health.embed_model}`;
  dom.ragBadge.textContent =
    `top-${health.rag.top_k} ≥ ${health.rag.threshold} · ${health.rag.chunk_strategy}`;
  state.maxDocumentBytes = health.max_document_bytes ?? state.maxDocumentBytes;
  state.defaults = {
    system_prompt: health.default_system_prompt ?? "",
    prompt_template: health.default_prompt_template ?? "",
  };
}

dom.form.addEventListener("submit", (event) => {
  event.preventDefault();
  submit();
});

dom.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submit();
  }
});

dom.input.addEventListener("input", autoGrow);
dom.reset.addEventListener("click", () => {
  clearConversation();
  dom.input.focus();
});

dom.newAssistant.addEventListener("click", () => openEditor(null));
dom.editAssistant.addEventListener("click", () => openEditor(state.current));
dom.deleteAssistant.addEventListener("click", deleteAssistant);
dom.editorForm.addEventListener("submit", saveAssistant);
dom.editorCancel.addEventListener("click", () => dom.editor.close());

dom.docFile.addEventListener("change", onDocumentChosen);

dom.toggleContext.addEventListener("click", () => {
  const hidden = dom.main.classList.toggle("no-context");
  dom.toggleContext.setAttribute("aria-expanded", String(!hidden));
});

(async function start() {
  try {
    await loadHealth();
    await refresh(null);
  } catch (error) {
    dom.modelBadge.textContent = "unavailable";
    showError(`Backend not reachable: ${error.message}`);
  }
})();
