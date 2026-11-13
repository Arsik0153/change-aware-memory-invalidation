"""Plot completed token-component evidence, including provider cache reads."""
import base64
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parent
result = json.loads((root / 'token-components-audit.json').read_text())
assert result['status'] == 'verified' and result['all15_pairs_componentwise_nonincreasing']
assert set(result['strict_components_in_every_pair']) == {'input','cache_read','output','reasoning'}
fig, axes = plt.subplots(2, 2, figsize=(10, 6.4), layout='constrained')
for ax, key, title in zip(axes.flat, ['input','cache_read','output','reasoning'],
                         ['Uncached input','Provider cache reads','Visible output','Reasoning']):
    for i, arm in enumerate(['cami','cami_replay']):
        v = result['statistics'][arm][key]
        ax.bar(i, v['median']/1000, color=['#73849a','#148c76'][i], width=.58)
        ax.errorbar(i,v['median']/1000,yerr=[[(v['median']-v['min'])/1000],[(v['max']-v['median'])/1000]],fmt='none',color='#243548',capsize=5)
        ax.text(i,v['max']/1000,f"{v['median']/1000:,.1f}k",ha='center',va='bottom',fontsize=11)
    ax.set_xticks([0,1],['CAMI','CAMI + exact reuse'])
    ax.set_title(title)
    ax.set_ylabel('thousand tokens / four tasks')
    ax.spines[['top','right']].set_visible(False)
    ax.grid(axis='y',alpha=.18)
    ax.set_axisbelow(True)
    ax.margins(y=.2)
fig.suptitle('All token components decreased\nMedian and observed range across five blocks',fontsize=15)
fig.savefig(root/'token-components.png',dpi=180)
fig.savefig(root/'token-components.pdf')
plt.close(fig)
encoded=base64.b64encode((root/'token-components.png').read_bytes()).decode()
(root/'token-components.html').write_text('''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Token components</title>
<style>body{margin:0;font:15px var(--font-sans);color:var(--foreground)}p{line-height:1.5;margin:8px 0}img{width:100%;display:block;background:white}</style>
<p><strong>Экономия сохраняется с учётом кеша провайдера.</strong> Завершённый опыт: 80 попыток, четыре режима, пять блоков.</p>
<img alt="Four token components: CAMI versus CAMI plus exact reuse, medians and ranges" src="data:image/png;base64,'''+encoded+'''">
<p>Во всех 15 сравнениях по блокам каждый из четырёх компонентов меньше, чем у обычного агента, статической памяти и CAMI. Запись в кеш — ноль во всех режимах. На графике показано сравнение с CAMI.</p>
<p>Одинаковые тарифы за токены дают меньшую расчётную стоимость. Это не сумма счёта по подписке. Две задачи разработки и точные повторы; диапазоны — наблюдённые минимум и максимум, не доверительные интервалы.</p></html>''')
