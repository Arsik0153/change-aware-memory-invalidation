"""Compare finite audit guarantees under exact and positive-sound validation."""
from pathlib import Path
import argparse

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from cami.artifacts import file_hash,read_json,reserve,write_json

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'reports/research-20261104/ternary-audit-invariants-v1/summary.json'


def plot(out):
    data=read_json(DATA)
    reserve(out)
    fig,(ax,tableax)=plt.subplots(1,2,figsize=(10,3.8),gridspec_kw={'width_ratios':[1,1.35]})
    ks=[1,2,4,8]
    for name,label,color,marker,style in [('exact_binary','Exact binary','#527d9f','o','-'),
        ('sound_positive_only','Sound positive only','#bb603f','x','--')]:
        values=[data['models'][f'{name}-K{k}']['risk']['max_consecutive_false_available'] for k in ks]
        ax.plot(ks,values,label=label,color=color,marker=marker,linestyle=style,markersize=8)
    ax.set(xticks=ks,xlabel='Audit interval K',ylabel='Longest false-availability run',title='A. Same bound, different retention')
    ax.legend(frameon=False,fontsize=9)
    ax.grid(alpha=.15)
    tableax.axis('off')
    table=tableax.table(cellText=[['Exact binary','K-1','No'],['Sound positive only','K-1','Yes'],
        ['False supported allowed','Unbounded','Yes'],['Carry on unknown','Unbounded','Yes']],
        colLabels=['Validation rule','False availability','False withholding'],
        colWidths=[.42,.27,.31],loc='center',cellLoc='left')
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1,1.7)
    for (row,_),cell in table.get_celld().items():
        cell.set_edgecolor('#d2d8dd')
        if row==0:
            cell.set_facecolor('#e3eaf0')
    tableax.set_title('B. Reachable outcomes in these models',fontsize=11)
    fig.subplots_adjust(left=.07,right=.99,top=.86,bottom=.22,wspace=.32)
    fig.text(.02,.025,'64 states / 403 transitions in the two sound-positive models; two defective rules have unsafe self-loops. No Docker executions.',fontsize=9)
    for suffix in ('png','svg'):
        fig.savefig(out/f'validation-assumptions.{suffix}',dpi=180)
    plt.close(fig)
    write_json(out/'manifest.json',{'source_sha256':file_hash(DATA),'script_sha256':file_hash(Path(__file__)),
        'artifact_hashes':{p.name:file_hash(p) for p in out.iterdir() if p.is_file()}})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    plot(parser.parse_args().out)
