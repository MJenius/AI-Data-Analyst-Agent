const form = document.querySelector("#analysis-form");
const input = document.querySelector("#question");
const statusEl = document.querySelector("#status");
const resultsEl = document.querySelector("#results");
const summaryEl = document.querySelector("#summary");
const confidenceTextEl = document.querySelector("#confidence-text");
const confidenceBarEl = document.querySelector("#confidence-bar");
const verdictBadgeEl = document.querySelector("#verdict-badge");
const findingsEl = document.querySelector("#findings");
const sqlEl = document.querySelector("#sql-queries");
const traceEl = document.querySelector("#trace");
const exampleButtons = document.querySelectorAll(".example-link");

const API_BASE = window.API_BASE || "http://127.0.0.1:8000";

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

function renderTrace(steps) {
  traceEl.innerHTML = "";
  for (const [index, step] of (steps || []).entries()) {
    const details = document.createElement("details");
    details.open = index === 0;
    details.innerHTML = `
      <summary>${escapeHtml(step.step)}</summary>
      <div class="trace-content">
        <div class="trace-meta">
          <strong>Analytical Reasoning</strong>
          ${escapeHtml(step.reasoning || "")}
        </div>
        ${step.sql ? `
          <div class="trace-meta">
            <strong>Generated SQL</strong>
            <pre>${escapeHtml(step.sql.trim())}</pre>
          </div>
        ` : ""}
        <div class="trace-meta">
          <strong>Result Preview</strong>
          <div style="font-family: monospace; font-size: 12px; background: #f3f4f6; padding: 12px; border-radius: 8px; overflow-x: auto; color: #334155; border: 1px solid #e2e8f0;">
            ${escapeHtml(step.result_preview || "No data returned")}
          </div>
        </div>
        <div class="trace-time">${Number(step.execution_time_ms || 0).toFixed(2)} ms</div>
      </div>
    `;
    traceEl.appendChild(details);
  }
}

async function runAnalysis(question) {
  console.log("Starting analysis for:", question);
  setLoading(true);
  resultsEl.hidden = true;
  summaryEl.textContent = "";
  findingsEl.innerHTML = "";
  sqlEl.innerHTML = "";
  traceEl.innerHTML = "";

  try {
    console.log("Fetching from:", `${API_BASE}/tasks/analyze`);
    const response = await fetch(`${API_BASE}/tasks/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    
    console.log("Response received:", response.status);
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Backend returned ${response.status}`);
    }
    
    const data = await response.json();
    console.log("Data parsed successfully", data);
    
    summaryEl.textContent = data.summary;
    const confPercent = (Number(data.confidence || 0) * 100).toFixed(0);
    confidenceTextEl.textContent = `Confidence: ${confPercent}% · Trace ID: ${data.run_id}`;
    confidenceBarEl.style.width = `${confPercent}%`;
    
    verdictBadgeEl.textContent = data.verdict;
    verdictBadgeEl.className = `badge ${data.verdict}`;
    
    renderList(findingsEl, data.key_findings);
    renderSql(data.sql_queries);
    renderTrace(data.steps);
    
    resultsEl.hidden = false;
  } catch (error) {
    console.error("Analysis failed:", error);
    summaryEl.textContent = `Error: ${error.message}`;
    confidenceTextEl.textContent = "Ensure the backend server is running at " + API_BASE;
    findingsEl.innerHTML = "";
    sqlEl.innerHTML = "";
    traceEl.innerHTML = "";
    resultsEl.hidden = false;
  } finally {
    setLoading(false);
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (question) runAnalysis(question);
});

exampleButtons.forEach(btn => {
  btn.addEventListener("click", () => {
    input.value = btn.textContent;
    runAnalysis(btn.textContent);
  });
});
