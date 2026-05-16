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

const API_BASE = (window.location.origin === "null" || window.location.protocol === "file:") 
  ? "http://127.0.0.1:8000" 
  : window.location.origin;

console.log("App initialized. API_BASE:", API_BASE);

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
  clearTimeout(statusInterval);
  
  if (isLoading) {
    const span = statusEl.querySelector("span");
    const initialMsg = message || "Initializing...";
    span.textContent = initialMsg;
    console.log("[Analysis Progress]:", initialMsg);
    
    const pollProgress = async () => {
      if (!statusEl.hidden) {
        try {
          const res = await fetch(`${API_BASE}/tasks/progress`);
          if (res.ok) {
            const data = await res.json();
            const nextMsg = data.message;
            if (span.textContent !== nextMsg) {
              span.textContent = nextMsg;
              console.log("[Analysis Progress]:", nextMsg);
            }
          }
        } catch (e) {
          // ignore fetch errors
        }
        statusInterval = setTimeout(pollProgress, 500);
      }
    };
    pollProgress();
  } else {
    console.log("[Analysis Progress]: Finished.");
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

const MOCK_TABLE_DATA = {
  customers: {
    columns: ["customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city", "customer_state"],
    rows: [
      ["06b8999e2fba1a1fbc88172c00ba8bc7", "861eff4711a542e4b93843c6dd7febb0", "14409", "franca", "SP"],
      ["18955e83d337fd6b2def6b18a428ac77", "290c77bc529b7ac935bce42fea531f56", "9790", "sao bernardo do campo", "SP"],
      ["4e7b3e00288586ebd08712fdd0374a03", "060e732b5b29e8181a18229c7b0b2b5e", "1151", "sao paulo", "SP"],
    ]
  },
  orders: {
    columns: ["order_id", "customer_id", "order_status", "order_purchase_timestamp", "order_delivered_customer_date"],
    rows: [
      ["e481f51cbdc54678b7cc49136f2d6af7", "9ef432eb6251297304e76186b10a928d", "delivered", "2017-10-02 10:56:33", "2017-10-10 21:25:13"],
      ["53cdb2fc8bc7dce0b6741e2150273451", "b0830fb4747a6c6d20dea0b8c802d7ef", "delivered", "2018-07-24 20:41:37", "2018-08-07 15:27:45"],
      ["47770eb9100c2d0c44946d9cf07ec65d", "41ce2a54c0b03bf3443c3d931a367089", "delivered", "2018-08-08 08:38:49", "2018-08-17 18:06:29"],
    ]
  },
  products: {
    columns: ["product_id", "product_category_name", "product_name_lenght", "product_description_lenght", "product_photos_qty"],
    rows: [
      ["1e9e8ef04dbcff4541ed26657ea517e5", "perfumaria", "40", "287", "1"],
      ["3aa071139cb16b67ca9e5dea641aaa2f", "artes", "44", "276", "1"],
      ["96bd76ec8810374ed1b65e291975717f", "esporte_lazer", "46", "250", "1"],
    ]
  },
  order_items: {
    columns: ["order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price", "freight_value"],
    rows: [
      ["00010242fe8c5a6d1ba2dd792cb16214", "1", "4244733e06e7ecb4970a6e2683c13e61", "48436dade18ac8b2bce089ec2a041202", "2017-09-19 09:45:35", "58.90", "13.29"],
      ["00018f77f2f0320c557190d7a144bdd3", "1", "e5f2d52b802189ee658865ca93d83a8f", "dd7ddc04e1b6c2c614352b383efe2d36", "2017-05-03 11:05:13", "239.90", "19.93"],
    ]
  }
};

async function fetchTablePreview(tableName) {
  previewHeader.innerHTML = "<th>Loading...</th>";
  previewBody.innerHTML = "";
  
  // Simulate quick network delay
  await new Promise(resolve => setTimeout(resolve, 150));
  
  const data = MOCK_TABLE_DATA[tableName] || { 
    columns: ["id", "timestamp", "metadata_1", "metadata_2", "status"], 
    rows: [
      ["row_abc123", "2018-05-12 14:22:11", "value_alpha", "metric_99", "active"], 
      ["row_def456", "2018-05-13 09:14:02", "value_beta", "metric_42", "pending"],
      ["row_ghi789", "2018-05-14 18:41:59", "value_gamma", "metric_7", "active"]
    ]
  };
  
  previewHeader.innerHTML = data.columns.map(col => `<th>${escapeHtml(col)}</th>`).join("");
  previewBody.innerHTML = data.rows.map(row => `
    <tr>
      ${row.map(cell => `<td>${escapeHtml(cell)}</td>`).join("")}
    </tr>
  `).join("");
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
