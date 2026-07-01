const state = {
  sessionId: "",
  cursor: 0,
  events: [],
  localEvents: [],
  sessions: [],
  snapshot: null,
  approvals: [],
  checkpoints: [],
  capabilities: [],
  memoryHits: [],
  repoStatus: null,
  repoCache: [],
  report: null,
  config: null,
  providers: [],
  providerReadiness: [],
  workspacePath: "",
  fileTree: {},
  expandedDirs: new Set(["."]),
  selectedFile: null,
  filePreview: null,
  busy: false,
  lastError: "",
  toastTimer: 0,
  avatarTimer: 0,
  avatarFrame: 0,
  activeTab: "approvals",
  terminalOpen: false,
  renderCache: {}
};

const idleFrames = ["/assets/cat-idle-1.webp", "/assets/cat-idle-2.webp", "/assets/cat-idle-3.webp"];
const workFrames = ["/assets/cat-work-1.webp", "/assets/cat-work-2.webp", "/assets/cat-work-3.webp"];

const POLL_FAST = 1000;
const POLL_SLOW = 2500;

const SUGGESTS = [
  { label: "查看仓库结构", prompt: "list files", hint: "list_files" },
  { label: "读 README", prompt: "read README.md", hint: "read_file" },
  { label: "分析项目最小架构", prompt: "分析项目最小架构", hint: "repo blueprint" },
  { label: "搜索 ToolRegistry", prompt: "search ToolRegistry", hint: "memory search" }
];

const NAV_TO_TAB = {
  approvals: "approvals",
  files: "files",
  memory: "memory",
  repo: "repo",
  api: "api",
  capabilities: "capabilities"
};

const nodes = {};
let pollTimer = 0;
let pollInterval = POLL_FAST;

boot().catch(showError);

async function boot() {
  cacheNodes();
  bindEvents();
  preloadMascots();
  selectTab(state.activeTab, { initial: true });
  startAvatarLoop();
  setPromptFeedback("正在连接 CodeMuse 后端...");
  await refreshWorkspace();
  if (!state.sessionId) {
    await createSession();
  }
  setPromptFeedback("");
  schedulePoll();
}

function cacheNodes() {
  const ids = [
    "workspace", "runtime-status", "agent-motion-label", "agent-mascot",
    "session-total", "active-count", "active-run-count", "failed-count",
    "session-state", "status-pill", "phase-state", "queue-count", "stat-session",
    "events", "terminal-pane", "terminal-feed", "toggle-terminal",
    "prompt-form", "prompt", "send", "prompt-feedback",
    "checkpoint", "stop-button", "approvals", "approval-count", "checkpoints",
    "checkpoint-count", "memory-form", "memory-query", "memory-index", "memory-results",
    "workspace-form", "workspace-path", "workspace-apply", "file-refresh", "file-tree", "file-preview",
    "repo-refresh", "repo-status", "repo-cache", "report-refresh", "report-summary",
    "api-form", "api-refresh", "api-status", "api-provider", "api-model",
    "api-base-url", "api-key-env", "provider-list", "capabilities",
    "sessions-panel", "sessions", "new-session", "refresh", "status-dot",
    "command-input", "toast",
    "nav-approval-hint", "nav-approval-badge", "nav-sessions-hint"
  ];
  for (const id of ids) {
    const camel = id.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    nodes[camel] = document.getElementById(id);
  }
}

function preloadMascots() {
  for (const src of [...idleFrames, ...workFrames]) {
    const img = new Image();
    img.src = src;
  }
}

function bindEvents() {
  nodes.newSession.addEventListener("click", e => withButton(e.currentTarget, createSession()));
  nodes.refresh.addEventListener("click", e => withButton(e.currentTarget, refreshWorkspace().then(() => showToast("已刷新工作台", "success"))));
  nodes.checkpoint.addEventListener("click", e => withButton(e.currentTarget, createCheckpoint()));
  nodes.stopButton.addEventListener("click", e => withButton(e.currentTarget, cancelRun()));
  nodes.toggleTerminal.addEventListener("click", () => toggleTerminal());
  nodes.workspaceForm.addEventListener("submit", e => {
    e.preventDefault();
    withButton(nodes.workspaceApply, switchWorkspace());
  });
  nodes.fileRefresh.addEventListener("click", e => withButton(e.currentTarget, refreshFiles(true).then(() => showToast("文件树已刷新", "success"))));

  nodes.repoRefresh.addEventListener("click", e => withButton(e.currentTarget, refreshRepo().then(() => { render(); showToast("仓库状态已刷新", "success"); })));
  nodes.reportRefresh.addEventListener("click", e => withButton(e.currentTarget, refreshReport().then(() => { render(); showToast("评测报告已刷新", "success"); })));
  nodes.memoryIndex.addEventListener("click", e => withButton(e.currentTarget, refreshMemoryIndex()));
  nodes.apiRefresh.addEventListener("click", e => withButton(e.currentTarget, refreshApiConfig().then(() => { render(); showToast("模型配置已刷新", "success"); })));
  nodes.apiProvider.addEventListener("change", applyProviderDefaults);

  nodes.promptForm.addEventListener("submit", e => {
    e.preventDefault();
    withButton(nodes.send, sendPrompt());
  });
  nodes.prompt.addEventListener("input", () => {
    autoGrow(nodes.prompt);
    renderShell();
  });
  nodes.prompt.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      withButton(nodes.send, sendPrompt());
    }
  });

  nodes.memoryForm.addEventListener("submit", e => {
    e.preventDefault();
    withButton(e.submitter || nodes.memoryForm.querySelector("button"), searchMemory());
  });
  nodes.apiForm.addEventListener("submit", e => {
    e.preventDefault();
    withButton(e.submitter || nodes.apiForm.querySelector("button"), saveApiConfig());
  });

  nodes.commandInput.addEventListener("keydown", e => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    runCommand(nodes.commandInput.value.trim()).catch(showError);
  });

  document.addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      nodes.commandInput.focus();
      nodes.commandInput.select();
    }
    if (e.key === "Escape" && nodes.sessionsPanel.classList.contains("open")) {
      nodes.sessionsPanel.classList.remove("open");
    }
  });

  document.body.addEventListener("click", e => {
    const target = e.target instanceof HTMLElement ? e.target : null;
    if (!target) return;

    const tab = target.closest("[data-tab]");
    if (tab && tab.classList.contains("tab")) {
      selectTab(tab.getAttribute("data-tab") || "");
      return;
    }
    const nav = target.closest("[data-panel-target]");
    if (nav) {
      const panel = nav.getAttribute("data-panel-target") || "";
      handleNavClick(panel);
      return;
    }
    const suggest = target.closest("[data-suggest]");
    if (suggest) {
      const promptText = suggest.getAttribute("data-suggest") || "";
      nodes.prompt.value = promptText;
      autoGrow(nodes.prompt);
      nodes.prompt.focus();
      renderShell();
      return;
    }
    const approval = target.closest("[data-approval-action]");
    if (approval) {
      const action = approval.getAttribute("data-approval-action") || "";
      const id = approval.getAttribute("data-approval-id") || "";
      withButton(approval, handleApproval(id, action));
      return;
    }
    const fileToggle = target.closest("[data-file-toggle]");
    if (fileToggle) {
      const path = fileToggle.getAttribute("data-file-toggle") || ".";
      withButton(fileToggle, toggleDirectory(path));
      return;
    }
    const fileOpen = target.closest("[data-file-open]");
    if (fileOpen) {
      const path = fileOpen.getAttribute("data-file-open") || "";
      readFilePreview(path).catch(showError);
      return;
    }
    const rewind = target.closest("[data-rewind-id]");
    if (rewind) {
      withButton(rewind, rewindCheckpoint(rewind.getAttribute("data-rewind-id") || ""));
      return;
    }
    const session = target.closest("[data-session-id]");
    if (session) {
      selectSession(session.getAttribute("data-session-id") || "").catch(showError);
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") schedulePoll(0);
  });
}

function handleNavClick(target) {
  if (!target) return;
  if (target === "workbench") {
    nodes.sessionsPanel.classList.remove("open");
    setNavActive("workbench");
    nodes.prompt.focus({ preventScroll: true });
    return;
  }
  if (target === "sessions") {
    nodes.sessionsPanel.classList.toggle("open");
    return;
  }
  const tabName = NAV_TO_TAB[target];
  if (tabName) selectTab(tabName);
}

function setNavActive(target) {
  document.querySelectorAll(".nav-entry").forEach(item => {
    item.classList.toggle("active", item.getAttribute("data-panel-target") === target);
  });
}

function selectTab(tabName, options = {}) {
  if (!tabName) return;
  state.activeTab = tabName;
  document.querySelectorAll(".tab").forEach(el => {
    el.classList.toggle("active", el.getAttribute("data-tab") === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach(el => {
    const matches = el.getAttribute("data-tab") === tabName;
    if (matches) el.removeAttribute("hidden");
    else el.setAttribute("hidden", "");
  });
  // sync nav highlight
  const navTarget = Object.entries(NAV_TO_TAB).find(([, v]) => v === tabName)?.[0] || tabName;
  setNavActive(navTarget);
  nodes.sessionsPanel.classList.remove("open");
  if (!options.initial) {
    const panel = document.querySelector(`.tab-panel[data-tab="${tabName}"]`);
    if (panel) panel.scrollIntoView({ block: "nearest" });
  }
}

function toggleTerminal() {
  state.terminalOpen = !state.terminalOpen;
  if (state.terminalOpen) {
    nodes.terminalPane.removeAttribute("hidden");
    nodes.toggleTerminal.setAttribute("aria-pressed", "true");
  } else {
    nodes.terminalPane.setAttribute("hidden", "");
    nodes.toggleTerminal.setAttribute("aria-pressed", "false");
  }
  renderTerminal();
}

async function request(path, options = {}) {
  const init = {
    method: options.method || "GET",
    headers: { "Content-Type": "application/json" }
  };
  if (options.body !== undefined) init.body = JSON.stringify(options.body);
  const response = await fetch(path, init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `${response.status} ${response.statusText}`);
  state.lastError = "";
  return payload;
}

async function refreshWorkspace() {
  const [health, workspace, capabilities, sessions] = await Promise.all([
    request("/api/health"),
    request("/api/workspace"),
    request("/api/capabilities"),
    request("/api/sessions")
  ]);
  state.workspacePath = workspace.workspace || health.workspace || "";
  nodes.workspace.textContent = state.workspacePath || "当前工作区";
  setInputValue(nodes.workspacePath, state.workspacePath);
  state.capabilities = capabilities.capabilities || [];
  state.sessions = sessions.sessions || [];
  if (!state.sessionId && state.sessions.length > 0) {
    state.sessionId = state.sessions[0].session_id;
  }
  await Promise.all([refreshSession(), refreshFiles(false), refreshRepo(), refreshReport(), refreshApiConfig()]);
  render();
}

async function switchWorkspace() {
  const workspace = nodes.workspacePath.value.trim();
  if (!workspace) {
    showToast("先输入要切换的工作区路径");
    return;
  }
  const payload = await request("/api/workspace/switch", { method: "POST", body: { workspace } });
  state.workspacePath = payload.workspace || workspace;
  state.sessionId = "";
  state.cursor = 0;
  state.events = [];
  state.localEvents = [];
  state.sessions = [];
  state.snapshot = null;
  state.approvals = [];
  state.checkpoints = [];
  state.fileTree = {};
  state.expandedDirs = new Set(["."]);
  state.selectedFile = null;
  state.filePreview = null;
  state.renderCache = {};
  await refreshWorkspace();
  await createSession();
  showToast(`已切换工作区：${state.workspacePath}`, "success");
}

async function refreshFiles(force) {
  if (force) state.fileTree = {};
  if (!state.fileTree["."] || force) {
    await loadDirectory(".");
  }
  renderFiles();
}

async function loadDirectory(path) {
  const key = normalizeTreePath(path);
  const payload = await request(`/api/files/tree?path=${encodeURIComponent(key)}`);
  state.fileTree[key] = payload;
  state.expandedDirs.add(key);
  return payload;
}

async function toggleDirectory(path) {
  const key = normalizeTreePath(path);
  if (state.expandedDirs.has(key)) {
    state.expandedDirs.delete(key);
  } else {
    if (!state.fileTree[key]) await loadDirectory(key);
    state.expandedDirs.add(key);
  }
  renderFiles();
}

async function readFilePreview(path) {
  if (!path) return;
  const payload = await request(`/api/files/read?path=${encodeURIComponent(path)}`);
  state.selectedFile = path;
  state.filePreview = payload;
  renderFiles();
}
async function createSession() {
  const created = await request("/api/sessions", { method: "POST", body: {} });
  state.sessionId = created.session_id;
  state.cursor = 0;
  state.events = [];
  state.localEvents = [];
  state.renderCache = {};
  await refreshWorkspace();
  showToast(`已创建新任务 ${shortId(state.sessionId)}`, "success");
}

async function selectSession(sessionId) {
  if (!sessionId || sessionId === state.sessionId) {
    nodes.sessionsPanel.classList.remove("open");
    return;
  }
  state.sessionId = sessionId;
  state.cursor = 0;
  state.events = [];
  state.localEvents = [];
  state.renderCache = {};
  nodes.sessionsPanel.classList.remove("open");
  await refreshSession();
  await poll();
  showToast(`已切换到 ${shortId(sessionId)}`);
}

async function refreshSession() {
  if (!state.sessionId) return;
  const [snapshot, approvals, checkpoints] = await Promise.all([
    request(`/api/sessions/${encodeURIComponent(state.sessionId)}`),
    request(`/api/sessions/${encodeURIComponent(state.sessionId)}/approvals?status=pending`),
    request(`/api/sessions/${encodeURIComponent(state.sessionId)}/checkpoints`)
  ]);
  state.snapshot = snapshot;
  state.approvals = approvals.approvals || [];
  state.checkpoints = checkpoints.checkpoints || [];
}

async function poll() {
  if (!state.sessionId) return false;
  const payload = await request(`/api/sessions/${encodeURIComponent(state.sessionId)}/events?after=${state.cursor}`);
  let hadNew = false;
  if (Array.isArray(payload.events) && payload.events.length > 0) {
    state.events.push(...payload.events);
    state.cursor = payload.next_cursor || state.cursor;
    hadNew = true;
  }
  await refreshSession();
  render();
  return hadNew;
}

function schedulePoll(delay) {
  if (pollTimer) {
    window.clearTimeout(pollTimer);
    pollTimer = 0;
  }
  const wait = delay !== undefined ? delay : pollInterval;
  pollTimer = window.setTimeout(async () => {
    if (document.visibilityState === "visible") {
      try {
        const hadNew = await poll();
        pollInterval = (hadNew || isAgentRunning()) ? POLL_FAST : POLL_SLOW;
      } catch (err) {
        showError(err);
        pollInterval = POLL_SLOW;
      }
    }
    schedulePoll();
  }, wait);
}

async function sendPrompt() {
  const prompt = nodes.prompt.value.trim();
  if (!prompt) {
    setPromptFeedback("先输入任务内容。");
    return;
  }
  if (!state.sessionId) await createSession();
  if (isAgentRunning()) {
    setPromptFeedback("上一轮任务还在运行，等它完成后再发送。");
    return;
  }

  state.busy = true;
  state.localEvents.push({ type: "local_user_prompt", message: prompt, timestamp: Date.now() / 1000 });
  nodes.prompt.value = "";
  autoGrow(nodes.prompt);
  setPromptFeedback("正在交给 Agent...");
  render();
  pollInterval = POLL_FAST;

  try {
    await request(`/api/sessions/${encodeURIComponent(state.sessionId)}/prompt`, {
      method: "POST",
      body: { prompt }
    });
    await poll();
  } finally {
    state.busy = false;
    setPromptFeedback("");
    render();
    schedulePoll(POLL_FAST);
  }
}

async function handleApproval(approvalId, action) {
  if (!approvalId || !state.sessionId) return;
  const endpoint = action === "reject" ? "reject" : "approve";
  await request(`/api/sessions/${encodeURIComponent(state.sessionId)}/${endpoint}`, {
    method: "POST",
    body: { approval_id: approvalId }
  });
  await poll();
  showToast(endpoint === "approve" ? "已批准操作" : "已拒绝操作", "success");
}

async function createCheckpoint() {
  if (!state.sessionId) return;
  await request(`/api/sessions/${encodeURIComponent(state.sessionId)}/checkpoint`, {
    method: "POST",
    body: { label: "web checkpoint" }
  });
  await poll();
  showToast("已创建检查点", "success");
}

async function rewindCheckpoint(checkpointId) {
  if (!checkpointId || !state.sessionId) return;
  await request(`/api/sessions/${encodeURIComponent(state.sessionId)}/rewind`, {
    method: "POST",
    body: { checkpoint_id: checkpointId }
  });
  await poll();
  showToast("已回滚到检查点", "success");
}

async function cancelRun() {
  if (!state.sessionId) return;
  if (!isAgentRunning()) {
    showToast("当前没有正在运行的任务");
    return;
  }
  const result = await request(`/api/sessions/${encodeURIComponent(state.sessionId)}/cancel`, {
    method: "POST",
    body: {}
  });
  await poll();
  const drained = result?.drained_jobs || 0;
  showToast(drained ? `已取消任务，并清理 ${drained} 个队列任务` : "已请求中断 Agent 任务", "success");
}

async function refreshMemoryIndex() {
  const payload = await request("/api/memory/index", { method: "POST", body: { max_files: 300 } });
  const index = payload.index || {};
  state.localEvents.push({
    type: "memory_index_refreshed",
    message: `已重建记忆索引：${index.chunk_count || 0} 个片段，${index.file_count || 0} 个文件`,
    timestamp: Date.now() / 1000
  });
  render();
  showToast("记忆索引已刷新", "success");
}

async function searchMemory() {
  const query = nodes.memoryQuery.value.trim();
  if (!query) {
    showToast("请输入记忆搜索关键词");
    return;
  }
  const payload = await request(`/api/memory/search?query=${encodeURIComponent(query)}&limit=6`);
  state.memoryHits = payload.hits || [];
  renderMemory();
  showToast(`找到 ${state.memoryHits.length} 条结果`, "success");
}

async function refreshRepo() {
  const [status, cache] = await Promise.all([
    request("/api/repo/status"),
    request("/api/repo/cache")
  ]);
  state.repoStatus = status.git || null;
  state.repoCache = cache.imports || [];
}

async function refreshReport() {
  state.report = await request("/api/reports/latest");
}

async function refreshApiConfig() {
  const [config, providers, readiness] = await Promise.all([
    request("/api/config"),
    request("/api/models/providers"),
    request("/api/models/readiness")
  ]);
  state.config = config;
  state.providers = providers.providers || [];
  state.providerReadiness = readiness.providers || [];
}

async function saveApiConfig() {
  const apiKeyEnv = nodes.apiKeyEnv.value.trim();
  if (looksLikeSecret(apiKeyEnv)) {
    showToast("这里填写环境变量名，比如 CODEMUSE_API_KEY，不要直接粘贴 API Key。");
    nodes.apiKeyEnv.focus();
    return;
  }
  const values = [
    ["model.provider", nodes.apiProvider.value.trim() || "fake"],
    ["model.model", nodes.apiModel.value.trim() || "fake-local"],
    ["model.base_url", nodes.apiBaseUrl.value.trim()],
    ["model.api_key_env", apiKeyEnv]
  ];
  for (const [path, value] of values) {
    await request("/api/config/set", { method: "POST", body: { path, value } });
  }
  await refreshApiConfig();
  renderApiConfig();
  showToast("模型配置已保存。API Key 请通过环境变量提供。", "success");
}

async function runCommand(command) {
  if (!command) return;
  if (command.startsWith("/memory ")) {
    const query = command.replace(/^\/memory\s+/, "").trim();
    nodes.memoryQuery.value = query;
    selectTab("memory");
    await searchMemory();
  } else if (command === "/new") {
    await createSession();
  } else if (command === "/refresh") {
    await refreshWorkspace();
    showToast("工作台已刷新", "success");
  } else {
    nodes.prompt.value = command;
    autoGrow(nodes.prompt);
    nodes.prompt.focus();
    setPromptFeedback("已放入输入框，按 Enter 发送");
  }
  nodes.commandInput.value = "";
}

/* ============ RENDERING ============ */
function render() {
  renderShell();
  renderSessions();
  renderEvents();
  renderTerminal();
  renderApprovals();
  renderCheckpoints();
  renderFiles();
  renderMemory();
  renderRepo();
  renderReport();
  renderApiConfig();
  renderCapabilities();
}

function setText(node, value) {
  const str = String(value);
  if (node && node.textContent !== str) node.textContent = str;
}
function setClass(node, name, on) {
  if (!node) return;
  if (node.classList.contains(name) !== !!on) node.classList.toggle(name, !!on);
}
function setDisabled(node, disabled) {
  if (!node) return;
  if (node.disabled !== !!disabled) node.disabled = !!disabled;
}

function renderShell() {
  const phase = state.snapshot?.state?.phase || "idle";
  const pending = state.snapshot?.pending_jobs || 0;
  const running = isAgentRunning();
  const total = state.sessions.length;
  const runningSessions = state.sessions.filter(s => (s.state?.phase || "") === "running").length;
  const failedSessions = state.sessions.filter(s => (s.state?.phase || "") === "failed").length;
  const status = state.lastError || phaseLabel(phase);

  setText(nodes.sessionState, state.sessionId ? shortId(state.sessionId) : "暂无会话");
  setText(nodes.statSession, state.sessionId ? shortId(state.sessionId) : "未创建");
  setText(nodes.phaseState, phase);
  setText(nodes.queueCount, pending);
  setText(nodes.runtimeStatus, running ? "Agent 运行中" : "Agent 空闲");
  setText(nodes.agentMotionLabel, running ? "正在处理当前任务" : "等待下一条任务");
  setText(nodes.statusPill, status);

  setClass(nodes.statusPill, "running", running);
  setClass(nodes.statusPill, "failed", phase === "failed");
  setClass(nodes.statusPill, "completed", phase === "completed");
  setClass(nodes.statusDot, "running", running);
  setClass(nodes.statusDot, "failed", phase === "failed");
  setClass(nodes.agentMascot, "running", running);
  setClass(nodes.agentMascot, "idle", !running);

  setText(nodes.sessionTotal, total);
  setText(nodes.activeCount, runningSessions);
  setText(nodes.activeRunCount, running ? Math.max(1, runningSessions) : runningSessions);
  setText(nodes.failedCount, failedSessions);
  setText(nodes.approvalCount, state.approvals.length);
  setText(nodes.checkpointCount, state.checkpoints.length);
  setText(nodes.navApprovalHint, state.approvals.length ? `${state.approvals.length} 个待审批` : "无需审批");
  setText(nodes.navSessionsHint, `${total} 个会话`);
  if (nodes.navApprovalBadge) {
    if (state.approvals.length) nodes.navApprovalBadge.removeAttribute("hidden");
    else nodes.navApprovalBadge.setAttribute("hidden", "");
  }

  setDisabled(nodes.send, !nodes.prompt.value.trim() || running);
  setDisabled(nodes.stopButton, !running);
}

function fingerprint(obj) {
  try { return JSON.stringify(obj); } catch { return String(obj); }
}
function shouldSkip(key, fp) {
  if (state.renderCache[key] === fp) return true;
  state.renderCache[key] = fp;
  return false;
}

function renderSessions() {
  const fp = fingerprint({
    s: state.sessions.map(s => [s.session_id, s.state?.phase, s.updated_at, s.created_at]),
    active: state.sessionId
  });
  if (shouldSkip("sessions", fp)) return;

  if (!state.sessions.length) {
    nodes.sessions.innerHTML = emptyHtml("暂无历史会话");
    return;
  }
  nodes.sessions.innerHTML = state.sessions.slice(0, 40).map(session => {
    const id = session.session_id || "";
    const active = id === state.sessionId ? " active" : "";
    const phase = phaseLabel(session.state?.phase || "idle");
    return `<button class="session-row${active}" data-session-id="${escapeHtml(id)}" type="button">
      <span><strong>${escapeHtml(shortId(id))}</strong><small>${escapeHtml(phase)}</small></span>
      <em>${escapeHtml(formatTime(session.updated_at || session.created_at))}</em>
    </button>`;
  }).join("");
}

function renderEvents() {
  const allItems = orderedEvents();
  const visibleItems = conversationEvents(allItems).slice(-120);
  const detailItems = detailEvents(allItems).slice(-160);
  const fp = fingerprint({
    visible: visibleItems.map(event => [event.type, event.timestamp, event.message, event.delta]),
    detailCount: detailItems.length,
    lastDetail: detailItems[detailItems.length - 1]?.timestamp || 0
  });
  if (shouldSkip("events", fp)) return;

  const nearBottom = nodes.events.scrollHeight - nodes.events.scrollTop - nodes.events.clientHeight < 120;
  if (!visibleItems.length) {
    nodes.events.innerHTML = welcomeHtml();
  } else {
    const detailBlock = detailItems.length ? renderConversationDetails(detailItems) : "";
    nodes.events.innerHTML = visibleItems.map(renderConversationItem).join("") + detailBlock;
  }
  if (nearBottom) nodes.events.scrollTop = nodes.events.scrollHeight;
}

function orderedEvents() {
  return state.localEvents
    .concat(state.events)
    .map((event, index) => ({ ...event, __order: index }))
    .sort((a, b) => eventTime(a) - eventTime(b) || a.__order - b.__order);
}

function eventTime(event) {
  const raw = Number(event?.timestamp || 0);
  return Number.isFinite(raw) ? raw : 0;
}

function conversationEvents(items) {
  const output = [];
  for (const event of items) {
    const type = event.type || "";
    const text = event.message || event.delta || "";
    if (type === "local_user_prompt") {
      output.push(event);
      continue;
    }
    if (isAssistantEvent(type) && text.trim()) {
      output.push(event);
      continue;
    }
    if (isUserVisibleError(event)) {
      output.push(event);
    }
  }
  return output;
}

function detailEvents(items) {
  return items.filter(event => {
    const type = event.type || "";
    if (type === "local_user_prompt") return false;
    if (isAssistantEvent(type) && (event.message || event.delta || "").trim()) return false;
    return true;
  });
}

function isUserVisibleError(event) {
  const type = event.type || "";
  return event.is_error || type === "error" || type.endsWith("_failed");
}

function welcomeHtml() {
  const cards = SUGGESTS.map(s => `
    <button class="welcome-suggest" data-suggest="${escapeHtml(s.prompt)}" type="button">
      <strong>${escapeHtml(s.label)}</strong>
      <small>${escapeHtml(s.hint)}</small>
    </button>
  `).join("");
  return `<div class="welcome">
    <div class="welcome-mark" aria-hidden="true">
      <svg viewBox="0 0 24 24" width="28" height="28"><path fill="currentColor" d="M12 2 4 7v10l8 5 8-5V7Zm0 2.3 5.5 3.4v8.6L12 19.7l-5.5-3.4V7.7Zm0 3.7L8 10.4v3.2l4 2.4 4-2.4v-3.2Z"/></svg>
    </div>
    <h2>把任务交给 CodeMuse 吧</h2>
    <p>可以查看文件、检索记忆、分析仓库，也可以直接描述你想修改的代码。</p>
    <div class="welcome-suggests">${cards}</div>
  </div>`;
}

function renderConversationItem(event) {
  const type = event.type || "";
  const text = event.message || event.delta || "";
  if (type === "local_user_prompt") {
    return messageHtml("user", "你", text, "你", event.timestamp);
  }
  if (isAssistantEvent(type)) {
    return messageHtml("assistant", "CodeMuse", text, "CM", event.timestamp);
  }
  return messageHtml("error", "错误", text || detailsText(event.details) || "暂无详情", "!", event.timestamp);
}

function renderConversationDetails(items) {
  const toolCount = items.filter(event => event.tool_name || String(event.type || "").startsWith("tool_")).length;
  const approvalCount = items.filter(event => event.type === "approval_required").length;
  const errorCount = items.filter(event => event.is_error || String(event.type || "").endsWith("_failed")).length;
  return `<details class="run-details">
    <summary>
      <span>执行细节</span>
      <small>${items.length} 个事件 · ${toolCount} 个工具 · ${approvalCount} 个审批 · ${errorCount} 个错误</small>
    </summary>
    <div class="run-event-list">${items.map(renderDetailItem).join("")}</div>
  </details>`;
}

function renderDetailItem(event) {
  const type = event.type || "";
  const text = event.message || event.delta || "";
  const title = event.tool_name ? `${eventLabel(type)} / ${toolLabel(event.tool_name)}` : eventLabel(type);
  const details = [text, detailsText(event.details)].filter(Boolean).join("\n\n") || "暂无详情";
  const cls = event.is_error || type.endsWith("_failed") ? " error" : event.type === "approval_required" ? " warning" : "";
  return `<article class="run-event${cls}">
    <header><strong>${escapeHtml(title)}</strong><time>${escapeHtml(formatTime(event.timestamp))}</time></header>
    <pre>${escapeHtml(details)}</pre>
  </article>`;
}

function renderEventItem(event) {
  return renderConversationItem(event);
}

function messageHtml(kind, label, text, avatar, timestamp) {
  const time = timestamp ? `<time>${escapeHtml(formatTime(timestamp))}</time>` : "";
  return `<article class="message ${kind}">
    <div class="message-avatar">${escapeHtml(avatar)}</div>
    <div class="bubble">
      <span class="bubble-label">${escapeHtml(label)}${time}</span>
      <p>${escapeHtml(text || "暂无内容")}</p>
    </div>
  </article>`;
}

function renderTerminal() {
  if (!state.terminalOpen) return;
  const items = state.localEvents.concat(state.events).slice(-80);
  const fp = items.length + ":" + (items[items.length - 1]?.timestamp || 0) + ":" + (state.snapshot?.state?.phase || "");
  if (shouldSkip("terminal", fp)) return;

  const lines = [
    `<div><span class="ok">workspace</span> <span class="dim">${escapeHtml(nodes.workspace.textContent || "")}</span></div>`,
    `<div><span class="ok">session</span> ${escapeHtml(state.sessionId ? shortId(state.sessionId) : "none")} <span class="dim">phase=${escapeHtml(state.snapshot?.state?.phase || "idle")}</span></div>`
  ];
  for (const event of items) {
    const cls = event.is_error || String(event.type || "").endsWith("_failed") ? "err" : event.type === "approval_required" ? "warn" : "dim";
    const label = event.tool_name ? `${event.type}:${event.tool_name}` : event.type;
    const text = event.message || event.delta || summarizeDetails(event.details) || "";
    lines.push(`<div><span class="${cls}">[${escapeHtml(label || "event")}]</span> ${escapeHtml(text)}</div>`);
  }
  nodes.terminalFeed.innerHTML = lines.join("");
  nodes.terminalFeed.scrollTop = nodes.terminalFeed.scrollHeight;
}

function renderApprovals() {
  const fp = fingerprint(state.approvals.map(a => [a.approval_id, a.tool_name, a.reason]));
  if (shouldSkip("approvals", fp)) return;

  if (!state.approvals.length) {
    nodes.approvals.innerHTML = emptyHtml("当前没有待审批操作");
    return;
  }
  nodes.approvals.innerHTML = state.approvals.map(item => {
    const id = item.approval_id || "";
    return `<article class="item-card">
      <strong>${escapeHtml(toolLabel(item.tool_name || "unknown"))}</strong>
      <small>${escapeHtml(id)}</small>
      <p>${escapeHtml(item.reason || summarizeDetails(item.details) || "该操作需要你确认后继续")}</p>
      <div class="approval-actions">
        <button data-approval-action="approve" data-approval-id="${escapeHtml(id)}" type="button">批准</button>
        <button data-approval-action="reject" data-approval-id="${escapeHtml(id)}" type="button">拒绝</button>
      </div>
    </article>`;
  }).join("");
}

function renderCheckpoints() {
  const fp = fingerprint(state.checkpoints.map(c => [c.checkpoint_id, c.label]));
  if (shouldSkip("checkpoints", fp)) return;

  if (!state.checkpoints.length) {
    nodes.checkpoints.innerHTML = emptyHtml("暂无检查点");
    return;
  }
  nodes.checkpoints.innerHTML = state.checkpoints.slice(0, 10).map(item => {
    const id = item.checkpoint_id || "";
    return `<article class="item-card checkpoint-row">
      <span><strong>${escapeHtml(shortId(id))}</strong><small>${escapeHtml(item.label || "未命名")}</small></span>
      <button data-rewind-id="${escapeHtml(id)}" type="button">回滚</button>
    </article>`;
  }).join("");
}

function renderFiles() {
  if (!nodes.fileTree || !nodes.filePreview) return;
  const fp = fingerprint({
    tree: Object.fromEntries(Object.entries(state.fileTree).map(([key, value]) => [key, (value.entries || []).map(item => [item.path, item.kind, item.size])])),
    expanded: Array.from(state.expandedDirs).sort(),
    selected: state.selectedFile,
    preview: state.filePreview && [state.filePreview.path, state.filePreview.size, state.filePreview.content]
  });
  if (shouldSkip("files", fp)) return;

  const root = state.fileTree["."];
  if (!root) {
    nodes.fileTree.innerHTML = emptyHtml("正在加载文件树");
  } else {
    nodes.fileTree.innerHTML = renderDirectoryEntries(".", 0);
  }

  if (!state.filePreview) {
    nodes.filePreview.innerHTML = `<div class="file-empty"><strong>选择一个文件</strong><span>点击左侧文件树中的文件后，这里会显示内容预览。</span></div>`;
    return;
  }
  const preview = state.filePreview;
  const content = preview.binary ? preview.content : String(preview.content || "");
  nodes.filePreview.innerHTML = `<article class="file-preview-card">
    <header>
      <div>
        <strong>${escapeHtml(preview.name || preview.path || "file")}</strong>
        <small>${escapeHtml(preview.path || "")} · ${escapeHtml(formatBytes(preview.size || 0))}</small>
      </div>
    </header>
    <pre>${escapeHtml(content || "空文件")}</pre>
  </article>`;
}

function renderDirectoryEntries(path, depth) {
  const key = normalizeTreePath(path);
  const payload = state.fileTree[key];
  const entries = payload?.entries || [];
  if (!entries.length) {
    return depth === 0 ? emptyHtml("当前目录没有可显示的文件") : "";
  }
  return entries.map(item => {
    const isDir = item.kind === "directory";
    const expanded = state.expandedDirs.has(item.path);
    const selected = state.selectedFile === item.path ? " selected" : "";
    const indent = Math.min(depth * 14, 84);
    if (isDir) {
      const children = expanded ? renderDirectoryEntries(item.path, depth + 1) : "";
      return `<div class="file-branch">
        <button class="file-row directory${expanded ? " expanded" : ""}" data-file-toggle="${escapeHtml(item.path)}" style="--indent:${indent}px" type="button">
          <span class="file-caret">${expanded ? "▾" : "▸"}</span>
          <span class="file-icon">📁</span>
          <span class="file-name">${escapeHtml(item.name)}</span>
        </button>
        ${children ? `<div class="file-children">${children}</div>` : ""}
      </div>`;
    }
    return `<button class="file-row file${selected}" data-file-open="${escapeHtml(item.path)}" style="--indent:${indent}px" type="button">
      <span class="file-caret"></span>
      <span class="file-icon">📄</span>
      <span class="file-name">${escapeHtml(item.name)}</span>
      <span class="file-size">${escapeHtml(formatBytes(item.size || 0))}</span>
    </button>`;
  }).join("");
}

function renderMemory() {
  const fp = fingerprint(state.memoryHits.map(h => [h.path, h.start_line, h.score]));
  if (shouldSkip("memory", fp)) return;

  if (!state.memoryHits.length) {
    nodes.memoryResults.innerHTML = emptyHtml("输入关键词搜索记忆，或先点击重建索引。");
    return;
  }
  nodes.memoryResults.innerHTML = state.memoryHits.map(hit => {
    const path = hit.path || hit.source || "memory";
    const line = hit.start_line ? `:${hit.start_line}` : "";
    const score = Number(hit.score || 0).toFixed(2);
    return `<article class="item-card">
      <strong>${escapeHtml(hit.title || path)}</strong>
      <small>${escapeHtml(path + line)} · 相关度 ${escapeHtml(score)}</small>
      <p>${escapeHtml(String(hit.content || "").slice(0, 240))}</p>
    </article>`;
  }).join("");
}

function renderRepo() {
  const fp = fingerprint({ status: state.repoStatus, cache: state.repoCache });
  if (shouldSkip("repo", fp)) return;

  if (!state.repoStatus) {
    nodes.repoStatus.textContent = "尚未加载仓库状态";
  } else if (state.repoStatus.is_git_repo) {
    const changed = Array.isArray(state.repoStatus.status) ? state.repoStatus.status.length : 0;
    nodes.repoStatus.textContent = `${state.repoStatus.branch || "detached"} · ${state.repoStatus.commit || ""} · ${changed} 个变更`;
  } else {
    nodes.repoStatus.textContent = "当前目录不是 Git 仓库";
  }
  nodes.repoCache.innerHTML = state.repoCache.length
    ? state.repoCache.slice(0, 4).map(item => `<article class="item-card">
        <strong>${escapeHtml(item.repo_id || item.source || "import")}</strong>
        <small>${escapeHtml(item.imported_path || item.destination || "")}</small>
      </article>`).join("")
    : emptyHtml("暂无导入记录");
}

function renderReport() {
  const fp = fingerprint(state.report);
  if (shouldSkip("report", fp)) return;
  if (!state.report || !state.report.exists || !state.report.report) {
    nodes.reportSummary.textContent = "暂无";
    return;
  }
  const report = state.report.report;
  const total = report.total_cases ?? report.total ?? 0;
  const passed = report.passed ?? 0;
  const failed = report.failed ?? Math.max(0, total - passed);
  nodes.reportSummary.textContent = `${passed}/${total} 通过 · ${failed} 失败`;
}

function renderApiConfig() {
  const fp = fingerprint({ c: state.config, p: state.providers, r: state.providerReadiness });
  if (shouldSkip("api", fp)) return;

  renderProviderOptions();
  const model = state.config?.config?.model || state.config?.model || {};
  setInputValue(nodes.apiProvider, model.provider || "fake");
  setInputValue(nodes.apiModel, model.model || "fake-local");
  setInputValue(nodes.apiBaseUrl, model.base_url || "");
  setInputValue(nodes.apiKeyEnv, model.api_key_env || "");

  const current = readinessFor(nodes.apiProvider.value || "fake");
  nodes.apiStatus.textContent = current
    ? `${providerLabel(current.name)}：${current.ready ? "已就绪" : "未就绪"}${current.api_key_env ? `，环境变量 ${current.api_key_env}` : ""}`
    : `${providerLabel(nodes.apiProvider.value || "fake")} 尚未检查`;

  nodes.providerList.innerHTML = state.providerReadiness.length
    ? state.providerReadiness.map(item => {
      const cls = item.ready ? "ok" : item.implemented === false ? "err" : "warn";
      const text = item.ready ? "可用" : item.implemented === false ? "未实现" : "未就绪";
      return `<article class="item-card">
        <strong>${escapeHtml(providerLabel(item.name))} <span class="badge ${cls}">${escapeHtml(text)}</span></strong>
        <small>${escapeHtml(item.model || item.api_key_env || "未配置")}</small>
      </article>`;
    }).join("")
    : emptyHtml("暂无 Provider 信息");
}

function renderProviderOptions() {
  const providers = state.providers.length ? state.providers : state.providerReadiness;
  const names = providers.length ? providers.map(item => item.name || item.provider || String(item)) : ["fake"];
  const uniq = [...new Set(names)];
  const existing = Array.from(nodes.apiProvider.options).map(o => o.value).join("|");
  const next = uniq.join("|");
  if (existing === next) return;
  const current = nodes.apiProvider.value;
  nodes.apiProvider.innerHTML = uniq.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(providerLabel(name))}</option>`).join("");
  if (current && Array.from(nodes.apiProvider.options).some(o => o.value === current)) {
    nodes.apiProvider.value = current;
  }
}

function renderCapabilities() {
  const fp = fingerprint(state.capabilities.map(c => [c.name, c.risk_level, c.kind]));
  if (shouldSkip("capabilities", fp)) return;

  if (!state.capabilities.length) {
    nodes.capabilities.innerHTML = emptyHtml("暂无可用能力");
    return;
  }
  nodes.capabilities.innerHTML = state.capabilities.slice(0, 28).map(item => {
    const risk = item.risk_level === "high" || item.risk_level === "medium" ? "warn" : "ok";
    return `<article class="item-card">
      <strong>${escapeHtml(toolLabel(item.name))} <span class="badge ${risk}">${escapeHtml(riskLabel(item.risk_level))}</span></strong>
      <small>${escapeHtml(kindLabel(item.kind))} · ${escapeHtml(item.name)}</small>
    </article>`;
  }).join("");
}

/* ============ HELPERS ============ */
/* ============ HELPERS ============ */
function applyProviderDefaults() {
  const ready = readinessFor(nodes.apiProvider.value);
  if (!nodes.apiModel.value.trim()) {
    nodes.apiModel.value = ready?.model || (nodes.apiProvider.value === "fake" ? "fake-local" : "");
  }
  if (!nodes.apiBaseUrl.value.trim() && ready?.base_url) {
    nodes.apiBaseUrl.value = ready.base_url;
  }
  if (!nodes.apiKeyEnv.value.trim() && ready?.api_key_env) {
    nodes.apiKeyEnv.value = ready.api_key_env;
  }
}

function startAvatarLoop() {
  window.clearInterval(state.avatarTimer);
  state.avatarTimer = window.setInterval(() => {
    const frames = isAgentRunning() ? workFrames : idleFrames;
    state.avatarFrame = (state.avatarFrame + 1) % frames.length;
    const next = frames[state.avatarFrame];
    if (nodes.agentMascot.getAttribute("src") !== next) nodes.agentMascot.src = next;
  }, 600);
}

function withButton(button, promise) {
  if (!(button instanceof HTMLElement)) {
    Promise.resolve(promise).catch(showError);
    return;
  }
  button.classList.add("is-pending");
  Promise.resolve(promise).catch(showError).finally(() => button.classList.remove("is-pending"));
}

function isAgentRunning() {
  const phase = state.snapshot?.state?.phase || "idle";
  const pending = state.snapshot?.pending_jobs || 0;
  return state.busy || phase === "running" || phase === "planning" || phase === "executing" || pending > 0;
}

function isAssistantEvent(type) {
  return ["assistant_delta", "assistant_message", "prompt_completed", "message"].includes(type);
}

function readinessFor(provider) {
  return state.providerReadiness.find(item => item.name === provider);
}

function setInputValue(input, value) {
  if (document.activeElement !== input && input.value !== value) input.value = value;
}

function autoGrow(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
}

function setPromptFeedback(text) {
  if (nodes.promptFeedback) nodes.promptFeedback.textContent = text;
}

function showError(error) {
  state.lastError = error?.message || String(error);
  showToast(state.lastError, "error");
  renderShell();
}

function showToast(text, kind) {
  nodes.toast.textContent = text;
  nodes.toast.classList.remove("toast-error", "toast-success");
  if (kind === "error") nodes.toast.classList.add("toast-error");
  if (kind === "success") nodes.toast.classList.add("toast-success");
  nodes.toast.classList.add("visible");
  window.clearTimeout(state.toastTimer);
  state.toastTimer = window.setTimeout(() => nodes.toast.classList.remove("visible"), 2600);
}

function emptyHtml(text) {
  return `<div class="empty">${escapeHtml(text)}</div>`;
}

function normalizeTreePath(path) {
  const clean = String(path || ".").replaceAll("\\", "/").replace(/^\/+/, "").replace(/\/+$/, "");
  return clean && clean !== "." ? clean : ".";
}

function formatBytes(value) {
  const size = Number(value || 0);
  if (!Number.isFinite(size) || size <= 0) return "0 B";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function detailsText(details) {
  if (!details || typeof details !== "object" || Object.keys(details).length === 0) return "";
  const normalized = {};
  for (const [key, value] of Object.entries(details)) {
    if (Array.isArray(value)) normalized[key] = value.length > 5 ? `${value.length} items` : value;
    else if (value && typeof value === "object") normalized[key] = summarizeObject(value);
    else normalized[key] = value;
  }
  const text = JSON.stringify(normalized, null, 2);
  return text.length > 1200 ? `${text.slice(0, 1200)}\n...` : text;
}

function summarizeDetails(details) {
  return detailsText(details).replace(/\s+/g, " ").slice(0, 180);
}

function summarizeObject(value) {
  const keys = Object.keys(value);
  if (keys.length > 8) return `${keys.length} fields`;
  return value;
}

function shortId(value) {
  return String(value || "").slice(0, 8);
}

function formatTime(value) {
  if (!value) return "";
  const number = Number(value);
  const date = Number.isFinite(number)
    ? new Date(number > 1000000000000 ? number : number * 1000)
    : new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function phaseLabel(value) {
  const labels = {
    idle: "Idle",
    running: "运行中",
    planning: "规划中",
    executing: "执行中",
    awaiting_approval: "等待审批",
    waiting_approval: "等待审批",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消"
  };
  return labels[value] || value || "Idle";
}

function eventLabel(value) {
  const labels = {
    ui_info: "界面信息",
    prompt_queued: "任务排队",
    prompt_started: "任务开始",
    prompt_completed: "任务完成",
    prompt_failed: "任务失败",
    approve_queued: "审批排队",
    approve_started: "审批开始",
    approve_completed: "审批完成",
    reject_queued: "拒绝排队",
    reject_started: "拒绝开始",
    reject_completed: "拒绝完成",
    checkpoint_queued: "检查点排队",
    checkpoint_started: "检查点开始",
    checkpoint_completed: "检查点完成",
    rewind_queued: "回滚排队",
    rewind_started: "回滚开始",
    rewind_completed: "回滚完成",
    tool_call: "调用工具",
    tool_result: "工具结果",
    tool_error: "工具错误",
    approval_required: "需要审批",
    approval_rejected: "审批拒绝",
    approval_stale: "审批已过期",
    approval_invalid: "审批无效",
    checkpoint_created: "检查点已创建",
    checkpoint_rewound: "检查点已回滚",
    assistant_delta: "助手输出",
    assistant_message: "助手消息",
    message: "消息",
    memory_index_refreshed: "记忆索引已刷新",
    cancel_requested: "已请求取消",
    agent_cancelled: "Agent 已取消",
    agent_start: "Agent 开始",
    agent_end: "Agent 结束",
    turn_start: "回合开始",
    turn_end: "回合结束",
    prompt_cancelled: "任务已取消",
    approve_cancelled: "审批已取消",
    reject_cancelled: "拒绝已取消",
    checkpoint_cancelled: "检查点已取消",
    rewind_cancelled: "回滚已取消"
  };
  return labels[value] || value || "未知";
}

function toolLabel(value) {
  const labels = {
    list_files: "列出文件",
    read_file: "读取文件",
    write_file: "写入文件",
    replace_text: "替换文本",
    apply_patch: "应用补丁",
    search_text: "搜索文本",
    save_project_memory: "保存项目记忆",
    search_project_memory: "搜索项目记忆",
    inspect_repo: "检查仓库",
    inspect_git_status: "检查 Git 状态",
    import_repo: "导入仓库",
    web_fetch_preview: "网页预览",
    delegate_to_subagent: "委派 Agent",
    run_extension: "运行扩展"
  };
  return labels[value] || value || "未知工具";
}

function kindLabel(value) {
  const labels = {
    builtin_tool: "内置工具",
    repo_tool: "仓库工具",
    memory_tool: "记忆工具",
    web_tool: "网页工具",
    subagent_tool: "子 Agent",
    mcp_tool: "MCP 工具",
    skill: "技能",
    extension: "扩展"
  };
  return labels[value] || value || "未知类型";
}

function riskLabel(value) {
  if (value === "high") return "高风险";
  if (value === "medium") return "中风险";
  return "低风险";
}

function providerLabel(value) {
  const labels = { fake: "本地模拟", openai_compatible: "OpenAI 兼容", bailian: "百炼" };
  return labels[value] || value || "Provider";
}

function looksLikeSecret(value) {
  const text = String(value || "").trim();
  if (!text) return false;
  if (/^(sk|pk|rk|ak)-/i.test(text)) return true;
  if (/^[A-Za-z0-9_\-]{32,}$/.test(text) && !/^[A-Z][A-Z0-9_]*$/.test(text)) return true;
  return false;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

