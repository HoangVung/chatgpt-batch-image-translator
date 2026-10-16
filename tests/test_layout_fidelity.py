"""TASK 3B local browser fidelity and pagination tests, no provider/worker."""
from dataclasses import replace
import json
from pathlib import Path
import pytest
from layout_rebuilder import RebuildProfile, Tree, build_content
from layout_calibration import run_layout, totals, math_integrity, choose_trial, load_inputs, calibrate
from translation_evidence import file_hash

ROOT=Path(__file__).resolve().parents[1]
DATASET=ROOT/'output/task2g-live-resume-20261010-192802/capture/capture-50a0ac2d28e3424c9f8a40befdcab1c1/dataset/dataset.json'
FIXTURE=ROOT/'tests/fixtures/layout_task2g_page114.json'
BASELINE=ROOT/'output/task3a-page114-20261010-final'

@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(offline=True,viewport={'width':800,'height':1000})
        attempts=[]
        context.route('**/*',lambda r:(attempts.append(r.request.url),r.abort()))
        page=context.new_page()
        yield page
        assert attempts==[]
        browser.close()

PROFILE=RebuildProfile(width=600,height=800,inner=60,outer=40,top=100,bottom=80,body_size=24,line_height=1.25,paragraph_gap=6,math_gap=6)

def candidate(html):
    root=Tree(html).root
    return {'html':html,'formulas':[{'representation':'latex_annotation','raw':n.text()} for n in root.walk() if n.tag=='annotation']}

def expression():
    # Two-row display formula, with fraction and superscript present.
    return '<div data-d-component="math"><math display="block"><semantics><mtable><mtr><mtd><mfrac><mi>x</mi><mn>2</mn></mfrac></mtd></mtr><mtr><mtd><msup><mi>x</mi><mn>2</mn></msup></mtd></mtr></mtable><annotation encoding="application/x-tex">\\frac{x}{2}\\\\x^2</annotation></semantics></math><span class="katex-html">DUPLICATE</span></div>'

def test_heading_never_orphan_at_page_end(page):
    content='<p>'+('Tiếng Việt. '*90)+'</p><h2>TIÊU ĐỀ PHẦN</h2><p>Đoạn theo sau luôn đi cùng tiêu đề.</p>'
    metrics,measure=run_layout(page,content,PROFILE,(600,800))
    assert metrics['page_count']>1
    headings=[h for p in measure['pages'] for h in p['headings']]
    assert headings and all(h['grouped'] and not h['orphan'] for h in headings)
    assert 'Đoạn theo sau' in metrics['content_text']

def test_multiline_atomic_and_tree_integrity(page):
    content,rows,structure=build_content(candidate('<p>Ta có</p>'+expression()))
    metrics,measure=run_layout(page,content,PROFILE,(600,800))
    integrity=math_integrity(structure,rows,measure)
    assert integrity['technical_preserved']==1 and integrity['limited_checks_passed']==1
    assert integrity['nodes'][0]['structure_counts']['mtr']==2
    assert integrity['nodes'][0]['structure_counts']['mfrac']==1
    assert integrity['nodes'][0]['structure_counts']['msup']==1
    assert not metrics['issues'] and not any(p['overlaps'] for p in measure['pages'])
    assert page.locator('.keep-group .display').count()==1
    assert page.locator('.formula').count()==1 and 'DUPLICATE' not in page.content()
    assert integrity['uncertain_comparison_nodes']==[0]

@pytest.mark.parametrize('change',['latex','mathml','duplicate'])
def test_integrity_detects_exact_mutation(page,change):
    content,rows,structure=build_content(candidate(expression()))
    _,measure=run_layout(page,content,PROFILE,(600,800))
    if change=='latex':rows[0]['latex']='x^3'
    if change=='mathml':measure['maths'][0]['mathml']=measure['maths'][0]['mathml'].replace('<mn>2</mn>','<mn>3</mn>')
    if change=='duplicate':measure['maths'].append(dict(measure['maths'][0]))
    report=math_integrity(structure,rows,measure)
    assert report['technical_preserved']==0
    assert not report['nodes'][0]['semantic_verified']

def test_latex_count_mismatch_does_not_become_semantic_verified(page):
    c=candidate(expression().replace('x^2</annotation>','x^2+x^3</annotation>'))
    content,rows,structure=build_content(c);_,measure=run_layout(page,content,PROFILE,(600,800))
    report=math_integrity(structure,rows,measure)
    assert report['technical_preserved']==1 and report['limited_checks_passed']==0
    assert report['nodes'][0]['latex_mathml_equivalence']=='NOT_PROVEN'

def test_overflow_fixed_font_preserved_all_text(page):
    text='Nội dung tiếng Việt có dấu. '
    content=''.join('<p>'+text*12+'</p>' for _ in range(9))
    metrics,measure=run_layout(page,content,PROFILE,(600,800))
    assert metrics['page_count']>1 and metrics['content_text']==text*108
    assert all(p['fonts']['size']=='24px' and p['fonts']['line_height']=='30px' for p in measure['pages'])
    assert not metrics['issues']
    sums=totals(measure)
    assert sum(v for k,v in sums.items() if k!='printable_area')==pytest.approx(sums['printable_area'])

def test_overlong_atomic_block_preserved(page):
    text='Dài nhưng không mất. '*800+'ĐUÔI'
    metrics,_=run_layout(page,'<p>'+text+'</p>',PROFILE,(600,800))
    assert metrics['oversized'] and metrics['content_text']==text

def test_math_overlap_and_clip_detected(page):
    content,_,_=build_content(candidate(expression()+expression()))
    _,measure=run_layout(page,content,PROFILE,(600,800))
    page.locator('math').evaluate_all("nodes=>nodes.forEach(e=>{e.style.position='absolute';e.style.left='0';e.style.top='0';e.style.width='900px'})")
    from layout_calibration import MEASURE
    measure=page.evaluate(MEASURE)
    assert any(issue['type']=='MATH_OVERLAP' for p in measure['pages'] for issue in p['overlaps'])
    # Deliberate overlapping oversized formulas must remain measurable.
    assert measure['pages'][0]['math_rects'][1][2]>measure['pages'][0]['printable_box'][2]


def test_selection_rejects_tiny_or_unsafe_profiles():
    trials=[{'pages':1,'safe':True,'profile':{'body_size':18,'line_height':1.15}}, {'pages':1,'safe':False,'profile':{'body_size':24,'line_height':1.25}}, {'pages':2,'safe':True,'profile':{'body_size':24,'line_height':1.25}}, {'pages':2,'safe':True,'profile':{'body_size':22,'line_height':1.2}}]
    assert choose_trial(trials)['profile']['body_size']==24
    with pytest.raises(ValueError):choose_trial(trials[:2])

def test_real_calibrated_artifact_and_originals():
    p=ROOT/'output/task3b-page114-20261011-final'
    if not p.exists():pytest.skip('Run offline pilot first')
    a=json.loads((p/'pagination-analysis.json').read_text(encoding='utf8'))
    l=json.loads((p/'layout-metrics.json').read_text(encoding='utf8'))
    m=json.loads((p/'math-integrity.json').read_text(encoding='utf8'))
    assert a['before_pages']==3 and a['after_pages']==2
    assert not a['one_page_possible_in_trials'] and a['minimum_trial_text_math_to_one_sheet_ratio']>1
    assert a['math_inventory']['duplicates']==0
    assert a['unknown_regions'] and all(not g['inserted'] and g['pixel_exact'] for g in a['geometry'])
    assert m['technical_preserved']==66 and m['limited_checks_passed']==66
    assert len(m['uncertain_comparison_nodes'])==66
    assert l['network_attempts']==[] and l['content_text_exact'] and l['all_original_hashes_unchanged']
    assert l['dataset_readiness_unchanged']['status']=='HIGH_RISK_HOLD'
    assert all(file_hash(path)==sha for path,sha in l['original_hashes'].items())
    assert all(not p['overlaps'] for p in l['calibrated_measurement']['pages'])
    assert not l['pagination_metrics']['issues']
    from PIL import Image
    for path in p.glob('rebuilt-calibrated*.png'):
        with Image.open(path) as im:assert list(im.size)==l['target_size']
    with pytest.raises(FileExistsError):calibrate(DATASET,FIXTURE,BASELINE,p)
