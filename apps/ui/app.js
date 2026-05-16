const form = document.querySelector("#analysis-form");
const input = document.querySelector("#question");
const statusEl = document.querySelector("#status");
const resultsEl = document.querySelector("#results");
const summaryEl = document.querySelector("#summary");
const confidenceEl = document.querySelector("#confidence");
const findingsEl = document.querySelector("#findings");
const sqlEl = document.querySelector("#sql-queries");
const traceEl = document.querySelector("#trace");

const API_BASE = window.API_BASE || "http://localhost:8000";

function setLoading(isLoading) {
  statusEl.hidden = !isLoading;
  form.querySelector("button").disabled = isLoading;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderList(target, items) {
  target.innerHTML = "";
  for (const item of items || []) {
    const li = document.createElement("li");
    li.textContent = item;
    target.appendChild(li);
  }
}

function renderSql(queries) {
  sqlEl.innerHTML = "";
  for (const query of queries || []) {
    const pre = document.createElement("pre");
    pre.textContent = query.trim();
    sqlEl.appendChild(pre);
  }
}

function renderTrace(trace) {
  traceEl.innerHTML = "";
  for (const [index, step] of (trace?.steps || []).entries()) {
    const details = document.createElement("details");
    details.open = index === 0;
    details.innerHTML = `
      <summary>${escapeHtml(step.step)}</summary>
      <div class="trace-meta">
        <strong>Reasoning</strong><br />
        ${escapeHtml(step.reasoning || "")}
      </div>
      ${step.sql ? `<pre>${escapeHtml(step.sql.trim())}</pre>` : ""}
      <div class="trace-meta">
        <strong>Result preview</strong><br />
        ${escapeHtml(step.result_preview || "")}
      </div>
      <div class="trace-meta">${Number(step.execution_time_ms || 0).toFixed(2)} ms</div>
    `;
    traceEl.appendChild(details);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question) return;

  setLoading(true);
  resultsEl.hidden = true;

  try {
    const response = await fetch(`${API_BASE}/tasks/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}`);
    }
    const data = await response.json();
    summaryEl.textContent = data.summary;
    confidenceEl.textContent = `Confidence ${(Number(data.confidence || 0) * 100).toFixed(0)}% · Run ${data.run_id}`;
    renderList(findingsEl, data.findings);
    renderSql(data.sql_queries);
    renderTrace(data.execution_trace);
    resultsEl.hidden = false;
  } catch (error) {
    summaryEl.textContent = error.message;
    confidenceEl.textContent = "";
    findingsEl.innerHTML = "";
    sqlEl.innerHTML = "";
    traceEl.innerHTML = "";
    resultsEl.hidden = false;
  } finally {
    setLoading(false);
  }
});
