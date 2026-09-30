from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import re
from zipfile import ZipFile
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / 'templates/submission/official_notice_and_template.docx'
OUT = ROOT / 'output/submission'
CHECKS = ROOT / 'docs/verification/submission'
SCRATCH = ROOT / 'tmp/submission'
SOURCE = ROOT / 'research_proposal.md'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}

def el(name, **attrs):
    node = etree.Element(f'{{{W}}}{name}')
    for key, value in attrs.items():
        node.set(f'{{{W}}}{key}', str(value))
    return node

with ZipFile(REF) as z:
    parts = {i.filename: z.read(i.filename) for i in z.infolist()}
root = etree.fromstring(parts['word/document.xml'])
body = root.find('w:body', NS)
form = body.findall('w:tbl', NS)[1]
cell = form.find('w:tr/w:tc', NS)
patterns = cell.findall('w:p', NS)
section = deepcopy(body.find('w:sectPr', NS))
form = deepcopy(form)
cell = form.find('w:tr/w:tc', NS)
for node in list(cell):
    if node.tag != f'{{{W}}}tcPr':
        cell.remove(node)
props = cell.find('w:tcPr', NS)
props.find('w:vAlign', NS).set(f'{{{W}}}val', 'top')
for edge in props.findall('w:tcMar/*', NS):
    edge.set(f'{{{W}}}w', '100')
for h in form.findall('w:tr/w:trPr/w:trHeight', NS):
    h.getparent().remove(h)

def paragraph(text, kind='body'):
    index = {'title': 0, 'meta': 2, 'h2': 6, 'h3': 12, 'body': 6, 'ref': 6}[kind]
    p = deepcopy(patterns[index])
    for child in list(p):
        if child.tag != f'{{{W}}}pPr':
            p.remove(child)
    pp = p.find('w:pPr', NS)
    for child in list(pp):
        if child.tag in {f'{{{W}}}rPr', f'{{{W}}}pStyle'}:
            pp.remove(child)
    if kind == 'title':
        pp.insert(0, el('pStyle', val='Title'))
    spacing = pp.find('w:spacing', NS)
    if spacing is None:
        spacing = el('spacing'); pp.append(spacing)
    spacing.set(f'{{{W}}}line', '384')
    spacing.set(f'{{{W}}}lineRule', 'auto')
    spacing.set(f'{{{W}}}after', '100' if kind in {'body','ref'} else '80')
    if kind in {'h2','h3'}:
        spacing.set(f'{{{W}}}before', '140')
    pp.append(el('widowControl'))
    if kind in {'title','h2','h3','meta','ref'}:
        pp.append(el('keepLines'))
    if kind in {'title','h2','h3'}:
        pp.append(el('keepNext'))
    if kind in {'h2','h3'}:
        pp.append(el('outlineLvl', val='0' if kind=='h2' else '1'))
    jc = pp.find('w:jc', NS)
    if kind != 'title':
        if jc is None:
            jc = el('jc'); pp.append(jc)
        jc.set(f'{{{W}}}val','left')
    run = el('r')
    rp = el('rPr')
    rp.append(el('rFonts', ascii='Times New Roman', hAnsi='Times New Roman', eastAsia='Apple SD Gothic Neo', cs='Times New Roman'))
    rp.append(el('sz', val='40' if kind=='title' else '26'))
    rp.append(el('szCs', val='40' if kind=='title' else '26'))
    rp.append(el('color', val='000000'))
    if kind in {'title','h2','h3'}:
        rp.append(el('b'))
    rp.append(el('lang', val='en-US', eastAsia='ko-KR'))
    run.append(rp)
    t = el('t'); t.text = text
    t.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
    run.append(t); p.append(run)
    return p

blocks = SOURCE.read_text().strip().split('\n\n')
plain_blocks=[]
in_refs=False
for block in blocks:
    if block.startswith('# '):
        kind='title'; text=block[2:]
    elif block.startswith('## '):
        kind='h2'; text=block[3:]; in_refs = text=='References'
    elif block.startswith('### '):
        kind='h3'; text=block[4:]
    elif block.startswith(('Title:', 'Korean title:', 'Researcher:', 'Academic advisor:')):
        kind='meta'; text=block
    else:
        kind='ref' if in_refs else 'body'; text=block
    cell.append(paragraph(text,kind)); plain_blocks.append(text)
    if block.startswith('Academic advisor:'):
        for line in ['Advisor confirmation: 김진대   Signature: ______________', 'Department head: 강동완   Signature: ______________', 'Approval date: __________________']:
            cell.append(paragraph(line,'meta'))
            plain_blocks.append(line)
paragraphs = list(cell.findall('w:p', NS))
page_starts = [
    "Anand's recent preprint",
    '2-2. Change analysis',
    '2-3. Dataset',
    'Primary measures',
    '3. Research Schedule',
    'References',
]
pages = [[]]
for p in paragraphs:
    txt = ''.join(p.xpath('.//w:t/text()', namespaces=NS))
    if any(txt.startswith(prefix) for prefix in page_starts):
        pages.append([])
    pages[-1].append(p)
for child in list(body):
    body.remove(child)
for page_index, page_paragraphs in enumerate(pages):
    if page_index:
        brp = el('p'); brp.append(el('pPr'))
        brp.find('w:pPr', NS).append(el('spacing', before='0', after='0', line='20', lineRule='exact'))
        rr=el('r'); rr.append(el('br', type='page')); brp.append(rr)
        body.append(brp)
    page_form = deepcopy(form)
    page_cell = page_form.find('w:tr/w:tc', NS)
    for node in list(page_cell):
        if node.tag != f'{{{W}}}tcPr': page_cell.remove(node)
    for p in page_paragraphs: page_cell.append(p)
    body.append(page_form)
body.append(el('p'))
body.append(section)
parts['word/document.xml'] = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
core = etree.fromstring(parts['docProps/core.xml'])
for tag,value in [('{http://purl.org/dc/elements/1.1/}creator','Sairanbekov Zhanarys'),('{http://purl.org/dc/elements/1.1/}title','Thesis research plan'),('{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}lastModifiedBy','Sairanbekov Zhanarys')]:
    node=core.find(tag)
    if node is None: node=etree.SubElement(core,tag)
    node.text=value
parts['docProps/core.xml']=etree.tostring(core,xml_declaration=True,encoding='UTF-8',standalone=True)
OUT.mkdir(parents=True,exist_ok=True)
final=OUT/'thesis_research_plan.docx'
with ZipFile(REF) as zin, ZipFile(final,'w') as zout:
    for info in zin.infolist():
        zout.writestr(info,parts[info.filename])
with ZipFile(REF) as a, ZipFile(final) as b:
    altered=[name for name in a.namelist() if a.read(name)!=b.read(name)]
assert set(altered)=={'word/document.xml','docProps/core.xml'},altered
assert etree.tostring(section)==etree.tostring(etree.fromstring(parts['word/document.xml']).find('w:body/w:sectPr',NS))
expected_refs=set(re.findall(r'^\[(\d+)\]', SOURCE.read_text(), re.M))
cited_refs=set(re.findall(r'\[(\d+)\]', SOURCE.read_text().split('## References')[0]))
assert expected_refs==cited_refs==set('123456')
text='\n\n'.join(plain_blocks)
assert '............................' not in text
assert all(s in text for s in ['1. Purpose and Motivation','2. Content and Methods','3. Research Schedule','References','Sairanbekov Zhanarys','김진대','강동완'])
SCRATCH.mkdir(parents=True, exist_ok=True)
CHECKS.mkdir(parents=True, exist_ok=True)
(SCRATCH/'expected_text.txt').write_text(text)
(CHECKS/'build_checks.json').write_text(json.dumps({'reference_sha256':sha256(REF.read_bytes()).hexdigest(),'source_sha256':sha256(SOURCE.read_bytes()).hexdigest(),'docx_sha256':sha256(final.read_bytes()).hexdigest(),'changed_package_parts':altered,'reference_count':len(expected_refs),'word_count':len(text.split()),'source_to_docx_blocks':len(plain_blocks)},indent=2))
print(final)
print('Words:',len(text.split()),'Changed package parts:',altered)
