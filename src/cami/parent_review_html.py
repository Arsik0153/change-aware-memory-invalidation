"""Render already filtered parent packets as inert, portable review pages."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from cami.artifacts import file_hash, within


def escaped(value: object) -> str:
    return html.escape(str(value), quote=True)


def page(title: str, body: str) -> str:
    return ('<!doctype html><html lang="ru"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" '
            'content="default-src \'none\'; style-src \'unsafe-inline\'">'
            f'<title>{escaped(title)}</title><style>'
            'body{font:17px/1.5 system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;'
            'color:#18212b;background:#fff}pre{overflow:auto;padding:1rem;background:#f3f5f7;'
            'font-size:14px}article{border-top:2px solid #bbb;margin-top:2rem;padding-top:1rem}'
            'a{color:#075ca8}code{overflow-wrap:anywhere}.line{display:block;white-space:pre}'
            '.line:target{background:#fff0a0}.number{display:inline-block;min-width:5ch;'
            'color:#555;text-decoration:none;user-select:none}dt{font-weight:bold}'
            '</style><body>' + body + '</body></html>')


def render(output: Path, packets: list[dict[str, Any]], secondary: list[dict[str, Any]],
           sources: dict[str, Path]) -> None:
    """Read copied evidence only; never load the unfiltered annotation package."""
    views = output / 'review-assets'
    views.mkdir()
    links = {}
    for relative in sorted(sources):
        source = within(output, relative)
        sha = file_hash(source)
        view = f'review-assets/{sha}.html'
        links[relative] = view
        # Display only: original bytes remain the authoritative evidence.
        text = source.read_bytes().decode('utf-8', errors='replace')
        lines = ''.join(f'<span class="line" id="L{i}"><a class="number" href="#L{i}">'
                        f'{i}</a>{escaped(line)}</span>'
                        for i, line in enumerate(text.splitlines(), 1))
        (output / view).write_text(page('Parent evidence',
            '<p><a href="../review.html">К заданиям</a></p>'
            f'<p>SHA-256: <code>{sha}</code></p>'
            '<p>Отображение UTF-8 с заменой недекодируемых байтов. '
            'Для проверки используйте исходный файл по ссылке в задании. '
            'Номера строк — навигация, не идентичность символа.</p>'
            f'<pre>{lines}</pre>'), encoding='utf-8')

    second = {(row['claim_id'], row['commit']) for row in secondary}
    body = ['<h1>Независимый parent-review</h1>',
            f'<p>Заданий: {len(packets)}. Назначений второму разметчику: {len(second)}.</p>',
            '<p>Это кандидаты, а не подтверждённые факты. Страница не исполняет probes '
            'и не создаёт ответы. Для behavior требуется отдельная проверка в изоляции.</p>',
            '<p>Первый разметчик заполняет <a href="primary_form.jsonl">primary_form.jsonl</a>; '
            'второй независимо заполняет <a href="second_form.jsonl">second_form.jsonl</a>. '
            'Поиск по claim_id: Ctrl+F. Исходные записи: '
            '<a href="packets.jsonl">packets.jsonl</a>.</p>']
    for index, packet in enumerate(packets, 1):
        claim = packet['claim']
        parent = packet['parent_commit']
        assignment = 'Да' if (claim['claim_id'], parent) in second else 'Нет'
        body.append(f'<article id="claim-{index}"><h2>{index}. {escaped(claim["text"])}</h2>'
                    f'<dl><dt>claim_id</dt><dd><code>{escaped(claim["claim_id"])}</code></dd>'
                    f'<dt>Repository</dt><dd>{escaped(packet["repo_id"])}</dd>'
                    f'<dt>Parent</dt><dd><code>{escaped(parent)}</code></dd>'
                    f'<dt>Второй разметчик назначен</dt><dd>{assignment}</dd></dl>'
                    '<h3>Полное утверждение (включая scope и predicate)</h3>'
                    f'<pre>{escaped(json.dumps(claim, ensure_ascii=False, indent=2))}</pre>'
                    '<h3>Parent evidence</h3><ul>')
        for entry in packet['source_evidence'][parent]:
            relative = entry['evidence_path']
            body.append(f'<li>{escaped(entry["path"])}: ')
            if relative is not None:
                body.append(f'<a href="{links[relative]}">исходник с номерами строк</a>; '
                            f'<a href="{quote(relative, safe="/")}">исходные байты</a>; '
                            f'SHA-256 <code>{escaped(entry["sha256"])}</code>')
            else:
                body.append('исходник отсутствует')
            if entry['limitation']:
                body.append(f' — ограничение: {escaped(entry["limitation"])}')
            body.append('</li>')
        body.append('</ul>')
        probe = packet['probe']
        if probe:
            relative = probe['path']
            body.append(f'<h3>Frozen probe</h3><p>Node ID: <code>{escaped(probe["node_id"])}</code>; '
                        f'<a href="{links[relative]}">код</a>; '
                        f'<a href="{quote(relative, safe="/")}">исходные байты</a>; '
                        f'SHA-256 <code>{escaped(probe["sha256"])}</code></p>')
        body.append('</article>')
    (output / 'review.html').write_text(page('Parent review', ''.join(body)), encoding='utf-8')
