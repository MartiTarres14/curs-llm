/**
 * EASY-CHATGPT frontend. Talks only to this app's own backend — never to the
 * model, and it never sees an API key.
 */

import { renderMarkdown, escapeHtml } from "./markdown.js";

const el = (id) => document.getElementById(id);

const dom = {
  main: document.querySelector("main"),
  messages: el("messages"),
  form: el("composer"),
  input: el("input"),
  send: el("send"),
  streaming: el("streaming"),
  reset: el("reset"),
  toggleContext: el("toggle-context"),
  error: el("error"),
  modelBadge: el("model-badge"),
  file: el("file"),
  attachLabel: el("attach-label"),
  attachment: el("attachment"),
  attachmentPreview: el("attachment-preview"),
  attachmentName: el("attachment-name"),
  attachmentRemove: el("attachment-remove"),
  contextPanel: el("context"),
  contextMessages: el("context-messages"),
  tokPrompt: el("tok-prompt"),
  tokCompletion: el("tok-completion"),
  tokTotal: el("tok-total"),
  tokSession: el("tok-session"),
  tokNote: el("tok-note"),
};

/** Conversation as the backend will receive it: user/assistant turns only. */
const state = {
  history: [],
  sessionTokens: 0,
  busy: false,
  attachment: null, // { dataUrl, name, size }
  maxImageBytes: 5 * 1024 * 1024,
};

// ---------------------------------------------------------------- rendering

function addBubble(role, { text = "", imageUrl = null, pending = false } = {}) {
  const bubble = document.createElement("div");
  bubble.className = `msg ${role}${pending ? " pending" : ""}`;

  const label = document.createElement("span");
  label.className = "role";
  label.textContent = role === "user" ? "You" : "Assistant";

  const body = document.createElement("div");
  body.className = "body";
  if (role === "user") {
    // The user's own text is shown literally — no Markdown pass over input.
    body.innerHTML = escapeHtml(text).replace(/\n/g, "<br>");
  } else {
    body.innerHTML = renderMarkdown(text);
  }

  bubble.append(label, body);

  if (imageUrl) {
    const image = document.createElement("img");
    image.className = "sent-image";
    image.src = imageUrl;
    image.alt = "Attached image";
    bubble.append(image);
  }

  dom.messages.append(bubble);
  scrollToBottom();
  return { bubble, body };
}

function scrollToBottom() {
  dom.messages.scrollTop = dom.messages.scrollHeight;
}

function showError(message) {
  dom.error.textContent = message;
  dom.error.hidden = false;
}

function clearError() {
  dom.error.hidden = true;
  dom.error.textContent = "";
}

// ------------------------------------------------------------- context view

const PREVIEW_CHARS = 48;

/** Shorten base64 payloads so the panel stays readable and the page stays fast. */
function shortenImages(content) {
  if (typeof content === "string") return content;
  return content.map((part) => {
    if (part.type !== "image_url") return part;
    const url = part.image_url.url;
    const kb = Math.round((url.length * 3) / 4 / 1024);
    return {
      type: "image_url",
      image_url: { url: `${url.slice(0, PREVIEW_CHARS)}… (${kb} KB, truncated)` },
    };
  });
}

function renderContext(contextSent) {
  dom.contextMessages.replaceChildren();
  for (const message of contextSent) {
    const item = document.createElement("li");

    const role = document.createElement("span");
    role.className = "role";
    role.textContent = message.role;

    const pre = document.createElement("pre");
    const content = shortenImages(message.content);
    pre.textContent =
      typeof content === "string" ? content : JSON.stringify(content, null, 2);

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

// ------------------------------------------------------------------ sending

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

async function sendNonStreaming(body, target) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await errorMessage(response));

  const data = await response.json();
  renderContext(data.context_sent);
  renderUsage(data.usage);
  target.body.innerHTML = renderMarkdown(data.reply);
  scrollToBottom();
  return data.reply;
}

async function sendStreaming(body, target) {
  const response = await fetch("/api/chat/stream", {
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
      renderContext(event.context_sent);
    } else if (event.type === "usage") {
      renderUsage(event.usage);
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
  scrollToBottom();
  return answer;
}

async function submit() {
  if (state.busy) return;

  const text = dom.input.value.trim();
  const attachment = state.attachment;
  if (!text && !attachment) return;

  clearError();

  const content = attachment
    ? [
        { type: "text", text },
        { type: "image_url", image_url: { url: attachment.dataUrl } },
      ]
    : text;

  const userBubble = addBubble("user", {
    text,
    imageUrl: attachment ? attachment.dataUrl : null,
  });
  const assistantBubble = addBubble("assistant", { pending: true });

  state.history.push({ role: "user", content });
  const body = { messages: state.history };

  setBusy(true);
  dom.input.value = "";
  autoGrow();
  clearAttachment();

  try {
    const send = dom.streaming.checked ? sendStreaming : sendNonStreaming;
    const reply = await send(body, assistantBubble);
    state.history.push({ role: "assistant", content: reply });
    assistantBubble.bubble.classList.remove("pending");
  } catch (error) {
    // Roll back so the history stays a clean alternating transcript and the
    // user can just press Send again.
    state.history.pop();
    assistantBubble.bubble.remove();
    userBubble.bubble.remove();
    dom.input.value = text;
    if (attachment) restoreAttachment(attachment);
    autoGrow();
    showError(error.message || String(error));
  } finally {
    setBusy(false);
    dom.input.focus();
  }
}

function setBusy(busy) {
  state.busy = busy;
  dom.send.disabled = busy;
  dom.send.textContent = busy ? "…" : "Send";
}

// -------------------------------------------------------------- attachments

function restoreAttachment(attachment) {
  state.attachment = attachment;
  dom.attachmentPreview.src = attachment.dataUrl;
  dom.attachmentName.textContent = `${attachment.name} · ${Math.round(attachment.size / 1024)} KB`;
  dom.attachment.hidden = false;
}

function clearAttachment() {
  state.attachment = null;
  dom.file.value = "";
  dom.attachment.hidden = true;
  dom.attachmentPreview.removeAttribute("src");
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("Could not read that file."));
    reader.readAsDataURL(file);
  });
}

async function onFileChosen() {
  const file = dom.file.files[0];
  if (!file) return;
  clearError();

  if (!file.type.startsWith("image/")) {
    showError("Only image files can be attached.");
    clearAttachment();
    return;
  }
  if (file.size > state.maxImageBytes) {
    showError(
      `That image is ${Math.round(file.size / 1024)} KB; the limit is ` +
        `${Math.round(state.maxImageBytes / 1024)} KB.`,
    );
    clearAttachment();
    return;
  }

  restoreAttachment({
    dataUrl: await readFile(file),
    name: file.name,
    size: file.size,
  });
}

// -------------------------------------------------------------------- setup

function autoGrow() {
  dom.input.style.height = "auto";
  dom.input.style.height = `${dom.input.scrollHeight}px`;
}

function resetChat() {
  state.history = [];
  state.sessionTokens = 0;
  dom.messages.replaceChildren();
  dom.contextMessages.replaceChildren();
  for (const cell of [dom.tokPrompt, dom.tokCompletion, dom.tokTotal]) {
    cell.textContent = "—";
  }
  dom.tokSession.textContent = "0";
  dom.tokNote.hidden = true;
  clearAttachment();
  clearError();
  dom.input.focus();
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error(await errorMessage(response));
    const health = await response.json();

    dom.modelBadge.textContent = health.model;
    state.maxImageBytes = health.max_image_bytes ?? state.maxImageBytes;

    if (health.vision_enabled) {
      dom.attachLabel.title = `Attach an image (vision model: ${health.vision_model})`;
    } else {
      dom.attachLabel.classList.add("disabled");
      dom.attachLabel.title =
        "Image attachments are disabled: no LLM_VISION_MODEL is set in .env";
      dom.file.disabled = true;
    }
  } catch (error) {
    dom.modelBadge.textContent = "unavailable";
    showError(`Backend not reachable: ${error.message}`);
  }
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
dom.file.addEventListener("change", onFileChosen);
dom.attachmentRemove.addEventListener("click", clearAttachment);
dom.reset.addEventListener("click", resetChat);

dom.attachLabel.addEventListener("click", (event) => {
  if (dom.file.disabled) event.preventDefault();
});

dom.toggleContext.addEventListener("click", () => {
  const hidden = dom.main.classList.toggle("no-context");
  dom.toggleContext.setAttribute("aria-expanded", String(!hidden));
});

loadHealth();
dom.input.focus();
