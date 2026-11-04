"""Plot dated binding-gate feasibility and the bounded carry check from saved results."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from cami.artifacts import file_hash, read_json, reserve, write_json

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'reports/research-20261104'


def plot(out: Path) -> None:
    gate_path = BASE / 'binding-gate-v1/summary.json'
    carry_path = BASE / 'structural-carry-v1/summary.json'
    gate, carry = read_json(gate_path), read_json(carry_path)
    reserve(out)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4), gridspec_kw={'width_ratios': [1.1, 1]})
    repositories = sorted(gate['by_repository'])
    passed = [gate['by_repository'][r].get('passes_binding_gate_only', 0) for r in repositories]
    rejected = [sum(gate['by_repository'][r].values()) - n for r, n in zip(repositories, passed)]
    axes[0].barh(repositories, rejected, color='#b9c2cc', label='Gate rejected')
    axes[0].barh(repositories, passed, left=rejected, color='#24766b', label='Gate passed only')
    for i, (p, r) in enumerate(zip(passed, rejected)):
        axes[0].text(p+r+2, i, f'{p}/{p+r} passed', va='center', fontsize=10)
    axes[0].set_xlim(0, max(p+r for p,r in zip(passed,rejected))*1.38)
    axes[0].set_xlabel('Prepared structural parent candidates (504 total)')
    axes[0].set_title('A. Real parent modules: binding gate', loc='left', fontsize=12)
    counts = [carry['selected'], carry['carried']]
    axes[1].barh(['Selected', 'Carried'], counts, color=['#557b9e', '#24766b'])
    for i, n in enumerate(counts):
        axes[1].text(n+2, i, str(n), va='center')
    axes[1].set_xlim(0, max(counts)*1.2)
    axes[1].set_xlabel('Authored cases (168 total)')
    axes[1].set_title('B. Synthetic carry versus fresh validator', loc='left', fontsize=12)
    axes[1].text(.43, .15, 'All 32 carried cases: supported\nNegative control: detected',
                 transform=axes[1].transAxes, fontsize=9)
    for ax in axes:
        ax.invert_yaxis()
        ax.spines[['top', 'right']].set_visible(False)
        ax.set_axisbelow(True)
        ax.xaxis.grid(True, alpha=.2)
    fig.text(.02, .07, 'Panel A: grey = rejected; green = gate passed only.', fontsize=9)
    fig.text(.02, .025, 'Different populations and questions. Gate pass is not admission; authored cases are not independent samples.', fontsize=9)
    fig.tight_layout(rect=(0, .13, 1, 1))
    for suffix in ('png', 'svg'):
        fig.savefig(out / ('research-findings.' + suffix), dpi=180)
    plt.close(fig)
    write_json(out / 'manifest.json', {
        'inputs': {str(p.relative_to(ROOT)): file_hash(p) for p in (gate_path, carry_path)},
        'script_sha256': file_hash(Path(__file__)),
        'artifacts': {p.name: file_hash(p) for p in out.iterdir() if p.is_file()}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    plot(parser.parse_args().out)
