"""Plot finite-model risk bounds and logical validation counts, not measured runtime."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from cami.artifacts import file_hash, read_json, reserve, write_json

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'reports/research-20261104/periodic-audit-bound-v1/summary.json'


def plot(out: Path) -> None:
    data = read_json(SOURCE)
    intervals = sorted(int(k) for k in data['intervals'])
    risk = [data['intervals'][str(k)]['risk']['max_consecutive_false_available'] for k in intervals]
    reserve(out)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11})
    fig, axes = plt.subplots(1,2,figsize=(12,4.6))
    axes[0].plot(intervals,risk,'o-',color='#b34e39')
    axes[0].set(title='A. Tight bound in the finite model',ylabel='Longest false-availability run, transitions')
    axes[0].text(.04,.88,'Without an audit: unbounded',transform=axes[0].transAxes,fontsize=10)
    axes[0].set_ylim(-.25,8)
    for name,label,color in [('stable','Stable','#24766b'),('persistently_false','Always false','#b34e39'),
                              ('break_then_restore','Break / restore','#557b9e')]:
        values = [next(w['logical_validations'] for w in data['workloads']
                       if w['workload']==name and w['interval']==k) for k in intervals]
        axes[1].plot(intervals,values,'o-',label=label,color=color)
    axes[1].set(title='B. Cost on three authored 40-step histories',ylabel='Child logical validations')
    axes[1].set_ylim(0,43)
    axes[1].legend(loc='upper center',bbox_to_anchor=(.5,-.25),ncol=3,fontsize=9,frameon=False)
    for ax in axes:
        ax.set_xlabel('Audit interval K, processed child commits')
        ax.set_xticks(intervals)
        ax.spines[['top','right']].set_visible(False)
        ax.grid(True,alpha=.2)
        ax.set_axisbelow(True)
    fig.text(.02,.025,'Model extension only: no Docker executions or timing measurements. Bound assumes correct validation of the stored predicate.',fontsize=9)
    fig.tight_layout(rect=(0,.07,1,1))
    for suffix in ('png','svg'):
        fig.savefig(out / ('periodic-audit.'+suffix),dpi=180)
    plt.close(fig)
    write_json(out / 'manifest.json',{'input_sha256':file_hash(SOURCE),
        'script_sha256':file_hash(Path(__file__)),
        'artifacts':{p.name:file_hash(p) for p in out.iterdir() if p.is_file()}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    plot(parser.parse_args().out)
