"""Pure metric aggregation and the fixed six-pair superiority decision."""

from __future__ import annotations

import math
import statistics

ARMS = ("plain", "static", "cami")
TOKEN_KEYS = ("input", "cache_read", "cache_write", "output", "reasoning")


def number(value, *, integer=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        return None
    if integer and int(value) != value:
        return None
    return int(value) if integer else value


def token_fields(usage):
    tokens = usage.get("session_tokens") if isinstance(usage, dict) else None
    tokens = tokens if isinstance(tokens, dict) else {}
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    values = {
        "input": number(tokens.get("input"), integer=True),
        "cache_read": number(cache.get("read"), integer=True),
        "cache_write": number(cache.get("write"), integer=True),
        "output": number(tokens.get("output"), integer=True),
        "reasoning": number(tokens.get("reasoning"), integer=True),
    }
    return values


def metric(rows, key, complete_key):
    values = [row.get(key) for row in rows]
    known = [value for value in values if value is not None]
    complete = len(rows) == 4 and all(row.get(complete_key) for row in rows)
    return {
        "total": sum(known) if complete else None,
        "observed_subtotal": sum(known) if known else None,
        "complete": complete,
        "known_stages": len(known),
        "unknown_or_incomplete_trials": [row["id"] for row in rows if not row.get(complete_key)],
    }


def stats(values):
    known = [value for value in values if value is not None]
    return {
        "complete_blocks": len(known),
        "all_three_blocks": len(known) == 3,
        "median": statistics.median(known) if known else None,
        "min": min(known) if known else None,
        "max": max(known) if known else None,
    }


def summarize(rows):
    blocks = []
    for repetition in range(1, 4):
        for arm in ARMS:
            members = sorted(
                [r for r in rows if r["repetition"] == repetition and r["arm"] == arm],
                key=lambda r: r["stage"],
            )
            block = {
                "repetition": repetition,
                "arm": arm,
                "trials": [r["id"] for r in members],
                "all_four_operational_quality_pass": all(r["quality_eligible"] for r in members),
                "charged_wall": metric(members, "charged_wall_seconds", "wall_complete"),
                "token_work": metric(members, "token_work", "tokens_complete"),
                "tokens": {},
            }
            for key in TOKEN_KEYS:
                vals = [r["tokens"][key] for r in members]
                known = [v for v in vals if v is not None]
                block["tokens"][key] = {
                    "total": sum(known) if all(r["tokens_complete"] for r in members) else None,
                    "observed_subtotal": sum(known) if known else None,
                    "known_stages": len(known),
                }
            blocks.append(block)
    lookup = {(b["repetition"], b["arm"]): b for b in blocks}
    pairs = []
    for rep in range(1, 4):
        for comparator in ("plain", "static"):
            pair = {"repetition": rep, "comparator": comparator}
            for key in ("charged_wall", "token_work"):
                cami, other = (
                    lookup[rep, "cami"][key]["total"],
                    lookup[rep, comparator][key]["total"],
                )
                pair[key] = {
                    "cami": cami,
                    "comparator": other,
                    "delta_cami_minus_comparator": cami - other
                    if cami is not None and other is not None
                    else None,
                    "ratio_cami_over_comparator": cami / other
                    if cami is not None and other is not None and other > 0
                    else None,
                    "strictly_lower": cami < other
                    if cami is not None and other is not None
                    else None,
                }
            pairs.append(pair)
    all_quality = all(r["quality_eligible"] for r in rows)
    all_metrics = all(r["wall_complete"] and r["tokens_complete"] for r in rows)
    eligible = len(rows) == 36 and all_quality and all_metrics
    winners = [
        key
        for key in ("charged_wall", "token_work")
        if eligible and all(p[key]["strictly_lower"] is True for p in pairs)
    ]
    summaries = {
        arm: {
            key: stats([b[key]["total"] for b in blocks if b["arm"] == arm])
            for key in ("charged_wall", "token_work")
        }
        for arm in ARMS
    }
    paired_stats = {
        comparator: {
            key: {
                "delta": stats(
                    [
                        p[key]["delta_cami_minus_comparator"]
                        for p in pairs
                        if p["comparator"] == comparator
                    ]
                ),
                "ratio": stats(
                    [
                        p[key]["ratio_cami_over_comparator"]
                        for p in pairs
                        if p["comparator"] == comparator
                    ]
                ),
            }
            for key in ("charged_wall", "token_work")
        }
        for comparator in ("plain", "static")
    }
    return {
        "expected_trials": 36,
        "terminal_trials": sum(r["terminal_present"] for r in rows),
        "all_trials_operational_quality_pass": all_quality,
        "all_primary_metrics_complete": all_metrics,
        "primary_efficiency_eligible": eligible,
        "primary_superiority": "established_for_declared_sequence"
        if winners
        else "not_established",
        "winning_metrics_satisfying_all_six_pairs": winners,
        "cami_quality_rule_met": all(r["quality_eligible"] for r in rows if r["arm"] == "cami"),
        "incomplete_study": sum(r["terminal_present"] for r in rows) != 36 or not all_metrics,
        "all_trials_terminal": sum(r["terminal_present"] for r in rows) == 36,
        "study_status": "incomplete"
        if sum(r["terminal_present"] for r in rows) != 36
        else "complete_eligible"
        if eligible
        else "complete_with_failures_or_incomplete_metrics",
        "blocks": blocks,
        "paired_comparisons": pairs,
        "descriptive_block_statistics": summaries,
        "descriptive_paired_statistics": paired_stats,
        "failure_or_missing_trials": [r["id"] for r in rows if not r["quality_eligible"]],
        "unknown_measurement_trials": [
            r["id"] for r in rows if not r["wall_complete"] or not r["tokens_complete"]
        ],
    }
