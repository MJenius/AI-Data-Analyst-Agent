from __future__ import annotations

from typing import Any

from agent_platform.orchestration.state import ExecutionState


class AnalyticsReportBuilder:
    """Converts execution state into a structured analytical output."""

    def build(self, state: ExecutionState) -> dict[str, Any]:
        sql_results = [
            item["result"]
            for item in state.tool_results
            if item.get("tool") == "sql" and isinstance(item.get("result"), dict)
        ]
        
        # Prioritize LLM-synthesized report from evaluation
        if state.evaluation and state.evaluation.get("summary"):
            summary = state.evaluation["summary"]
            findings = state.evaluation.get("key_findings", [])
        else:
            findings = self._findings_from(sql_results)
            summary = findings[0] if findings else "Analysis completed, but no strong finding was produced."
            
        confidence = state.evaluation.get("confidence", 0.0) if state.evaluation else 0.0
        return {
            "summary": summary,
            "key_findings": findings,
            "why_explanation": state.evaluation.get("why_explanation") if state.evaluation else None,
            "anomalies": state.evaluation.get("anomalies", []) if state.evaluation else [],
            "confidence": confidence,
            "confidence_explanation": state.evaluation.get("confidence_explanation") if state.evaluation else "Analysis was performed using SQL evidence.",
            "execution_trace": self._execution_trace(state),
            "sql_queries": [result["query"] for result in sql_results],
        }

    def _findings_from(self, sql_results: list[dict[str, Any]]) -> list[str]:
        findings: list[str] = []
        for result in sql_results:
            rows = result.get("rows", [])
            if not rows:
                continue
            
            # Trend detection
            if len(rows) >= 2 and "revenue" in rows[0] and ("month" in rows[0] or "order_month" in rows[0]):
                for i in range(1, len(rows)):
                    prev = rows[i-1]
                    curr = rows[i]
                    p_rev = prev["revenue"]
                    c_rev = curr["revenue"]
                    label = curr.get("month") or curr.get("order_month")
                    if c_rev < p_rev:
                        drop = p_rev - c_rev
                        pct = (drop / p_rev * 100) if p_rev > 0 else 0
                        findings.append(f"Revenue dropped by {drop:.1f} ({pct:.1f}%) in {label} compared to the previous period.")
                    else:
                        findings.append(f"Revenue increased to {c_rev:.1f} in {label}.")

            # Delivery time comparison
            elif len(rows) >= 2 and "avg_delivery_time_days" in rows[0] and "state" in rows[0]:
                sp_row = next((r for r in rows if r["state"] == "SP"), None)
                rj_row = next((r for r in rows if r["state"] == "RJ"), None)
                if sp_row and rj_row:
                    diff = rj_row["avg_delivery_time_days"] - sp_row["avg_delivery_time_days"]
                    pct = (diff / sp_row["avg_delivery_time_days"] * 100) if sp_row["avg_delivery_time_days"] > 0 else 0
                    findings.append(f"Rio de Janeiro (RJ) deliveries take {diff:.2f} days longer than São Paulo (SP) on average (+{pct:.1f}%).")
                for row in rows:
                    findings.append(f"Average delivery time in state {row['state']} is {row['avg_delivery_time_days']:.2f} days.")

            # Single row attribution
            elif len(rows) == 1:
                first = rows[0]
                label = first.get("product_name") or first.get("category") or first.get("region") or "Top segment"
                val = first.get("revenue") or first.get("revenue_growth")
                if val:
                    findings.append(f"{label} contributed {val:.1f} to the current results.")
        
        return findings[:5]  # Limit to top 5 findings

    def _execution_trace(self, state: ExecutionState) -> dict[str, list[dict[str, Any]]]:
        steps = []
        for trace in state.traces:
            steps.append(
                {
                    "step": trace.step,
                    "reasoning": trace.metadata.get("reasoning", ""),
                    "sql": trace.metadata.get("sql"),
                    "result_preview": trace.metadata.get("result_preview", ""),
                    "execution_time_ms": trace.metadata.get("execution_time_ms", 0),
                }
            )
        return {"steps": steps}
