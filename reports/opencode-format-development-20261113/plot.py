from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=Path(__file__).resolve().parent
data=json.loads((root/'analysis.json').read_text())['summary']
blocks=data['blocks']
labels=['No memory','Static compact','CAMI compact','Static readable','CAMI readable']
values=[b['token_work']['total'] for b in blocks]
fig,ax=plt.subplots(figsize=(8,4.2),layout='constrained')
ax.barh(labels,values,color=['#6b7280','#2563eb','#7c3aed','#2563eb','#7c3aed'])
ax.invert_yaxis();ax.set_xlim(0,max(values)*1.2)
for i,v in enumerate(values):ax.text(v+1800,i,f'{v:,}',va='center',fontsize=10)
ax.set_xlabel('Normalized noncached token work / four stages')
ax.set_title('20 sessions: quality passed; combined hypothesis inconclusive',loc='left',fontsize=12)
ax.spines[['top','right','left']].set_visible(False)
ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True)
fig.savefig(root/'token-work.png',dpi=180)
fig.savefig(root/'token-work.pdf')
