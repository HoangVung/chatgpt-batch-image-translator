import pytest
from layout_source_bbox import make_boxes, align_source_blocks, chinese_key
H='a'*64

def box(text, quad=None, score=.9):
    return make_boxes([quad or [[0,0],[100,0],[100,20],[0,20]]],[text],[score],H,(100,100))[0]

def test_original_quad_and_text_preserved():
    q=[[1,2],[99,1],[98,20],[0,21]]; text='充分性：若 S,N,T 三点共线。'
    row=box(text,q);assert row['quadrilateral']==q;assert row['text']==text
    assert row['bbox']==[0,1,99,21];assert row['verification_status']=='OCR_UNVERIFIED'

@pytest.mark.parametrize('score',[-.1,1.1,float('nan')])
def test_bad_confidence_rejected(score):
    with pytest.raises(ValueError):box('文字',score=score)

def test_inventory_mismatch():
    with pytest.raises(ValueError):make_boxes([],['文字'],[],H,(100,100))

def test_outside_image():
    with pytest.raises(ValueError):box('文字',[[-1,0],[100,0],[100,20],[0,20]])

def test_empty_text():
    with pytest.raises(ValueError):box('')

def test_boundary_caption_not_verified():
    row=box('图3-52');assert row['classification']=='caption_candidate'
    assert row['verification_status']=='OCR_UNVERIFIED'

def test_unique_chinese_with_math_not_certified():
    rows=align_source_blocks([box('充分性：若 S,N,T 三点共线。')],[{'id':'src:block:1','non_math_text':'充分性：若  三点共线。'}],H)
    assert rows[0]['status']=='ALIGNED_CANDIDATE';assert not rows[0]['math_verified']

def test_repeated_blocks_abstain():
    rows=align_source_blocks([box('所以四点共圆')],[{'non_math_text':'所以四点共圆'}]*2,H)
    assert all(r['status']=='AMBIGUOUS' for r in rows)

def test_multiple_locations_abstain():
    a=box('充分性若三点共线');b=box('充分性若三点共线',[[0,50],[100,50],[100,70],[0,70]]);b['id']='ocr:line:1'
    assert align_source_blocks([a,b],[{'non_math_text':'充分性若三点共线'}],H)[0]['status']=='AMBIGUOUS'

def test_two_measured_lines_one_source_block():
    a=box('延长直线交圆于点');b=box('所确定的圆于点则',[[0,30],[100,30],[100,50],[0,50]]);b['id']='ocr:line:1'
    r=align_source_blocks([a,b],[{'non_math_text':'延长直线交圆于点所确定的圆于点则'}],H)[0]
    assert r['status']=='ALIGNED_CANDIDATE';assert r['source_bbox']==[0,0,100,50];assert len(r['ocr_box_ids'])==2

def test_low_confidence_abstain():
    r=align_source_blocks([box('充分性若三点共线',score=.5)],[{'non_math_text':'充分性若三点共线'}],H)[0]
    assert r['status']=='UNMATCHED'

@pytest.mark.parametrize('page,hash_value',[('113',H),('114','b'*64)])
def test_wrong_page_or_hash(page,hash_value):
    with pytest.raises(ValueError):align_source_blocks([box('平面几何')],[],hash_value,page)

def test_math_only_abstain():
    assert align_source_blocks([box('ABC=DEF')],[{'non_math_text':''}],H)[0]['status']=='UNMATCHED'

def test_key_only_for_matching():
    assert chinese_key('因为 AB=CD，所以。')=='因为所以'

def test_one_measured_line_two_distinct_source_blocks():
    b=box('充分性若三点共线必要性若五点共圆')
    rows=align_source_blocks([b],[{'non_math_text':'充分性若三点共线'},{'non_math_text':'必要性若五点共圆'}],H)
    assert all(r['status']=='ALIGNED_CANDIDATE' for r in rows)
    assert rows[0]['ocr_box_ids']==rows[1]['ocr_box_ids']

def test_real_ocr_grounding_and_historical_source_hash():
    import json
    from pathlib import Path
    from layout_source_bbox import file_sha256
    root=Path(__file__).resolve().parents[1]
    data=json.loads((root/'output/task3f-page114-20261011-ocr/source-bboxes.json').read_text(encoding='utf-8'))
    saved=json.loads((root/'output/task3d-page114-20261011-final/alignment-dataset.json').read_text(encoding='utf-8'))
    assert len(data['boxes'])==91
    assert file_sha256(data['source_image_path'])==data['source_image_sha256']
    links=align_source_blocks(data['boxes'],saved['source_blocks'],data['source_image_sha256'])
    assert sum(r['status']=='ALIGNED_CANDIDATE' for r in links)==11
    assert all(not r['math_verified'] and not r['reading_order_verified'] for r in links)
