"""Plot parent-only graph diagnostics; no child outcomes or extraction accuracy claim."""
from pathlib import Path
import argparse

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from cami.artifacts import file_hash,read_json,reserve,write_json

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'reports/research-20261104/parent-graph-profile-v2/summary.json'


def plot(out):
    summary=read_json(DATA)
    reserve(out)
    fig,axes=plt.subplots(1,2,figsize=(11,3.6),gridspec_kw={'width_ratios':[1.2,1]})
    repos=['click','requests','pytest']
    total=[summary['by_repo'][r]['modules_across_parents'] for r in repos]
    unresolved=[summary['by_repo'][r]['modules_unresolved_added_by_linking'] for r in repos]
    axes[0].barh(repos,total,color='#d3dade',label='All indexed modules')
    axes[0].barh(repos,unresolved,color='#547d9b',label='Module unresolved after linking')
    for y,(n,d) in enumerate(zip(unresolved,total,strict=True)):
        axes[0].text(d+18,y,f'{n}/{d}',va='center',fontsize=10)
    axes[0].set(xlim=(0,1660),xlabel='Module occurrences across frozen parent snapshots',title='A. Linking adds module-level uncertainty')
    axes[0].legend(loc='upper center',bbox_to_anchor=(.5,-.25),frameon=False,fontsize=8)
    labels=['Subject unresolved','Subject module unresolved','Global unresolved']
    axes[1].barh(labels,[63,63,63],color='#b6523c')
    for y in range(3):
        axes[1].text(64,y,'63/63',va='center',fontsize=10)
    axes[1].set(xlim=(0,78),xlabel='Behavior candidates (same 63 in each row)',title='B. Overlapping fallback flags')
    for ax in axes:
        ax.invert_yaxis()
        for spine in ('top','right'):
            ax.spines[spine].set_visible(False)
    fig.subplots_adjust(left=.08,right=.99,bottom=.32,top=.86,wspace=.65)
    fig.text(.02,.025,'Parent-only diagnostic. Flags are analyzer uncertainty, not false claims. All original provenance remains known-incomplete.',fontsize=9)
    for ext in ('png','svg'):
        fig.savefig(out/f'parent-graph-profile.{ext}',dpi=180)
    plt.close(fig)
    write_json(out/'manifest.json',{'source_sha256':file_hash(DATA),'script_sha256':file_hash(Path(__file__)),
        'artifact_hashes':{p.name:file_hash(p) for p in out.iterdir() if p.is_file()}})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    plot(parser.parse_args().out)
