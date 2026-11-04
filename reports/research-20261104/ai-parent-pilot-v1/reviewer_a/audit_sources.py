import ast
import json
import pathlib
ROOT = pathlib.Path('/root/apps/change-aware-memory-invalidation/examples/ai_review_pilot/packet')
OUT = pathlib.Path('/root/apps/change-aware-memory-invalidation/runs/blinded-ai-reviewer-a-20261104')
cases = json.loads((ROOT / 'cases.json').read_text())
lines_out = []
for path in sorted(set(c['source_path'] for c in cases)):
    text = (ROOT / path).read_text()
    lines = text.splitlines()
    tree = ast.parse(text)
    targets = {c['subject']['qualname'] for c in cases if c['source_path'] == path}
    lines_out.append('\nFILE ' + path)
    def outline(nodes, indent=''):
        for node in nodes:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                lines_out.append(f'{indent}{node.lineno}-{node.end_lineno} {type(node).__name__} {node.name}')
            else:
                lines_out.append(f'{indent}{node.lineno}-{node.end_lineno} {type(node).__name__}: ' + lines[node.lineno-1].strip())
                for field in ('body', 'orelse', 'finalbody'):
                    children = getattr(node, field, [])
                    if children:
                        outline(children, indent + '  ')
                for handler in getattr(node, 'handlers', []):
                    lines_out.append(f'{indent}  EXCEPT {handler.lineno}: {handler.name}')
                    outline(handler.body, indent + '    ')
    outline(tree.body)
    lines_out.append('TARGET HEADERS AND SURROUNDING LINES:')
    selected = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in targets:
            selected.update(range(max(1,n.lineno-2), min(len(lines),n.body[0].lineno)+1))
        if isinstance(n, (ast.Global, ast.Nonlocal)):
            lines_out.append(f'SCOPE DECLARATION {n.lineno}: {ast.dump(n)}')
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {'exec','eval','globals','locals','setattr','delattr'}:
            lines_out.append(f'DYNAMIC CALL {n.lineno}: {lines[n.lineno-1].strip()}')
        if isinstance(n, ast.Name) and n.id in targets and isinstance(n.ctx,(ast.Store, ast.Del)):
            lines_out.append(f'ALL-SCOPE TARGET WRITE {n.lineno}: {ast.dump(n)}')
    for i in sorted(selected):
        lines_out.append(f'{i}: {lines[i-1]}')
    lines_out.append('MODULE TAIL:')
    for i in range(max(1,len(lines)-11),len(lines)+1):
        lines_out.append(f'{i}: {lines[i-1]}')
(OUT / 'source_audit.txt').write_text('\n'.join(lines_out)+'\n')
print('\n'.join(lines_out))
