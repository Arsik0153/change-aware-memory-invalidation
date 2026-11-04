import ast
import hashlib
import io
import json
import pathlib
import platform
import sys
import tokenize

ROOT = pathlib.Path('/root/apps/change-aware-memory-invalidation/examples/ai_review_pilot/packet')
OUT = pathlib.Path('/root/apps/change-aware-memory-invalidation/runs/blinded-ai-reviewer-a-20261104')

def dump(expr):
    return None if expr is None else ast.dump(expr, include_attributes=False)

def signature(node):
    # Entirely derived from source syntax; predicate data is not passed in.
    args = node.args
    normal = args.posonlyargs + args.args
    defaults = [None] * (len(normal) - len(args.defaults)) + list(args.defaults)
    params = []
    for i, (arg, default) in enumerate(zip(normal, defaults)):
        params.append(dict(name=arg.arg, kind='positional_only' if i < len(args.posonlyargs) else 'positional_or_keyword', default_ast=dump(default), annotation_ast=dump(arg.annotation)))
    if args.vararg:
        params.append(dict(name=args.vararg.arg, kind='var_positional', default_ast=None, annotation_ast=dump(args.vararg.annotation)))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        params.append(dict(name=arg.arg, kind='keyword_only', default_ast=dump(default), annotation_ast=dump(arg.annotation)))
    if args.kwarg:
        params.append(dict(name=args.kwarg.arg, kind='var_keyword', default_ast=None, annotation_ast=dump(args.kwarg.annotation)))
    return dict(parameters=params, returns_ast=dump(node.returns), decorators_ast=[dump(x) for x in node.decorator_list], is_async=isinstance(node, ast.AsyncFunctionDef))

class ModuleScan(ast.NodeVisitor):
    def __init__(self, target):
        self.target = target
        self.definitions = []
        self.bindings = []
        self.wildcards = []
        self.conditional = 0
        self.scope = 'module'
    def event(self, node, kind):
        self.bindings.append(dict(kind=kind, line_start=node.lineno, line_end=node.end_lineno))
    def visit_Name(self, node):
        if node.id == self.target and isinstance(node.ctx, (ast.Store, ast.Del)):
            self.event(node, type(node.ctx).__name__)
    def visit_Import(self, node):
        for alias in node.names:
            if (alias.asname or alias.name.split('.')[0]) == self.target:
                self.event(node, 'import')
    def visit_ImportFrom(self, node):
        for alias in node.names:
            if alias.name == '*':
                self.wildcards.append(dict(line_start=node.lineno, line_end=node.end_lineno))
            elif (alias.asname or alias.name) == self.target:
                self.event(node, 'import_from')
    def visit_FunctionDef(self, node):
        if node.name == self.target:
            self.definitions.append(dict(line_start=node.lineno, line_end=node.end_lineno, unconditional=self.conditional == 0, type_parameters_present=bool(getattr(node, 'type_params', [])), actual_signature=signature(node)))
        # Function body is a distinct lexical scope. Definition expressions run here.
        for deco in node.decorator_list:
            self.visit(deco)
        for expr in node.args.defaults + [x for x in node.args.kw_defaults if x is not None]:
            self.visit(expr)
        for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs + ([node.args.vararg] if node.args.vararg else []) + ([node.args.kwarg] if node.args.kwarg else []):
            if arg.annotation:
                self.visit(arg.annotation)
        if node.returns:
            self.visit(node.returns)
    visit_AsyncFunctionDef = visit_FunctionDef
    def visit_ClassDef(self, node):
        if node.name == self.target:
            self.event(node, 'class_definition')
        for expr in node.decorator_list + node.bases + [x.value for x in node.keywords]:
            self.visit(expr)
        # Class-local bindings and methods are not module definitions.
    def visit_Lambda(self, node):
        for expr in node.args.defaults + [x for x in node.args.kw_defaults if x is not None]:
            self.visit(expr)
    def visit_AnnAssign(self, node):
        # A bare annotation does not bind the name; inspect annotation/value expressions.
        if node.value is not None:
            self.visit(node.target)
            self.visit(node.value)
        self.visit(node.annotation)
    def visit_ExceptHandler(self, node):
        if node.name == self.target:
            self.event(node, 'exception_binding')
        self.generic_visit(node)
    def visit_MatchAs(self, node):
        if node.name == self.target:
            self.event(node, 'match_binding')
        self.generic_visit(node)
    def visit_MatchStar(self, node):
        if node.name == self.target:
            self.event(node, 'match_star_binding')
    def visit_MatchMapping(self, node):
        if node.rest == self.target:
            self.event(node, 'match_mapping_binding')
        self.generic_visit(node)
    def control(self, node):
        self.conditional += 1
        self.generic_visit(node)
        self.conditional -= 1
    visit_If = control
    visit_For = control
    visit_AsyncFor = control
    visit_While = control
    visit_With = control
    visit_AsyncWith = control
    visit_Try = control
    visit_TryStar = control
    visit_Match = control
    def comprehension(self, node):
        # Comprehension iteration targets are local. Walrus assignments in its
        # expressions bind the containing scope, so inspect expressions only.
        for gen in node.generators:
            self.visit(gen.iter)
            for expr in gen.ifs:
                self.visit(expr)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
    visit_ListComp = comprehension
    visit_SetComp = comprehension
    visit_DictComp = comprehension
    visit_GeneratorExp = comprehension

cases_bytes = (ROOT / 'cases.json').read_bytes()
cases = json.loads(cases_bytes)
paths = sorted(set(c['source_path'] for c in cases))
sources = {}
inventory = []
for path in paths:
    data = (ROOT / path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    assert all(c['source_sha256'] == sha for c in cases if c['source_path'] == path)
    inventory.append(dict(source_path=path, source_sha256=sha))
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    text = data.decode(encoding)
    tree = ast.parse(text, filename=path, type_comments=True)
    sources[path] = (text, tree)
identity = dict(cases_sha256=hashlib.sha256(cases_bytes).hexdigest(), sources=inventory)
packet_hash = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
assert packet_hash == '3b2069e787061695a9d1e3c9028678803155a1804ba86f4d83ddb60d7dfc27c3'
observations = []
for c in cases:
    text, tree = sources[c['source_path']]
    target = c['subject']['qualname']
    scan = ModuleScan(target)
    scan.visit(tree)
    # Independent signature extraction above is complete before reading predicate.
    matches = None
    if c['kind'] == 'signature_equals' and len(scan.definitions) == 1:
        matches = scan.definitions[0]['actual_signature'] == c['predicate']['expected_signature']
    hits = []
    for node in ast.walk(tree):
        if ((isinstance(node, ast.Name) and node.id == target) or
            (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == target) or
            (isinstance(node, ast.alias) and (node.asname or node.name.split('.')[0]) == target) or
            (isinstance(node, (ast.Global, ast.Nonlocal)) and target in node.names)):
            hits.append(dict(node=type(node).__name__, line=node.lineno, code=text.splitlines()[node.lineno-1].strip()))
    observations.append(dict(id=c['id'], kind=c['kind'], source_path=c['source_path'], subject=c['subject'], lines=len(text.splitlines()), definitions=scan.definitions, bindings=scan.bindings, wildcards=scan.wildcards, signature_matches=matches, target_hits=sorted(hits,key=lambda x:x['line'])))
report = dict(python=sys.version, platform=platform.python_implementation(), packet_sha256=packet_hash, cases_sha256=identity['cases_sha256'], sources=inventory, observations=observations)
(OUT / 'observations.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(dict(python=sys.version, cases=len(cases), sources=len(paths), packet_sha256=packet_hash), indent=2))
for o in observations:
    print(json.dumps(o, separators=(',', ':')))
