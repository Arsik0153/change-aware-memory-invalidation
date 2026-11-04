"""Independent, nonexecuting whole-module syntax inspection of authorized packet."""
import ast
import hashlib
import json
import platform
import sys
import tokenize
from pathlib import Path

BASE = Path('/root/apps/change-aware-memory-invalidation/examples/ai_review_pilot/packet')
OUT = Path('/root/apps/change-aware-memory-invalidation/runs/blinded-ai-reviewer-b-20261104')

def dump(node):
    return None if node is None else ast.dump(node, include_attributes=False)

def signature(node):
    a = node.args
    params = []
    ordinary = a.posonlyargs + a.args
    defaults = [None] * (len(ordinary) - len(a.defaults)) + list(a.defaults)
    for i, (arg, default) in enumerate(zip(ordinary, defaults)):
        params.append(dict(name=arg.arg, kind='positional_only' if i < len(a.posonlyargs) else 'positional_or_keyword', default_ast=dump(default), annotation_ast=dump(arg.annotation)))
    if a.vararg:
        params.append(dict(name=a.vararg.arg, kind='var_positional', default_ast=None, annotation_ast=dump(a.vararg.annotation)))
    for arg, default in zip(a.kwonlyargs, a.kw_defaults):
        params.append(dict(name=arg.arg, kind='keyword_only', default_ast=dump(default), annotation_ast=dump(arg.annotation)))
    if a.kwarg:
        params.append(dict(name=a.kwarg.arg, kind='var_keyword', default_ast=None, annotation_ast=dump(a.kwarg.annotation)))
    return dict(parameters=params, decorators_ast=[dump(x) for x in node.decorator_list], returns_ast=dump(node.returns), is_async=isinstance(node, ast.AsyncFunctionDef))

class Inspector(ast.NodeVisitor):
    def __init__(self):
        self.events = []
        self.conditional = 0
        self.lexical_scope = 'module'
        self.class_globals = set()

    def event(self, node, name, kind, **extra):
        self.events.append(dict(name=name, kind=kind, line_start=node.lineno, line_end=node.end_lineno, unconditional=self.conditional == 0, **extra))

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            if self.lexical_scope == 'module' or node.id in self.class_globals:
                self.event(node, node.id, 'delete' if isinstance(node.ctx, ast.Del) else 'assignment_or_target')

    def visit_FunctionDef(self, node):
        if self.lexical_scope == 'module' or node.name in self.class_globals:
            self.event(node, node.name, 'function', signature=signature(node), type_parameters_present=bool(getattr(node, 'type_params', [])))
        # Decorators, defaults and annotations are source expressions at the enclosing scope.
        for expr in node.decorator_list + node.args.defaults + [x for x in node.args.kw_defaults if x is not None]:
            self.visit(expr)
        for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs + ([node.args.vararg] if node.args.vararg else []) + ([node.args.kwarg] if node.args.kwarg else []):
            if arg.annotation:
                self.visit(arg.annotation)
        if node.returns:
            self.visit(node.returns)
        # Function bodies create a separate scope; their syntax is still parsed in full.

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        if self.lexical_scope == 'module' or node.name in self.class_globals:
            self.event(node, node.name, 'class')
        for expr in node.decorator_list + node.bases + [x.value for x in node.keywords]:
            self.visit(expr)
        old_scope, old_globals = self.lexical_scope, self.class_globals
        self.lexical_scope = 'class'
        self.class_globals = {name for stmt in node.body if isinstance(stmt, ast.Global) for name in stmt.names}
        for stmt in node.body:
            self.visit(stmt)
        self.lexical_scope, self.class_globals = old_scope, old_globals

    def visit_Lambda(self, node):
        for expr in node.args.defaults + [x for x in node.args.kw_defaults if x is not None]:
            self.visit(expr)

    def visit_Import(self, node):
        for alias in node.names:
            name = alias.asname or alias.name.split('.')[0]
            if self.lexical_scope == 'module' or name in self.class_globals:
                self.event(node, name, 'import')

    def visit_ImportFrom(self, node):
        for alias in node.names:
            name = alias.asname or alias.name
            if self.lexical_scope == 'module' or name in self.class_globals:
                self.event(node, name, 'wildcard_import' if name == '*' else 'import')

    def visit_ExceptHandler(self, node):
        if node.name and (self.lexical_scope == 'module' or node.name in self.class_globals):
            self.event(node, node.name, 'exception_binding')
        self.generic_visit(node)

    def visit_MatchAs(self, node):
        if node.name and (self.lexical_scope == 'module' or node.name in self.class_globals):
            self.event(node, node.name, 'match_binding')
        self.generic_visit(node)

    def visit_MatchStar(self, node):
        if node.name and (self.lexical_scope == 'module' or node.name in self.class_globals):
            self.event(node, node.name, 'match_binding')

    def visit_MatchMapping(self, node):
        if node.rest and (self.lexical_scope == 'module' or node.rest in self.class_globals):
            self.event(node, node.rest, 'match_binding')
        self.generic_visit(node)

    def visit_comprehension(self, node):
        # Comprehension iteration variables have their own scope, but a walrus
        # in its iterable/condition/value can bind into the containing scope.
        self.visit(node.iter)
        for expr in node.ifs:
            self.visit(expr)

    def control(self, node):
        self.conditional += 1
        self.generic_visit(node)
        self.conditional -= 1

    visit_If = control
    visit_For = control
    visit_AsyncFor = control
    visit_While = control
    visit_Try = control
    visit_TryStar = control
    visit_With = control
    visit_AsyncWith = control
    visit_Match = control

def main():
    raw = (BASE / 'cases.json').read_bytes()
    cases = json.loads(raw)
    paths = sorted({c['source_path'] for c in cases})
    modules = {}
    inventory = []
    for rel in paths:
        p = BASE / rel
        source_raw = p.read_bytes()
        sha = hashlib.sha256(source_raw).hexdigest()
        assert all(c['source_sha256'] == sha for c in cases if c['source_path'] == rel)
        inventory.append(dict(source_path=rel, source_sha256=sha))
        with tokenize.open(p) as stream:
            source = stream.read()
        tree = ast.parse(source, filename=rel)
        scanner = Inspector()
        scanner.visit(tree)
        targets = sorted({c['subject']['qualname'] for c in cases if c['source_path'] == rel})
        # Independently store actual facts first; this pass never reads expected_signature.
        target_info = {}
        for name in targets:
            ev = [e for e in scanner.events if e['name'] in (name, '*')]
            defs = [e for e in ev if e['name'] == name and e['kind'] == 'function']
            bindings = [e for e in ev if e['kind'] != 'function']
            snippets = []
            lines = source.splitlines()
            for event in ev:
                end = event['line_end']
                if event['kind'] == 'function':
                    n = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.lineno == event['line_start'])
                    end = n.body[0].lineno - 1
                    if end < event['line_start']:
                        end = event['line_start']
                start = max(1, event['line_start'] - 1)
                snippets.append('\n'.join(f'{i}: {lines[i-1]}' for i in range(start, min(end+2, len(lines))+1)))
            target_info[name] = dict(definitions=defs, bindings=bindings, snippets=snippets)
        modules[rel] = dict(line_count=len(source.splitlines()), ast_node_count=sum(1 for _ in ast.walk(tree)), top_level_statements=[dict(kind=type(n).__name__, line_start=n.lineno, line_end=n.end_lineno, name=getattr(n, 'name', None)) for n in tree.body], module_scope_events=scanner.events, targets=target_info, global_declarations=[dict(line=n.lineno, names=n.names) for n in ast.walk(tree) if isinstance(n, ast.Global)])
    identity = dict(cases_sha256=hashlib.sha256(raw).hexdigest(), sources=inventory)
    packet_sha = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    assert packet_sha == '3b2069e787061695a9d1e3c9028678803155a1804ba86f4d83ddb60d7dfc27c3'
    report = dict(parser='CPython ast', python_version=sys.version, platform=platform.python_implementation(), identity=identity, packet_sha256=packet_sha, modules=modules)
    (OUT / 'independent_extraction.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Python {sys.version}; packet_sha256={packet_sha}; {len(cases)} cases, {len(paths)} source modules')
    for rel, module in modules.items():
        print(f'\nMODULE {rel} lines={module["line_count"]} nodes={module["ast_node_count"]} globals={module["global_declarations"]}')
        for name, facts in module['targets'].items():
            print(name, json.dumps({k:v for k,v in facts.items() if k != 'snippets'}, sort_keys=True))
            for snippet in facts['snippets']:
                print(snippet)

if __name__ == '__main__':
    main()
