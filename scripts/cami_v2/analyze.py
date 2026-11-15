"""Audit every scheduled attempt and derive the sealed study's aggregate metrics."""
import hashlib
import json
import os
import sqlite3
import subprocess

from study import REPORT, ROOT, RUN


def read(path):
    return json.loads(path.read_text())


def main():
    protocol = read(REPORT / 'protocol.json')
    assert hashlib.sha256((REPORT / 'protocol.json').read_bytes()).hexdigest() == read(REPORT / 'protocol-seal.json')['sha256']
    assert (RUN / 'grader.py').read_text() == protocol['grader']
    assert read(RUN / 'external.json') == protocol['external']
    rows = []
    fixtures = {f['id']: f for f in protocol['fixtures']}
    for item in protocol['attempts']:
        target = RUN / item['id']
        receipt = read(target / 'start.json')
        assert receipt['attempt'] == item
        stdout = (target / 'stdout.log').read_text()
        value = json.loads(stdout.splitlines()[-1]) if stdout.strip() else None
        journals = list((target / 'journals').glob('*'))
        assert len(journals) == 1
        directory = journals[0]
        db = sqlite3.connect(f'file:{directory / "events.sqlite"}?mode=ro', uri=True)
        timed = [(t,k,json.loads(d)) for t,k,d in db.execute('select time_ns,kind,data from events order by seq')]
        events = [(k,d) for _,k,d in timed]
        db.close()
        config = next(v for k,v in events if k == 'prepared')
        terminal = next(v for k,v in events if k == 'terminal')
        api = read(directory / 'api-session.json')
        assert api['workspace'] == config['workspace']
        assert api['model'] == {'providerID':'openai','id':'gpt-6.1-sol','variant':'high'}
        canonical = json.dumps({'schema':'cami-exact-task-replay/2', 'files':config['files'],
                                'task_sha256':hashlib.sha256(config['task'].encode()).hexdigest(),
                                'context':config['context']},sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
        assert config['key'] == hashlib.sha256(canonical).hexdigest() == terminal['input_key']
        assert value['input_key'] == terminal['input_key']
        fixture = fixtures[item['fixture']]
        assert config['task'] == fixture['task']
        assert (directory / 'before/src/solution.py').read_text() == fixture['source']
        assert (directory / 'before/tests/test_solution.py').read_text() == fixture['test_source']
        context = json.loads(config['context'])
        assert json.loads(context['external']) == protocol['external']
        assert context['model'] == protocol['external']['model'] and not config['request_coverage']
        # Independent grader rerun against preserved submission, excluding these audit costs.
        assert config['grade'][:2] == ['/usr/bin/python3.12', '-B']
        audit_grade = ['/usr/bin/python3.12', '-B', str(RUN / 'grader.py'), config['grade'][-1]]
        result = subprocess.run(audit_grade, cwd=directory / 'solution', capture_output=True, text=True,
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'})
        (target / 'audit-grade.log').write_text(result.stdout + result.stderr)
        for tree, files in [('before', config['files']), ('solution', terminal['solution_files'])]:
            actual = {}
            for path in (directory / tree).rglob('*'):
                if path.is_file():
                    actual[path.relative_to(directory / tree).as_posix()] = {
                        'sha256':hashlib.sha256(path.read_bytes()).hexdigest(), 'mode':path.stat().st_mode & 0o777}
            assert actual == files
        telemetry = terminal['telemetry']
        total = telemetry['total']
        row = {**item, 'seconds': read(target / 'timing.json')['seconds'], 'usage':total,
               'token_work':sum(total[k] for k in ['input','output','reasoning','cache_write']) if total else None,
               'known_subtotal':telemetry['known_subtotal'], 'usage_complete':telemetry['complete'],
               'quality':terminal['quality'], 'independent_quality':result.returncode == 0,
               'execution':terminal['execution'], 'returncode':read(target / 'result.json')['returncode'],
               'replayed':terminal.get('replayed',False), 'cache_recorded':terminal['cache_recorded'],
               'journal':str(directory.relative_to(ROOT)),
               'api_receipt':read(directory / 'api-session.json'),
               'terminal_sha256':hashlib.sha256(json.dumps(terminal,sort_keys=True).encode()).hexdigest()}
        times = {k:t for t,k,_ in timed}
        row['spans_seconds'] = {
            'capture': (times['prepared']-times['capture_input_started'])/1e9,
            'context_and_lookup': (times['agent_started']-times['prepared'])/1e9,
            'agent': (times['agent_finished']-times['agent_started'])/1e9,
            'finish': (times['terminal']-times['agent_finished'])/1e9}
        rows.append(row)
    summary = {}
    for arm in ['baseline','v2']:
        selected = [r for r in rows if r['arm'] == arm]
        summary[arm] = {'attempts':len(selected), 'quality_pass':sum(r['independent_quality'] for r in selected),
                        'seconds':sum(r['seconds'] for r in selected),
                        'token_work':sum(r['token_work'] for r in selected) if all(r['usage_complete'] for r in selected) else None,
                        'usage':{k:sum(r['usage'][k] for r in selected) for k in selected[0]['usage']} if all(r['usage_complete'] for r in selected) else None}
    scenarios = {}
    for name, stages in [('new', [1,2]), ('exact-repeat', [3,4]), ('changed-similar', [5,6])]:
        scenarios[name] = {}
        for arm in ['baseline', 'v2']:
            selected = [r for r in rows if r['stage'] in stages and r['arm'] == arm]
            scenarios[name][arm] = {'seconds':sum(r['seconds'] for r in selected),
                                    'token_work':sum(r['token_work'] for r in selected) if all(r['usage_complete'] for r in selected) else None,
                                    'quality_pass':sum(r['independent_quality'] for r in selected)}
    ratio_time = summary['v2']['seconds'] / summary['baseline']['seconds']
    ratio_tokens = summary['v2']['token_work'] / summary['baseline']['token_work'] if all(summary[a]['token_work'] is not None for a in summary) else None
    gate = all(r['independent_quality'] and r['quality']=='pass' and r['execution']=='success' and r['usage_complete'] and r['returncode']==0 for r in rows)
    outcome = {'rows':rows, 'scenarios':scenarios,'totals':summary,'time_ratio':ratio_time,'token_work_ratio':ratio_tokens,
               'quality_and_usage_gate':gate,'positive':gate and ratio_time < 1 and ratio_tokens is not None and ratio_tokens < 1,
               'target_50':gate and ratio_time <= .5 and ratio_tokens is not None and ratio_tokens <= .5,
               'claim_scope':'one sealed synthetic sequence; no production frequency or invoice estimate'}
    (REPORT / 'results.json').write_text(json.dumps(outcome,indent=2,sort_keys=True))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1,2,figsize=(9,4))
    for ax,key,label in [(axes[0],'seconds','Full pipeline seconds'),(axes[1],'token_work','Normalized token work')]:
        values = [summary[a][key] for a in ['baseline','v2']]
        ax.bar(['807285f legacy','v2 opt-in'],values,color=['#64748b','#0d9488'])
        ax.set_title(label)
        for i,v in enumerate(values):
            ax.text(i,v,f'{v:,.1f}',ha='center',va='bottom')
        ax.set_ylim(0,max(values)*1.18)
    fig.suptitle('12 live attempts: six per arm; fixed synthetic sequence')
    fig.tight_layout()
    fig.savefig(REPORT / 'comparison.png',dpi=140)
    html = '<html><body style="font:16px var(--font-sans);color:var(--foreground)"><h3>CAMI v2: 12 live attempts</h3>'
    html += '<p>Two new tasks, two exact repeats, two changed-input tasks per arm. Quality and usage gate: '+str(gate)+'</p>'
    for title,ratio in [('Full time',ratio_time),('Token work',ratio_tokens)]:
        html += f'<p>{title}: v2 / baseline = {ratio:.4f}</p><div style="background:#64748b;width:80%;color:white">baseline 100%</div><div style="background:#0d9488;width:{80*ratio}%;max-width:100%;color:white">v2 {100*ratio:.1f}%</div>'
    html += '<p>No production repeat-rate inference. Observed tokens are not an invoice.</p></body></html>'
    (REPORT / 'comparison.html').write_text(html)
    print(json.dumps({k:v for k,v in outcome.items() if k!='rows'},indent=2))


if __name__ == '__main__':
    main()
