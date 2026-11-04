"""Plot the persisted 48-state Git/Docker audit witness, without timing claims."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle

from cami.artifacts import file_hash, read_json, reserve, write_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'reports/research-20261104/periodic-audit-docker-v1/results.json'


def plot(out: Path) -> None:
    rows = read_json(DATA)
    reserve(out)
    fig, ax = plt.subplots(figsize=(11,3.7))
    colors = {'false_available':'#c4513d','withheld':'#d4d9dd','supported':'#4b9c87'}
    labels = {'hidden_missing':'No periodic audit','periodic_2':'Audit K=2',
              'periodic_4':'Audit K=4','all_validate':'Validate all'}
    for y,row in enumerate(rows):
        for x,state in enumerate(row['states'],1):
            kind = ('withheld' if not state['available'] else 'supported'
                    if state['truth']=='supported' else 'false_available')
            ax.add_patch(Rectangle((x-.45,y-.35),.9,.7,facecolor=colors[kind]))
            if state['selected']:
                ax.plot(x,y,'o',color='#17242b',markersize=4)
        ax.text(12.7,y,f"{row['maintenance_validations']} / {row['availability_mismatches']}",va='center')
    ax.text(12.7,-.85,'Checks / errors',fontsize=10)
    ax.set(xticks=range(1,13),yticks=range(4),yticklabels=[labels[r['variant']] for r in rows],
           xlim=(.5,14.7),ylim=(3.6,-1),xlabel='Processed child commit (dependency restored at 9)')
    ax.axvline(8.5,color='#64717a',linestyle='--',linewidth=1)
    for side in ('top','right','left'):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis='y',length=0)
    ax.legend(handles=[Patch(color=colors['false_available'],label='False availability'),
        Patch(color=colors['withheld'],label='Withheld'),Patch(color=colors['supported'],label='Supported'),
        plt.Line2D([],[],marker='o',color='none',markerfacecolor='#17242b',label='Validated')],
        loc='upper center',bbox_to_anchor=(.5,-.26),ncol=4,frameon=False)
    fig.subplots_adjust(left=.17,right=.99,top=.98,bottom=.30)
    fig.text(.02,.015,'Research adapter; one authored history; 93 actual Docker probe executions. No timing or population claim.',fontsize=9)
    for suffix in ('png','svg'):
        fig.savefig(out/f'periodic-audit-docker.{suffix}',dpi=180)
    plt.close(fig)
    write_json(out/'manifest.json',{'source':str(DATA.relative_to(ROOT)),'source_sha256':file_hash(DATA),
        'script_sha256':file_hash(Path(__file__)),
        'artifact_hashes':{p.name:file_hash(p) for p in out.iterdir() if p.is_file()}})


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    plot(parser.parse_args().out)
