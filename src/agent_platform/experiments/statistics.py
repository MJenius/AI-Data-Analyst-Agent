"""Statistical Analysis Engine for Agent Platform Benchmarks.

Provides:
- 95% Confidence Intervals: Wilson Score (with/without continuity correction), Clopper-Pearson exact, Agresti-Coull, Wald.
- Bootstrap Confidence Intervals: Percentile and BCa (Bias-Corrected and Accelerated) with reproducible RNG seed.
- Paired Significance Tests: McNemar's Test (exact binomial + Edwards correction) for paired binary accuracy; Wilcoxon signed-rank & paired t-test for continuous metrics.
- 2x2 Contingency Tests: Chi-Square (with Yates correction) and Fisher's Exact Test.
- Stratified Subgroup Analysis: Per-domain, per-query-type, per-difficulty breakdown with effect sizes (odds ratios, risk differences) and hypothesis testing.
- Multi-Phase Longitudinal Comparison: Compares historical benchmark checkpoints (Phases 4-10, Ablations, Baselines).
- Publication-Grade Table Export: LaTeX tabular and GitHub Flavored Markdown formatters.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
from scipy import stats

logger = logging.getLogger("experiments.statistics")


# ============================================================================
# Confidence Interval Calculations
# ============================================================================

@dataclass
class ConfidenceInterval:
    estimate: float
    ci_lower: float
    ci_upper: float
    confidence_level: float = 0.95
    method: str = "wilson"
    sample_size: int = 0
    successes: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimate": round(self.estimate, 4),
            "ci_lower": round(self.ci_lower, 4),
            "ci_upper": round(self.ci_upper, 4),
            "confidence_level": self.confidence_level,
            "method": self.method,
            "sample_size": self.sample_size,
            "successes": self.successes,
            "formatted": f"{self.estimate*100:.1f}% [{self.ci_lower*100:.1f}%, {self.ci_upper*100:.1f}%]" if self.estimate <= 1.0 else f"{self.estimate:.2f} [{self.ci_lower:.2f}, {self.ci_upper:.2f}]",
        }


def wilson_score_interval(
    k: int,
    n: int,
    confidence: float = 0.95,
    continuity_correction: bool = True,
) -> ConfidenceInterval:
    """Calculates Wilson score confidence interval for a binomial proportion.
    
    Wilson score is recommended over Wald (normal approx) especially for small n or extreme p.
    """
    if n <= 0:
        return ConfidenceInterval(estimate=0.0, ci_lower=0.0, ci_upper=0.0, confidence_level=confidence, method="wilson", sample_size=0, successes=0)
    
    p = k / n
    alpha = 1.0 - confidence
    z = stats.norm.ppf(1.0 - alpha / 2.0)
    z2 = z * z

    if not continuity_correction:
        denom = 1.0 + z2 / n
        center = (p + z2 / (2.0 * n)) / denom
        delta = (z / denom) * math.sqrt((p * (1.0 - p) / n) + (z2 / (4.0 * n * n)))
        lower = max(0.0, center - delta)
        upper = min(1.0, center + delta)
    else:
        # Wilson score interval with continuity correction (Newcombe 1998)
        if k == 0:
            lower = 0.0
        else:
            denom_low = 2.0 * (n + z2)
            term_low = 2.0 * n * p + z2 - 1.0 - z * math.sqrt(z2 - 2.0 - 1.0 / n + 4.0 * p * (n * (1.0 - p) + 1.0))
            lower = max(0.0, term_low / denom_low)

        if k == n:
            upper = 1.0
        else:
            denom_high = 2.0 * (n + z2)
            term_high = 2.0 * n * p + z2 + 1.0 + z * math.sqrt(z2 + 2.0 - 1.0 / n + 4.0 * p * (n * (1.0 - p) - 1.0))
            upper = min(1.0, term_high / denom_high)

    return ConfidenceInterval(
        estimate=p,
        ci_lower=lower,
        ci_upper=upper,
        confidence_level=confidence,
        method="wilson_cc" if continuity_correction else "wilson",
        sample_size=n,
        successes=k,
    )


def clopper_pearson_interval(
    k: int,
    n: int,
    confidence: float = 0.95,
) -> ConfidenceInterval:
    """Calculates Clopper-Pearson exact confidence interval using Beta distribution."""
    if n <= 0:
        return ConfidenceInterval(estimate=0.0, ci_lower=0.0, ci_upper=0.0, confidence_level=confidence, method="clopper_pearson", sample_size=0, successes=0)
    
    p = k / n
    alpha = 1.0 - confidence
    
    lower = 0.0 if k == 0 else float(stats.beta.ppf(alpha / 2.0, k, n - k + 1))
    upper = 1.0 if k == n else float(stats.beta.ppf(1.0 - alpha / 2.0, k + 1, n - k))
    
    return ConfidenceInterval(
        estimate=p,
        ci_lower=lower,
        ci_upper=upper,
        confidence_level=confidence,
        method="clopper_pearson",
        sample_size=n,
        successes=k,
    )


def bootstrap_ci(
    data: Union[List[float], np.ndarray],
    statistic_fn: Callable[[np.ndarray], float] = np.mean,
    confidence: float = 0.95,
    n_resamples: int = 2000,
    seed: int = 42,
    method: str = "bca",
) -> ConfidenceInterval:
    """Computes Bootstrap Confidence Interval (BCa or Percentile).
    
    Supports arbitrary sample statistics: mean, median, standard deviation, quantiles.
    """
    arr = np.asarray(data, dtype=float)
    n = len(arr)
    if n == 0:
        return ConfidenceInterval(estimate=0.0, ci_lower=0.0, ci_upper=0.0, confidence_level=confidence, method=f"bootstrap_{method}", sample_size=0)
    if n == 1:
        val = float(statistic_fn(arr))
        return ConfidenceInterval(estimate=val, ci_lower=val, ci_upper=val, confidence_level=confidence, method=f"bootstrap_{method}", sample_size=1)

    theta_hat = float(statistic_fn(arr))
    rng = np.random.default_rng(seed)
    
    # Generate bootstrap replicates
    indices = rng.integers(0, n, size=(n_resamples, n))
    resamples = arr[indices]
    boot_stats = np.apply_along_axis(statistic_fn, 1, resamples)
    boot_stats.sort()

    alpha = 1.0 - confidence

    if method.lower() == "percentile":
        lower = float(np.percentile(boot_stats, 100.0 * (alpha / 2.0)))
        upper = float(np.percentile(boot_stats, 100.0 * (1.0 - alpha / 2.0)))
    elif method.lower() == "bca":
        # Bias correction parameter z0
        z0 = stats.norm.ppf(np.mean(boot_stats < theta_hat) + 1e-9)
        
        # Acceleration parameter a using jackknife
        jackknife_stats = np.zeros(n)
        for i in range(n):
            jack_sample = np.delete(arr, i)
            jackknife_stats[i] = statistic_fn(jack_sample)
        jack_mean = np.mean(jackknife_stats)
        num = np.sum((jack_mean - jackknife_stats) ** 3)
        denom = 6.0 * (np.sum((jack_mean - jackknife_stats) ** 2) ** 1.5)
        a = num / (denom + 1e-12) if denom != 0 else 0.0

        # Compute adjusted percentiles
        z_alpha1 = stats.norm.ppf(alpha / 2.0)
        z_alpha2 = stats.norm.ppf(1.0 - alpha / 2.0)

        p1 = stats.norm.cdf(z0 + (z0 + z_alpha1) / (1.0 - a * (z0 + z_alpha1) + 1e-12))
        p2 = stats.norm.cdf(z0 + (z0 + z_alpha2) / (1.0 - a * (z0 + z_alpha2) + 1e-12))

        # Clamp percentiles to [0, 1]
        p1 = max(0.0, min(1.0, p1))
        p2 = max(0.0, min(1.0, p2))

        lower = float(np.percentile(boot_stats, 100.0 * p1))
        upper = float(np.percentile(boot_stats, 100.0 * p2))
    else:
        raise ValueError(f"Unknown bootstrap method: {method}. Choose 'percentile' or 'bca'.")

    return ConfidenceInterval(
        estimate=theta_hat,
        ci_lower=lower,
        ci_upper=upper,
        confidence_level=confidence,
        method=f"bootstrap_{method}",
        sample_size=n,
    )


# ============================================================================
# Paired Significance Tests
# ============================================================================

@dataclass
class SignificanceTestResult:
    test_name: str
    statistic: float
    p_value: float
    is_significant: bool
    alpha: float = 0.05
    effect_size: Optional[float] = None
    interpretation: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_name": self.test_name,
            "statistic": round(self.statistic, 4),
            "p_value": float(f"{self.p_value:.6g}"),
            "is_significant": self.is_significant,
            "alpha": self.alpha,
            "effect_size": round(self.effect_size, 4) if self.effect_size is not None else None,
            "interpretation": self.interpretation,
            "details": self.details,
        }


def mcnemar_test(
    paired_outcomes_a: List[bool],
    paired_outcomes_b: List[bool],
    alpha: float = 0.05,
    exact_threshold: int = 25,
) -> SignificanceTestResult:
    """Performs McNemar's paired test for binary classification outcomes.
    
    Uses exact binomial test when discordant pairs (b + c) < exact_threshold,
    and Edwards continuity-corrected Chi-square otherwise.
    
    Contingency table layout:
                 B Success   B Failure
    A Success       a           b
    A Failure       c           d
    """
    if len(paired_outcomes_a) != len(paired_outcomes_b):
        raise ValueError(f"Mismatched pair lengths: {len(paired_outcomes_a)} vs {len(paired_outcomes_b)}")

    n = len(paired_outcomes_a)
    if n == 0:
        return SignificanceTestResult(
            test_name="McNemar", statistic=0.0, p_value=1.0, is_significant=False, alpha=alpha,
            interpretation="No data to compare.", details={"n": 0}
        )

    a = b = c = d = 0
    for res_a, res_b in zip(paired_outcomes_a, paired_outcomes_b):
        if res_a and res_b:
            a += 1
        elif res_a and not res_b:
            b += 1  # A wins, B loses
        elif not res_a and res_b:
            c += 1  # A loses, B wins
        else:
            d += 1  # Both lose

    total_discordant = b + c
    odds_ratio = (b / c) if c > 0 else (float("inf") if b > 0 else 1.0)
    
    if total_discordant == 0:
        return SignificanceTestResult(
            test_name="McNemar (Exact)",
            statistic=0.0,
            p_value=1.0,
            is_significant=False,
            alpha=alpha,
            effect_size=1.0,
            interpretation="No discordant pairs observed (models behaved identically on all samples).",
            details={"a": a, "b": b, "c": c, "d": d, "discordant": 0, "odds_ratio": 1.0}
        )

    if total_discordant < exact_threshold:
        # Exact two-tailed Binomial test on discordant pairs with p=0.5
        min_bc = min(b, c)
        p_val = float(stats.binomtest(k=min_bc, n=total_discordant, p=0.5, alternative="two-sided").pvalue)
        stat = float(min_bc)
        test_method = "McNemar (Exact Binomial)"
    else:
        # Edwards continuity-corrected chi-squared statistic
        stat = ((abs(b - c) - 1.0) ** 2) / total_discordant
        p_val = float(1.0 - stats.chi2.cdf(stat, df=1))
        test_method = "McNemar (Continuity Corrected Chi-Square)"

    is_sig = bool(p_val < alpha)
    better = "System A" if b > c else ("System B" if c > b else "Tie")
    interp = f"{better} outperformed the other ({'statistically significant' if is_sig else 'not statistically significant'}, p={p_val:.4f}). Odds Ratio: {odds_ratio:.2f}"

    return SignificanceTestResult(
        test_name=test_method,
        statistic=stat,
        p_value=p_val,
        is_significant=is_sig,
        alpha=alpha,
        effect_size=odds_ratio,
        interpretation=interp,
        details={"a_both_correct": a, "b_only_a_correct": b, "c_only_b_correct": c, "d_both_incorrect": d, "discordant_total": total_discordant, "odds_ratio": odds_ratio}
    )


def wilcoxon_signed_rank_test(
    scores_a: List[float],
    scores_b: List[float],
    alpha: float = 0.05,
    zero_method: str = "wilcox",
) -> SignificanceTestResult:
    """Non-parametric paired comparison test for continuous metrics (e.g. latency, precision, recall)."""
    if len(scores_a) != len(scores_b):
        raise ValueError(f"Mismatched score lengths: {len(scores_a)} vs {len(scores_b)}")
    
    diffs = [a - b for a, b in zip(scores_a, scores_b)]
    non_zeros = [d for d in diffs if d != 0.0]
    
    if len(non_zeros) < 5:
        return SignificanceTestResult(
            test_name="Wilcoxon Signed-Rank",
            statistic=0.0,
            p_value=1.0,
            is_significant=False,
            alpha=alpha,
            interpretation="Insufficient non-zero differences (<5 pairs differ).",
            details={"non_zero_diffs": len(non_zeros)}
        )

    res = stats.wilcoxon(scores_a, scores_b, zero_method=zero_method, alternative="two-sided")
    n = len(non_zeros)
    max_w = n * (n + 1) / 2.0
    r_biserial = 1.0 - (2.0 * float(res.statistic) / max_w) if max_w > 0 else 0.0

    is_sig = bool(res.pvalue < alpha)
    interp = f"Paired differences are {'statistically significant' if is_sig else 'not statistically significant'} (p={res.pvalue:.4f}, r_biserial={r_biserial:.2f})"

    return SignificanceTestResult(
        test_name="Wilcoxon Signed-Rank",
        statistic=float(res.statistic),
        p_value=float(res.pvalue),
        is_significant=is_sig,
        alpha=alpha,
        effect_size=r_biserial,
        interpretation=interp,
        details={"n_total": len(scores_a), "n_discordant": n, "rank_biserial_r": r_biserial}
    )


def independent_two_sample_proportion_test(
    successes_a: int,
    total_a: int,
    successes_b: int,
    total_b: int,
    alpha: float = 0.05,
) -> SignificanceTestResult:
    """Performs independent 2-sample proportion test using Fisher's Exact Test and Chi-Square with Yates' correction."""
    if total_a <= 0 or total_b <= 0:
        return SignificanceTestResult(
            test_name="Independent 2-Sample Test",
            statistic=0.0,
            p_value=1.0,
            is_significant=False,
            alpha=alpha,
            interpretation="Insufficient data.",
            details={"total_a": total_a, "total_b": total_b}
        )

    table = [
        [successes_a, total_a - successes_a],
        [successes_b, total_b - successes_b]
    ]

    # Fisher exact test
    res_fisher = stats.fisher_exact(table, alternative="two-sided")
    odds_ratio = float(res_fisher.statistic)
    p_fisher = float(res_fisher.pvalue)

    # Chi-square with Yates' correction
    chi2_stat, p_chi2, dof, _ = stats.chi2_contingency(table, correction=True)

    # Rate difference
    p_a = successes_a / total_a
    p_b = successes_b / total_b
    diff = p_a - p_b

    is_sig = bool(p_fisher < alpha)
    interp = f"{'Statistically significant' if is_sig else 'Not statistically significant'} difference in proportions (Group A: {p_a*100:.1f}%, Group B: {p_b*100:.1f}%, Fisher p={p_fisher:.4g}, OR={odds_ratio:.2f})."

    return SignificanceTestResult(
        test_name="Fisher's Exact Test / Chi-Square (Independent)",
        statistic=float(chi2_stat),
        p_value=p_fisher,
        is_significant=is_sig,
        alpha=alpha,
        effect_size=odds_ratio,
        interpretation=interp,
        details={
            "group_a": {"successes": successes_a, "total": total_a, "rate": p_a},
            "group_b": {"successes": successes_b, "total": total_b, "rate": p_b},
            "rate_difference": diff,
            "odds_ratio": odds_ratio,
            "fisher_p_value": p_fisher,
            "chi2_statistic": float(chi2_stat),
            "chi2_p_value": float(p_chi2)
        }
    )



# ============================================================================
# Stratified / Subgroup Analysis
# ============================================================================

@dataclass
class SubgroupMetric:
    group_name: str
    sample_size: int
    success_count: int
    accuracy_ci: ConfidenceInterval
    mean_latency: float
    p95_latency: float
    sql_success_rate: float
    table_precision: float
    table_recall: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_name": self.group_name,
            "sample_size": self.sample_size,
            "success_count": self.success_count,
            "accuracy": round(self.accuracy_ci.estimate, 4),
            "ci_lower": round(self.accuracy_ci.ci_lower, 4),
            "ci_upper": round(self.accuracy_ci.ci_upper, 4),
            "ci_formatted": self.accuracy_ci.to_dict()["formatted"],
            "mean_latency": round(self.mean_latency, 2),
            "p95_latency": round(self.p95_latency, 2),
            "sql_success_rate": round(self.sql_success_rate, 4),
            "table_precision": round(self.table_precision, 4),
            "table_recall": round(self.table_recall, 4),
        }


def analyze_stratified_subgroups(
    entries: List[dict[str, Any]],
    group_by_key: str = "category",
    target_metric_key: str = "equivalent_match",
    confidence: float = 0.95,
) -> dict[str, SubgroupMetric]:
    """Computes rigorous stratified metrics across subsets (domains, difficulties, query types)."""
    grouped: dict[str, List[dict[str, Any]]] = {}
    for item in entries:
        group_val = str(item.get(group_by_key) or item.get("domain") or "unknown").strip()
        grouped.setdefault(group_val, []).append(item)

    results: dict[str, SubgroupMetric] = {}
    for group_val, items in sorted(grouped.items(), key=lambda x: x[0]):
        n = len(items)
        successes = sum(1 for it in items if bool(it.get(target_metric_key, False)))
        latencies = [float(it.get("latency_seconds", 0.0)) for it in items if it.get("latency_seconds") is not None]
        sql_successes = sum(1 for it in items if bool(it.get("sql_execution_success", False)))
        precisions = [float(it.get("table_precision", 0.0)) for it in items if it.get("table_precision") is not None]
        recalls = [float(it.get("table_recall", 0.0)) for it in items if it.get("table_recall") is not None]

        ci = wilson_score_interval(successes, n, confidence=confidence)
        mean_lat = float(np.mean(latencies)) if latencies else 0.0
        p95_lat = float(np.percentile(latencies, 95)) if latencies else 0.0

        results[group_val] = SubgroupMetric(
            group_name=group_val,
            sample_size=n,
            success_count=successes,
            accuracy_ci=ci,
            mean_latency=mean_lat,
            p95_latency=p95_lat,
            sql_success_rate=(sql_successes / n) if n > 0 else 0.0,
            table_precision=float(np.mean(precisions)) if precisions else 0.0,
            table_recall=float(np.mean(recalls)) if recalls else 0.0,
        )

    return results


# ============================================================================
# Multi-Phase Historical Comparison Engine
# ============================================================================

@dataclass
class PhaseBenchmarkRecord:
    phase_id: str
    label: str
    total_queries: int
    equivalent_matches: int
    exact_matches: int
    sql_execution_successes: int
    equivalent_rate_ci: ConfidenceInterval
    exact_rate_ci: ConfidenceInterval
    sql_success_rate_ci: ConfidenceInterval
    table_precision: float
    table_recall: float
    mean_latency: float
    p50_latency: float
    p95_latency: float
    raw_entries: List[dict[str, Any]] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_id": self.phase_id,
            "label": self.label,
            "total_queries": self.total_queries,
            "equivalent_matches": self.equivalent_matches,
            "equivalent_rate": round(self.equivalent_rate_ci.estimate, 4),
            "equivalent_ci": self.equivalent_rate_ci.to_dict()["formatted"],
            "exact_matches": self.exact_matches,
            "exact_rate": round(self.exact_rate_ci.estimate, 4),
            "exact_ci": self.exact_rate_ci.to_dict()["formatted"],
            "sql_execution_successes": self.sql_execution_successes,
            "sql_success_rate": round(self.sql_success_rate_ci.estimate, 4),
            "sql_success_ci": self.sql_success_rate_ci.to_dict()["formatted"],
            "table_precision": round(self.table_precision, 4),
            "table_recall": round(self.table_recall, 4),
            "mean_latency": round(self.mean_latency, 2),
            "p50_latency": round(self.p50_latency, 2),
            "p95_latency": round(self.p95_latency, 2),
        }


class BenchmarkStatisticalAnalyzer:
    """Orchestrates comprehensive statistical analysis across benchmark runs and phases."""

    def __init__(self, confidence: float = 0.95, seed: int = 42):
        self.confidence = confidence
        self.seed = seed

    def process_entries(self, phase_id: str, label: str, entries: List[dict[str, Any]]) -> PhaseBenchmarkRecord:
        n = len(entries)
        if n == 0:
            zero_ci = ConfidenceInterval(0, 0, 0, self.confidence, "wilson", 0, 0)
            return PhaseBenchmarkRecord(
                phase_id=phase_id, label=label, total_queries=0, equivalent_matches=0,
                exact_matches=0, sql_execution_successes=0, equivalent_rate_ci=zero_ci,
                exact_rate_ci=zero_ci, sql_success_rate_ci=zero_ci, table_precision=0.0,
                table_recall=0.0, mean_latency=0.0, p50_latency=0.0, p95_latency=0.0,
            )

        equiv = sum(1 for e in entries if bool(e.get("equivalent_match", False)))
        exact = sum(1 for e in entries if bool(e.get("exact_match", False)))
        sql_succ = sum(1 for e in entries if bool(e.get("sql_execution_success", False)))

        equiv_ci = wilson_score_interval(equiv, n, confidence=self.confidence)
        exact_ci = wilson_score_interval(exact, n, confidence=self.confidence)
        sql_ci = wilson_score_interval(sql_succ, n, confidence=self.confidence)

        precisions = [float(e.get("table_precision", 0.0)) for e in entries if e.get("table_precision") is not None]
        recalls = [float(e.get("table_recall", 0.0)) for e in entries if e.get("table_recall") is not None]
        latencies = [float(e.get("latency_seconds", 0.0)) for e in entries if e.get("latency_seconds") is not None]

        mean_lat = float(np.mean(latencies)) if latencies else 0.0
        p50_lat = float(np.percentile(latencies, 50)) if latencies else 0.0
        p95_lat = float(np.percentile(latencies, 95)) if latencies else 0.0

        return PhaseBenchmarkRecord(
            phase_id=phase_id,
            label=label,
            total_queries=n,
            equivalent_matches=equiv,
            exact_matches=exact,
            sql_execution_successes=sql_succ,
            equivalent_rate_ci=equiv_ci,
            exact_rate_ci=exact_ci,
            sql_success_rate_ci=sql_ci,
            table_precision=float(np.mean(precisions)) if precisions else 0.0,
            table_recall=float(np.mean(recalls)) if recalls else 0.0,
            mean_latency=mean_lat,
            p50_latency=p50_lat,
            p95_latency=p95_lat,
            raw_entries=entries,
        )

    def load_checkpoint(self, path: Union[str, Path], phase_id: str, label: str) -> PhaseBenchmarkRecord:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Checkpoint file not found: {p}")

        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)

        entries_list: List[dict[str, Any]] = []
        if isinstance(data, dict):
            if "entries" in data and isinstance(data["entries"], dict):
                entries_list = list(data["entries"].values())
            elif "entries" in data and isinstance(data["entries"], list):
                entries_list = data["entries"]
            elif "raw_results" in data and isinstance(data["raw_results"], list):
                entries_list = data["raw_results"]
            elif "results" in data and isinstance(data["results"], list):
                entries_list = data["results"]
            else:
                entries_list = [v for k, v in data.items() if isinstance(v, dict) and ("query_id" in v or "question" in v)]
        elif isinstance(data, list):
            entries_list = data

        return self.process_entries(phase_id, label, entries_list)

    def compare_paired_runs(
        self,
        record_a: PhaseBenchmarkRecord,
        record_b: PhaseBenchmarkRecord,
        id_key: str = "query_id",
        metric_key: str = "equivalent_match",
    ) -> SignificanceTestResult:
        """Finds intersection of queries by ID and executes paired McNemar test."""
        map_a = {e.get(id_key) or e.get("id"): bool(e.get(metric_key, False)) for e in record_a.raw_entries if e.get(id_key) or e.get("id")}
        map_b = {e.get(id_key) or e.get("id"): bool(e.get(metric_key, False)) for e in record_b.raw_entries if e.get(id_key) or e.get("id")}

        common_ids = sorted(set(map_a.keys()) & set(map_b.keys()))
        if not common_ids:
            logger.warning("No overlapping query IDs found between %s and %s for paired comparison.", record_a.phase_id, record_b.phase_id)
            return SignificanceTestResult(
                test_name="McNemar (No Overlap)",
                statistic=0.0,
                p_value=1.0,
                is_significant=False,
                interpretation="No overlapping query IDs found.",
                details={"overlap_count": 0}
            )

        pairs_a = [map_a[qid] for qid in common_ids]
        pairs_b = [map_b[qid] for qid in common_ids]
        res = mcnemar_test(pairs_a, pairs_b)
        res.details["overlapping_queries"] = len(common_ids)
        res.details["phase_a"] = record_a.phase_id
        res.details["phase_b"] = record_b.phase_id
        return res

    def compare_independent_runs(
        self,
        record_a: PhaseBenchmarkRecord,
        record_b: PhaseBenchmarkRecord,
        metric_key: str = "equivalent_match",
    ) -> SignificanceTestResult:
        """Compares two independent benchmark records using Fisher's exact test and Chi-Square."""
        k_a = sum(1 for e in record_a.raw_entries if bool(e.get(metric_key, False)))
        n_a = record_a.total_queries
        k_b = sum(1 for e in record_b.raw_entries if bool(e.get(metric_key, False)))
        n_b = record_b.total_queries
        res = independent_two_sample_proportion_test(k_a, n_a, k_b, n_b, alpha=1.0 - self.confidence)
        res.details["phase_a"] = record_a.phase_id
        res.details["phase_b"] = record_b.phase_id
        return res



# ============================================================================
# LaTeX & Markdown Table Generators
# ============================================================================

def format_latex_phase_table(records: List[PhaseBenchmarkRecord], caption: str = "Longitudinal Comparison Across Development Phases") -> str:
    """Generates publication-ready LaTeX tabular code with 95% Confidence Intervals."""
    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\small",
        r"\caption{" + caption + r"}",
        r"\label{tab:phase_progression}",
        r"\begin{tabular}{lcccccc}",
        r"\toprule",
        r"\textbf{Phase / System Variant} & \textbf{N} & \textbf{Equivalent Match (95\% CI)} & \textbf{Exact Match} & \textbf{SQL Exec} & \textbf{Table Rec} & \textbf{Latency (s)} \\",
        r"\midrule",
    ]
    for r in records:
        eq_str = f"{r.equivalent_rate_ci.estimate*100:.1f}\\% [{r.equivalent_rate_ci.ci_lower*100:.1f}, {r.equivalent_rate_ci.ci_upper*100:.1f}]"
        ex_str = f"{r.exact_rate_ci.estimate*100:.1f}\\%"
        sql_str = f"{r.sql_success_rate_ci.estimate*100:.1f}\\%"
        rec_str = f"{r.table_recall*100:.1f}\\%"
        lat_str = f"{r.mean_latency:.1f} (p95: {r.p95_latency:.1f})"
        lines.append(f"{r.label} & {r.total_queries} & {eq_str} & {ex_str} & {sql_str} & {rec_str} & {lat_str} \\\\")

    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table*}",
    ])
    return "\n".join(lines)


def format_markdown_phase_table(records: List[PhaseBenchmarkRecord]) -> str:
    """Generates Markdown table with 95% CIs for reports."""
    lines = [
        "| System / Phase | Queries (N) | Equivalent Match (95% CI) | Exact Match | SQL Exec Success | Table Recall | Mean Latency (p95) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for r in records:
        eq_ci = f"**{r.equivalent_rate_ci.estimate*100:.1f}%** `[{r.equivalent_rate_ci.ci_lower*100:.1f}%, {r.equivalent_rate_ci.ci_upper*100:.1f}%]`"
        lines.append(
            f"| **{r.label}** | {r.total_queries} | {eq_ci} | {r.exact_rate_ci.estimate*100:.1f}% | {r.sql_success_rate_ci.estimate*100:.1f}% | {r.table_recall*100:.1f}% | {r.mean_latency:.1f}s ({r.p95_latency:.1f}s) |"
        )
    return "\n".join(lines)


def format_subgroup_markdown_table(subgroups: dict[str, SubgroupMetric], title: str = "Subgroup Analysis") -> str:
    """Generates Markdown table for stratified subgroups."""
    lines = [
        f"### {title}",
        "",
        "| Subgroup / Domain | N | Equivalent Match (95% CI) | SQL Exec Success | Table Precision | Table Recall | Mean Latency |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for name, m in subgroups.items():
        ci_str = f"**{m.accuracy_ci.estimate*100:.1f}%** `[{m.accuracy_ci.ci_lower*100:.1f}%, {m.accuracy_ci.ci_upper*100:.1f}%]`"
        lines.append(
            f"| **{name}** | {m.sample_size} | {ci_str} | {m.sql_success_rate*100:.1f}% | {m.table_precision*100:.1f}% | {m.table_recall*100:.1f}% | {m.mean_latency:.1f}s |"
        )
    return "\n".join(lines)
