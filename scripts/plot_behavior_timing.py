"""Plot all five observed timings; ranges are descriptive, not confidence intervals."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from cami.artifacts import file_hash, read_json, reserve, write_json

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / 'reports/research-20261104/behavior-timing-v1/summary.json'


def plot(out: Path) -> None:
    summary = read_json(SUMMARY)
    reserve(out)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharex=True, sharey=True)
    variants = ['all_validate', 'intact', 'known_missing', 'hidden_missing']
    labels = ['All validate', 'Intact provenance', 'Known missing', 'Hidden missing']
    rows = []
    for ax, history, title in zip(axes, ['exposure', 'recovery'],
                                 ['A. Exposure history (6 transitions)', 'B. Recovery history (4 transitions)']):
        for i, variant in enumerate(variants):
            group = summary['groups'][history + '/' + variant]
            times = group['cli_wall_seconds']
            unsafe = any(group['availability_mismatches'])
            color = '#b34e39' if unsafe else '#24766b' if variant == 'intact' else '#557b9e'
            ax.hlines(i, times['min'], times['max'], color=color, linewidth=2)
            ax.scatter(times['values'], [i + j*.055 - .11 for j in range(5)],
                       color=color, alpha=.45, s=24)
            ax.scatter([times['median']], [i], marker='D', color=color, s=48, zorder=3)
            ax.text(times['max']+.18, i, f"{times['median']:.2f}s", va='center', fontsize=10)
            if unsafe:
                ax.text(7, i-.24, 'False claim available: 2/6 transitions',
                        color=color, fontsize=9, va='center')
            rows.append({'history': history, 'variant': variant, 'repetitions': group['repetitions'],
                'median_cli_seconds': times['median'], 'min_cli_seconds': times['min'],
                'max_cli_seconds': times['max'], 'probe_executions_per_run': group['executions'][0],
                'availability_mismatches_per_history': group['availability_mismatches'][0]})
        ax.set_title(title, loc='left', fontsize=12)
        ax.set_xlabel('Complete CLI run, seconds (includes parent preflight)')
        ax.set_xlim(0, 13)
        ax.set_yticks(range(4), labels)
        ax.spines[['top', 'right']].set_visible(False)
        ax.set_axisbelow(True)
        ax.xaxis.grid(True, alpha=.2)
    axes[0].invert_yaxis()
    fig.text(.02, .07, 'Diamond: median; line: min–max; dots: all five runs. These are repeat timings of two authored histories.', fontsize=9)
    fig.text(.02, .025, 'Red marks lower time with worse availability. Shared host; pinned Docker image; verdict cache disabled.', fontsize=9)
    fig.tight_layout(rect=(0, .13, 1, 1))
    for suffix in ('png', 'svg'):
        fig.savefig(out / ('behavior-timing.' + suffix), dpi=180)
    plt.close(fig)
    with (out / 'timings.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(out / 'manifest.json', {'input_sha256': file_hash(SUMMARY),
        'script_sha256': file_hash(Path(__file__)),
        'artifacts': {p.name: file_hash(p) for p in out.iterdir() if p.is_file()}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    plot(parser.parse_args().out)
