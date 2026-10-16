"""TASK 3A unit + actual local browser checks; no provider/worker operations."""
from dataclasses import replace
import json
from pathlib import Path
import pytest
from layout_rebuilder import (RebuildProfile, STATUS, build_content, preview_html,
                              PAGINATE, render, Tree)
from translation_evidence import structured_math, file_hash

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tests/fixtures/layout_task2g_page114.json'
DATASET=ROOT/'output/task2g-live-resume-20261010-192802/capture/capture-50a0ac2d28e3424c9f8a40befdcab1c1/dataset/dataset.json'

def formula(latex='x^2',display=False,native=True):
    tag='div' if display else 'span'
    body='<math'+(' display="block"' if display else '')+'><semantics><msup><mi>x</mi><mn>2</mn></msup><annotation encoding="application/x-tex">'+latex+'</annotation></semantics></math>' if native else ''
    return '<'+tag+' data-d-component="math"><span class="katex'+('-display' if display else '')+'">'+body+'<span class="katex-html">DUPLICATE_VISUAL</span></span></'+tag+'>'

def candidate(html):
    # The annotation inventory is explicit, never inferred from raw DOM text.
    root=Tree(html).root
    formulas=[{'representation':'latex_annotation','raw':n.text()} for n in root.walk() if n.tag=='annotation']
    return {'html':html,'formulas':formulas}

@pytest.fixture
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True)
        yield b
        b.close()

def paginate(browser,html,profile):
    context=browser.new_context(offline=True,viewport={'width':800,'height':1000})
    attempts=[]
    context.route('**/*',lambda route:(attempts.append(route.request.url),route.abort()))
    page=context.new_page();page.set_content(preview_html(html,profile,profile.dimensions((600,800))))
    data=page.evaluate(PAGINATE,vars(profile));result=page.content();context.close()
    assert attempts==[]
    return data,result

def test_vietnamese_inline_display_and_exact_latex(browser):
    c=candidate('<h2>HÌNH HỌC PHẲNG</h2><p>Điều kiện đủ: đường tròn '+formula()+' tiếp tuyến.</p>'+formula('x^{2}',True))
    markup,rows,_=build_content(c)
    data,html=paginate(browser,markup,replace(RebuildProfile(),width=600,body_size=22,top=90,bottom=80,inner=60,outer=40))
    assert data['content_text']=='HÌNH HỌC PHẲNGĐiều kiện đủ: đường tròn  tiếp tuyến.'
    assert [r['latex'] for r in rows]==['x^2','x^{2}']
    assert [r['display'] for r in rows]==[False,True]
    assert len(data['formula'])==2 and all(r['has_math'] and not r['clipped'] for r in data['formula'])
    assert 'DUPLICATE_VISUAL' not in html and '<annotation' not in html
    assert not any(r['verified'] for r in rows)

def test_missing_math_is_placeholder():
    markup,rows,_=build_content(candidate('<p>Không đoán: '+formula(native=False)+'</p>'))
    assert rows[0]['status']=='PLACEHOLDER' and '[MATH_UNRESOLVED]' in markup

def test_unknown_mathml_is_placeholder():
    c=candidate(formula().replace('<msup>','<unsupported>').replace('</msup>','</unsupported>'))
    markup,rows,_=build_content(c)
    assert rows[0]['status']=='PLACEHOLDER' and 'x^2' in markup

def test_missing_evidence():
    with pytest.raises(ValueError):build_content({'html':None})

@pytest.mark.parametrize('raw',['<p>broken','<script>alert(1)</script>','<img src="https://chatgpt.com/image">'])
def test_reject_unsafe_or_malformed(raw):
    with pytest.raises(ValueError):build_content(candidate(raw))

def test_mirrored_and_unknown_number():
    assert RebuildProfile(page_number=114).margins()==(85,110)
    assert RebuildProfile(page_number=115).margins()==(110,85)
    assert RebuildProfile().page_number is None
    assert RebuildProfile().chapter is None

def test_source_aspect_and_explicit_target():
    assert RebuildProfile().dimensions((4056,5639))==(1200,1668)
    assert RebuildProfile(height=1800).dimensions((4056,5639))==(1200,1800)

@pytest.mark.parametrize('kw',[{'body_size':0},{'width':0},{'height':-1},{'font':"bad';url(x)"},{'page_number':True}])
def test_invalid_profile(kw):
    with pytest.raises(ValueError):RebuildProfile(**kw)

def test_overflow_continuation_without_text_loss(browser):
    profile=RebuildProfile(width=600,height=800,inner=60,outer=40,top=100,bottom=80,body_size=25)
    text='Tiếng Việt: đường tròn và tiếp tuyến. '
    content=''.join('<p>'+text*8+'</p>' for _ in range(8))
    metrics,html=paginate(browser,content,profile)
    assert metrics['page_count']>1
    assert metrics['content_text']==text*64
    assert metrics['typography']['font_size']=='25px'
    assert STATUS in html

def test_oversized_block_retains_tail(browser):
    profile=RebuildProfile(width=600,height=800,inner=60,outer=40,top=100,bottom=80)
    content='<p>'+'Toán học. '*500+'ĐUÔI KHÔNG ĐƯỢC MẤT</p>'
    metrics,html=paginate(browser,content,profile)
    assert metrics['oversized'] and metrics['content_text'].endswith('ĐUÔI KHÔNG ĐƯỢC MẤT')
    assert 'oversized' in html

def test_formula_clip_detected(browser):
    profile=RebuildProfile(width=600,height=800,inner=60,outer=40,top=100,bottom=80)
    markup,_,_=build_content(candidate(formula().replace('<mi>x</mi>','<mi>'+'x'*200+'</mi>')))
    metrics,_=paginate(browser,markup,profile)
    assert any(i['type']=='MATH_CLIP' for i in metrics['issues'])

def test_real_114_integrity_geometry_and_offline(tmp_path):
    if not DATASET.exists():pytest.skip('Real persisted capture not present')
    before={p:file_hash(p) for p in (DATASET,FIXTURE)}
    out=tmp_path/'pilot'
    report=render(DATASET,FIXTURE,out)
    assert report['math']['total']==report['math']['rendered_native']==66
    assert report['math']['placeholder_count']==0 and report['math']['latex_unchanged']
    d=json.loads(DATASET.read_text(encoding='utf8'))
    c=d['translation']['capture_audit']['after']['messages'][-1]
    expected=[n['latex_candidate'] for n in structured_math(c['html'],formulas=c['formulas'])['nodes'] if n['kind']=='math']
    assert [n['latex'] for n in report['math']['nodes']]==expected
    assert report['non_math_text_preserved'] and report['renderer']['network_attempts']==[]
    assert report['layout_status']=='OVERFLOW'
    assert report['status']==STATUS and not report['verified'] and not report['eligible_for_final_page']
    assert report['dataset_readiness_unchanged']['status']=='HIGH_RISK_HOLD'
    assert report['unknown_regions'] and len(report['geometry'])==2
    assert all(not g['inserted'] for g in report['geometry'])
    assert all(file_hash(p)==h for p,h in before.items())
    from PIL import Image
    for p in out.glob('rebuilt-preview*.png'):
        with Image.open(p) as im:assert list(im.size)==report['target_size']
    with pytest.raises(FileExistsError):render(DATASET,FIXTURE,out)
    assert '<script' not in (out/'rebuilt-preview.html').read_text(encoding='utf8').lower()

def test_no_production_dependencies():
    # Enforce the intended isolation boundary without touching running workers.
    import ast
    tree=ast.parse((ROOT/'layout_rebuilder.py').read_text(encoding='utf-8-sig'))
    names=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert not any(n.startswith(('desktop','run_chatgpt','books34')) for n in names)
