"use strict";

const log = document.getElementById("log");
const form = document.getElementById("form");
const prompt = document.getElementById("prompt");
const sendButton = document.getElementById("send");
const stopButton = document.getElementById("stop");

// история только в памяти вкладки, после перезагрузки её нет
let history = [];
let controller = null;

function addMessage(role, text) {
  const stick = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  const item = document.createElement("div");

  item.className = `msg ${role}`;
  const body = document.createElement("div");

  body.className = "text";
  body.textContent = text;
  item.append(body);
  log.append(item);
  if (stick) log.scrollTop = log.scrollHeight;
  return item;
}

function addNote(item, text, isError) {
  const note = document.createElement("div");

  note.className = isError ? "note error" : "note";
  note.textContent = text;
  item.append(note);
}

function errorText(status, data) {
  const error = data && data.error;

  if (typeof error === "string") return error;
  if (error && error.message) return error.message;
  return `ошибка ${status}`;
}

// разбор SSE
async function readEvents(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  let buffer = "";

  for (;;) {
    const {value, done} = await reader.read();
    if (done) return false;
    buffer += decoder.decode(value, {stream: true});
    let end;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const event = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      for (const line of event.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        const data = line.slice(6);
        if (data === "[DONE]") return true;
        onEvent(JSON.parse(data));
      }
    }
  }
}

function stats(started, firstToken, usage) {
  const parts = [];
  if (firstToken) parts.push(`TTFT ${((firstToken - started) / 1000).toFixed(1)} с`);
  if (usage) {
    const tokens = usage.completion_tokens;
    const seconds = (performance.now() - firstToken) / 1000;
    if (tokens > 1 && seconds > 0) parts.push(`${((tokens - 1) / seconds).toFixed(1)} ток/с`);
    parts.push(`${tokens} ток.`);
  }
  return parts.join(" | ");
}

function setBusy(busy) {
  sendButton.hidden = busy;
  stopButton.hidden = !busy;
}

async function send(text) {
  // "Новый чат" заменяет массив, и прерванный ответ остаётся в старом
  const thread = history;
  const system = document.getElementById("system").value.trim();

  thread.push({role: "user", content: text});

  const question = addMessage("user", text);
  const item = addMessage("assistant", "");
  const body = item.querySelector(".text");
  const messages = system ? [{role: "system", content: system}, ...thread] : thread;

  controller = new AbortController();
  setBusy(true);
  const started = performance.now();
  let firstToken = null;
  let usage = null;
  let answer = "";
  let finished = false;
  try {
    const response = await fetch("api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        messages,
        temperature: Number(document.getElementById("temperature").value),
        max_tokens: Number(document.getElementById("max-tokens").value),
      }),
      signal: controller.signal,
    });
    if (!response.ok) {
      // 500 от сервера приходит текстом, не JSON
      const data = await response.json().catch(() => null);
      throw new Error(errorText(response.status, data));
    }
    finished = await readEvents(response, (chunk) => {
      if (chunk.error) throw new Error(errorText(0, chunk));
      if (chunk.model) document.getElementById("model").textContent = chunk.model;
      if (chunk.usage) usage = chunk.usage;
      const delta = chunk.choices && chunk.choices.length && chunk.choices[0].delta.content;
      if (delta) {
        firstToken = firstToken || performance.now();
        answer += delta;
        const stick = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
        body.textContent = answer;
        if (stick) log.scrollTop = log.scrollHeight;
      }
    });
    if (!finished) addNote(item, "поток оборвался", true);
  } catch (err) {
    addNote(item, err.name === "AbortError" ? "остановлено" : err.message, err.name !== "AbortError");
  } finally {
    controller = null;
    setBusy(false);
  }

  if (answer) {
    thread.push({role: "assistant", content: answer});
    if (finished) addNote(item, stats(started, firstToken, usage), false);
  } else {
    // без ответа вопрос в историю не идёт
    thread.pop();
    question.classList.add("dropped");
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = prompt.value.trim();
  if (!text || controller) return;
  prompt.value = "";
  send(text);
});

prompt.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});

stopButton.addEventListener("click", () => controller && controller.abort());

document.getElementById("reset").addEventListener("click", () => {
  if (controller) controller.abort();
  history = [];
  log.replaceChildren();
  prompt.focus();
});
