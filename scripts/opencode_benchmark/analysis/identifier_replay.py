"""Post-hoc fixed-query rank replay; retrieval coverage only, no agent utility claim."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from aggregate_study import read, sha, verify_terminal, write

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "integrations/opencode"))
from memory_backend import IDENTIFIER_RANKING, identifier_mentions, mention_priority, rank  # noqa: E402


def replay(root):
    catalog_path = root / "namespaces/r1-cami_compact/memory/prepared/catalog.json"
    last, _, _ = verify_terminal(root / "trials/r1-cami_compact-s4")
    if sha(catalog_path) != last["memory_files_after"]["prepared/catalog.json"]:
        raise ValueError("catalog differs from terminal memory inventory")
    catalog = read(catalog_path)
    calls = []
    for directory in sorted((root / "trials").iterdir()):
        terminal, terminal_sha, _ = verify_terminal(directory)
        trace = directory / "session/evidence/memory-backend-trace.jsonl"
        if not trace.exists():
            continue
        for event in (json.loads(line) for line in trace.read_text().splitlines()):
            if event.get("event") != "memory_lookup":
                continue
            if event.get("error") is not None:
                raise ValueError("failed lookup requires a separate incomplete analysis")
            body = json.loads(event["response_audit"]["full_result"]["content"][0]["text"])
            query, limit = body["query"], event["requested_limit"]
            old, matched = rank(catalog, query, limit)
            observed = {r["id"] for r in body["entries"] + body["withheld"]}
            if {r["id"] for r in old} != observed or matched != body["matched_records"]:
                raise ValueError("legacy replay differs from frozen observed selection")
            for group in ("entries", "withheld"):
                identities = {r["id"] for r in body[group]}
                if [r["id"] for r in old if r["id"] in identities] != [r["id"] for r in body[group]]:
                    raise ValueError("legacy replay order differs from frozen observations")
            candidate, _ = rank(catalog, query, limit, ranking_policy=IDENTIFIER_RANKING)
            mentions = identifier_mentions(query)
            explicit = {r["id"]: r["payload"]["subject"]["qualname"] for r in catalog["records"]
                        if mention_priority(r["payload"]["subject"], mentions) < 2}
            old_ids, new_ids = {r["id"] for r in old}, {r["id"] for r in candidate}
            calls.append({"trial_id": terminal["trial"]["id"], "terminal_sha256": terminal_sha,
                "query": query, "limit": limit, "explicit_symbols": explicit,
                "legacy_selected": [r["id"] for r in old],
                "candidate_selected": [r["id"] for r in candidate],
                "legacy_omitted": {key: value for key, value in explicit.items() if key not in old_ids},
                "candidate_omitted": {key: value for key, value in explicit.items() if key not in new_ids}})
    return {"schema_version": 1, "catalog_file_sha256": sha(catalog_path),
        "adapter_source_sha256": sha(ROOT / "integrations/opencode/memory_backend.py"),
        "scope": "Post-hoc replay of every recorded query against the same origin catalog. Both policies rank before availability, with identical requested limits and16384-byte origin budget. Explicit-reference coverage is defined by the declared identifier rule, not task correctness. No new model calls, timings or causal/efficiency claims.",
        "summary": {"queries": len(calls), "explicit_symbol_observations": sum(len(c["explicit_symbols"]) for c in calls),
            "legacy_queries_with_omissions": sum(bool(c["legacy_omitted"]) for c in calls),
            "candidate_queries_with_omissions": sum(bool(c["candidate_omitted"]) for c in calls),
            "legacy_omitted_observations": sum(len(c["legacy_omitted"]) for c in calls),
            "candidate_omitted_observations": sum(len(c["candidate_omitted"]) for c in calls),
            "legacy_matches_frozen_selections": True, "model_calls": 0},
        "calls": calls}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    write(args.out, replay(args.run.resolve()))


if __name__ == "__main__":
    main()
