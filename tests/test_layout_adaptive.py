"""TASK 3G: paragraph boundaries, evidence abstention, measured placement/integrity."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from layout_paragraphs import reconstruct, align_paragraphs
from layout_adaptive import solve, intersects, make_units, render_adaptive, POST_MEASURE
from layout_rebuilder import Tree, RebuildProfile

H='a'*64
ROOT=Path(__file__).resolve().parents[1]
FINAL=ROOT/'output/task3g-page114-20261011-release-diagnostic'


def line(i,text='中文段落内容',box=(10,10,200,30),kind='text_candidate'):
    return {'id':f'ocr:line:{i}','text':text,'bbox':list(box),'confidence':.95,
            'source_image_sha256':H,'page_identifier':'114','classification':kind,
            'extraction_method':'SAVED_TEST_OCR','region_reference':'region:test'}


def block(i,text='中文段落内容',math=()):
    return {'id':f'src:block:{i}','non_math_text':text,'math_indices':list(math),'tag':'p'}


def test_aligned_lines_merge_preserve_raw():
    boxes=[line(0),line(1,box=(10,34,195,54))];original=deepcopy(boxes)
    r=reconstruct(boxes,H)
    assert len(r['paragraphs'])==1 and r['paragraphs'][0]['source_line_ids']==['ocr:line:0','ocr:line:1']
    assert boxes==original==r['source_lines'] and r['all_lines_preserved']
    assert r['paragraphs'][0]['verification_status']=='PARAGRAPH_CANDIDATE'
    assert not r['paragraphs'][0]['reading_order_verified']
    assert r['paragraphs'][0]['evidence']['line_evidence'][0]['region_reference']=='region:test'


def test_indent_return_allowed_new_indent_boundary():
    r=reconstruct([line(0,box=(40,10,200,30)),line(1,box=(10,34,200,54)),line(2,box=(50,58,200,78))],H)
    assert [len(p['source_line_ids']) for p in r['paragraphs']]==[2,1]


def test_columns_remain_independent():
    boxes=[line(0,box=(10,10,150,30)),line(1,box=(200,10,350,30)),
           line(2,box=(10,34,150,54)),line(3,box=(200,34,350,54))]
    r=reconstruct(boxes,H)
    assert [p['source_line_ids'] for p in r['paragraphs']]==[['ocr:line:0','ocr:line:2'],['ocr:line:1','ocr:line:3']]


@pytest.mark.parametrize('text,kind,expected',[('平面几何','text_candidate','HEADING'),('图3-52','caption_candidate','CAPTION'),
    ('x=y','math_candidate','MATH_CANDIDATE'),('Q','unknown','UNKNOWN')])
def test_isolated_roles_not_merged(text,kind,expected):
    r=reconstruct([line(0),line(1,text,(10,34,200,54),kind),line(2,box=(10,58,200,78))],H)
    assert len(r['paragraphs'])==3 and r['paragraphs'][1]['region_type']==expected


@pytest.mark.parametrize('section',['充分性中文段落','必要性中文段落','例8 中文段落','证明 中文段落'])
def test_section_boundaries(section):
    r=reconstruct([line(0),line(1,section,(10,34,200,54))],H)
    assert len(r['paragraphs'])==2


def test_short_chinese_connectors_remain_text():
    r=reconstruct([line(0),line(1,'所以x=y',(10,34,200,54))],H)
    assert len(r['paragraphs'])==1


def test_math_in_gap_blocks_merge():
    r=reconstruct([line(0),line(1,'x=y',(80,31,140,34),'math_candidate'),line(2,box=(10,36,200,56))],H)
    assert len(r['paragraphs'])==3


@pytest.mark.parametrize('box',[(10,60,200,80),(200,34,350,54),(10,34,200,75)])
def test_gap_alignment_height_boundaries(box):
    assert len(reconstruct([line(0),line(1,box=box)],H)['paragraphs'])==2


def test_alternative_lines_abstain():
    r=reconstruct([line(0),line(1,box=(10,34,170,54)),line(2,box=(15,35,180,55))],H)
    assert r['paragraphs'][0]['verification_status']=='PARAGRAPH_AMBIGUOUS'


@pytest.mark.parametrize('change',['hash','duplicate','bbox'])
def test_invalid_ocr_rejected(change):
    boxes=[line(0)]
    if change=='hash':boxes[0]['source_image_sha256']='b'*64
    if change=='duplicate':boxes.append(deepcopy(boxes[0]))
    if change=='bbox':boxes[0]['bbox']=[10,10,0,30]
    with pytest.raises(ValueError):reconstruct(boxes,H)


def test_empty_data_fallback():
    r=reconstruct([],H);a=align_paragraphs(r,[],[],[],{}, {})
    assert r['paragraphs']==[] and a['verified_anchors']==0 and a['status']=='NOT_ANCHORABLE'


def test_paragraph_one_source_many_translation():
    r=reconstruct([line(0)],H)
    vi=[{'id':'vi:block:0','math_indices':[0]},{'id':'vi:block:1','math_indices':[1]}]
    prior=[{'source_text_reference':'src:block:0','translation_block_ids':['vi:block:0','vi:block:1'],'confidence':.7}]
    a=align_paragraphs(r,[block(0,math=[0])],vi,prior,{'links':[]},{'source_image_sha256':H})
    l=a['links'][0]
    assert l['translation_block_ids']==['vi:block:0','vi:block:1'] and l['translation_math_node_ids']==[0,1]
    assert l['verification_status']=='ALIGNED_CANDIDATE' and not l['eligible_for_anchor'] and not l['math_verified']


def test_multiple_source_blocks_one_paragraph_and_target():
    r=reconstruct([line(0,'中文段落内容充分证明条件成立')],H)
    src=[block(0),block(1,'充分证明条件成立')]
    prior=[{'source_text_reference':s['id'],'translation_block_ids':['vi:block:0'],'confidence':.7} for s in src]
    a=align_paragraphs(r,src,[{'id':'vi:block:0','math_indices':[]}],prior,{}, {})
    assert a['links'][0]['source_block_ids']==['src:block:0','src:block:1']
    assert a['links'][0]['translation_block_ids']==['vi:block:0']


def test_many_paragraphs_one_measured_source_block():
    # Section boundary preserves two paragraph regions. Existing measured lexical
    # window still links the CN block jointly, never chooses one exact anchor.
    r=reconstruct([line(0,'中文段落内容'),line(1,'必要性条件成立',(10,34,200,54))],H)
    a=align_paragraphs(r,[block(0,'中文段落内容必要性条件成立')],[{'id':'vi:block:0','math_indices':[]}],
        [{'source_text_reference':'src:block:0','translation_block_ids':['vi:block:0'],'confidence':.7}],{}, {})
    assert all(l['source_block_ids']==['src:block:0'] for l in a['links'])
    assert all(len(l['source_block_paragraph_groups']['src:block:0'])==2 for l in a['links'])
    nodes=Tree('<p>Đủ nội dung</p>').root.children
    units=make_units(nodes,a,(1200,1668))
    assert units[0]['status']=='AMBIGUOUS' and units[0]['paragraph_id'] is None


def test_repeated_lexical_evidence_abstains():
    r=reconstruct([line(0)],H)
    a=align_paragraphs(r,[block(0),block(1)],[],[],{}, {})
    assert a['links'][0]['verification_status']=='AMBIGUOUS'


def test_unmatched_translation_preserved_no_forced_match():
    r=reconstruct([line(0)],H)
    a=align_paragraphs(r,[block(0,'完全不同的内容词汇')],[{'id':'vi:block:0','math_indices':[0]}],[],{}, {})
    assert a['unmatched_translation_block_ids']==['vi:block:0']
    units=make_units(Tree('<p>Nội dung</p>').root.children,a,(1200,1668))
    assert units[0]['block_ids']==['vi:block:0'] and units[0]['status']=='UNMATCHED'


def test_expansion_displaces_following_regions():
    r=solve([{'id':'a','width':500,'height':100,'reference_top':120},
             {'id':'b','width':500,'height':200,'reference_top':130}])
    assert r['placements'][0]['bbox']==[110,120,610,220]
    assert r['placements'][1]['bbox'][1]==226
    assert not intersects(r['placements'][0]['bbox'],r['placements'][1]['bbox'])


def test_pagination_not_font_shrink():
    r=solve([{'id':'a','width':1005,'height':1000},{'id':'b','width':1005,'height':500}])
    assert r['page_count']==2 and r['placements'][1]['bbox'][1]==110
    assert r['placements'][1]['height']==500


@pytest.mark.parametrize('item',[{'id':'a','width':1005,'height':2000},{'id':'a','width':1500,'height':100}])
def test_infeasible_keeps_item(item):
    r=solve([item]);assert r['status']=='LAYOUT_INFEASIBLE' and r['placements'][0]['id']=='a'


@pytest.mark.parametrize('verified',[False,True])
def test_unknown_geometry_not_inserted_verified_obstacle_avoided(verified):
    r=solve([{'id':'a','width':1005,'height':100}],obstacles=[{'bbox':[110,110,1115,210],'verified':verified}])
    assert r['placements'][0]['bbox'][1]==(216 if verified else 110)


def test_unit_grouping_no_duplicate_nonconsecutive_math():
    nodes=Tree('<p><span class="formula" data-math="0"><math><mi>x</mi></math></span></p><p>unmatched</p><p><span class="formula" data-math="1"><math><mi>x</mi></math></span></p>').root.children
    a={'links':[{'verification_status':'ALIGNED_CANDIDATE','translation_block_ids':['vi:block:0','vi:block:2'],
                'paragraph_id':'p:0','source_bbox':[110,110,600,210]}]}
    units=make_units(nodes,a,(1200,1668));joined=''.join(u['html'] for u in units)
    assert len(units)==3 and joined.count('data-math="0"')==joined.count('data-math="1"')==1
    assert [t for u in units for t in u['block_ids']]==['vi:block:0','vi:block:1','vi:block:2']


@pytest.fixture
def offline_page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);context=browser.new_context(offline=True)
        attempts=[];context.route('**/*',lambda route:(attempts.append(route.request.url),route.abort()))
        page=context.new_page();yield page
        browser.close();assert attempts==[]


def profile():return RebuildProfile(body_size=24,title_size=28,line_height=1.25,paragraph_gap=6,math_gap=6,indent=24)


def test_actual_renderer_expansion_and_text_math_collision_free(offline_page):
    html='<p>'+'Nội dung dài có toán '*30+'<span class="formula inline" data-math="0"><math><mi>x</mi></math></span></p>'
    units=[{'id':'unit:0','html':html,'block_ids':['vi:block:0'],'width':300,'left':110,'reference_top':110,'status':'PARAGRAPH_CANDIDATE'},
           {'id':'unit:1','html':'<p>Đoạn tiếp theo</p>','block_ids':['vi:block:1'],'width':300,'left':110,'reference_top':120,'status':'PARAGRAPH_CANDIDATE'}]
    r,m,post=render_adaptive(offline_page,units,profile(),(1200,1668))
    assert post['collisions']==post['overflow']==[] and len(m['maths'])==1
    assert r['placements'][0]['height']>100 and r['placements'][1]['bbox'][1]>r['placements'][0]['bbox'][3]


def test_actual_post_renderer_reports_math_overflow(offline_page):
    tex='<math><mi>'+'W'*140+'</mi></math>'
    u={'id':'unit:0','html':f'<p><span class="formula" data-math="0">{tex}</span></p>',
       'block_ids':['vi:block:0'],'width':300,'left':110,'reference_top':110,'status':'PARAGRAPH_CANDIDATE'}
    r,m,post=render_adaptive(offline_page,[u],profile(),(1200,1668))
    assert any(v['type']=='MATH_OVERFLOW' for v in post['overflow'])
    assert len(m['maths'])==1 and u['width']==1005


def test_actual_post_render_detects_deliberate_text_math_overlap(offline_page):
    html='<p>Văn bản <span class="formula" data-math="0"><math><mi>x</mi></math></span></p>'
    u={'id':'unit:0','html':html,'block_ids':['vi:block:0'],'width':500,'left':110,'reference_top':110,'status':'UNMATCHED'}
    render_adaptive(offline_page,[u],profile(),(1200,1668))
    offline_page.add_style_tag(content='.formula{position:absolute;left:0;top:0}')
    report=offline_page.evaluate(POST_MEASURE)
    assert any('MATH' in c['type'] and 'TEXT' in c['type'] for c in report['collisions'])


def test_real_pilot_all_content_and_historical_files_preserved():
    r=json.loads((FINAL/'adaptive-layout.json').read_text(encoding='utf8'))
    from translation_evidence import file_hash
    assert r['text_exact'] and r['rendered_block_count']==53 and r['math_nodes_preserved']==66
    assert r['content_preservation_ratio']==1 and r['original_hashes_unchanged']
    assert all(file_hash(p)==h for p,h in r['original_hashes'].items())
    assert r['comparison']['collision_pairs_after']==r['comparison']['overflow_after']==0
    assert r['verified_anchors']==0 and r['anchor_status']=='NOT_ANCHORABLE'
    assert not r['production_integration'] and r['network_attempts']==[]
    assert all(g['sha256']==g['source_sha256'] and not g['inserted_in_layout'] for g in r['geometry'])
    reconstruction=json.loads((FINAL/'paragraph-regions.json').read_text(encoding='utf8'))
    ids=[i for p in reconstruction['paragraphs'] for i in p['source_line_ids']]
    assert len(ids)==len(set(ids))==91
    assert all(p['verification_status']!='PARAGRAPH_VERIFIED' for p in reconstruction['paragraphs'])
    assert all(n['render_occurrences']==1 for n in r['math_integrity']['nodes'])


@pytest.mark.parametrize('height',[0,-1,float('nan'),float('inf')])
def test_invalid_measurements_rejected(height):
    with pytest.raises(ValueError):solve([{'id':'bad','width':100,'height':height}])


def test_post_render_text_text_overlap_inside_paragraph_unit(offline_page):
    u={'id':'unit:0','html':'<p>Văn bản một</p><p>Văn bản hai</p>','block_ids':['vi:block:0','vi:block:1'],
       'width':500,'left':110,'reference_top':110,'status':'UNMATCHED'}
    render_adaptive(offline_page,[u],profile(),(1200,1668))
    offline_page.add_style_tag(content='.unit p+p{position:absolute;left:0;top:0}')
    post=offline_page.evaluate(POST_MEASURE)
    assert any(c['type']=='TEXT–TEXT' for c in post['collisions'])
