"""Draw the checked two-state cycle from the finite reachability artifact."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

from cami.artifacts import file_hash, read_json, reserve, write_json

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'reports/research-20261104/behavior-reachability-v1'


def plot(out: Path) -> None:
    result_path, programs_path = BASE / 'hidden_missing.json', BASE / 'programs.json'
    result, programs = read_json(result_path), read_json(programs_path)
    prefix, cycle = result['cycle_prefix'], result['source_changing_unsafe_cycle']
    assert len(prefix) == 1 and len(cycle) == 2
    assert prefix[0]['to'] == cycle[0]['from'] == cycle[-1]['to']
    assert all(not e['selected'] and e['changed_files'] == ['unrelated.py'] for e in cycle)
    reserve(out)
    fig, ax = plt.subplots(figsize=(11, 4.8))
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.axis('off')
    node_positions = [(.16, .50), (.62, .76), (.62, .24)]
    ids = [prefix[0]['from_program'], cycle[0]['from_program'], cycle[0]['to_program']]
    for i, (position, number) in enumerate(zip(node_positions, ids)):
        p = programs[number]
        label = f"f() = {p['value']}\nVALUE = {p['unrelated']}\navailable = true"
        if i:
            label += '\nCLAIM IS FALSE'
        ax.text(*position, label, ha='center', va='center', fontsize=12,
            color='#8b3427' if i else '#175c52',
            bbox={'boxstyle':'round,pad=.65', 'facecolor':'#fae9e4' if i else '#e5f2ee',
                  'edgecolor':'#b34e39' if i else '#24766b', 'linewidth':1.5})
    ax.add_patch(FancyArrowPatch((.29,.56),(.47,.72),arrowstyle='-|>',mutation_scale=18,color='#555555'))
    ax.text(.34,.76,'g: 1 → 2\nhidden change',ha='center',va='center',fontsize=11)
    ax.add_patch(FancyArrowPatch((.76,.63),(.76,.37),connectionstyle='arc3,rad=-.6',
        arrowstyle='-|>',mutation_scale=18,color='#b34e39',linewidth=1.6))
    ax.add_patch(FancyArrowPatch((.48,.37),(.48,.63),connectionstyle='arc3,rad=-.6',
        arrowstyle='-|>',mutation_scale=18,color='#b34e39',linewidth=1.6))
    ax.text(.91,.50,'VALUE\n0 → 1',ha='center',va='center',fontsize=11)
    ax.text(.36,.49,'VALUE\n1 → 0',ha='center',va='center',fontsize=11)
    ax.text(.62,.50,'No validation\non either cycle edge',ha='center',va='center',fontsize=11)
    fig.suptitle('A source-changing cycle preserves false availability',fontsize=15,y=.98)
    fig.text(.02,.025,'Finite model: cycle can repeat without bound. Concrete Git witness verified one traversal; this is not a population frequency.',fontsize=9)
    fig.tight_layout(rect=(0,.08,1,.95))
    for suffix in ('png','svg'):
        fig.savefig(out / ('behavior-cycle.'+suffix),dpi=180)
    plt.close(fig)
    write_json(out / 'manifest.json', {'inputs':{str(p.relative_to(ROOT)):file_hash(p)
        for p in (result_path,programs_path)}, 'script_sha256':file_hash(Path(__file__)),
        'artifacts':{p.name:file_hash(p) for p in out.iterdir() if p.is_file()}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    plot(parser.parse_args().out)
