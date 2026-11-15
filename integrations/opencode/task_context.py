"""Bounded task packet over the existing verified worktree index; no target execution."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def tokens(text):
    return set(re.findall(r"[^\W_]+", text.casefold()))


def build(workspace, task, budget=14000):
    from cami.product.store import refresh
    from cami.symbol_search import _search_index
    from cami.product.service import ProductMemory

    workspace = Path(workspace)
    indexed = refresh(workspace, None, (), _search_index)
    query = tokens(task)
    definitions = []
    for module in indexed.generation.index.modules:
        for d in module.definitions:
            name = f"{module.path}:{d.node.qualname}"
            lines = module.source.splitlines(keepends=True)
            body = ''.join(lines[d.start_line - 1:d.end_line])
            # Same transparent lexical identity/body weighting as memory_backend.rank.
            score = 4 * len(query & tokens(name)) + len(query & tokens(body))
            if score:
                definitions.append((-score, name, module.path, d, body))
    definitions.sort(key=lambda x: x[:2])
    selected = definitions[:6]
    selectors = tuple(x[1] for x in selected)
    contexts = ProductMemory(workspace).context_many(selectors) if selectors else ()
    chunks = []
    used = 0

    def add(path, first, last, text, role):
        nonlocal used
        raw = (workspace / path).read_bytes()
        block = f"\n{role} {path}:{first}-{last} sha256={hashlib.sha256(raw).hexdigest()}\n{text}"
        if used + len(block.encode()) <= budget:
            chunks.append(block)
            used += len(block.encode())
            return True
        return False

    for _, _, path, definition, body in selected:
        # Whole definitions first. Large functions use query-centered windows, never a blind prefix.
        if not add(path, definition.start_line, definition.end_line, body, 'definition'):
            lines = (workspace / path).read_text().splitlines(keepends=True)
            hits = [i for i in range(definition.start_line - 1, definition.end_line)
                    if query & tokens(lines[i])]
            center = max(hits, key=lambda i: len(query & tokens(lines[i]))) if hits else definition.start_line - 1
            lo, hi = max(definition.start_line - 1, center - 8), min(definition.end_line, center + 12)
            add(path, lo + 1, hi, ''.join(lines[lo:hi]), 'partial definition; read remaining source')
    chosen = {x[3].node for x in selected}
    relations = [e.model_dump(mode='json', by_alias=True) for e in indexed.generation.index.edges
                 if e.source in chosen or e.target in chosen]
    neighbors = {e.target for e in indexed.generation.index.edges if e.source in chosen}
    neighbors |= {e.source for e in indexed.generation.index.edges if e.target in chosen}
    for module in indexed.generation.index.modules:
        for definition in module.definitions:
            if definition.node in neighbors - chosen:
                lines = module.source.splitlines(keepends=True)
                add(module.path, definition.start_line, definition.end_line,
                    ''.join(lines[definition.start_line - 1:definition.end_line]), 'related definition')
    for path, blob in sorted(((b.path, b) for b in indexed.capture.blobs if b.content is not None)):
        if ('test' in path or Path(path).name in {'pyproject.toml', 'setup.cfg', 'tox.ini'}):
            lines = blob.content.decode('utf-8', errors='replace').splitlines(keepends=True)
            hits = [i for i, line in enumerate(lines) if query & tokens(line)]
            if hits:
                center = max(hits, key=lambda i: len(query & tokens(lines[i])))
                lo, hi = max(0, center - 4), min(len(lines), center + 12)
                add(path, lo + 1, hi, ''.join(lines[lo:hi]), 'test/config window')
    if refresh(workspace, None, (), _search_index).capture.snapshot_id != indexed.capture.snapshot_id:
        raise ValueError('context inputs changed')
    metadata = {'schema': 'cami-task-context/1', 'snapshot': indexed.capture.snapshot_id,
                'cache_reused': indexed.observation.cache_reused,
                'selectors': selectors, 'generations': [c.memory_generation_id for c in contexts],
                'relations': relations[:24], 'graph_complete': False,
                'limitations': ['lexical selection; omitted code may be necessary',
                                'static relations are incomplete; tests are windows'],
                'budget_bytes': budget}
    header = json.dumps(metadata, ensure_ascii=True)
    packet = header + '\n' + ''.join(chunks)
    # Envelope counts toward the hard UTF-8 budget. Remove complete blocks, not mid-code bytes.
    while len(packet.encode()) > budget and chunks:
        chunks.pop()
        packet = header + '\n' + ''.join(chunks)
    if len(packet.encode()) > budget:
        raise ValueError('context metadata exceeds budget')
    return packet


def prepare(workspace, task, state, output):
    env = {**os.environ, 'XDG_STATE_HOME': str(Path(state) / 'index-v2'), 'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(workspace)],
                            input=task, text=True, capture_output=True, env=env, timeout=180)
    if result.returncode:
        raise ValueError('context preparation failed: ' + result.stderr[-2000:])
    Path(output).write_text(result.stdout)
    return result.stdout


if __name__ == '__main__':
    print(build(Path(sys.argv[1]), sys.stdin.read()), end='')
