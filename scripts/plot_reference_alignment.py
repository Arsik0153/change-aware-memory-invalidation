"""Render paired, authored transition-challenge counts from sealed summaries."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def run(before: Path, after: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=False)
    inputs = [json.loads(path.read_bytes()) for path in (before, after)]
    assert all(x['claim_transitions'] == 42 and x['input_pairs'] == 21 for x in inputs)
    groups = ['symbol_anchor', 'file_anchor', 'all_validate']
    labels = ['Symbol anchor', 'File anchor', 'Validate all']
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    metrics = [('available_when_reference_not_supported', 'Available without reference support'),
               ('selected', 'Selected validations / 42 transitions')]
    for axis, (metric, title) in zip(axes, metrics, strict=True):
        for offset, data, label, color in zip((-.18, .18), inputs, ('Before fix', 'After fix'),
                                            ('#b9583c', '#286c8e'), strict=True):
            values = [data['measurement_2_research_reference_pipeline']['by_selector_variant'][g][metric]
                      for g in groups]
            bars = axis.bar(np.arange(3)+offset, values, width=.34, color=color, label=label)
            axis.bar_label(bars, padding=3)
        axis.set_xticks(np.arange(3), labels)
        axis.set_title(title, fontsize=10)
        axis.set_ylim(0, 5 if metric.startswith('available') else 48)
        axis.set_yticks(range(0, 6) if metric.startswith('available') else range(0, 49, 8))
        axis.spines[['top', 'right']].set_visible(False)
        axis.grid(axis='y', alpha=.2)
        axis.set_axisbelow(True)
    axes[0].legend(frameon=False)
    fig.suptitle('Class-global ambiguity: fixed production, unchanged reference v2', fontsize=12)
    fig.supxlabel('21 authored mutations × 2 predicates. Unsupported cases are uncertain, not proven false.', fontsize=9)
    fig.savefig(out/'reference-alignment.png', dpi=180)
    fig.savefig(out/'reference-alignment.svg')
    plt.close(fig)

    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    (out/'manifest.json').write_text(json.dumps({'input_sha256': {str(p): sha(p) for p in (before, after)},
        'script_sha256': sha(Path(__file__)), 'artifact_sha256': {p.name: sha(p) for p in out.iterdir() if p.is_file()}}, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('before', 'after', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    run(args.before, args.after, args.out)
