// Hams AI — VS Code Extension
//
// Wires the agent API into VS Code:
//   - Chat sidebar panel  (WebviewView)
//   - Context menu commands: Explain, Fix, Generate Tests
//   - Editor title button: Run Task
//
// Communication: HTTP POST to the agent API (default: http://localhost:8000)

"use strict";

const vscode = require("vscode");

// ---------------------------------------------------------------------------
// Extension lifecycle
// ---------------------------------------------------------------------------

/** @param {vscode.ExtensionContext} context */
function activate(context) {
  console.log("Hams AI extension activated");

  const controller = new AgentController(context);

  context.subscriptions.push(
    vscode.commands.registerCommand("aiAgent.startChat", () =>
      controller.focusChatView()
    ),
    vscode.commands.registerCommand("aiAgent.runTask", () =>
      controller.runTaskOnActiveFile()
    ),
    vscode.commands.registerCommand("aiAgent.explainSelection", () =>
      controller.explainSelection()
    ),
    vscode.commands.registerCommand("aiAgent.generateTests", () =>
      controller.generateTests()
    ),
    vscode.commands.registerCommand("aiAgent.fixSelection", () =>
      controller.fixSelection()
    ),
    vscode.commands.registerCommand("aiAgent.refactorCode", () =>
      controller.refactorCode()
    ),
    vscode.window.registerWebviewViewProvider(
      "aiAgentChatView",
      controller.chatViewProvider,
      { webviewOptions: { retainContextWhenHidden: true } }
    )
  );
}

function deactivate() {
  console.log("Hams AI extension deactivated");
}

module.exports = { activate, deactivate };

// ---------------------------------------------------------------------------
// AgentController — coordinates all commands and the chat view
// ---------------------------------------------------------------------------

class AgentController {
  /** @param {vscode.ExtensionContext} context */
  constructor(context) {
    this._context = context;
    this._chatProvider = new ChatViewProvider(context);
  }

  get chatViewProvider() {
    return this._chatProvider;
  }

  focusChatView() {
    vscode.commands.executeCommand("aiAgentChatView.focus");
  }

  // ── Commands ──────────────────────────────────────────────────────────

  async runTaskOnActiveFile() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
      vscode.window.showWarningMessage("Hams AI: No active file.");
      return;
    }
    const fileName = editor.document.fileName;
    const task = await vscode.window.showInputBox({
      prompt: "What should the agent do with this file?",
      placeHolder: `e.g. "Add type hints to all functions in ${fileName}"`,
    });
    if (!task) return;
    this._chatProvider.sendTask(task);
    this.focusChatView();
  }

  async explainSelection() {
    const text = this._getSelection();
    if (!text) return;
    const lang = vscode.window.activeTextEditor?.document.languageId ?? "";
    const task = `Explain what this ${lang} code does:\n\n\`\`\`${lang}\n${text}\n\`\`\``;
    this._chatProvider.sendTask(task);
    this.focusChatView();
  }

  async generateTests() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
      vscode.window.showWarningMessage("Hams AI: No active file.");
      return;
    }
    const lang = editor.document.languageId;
    const file = editor.document.fileName;
    const task = `Generate comprehensive unit tests for the code in ${file}. Write the tests to a new file alongside the source file.`;
    this._chatProvider.sendTask(task);
    this.focusChatView();
  }

  async fixSelection() {
    const text = this._getSelection();
    if (!text) return;
    const lang = vscode.window.activeTextEditor?.document.languageId ?? "";
    const task = `Fix any bugs or issues in this ${lang} code and explain the changes:\n\n\`\`\`${lang}\n${text}\n\`\`\``;
    this._chatProvider.sendTask(task);
    this.focusChatView();
  }

  async refactorCode() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
      vscode.window.showWarningMessage("Hams AI: No active file.");
      return;
    }
    const file = editor.document.fileName;
    const task = `Suggest and apply refactoring improvements to ${file}. Focus on readability, maintainability, and performance without changing behavior.`;
    this._chatProvider.sendTask(task);
    this.focusChatView();
  }

  // ── Helpers ───────────────────────────────────────────────────────────

  _getSelection() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
      vscode.window.showWarningMessage("Hams AI: No active editor.");
      return null;
    }
    const text = editor.document.getText(editor.selection).trim();
    if (!text) {
      vscode.window.showWarningMessage("Hams AI No text selected.");
      return null;
    }
    return text;
  }
}

// ---------------------------------------------------------------------------
// ChatViewProvider — Webview sidebar panel
// ---------------------------------------------------------------------------

class ChatViewProvider {
  static viewType = "aiAgentChatView";

  /** @param {vscode.ExtensionContext} context */
  constructor(context) {
    this._context = context;
    this._view = null;
  }

  /** @param {vscode.WebviewView} webviewView */
  resolveWebviewView(webviewView) {
    this._view = webviewView;
    webviewView.webview.options = { enableScripts: true };
    webviewView.webview.html = this._getHtml();

    // Handle messages from the webview
    webviewView.webview.onDidReceiveMessage(async (msg) => {
      switch (msg.type) {
        case "sendTask":
          await this._runTask(msg.task);
          break;
        case "clearChat":
          // Already handled client-side
          break;
        case "openSettings":
          vscode.commands.executeCommand(
            "workbench.action.openSettings",
            "aiAgent"
          );
          break;
      }
    });
  }

  // Called by AgentController commands to pre-fill and submit a task
  sendTask(task) {
    if (this._view) {
      this._view.webview.postMessage({ type: "prefillTask", task });
      this._runTask(task);
    } else {
      // View not open yet — run the task and results will appear when opened
      this._pendingTask = task;
      this._runTask(task);
    }
  }

  async _runTask(task) {
    const config = vscode.workspace.getConfiguration("aiAgent");
    const apiUrl = config.get("apiUrl", "http://localhost:8000");
    const useStream = config.get("streamResponses", true);

    this._postToView({ type: "taskStart", task });

    try {
      if (useStream) {
        await this._runStreaming(apiUrl, task, config);
      } else {
        await this._runBlocking(apiUrl, task, config);
      }
    } catch (err) {
      this._postToView({
        type: "error",
        message: `Connection failed: ${err.message}\n\nMake sure the agent server is running at ${apiUrl}`,
      });
    }
  }

  async _runBlocking(apiUrl, task, config) {
    const body = JSON.stringify({
      task,
      provider: config.get("provider", "ollama"),
      model: config.get("model", "") || undefined,
      max_steps: config.get("maxSteps", 30),
    });

    const resp = await fetch(`${apiUrl}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
    }

    const data = await resp.json();
    this._postToView({
      type: "taskComplete",
      runId: data.run_id,
      status: data.status,
      answer: data.final_answer ?? data.error ?? "(no output)",
      steps: data.steps_taken,
      tokens: data.total_tokens,
      duration: data.duration_seconds,
    });
  }

  async _runStreaming(apiUrl, task, config) {
    const body = JSON.stringify({
      task,
      provider: config.get("provider", "ollama"),
      model: config.get("model", "") || undefined,
      max_steps: config.get("maxSteps", 30),
    });

    const resp = await fetch(`${apiUrl}/run/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      for (const line of chunk.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        try {
          const event = JSON.parse(line.slice(6));
          if (event.type === "step") {
            this._postToView({ type: "step", ...event });
          } else if (event.type === "complete" || event.type === "error") {
            this._postToView({
              type: "taskComplete",
              runId: event.run_id,
              status: event.type,
              answer: event.final_answer ?? event.error ?? "(no output)",
              steps: event.steps,
              tokens: event.tokens,
            });
          }
        } catch {
          // Ignore unparseable lines
        }
      }
    }
  }

  _postToView(msg) {
    if (this._view) {
      this._view.webview.postMessage(msg);
    }
  }

  _getHtml() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hams AI</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    color: var(--vscode-foreground);
    background: var(--vscode-sideBar-background);
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .header {
    padding: 8px 10px;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--vscode-sideBarTitle-foreground);
    border-bottom: 1px solid var(--vscode-sideBar-border, #333);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .header-actions { display: flex; gap: 4px; }
  .icon-btn {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--vscode-icon-foreground);
    padding: 2px 4px;
    border-radius: 3px;
    font-size: 14px;
    line-height: 1;
  }
  .icon-btn:hover { background: var(--vscode-toolbar-hoverBackground); }
  #messages {
    flex: 1;
    overflow-y: auto;
    padding: 8px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .msg { padding: 6px 8px; border-radius: 6px; font-size: 12px; line-height: 1.5; }
  .msg-user {
    background: var(--vscode-inputOption-activeBackground);
    border-left: 2px solid var(--vscode-focusBorder);
  }
  .msg-agent {
    background: var(--vscode-editor-inactiveSelectionBackground);
    white-space: pre-wrap;
    word-break: break-word;
  }
  .msg-step {
    background: var(--vscode-diffEditor-unchangedCodeBackground, rgba(255,255,255,0.03));
    border-left: 2px solid var(--vscode-charts-yellow, #cca700);
    font-size: 11px;
    color: var(--vscode-descriptionForeground);
  }
  .msg-error {
    background: var(--vscode-inputValidation-errorBackground);
    border-left: 2px solid var(--vscode-inputValidation-errorBorder);
    color: var(--vscode-editorError-foreground);
  }
  .msg-label {
    font-size: 10px;
    color: var(--vscode-descriptionForeground);
    margin-bottom: 2px;
    font-weight: 600;
  }
  .meta {
    font-size: 10px;
    color: var(--vscode-descriptionForeground);
    text-align: right;
    margin-top: 4px;
  }
  .spinner {
    display: inline-block;
    width: 10px; height: 10px;
    border: 2px solid var(--vscode-focusBorder);
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin-right: 6px;
    vertical-align: middle;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .input-area {
    padding: 8px;
    border-top: 1px solid var(--vscode-sideBar-border, #333);
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  #task-input {
    width: 100%;
    background: var(--vscode-input-background);
    color: var(--vscode-input-foreground);
    border: 1px solid var(--vscode-input-border, #555);
    border-radius: 4px;
    padding: 6px 8px;
    font-family: inherit;
    font-size: 12px;
    resize: vertical;
    min-height: 60px;
    outline: none;
  }
  #task-input:focus { border-color: var(--vscode-focusBorder); }
  #send-btn {
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    border: none;
    border-radius: 4px;
    padding: 5px 12px;
    cursor: pointer;
    font-size: 12px;
    font-family: inherit;
    align-self: flex-end;
  }
  #send-btn:hover { background: var(--vscode-button-hoverBackground); }
  #send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .welcome {
    text-align: center;
    color: var(--vscode-descriptionForeground);
    padding: 20px;
    font-size: 12px;
    line-height: 1.7;
  }
  .welcome-title { font-size: 14px; font-weight: 600; margin-bottom: 8px; color: var(--vscode-foreground); }
</style>
</head>
<body>
<div class="header">
  Hams AI
  <div class="header-actions">
    <button class="icon-btn" onclick="clearChat()" title="Clear chat">⊘</button>
    <button class="icon-btn" onclick="openSettings()" title="Settings">⚙</button>
  </div>
</div>

<div id="messages">
  <div class="welcome">
    <div class="welcome-title">Hams AI</div>
    Describe a coding task and the agent will<br>
    write, test, fix, and verify the code for you.
  </div>
</div>

<div class="input-area">
  <textarea id="task-input" placeholder="Describe a coding task..."></textarea>
  <button id="send-btn" onclick="sendTask()">Run Task ▶</button>
</div>

<script>
  const vscode = acquireVsCodeApi();
  let busy = false;

  function sendTask() {
    const input = document.getElementById('task-input');
    const task = input.value.trim();
    if (!task || busy) return;
    input.value = '';
    vscode.postMessage({ type: 'sendTask', task });
  }

  function clearChat() {
    document.getElementById('messages').innerHTML =
      '<div class="welcome"><div class="welcome-title">Hams AI</div>Chat cleared.</div>';
    busy = false;
    document.getElementById('send-btn').disabled = false;
  }

  function openSettings() {
    vscode.postMessage({ type: 'openSettings' });
  }

  function addMsg(html, cls) {
    const msgs = document.getElementById('messages');
    const first = msgs.querySelector('.welcome');
    if (first) first.remove();
    const div = document.createElement('div');
    div.className = 'msg ' + cls;
    div.innerHTML = html;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
  }

  document.getElementById('task-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      sendTask();
    }
  });

  window.addEventListener('message', e => {
    const msg = e.data;
    const btn = document.getElementById('send-btn');

    if (msg.type === 'prefillTask') {
      document.getElementById('task-input').value = msg.task;
    }

    if (msg.type === 'taskStart') {
      busy = true;
      btn.disabled = true;
      addMsg('<div class="msg-label">You</div>' + escHtml(msg.task), 'msg-user');
      addMsg('<span class="spinner"></span>Running task…', 'msg-agent msg-running');
    }

    if (msg.type === 'step') {
      const running = document.querySelector('.msg-running');
      const tools = (msg.tools || []).join(', ') || '—';
      const obs = msg.observation ? '<br><span style="opacity:0.7">' + escHtml(msg.observation) + '</span>' : '';
      const step = document.createElement('div');
      step.className = 'msg msg-step';
      step.innerHTML = '<b>Step ' + msg.step + '</b> · ' + escHtml(tools) + obs;
      if (running) running.before(step);
    }

    if (msg.type === 'taskComplete') {
      busy = false;
      btn.disabled = false;
      document.querySelector('.msg-running')?.remove();
      const icon = msg.status === 'complete' ? '✅' : '❌';
      const meta = [
        msg.steps ? msg.steps + ' steps' : '',
        msg.tokens ? msg.tokens.toLocaleString() + ' tokens' : '',
        msg.duration ? msg.duration + 's' : '',
      ].filter(Boolean).join(' · ');
      addMsg(
        '<div class="msg-label">' + icon + ' Agent</div>' +
        escHtml(msg.answer || '') +
        (meta ? '<div class="meta">' + meta + '</div>' : ''),
        'msg-agent'
      );
    }

    if (msg.type === 'error') {
      busy = false;
      btn.disabled = false;
      document.querySelector('.msg-running')?.remove();
      addMsg('<div class="msg-label">⚠ Error</div>' + escHtml(msg.message), 'msg-error');
    }
  });

  function escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/\n/g, '<br>');
  }
</script>
</body>
</html>`;
  }
}
