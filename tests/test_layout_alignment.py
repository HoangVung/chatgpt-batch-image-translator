"""TASK 3D unit fixtures are synthetic; artifact checks use real saved data."""
import copy
import json
from pathlib import Path
import pytest
from PIL import Image,ImageDraw
from layout_alignment import (recover_source,align_math,link_blocks,region_candidates,apply_reviews,padded_crops,math_key,build_alignment)
from translation_evidence import file_hash

ROOT=Path(__file__).resolve().parents[1]
CAPTURE=ROOT/'output/task2g-live-resume-20261010-192802/capture/capture-50a0ac2d28e3424c9f8a40befdcab1c1/translation-attempt-1.json'
FINAL=ROOT/'output/task3d-page114-20261011-final'


def rows(*latex):return [{'latex':t} for t in latex]


def test_math_alignment_does_not_pair_mismatched_index():
    r=align_math(rows('x+y','a=b'),rows('x-y','a=b'))
    assert [(p['source_math_ids'],p['math_node_ids']) for p in r['links']]==[([1],[1])]
    assert r['unmatched_source_math_ids']==r['unmatched_translation_math_ids']==[0]


@pytest.mark.parametrize('source,target,expected',[
    (rows('x=1,\\quad y=2'),rows('x=1','y=2'),([0],[0,1])),
    (rows('x=1','y=2'),rows('\\begin{aligned}x&=1\\\\y&=2\\end{aligned}'),([0,1],[0]))])
def test_math_one_many_and_many_one(source,target,expected):
    before=copy.deepcopy((source,target));r=align_math(source,target)
    assert (r['links'][0]['source_math_ids'],r['links'][0]['math_node_ids'])==expected
    assert (source,target)==before and r['links'][0]['mathematical_equivalence']=='NOT_PROVEN'


def test_repeated_formula_remains_ambiguous():
    r=align_math(rows('x','x'),rows('x'))
    assert len(r['links'])==1 and r['links'][0]['verification_status']=='AMBIGUOUS'
    assert len(r['unmatched_source_math_ids'])==1


@pytest.mark.parametrize('tex,target',[(r'\triangle ABC','ABC'),(r'\odot O','(O)')])
def test_missing_math_operator_is_unmatched(tex,target):
    assert not align_math(rows(tex),rows(target))['links']


def test_missing_source_text_fallback():
    assert recover_source({},'a'*64)['status']=='INSUFFICIENT_EVIDENCE'
    r=align_math([],rows('x','y'));assert r['unmatched_translation_math_ids']==[0,1]
    assert region_candidates([],[],[],{})==[]


@pytest.mark.parametrize('change',['wrong_page','snapshot_conflict','conversation_conflict'])
def test_real_source_recovery_rejects_incorrect_binding(change):
    if not CAPTURE.exists():pytest.skip('Real capture absent')
    c=json.loads(CAPTURE.read_text(encoding='utf8'));expected=c['source_sha256']
    if change=='wrong_page':expected='0'*64
    if change=='snapshot_conflict':c['capture_audit']['after']['messages'][1]['text']+='CHANGED'
    if change=='conversation_conflict':c['capture_audit']['after']['conversation_url']='other-conversation'
    r=recover_source(c,expected);assert r['candidate'] is None and not r['verified']


def test_real_source_recovery_keeps_observed_id_and_raw_payload():
    if not CAPTURE.exists():pytest.skip('Real capture absent')
    c=json.loads(CAPTURE.read_text(encoding='utf8'));before=copy.deepcopy(c)
    r=recover_source(c,c['source_sha256'])
    assert r['status']=='ALIGNED_CANDIDATE' and not r['verified']
    assert r['candidate']==c['capture_audit']['before']['messages'][1] and c==before
    assert r['provenance']['captured_response_id']==r['candidate']['id']


def block(name,text,indices,tag='p'):
    return {'id':name,'non_math_text':text,'math_indices':indices,'tag':tag}


def test_section_marker_text_alignment_without_formula():
    s=[block('s','例8',[])];t=[block('v','Ví dụ 8.',[])]
    r=link_blocks(s,t,{'links':[]})
    assert r[0]['source_text_reference']=='s' and r[0]['translation_block_ids']==['v']
    assert r[0]['verification_status']=='ALIGNED_CANDIDATE' and r[0]['reading_order_index'] is None


def test_block_many_one_and_one_many():
    source=[block('s0','',[0]),block('s1','',[1])];target=[block('v0','',[0],tag='div')]
    r=link_blocks(source,target,{'links':[{'source_math_ids':[0,1],'math_node_ids':[0],'verification_status':'ALIGNED_CANDIDATE'}]})
    assert len(r)==2 and all(p['translation_block_ids']==['v0'] for p in r)
    r=link_blocks([block('s0','',[0])],[block('v0','',[0]),block('v1','',[1])],{'links':[{'source_math_ids':[0],'math_node_ids':[0,1],'verification_status':'ALIGNED_CANDIDATE'}]})
    assert r[0]['translation_block_id'] is None and r[0]['translation_block_ids']==['v0','v1']


def test_rank_is_ambiguous_not_verified_reading_order():
    s=[block('s','充分性',[0])];links=[{'source_text_reference':'s','translation_block_id':'v','translation_block_ids':['v'],'math_node_ids':[0],'alignment_method':['lexical'],'verification_status':'ALIGNED_CANDIDATE','reading_order_index':None}]
    r=region_candidates([{'id':'source:8','bbox':[10,20,30,40],'comparison_type':'BODY_TEXT'}],s,links,{})
    assert r[0]['verification_status']=='AMBIGUOUS' and not r[0]['eligible_for_anchor'] and r[0]['reading_order_index'] is None


def test_review_requires_independence_full_hash_binding_and_reading_order():
    link={'alignment_id':'local-alignment:one','source_bbox':[0,0,10,10],'verification_status':'AMBIGUOUS','eligible_for_anchor':False}
    bindings={k:'a'*64 for k in ('source_image_sha256','capture_sha256','source_html_sha256','translation_html_sha256')}
    review=dict(bindings,alignment_id=link['alignment_id'],source_bbox=link['source_bbox'],reviewer='unit fixture reviewer',basis='unit fixture independent adjudication',verified=True,independent=True,reading_order_index=0,checks={k:True for k in ('page_pairing','bbox_content','translation_content','math','reading_order')})
    assert apply_reviews([link],[review],bindings)[0]['verification_status']=='ALIGNED_VERIFIED'
    for altered in [dict(review,independent=False),dict(review,capture_sha256='b'*64),dict(review,reading_order_index=None)]:
        assert not apply_reviews([link],[altered],bindings)[0]['eligible_for_anchor']
    assert not apply_reviews([link],[review],{})[0]['eligible_for_anchor']
    assert link['verification_status']=='AMBIGUOUS'


def test_padded_geometry_preserves_pixels_without_certifying_labels(tmp_path):
    source=tmp_path/'source.png'
    with Image.new('RGB',(300,400),'white') as im:
        draw=ImageDraw.Draw(im);draw.line((180,100,220,180),fill='black',width=2);draw.text((225,185),'Q',fill='black');im.save(source)
    before=file_hash(source)
    r=padded_crops(source,[{'id':'source:3','bbox':[180,100,220,180],'comparison_type':'GEOMETRY_DIAGRAM'}],tmp_path/'crops',padding=20)[0]
    assert r['padded_bbox']==[160,80,240,200] and r['decoded_pixels_exact']
    assert r['status']=='GEOMETRY_UNVERIFIED' and not r['labels_complete'] and not r['caption_complete'] and not r['inserted']
    assert file_hash(source)==before
    with pytest.raises(FileExistsError):padded_crops(source,[],tmp_path/'crops')


def test_real_alignment_artifact_originals_and_no_anchor():
    if not FINAL.exists():pytest.skip('Generate real offline TASK 3D first')
    r=json.loads((FINAL/'alignment-dataset.json').read_text(encoding='utf8'))
    assert r['counts']['source_math_nodes']==67 and r['counts']['translation_math_nodes']==66
    assert r['counts']['math_nodes_with_candidate_or_ambiguous_links']==60
    assert r['counts']['regions_with_candidates']==33 and r['counts']['regions_without_candidates']==6
    assert r['counts']['verified_regions']==r['counts']['verified_complete_figures']==0
    assert all(not l['eligible_for_anchor'] and l['reading_order_index'] is None for l in r['alignments'])
    assert all(l['layout_position_candidate']['status']=='NOT_PLACED' for l in r['alignments'])
    assert all(p['provenance']['capture_sha256'] for p in r['math_alignment']['links'])
    assert r['pilot']['anchor_status']=='NOT_ANCHORABLE' and r['pilot']['math_preserved']==66
    assert r['pilot']['full_reflow_pages']==2 and r['pilot']['network_attempts']==[]
    assert r['page_boundary']['page_file_identifier']=='114' and r['page_boundary']['printed_page_number_observation']=='100'
    assert not r['page_boundary']['file_identifier_is_printed_page'] and r['page_boundary']['reading_order_status']=='DOM_SEQUENCE_ONLY_UNVERIFIED'
    assert r['original_hashes_unchanged'] and all(file_hash(p)==h for p,h in r['original_hashes'].items())
    with pytest.raises(FileExistsError):
        build_alignment(CAPTURE.parent/'dataset/dataset.json',ROOT/'tests/fixtures/layout_task2g_page114.json',CAPTURE,ROOT/'output/task3b-page114-20261011-recheck',ROOT/'output/task3c-page114-20261011',FINAL)
