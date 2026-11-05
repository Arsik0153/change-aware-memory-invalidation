"""Rebuild descriptive v5 figures from the closed, hash-bound aggregate only."""
import hashlib
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter, MaxNLocator

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
REPORT = ROOT / "runs/opencode-development-v5-final-analysis-20261105/report.json"
PROTOCOL = ROOT / "reports/opencode-study-design-v5-20261104/protocol.json"
STUDY = PROTOCOL.with_name("study.json")
ARMS = ("plain", "static", "cami")
LABELS = ("OpenCode", "+ Static memory", "+ CAMI")
COLORS = ("#3569a8", "#d58b21", "#19856d")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def verify(report, protocol):
    """Independent arithmetic/eligibility checks; do not import the evaluator."""
    assert sha(PROTOCOL) == report["protocol_sha256"]
    assert sha(STUDY) == report["study_sha256"]
    assert protocol["study_id"] == "opencode-cami-real-maintenance-development-v5-literal-compact"
    trials = report["trials"]
    assert len(trials) == 36
    assert len({t["id"] for t in trials}) == 36
    assert {(t["repetition"], t["arm"], t["stage"]) for t in trials} == {
        (r, a, s) for r in (1, 2, 3) for a in ARMS for s in (1, 2, 3, 4)
    }
    for t in trials:
        terminal = Path(report["run"]) / "trials" / t["id"] / "terminal.json"
        assert sha(terminal) == t["terminal_sha256"]
        assert t["terminal_present"]
        if t["tokens_complete"]:
            assert t["token_work"] == sum(t["tokens"][k] for k in ("input", "cache_write", "output", "reasoning"))
        if t["wall_complete"]:
            c = t["resource_components"]
            assert math.isclose(t["charged_wall_seconds"], sum(c[k] for k in (
                "construction_host_wall_seconds", "session_host_wall_seconds", "guard_and_orchestration_host_wall_seconds"
            )), abs_tol=1e-7)
    blocks = report["summary"]["blocks"]
    assert len(blocks) == 9
    for b in blocks:
        members = [t for t in trials if (t["arm"], t["repetition"]) == (b["arm"], b["repetition"])]
        assert sorted(b["trials"]) == sorted(t["id"] for t in members)
        for key, value, complete in (("token_work", "token_work", "tokens_complete"), ("charged_wall", "charged_wall_seconds", "wall_complete")):
            known = [t[value] for t in members if t[complete]]
            assert b[key]["complete"] == (len(known) == 4)
            expected = sum(known) if len(known) == 4 else None
            assert (expected is None and b[key]["total"] is None) or math.isclose(b[key]["total"], expected, abs_tol=1e-7)
        for k in ("input", "output", "reasoning", "cache_read", "cache_write"):
            assert b["tokens"][k]["total"] == sum(t["tokens"][k] for t in members)
    quality = sum(t["quality"] == "pass" for t in trials)
    operational = sum(t["operational_status"] == "passed" for t in trials)
    assert quality == 36 and operational == 35
    failed = [t for t in trials if t["operational_status"] != "passed"]
    assert [t["id"] for t in failed] == ["r3-static-s1"]
    assert failed[0]["runtime_passed_controller_admission_failed"]
    eligible = all(t["quality"] == "pass" and t["operational_status"] == "passed" and t["tokens_complete"] and t["wall_complete"] for t in trials)
    assert eligible == report["summary"]["primary_efficiency_eligible"]
    assert not eligible
    assert report["summary"]["primary_superiority"] == "not_established"
    assert not report["timing_caveats"]["affected_trial_ids"]
    wins = {}
    for metric in ("token_work", "charged_wall"):
        wins[metric] = {}
        for comparator in ("plain", "static"):
            pairs = [(next(b[metric]["total"] for b in blocks if b["arm"] == "cami" and b["repetition"] == r), next(b[metric]["total"] for b in blocks if b["arm"] == comparator and b["repetition"] == r)) for r in (1, 2, 3)]
            wins[metric][comparator] = sum(c < other for c, other in pairs)
    assert wins == {"token_work": {"plain": 3, "static": 2}, "charged_wall": {"plain": 0, "static": 1}}
    return {"quality_pass": quality, "operational_pass": operational, "terminal_trials": 36,
            "terminal_hashes_independently_checked": 36, "full_terminal_payload_inventory_rehashed": False,
            "aggregate_reported_artifact_hashes_verified": report["integrity"]["terminal_artifact_hashes_verified"],
            "independent_checks": ["36 terminal-file hashes", "trial token arithmetic", "charged wall component arithmetic", "nine block sums including failed paid trial", "strict quality/operational eligibility", "paired directional counts"],
            "descriptive_lower_cami_blocks_out_of_three": wins}


def main():
    report = json.loads(REPORT.read_text())
    protocol = json.loads(PROTOCOL.read_text())
    checks = verify(report, protocol)
    rows = [{"repetition": b["repetition"], "arm": b["arm"],
             "token_work": b["token_work"]["total"], "charged_wall": b["charged_wall"]["total"],
             "tokens": {k: v["total"] for k, v in b["tokens"].items()},
             "operational_quality_pass": b["all_four_operational_quality_pass"], "trials": b["trials"]}
            for b in report["summary"]["blocks"]]
    data = {"schema_version": 1, "study_id": protocol["study_id"],
            "input_sha256": {str(p.relative_to(ROOT)): sha(p) for p in (REPORT, PROTOCOL, STUDY)},
            "blocks": rows, "verification": checks,
            "primary_efficiency_eligible": False, "primary_superiority": "not_established",
            "token_definition": "input + cache_write + output + reasoning; cache_read is separate; normalized resource proxy, not billing",
            "wall_definition": protocol["cost_boundary"], "timing_caveat_trial_ids": [],
            "failed_paid_trial": {k: next(t for t in report["trials"] if t["id"] == "r3-static-s1")[k] for k in ("id", "operational_status", "quality", "runtime_manifest_status", "runtime_passed_controller_admission_failed", "charged_wall_seconds", "token_work", "tokens")},
            "scope": "Development v5, literal compact memory; three dependent four-stage sequences per arm on two fixed Click task instances. No population, causal, billing or final-heldout claim.",
            "missing_data_policy": "Unavailable measurements remain null and are labeled unavailable; never replaced by zero."}
    write_json("chart-data.json", data)
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.hashsalt": "opencode-development-v5"})
    fig, axes = plt.subplots(1, 2, figsize=(12.6, 5.5))
    for ax, metric, title, ylabel in zip(axes, ("token_work", "charged_wall"),
        ("Normalized token work · descriptive", "Charged sequence wall · descriptive"), ("Normalized tokens (cache reads separate)", "Seconds, including memory construction"), strict=True):
        known = [r[metric] for r in rows if r[metric] is not None]
        ax.set_ylim(0, max(known, default=1) * 1.22)
        for i, arm in enumerate(ARMS):
            for rep in (1, 2, 3):
                row = next(r for r in rows if r["arm"] == arm and r["repetition"] == rep)
                x = rep - 1 + (i - 1) * .25
                value = row[metric]
                if value is None:
                    ax.text(x, ax.get_ylim()[1] * .03, "Unavailable", rotation=90, ha="center", fontsize=8)
                    continue
                ax.bar(x, value, .23, color=COLORS[i], hatch="///" if not row["operational_quality_pass"] else None, edgecolor="#334155" if not row["operational_quality_pass"] else COLORS[i], linewidth=.65)
                label = f"{value / 1000:.1f}k" if metric == "token_work" else f"{value:.1f}"
                ax.annotate(label + ("*" if not row["operational_quality_pass"] else ""), (x, value), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=8)
        ax.set_xticks(range(3), ("Repeat 1", "Repeat 2", "Repeat 3"))
        ax.set_title(title, fontsize=11, pad=12)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.yaxis.set_major_locator(MaxNLocator(5))
        if metric == "token_work":
            ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x / 1000:g}k"))
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_axisbelow(True)
        ax.grid(axis="y", alpha=.18)
    fig.suptitle("Development v5 · quality 36/36; operational 35/36", fontsize=14, y=.98)
    fig.legend(handles=[Patch(facecolor=color, label=label) for color, label in zip(COLORS, LABELS, strict=True)], loc="upper center", bbox_to_anchor=(.5, .915), ncol=3, frameon=False, fontsize=9)
    fig.text(.5, .092, "Primary efficiency comparison ineligible; superiority not established. * Repeat 3 static includes the failed paid trial.\nAll nine blocks retain all four stages. Normalized counters are not bills; no confidence intervals from three dependent sequences.", ha="center", va="center", fontsize=8.5)
    fig.text(.5, .025, "Literal compact memory · two fixed historical Click task instances · development scope only · no known auxiliary overlap recorded", ha="center", fontsize=8, color="#475569")
    fig.tight_layout(rect=(0, .15, 1, .87))
    fig.savefig(OUT / "comparison.png", dpi=180)
    fig.savefig(OUT / "comparison.svg", metadata={"Date": None})
    plt.close(fig)
    html_template = (OUT / "template.html").read_text()
    safe = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    (OUT / "comparison.html").write_text(html_template.replace("__CHART_DATA__", safe))
    findings = {"verdict": "Primary superiority not established; both plotted metrics are descriptive.",
                "verification": checks, "failed_trial": data["failed_paid_trial"],
                "interpretation": ["CAMI has lower token work than plain in all three blocks and than static in two of three; no metric wins all six comparisons.", "CAMI charged wall is higher than plain in all three blocks and higher than static in two of three.", "The operational failure independently disqualifies the primary efficiency claim; passing task quality does not override it.", "All cost counters for the failed paid trial are included. No incomplete observations are converted to zero.", "No v3 wall-overlap caveat is transferred to v5; the aggregate records no affected trials. This is not independent proof of an idle host.", "Only two task instances and three dependent sequences per arm; no general causal or heldout conclusion."],
                "scope": "Read-only arithmetic/terminal-hash review, not a new full evidence audit or experimental rerun."}
    write_json("findings.json", findings)
    outputs = ("chart-data.json", "comparison.png", "comparison.svg", "comparison.html", "findings.json")
    manifest = {"schema_version": 1, "status": "complete", "input_sha256": data["input_sha256"],
                "build_source_sha256": {name: sha(OUT / name) for name in ("build.py", "template.html")},
                "artifact_sha256": {name: sha(OUT / name) for name in outputs},
                "matplotlib_version": matplotlib.__version__,
                "rebuild": ".venv/bin/python runs/opencode-development-v5-figures-20261105/build.py",
                "measurement_activity": "No model, Docker, experiment, task grading or source changes; publication visualization only."}
    write_json("manifest.json", manifest)
    print(json.dumps({"checks": checks, "artifact_sha256": manifest["artifact_sha256"]}))


if __name__ == "__main__":
    main()
