/* 使用教程页交互 */

const TIER_TEXT = {
  flash: "Flash：只读取 PDF 原生文本层，不跑任何模型。适合电子版 PDF 的快速预览、检索。扫描件不要用它。",
  basic: "Basic：用小模型做 OCR、版面和表格识别，不调用 VLM。适合扫描件但公式/复杂版面要求不高的情况。",
  standard: "Standard：小模型 + VLM 组合，复杂版面、公式、表格还原质量最好，是默认推荐档位。",
  advanced: "Advanced：在 Standard 基础上投入更多推理计算，质量更高但更慢，适合精度要求极高的文档。",
};

document.querySelectorAll(".tg").forEach((el) => {
  el.onclick = () => {
    document.querySelectorAll(".tg").forEach((x) => x.classList.remove("on"));
    el.classList.add("on");
    document.getElementById("tierDetail").textContent = TIER_TEXT[el.dataset.key];
  };
});

document.querySelectorAll(".copy").forEach((btn) => {
  btn.onclick = async () => {
    const code = btn.parentElement.textContent.replace(/^复制/, "").trim();
    try {
      await navigator.clipboard.writeText(code);
      btn.textContent = "已复制";
    } catch {
      btn.textContent = "复制失败";
    }
    setTimeout(() => (btn.textContent = "复制"), 1500);
  };
});

async function pollDemo(taskId) {
  const status = document.getElementById("demoStatus");
  const out = document.getElementById("demoOut");
  for (let i = 0; i < 300; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    const r = await fetch(`/api/tasks/${taskId}`);
    if (!r.ok) break;
    const d = await r.json();
    status.textContent = `${d.phase || "排队中"}${d.percent ? " · " + d.percent + "%" : ""} · 已用 ${Math.round(d.elapsed || 0)} 秒`;
    if (d.status === "done") {
      status.textContent = `完成 · 耗时 ${Math.round(d.elapsed || 0)} 秒`;
      out.innerHTML = marked.parse(d.markdown || "");
      out.querySelectorAll("img").forEach((img) => (img.loading = "lazy"));
      return;
    }
    if (d.status === "error") {
      status.textContent = "解析失败：" + (d.error || "未知错误");
      return;
    }
  }
}

document.getElementById("demoBtn").onclick = async (e) => {
  e.target.disabled = true;
  const status = document.getElementById("demoStatus");
  const out = document.getElementById("demoOut");
  status.textContent = "正在提交…";
  out.innerHTML = "";
  try {
    const fd = new FormData();
    fd.append("tier", "standard");
    const r = await fetch("/api/demo", { method: "POST", body: fd });
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json();
    await pollDemo(d.task_id);
  } catch (err) {
    status.textContent = "提交失败：" + err.message;
  } finally {
    e.target.disabled = false;
  }
};
