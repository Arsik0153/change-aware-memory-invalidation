"""Standalone figures and a theme-aware interactive view of the complete v3 run."""
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / 'runs/opencode-development-v3-final-analysis-20261104/report.json'
report = json.loads(SOURCE.read_text())
assert report['summary']['terminal_trials'] == 36
assert report['summary']['all_trials_operational_quality_pass']
rows = [{'repetition': b['repetition'], 'arm': b['arm'],
         'tokens': b['token_work']['total'], 'wall': b['charged_wall']['total']}
        for b in report['summary']['blocks']]
data = {'report_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(), 'blocks': rows,
        'primary_superiority': report['summary']['primary_superiority'],
        'timing_caveat': 'Known auxiliary overlap in r1-plain-s1; primary wall metric ineligible.',
        'token_definition': 'input + cache_write + output + reasoning; cache_read reported separately; not actual billing'}
(OUT / 'chart-data.json').write_text(json.dumps(data, indent=2) + '\n')
names = ['plain', 'static', 'cami']
labels = ['OpenCode', '+ Static memory', '+ CAMI']
colors = ['#3569a8', '#d58b21', '#19856d']
fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.5))
for ax, metric, title, ylabel in zip(axes, ['tokens', 'wall'],
        ['Normalized token work', 'Charged sequence wall (descriptive only)'], ['Tokens', 'Seconds'], strict=True):
    for i, arm in enumerate(names):
        values = [next(row[metric] for row in rows if row['arm'] == arm and row['repetition'] == rep)
                  for rep in (1, 2, 3)]
        bars = ax.bar(np.arange(3) + (i - 1) * 0.25, values, 0.24, label=labels[i], color=colors[i])
        ax.bar_label(bars, labels=[f'{v / 1000:.1f}k' if metric == 'tokens' else f'{v:.1f}' for v in values], fontsize=8)
    ax.set_xticks(np.arange(3), ['Repeat 1', 'Repeat 2', 'Repeat 3'])
    ax.set_title(title, fontsize=11)
    ax.set_ylabel(ylabel)
    ax.set_ylim(0, max(row[metric] for row in rows) * 1.17)
    ax.spines[['top', 'right']].set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(axis='y', alpha=0.18)
axes[0].legend(frameon=False, fontsize=8, loc='upper left')
fig.suptitle('Development v3: all 36 attempts pass quality; no consistent advantage', fontsize=12)
fig.text(0.5, 0.025, 'Token work excludes cache reads and is not billing. Known auxiliary overlap disqualifies the primary wall-time claim.\nEach block contains four stages on two fixed Click tasks; no population or final-heldout claim.', ha='center', fontsize=8)
fig.tight_layout(rect=(0, 0.10, 1, 0.94))
fig.savefig(OUT / 'comparison.png', dpi=180)
fig.savefig(OUT / 'comparison.svg')
plt.close(fig)

html = '''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{margin:0;font-family:var(--font-sans);color:var(--foreground)}p{line-height:1.5;margin:8px 0}.controls,.legend{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.controls button{padding:7px 12px;border:1px solid var(--border);border-radius:var(--radius);background:var(--secondary);color:var(--foreground);cursor:pointer}.controls button[aria-pressed=true]{background:var(--primary);color:var(--primary-foreground)}.legend{font-size:13px;margin-top:14px}.key{display:inline-block;width:10px;height:10px;margin-right:5px;border-radius:2px}.small{font-size:12px;color:var(--muted-foreground)}svg{display:block;width:100%;height:280px;overflow:visible}svg text{fill:var(--foreground);font-family:var(--font-sans)}.axis{stroke:var(--border)}.grid{stroke:var(--border);stroke-dasharray:3 3}.result{font-weight:600}table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:right;padding:6px 4px;border-bottom:1px solid var(--border)}td:first-child,th:first-child{text-align:left}
</style></head><body><p class="result">Разработка v3: 36/36 запусков прошли проверку решения. Критерий преимущества не выполнен.</p><div class="controls"><button id="tokens" aria-pressed="true">Токены без чтения кеша</button><button id="wall" aria-pressed="false">Время с полными затратами</button></div><div class="legend"><span><i class="key" style="background:var(--chart-1)"></i>OpenCode</span><span><i class="key" style="background:var(--chart-2)"></i>+ память без CAMI</span><span><i class="key" style="background:var(--chart-3)"></i>+ память CAMI</span></div><svg id="chart" viewBox="0 0 700 280" role="img"></svg><table id="table"></table><p id="note" class="small"></p><p class="small">Каждый повтор — четыре этапа на двух закреплённых задачах Click. Построение и обновление памяти включены. Итоговый отложенный набор ещё не использовался.</p><script>
const data=DATA,arms=['plain','static','cami'];let metric='tokens';const ns='http://www.w3.org/2000/svg';
function draw(){const svg=document.getElementById('chart');svg.replaceChildren();const max=metric==='tokens'?160000:700;const top=22,bottom=238,h=bottom-top,W=Math.max(320,Math.min(700,svg.getBoundingClientRect().width)),left=45,group=(W-left-4)/3,bw=Math.min(40,group*.24),step=bw+Math.min(9,group*.05);svg.setAttribute('viewBox','0 0 '+W+' 280');function el(n,a,t){const e=document.createElementNS(ns,n);Object.entries(a).forEach(([k,v])=>e.setAttribute(k,v));if(t!==undefined)e.textContent=t;svg.appendChild(e);return e;}
for(let i=0;i<=4;i++){const v=max*i/4,y=bottom-h*i/4;el('line',{x1:left,x2:W-4,y1:y,y2:y,class:'grid'});el('text',{x:left-7,y:y+4,'text-anchor':'end','font-size':11},metric==='tokens'?(v/1000)+'k':Math.round(v));}
for(let r=1;r<=3;r++){const center=left+(r-.5)*group;arms.forEach((arm,i)=>{const row=data.blocks.find(x=>x.repetition===r&&x.arm===arm),v=row[metric],height=h*v/max,x=center+(i-1)*step-bw/2;const bar=el('rect',{x,y:bottom-height,width:bw,height,fill:'var(--chart-'+(i+1)+')'});const title=document.createElementNS(ns,'title');title.textContent=arm+': '+v;bar.appendChild(title);el('text',{x:x+bw/2,y:bottom-height-6,'text-anchor':'middle','font-size':11},metric==='tokens'?(v/1000).toFixed(1)+'k':v.toFixed(1));});el('text',{x:center,y:261,'text-anchor':'middle','font-size':12},'Повтор '+r);}
svg.setAttribute('aria-label',metric==='tokens'?'Токены по трём повторам':'Время по трём повторам, только описательное сравнение');document.getElementById('tokens').setAttribute('aria-pressed',metric==='tokens');document.getElementById('wall').setAttribute('aria-pressed',metric==='wall');document.getElementById('table').innerHTML='<thead><tr><th>Повтор</th><th>OpenCode</th><th>Без CAMI</th><th>CAMI</th></tr></thead><tbody>'+[1,2,3].map(r=>'<tr><td>'+r+'</td>'+arms.map(a=>'<td>'+data.blocks.find(x=>x.repetition===r&&x.arm===a)[metric].toLocaleString('ru-RU',{maximumFractionDigits:metric==='tokens'?0:2})+'</td>').join('')+'</tr>').join('')+'</tbody>';document.getElementById('note').textContent=metric==='tokens'?'Сумма input + cache_write + output + reasoning. Чтение кеша учитывается отдельно; это не сумма оплаты Codex. CAMI обошёл обе альтернативы по этому счётчику только в третьем повторе.':'Секунды, включая построение, обновление памяти и работу сессии. Из-за известного пересечения первого обычного запуска с фоновой проверкой первичное сравнение времени недопустимо; значения сохранены как описательные.';}
document.getElementById('tokens').onclick=()=>{metric='tokens';draw()};document.getElementById('wall').onclick=()=>{metric='wall';draw()};window.addEventListener('resize',draw);draw();
</script></body></html>'''.replace('DATA', json.dumps(data, ensure_ascii=False))
(OUT / 'comparison.html').write_text(html)
print(json.dumps({'outputs': ['comparison.png', 'comparison.svg', 'comparison.html', 'chart-data.json'], 'report_sha256': data['report_sha256']}))
