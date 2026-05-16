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
const whySection = document.querySelector("#why-section");
const whyExplanationEl = document.querySelector("#why-explanation");
const anomaliesSection = document.querySelector("#anomalies-section");
const anomaliesListEl = document.querySelector("#anomalies-list");
const confidenceExplanationEl = document.querySelector("#confidence-explanation");
const traceEl = document.querySelector("#trace");
const exampleButtons = document.querySelectorAll(".example-link");

const API_BASE = window.location.origin === "null" || window.location.protocol === "file:" 
  ? "http://127.0.0.1:8000" 
  : window.location.origin;

let statusInterval;
const thinkingMessages = [
  "Initializing analytical agents...",
  "Decomposing question into logical steps...",
  "Synthesizing schema context...",
  "Generating and validating SQL queries...",
  "Executing data analysis tools...",
  "Identifying anomalies and patterns...",
  "Synthesizing executive summary...",
  "Finalizing analytical trace..."
];

function setLoading(isLoading, message) {
  statusEl.hidden = !isLoading;
  clearInterval(statusInterval);
  
  if (isLoading) {
    const span = statusEl.querySelector("span");
    span.textContent = message || thinkingMessages[0];
    let msgIndex = 0;
    statusInterval = setInterval(() => {
      msgIndex = (msgIndex + 1) % thinkingMessages.length;
      span.textContent = thinkingMessages[msgIndex];
    }, 3000);
  }
  
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
  for (const [index, query] of (queries || []).entries()) {
    const details = document.createElement("details");
    details.className = "sql-details";
    // Collapse all by default, maybe open the first one if it's the most important
    details.open = false; 
    
    details.innerHTML = `
      <summary>Query ${index + 1} <span class="sql-peek">${escapeHtml(query.substring(0, 40))}...</span></summary>
      <div class="sql-content">
        <pre><code>${escapeHtml(query.trim())}</code></pre>
      </div>
    `;
    sqlEl.appendChild(details);
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
    
    setLoading(true, "Executing SQL queries and interpreting results...");
    console.log("Response received:", response.status);
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Backend returned ${response.status}`);
    }
    
    setLoading(true, "Synthesizing final executive report...");
    const data = await response.json();
    console.log("Data parsed successfully", data);
    
    summaryEl.textContent = data.summary;
    const confPercent = (Number(data.confidence || 0) * 100).toFixed(0);
    confidenceTextEl.textContent = `Confidence: ${confPercent}% · Trace ID: ${data.run_id}`;
    confidenceBarEl.style.width = `${confPercent}%`;
    
    verdictBadgeEl.textContent = data.verdict;
    verdictBadgeEl.className = `badge ${data.verdict}`;
    
    if (data.why_explanation) {
      whyExplanationEl.textContent = data.why_explanation;
      whySection.hidden = false;
    } else {
      whySection.hidden = true;
    }

    if (data.anomalies && data.anomalies.length > 0) {
      renderList(anomaliesListEl, data.anomalies);
      anomaliesSection.hidden = false;
    } else {
      anomaliesSection.hidden = true;
    }

    if (data.confidence_explanation) {
      confidenceExplanationEl.textContent = data.confidence_explanation;
    } else {
      confidenceExplanationEl.textContent = "";
    }

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

const datasetBtn = document.querySelector("#dataset-btn");
const datasetModal = document.querySelector("#dataset-modal");
const modalClose = document.querySelector("#modal-close");
const navItems = document.querySelectorAll(".nav-item");
const tabOverview = document.querySelector("#tab-overview");
const tabData = document.querySelector("#tab-data");
const previewHeader = document.querySelector("#preview-header");
const previewBody = document.querySelector("#preview-body");

datasetBtn.addEventListener("click", () => {
  datasetModal.classList.add("active");
});

modalClose.addEventListener("click", () => {
  datasetModal.classList.remove("active");
});

datasetModal.addEventListener("click", (e) => {
  if (e.target === datasetModal) {
    datasetModal.classList.remove("active");
  }
});

async function fetchTablePreview(tableName) {
  console.log("Requesting preview for table:", tableName);
  previewHeader.innerHTML = "<th>Loading...</th>";
  previewBody.innerHTML = "";
  
  try {
    const url = `${API_BASE}/data/tables/${tableName}/preview`;
    console.log("Fetching preview from:", url);
    const response = await fetch(url);
    console.log("Preview response status:", response.status);
    
    if (!response.ok) throw new Error(`Failed to fetch preview: ${response.status}`);
    
    const data = await response.json();
    console.log("Preview data received:", data.columns.length, "columns,", data.rows.length, "rows");
    
    if (data.columns.length === 0) {
      previewHeader.innerHTML = "<th>No columns found</th>";
      return;
    }

    // Render Header
    previewHeader.innerHTML = data.columns.map(col => `<th>${escapeHtml(col)}</th>`).join("");
    
    // Render Rows
    if (data.rows.length === 0) {
      previewBody.innerHTML = `<tr><td colspan="${data.columns.length}">Table is empty</td></tr>`;
    } else {
      previewBody.innerHTML = data.rows.map(row => `
        <tr>
          ${row.map(cell => `<td>${escapeHtml(cell === null ? "NULL" : cell)}</td>`).join("")}
        </tr>
      `).join("");
    }
    
  } catch (error) {
    console.error("Preview fetch failed:", error);
    previewHeader.innerHTML = `<th style="color: var(--error)">Error: ${escapeHtml(error.message)}</th>`;
  }
}

navItems.forEach(item => {
  item.addEventListener("click", () => {
    // Update active UI
    navItems.forEach(nav => nav.classList.remove("active"));
    item.classList.add("active");
    
    const tab = item.getAttribute("data-tab");
    
    if (tab === "overview") {
      tabOverview.classList.add("active");
      tabData.classList.remove("active");
    } else {
      tabOverview.classList.remove("active");
      tabData.classList.add("active");
      fetchTablePreview(tab);
    }
  });
});

exampleButtons.forEach(btn => {
  btn.addEventListener("click", () => {
    input.value = btn.textContent;
    runAnalysis(btn.textContent);
  });
});
