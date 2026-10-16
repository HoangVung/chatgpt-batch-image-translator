"""TASK 3H direct order, crop, adjudication gate and offline renderer tests."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import pytest
from PIL import Image,ImageDraw
from layout_reading_order import candidate_order,audit_order,independent_review
from layout_geometry_review import review_geometry,border_ink
from layout_hybrid import select_anchors,hybrid_layout_preview,BLOCKED
from layout_adaptive import render_adaptive,POST_MEASURE
from layout_rebuilder import Tree,RebuildProfile
from translation_evidence import file_hash

ROOT=Path(__file__).resolve().parents[1]
FINAL=ROOT/'output/task3h-page114-20261011-final'
BINDINGS={'source_image_sha256':'a'*64,'capture_sha256':'b'*64,'source_html_sha256':'c'*64,'translation_html_sha256':'d'*64,'paragraph_alignment_sha256':'e'*64}
ORDER_CHECKS=('source_order','translation_order','page_boundary','math_order')
ALIGN_CHECKS=('page_pairing','bbox_content','translation_content','math','reading_order')


def para(i,bbox=(10,10,150,30),typ='BODY_TEXT'):
    return {'paragraph_id':f'p:{i}','source_line_ids':[f'line:{i}'],'source_bbox':list(bbox),'region_type':typ,'confidence':.9}


def blocks(prefix,n):return [{'id':f'{prefix}:block:{i}','math_indices':[i],'non_math_text':f'Unique block text number {i}','tag':'p'} for i in range(n)]


def link(i=0,target=None):
    return {'paragraph_id':f'p:{i}','source_bbox':[10,10+i*40,150,30+i*40],
      'source_block_ids':[f'src:block:{i}'],'translation_block_ids':[f'vi:block:{i if target is None else target}'],
      'source_math_node_ids':[i],'translation_math_node_ids':[i if target is None else target],
      'verification_status':'ALIGNED_CANDIDATE','confidence':.8,'evidence':{'method':'SAVED_CANDIDATE'},'provenance':{'source_image_sha256':'a'*64}}


def review(reference='p:0',checks=ORDER_CHECKS,index=0):
    return {'reference':reference,'verified':True,'independent':True,'reviewer':'Independent fixture reviewer',
       'basis':'Synthetic independent review for gate testing; not pilot evidence','bindings':deepcopy(BINDINGS),
       'checks':{k:True for k in checks},'proposed_reading_order_index':index}


def order(n=1,links=None,reviews=(),rendered=None):
    ps=[para(i,(10,10+i*40,150,30+i*40)) for i in range(n)]
    return audit_order(blocks('src',n),blocks('vi',n),ps,{'links':links or [link(i) for i in range(n)]},
       {'links':[]},bindings=BINDINGS,reviews=reviews,rendered_block_ids=rendered)


def test_columns_are_read_column_first_not_naive_y():
    ps=[para(0),para(1,(200,10,340,30)),para(2,(10,40,150,60)),para(3,(200,40,340,60))]
    r=candidate_order(ps,columns=[[0,0,170,100],[190,0,360,100]])
    assert r['main_candidate_sequence']==['p:0','p:2','p:1','p:3']
    assert r['column_order_differs_from_naive_y'] and not r['reading_order_verified']


def test_heading_and_spanning_content_split_column_bands():
    ps=[para(0,(0,0,360,20),'HEADING'),para(1,(10,25,150,45)),para(2,(200,25,340,45)),
        para(3,(0,50,360,70)),para(4,(10,75,150,95)),para(5,(200,75,340,95))]
    r=candidate_order(ps,columns=[[0,0,170,100],[190,0,360,100]])
    assert r['main_candidate_sequence']==['p:0','p:1','p:2','p:3','p:4','p:5']


def test_float_labels_caption_and_footer_separate_from_main():
    ps=[para(0),para(1,(200,20,230,40),'UNKNOWN'),para(2,(200,60,260,80),'CAPTION'),para(3,(10,180,40,200),'FOOTER')]
    r=candidate_order(ps,figure_regions=[{'figure_id':'figure:test','bbox':[190,0,270,90]}])
    assert r['main_candidate_sequence']==['p:0']
    assert [v['stream'] for v in r['regions']]==['main_candidate','figure_label_candidate','figure_caption','footer']
    assert all(v['proposed_reading_order_index'] is None for v in r['regions'][1:])


@pytest.mark.parametrize('columns',[[[0,0,200,100],[100,0,300,100]],[[0,0,0,100]]])
def test_invalid_column_boundaries_rejected(columns):
    with pytest.raises(ValueError):candidate_order([para(0)],columns)


def test_missing_source_link_stays_unresolved():
    r=order(2,links=[link(0)])
    assert r['translation_blocks'][1]['verification_status']=='READING_ORDER_UNRESOLVED'
    assert r['translation_blocks'][1]['proposed_reading_order_index'] is None


def test_inverted_target_dom_is_reported_and_ambiguous():
    r=order(2,links=[link(0,1),link(1,0)])
    assert len(r['inversions'])==1
    assert all(l['verification_status']=='READING_ORDER_AMBIGUOUS' for l in r['paragraph_links'])


def test_missing_duplicate_rendered_blocks_reported():
    r=order(2,rendered=['vi:block:0','vi:block:0'])
    assert r['render_coverage']['missing_rendered_block_ids']==['vi:block:1']
    assert r['render_coverage']['duplicate_rendered_block_ids']==['vi:block:0']


def test_duplicate_inventory_ids_rejected():
    with pytest.raises(ValueError):audit_order(blocks('src',1),blocks('vi',1)*2,[para(0)],{'links':[link()]},{})


def test_text_duplicate_candidate_does_not_remove_legitimate_math_occurrences():
    vi=blocks('vi',2);vi[1]['non_math_text']=vi[0]['non_math_text']
    r=audit_order(blocks('src',2),vi,[para(0),para(1,(10,50,150,70))],{'links':[link(0),link(1)]},{'links':[]})
    assert len(r['duplicate_text_candidates'])==1
    assert len([m for m in r['math_nodes'] if m['side']=='translation'])==2
    assert not r['duplicate_text_candidates'][0]['removed']


def test_continuation_note_is_preserved_unverified():
    vi=blocks('vi',1);vi[0]['non_math_text']='(Phần chứng minh tiếp tục ở trang sau.)'
    r=audit_order(blocks('src',1),vi,[para(0)],{'links':[link()]},{})
    assert r['translation_only_note_candidates'][0]['translation_reference']=='vi:block:0'
    assert r['adjacent_page_membership']=='UNVERIFIED' and r['file_identifier']=='114'
    assert r['printed_page_number_observation']=='100' and not r['printed_page_number_verified']


@pytest.mark.parametrize('field,value',[('independent',False),('verified',False),('reviewer',''),('basis',''),('reference','p:fake')])
def test_independent_review_requires_explicit_evidence(field,value):
    v=review();v[field]=value
    assert not independent_review(v,BINDINGS,'p:0',ORDER_CHECKS)


@pytest.mark.parametrize('field',list(BINDINGS))
def test_each_hash_binding_must_match(field):
    v=review();v['bindings'][field]='f'*64
    assert not independent_review(v,BINDINGS,'p:0',ORDER_CHECKS)


def test_confidence_and_verified_label_cannot_self_verify():
    l=link();l['confidence']=1;l['verification_status']='ALIGNED_VERIFIED'
    r=order(links=[l]);s=select_anchors({'links':[l]},r,BINDINGS)
    assert r['paragraph_links'][0]['verification_status']=='READING_ORDER_CANDIDATE'
    assert s['qualified_preview_status']==BLOCKED and s['eligible_anchors']==[]


def test_bound_reading_order_review_can_verify_only_reviewed_link():
    r=order(2,reviews=[review()])
    assert [l['verification_status'] for l in r['paragraph_links']]==['READING_ORDER_VERIFIED','READING_ORDER_CANDIDATE']


def align_review(l=None):
    l=l or link();v=review(l['paragraph_id'],ALIGN_CHECKS,index=int(l['paragraph_id'].split(':')[1]))
    for k in ('source_bbox','source_block_ids','translation_block_ids','translation_math_node_ids'):v[k]=deepcopy(l[k])
    return v


def test_anchor_requires_alignment_and_separate_order_adjudication():
    l=link();r=order(reviews=[review()]);s=select_anchors({'links':[l]},r,BINDINGS,[align_review()])
    assert s['verified_anchor_count']==1
    r['paragraph_links'][0]['evidence']['independent_review']=None
    assert select_anchors({'links':[l]},r,BINDINGS,[align_review()])['verified_anchor_count']==0


@pytest.mark.parametrize('field',['source_bbox','source_block_ids','translation_block_ids','translation_math_node_ids'])
def test_anchor_gate_checks_exact_bbox_and_membership(field):
    v=align_review();v[field]=[]
    assert select_anchors({'links':[link()]},order(reviews=[review()]),BINDINGS,[v])['verified_anchor_count']==0


def test_conflicting_reviewed_target_owner_does_not_choose_one():
    ls=[link(0,0),link(1,0)];r=order(2,links=ls,reviews=[review('p:0',index=0),review('p:1',index=1)])
    s=select_anchors({'links':ls},r,BINDINGS,[align_review(l) for l in ls])
    assert s['verified_anchor_count']==0 and all(v['status']=='AMBIGUOUS' for v in s['rejected_anchors'])


def test_hybrid_unit_plan_preserves_unresolved_blocks_and_math_once():
    nodes=Tree('<p><span class="formula" data-math="0"><math><mi>x</mi></math></span></p><p>unresolved</p>').root.children
    s=select_anchors({'links':[link()]},order(reviews=[review()]),BINDINGS,[align_review()])
    plan=hybrid_layout_preview(nodes,s,(1200,1668))
    assert plan['anchored_block_ids']==['vi:block:0'] and plan['reflow_block_ids']==['vi:block:1']
    markup=''.join(u['html'] for u in plan['units']);assert markup.count('data-math="0"')==1


def test_no_review_hybrid_blocked_and_full_reflow_fallback():
    nodes=Tree('<p>unchanged</p>').root.children
    s=select_anchors({'links':[link()]},order(),BINDINGS)
    plan=hybrid_layout_preview(nodes,s,(1200,1668))
    assert plan['status']==BLOCKED and plan['verified_anchors']==0
    assert plan['units'][0]['paragraph_id'] is None and plan['units'][0]['width']==1005
    assert plan['reflow_block_ids']==['vi:block:0']


@pytest.fixture
def geometry_source(tmp_path):
    p=tmp_path/'source.png';im=Image.new('RGB',(200,200),'white');draw=ImageDraw.Draw(im)
    draw.ellipse((60,50,140,130),outline='black',width=2);draw.text((75,145),'caption',fill='black');im.save(p)
    h=file_hash(p)
    ocr=[{'id':'line:caption','text':'图3-51','bbox':[75,145,120,158],'classification':'caption_candidate','source_image_sha256':h}]
    proposals=[{'figure_id':'figure:3-51','caption_candidate':'图3-51','roi':[40,30,160,175],
       'observations':{'visual_extent_candidate':True,'basis':'Synthetic fixture visual candidate'}}]
    return p,h,ocr,proposals


def test_raw_crop_exact_pixels_no_source_change(geometry_source,tmp_path):
    source,h,ocr,ps=geometry_source;r=review_geometry(source,h,ps,ocr,tmp_path/'crops');g=r['figures'][0]
    with Image.open(source) as original,Image.open(g['path']) as crop:
        assert crop.size==(120,145) and crop.tobytes()==original.crop(ps[0]['roi']).tobytes()
    assert file_hash(source)==h and g['decoded_pixels_exact'] and not g['resized'] and g['rotation']==0
    assert g['verification_status']=='GEOMETRY_CANDIDATE' and not g['labels_complete_verified']


def test_white_border_caption_does_not_verify(geometry_source,tmp_path):
    s,h,o,p=geometry_source;r=review_geometry(s,h,p,o,tmp_path/'crops')
    assert r['verified_figures']==0 and not any(r['figures'][0]['border_ink_counts'].values())


def test_caption_missing_is_incomplete(geometry_source,tmp_path):
    s,h,o,p=geometry_source;p[0]['roi'][3]=140
    assert review_geometry(s,h,p,o,tmp_path/'crops')['figures'][0]['verification_status']=='GEOMETRY_INCOMPLETE'


def test_ocr_label_crossing_crop_edge_is_ambiguous(geometry_source,tmp_path):
    s,h,o,p=geometry_source;o.append({'id':'label:B','text':'B','bbox':[35,80,50,95],'classification':'unknown','source_image_sha256':h})
    g=review_geometry(s,h,p,o,tmp_path/'crops')['figures'][0]
    assert g['verification_status']=='GEOMETRY_AMBIGUOUS' and g['edge_crossing_ocr'][0]['id']=='label:B'


def test_neighbouring_prose_is_reported(geometry_source,tmp_path):
    s,h,o,p=geometry_source;o.append({'id':'line:prose','text':'中文正文','bbox':[45,35,150,48],'classification':'text_candidate','source_image_sha256':h})
    g=review_geometry(s,h,p,o,tmp_path/'crops')['figures'][0]
    assert g['verification_status']=='GEOMETRY_AMBIGUOUS' and g['adjacent_prose_candidates']


@pytest.mark.parametrize('change',['source_hash','ocr_hash','outside_roi','fractional_roi'])
def test_geometry_binding_and_roi_validation(geometry_source,tmp_path,change):
    s,h,o,p=geometry_source
    if change=='source_hash':h='f'*64
    if change=='ocr_hash':o[0]['source_image_sha256']='f'*64
    if change=='outside_roi':p[0]['roi']=[-1,0,160,175]
    if change=='fractional_roi':p[0]['roi'][0]=40.5
    with pytest.raises(ValueError):review_geometry(s,h,p,o,tmp_path/'crops')
    assert not (tmp_path/'crops').exists()


def test_crop_output_cannot_overwrite(geometry_source,tmp_path):
    s,h,o,p=geometry_source;review_geometry(s,h,p,o,tmp_path/'crops')
    with pytest.raises(FileExistsError):review_geometry(s,h,p,o,tmp_path/'crops')


def test_geometry_requires_exact_bound_independent_roi_review(geometry_source,tmp_path):
    s,h,o,p=geometry_source;first=review_geometry(s,h,p,o,tmp_path/'first')['figures'][0]
    v={'reference':p[0]['figure_id'],'verified':True,'independent':True,'reviewer':'Independent fixture reviewer','basis':'Synthetic geometry review',
       'bindings':first['binding'],'roi':p[0]['roi'],'checks':{k:True for k in ('figure_extent','all_point_labels','caption','no_adjacent_prose','pixel_fidelity')}}
    g=review_geometry(s,h,p,o,tmp_path/'second',reviews=[v])['figures'][0]
    assert g['verification_status']=='GEOMETRY_VERIFIED' and not g['inserted_in_qualified_preview']
    v['roi']=[0,0,200,200]
    assert review_geometry(s,h,p,o,tmp_path/'third',reviews=[v])['verified_figures']==0


def test_import_with_production_flag_off_does_not_launch_worker_or_browser(tmp_path):
    script="import os,sys; os.environ['BATCH_PROVENANCE_EVENTS']='0'; import layout_hybrid; assert 'run_chatgpt_batch' not in sys.modules; assert 'run_chatgpt_batch_books34' not in sys.modules; assert 'playwright.sync_api' not in sys.modules; print('OFF_IMPORT_NO_WORKER_OR_BROWSER')"
    r=subprocess.run([sys.executable,'-B','-X','utf8','-c',script],cwd=ROOT,capture_output=True,text=True,check=True)
    assert r.stdout.strip()=='OFF_IMPORT_NO_WORKER_OR_BROWSER'


def test_reviewed_hybrid_units_render_no_collision_or_math_duplication():
    from playwright.sync_api import sync_playwright
    nodes=Tree('<p>Văn bản <span class="formula" data-math="0"><math><mi>x</mi></math></span></p><p>Đoạn chưa ghép</p>').root.children
    s=select_anchors({'links':[link()]},order(reviews=[review()]),BINDINGS,[align_review()])
    plan=hybrid_layout_preview(nodes,s,(1200,1668))
    cfg=RebuildProfile(body_size=24,title_size=28,line_height=1.25,paragraph_gap=6,math_gap=6,indent=24)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);context=browser.new_context(offline=True);attempts=[]
        context.route('**/*',lambda route:(attempts.append(route.request.url),route.abort()));page=context.new_page()
        sol,m,post=render_adaptive(page,plan['units'],cfg,(1200,1668))
        assert post['collisions']==post['overflow']==[] and len(m['maths'])==1
        assert post['content_text']=='Văn bản Đoạn chưa ghép'
        page.add_style_tag(content='math{position:absolute;left:24px;top:0}')
        assert page.evaluate(POST_MEASURE)['collisions']
        browser.close();assert attempts==[]


def test_real_3h_diagnostic_boundaries_and_full_preservation():
    r=json.loads((FINAL/'hybrid-layout.json').read_text(encoding='utf8'));c=json.loads((FINAL/'coverage-report.json').read_text(encoding='utf8'))
    geometry=json.loads((FINAL/'geometry-inventory.json').read_text(encoding='utf8'));o=json.loads((FINAL/'reading-order.json').read_text(encoding='utf8'))
    assert r['status']==BLOCKED and r['selection']['verified_anchor_count']==0 and r['qualified_preview'] is None
    assert not (FINAL/'hybrid-preview.png').exists() and (FINAL/'candidate-diagnostic.png').exists()
    assert r['safe_reflow']['is_hybrid'] is False and not r['candidate_diagnostic']['is_qualified_hybrid']
    assert c['translation_blocks_preserved']==53 and c['translation_math_nodes_preserved']==66 and c['text_exact']
    assert c['duplicate_rendered_math_nodes']==0 and c['candidate_diagnostic_pages']==2
    assert c['candidate_diagnostic_collisions']==c['candidate_diagnostic_overflow']==[]
    assert c['qualified_hybrid_pages']==0 and c['verified_figures']==c['verified_anchors_used']==0
    assert len(o['paragraph_links'])==7 and not o['inversions']
    assert o['translation_order_counts']['READING_ORDER_UNRESOLVED']==36
    assert all(not n['math_verified'] for n in o['math_nodes'])
    assert r['original_hashes_unchanged'] and all(file_hash(p)==h for p,h in r['original_hashes'].items())
    assert r['network_attempts']==[] and not r['production_integration']
    assert geometry['verified_figures']==0 and len(geometry['figures'])==3
    for g in geometry['figures']:
        with Image.open(g['source_image_path']) as im,Image.open(g['path']) as crop:
            assert crop.tobytes()==im.crop(g['roi']).tobytes()
        assert file_hash(g['path'])==g['crop_sha256'] and not g['inserted_in_qualified_preview']
