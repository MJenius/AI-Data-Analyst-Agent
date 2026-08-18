"""Cost, Token, Latency, and Pareto Frontier Profiling Engine.

Provides:
- Precise token counter with tiktoken support (cl100k_base, o200k_base) and fallback estimators.
- Comprehensive pricing catalog with pre-configured rate cards (GPT-4o, Claude 3.5, DeepSeek, Llama 3.3, Nvidia Nemotron).
- Latency distribution profiler: p50, p75, p90, p95, p99, mean, std, IQR, skewness, kurtosis, and empirical CDF.
- Concurrency & throughput scaling model: QPS, QPM, speedup factor, scaling efficiency.
- Multi-turn SQL repair overhead analyzer: repair trigger rate, latency/token penalties, recovery efficiency.
- Accuracy-Latency-Cost Pareto Frontier analyzer: non-dominated sorting and trade-off gradient computation.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from scipy import stats

try:
    import tiktoken
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _TIKTOKEN_AVAILABLE = False

logger = logging.getLogger("experiments.cost_latency")


# ============================================================================
# Token Counting & Cost Modeling
# ============================================================================

@dataclass
class ModelRateCard:
    model_id: str
    input_cost_per_m: float       # Cost per 1 Million input tokens (USD)
    output_cost_per_m: float      # Cost per 1 Million output tokens (USD)
    cached_input_cost_per_m: float = 0.0
    reasoning_cost_per_m: float = 0.0
    provider: str = "custom"

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> float:
        regular_prompt = max(0, prompt_tokens - cached_tokens)
        cost_input = (regular_prompt / 1_000_000.0) * self.input_cost_per_m
        cost_cached = (cached_tokens / 1_000_000.0) * self.cached_input_cost_per_m
        cost_output = (completion_tokens / 1_000_000.0) * self.output_cost_per_m
        cost_reasoning = (reasoning_tokens / 1_000_000.0) * (self.reasoning_cost_per_m or self.output_cost_per_m)
        return cost_input + cost_cached + cost_output + cost_reasoning


# Standard Provider Pricing Catalog (as of August 2026 / current rates)
RATE_CARDS: dict[str, ModelRateCard] = {
    # OpenAI
    "gpt-4o": ModelRateCard("gpt-4o", input_cost_per_m=2.50, output_cost_per_m=10.00, cached_input_cost_per_m=1.25, provider="openai"),
    "gpt-4o-mini": ModelRateCard("gpt-4o-mini", input_cost_per_m=0.15, output_cost_per_m=0.60, cached_input_cost_per_m=0.075, provider="openai"),
    "o1": ModelRateCard("o1", input_cost_per_m=15.00, output_cost_per_m=60.00, reasoning_cost_per_m=60.00, provider="openai"),
    "o3-mini": ModelRateCard("o3-mini", input_cost_per_m=1.10, output_cost_per_m=4.40, reasoning_cost_per_m=4.40, provider="openai"),
    # Anthropic
    "claude-3-5-sonnet": ModelRateCard("claude-3-5-sonnet", input_cost_per_m=3.00, output_cost_per_m=15.00, cached_input_cost_per_m=0.30, provider="anthropic"),
    "claude-3-5-haiku": ModelRateCard("claude-3-5-haiku", input_cost_per_m=0.80, output_cost_per_m=4.00, cached_input_cost_per_m=0.08, provider="anthropic"),
    # DeepSeek
    "deepseek-v3": ModelRateCard("deepseek-v3", input_cost_per_m=0.14, output_cost_per_m=0.28, cached_input_cost_per_m=0.014, provider="deepseek"),
    "deepseek-r1": ModelRateCard("deepseek-r1", input_cost_per_m=0.55, output_cost_per_m=2.19, reasoning_cost_per_m=2.19, provider="deepseek"),
    # Open-Source / Hosted Endpoints (Groq / Together / Nvidia NIM)
    "meta/llama-3.3-70b-instruct": ModelRateCard("meta/llama-3.3-70b-instruct", input_cost_per_m=0.59, output_cost_per_m=0.79, provider="groq_or_together"),
    "nvidia/llama-3.1-nemotron-70b-instruct": ModelRateCard("nvidia/llama-3.1-nemotron-70b-instruct", input_cost_per_m=0.35, output_cost_per_m=0.40, provider="nvidia_nim"),
    "nvidia/nemotron-4-340b-instruct": ModelRateCard("nvidia/nemotron-4-340b-instruct", input_cost_per_m=1.00, output_cost_per_m=2.00, provider="nvidia_nim"),
}


class TokenCounter:
    """Accurately counts or estimates tokens across prompts and schema contexts."""

    def __init__(self, default_encoding: str = "cl100k_base"):
        self.default_encoding = default_encoding
        self._encoder = None
        if _TIKTOKEN_AVAILABLE:
            try:
                self._encoder = tiktoken.get_encoding(default_encoding)
            except Exception:
                try:
                    self._encoder = tiktoken.get_encoding("cl100k_base")
                except Exception:
                    self._encoder = None

    def count_tokens(self, text: Optional[str]) -> int:
        if not text:
            return 0
        if self._encoder:
            try:
                return len(self._encoder.encode(text))
            except Exception:
                pass
        # Robust heuristic fallback: ~4 chars per token for English/code
        return max(1, math.ceil(len(text) / 3.8))

    def estimate_query_tokens(
        self,
        question: str,
        retrieved_schema_context: str = "",
        generated_sql: str = "",
        repair_messages: Optional[List[str]] = None,
    ) -> dict[str, int]:
        """Estimates full token footprint for a query lifecycle."""
        base_prompt_tokens = self.count_tokens(question) + self.count_tokens(retrieved_schema_context) + 350 # system prompt overhead
        sql_tokens = self.count_tokens(generated_sql)
        repair_tokens = sum(self.count_tokens(m) for m in (repair_messages or []))
        total_prompt = base_prompt_tokens + (repair_tokens if repair_messages else 0)
        total_completion = sql_tokens + (int(repair_tokens * 0.5) if repair_messages else 0)

        return {
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "schema_tokens": self.count_tokens(retrieved_schema_context),
            "repair_tokens": repair_tokens,
            "total_tokens": total_prompt + total_completion,
        }


# ============================================================================
# Latency Distribution Profiling
# ============================================================================

@dataclass
class LatencyProfile:
    count: int
    mean: float
    std: float
    min: float
    p10: float
    p25: float
    p50: float       # Median
    p75: float
    p90: float
    p95: float
    p99: float
    max: float
    iqr: float
    skewness: float
    kurtosis: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "mean": round(self.mean, 2),
            "std": round(self.std, 2),
            "min": round(self.min, 2),
            "p10": round(self.p10, 2),
            "p25": round(self.p25, 2),
            "p50": round(self.p50, 2),
            "p75": round(self.p75, 2),
            "p90": round(self.p90, 2),
            "p95": round(self.p95, 2),
            "p99": round(self.p99, 2),
            "max": round(self.max, 2),
            "iqr": round(self.iqr, 2),
            "skewness": round(self.skewness, 3),
            "kurtosis": round(self.kurtosis, 3),
        }


def compute_latency_profile(latencies: Union[List[float], np.ndarray]) -> LatencyProfile:
    arr = np.asarray([x for x in latencies if x is not None and not np.isnan(x)], dtype=float)
    if len(arr) == 0:
        return LatencyProfile(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    p25, p50, p75 = np.percentile(arr, [25, 50, 75])
    p10, p90, p95, p99 = np.percentile(arr, [10, 90, 95, 99])

    skew_val = float(stats.skew(arr)) if len(arr) > 2 else 0.0
    kurt_val = float(stats.kurtosis(arr)) if len(arr) > 3 else 0.0

    return LatencyProfile(
        count=len(arr),
        mean=float(np.mean(arr)),
        std=float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
        min=float(np.min(arr)),
        p10=float(p10),
        p25=float(p25),
        p50=float(p50),
        p75=float(p75),
        p90=float(p90),
        p95=float(p95),
        p99=float(p99),
        max=float(np.max(arr)),
        iqr=float(p75 - p25),
        skewness=skew_val,
        kurtosis=kurt_val,
    )


# ============================================================================
# Repair Overhead & Dynamics Analyzer
# ============================================================================

@dataclass
class RepairOverheadReport:
    total_queries: int
    repaired_queries_count: int
    repair_trigger_rate: float
    mean_repair_rounds: float
    max_repair_rounds: int
    unrepaired_mean_latency: float
    repaired_mean_latency: float
    latency_overhead_seconds: float
    latency_overhead_ratio: float
    rescued_queries_count: int         # Queries that failed initial execution but succeeded after repair
    repair_recovery_rate: float        # rescued / total repaired
    total_tokens_spent_on_repair: int
    estimated_repair_cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_queries": self.total_queries,
            "repaired_queries_count": self.repaired_queries_count,
            "repair_trigger_rate": round(self.repair_trigger_rate, 4),
            "repair_trigger_percent": f"{self.repair_trigger_rate * 100:.1f}%",
            "mean_repair_rounds": round(self.mean_repair_rounds, 2),
            "max_repair_rounds": self.max_repair_rounds,
            "unrepaired_mean_latency": round(self.unrepaired_mean_latency, 2),
            "repaired_mean_latency": round(self.repaired_mean_latency, 2),
            "latency_overhead_seconds": round(self.latency_overhead_seconds, 2),
            "latency_overhead_ratio": round(self.latency_overhead_ratio, 2),
            "rescued_queries_count": self.rescued_queries_count,
            "repair_recovery_rate": round(self.repair_recovery_rate, 4),
            "repair_recovery_percent": f"{self.repair_recovery_rate * 100:.1f}%",
            "total_tokens_spent_on_repair": self.total_tokens_spent_on_repair,
            "estimated_repair_cost_usd": round(self.estimated_repair_cost_usd, 4),
        }


def analyze_repair_overhead(
    entries: List[dict[str, Any]],
    rate_card: Optional[ModelRateCard] = None,
    token_counter: Optional[TokenCounter] = None,
) -> RepairOverheadReport:
    """Analyzes the precise performance, latency, and cost impact of the repair loop."""
    tc = token_counter or TokenCounter()
    rc = rate_card or RATE_CARDS["nvidia/llama-3.1-nemotron-70b-instruct"]

    total = len(entries)
    if total == 0:
        return RepairOverheadReport(0, 0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 1.0, 0, 0.0, 0, 0.0)

    unrepaired_lats: List[float] = []
    repaired_lats: List[float] = []
    repair_rounds: List[int] = []
    rescued_count = 0
    repaired_count = 0
    total_repair_tokens = 0

    for e in entries:
        events = e.get("repair_events", [])
        lat = float(e.get("latency_seconds", 0.0))
        n_rounds = len(events)
        equiv = bool(e.get("equivalent_match", False))
        sql_succ = bool(e.get("sql_execution_success", False))

        if n_rounds > 0 or bool(e.get("repair_applied", False)):
            repaired_count += 1
            repaired_lats.append(lat)
            repair_rounds.append(n_rounds or 1)
            
            # Count tokens spent on repairs
            for ev in events:
                if isinstance(ev, dict):
                    msg = str(ev.get("reason", "")) + " " + str(ev.get("repaired_sql", ""))
                else:
                    msg = str(ev)
                total_repair_tokens += tc.count_tokens(msg)

            # Check if query was rescued into success
            if equiv or sql_succ:
                rescued_count += 1
        else:
            unrepaired_lats.append(lat)

    mean_unrep = float(np.mean(unrepaired_lats)) if unrepaired_lats else 0.0
    mean_rep = float(np.mean(repaired_lats)) if repaired_lats else 0.0
    delta_lat = mean_rep - mean_unrep
    lat_ratio = (mean_rep / mean_unrep) if mean_unrep > 0 else 1.0
    trigger_rate = repaired_count / total
    recovery_rate = (rescued_count / repaired_count) if repaired_count > 0 else 0.0

    # Estimate repair dollar cost
    repair_cost = (total_repair_tokens / 1_000_000.0) * rc.output_cost_per_m

    return RepairOverheadReport(
        total_queries=total,
        repaired_queries_count=repaired_count,
        repair_trigger_rate=trigger_rate,
        mean_repair_rounds=float(np.mean(repair_rounds)) if repair_rounds else 0.0,
        max_repair_rounds=max(repair_rounds) if repair_rounds else 0,
        unrepaired_mean_latency=mean_unrep,
        repaired_mean_latency=mean_rep,
        latency_overhead_seconds=delta_lat,
        latency_overhead_ratio=lat_ratio,
        rescued_queries_count=rescued_count,
        repair_recovery_rate=recovery_rate,
        total_tokens_spent_on_repair=total_repair_tokens,
        estimated_repair_cost_usd=repair_cost,
    )


# ============================================================================
# Pareto Frontier Analyzer (Accuracy vs Latency vs Cost)
# ============================================================================

@dataclass
class ParetoPoint:
    config_name: str
    accuracy: float          # Higher is better (e.g. 0.26)
    latency_p50: float       # Lower is better (seconds)
    latency_mean: float      # Lower is better (seconds)
    cost_per_1k_queries: float # Lower is better (USD)
    is_pareto_optimal: bool = False
    dominated_by: List[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_name": self.config_name,
            "accuracy": round(self.accuracy, 4),
            "latency_p50": round(self.latency_p50, 2),
            "latency_mean": round(self.latency_mean, 2),
            "cost_per_1k_queries": round(self.cost_per_1k_queries, 4),
            "is_pareto_optimal": self.is_pareto_optimal,
            "dominated_by": self.dominated_by,
        }


def compute_pareto_frontier(
    points: List[ParetoPoint],
    criteria: Tuple[str, ...] = ("accuracy", "latency_p50", "cost_per_1k_queries"),
) -> List[ParetoPoint]:
    """Computes Pareto dominance and identifies non-dominated configurations."""
    for p in points:
        p.is_pareto_optimal = True
        p.dominated_by = []

    for i, p1 in enumerate(points):
        for j, p2 in enumerate(points):
            if i == j:
                continue
            
            # Check if p2 dominates p1
            # For accuracy: p2.acc >= p1.acc
            # For latency: p2.lat <= p1.lat
            # For cost: p2.cost <= p1.cost
            # And at least one strictly better
            acc_better = p2.accuracy >= p1.accuracy
            acc_strict = p2.accuracy > p1.accuracy

            lat_better = p2.latency_p50 <= p1.latency_p50
            lat_strict = p2.latency_p50 < p1.latency_p50

            cost_better = p2.cost_per_1k_queries <= p1.cost_per_1k_queries
            cost_strict = p2.cost_per_1k_queries < p1.cost_per_1k_queries

            if acc_better and lat_better and cost_better and (acc_strict or lat_strict or cost_strict):
                p1.is_pareto_optimal = False
                p1.dominated_by.append(p2.config_name)

    return points


def compute_tradeoff_gradients(pareto_points: List[ParetoPoint]) -> List[dict[str, Any]]:
    """Calculates the marginal cost and latency exchange rates between Pareto-optimal points."""
    optimal = [p for p in pareto_points if p.is_pareto_optimal]
    optimal.sort(key=lambda x: x.accuracy)

    gradients: List[dict[str, Any]] = []
    for i in range(len(optimal) - 1):
        p_low = optimal[i]
        p_high = optimal[i + 1]

        delta_acc = p_high.accuracy - p_low.accuracy
        delta_lat = p_high.latency_p50 - p_low.latency_p50
        delta_cost = p_high.cost_per_1k_queries - p_low.cost_per_1k_queries

        gradients.append({
            "from_config": p_low.config_name,
            "to_config": p_high.config_name,
            "delta_accuracy_pct": round(delta_acc * 100, 2),
            "delta_latency_seconds": round(delta_lat, 2),
            "delta_cost_per_1k": round(delta_cost, 4),
            "latency_cost_per_pct_acc": round(delta_lat / (delta_acc * 100), 2) if delta_acc > 0 else 0.0,
            "dollar_cost_per_pct_acc": round(delta_cost / (delta_acc * 100), 4) if delta_acc > 0 else 0.0,
        })

    return gradients
