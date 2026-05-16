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
        findings = self._findings_from(sql_results)
        supporting_metrics = self._metrics_from(sql_results)
        summary = findings[0] if findings else "Analysis completed, but no strong finding was produced."
        confidence = state.evaluation.get("confidence", 0.0) if state.evaluation else 0.0
        return {
            "summary": summary,
            "key_findings": findings,
            "sql_queries": [result["query"] for result in sql_results],
            "supporting_metrics": supporting_metrics,
            "confidence": confidence,
            "execution_trace": self._execution_trace(state),
            "chart_ready": self._chart_ready(sql_results),
        }

    def _findings_from(self, sql_results: list[dict[str, Any]]) -> list[str]:
        findings: list[str] = []
        for result in sql_results:
            rows = result.get("rows", [])
            if not rows:
                continue
            first = rows[0]
            if "revenue_growth" in first:
                findings.append(
                    f"{first['product_name']} drove the highest revenue growth "
                    f"at {first['revenue_growth']} incremental revenue."
                )
            elif "region" in first:
                findings.append(
                    f"{first['region']} was the strongest region in this slice, "
                    f"led by {first.get('product_name', 'the top product')}."
                )
            elif "revenue" in first:
                label = first.get("product_name") or first.get("category") or first.get("month")
                findings.append(f"{label} was the top revenue contributor at {first['revenue']}.")
        return findings

    def _metrics_from(self, sql_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        metrics: list[dict[str, Any]] = []
        for result in sql_results:
            for row in result.get("rows", [])[:5]:
                metrics.append(row)
        return metrics

    def _chart_ready(self, sql_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        charts: list[dict[str, Any]] = []
        for result in sql_results:
            rows = result.get("rows", [])
            if rows:
                charts.append({"query": result["query"], "data": rows})
        return charts

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
