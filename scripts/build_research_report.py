"""Build the dated research progress report as portable Markdown, DOCX and PDF.

Use the separate environment pinned in requirements/report.txt. Requires local
LibreOffice and pdftotext; never overwrites an existing output directory.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from markdown_it import MarkdownIt

from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = [
    'structural-stress-v1/results.json', 'structural-stress-v1/independent-review.json',
    'bootstrap-study-v1/summary.json', 'bootstrap-study-v1/protocol.json',
    'bootstrap-availability-v1/results.json', 'paired-support-v2/results.json',
    'paired-support-v2/audit.json', 'paired-support-v1/independent-review.json',
    'metric-denominators-v2/summary.json', 'metric-denominators-v2/independent-review.json',
    'product-watch-v2/audit.json', 'product-watch-v2/independent-review.json',
    'product-memory-real/audit.json', 'product-memory-typescript-v2/artifact-audit.json',
    'provenance-restoration-v1/summary.json', 'parent-functions-v2/audit.json',
    'parent-function-results-review.json', 'parent-function-full-verification/checks.json',
    'parent-function-full-verification/pytest.log', 'metric-denominators-focused.log',
]
HEADER = 'CAMI · Предварительные результаты'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def styles(document):
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(1.8)
    section.left_margin = section.right_margin = Cm(1.75)
    section.header_distance = section.footer_distance = Cm(.8)
    for name, size in [('Normal',11),('Title',22),('Heading 1',15),('Heading 2',12),
                       ('List Bullet',11),('List Number',11)]:
        style = document.styles[name]
        style.font.name = 'Liberation Serif'
        style.font.size = Pt(size)
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.line_spacing = 1.12
        if name in ('Title','Heading 1','Heading 2'):
            style.font.color.rgb = RGBColor.from_string('17324D')
            style.paragraph_format.keep_with_next = True
    paragraph = section.header.paragraphs[0]
    paragraph.text = HEADER
    paragraph.style = document.styles['Normal']
    for run in paragraph.runs:
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor.from_string('607080')
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer.add_run('Стр. ').font.size = Pt(9)
    field = OxmlElement('w:fldSimple')
    field.set(qn('w:instr'), 'PAGE')
    footer._p.append(field)
    lang = OxmlElement('w:lang')
    lang.set(qn('w:val'), 'ru-RU')
    document.styles['Normal']._element.get_or_add_rPr().append(lang)
    document.core_properties.title = 'CAMI: предварительные научные результаты'
    document.core_properties.subject = 'Development evidence and limits of the thesis conclusions'
    document.core_properties.author = 'CAMI research project'


def inline(paragraph, children, *, size=None):
    bold = italic = False
    for token in children or []:
        if token.type in ('strong_open','strong_close'):
            bold = token.type == 'strong_open'
        elif token.type in ('em_open','em_close'):
            italic = token.type == 'em_open'
        elif token.type in ('text','code_inline','softbreak'):
            run = paragraph.add_run(' ' if token.type == 'softbreak' else token.content)
            run.bold, run.italic = bold, italic
            if size is not None:
                run.font.size = Pt(size)
            if token.type == 'code_inline':
                run.font.name = 'Liberation Mono'
                run.font.size = Pt(8.5 if size is None else min(size,8.5))
        else:
            raise ValueError(f'Unsupported report inline token: {token.type}')


def build(source: Path, out: Path, spec_path: Path | None = None):
    source, out = source.resolve(), out.resolve()
    spec = json.loads(spec_path.read_text()) if spec_path else {
        'artifact_stem': 'CAMI_research_progress_2026-10-29',
        'evidence_root': 'reports/research-20261029', 'evidence': EVIDENCE,
        'evidence_cutoff': '4e13583', 'full_suite_head': '44c77d3',
    }
    stem = spec['artifact_stem']
    if not re.fullmatch(r'[A-Za-z0-9_-]+', stem):
        raise ValueError('Artifact stem must be a plain filename without extension')
    evidence_root = (ROOT / spec['evidence_root']).resolve()
    if not evidence_root.is_relative_to(ROOT / 'reports'):
        raise ValueError('Evidence must come from the project reports directory')
    evidence_paths = {}
    for name in spec['evidence']:
        path = (evidence_root / name).resolve()
        if not path.is_relative_to(evidence_root) or not path.is_file():
            raise ValueError('Evidence paths must be existing files inside evidence_root')
        evidence_paths[name] = path
    evidence_hashes = {name: sha(path) for name, path in evidence_paths.items()}
    spec_hash = sha(spec_path) if spec_path else None
    if out.exists() or out.is_relative_to(ROOT / 'docs'):
        raise ValueError('Output must be a new directory outside source documentation')
    before = source_snapshot(ROOT)
    if before['source_status']:
        raise ValueError('Commit the report builder before building the artifact')
    original = source.read_text()
    tokens = MarkdownIt('commonmark').enable('table').parse(original)
    out.mkdir(parents=True)
    (out / 'assets').mkdir()
    document = Document()
    styles(document)
    expected_text = []
    images = {}
    manifest = {'status':'building','source_path':str(source.relative_to(ROOT)),
                'source_sha256':sha(source),'source_before':before,
                'python':sys.version,'packages':{p:version(p) for p in
                    ('python-docx','markdown-it-py','mdurl','lxml','typing-extensions')},
                'evidence_cutoff':spec['evidence_cutoff'],'source_images':images,
                'report_spec':spec,'report_spec_sha256':spec_hash}
    write(out / 'manifest.json', manifest)
    index, list_style, pending_style = 0, None, None
    try:
        while index < len(tokens):
            token = tokens[index]
            if token.type == 'table_open':
                rows, row = [], None
                index += 1
                while tokens[index].type != 'table_close':
                    item = tokens[index]
                    if item.type == 'tr_open':
                        row = []
                    elif item.type == 'inline':
                        assert row is not None
                        row.append(item.children)
                    elif item.type == 'tr_close':
                        rows.append(row)
                    index += 1
                table = document.add_table(rows=0, cols=len(rows[0]))
                table.style = 'Light Shading Accent 1'
                for number, cells in enumerate(rows):
                    cells_out = table.add_row().cells
                    properties = cells_out[0]._tc.getparent().get_or_add_trPr()
                    properties.append(OxmlElement('w:cantSplit'))
                    if number == 0:
                        properties.append(OxmlElement('w:tblHeader'))
                    for col, children in enumerate(cells):
                        paragraph = cells_out[col].paragraphs[0]
                        paragraph.paragraph_format.space_after = Pt(4)
                        inline(paragraph,children,size=9.5)
                        expected_text.append(paragraph.text)
                        if number == 0:
                            for run in paragraph.runs:
                                run.bold = True
                document.add_paragraph().paragraph_format.space_after = Pt(2)
            elif token.type == 'heading_open':
                level = int(token.tag[1:])
                pending_style = 'Title' if level == 1 else f'Heading {level-1}'
            elif token.type == 'paragraph_open':
                pending_style = list_style or 'Normal'
            elif token.type == 'inline':
                children = token.children or []
                if len(children) == 1 and children[0].type == 'image':
                    image = children[0]
                    path = (source.parent / image.attrGet('src')).resolve()
                    if not path.is_relative_to(ROOT) or not path.is_file():
                        raise ValueError('Report figures must be existing local project files')
                    destination = out / 'assets' / path.name
                    if destination.exists():
                        raise ValueError('Duplicate report image basename')
                    shutil.copyfile(path,destination)
                    images[str(path.relative_to(ROOT))] = {'sha256':sha(path),'packaged':str(destination.relative_to(out))}
                    paragraph = document.add_paragraph()
                    paragraph.paragraph_format.keep_with_next = True
                    paragraph.add_run().add_picture(str(destination),width=Cm(17.5))
                else:
                    paragraph = document.add_paragraph(style=pending_style)
                    inline(paragraph,children)
                    expected_text.append(paragraph.text)
                pending_style = None
            elif token.type == 'fence':
                paragraph = document.add_paragraph()
                paragraph.paragraph_format.line_spacing = 1
                run = paragraph.add_run(token.content.rstrip())
                run.font.name, run.font.size = 'Liberation Mono', Pt(9)
                expected_text.append(paragraph.text)
            elif token.type == 'hr':
                document.add_page_break()
            elif token.type in ('bullet_list_open','ordered_list_open'):
                list_style = 'List Bullet' if token.type == 'bullet_list_open' else 'List Number'
            elif token.type in ('bullet_list_close','ordered_list_close'):
                list_style = None
            elif token.type not in ('heading_close','paragraph_close','list_item_open','list_item_close'):
                raise ValueError(f'Unsupported report block token: {token.type}')
            index += 1
        docx_path = out / (stem + '.docx')
        document.save(docx_path)
        packaged_markdown = original
        for name, data in images.items():
            relative = Path(name).relative_to('reports').as_posix()
            packaged_markdown = packaged_markdown.replace('../reports/' + relative, data['packaged'])
        (out / 'report.md').write_text(packaged_markdown)
        (out / 'source-original.md').write_text(original)
        for name, evidence in evidence_paths.items():
            destination = out / 'evidence' / name
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(evidence,destination)
        manifest['evidence_sources'] = evidence_hashes
        manifest['libreoffice_version'] = subprocess.check_output(['libreoffice','--version'],text=True).strip()
        with tempfile.TemporaryDirectory(prefix='cami-report-lo-') as directory:
            result = subprocess.run(['libreoffice','-env:UserInstallation='+Path(directory).as_uri(),
                '--headless','--convert-to','pdf:writer_pdf_Export','--outdir',str(out),str(docx_path)],
                capture_output=True,timeout=120)
        (out / 'conversion.stdout.log').write_bytes(result.stdout)
        (out / 'conversion.stderr.log').write_bytes(result.stderr)
        assert result.returncode == 0
        pdf = docx_path.with_suffix('.pdf')
        assert pdf.is_file() and pdf.stat().st_size > 1000
        subprocess.run(['pdftotext','-layout',str(pdf),str(out/'extracted.txt')],check=True,timeout=30)
        # Layout mode interleaves lines from adjacent, wrapped table cells.
        # Content-stream order preserves each cell for semantic text comparison.
        subprocess.run(['pdftotext','-raw',str(pdf),str(out/'extracted-raw.txt')],check=True,timeout=30)
        extracted = (out/'extracted-raw.txt').read_text()
        cleaned = '\n'.join(line for line in extracted.splitlines()
                            if line.strip() != HEADER and not re.match(r'^\s*Стр\.\s*\d+\s*$',line))
        def normalize(value):
            return re.sub(r'\s+','',unicodedata.normalize('NFKC',value))
        joined = normalize(cleaned)
        missing = [text for text in expected_text if normalize(text) not in joined]
        write(out/'text-check.json',{'extraction_mode':'raw','layout_extraction':'extracted.txt',
                                    'paragraphs_and_cells':len(expected_text),'missing':missing,
                                    'status':'passed' if not missing else 'failed'})
        assert not missing, f'{len(missing)} text blocks missing from PDF extraction'
        manifest.update(status='rendered_pending_visual_review',text_blocks_checked=len(expected_text),
                        source_after=source_snapshot(ROOT))
        assert manifest['source_after'] == before
        assert sha(source) == manifest['source_sha256']
        assert all(sha(path) == evidence_hashes[name] for name, path in evidence_paths.items())
        assert spec_path is None or sha(spec_path) == spec_hash
        assert subprocess.run(['git','-C',str(ROOT),'diff','--quiet',spec['full_suite_head'],
                               'HEAD','--','src','schemas']).returncode == 0
        manifest['production_and_schemas_unchanged_since_full_suite'] = spec['full_suite_head']
    except Exception as exc:
        manifest.update(status='failed',failure={'type':type(exc).__name__,'message':str(exc)})
        raise
    finally:
        manifest['artifact_hashes'] = {p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*'))
                                       if p.is_file() and p.name != 'manifest.json'}
        write(out / 'manifest.json',manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'docs/research_progress_report_2026-10-29_ru.md')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--spec',type=Path,help='Dated artifact name and evidence inventory JSON')
    args = parser.parse_args()
    build(args.source,args.out,args.spec)
