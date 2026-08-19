"""Out-Of-Distribution (OOD) & Robustness Evaluation Suite.

Independent from the frozen 500-query benchmark.
Evaluates agent resilience against 5 core perturbation vectors:
1. Syntactic Paraphrasing (passive voice, colloquialisms, conversational questions)
2. Typo Injection (QWERTY adjacent keys, character drops, vowel omissions, domain typos)
3. Ambiguous Domain Synonyms (e.g. turnover <-> revenue, postcode <-> zip_code, merchandise <-> product)
4. Ranking & Ordering Permutations (top-k vs bottom-k, highest vs largest, ties)
5. Temporal Shift Variants (relative timeframes, localized formats, ISO intervals)

Computes robustness drop ΔAcc, retention rate, and per-perturbation degradation matrices.
"""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger("experiments.robustness")

# Brazilian E-Commerce Domain Synonym Dictionary
DOMAIN_SYNONYM_MAP: dict[str, list[str]] = {
    "revenue": ["turnover", "total sales value", "gross receipts", "total monetary intake"],
    "total revenue": ["gross turnover", "aggregate sales volume in BRL", "overall earnings"],
    "freight": ["shipping fee", "delivery charge", "transport cost", "postage fee"],
    "customer": ["buyer", "client", "purchaser", "shopper", "consumer"],
    "customers": ["buyers", "clients", "purchasers", "shoppers"],
    "seller": ["vendor", "merchant", "store owner", "supplier"],
    "sellers": ["vendors", "merchants", "suppliers"],
    "product": ["merchandise", "item", "catalog article", "SKU"],
    "products": ["items", "merchandise", "SKUs", "catalog articles"],
    "order": ["purchase", "transaction", "placed order"],
    "orders": ["transactions", "purchases"],
    "review score": ["satisfaction rating", "customer feedback score", "star rating", "grade"],
    "delivered": ["completed delivery", "dispatched and received", "fulfilled"],
    "delayed": ["late delivery", "exceeded estimated date", "overdue"],
    "payment": ["settlement", "remittance", "transaction payment"],
    "credit card": ["card payment", "credit line"],
    "installments": ["payment splits", "deferred slices", "monthly installments"],
    "zip code": ["postcode", "postal prefix", "CEP", "zip_code_prefix"],
    "state": ["federation unit", "province", "UF"],
    "city": ["municipality", "town"],
    "category": ["product segment", "product department", "merchandise type"],
    "price": ["item cost", "catalog price", "unit value"],
}

# Common QWERTY Adjacent Keys for Realistic Typos
KEYBOARD_ADJACENT: dict[str, str] = {
    'a': 'qwsz', 'b': 'vghn', 'c': 'xdfv', 'd': 'ersfcx', 'e': 'wsdr',
    'f': 'rtgvcd', 'g': 'tyhbvf', 'h': 'yujnbg', 'i': 'ujko', 'j': 'uikmnh',
    'k': 'ijolm', 'l': 'kop', 'm': 'njk', 'n': 'bhjm', 'o': 'iklp',
    'p': 'ol', 'q': 'wa', 'r': 'edft', 's': 'wazxed', 't': 'rfgy',
    'u': 'yhji', 'v': 'cfgb', 'w': 'qase', 'x': 'zsdc', 'y': 'tghu', 'z': 'asx'
}


# ============================================================================
# Perturbation Generators
# ============================================================================

class PerturbationGenerator:
    """Base class for deterministic perturbation injection."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)

    def perturb(self, item: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class ParaphrasePerturbation(PerturbationGenerator):
    """Applies syntactic and conversational restructuring."""

    PREFIXES = [
        "Could you please tell me ",
        "I need to know ",
        "Can you extract ",
        "Show me ",
        "Please query ",
        "Help me find ",
        "What would be ",
        "Provide a breakdown of ",
    ]

    def perturb(self, item: dict[str, Any]) -> dict[str, Any]:
        q = item.get("question", "")
        # Remove trailing question mark and leading 'What is / are'
        cleaned = q.rstrip("?").strip()
        
        lower = cleaned.lower()
        if lower.startswith("what is the "):
            core = cleaned[12:]
            prefix = self.rng.choice(["Can you calculate the ", "Show me the ", "I'd like to see the "])
            new_q = f"{prefix}{core}?"
        elif lower.startswith("what are the "):
            core = cleaned[13:]
            prefix = self.rng.choice(["List the ", "Extract the ", "Show all "])
            new_q = f"{prefix}{core}?"
        elif lower.startswith("how many "):
            core = cleaned[9:]
            prefix = self.rng.choice(["Count the number of ", "What is the total count of "])
            new_q = f"{prefix}{core}?"
        elif lower.startswith("which "):
            core = cleaned[6:]
            prefix = self.rng.choice(["Identify which ", "Find the "])
            new_q = f"{prefix}{core}?"
        else:
            prefix = self.rng.choice(self.PREFIXES)
            new_q = f"{prefix}{cleaned.lower()}?"

        res = dict(item)
        res["id"] = f"{item.get('id', 'q')}_ood_paraphrase"
        res["question"] = new_q
        res["original_question"] = q
        res["perturbation_type"] = "paraphrase"
        return res


class TypoPerturbation(PerturbationGenerator):
    """Injects realistic keyboard and phonetic typos into queries."""

    def __init__(self, typo_rate: float = 0.08, seed: int = 42):
        super().__init__(seed)
        self.typo_rate = typo_rate

    def perturb(self, item: dict[str, Any]) -> dict[str, Any]:
        q = item.get("question", "")
        words = q.split()
        new_words = []

        for word in words:
            # Don't corrupt short words or SQL-like constants
            if len(word) <= 3 or word.isupper() or "'" in word:
                new_words.append(word)
                continue

            if self.rng.random() < 0.35:
                # Apply single character perturbation
                chars = list(word)
                idx = self.rng.randint(0, len(chars) - 1)
                char = chars[idx].lower()
                
                op = self.rng.choice(["swap_adjacent", "drop", "keyboard_adjacent", "duplicate"])
                if op == "swap_adjacent" and idx < len(chars) - 1:
                    chars[idx], chars[idx + 1] = chars[idx + 1], chars[idx]
                elif op == "drop" and len(chars) > 4:
                    chars.pop(idx)
                elif op == "keyboard_adjacent" and char in KEYBOARD_ADJACENT:
                    replacement = self.rng.choice(KEYBOARD_ADJACENT[char])
                    chars[idx] = replacement.upper() if chars[idx].isupper() else replacement
                elif op == "duplicate":
                    chars.insert(idx, chars[idx])

                new_words.append("".join(chars))
            else:
                new_words.append(word)

        new_q = " ".join(new_words)
        if new_q == q and len(words) > 2:
            # Force at least one typo
            idx_word = self.rng.randint(0, len(words) - 1)
            target = list(words[idx_word])
            if len(target) > 3:
                target[1], target[2] = target[2], target[1]
                words[idx_word] = "".join(target)
                new_q = " ".join(words)

        res = dict(item)
        res["id"] = f"{item.get('id', 'q')}_ood_typo"
        res["question"] = new_q
        res["original_question"] = q
        res["perturbation_type"] = "typo"
        return res


class AmbiguousSynonymPerturbation(PerturbationGenerator):
    """Substitutes domain terms with colloquial or business synonyms."""

    def perturb(self, item: dict[str, Any]) -> dict[str, Any]:
        q = item.get("question", "")
        new_q = q

        applied = False
        for term, syns in DOMAIN_SYNONYM_MAP.items():
            pattern = rf"\b{re.escape(term)}\b"
            if re.search(pattern, new_q, re.IGNORECASE):
                replacement = self.rng.choice(syns)
                new_q = re.sub(pattern, replacement, new_q, count=1, flags=re.IGNORECASE)
                applied = True
                break

        if not applied:
            # Fallback simple replacement
            new_q = new_q.replace("total", "aggregate overall").replace("average", "mean arithmetic")

        res = dict(item)
        res["id"] = f"{item.get('id', 'q')}_ood_synonym"
        res["question"] = new_q
        res["original_question"] = q
        res["perturbation_type"] = "synonym"
        return res


class RankingVariantPerturbation(PerturbationGenerator):
    """Permutes ranking queries with alternative syntax (e.g. top 5 vs highest 5 vs bottom 5)."""

    def perturb(self, item: dict[str, Any]) -> dict[str, Any]:
        q = item.get("question", "")
        new_q = q

        if "top " in q.lower():
            new_q = re.sub(r"\btop (\d+)\b", r"highest \1 performing", new_q, flags=re.IGNORECASE)
        elif "highest " in q.lower():
            new_q = re.sub(r"\bhighest (\d+)\b", r"leading \1", new_q, flags=re.IGNORECASE)
        elif "lowest " in q.lower():
            new_q = re.sub(r"\blowest (\d+)\b", r"bottom \1", new_q, flags=re.IGNORECASE)
        elif "most " in q.lower():
            new_q = re.sub(r"\bmost (\w+)\b", r"greatest number of \1", new_q, flags=re.IGNORECASE)
        else:
            new_q = f"{q.rstrip('?')} ranked in descending order?"

        res = dict(item)
        res["id"] = f"{item.get('id', 'q')}_ood_ranking"
        res["question"] = new_q
        res["original_question"] = q
        res["perturbation_type"] = "ranking_variant"
        return res


class TemporalVariantPerturbation(PerturbationGenerator):
    """Reformulates temporal filter formats and grain descriptions."""

    def perturb(self, item: dict[str, Any]) -> dict[str, Any]:
        q = item.get("question", "")
        new_q = q

        if "monthly" in q.lower():
            new_q = re.sub(r"\bmonthly\b", "month-by-month calendar", new_q, flags=re.IGNORECASE)
        elif "in 2017" in q.lower():
            new_q = re.sub(r"\bin 2017\b", "during the entire calendar year 2017 (Jan to Dec)", new_q, flags=re.IGNORECASE)
        elif "in 2018" in q.lower():
            new_q = re.sub(r"\bin 2018\b", "between 2018-01-01 and 2018-12-31", new_q, flags=re.IGNORECASE)
        elif "yearly" in q.lower():
            new_q = re.sub(r"\byearly\b", "on an annual basis", new_q, flags=re.IGNORECASE)
        else:
            new_q = f"{q.rstrip('?')} across historical recorded dates?"

        res = dict(item)
        res["id"] = f"{item.get('id', 'q')}_ood_temporal"
        res["question"] = new_q
        res["original_question"] = q
        res["perturbation_type"] = "temporal_variant"
        return res


# ============================================================================
# OOD Suite Generator & Evaluator
# ============================================================================

class RobustnessSuiteBuilder:
    """Builds a balanced OOD evaluation dataset from a clean benchmark sample."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.generators = {
            "paraphrase": ParaphrasePerturbation(seed=seed),
            "typo": TypoPerturbation(seed=seed + 1),
            "synonym": AmbiguousSynonymPerturbation(seed=seed + 2),
            "ranking": RankingVariantPerturbation(seed=seed + 3),
            "temporal": TemporalVariantPerturbation(seed=seed + 4),
        }

    def generate_suite(self, clean_dataset: List[dict[str, Any]]) -> List[dict[str, Any]]:
        ood_items: List[dict[str, Any]] = []
        gen_keys = list(self.generators.keys())

        for idx, item in enumerate(clean_dataset):
            # Deterministically cycle or apply perturbations
            gen_type = gen_keys[idx % len(gen_keys)]
            generator = self.generators[gen_type]
            perturbed = generator.perturb(item)
            ood_items.append(perturbed)

        logger.info("Generated %d OOD perturbed evaluation queries across %d types.", len(ood_items), len(gen_keys))
        return ood_items


@dataclass
class RobustnessDegradationMetric:
    perturbation_type: str
    clean_accuracy: float
    perturbed_accuracy: float
    absolute_drop: float            # Clean - Perturbed
    retention_rate: float           # Perturbed / Clean
    degradation_percent: float      # (1 - Retention) * 100
    sample_size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "perturbation_type": self.perturbation_type,
            "sample_size": self.sample_size,
            "clean_accuracy": round(self.clean_accuracy, 4),
            "perturbed_accuracy": round(self.perturbed_accuracy, 4),
            "absolute_drop": round(self.absolute_drop, 4),
            "retention_rate": round(self.retention_rate, 4),
            "degradation_percent": f"{self.degradation_percent:.1f}%",
        }


def evaluate_robustness_drop(
    clean_results: List[dict[str, Any]],
    perturbed_results: List[dict[str, Any]],
    metric_key: str = "equivalent_match",
) -> dict[str, RobustnessDegradationMetric]:
    """Computes comparative degradation metrics stratified by perturbation type."""
    # Build lookup by base ID
    clean_lookup = {
        (e.get("id") or e.get("query_id", "")).replace("_clean", ""): bool(e.get(metric_key, False))
        for e in clean_results
    }

    grouped_perturbed: dict[str, List[Tuple[bool, bool]]] = {}
    for p_item in perturbed_results:
        p_type = p_item.get("perturbation_type", "unknown")
        # Extract base ID
        p_id = str(p_item.get("id") or p_item.get("query_id", ""))
        base_id = re.sub(r"_ood_.*$", "", p_id)
        
        c_succ = clean_lookup.get(base_id, False)
        p_succ = bool(p_item.get(metric_key, False))

        grouped_perturbed.setdefault(p_type, []).append((c_succ, p_succ))

    reports: dict[str, RobustnessDegradationMetric] = {}
    for p_type, pairs in sorted(grouped_perturbed.items()):
        n = len(pairs)
        if n == 0:
            continue
        c_acc = sum(1 for c, p in pairs if c) / n
        p_acc = sum(1 for c, p in pairs if p) / n
        abs_drop = max(0.0, c_acc - p_acc)
        retention = (p_acc / c_acc) if c_acc > 0 else (1.0 if p_acc == 0 else 0.0)
        deg_pct = (1.0 - retention) * 100.0 if c_acc > 0 else 0.0

        reports[p_type] = RobustnessDegradationMetric(
            perturbation_type=p_type,
            clean_accuracy=c_acc,
            perturbed_accuracy=p_acc,
            absolute_drop=abs_drop,
            retention_rate=retention,
            degradation_percent=deg_pct,
            sample_size=n,
        )

    return reports


def format_robustness_markdown_table(reports: dict[str, RobustnessDegradationMetric]) -> str:
    lines = [
        "| Perturbation Category | N | Clean Acc | Perturbed Acc | Robustness Drop (ΔAcc) | Retention Rate |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]
    for p_type, m in reports.items():
        lines.append(
            f"| **{p_type.capitalize()}** | {m.sample_size} | {m.clean_accuracy*100:.1f}% | {m.perturbed_accuracy*100:.1f}% | **-{m.absolute_drop*100:.1f}%** | {m.retention_rate*100:.1f}% |"
        )
    return "\n".join(lines)
