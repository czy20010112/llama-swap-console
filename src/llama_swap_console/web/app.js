"use strict";

const locales = {
  "zh-CN": {
    connecting: "正在连接", connected: "已连接", offline: "服务不可用", models: "模型",
    details: "详情", operations: "状态", library: "本地推理", running: "正在运行",
    allModels: "全部模型", discovered: "待登记模型", noneRunning: "暂无运行模型",
    searchModels: "搜索模型、路径或 ID", searchProcesses: "进程、服务或 PID",
    selectModel: "选择一个模型", load: "加载", unload: "卸载", editSettings: "编辑设置",
    registerModel: "登记模型", basicSettings: "基础设置", memoryContext: "显存与上下文",
    acceleration: "加速与缓存", compatibilityArgs: "兼容参数", gpu: "GPU",
    gpuProcesses: "WDDM 显存分配", liveLogs: "实时日志", loading: "加载中",
    allAdapters: "全部图形适配器", windowsAdapter: "Windows 适配器",
    disconnected: "连接已中断", structuredConfig: "结构化配置",
    saveNotice: "保存前将验证并备份当前配置", cancel: "取消", saveOnly: "仅保存",
    saveReload: "保存并重新加载", copied: "已复制", copyFailed: "复制失败，请检查浏览器剪贴板权限",
    scanComplete: "扫描完成", backend: "推理后端", modelPath: "模型路径",
    context: "上下文长度", status: "状态", unknown: "未知", noModels: "没有匹配的模型",
    modelId: "模型 ID", displayName: "显示名称", description: "描述", launcher: "启动程序",
    templateMissing: "当前后端没有可复用的受信任启动模板，请先在 llama-swap 配置中登记一个同后端模型",
    incomplete: "下载未完成", metadataUnreadable: "元数据不可读", ready: "可登记",
    size: "大小", quantization: "量化", architecture: "架构", mtp: "MTP",
    enabled: "已启用", disabled: "未启用", operationFailed: "操作失败",
    requiredIdentity: "模型 ID 和显示名称不能为空", invalidContext: "上下文长度必须在 512 到 262144 之间",
    gpuLayers: "GPU 层数", flashAttention: "Flash Attention", kvCacheK: "KV 缓存 K",
    kvCacheV: "KV 缓存 V", jinja: "Jinja 模板", mmproj: "视觉投影文件",
    draftModel: "草稿模型", specType: "推测类型", draftMax: "最大草稿 Token",
    temperature: "温度", topP: "Top P", topK: "Top K", minP: "Min P",
    repeatPenalty: "重复惩罚", gpuUtilization: "GPU 显存使用率", kvCacheDtype: "KV 缓存类型",
    dtype: "计算精度", maxSequences: "最大并发序列", maxBatchedTokens: "最大批处理 Token",
    chunkedPrefill: "分块预填充", trustRemoteCode: "信任远程代码", reasoningParser: "推理解析器",
    toolParser: "工具调用解析器", autoToolChoice: "自动工具选择", loadStrategy: "权重加载策略",
    mtpMethod: "推测方法", mtpModel: "推测模型", mtpTokens: "推测 Token 数", yes: "是", no: "否"
  },
  en: {
    connecting: "Connecting", connected: "Connected", offline: "Service unavailable", models: "Models",
    details: "Details", operations: "Status", library: "Local inference", running: "Running",
    allModels: "All models", discovered: "Unregistered", noneRunning: "No running models",
    searchModels: "Search model, path, or ID", searchProcesses: "Process, service, or PID",
    selectModel: "Select a model", load: "Load", unload: "Unload", editSettings: "Edit settings",
    registerModel: "Register model", basicSettings: "Basic settings", memoryContext: "Memory & context",
    acceleration: "Acceleration & cache", compatibilityArgs: "Compatibility arguments", gpu: "GPU",
    gpuProcesses: "WDDM allocations", liveLogs: "Live logs", loading: "Loading",
    allAdapters: "All graphics adapters", windowsAdapter: "Windows adapter",
    disconnected: "Disconnected", structuredConfig: "Structured configuration",
    saveNotice: "The current configuration will be validated and backed up", cancel: "Cancel",
    saveOnly: "Save", saveReload: "Save and reload", copied: "Copied",
    copyFailed: "Copy failed; check browser clipboard permissions", scanComplete: "Scan complete",
    backend: "Backend", modelPath: "Model path", context: "Context length", status: "Status",
    unknown: "Unknown", noModels: "No matching models", modelId: "Model ID",
    displayName: "Display name", description: "Description", launcher: "Launcher",
    templateMissing: "No trusted launcher template exists for this backend. Register one model in llama-swap first.",
    incomplete: "Download incomplete", metadataUnreadable: "Metadata unreadable", ready: "Ready",
    size: "Size", quantization: "Quantization", architecture: "Architecture", mtp: "MTP",
    enabled: "Enabled", disabled: "Disabled", operationFailed: "Operation failed",
    requiredIdentity: "Model ID and display name are required",
    invalidContext: "Context length must be between 512 and 262144",
    gpuLayers: "GPU layers", flashAttention: "Flash attention", kvCacheK: "KV cache K",
    kvCacheV: "KV cache V", jinja: "Jinja template", mmproj: "Vision projector",
    draftModel: "Draft model", specType: "Speculative type", draftMax: "Maximum draft tokens",
    temperature: "Temperature", topP: "Top P", topK: "Top K", minP: "Min P",
    repeatPenalty: "Repeat penalty", gpuUtilization: "GPU memory utilization", kvCacheDtype: "KV cache dtype",
    dtype: "Compute dtype", maxSequences: "Maximum sequences", maxBatchedTokens: "Maximum batched tokens",
    chunkedPrefill: "Chunked prefill", trustRemoteCode: "Trust remote code", reasoningParser: "Reasoning parser",
    toolParser: "Tool-call parser", autoToolChoice: "Automatic tool choice", loadStrategy: "Weight load strategy",
    mtpMethod: "Speculative method", mtpModel: "Speculative model", mtpTokens: "Speculative tokens",
    yes: "Yes", no: "No"
  }
};

const state = {
  locale: localStorage.getItem("llamaSwapConsole.locale") || "zh-CN",
  models: [], discovered: [], selectedId: null, currentModel: null, editingCandidate: null,
  query: "", processQuery: "", gpu: null, gpuAdapter: null, operationBusy: false, logSource: null,
  logRetry: 0, logTimer: null, operationPollTimer: null
};
const OPERATION_STATUS_POLL_MS = 1000;
const OPERATION_STATUS_MAX_POLLS = 30;
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const t = key => locales[state.locale][key] || key;

function applyLocale() {
  document.documentElement.lang = state.locale;
  $$('[data-i18n]').forEach(element => { element.textContent = t(element.dataset.i18n); });
  $$('[data-i18n-placeholder]').forEach(element => { element.placeholder = t(element.dataset.i18nPlaceholder); });
  $$('[data-i18n-title]').forEach(element => { element.title = t(element.dataset.i18nTitle); });
  $("#language-toggle").textContent = state.locale === "zh-CN" ? "EN" : "中";
  $("#dialog-language-toggle").textContent = state.locale === "zh-CN" ? "EN" : "中";
}

async function api(path, options = {}) {
  const response = await fetch(path, {headers: {"Content-Type": "application/json", ...(options.headers || {})}, ...options});
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const detail = (await response.json()).detail;
      message = Array.isArray(detail) ? detail.map(item => item.msg).join("; ") : detail || message;
    } catch {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function showToast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => element.classList.remove("show"), 2200);
}

function setConnection(online) {
  const element = $("#connection-status");
  element.classList.toggle("online", online);
  element.lastElementChild.textContent = t(online ? "connected" : "offline");
  updateCommandButtons(online);
}

function isActiveStatus(status) {
  return ["running", "loaded", "ready", "starting", "loading", "pending"].includes(status);
}

function updateCommandButtons(online = $("#connection-status").classList.contains("online")) {
  const status = state.currentModel?.status;
  const active = isActiveStatus(status);
  const transitioning = ["starting", "loading", "pending"].includes(status);
  $("#load-model").disabled = !online || state.operationBusy || active;
  $("#unload-model").disabled = !online || state.operationBusy || transitioning || !active;
}

function modelMatches(model) {
  const haystack = [model.id, model.name, model.settings?.model_path].filter(Boolean).join(" ").toLowerCase();
  return haystack.includes(state.query.toLowerCase());
}

function modelButton(model) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `model-row${model.id === state.selectedId ? " active" : ""}`;
  button.innerHTML = '<strong></strong><span class="mini-status"></span><code></code>';
  button.querySelector("strong").textContent = model.name || model.id;
  button.querySelector("code").textContent = model.id;
  button.querySelector(".mini-status").classList.toggle("running", isActiveStatus(model.status));
  button.addEventListener("click", () => selectModel(model.id));
  return button;
}

function renderModels() {
  const models = state.models.filter(modelMatches).sort((a, b) =>
    (a.name || a.id).localeCompare(b.name || b.id, state.locale, {sensitivity: "base"}));
  const list = $("#model-list");
  list.replaceChildren();
  $("#model-count").textContent = String(models.length);
  if (!models.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = t("noModels");
    list.append(empty);
  }
  models.forEach(model => list.append(modelButton(model)));
  const running = models.filter(model => isActiveStatus(model.status));
  $("#running-count").textContent = String(running.length);
  const runningList = $("#running-models");
  runningList.replaceChildren();
  if (!running.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = t("noneRunning");
    runningList.append(empty);
  } else {
    running.forEach(model => runningList.append(modelButton(model)));
  }
  renderDiscovered();
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "—";
  return bytes >= 1073741824 ? `${(bytes / 1073741824).toFixed(1)} GiB` : `${(bytes / 1048576).toFixed(0)} MiB`;
}

function renderDiscovered() {
  const list = $("#discovered-models");
  list.replaceChildren();
  const candidates = [...state.discovered].sort((a, b) => a.path.localeCompare(b.path, state.locale, {sensitivity: "base"}));
  $("#discovered-count").textContent = String(candidates.length);
  candidates.forEach(item => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `model-row candidate-row${item.complete ? "" : " incomplete"}`;
    button.disabled = !item.complete;
    button.innerHTML = '<strong></strong><span class="candidate-state"></span><code></code>';
    button.querySelector("strong").textContent = item.path.split(/[\\/]/).pop();
    button.querySelector(".candidate-state").textContent = item.complete ? t("ready") : t("incomplete");
    button.querySelector("code").textContent = [item.quantization || item.kind, formatBytes(item.size_bytes), item.has_mtp ? "MTP" : null].filter(Boolean).join(" · ");
    button.title = item.reason || "";
    button.addEventListener("click", () => openRegistration(item));
    list.append(button);
  });
}

function addDefinition(container, label, value) {
  const wrap = document.createElement("div");
  const term = document.createElement("dt");
  const detail = document.createElement("dd");
  term.textContent = label;
  detail.textContent = value ?? "—";
  wrap.append(term, detail);
  container.append(wrap);
}

const settingLabels = {
  n_gpu_layers: "gpuLayers", flash_attn: "flashAttention", cache_type_k: "kvCacheK",
  cache_type_v: "kvCacheV", jinja: "jinja", mmproj: "mmproj", model_draft: "draftModel",
  spec_type: "specType", spec_draft_n_max: "draftMax", temperature: "temperature",
  top_p: "topP", top_k: "topK", min_p: "minP", repeat_penalty: "repeatPenalty",
  gpu_memory_utilization: "gpuUtilization", kv_cache_dtype: "kvCacheDtype", dtype: "dtype",
  quantization: "quantization", max_num_seqs: "maxSequences", max_num_batched_tokens: "maxBatchedTokens",
  enable_chunked_prefill: "chunkedPrefill", trust_remote_code: "trustRemoteCode",
  reasoning_parser: "reasoningParser", tool_call_parser: "toolParser",
  enable_auto_tool_choice: "autoToolChoice", safetensors_load_strategy: "loadStrategy", speculative: "mtp"
};

function displayValue(value) {
  if (typeof value === "boolean") return t(value ? "yes" : "no");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function renderDetail(model) {
  $("#detail-empty").hidden = Boolean(model);
  $("#detail-content").hidden = !model;
  if (!model) return;
  $("#detail-name").textContent = model.name;
  $("#detail-id").textContent = model.id;
  $("#detail-description").textContent = model.description || "";
  const status = $("#detail-status");
  status.textContent = model.status || t("unknown");
  status.className = `status-pill ${isActiveStatus(model.status) ? "running" : ""}`;
  updateCommandButtons();
  const error = $("#compatibility-error");
  error.hidden = !model.compatibility_error;
  error.textContent = model.compatibility_error || "";
  const settings = model.settings;
  $("#edit-model").disabled = !settings;
  for (const id of ["#basic-settings", "#memory-settings", "#acceleration-settings"]) $(id).replaceChildren();
  if (!settings) return;
  addDefinition($("#basic-settings"), t("backend"), settings.backend === "vllm" ? "vLLM" : "llama.cpp");
  addDefinition($("#basic-settings"), t("modelPath"), settings.model_path);
  addDefinition($("#memory-settings"), t("context"), String(settings.context_length));
  const specific = settings[settings.backend === "vllm" ? "vllm" : "llama_cpp"] || {};
  Object.entries(specific).filter(([, value]) => value !== null && value !== false).forEach(([key, value]) =>
    addDefinition($("#acceleration-settings"), t(settingLabels[key] || key), displayValue(value)));
  const unknown = settings.unknown_tokens || [];
  $("#unknown-section").hidden = !unknown.length;
  $("#unknown-args").textContent = unknown.join(" ");
}

async function selectModel(id) {
  state.selectedId = id;
  renderModels();
  try {
    const model = await api(`/api/models/${encodeURIComponent(id)}`);
    const summary = state.models.find(item => item.id === id);
    state.currentModel = {...model, status: summary?.status};
    renderDetail(state.currentModel);
    showMobilePanel("detail");
  } catch (error) {
    showToast(error.message);
  }
}

async function loadModels() {
  try {
    const data = await api("/api/models");
    state.models = data.models;
    setConnection(data.llama_swap_available);
    renderModels();
    if (state.selectedId && state.models.some(model => model.id === state.selectedId)) await selectModel(state.selectedId);
  } catch (error) {
    setConnection(false);
    showToast(error.message);
  }
}

async function loadDiscovered() {
  try {
    state.discovered = (await api("/api/discovered-models")).models;
    renderDiscovered();
  } catch (error) {
    showToast(error.message);
  }
}

function gpuDevice(device) {
  const used = device.memory_used_mib;
  const total = device.memory_total_mib;
  const percent = total ? Math.min(100, used / total * 100) : 0;
  const element = document.createElement("div");
  element.className = "gpu-device";
  element.innerHTML = '<strong></strong><span></span><div class="meter"><i></i></div><div class="gpu-meta"></div>';
  element.querySelector("strong").textContent = device.name;
  element.querySelector("span").textContent = total
    ? `${(used / 1024).toFixed(1)} / ${(total / 1024).toFixed(1)} GiB`
    : `${(used / 1024).toFixed(1)} GiB`;
  element.querySelector("i").style.width = `${percent}%`;
  element.querySelector(".gpu-meta").textContent = device.utilization_percent == null
    ? "WDDM"
    : `${device.utilization_percent}% · ${device.temperature_c}°C`;
  return element;
}

function adapterName(adapter) {
  return adapter.name || `${t("windowsAdapter")} ${adapter.adapter_id.split("_").slice(0, 2).join("_")}`;
}

function renderGpuSelector() {
  const selector = $("#gpu-selector");
  const adapters = state.gpu?.adapters || [];
  const available = new Set(adapters.map(adapter => adapter.adapter_id));
  if (!state.gpuAdapter || (state.gpuAdapter !== "all" && !available.has(state.gpuAdapter))) {
    state.gpuAdapter = adapters.find(adapter => adapter.is_discrete)?.adapter_id || "all";
  }
  selector.replaceChildren();
  const all = document.createElement("option");
  all.value = "all";
  all.textContent = t("allAdapters");
  selector.append(all);
  adapters.forEach(adapter => {
    const option = document.createElement("option");
    option.value = adapter.adapter_id;
    option.textContent = adapterName(adapter);
    selector.append(option);
  });
  selector.value = state.gpuAdapter;
}

function renderGpu() {
  renderGpuSelector();
  const summary = $("#gpu-summary");
  summary.replaceChildren();
  const selectedAdapter = (state.gpu?.adapters || []).find(adapter => adapter.adapter_id === state.gpuAdapter);
  let devices = state.gpuAdapter === "all" ? (state.gpu?.gpus || []) : [];
  if (selectedAdapter) {
    const nvidia = (state.gpu?.gpus || []).find(device => device.name === selectedAdapter.name);
    devices = [nvidia || {
      name: adapterName(selectedAdapter),
      memory_used_mib: selectedAdapter.dedicated_bytes / 1024**2,
      memory_total_mib: selectedAdapter.memory_total_mib,
      utilization_percent: null,
      temperature_c: null
    }];
  }
  devices.forEach(device => summary.append(gpuDevice(device)));
  if (!devices.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = state.gpu?.degraded_reason || t("loading");
    summary.append(empty);
  }
  const query = state.processQuery.toLowerCase();
  const processes = (state.gpu?.processes || [])
    .filter(process => state.gpuAdapter === "all" || process.adapter_id === state.gpuAdapter)
    .filter(process => [process.process_name, process.pid, process.path, ...(process.service_names || [])].join(" ").toLowerCase().includes(query))
    .sort((a, b) => b.dedicated_bytes - a.dedicated_bytes);
  $("#process-count").textContent = String(processes.length);
  const list = $("#process-list");
  list.replaceChildren();
  processes.forEach(process => {
    const row = document.createElement("div");
    row.className = `process-row${process.protected ? " protected" : ""}`;
    row.innerHTML = '<strong></strong><span class="memory"></span><small></small><button class="copy-button" type="button" title="Copy taskkill command" aria-label="Copy taskkill command">⧉</button>';
    row.querySelector("strong").textContent = process.process_name || `PID ${process.pid}`;
    row.querySelector(".memory").textContent = process.dedicated_mib >= 1024 ? `${(process.dedicated_mib / 1024).toFixed(1)} GiB` : `${process.dedicated_mib.toFixed(0)} MiB`;
    const adapter = (state.gpu?.adapters || []).find(item => item.adapter_id === process.adapter_id);
    row.querySelector("small").textContent = [
      state.gpuAdapter === "all" && adapter ? adapterName(adapter) : null,
      process.service_names?.join(", "), `PID ${process.pid}`, process.path
    ].filter(Boolean).join(" · ");
    row.querySelector("button").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(process.kill_command);
        showToast(t("copied"));
      } catch {
        showToast(t("copyFailed"));
      }
    });
    list.append(row);
  });
}

async function loadGpu() {
  try {
    state.gpu = await api("/api/gpu");
    renderGpu();
  } catch (error) {
    showToast(error.message);
  }
}

function showMobilePanel(name) {
  if (innerWidth > 980) return;
  $$('[data-panel]').forEach(element => element.classList.toggle("mobile-active", element.dataset.panel === name));
  $$('[data-mobile-panel]').forEach(element => element.classList.toggle("active", element.dataset.mobilePanel === name));
}

function appendLog(event) {
  const view = $("#live-logs");
  const stickToBottom = view.scrollHeight - view.scrollTop - view.clientHeight < 24;
  const lines = `${view.textContent}${event.data}\n`.split("\n");
  view.textContent = lines.slice(-2000).join("\n");
  if (stickToBottom) view.scrollTop = view.scrollHeight;
}

function connectLogs() {
  clearTimeout(state.logTimer);
  state.logSource?.close();
  const status = $("#log-status");
  status.textContent = t("connecting");
  const source = new EventSource("/api/events");
  state.logSource = source;
  source.onopen = () => {
    state.logRetry = 0;
    status.textContent = t("connected");
  };
  source.onmessage = appendLog;
  for (const name of ["log", "state", "status", "model", "running", "hardware"]) source.addEventListener(name, appendLog);
  source.onerror = () => {
    source.close();
    status.textContent = t("disconnected");
    const delays = [1000, 2000, 4000, 8000, 15000];
    const delay = delays[Math.min(state.logRetry, delays.length - 1)];
    state.logRetry += 1;
    state.logTimer = setTimeout(connectLogs, delay);
  };
}

function clone(value) { return JSON.parse(JSON.stringify(value)); }
function setDeep(object, path, value) {
  const parts = path.split(".");
  let target = object;
  for (const part of parts.slice(0, -1)) {
    if (!target[part] || typeof target[part] !== "object") target[part] = {};
    target = target[part];
  }
  target[parts.at(-1)] = value;
}

function field(label, path, value, {type = "text", step, options, full = false, readonly = false} = {}) {
  const wrap = document.createElement("label");
  wrap.className = `field${full ? " full" : ""}`;
  const title = document.createElement("span");
  title.textContent = label;
  let control;
  if (options) {
    control = document.createElement("select");
    for (const [optionValue, optionLabel] of options) {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = optionLabel;
      option.selected = String(value ?? "") === String(optionValue);
      control.append(option);
    }
  } else {
    control = document.createElement("input");
    control.type = type;
    if (type === "checkbox") control.checked = Boolean(value);
    else control.value = value ?? "";
    if (step) control.step = step;
  }
  if (path) control.dataset.path = path;
  control.readOnly = readonly;
  if (readonly && control.tagName === "SELECT") control.disabled = true;
  wrap.append(title, control);
  return wrap;
}

function group(title, fields) {
  const section = document.createElement("section");
  section.className = "field-group";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const grid = document.createElement("div");
  grid.className = "field-grid";
  grid.append(...fields);
  section.append(heading, grid);
  return section;
}

function candidateDefaults(item) {
  const peer = state.models.find(model => model.settings?.backend === item.backend)?.settings;
  const gib = item.size_bytes / 1024**3;
  const context = gib >= 24 ? 8192 : gib >= 20 ? 16384 : gib >= 12 ? 32768 : 65536;
  const gpuUtilization = gib >= 24 ? 0.94 : gib >= 20 ? 0.92 : 0.9;
  return {
    backend: item.backend,
    launch_tokens: peer?.launch_tokens || [],
    model_path: item.path,
    model_argument: peer?.model_argument || (item.backend === "vllm" ? "positional" : "flag"),
    context_length: context,
    port_token: peer?.port_token || "${PORT}",
    llama_cpp: item.backend === "llama_cpp" ? {
      n_gpu_layers: 99, flash_attn: "on", cache_type_k: "q8_0", cache_type_v: "q8_0", jinja: true
    } : null,
    vllm: item.backend === "vllm" ? {
      gpu_memory_utilization: gpuUtilization, kv_cache_dtype: "fp8", max_num_seqs: 1,
      max_num_batched_tokens: Math.min(context, 4096), enable_chunked_prefill: true,
      trust_remote_code: true, reasoning_parser: "qwen3", enable_auto_tool_choice: true,
      tool_call_parser: "qwen3_coder", safetensors_load_strategy: "prefetch",
      speculative: null
    } : null,
    unknown_tokens: peer?.unknown_tokens || []
  };
}

function editorFields(settings, model, candidate, meta = null) {
  const name = meta?.name || model?.name || candidate.path.split(/[\\/]/).pop().replace(/\.gguf$/i, "");
  const id = meta?.id || model?.id || name.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 128);
  const identity = [
    field(t("modelId"), "meta.id", id, {readonly: Boolean(model)}),
    field(t("displayName"), "meta.name", name),
    field(t("description"), "meta.description", meta?.description ?? model?.description ?? "", {full: true}),
    field(t("backend"), null, settings.backend, {options: [["llama_cpp", "llama.cpp"], ["vllm", "vLLM"]], readonly: true}),
    field(t("modelPath"), "model_path", settings.model_path, {full: true}),
    field(t("launcher"), null, settings.launch_tokens.join(" "), {full: true, readonly: true})
  ];
  const memory = [field(t("context"), "context_length", settings.context_length, {type: "number", step: "1"})];
  const specific = settings.backend === "llama_cpp" ? [
    field(t("gpuLayers"), "llama_cpp.n_gpu_layers", settings.llama_cpp?.n_gpu_layers, {type: "number"}),
    field(t("flashAttention"), "llama_cpp.flash_attn", settings.llama_cpp?.flash_attn, {options: [["auto", "auto"], ["on", "on"], ["off", "off"]]}),
    field(t("kvCacheK"), "llama_cpp.cache_type_k", settings.llama_cpp?.cache_type_k),
    field(t("kvCacheV"), "llama_cpp.cache_type_v", settings.llama_cpp?.cache_type_v),
    field(t("jinja"), "llama_cpp.jinja", settings.llama_cpp?.jinja, {type: "checkbox"}),
    field(t("mmproj"), "llama_cpp.mmproj", settings.llama_cpp?.mmproj, {full: true}),
    field(t("draftModel"), "llama_cpp.model_draft", settings.llama_cpp?.model_draft, {full: true}),
    field(t("specType"), "llama_cpp.spec_type", settings.llama_cpp?.spec_type),
    field(t("draftMax"), "llama_cpp.spec_draft_n_max", settings.llama_cpp?.spec_draft_n_max, {type: "number"}),
    field(t("temperature"), "llama_cpp.temperature", settings.llama_cpp?.temperature, {type: "number", step: "0.01"}),
    field(t("topP"), "llama_cpp.top_p", settings.llama_cpp?.top_p, {type: "number", step: "0.01"}),
    field(t("topK"), "llama_cpp.top_k", settings.llama_cpp?.top_k, {type: "number"}),
    field(t("minP"), "llama_cpp.min_p", settings.llama_cpp?.min_p, {type: "number", step: "0.01"}),
    field(t("repeatPenalty"), "llama_cpp.repeat_penalty", settings.llama_cpp?.repeat_penalty, {type: "number", step: "0.01"})
  ] : [
    field(t("gpuUtilization"), "vllm.gpu_memory_utilization", settings.vllm?.gpu_memory_utilization, {type: "number", step: "0.01"}),
    field(t("kvCacheDtype"), "vllm.kv_cache_dtype", settings.vllm?.kv_cache_dtype),
    field(t("dtype"), "vllm.dtype", settings.vllm?.dtype),
    field(t("quantization"), "vllm.quantization", settings.vllm?.quantization),
    field(t("maxSequences"), "vllm.max_num_seqs", settings.vllm?.max_num_seqs, {type: "number"}),
    field(t("maxBatchedTokens"), "vllm.max_num_batched_tokens", settings.vllm?.max_num_batched_tokens, {type: "number"}),
    field(t("chunkedPrefill"), "vllm.enable_chunked_prefill", settings.vllm?.enable_chunked_prefill, {type: "checkbox"}),
    field(t("trustRemoteCode"), "vllm.trust_remote_code", settings.vllm?.trust_remote_code, {type: "checkbox"}),
    field(t("reasoningParser"), "vllm.reasoning_parser", settings.vllm?.reasoning_parser),
    field(t("toolParser"), "vllm.tool_call_parser", settings.vllm?.tool_call_parser),
    field(t("autoToolChoice"), "vllm.enable_auto_tool_choice", settings.vllm?.enable_auto_tool_choice, {type: "checkbox"}),
    field(t("loadStrategy"), "vllm.safetensors_load_strategy", settings.vllm?.safetensors_load_strategy),
    field(t("mtpMethod"), "vllm.speculative.method", settings.vllm?.speculative?.method),
    field(t("mtpModel"), "vllm.speculative.model", settings.vllm?.speculative?.model, {full: true}),
    field(t("mtpTokens"), "vllm.speculative.num_speculative_tokens", settings.vllm?.speculative?.num_speculative_tokens, {type: "number"})
  ];
  return [group(t("basicSettings"), identity), group(t("memoryContext"), memory), group(t("acceleration"), specific)];
}

function openEditor(model = null, candidate = null, draft = null) {
  state.editingCandidate = candidate;
  const settings = clone(draft?.settings || model?.settings || candidateDefaults(candidate));
  const container = $("#editor-fields");
  container.replaceChildren(...editorFields(settings, model, candidate, draft?.meta));
  container.dataset.settings = JSON.stringify(settings);
  $("#editor-title").textContent = t(candidate ? "registerModel" : "editSettings");
  const missingTemplate = candidate && !settings.launch_tokens.length;
  const error = $("#editor-errors");
  error.textContent = missingTemplate ? t("templateMissing") : "";
  error.hidden = !missingTemplate;
  $("#save-only").disabled = Boolean(missingTemplate);
  $("#save-reload").disabled = Boolean(missingTemplate || candidate);
  if (!$("#model-editor").open) $("#model-editor").showModal();
}

function openRegistration(item) { openEditor(null, item); }

function editorPayload() {
  const container = $("#editor-fields");
  const settings = JSON.parse(container.dataset.settings);
  const meta = {};
  for (const control of container.querySelectorAll("[data-path]")) {
    let value;
    if (control.type === "checkbox") value = control.checked;
    else if (control.type === "number") value = control.value === "" ? null : Number(control.value);
    else value = control.value;
    const path = control.dataset.path;
    if (path.startsWith("meta.")) setDeep(meta, path.slice(5), value);
    else setDeep(settings, path, value);
  }
  if (settings.vllm?.speculative && !settings.vllm.speculative.method) settings.vllm.speculative = null;
  return {meta, settings};
}

async function saveEditor(reload) {
  const error = $("#editor-errors");
  const saveButtons = [$("#save-only"), $("#save-reload")];
  try {
    const {meta, settings} = editorPayload();
    if (!meta.id || !meta.name) throw new Error(t("requiredIdentity"));
    if (!Number.isInteger(settings.context_length) || settings.context_length < 512 || settings.context_length > 262144) {
      throw new Error(t("invalidContext"));
    }
    saveButtons.forEach(button => { button.disabled = true; });
    if (state.editingCandidate) {
      const listing = await api("/api/models");
      await api(`/api/discovered-models/${state.editingCandidate.candidate_id}/register`, {
        method: "POST",
        body: JSON.stringify({revision: listing.revision, model_id: meta.id, name: meta.name, description: meta.description, settings})
      });
      state.discovered = state.discovered.filter(item => item.candidate_id !== state.editingCandidate.candidate_id);
    } else {
      await api(`/api/models/${encodeURIComponent(state.currentModel.id)}`, {
        method: "PUT",
        body: JSON.stringify({revision: state.currentModel.revision, name: meta.name, description: meta.description, settings, reload})
      });
    }
    $("#model-editor").close();
    await loadModels();
  } catch (exception) {
    error.textContent = exception.message;
    error.hidden = false;
  } finally {
    const missingTemplate = state.editingCandidate && !JSON.parse($("#editor-fields").dataset.settings).launch_tokens.length;
    $("#save-only").disabled = Boolean(missingTemplate);
    $("#save-reload").disabled = Boolean(missingTemplate || state.editingCandidate);
  }
}

async function runModelOperation(action) {
  if (!state.selectedId || state.operationBusy) return;
  state.operationBusy = true;
  $("#load-model").disabled = true;
  $("#unload-model").disabled = true;
  try {
    const operation = await api(`/api/models/${encodeURIComponent(state.selectedId)}/${action}`, {method: "POST", body: "{}"});
    await loadModels();
    if (action === "load" && ["starting", "loading", "pending"].includes(operation.status)) await waitForOperationStatus(state.selectedId);
  } catch (error) {
    showToast(`${t("operationFailed")}: ${error.message}`);
    await loadModels();
  } finally {
    state.operationBusy = false;
    setConnection($("#connection-status").classList.contains("online"));
  }
}

async function waitForOperationStatus(modelId) {
  clearTimeout(state.operationPollTimer);
  for (let attempt = 0; attempt < OPERATION_STATUS_MAX_POLLS; attempt += 1) {
    await new Promise(resolve => { state.operationPollTimer = setTimeout(resolve, OPERATION_STATUS_POLL_MS); });
    await loadModels();
    const model = state.models.find(item => item.id === modelId);
    if (!model || !["starting", "loading", "pending"].includes(model.status)) return;
  }
  await loadModels();
}

function toggleLocale() {
  const draft = $("#model-editor").open ? editorPayload() : null;
  state.locale = state.locale === "zh-CN" ? "en" : "zh-CN";
  localStorage.setItem("llamaSwapConsole.locale", state.locale);
  applyLocale();
  renderModels();
  renderGpu();
  renderDetail(state.currentModel);
  setConnection($("#connection-status").classList.contains("online"));
  if ($("#model-editor").open) openEditor(state.editingCandidate ? null : state.currentModel, state.editingCandidate, draft);
}
$("#language-toggle").addEventListener("click", toggleLocale);
$("#dialog-language-toggle").addEventListener("click", toggleLocale);
$("#refresh-all").addEventListener("click", () => Promise.all([loadModels(), loadDiscovered(), loadGpu()]));
$("#model-search").addEventListener("input", event => { state.query = event.target.value; renderModels(); });
$("#process-search").addEventListener("input", event => { state.processQuery = event.target.value; renderGpu(); });
$("#gpu-selector").addEventListener("change", event => { state.gpuAdapter = event.target.value; renderGpu(); });
$$('[data-mobile-panel]').forEach(button => button.addEventListener("click", () => showMobilePanel(button.dataset.mobilePanel)));
$("#scan-models").addEventListener("click", async () => {
  try {
    await api("/api/scan", {method: "POST", body: "{}"});
    state.discovered = (await api("/api/discovered-models")).models;
    renderDiscovered();
    showToast(t("scanComplete"));
  } catch (error) {
    showToast(error.message);
  }
});
$("#load-model").addEventListener("click", () => runModelOperation("load"));
$("#unload-model").addEventListener("click", () => runModelOperation("unload"));
$("#edit-model").addEventListener("click", () => { if (state.currentModel?.settings) openEditor(state.currentModel); });
$("#editor-form").addEventListener("submit", event => {
  const action = event.submitter?.value;
  if (action === "cancel") return;
  event.preventDefault();
  saveEditor(action === "reload");
});
window.addEventListener("resize", () => { if (innerWidth <= 980) showMobilePanel($(".mobile-tabs .active")?.dataset.mobilePanel || "models"); });

applyLocale();
showMobilePanel("models");
loadModels();
loadDiscovered();
loadGpu();
connectLogs();
setInterval(() => { if (!document.hidden) loadGpu(); }, 2000);
