#!/usr/bin/env python3
"""Reproduce the frozen Packaging research figure using saved result JSON only."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
import os
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle

EXPECTED_MANIFEST = "93f8ba40cc44320e28d82aaaed965a518e291e2fd37d85a25a99006c47baf508"
VARIANTS = ("symbol_anchor", "file_anchor", "known_incomplete", "all_validate")
LABELS = ("Symbol anchor", "File anchor", "Known incomplete", "Validate all")
INK, MUTED, TEAL, RED = "#172033", "#526174", "#087e8b", "#bd483c"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def collect(run, root):
    manifest_path = run / "manifest.json"
    require(sha(manifest_path) == EXPECTED_MANIFEST, "requires exact completed Packaging v2 manifest")
    manifest = json.loads(manifest_path.read_text())
    require(manifest["status"] == "complete" and manifest["source_before"] == manifest["source_after"],
            "incomplete run or implementation changed")
    protocol = manifest["protocol"]
    require(protocol["protocol_id"] == "packaging-derived-structural-first-parent-development-v2"
            and protocol["primary_horizon"] == 23 and protocol["prefix_horizon"] == 12
            and not manifest["evaluation_eligible"], "unexpected study scope")
    inputs = {"manifest.json": EXPECTED_MANIFEST}

    def read(name, jsonl=False):
        path = run / name
        digest = sha(path)
        require(digest == manifest["artifact_hashes"][name], f"artifact hash mismatch: {name}")
        inputs[name] = digest
        return ([json.loads(line) for line in path.read_text().splitlines() if line.strip()]
                if jsonl else json.loads(path.read_text()))

    report = read("report.json")
    rows, parents, costs = (read(name, True) for name in
                            ("observations.jsonl", "parents.jsonl", "costs.jsonl"))
    topology = read("topology.json")
    claims = {row["claim"]["claim_id"]: row["claim"] for row in parents}
    require(len(parents) == len(claims) == 24 and len(rows) == 2208, "claim/observation count changed")
    require(all(row["eligible"] for row in parents + rows), "excluded parent present")
    expected_keys = {(g["group_id"], c["claim_id"], v, step)
                     for g in protocol["groups"] for c in claims.values()
                     if c["origin_commit"] == g["parent_commit"]
                     for v in VARIANTS for step in range(1, 24)}
    actual_keys = {(r["group_id"], r["claim_id"], r["variant"], r["trajectory"]["step"]) for r in rows}
    require(len(actual_keys) == len(rows) and actual_keys == expected_keys, "row inventory mismatch")
    for row in rows:
        require(row["trajectory"] == topology[row["group_id"]][row["commit"]], "saved topology mismatch")
        require(not row["trajectory"]["is_merge"], "unexpected merge observation")
    require(sum(len(g) for g in topology.values()) == 69, "transition count changed")
    # Reference is computed once per child claim, then repeated across policy rows.
    references = {}
    for row in rows:
        key = (row["group_id"], row["claim_id"], row["commit"])
        require(key not in references or references[key] == row["reference"], "variant reference disagreement")
        references[key] = row["reference"]
    series, summaries = {}, {}
    for name, limit in (("full23", 23), ("prefix12", 12)):
        series[name], summaries[name] = [], {}
        for variant in VARIANTS:
            selected = [r for r in rows if r["variant"] == variant and r["trajectory"]["step"] <= limit]
            counts = Counter(r["reference"]["verdict"] for r in selected)
            actual = sum(r["validation"] is not None for r in selected)
            false_available = sum(r["state"]["available"] and r["reference"]["verdict"] == "contradicted"
                                  for r in selected)
            unknown = sum(r["full_production_validation"]["verdict"] == "uncertain" for r in selected)
            summary = {"candidate_observations": len(selected), "actual_validation_calls": actual,
                       "reference_supported": counts["supported"], "reference_contradicted": counts["contradicted"],
                       "reference_unknown": counts["uncertain"], "false_available": false_available,
                       "available": sum(r["state"]["available"] for r in selected),
                       "full_production_unknown": unknown}
            require(all(report[name]["variants"][variant][k] == v for k, v in summary.items()),
                    f"report/row accounting mismatch: {name}/{variant}")
            require(not false_available and not unknown and not counts["uncertain"], "unexpected uncertainty/error")
            summaries[name][variant] = summary
            series[name].append(actual)
    require(series == {"full23": [28, 71, 552, 552], "prefix12": [13, 38, 288, 288]}, "frozen calls changed")
    symbol_rows = [r for r in rows if r["variant"] == "symbol_anchor"]
    affected = sorted({r["claim_id"] for r in symbol_rows if r["reference"]["verdict"] == "contradicted"})
    timelines, episodes = [], []
    for claim_id in affected:
        selected = sorted((r for r in symbol_rows if r["claim_id"] == claim_id), key=lambda r: r["trajectory"]["step"])
        require([r["trajectory"]["step"] for r in selected] == list(range(1, 24)), "timeline gaps")
        verdicts = [r["reference"]["verdict"] for r in selected]
        start = None
        for step, verdict in enumerate(verdicts + ["end"], 1):
            if verdict == "contradicted" and start is None:
                start = step
            elif verdict != "contradicted" and start is not None:
                episodes.append({"claim_id": claim_id, "first_step": start, "last_step": step - 1,
                                 "observations": step - start})
                start = None
        timelines.append({"claim_id": claim_id, "subject": claims[claim_id]["subject"],
                          "parent_commit": claims[claim_id]["origin_commit"], "verdicts": verdicts,
                          "commits": [r["commit"] for r in selected]})
    require(len(affected) == len(episodes) == 2 and [e["observations"] for e in episodes] == [21, 3],
            "contradiction incidence changed")
    incidence = report["full23"]["variants"]["symbol_anchor"]["incidence"]
    require(incidence["runs"] == episodes and incidence["unique_contradicted_claims"] == 2
            and incidence["repeated_contradicted_observations"] == 22, "incidence report mismatch")
    parent_calls = sum(c.get("actual_calls", 0) for c in costs if c["phase"] == "parent_production_validation")
    child_calls = sum(c.get("actual_calls", 0) for c in costs if c["phase"] == "child_production_validation")
    parent_refs = sum(c.get("reference_calls", 0) for c in costs if c["phase"] == "parent_reference")
    child_refs = sum(c.get("reference_calls", 0) for c in costs if c["phase"] == "child_reference")
    indexes = sum(c.get("index_builds", 0) for c in costs)
    require((parent_calls, child_calls, parent_refs, child_refs, indexes) == (96, 1203, 24, 552, 72),
            "cost ledger changed")
    require(report["separate_work"] == {"child_reference_calls": child_refs,
            "parent_reference_calls": parent_refs, "shared_index_builds": indexes}, "separate work mismatch")
    earlier_packet_calls = 0
    sealed_inputs = {}
    for group in protocol["review_groups"]:
        name = group["reference_answers_path"]
        path = (root / name).resolve()
        require(path.is_relative_to(root), "reference wrapper outside root")
        digest = sha(path)
        require(digest == manifest["seal"]["files"][name], "earlier reference wrapper hash mismatch")
        sealed_inputs[name] = digest
        answers = json.loads(path.read_text())
        require(answers["packet_sha256"] == group["packet_sha256"], "earlier packet identity mismatch")
        earlier_packet_calls += len(answers["decisions"])
    require(earlier_packet_calls == 36, "earlier reference count changed")
    return {"source_run": os.path.relpath(run, root), "source_commit": manifest["source_before"]["git_head"],
            "input_hashes": inputs, "earlier_sealed_result_hashes": sealed_inputs,
            "variants": list(VARIANTS), "series": series, "summaries": summaries,
            "claims": 24, "parents": 3, "transitions": 69, "merge_transitions": 0,
            "timelines": timelines, "episodes": episodes, "unique_contradicted_claims": len(affected),
            "contradicted_rows_per_variant": 24, "repeated_contradicted_rows_per_variant": 22,
            "parent_actual_validations": parent_calls, "child_actual_validations": child_calls,
            "parent_reference_calls": parent_refs, "child_reference_calls": child_refs,
            "earlier_packet_reference_calls": earlier_packet_calls, "shared_indexes": indexes,
            "scope": "New-derived Packaging development; AI reviewed, not human reviewed; metadata-informed horizon23.",
            "limits": ["552 observations per variant are dependent repeats, not independent samples.",
                       "Two observed contradiction runs in two claims; no confidence interval or general detection claim.",
                       "Prefix12 is nested in full23; no new independent experiment.",
                       "No merge observations; no merge-performance inference.",
                       "Actual validator calls are not elapsed time or speedup; reference shares CPython AST primitives.",
                       "This script checks saved-artifact integrity/accounting, not independent replay correctness."]}


def render(data, output):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
                         "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": INK,
                         "svg.fonttype": "none", "svg.hashsalt": "packaging-replay-v2"})
    fig = plt.figure(figsize=(15, 7.1), facecolor="white")
    left = fig.add_axes((.16, .30, .32, .40))
    right = fig.add_axes((.58, .30, .37, .40))
    for i, (full, prefix) in enumerate(zip(data["series"]["full23"], data["series"]["prefix12"], strict=True)):
        left.barh(i - .15, full, height=.27, color=TEAL)
        left.barh(i + .15, prefix, height=.27, color="#a8cbd0")
        left.text(full + 9, i - .15, str(full), va="center", fontsize=11, weight="bold")
        left.text(prefix + 9, i + .15, str(prefix), va="center", fontsize=10, color=MUTED)
    left.set_yticks(range(4), LABELS)
    left.invert_yaxis()
    left.set_xlim(0, 655)
    left.set_xticks([0, 150, 300, 450, 600])
    left.set_xlabel("Actual child validator calls", labelpad=10)
    left.grid(axis="x", color="#e3e8ed", linewidth=.7)
    left.set_axisbelow(True)
    left.tick_params(axis="y", length=0)
    left.set_title("A   Calls by policy variant", loc="left", fontsize=13, weight="bold", pad=40)
    left.legend(handles=[Patch(color=TEAL, label="Full23 · 552 rows/variant"),
                         Patch(color="#a8cbd0", label="Prefix12 · 288 rows/variant")],
                loc="lower left", bbox_to_anchor=(-.01, 1.01), frameon=False, fontsize=9)
    for spine in left.spines.values():
        spine.set_visible(False)
    for row, timeline in enumerate(data["timelines"]):
        for step, verdict in enumerate(timeline["verdicts"], 1):
            right.add_patch(Rectangle((step - .46, row - .19), .92, .38,
                                      facecolor=RED if verdict == "contradicted" else "#dce9eb",
                                      edgecolor="white", linewidth=.5))
        right.text(.6, row - .36,
                   f"{timeline['subject']['qualname']}  ·  parent {timeline['parent_commit'][:7]}", fontsize=9)
        episode = data["episodes"][row]
        right.text((episode["first_step"] + episode["last_step"]) / 2, row,
                   f"{episode['observations']} rows", ha="center", va="center", color="white", fontsize=8)
    right.axvline(12.5, color=MUTED, linestyle=(0, (3, 3)), linewidth=1)
    right.text(12.5, 1.60, "prefix ends", ha="center", color=MUTED, fontsize=8)
    right.set_xlim(.4, 23.6)
    right.set_ylim(1.85, -.65)
    right.set_yticks([])
    right.set_xticks([1, 3, 6, 9, 12, 15, 18, 21, 23])
    right.set_xlabel("First-parent step within each claim's own group", labelpad=10)
    right.set_title("B   Two exact-signature claim timelines", loc="left", fontsize=13, weight="bold", pad=40)
    right.legend(handles=[Patch(color="#dce9eb", label="Reference supported"),
                          Patch(color=RED, label="Reference contradicted")],
                 loc="lower left", bbox_to_anchor=(-.01, 1.01), frameon=False, fontsize=9)
    for spine in right.spines.values():
        spine.set_visible(False)
    fig.text(.06, .94, "Packaging: validator calls and contradiction trajectories", fontsize=20, weight="bold")
    fig.text(.06, .885, "New-derived development claims · 24 claims · 3 parents · 69 first-parent transitions", color=MUTED, fontsize=12)
    fig.text(.06, .84, "AI reviewed, not human reviewed · metadata-informed horizon: 23 steps per parent · no merge observations", color=MUTED)
    fig.text(.06, .19, "Full23: 528 supported + 24 contradicted rows per variant; zero unknown or false-available rows.", fontsize=11)
    fig.text(.06, .145, "24 contradicted rows = 2 claims, 2 observed runs (21 + 3 steps). No confidence interval or general detection claim.", color=MUTED)
    fig.text(.06, .10, "Prefix12 is nested: 278 supported + 10 contradicted rows, one observed run. Repeated rows are dependent.", color=MUTED)
    fig.text(.06, .045, "Separate work: 96 parent validations · 576 replay reference calls + 36 earlier packet calls · 72 shared indexes. No speedup measured.", fontsize=9, color=MUTED)
    fig.savefig(output / "packaging_replay.png", dpi=180, facecolor="white", metadata={"Software": "plot_packaging_replay.py"})
    fig.savefig(output / "packaging_replay.svg", facecolor="none", transparent=True, metadata={"Date": None, "Creator": "plot_packaging_replay.py"})
    plt.close(fig)
    svg = (output / "packaging_replay.svg").read_text()
    svg = svg[svg.index("<svg "):]
    for old, new in (("#172033", "var(--foreground, #172033)"),
                     ("#526174", "var(--muted-foreground, #526174)"),
                     ("#087e8b", "var(--chart-1, #087e8b)"),
                     ("#bd483c", "var(--destructive, #bd483c)"),
                     ("#a8cbd0", "var(--chart-2, #a8cbd0)"),
                     ("#dce9eb", "var(--secondary, #dce9eb)"),
                     ("#e3e8ed", "var(--border, #e3e8ed)"),
                     ("#ffffff", "var(--destructive-foreground, #ffffff)")):
        svg = svg.replace(old, new)
    table = "".join(f"<tr><th scope='row'>{html.escape(label)}</th><td>{data['series']['full23'][i]} / 552</td>"
                    f"<td>{data['series']['prefix12'][i]} / 288</td></tr>" for i, label in enumerate(LABELS))
    limits = "".join(f"<li>{html.escape(limit)}</li>" for limit in data["limits"])
    page = f'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Packaging development replay · calls and trajectories</title>
<style>
:root{{--text:var(--foreground,#172033);--muted-text:var(--muted-foreground,#526174);--rule:var(--border,#dce3e9);--link:var(--primary,#087e8b)}}
*{{box-sizing:border-box}}html,body{{margin:0;padding:0;background:transparent;color:var(--text);font:16px/1.55 var(--font-sans,system-ui),sans-serif}}
main{{margin:0;padding:0;width:100%}}svg{{display:block;width:100%;height:360px}}.details{{padding:0}}@media(max-width:480px){{svg{{height:240px}}}}
h1{{font-size:1.3rem}}h2{{font-size:1.1rem;margin-top:1.7rem}}a{{color:var(--link)}}
table{{border-collapse:collapse;width:100%;max-width:780px}}th,td{{border-bottom:1px solid var(--rule);padding:.55rem;text-align:left}}
small,.muted{{color:var(--muted-text)}}code{{overflow-wrap:anywhere}}li{{margin:.4rem 0}}
</style><main aria-label="Packaging research figure">{svg}<div class="details">
<h1>Saved development replay, not an independent-sample benchmark</h1>
<table><caption>Actual child validator calls / candidate observations</caption><thead><tr><th>Variant</th><th>Full23</th><th>Nested prefix12</th></tr></thead><tbody>{table}</tbody></table>
<p>The two affected claims assert signatures of <code>_format_marker</code> and <code>_evaluate_markers</code>.
Their own parent trajectories contain 21 and 3 consecutive contradicted steps. These are exact syntactic signature changes;
a behavioral API break has not been established. All four variants withhold the contradicted claims;
no false-available or unknown rows were recorded. Other claims remain supported. The two timelines use different parent groups,
so their step numbers are relative positions, not shared calendar dates.</p>
<h2>Work outside the child-call bars</h2><p>96 parent production validations, 24 parent + 552 child reference calls (576 replay calls),
36 earlier packet reference calls, and 72 shared indexes. Actual calls are counts, not elapsed time or a speedup estimate.</p>
<h2>Scope and limits</h2><ul>{limits}</ul>
<p>New derived PyPA Packaging development claims; parents were supported by reference v2 and two fresh AI reviews each.
AI review is not human review. The original 24-step plan failed metadata-only before source access; a separately frozen,
metadata-informed amendment set 23 steps on the same 72-position frame. No main-cohort admission or held-out evaluation is claimed.</p>
<small>Run source commit <code>{data['source_commit']}</code>. Saved manifest SHA256 <code>{EXPECTED_MANIFEST}</code>.
<a href="plot-data.json">Derived data and input hashes</a> · <a href="manifest.json">Figure manifest</a> ·
<a href="packaging_replay.png">PNG</a> · <a href="packaging_replay.svg">SVG</a>.
No external assets or network requests. Figure accounting is not an independent correctness audit.</small>
</div></main></html>'''
    (output / "index.html").write_text(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="workspace root for sealed earlier result artifacts")
    args = parser.parse_args()
    data = collect(args.run.resolve(), args.root.resolve())
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "plot-data.json", data)
    render(data, output)
    dump(output / "manifest.json", {"status": "complete", "helper_sha256": sha(Path(__file__)),
         "python": sys.version, "matplotlib": matplotlib.__version__, "input_hashes": data["input_hashes"],
         "earlier_sealed_result_hashes": data["earlier_sealed_result_hashes"],
         "artifact_hashes": {path.name: sha(path) for path in sorted(output.iterdir()) if path.is_file()},
         "scope": data["scope"], "verification_scope": "Saved JSON hash/accounting checks only; no Git or project source access."})


if __name__ == "__main__":
    main()
