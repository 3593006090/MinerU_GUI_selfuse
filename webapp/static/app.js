/* MinerU 本地操作台前端逻辑 */
const state = { file: null, tier: "standard", taskId: null, timer: null };

const $ = (id) => document.getElementById(id);

function fmtSize(n) {
  if (!n && n !== 0) return "";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

function fmtTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const p = (x) => String(x).padStart(2, "0");
  return `${d.getMonth() + 1}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/* ---------- 顶部状态 ---------- */
async function loadHealth() {
  try {
    const r = await fetch("/api/health");
    const d = await r.json();
    const pill = $("statusPill"), dot = pill.querySelector(".dot");
    if (d.ok) {
      dot.className = "dot ok";
      $("statusText").textContent = `MinerU ${d.version} · ${d.gpu.split(",")[0]}`;
    } else {
      dot.className = "dot err";
      $("statusText").textContent = "服务异常";
    }
  } catch {
    $("statusText").textContent = "后端未连接";
  }
}

/* ---------- 档位 ---------- */
async function loadTiers() {
  const r = await fetch("/api/config");
  const d = await r.json();
  const box = $("tierList");
  box.innerHTML = "";
  Object.entries(d.tiers).forEach(([key, t]) => {
    const el = document.createElement("div");
    el.className = "tier" + (key === state.tier ? " on" : "");
    el.innerHTML = `<div class="t-name"><span>${t.name}</span>${key === "standard" ? "<em>推荐</em>" : ""}</div>
      <div class="t-desc">${t.desc}</div><div class="t-time">${t.time}</div>`;
    el.onclick = () => {
      state.tier = key;
      box.querySelectorAll(".tier").forEach((n) => n.classList.remove("on"));
      el.classList.add("on");
    };
    box.appendChild(el);
  });
}

/* ---------- 上传 ---------- */
function renderFile(f) {
  const list = $("fileList");
  list.innerHTML = "";
  if (!f) { $("parseBtn").disabled = true; return; }
  const li = document.createElement("li");
  li.className = "file-item";
  li.innerHTML = `<span class="fi-name">${f.name}</span>
    <span class="fi-size">${fmtSize(f.size)}</span>
    <span class="fi-tag">待解析</span>
    <button class="fi-del" title="移除">×</button>`;
  li.querySelector(".fi-del").onclick = () => { state.file = null; renderFile(null); };
  list.appendChild(li);
  $("parseBtn").disabled = false;
}

async function uploadFile(file) {
  const fd = new FormData();
  fd.append("file", file);
  const btn = $("dropzone");
  btn.style.opacity = ".6";
  try {
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json();
    state.file = { file_id: d.file_id, name: d.name, size: d.size };
    state.taskId = null;
    renderFile(state.file);
  } catch (e) {
    alert("上传失败：" + e.message);
  } finally {
    btn.style.opacity = "1";
  }
}

function bindDropzone() {
  const dz = $("dropzone"), input = $("fileInput");
  dz.onclick = () => input.click();
  input.onchange = () => input.files[0] && uploadFile(input.files[0]);
  ["dragenter", "dragover"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files[0];
    if (f) uploadFile(f);
  });
}

/* ---------- 任务 ---------- */
async function startParse() {
  if (!state.file) return;
  const fd = new FormData();
  fd.append("file_id", state.file.file_id);
  fd.append("tier", state.tier);
  const r = await fetch("/api/tasks", { method: "POST", body: fd });
  if (!r.ok) { alert("启动失败：" + (await r.text())); return; }
  const d = await r.json();
  state.taskId = d.task_id;
  showProgress(true);
  $("empty").classList.add("hidden");
  $("preview").classList.add("hidden");
  $("raw").classList.add("hidden");
  $("downloadBtn").disabled = true;
  $("zipBtn").disabled = true;
  $("cancelBtn").disabled = false;
  pollTask();
}

function showProgress(on) {
  $("progress").classList.toggle("hidden", !on);
}

async function pollTask() {
  clearTimeout(state.timer);
  if (!state.taskId) return;
  try {
    const r = await fetch(`/api/tasks/${state.taskId}`);
    const d = await r.json();
    $("phaseText").textContent = `${d.phase || ""}${d.percent ? " · " + d.percent + "%" : ""}`;
    $("barFill").style.width = (d.percent || 0) + "%";
    $("elapsedText").textContent = d.elapsed ? `已用 ${Math.round(d.elapsed)} 秒` : "";
    $("logBox").textContent = (d.log || []).join("\n");
    $("logBox").scrollTop = $("logBox").scrollHeight;

    if (d.status === "done") {
      $("phaseText").textContent = `完成 · 耗时 ${d.elapsed || 0} 秒`;
      $("barFill").style.width = "100%";
      $("cancelBtn").disabled = true;
      $("downloadBtn").disabled = false;
      $("zipBtn").disabled = false;
      renderResult(d.markdown || "", d.task_id || state.taskId);
      loadHistory();
      return;
    }
    if (d.status === "error" || d.status === "cancelled") {
      $("phaseText").textContent = d.status === "error" ? "解析失败" : "已取消";
      $("cancelBtn").disabled = true;
      if (d.error) $("logBox").textContent += "\n\n" + d.error;
      return;
    }
  } catch (e) {
    console.warn(e);
  }
  state.timer = setTimeout(pollTask, 1200);
}

function renderResult(markdown, taskId) {
  const preview = $("preview"), raw = $("raw");
  raw.textContent = markdown;
  preview.innerHTML = marked.parse(markdown);
  preview.querySelectorAll("img").forEach((img) => { img.loading = "lazy"; });
  preview.classList.remove("hidden");
  $("empty").classList.add("hidden");
  const active = document.querySelector(".tabs button.active");
  if (active && active.dataset.tab === "raw") {
    raw.classList.remove("hidden"); preview.classList.add("hidden");
  } else {
    preview.classList.remove("hidden"); raw.classList.add("hidden");
  }
  state.taskId = taskId;
  $("downloadBtn").onclick = () => location.href = `/api/tasks/${taskId}/download`;
  $("zipBtn").onclick = () => location.href = `/api/tasks/${taskId}/zip`;
}

/* ---------- 历史 ---------- */
async function loadHistory() {
  try {
    const r = await fetch("/api/history");
    const items = await r.json();
    const box = $("history");
    box.innerHTML = "";
    if (!items.length) { box.innerHTML = '<li class="empty-hint">暂无历史记录</li>'; return; }
    items.forEach((it) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="h-name">${it.name}</span>
        <span class="h-meta">${it.tier} · ${fmtTime(it.created)}</span>`;
      li.onclick = () => reopenTask(it.id);
      box.appendChild(li);
    });
  } catch { /* ignore */ }
}

async function reopenTask(taskId) {
  const r = await fetch(`/api/tasks/${taskId}`);
  if (!r.ok) return;
  const d = await r.json();
  showProgress(false);
  $("cancelBtn").disabled = true;
  $("downloadBtn").disabled = false;
  $("zipBtn").disabled = false;
  if (d.status === "done" && d.markdown) renderResult(d.markdown, taskId);
}

/* ---------- 事件 ---------- */
function bindUI() {
  bindDropzone();
  $("parseBtn").onclick = startParse;
  $("cancelBtn").onclick = async () => {
    if (!state.taskId) return;
    await fetch(`/api/tasks/${state.taskId}/cancel`, { method: "POST" });
  };
  document.querySelectorAll(".tabs button").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll(".tabs button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      const isRaw = b.dataset.tab === "raw";
      $("raw").classList.toggle("hidden", !isRaw);
      $("preview").classList.toggle("hidden", isRaw);
      if (!isRaw && !$("preview").innerHTML) {
        $("empty").classList.remove("hidden");
      }
    };
  });
}

loadHealth();
loadTiers();
loadHistory();
bindUI();

// 支持通过 URL 直接打开某个历史任务： /?task=<task_id>
const sharedTask = new URLSearchParams(location.search).get("task");
if (sharedTask) {
  showProgress(false);
  reopenTask(sharedTask);
}
