"""TASK 3C offline abstention and geometry-space measurements."""
from pathlib import Path
import json
import pytest
from layout_source_anchored import assess_regions, union_area, project_boxes, feasibility, inventory, diagnostic_html, build
from layout_rebuilder import RebuildProfile
from translation_evidence import file_hash

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/task3c-page114-20261011'


def test_raster_counterpart_and_verified_type_not_dom_mapping():
    d={'region_qc':{'regions':{'source':[{'id':'source:1','bbox':[0,0,20,20],'comparison_type':'BODY_TEXT','classification_verified':True,'counterpart_id':'generated:1'}]}}}
    r=assess_regions(d)[0]
    assert r['status']=='NOT_ANCHORABLE' and not r['translation_blocks'] and not r['math_indices']


def test_geometry_union_avoids_double_counting():
    assert union_area([[0,0,10,10],[5,0,15,10]])==150
    assert union_area([])==0
    assert union_area([[0,0,10,10],[0,20,10,30]])==200


def test_boxes_use_source_pixels_and_clip_print_margins():
    regions=[{'source_bbox':[0,0,50,50]},{'source_bbox':[80,80,100,100]}]
    boxes=project_boxes(regions,(100,100),(200,200),[20,30,160,170])
    assert boxes==[[20,30,100,100]]


def test_diagnostic_never_claims_finished_page():
    p=RebuildProfile();r=[{'id':'source:1','source_bbox':[10,20,50,60],'predicted_type':'BODY_TEXT'}]
    h=diagnostic_html(r,p,(1200,1668),(100,200))
    assert 'NOT_ANCHORABLE' in h and 'KHÔNG PHẢI TRANG DỊCH' in h
    assert '24px' not in h and '27px' in h
    assert '<math' not in h and '<img' not in h and 'HIGH_RISK_HOLD' in h


def test_inventory_keeps_distinct_math_indices_and_note():
    content='<p>Giữ <span class="formula" data-math="0"><math><mi>x</mi></math></span></p><div class="formula display" data-math="1"><math><mi>x</mi></math></div><p>Ghi chú tiếp trang sau.</p>'
    rows=inventory(content)
    assert [r['math_indices'] for r in rows]==[[0],[1],[]]
    assert rows[-1]['non_math_text']=='Ghi chú tiếp trang sau.'
    assert all(r['status']=='NOT_ANCHORABLE' and not r['source_regions'] for r in rows)


def test_space_deficit_separates_debug_notices_and_geometry():
    m={'pages':[{'area_bands':{'text':1000,'display_math':500,'placeholder':200,'internal_whitespace':100,'trailing_whitespace':8200},'printable_area':10000,'printable_box':[0,0,100,100],'blocks':[{'box':[0,0,100,18]}]}]}
    f=feasibility(m,100,10,100)
    assert f['text_math_band_equivalent_height']==15
    assert f['placeholder_band_height']==2
    assert f['band_deficit_without_geometry_px2']==500
    assert f['band_deficit_with_candidate_geometry_px2']==600
    assert f['source_anchored_feasibility']=='NOT_ANCHORABLE'
    assert feasibility(m,100,30,100)['one_page_at_current_full_reflow']=='FITS_FLOW_ONLY_GEOMETRY_UNVERIFIED'


def test_real_source_anchored_artifact_integrity():
    if not OUT.exists():pytest.skip('Run local TASK 3C prototype first')
    r=json.loads((OUT/'source-anchor-analysis.json').read_text(encoding='utf8'))
    assert r['reliably_matched_regions']==0 and r['unverified_regions']==39
    assert r['unknown_type_regions']==3 and r['anchor_status']=='NOT_ANCHORABLE'
    assert r['completed_source_anchored_pages']==0 and r['diagnostic_sheets']==1
    assert r['full_reflow_pages_before']==r['full_reflow_pages_after']==2
    assert r['math_integrity']['technical_preserved']==66
    assert r['boundary_audit']['rendered_duplicate_math_nodes']==0
    assert r['boundary_audit']['source_next_page_content']=='UNVERIFIED'
    assert r['content_text_exact'] and r['original_hashes_unchanged']
    assert all(file_hash(p)==s for p,s in r['original_hashes'].items())
    assert r['network_attempts']==[] and r['dataset_readiness_unchanged']['status']=='HIGH_RISK_HOLD'
    assert r['profile']['body_size']==24 and r['profile']['line_height']==1.25
    assert r['feasibility']['band_deficit_without_geometry_px2']>0
    from PIL import Image
    for name in ('source-anchored-preview.png','unanchored-full-reflow-1.png','unanchored-full-reflow-2.png'):
        with Image.open(OUT/name) as im:assert list(im.size)==r['target_size']
    with pytest.raises(FileExistsError):
        build(ROOT/'output/task2g-live-resume-20261010-192802/capture/capture-50a0ac2d28e3424c9f8a40befdcab1c1/dataset/dataset.json',ROOT/'tests/fixtures/layout_task2g_page114.json',ROOT/'output/task3b-page114-20261011-recheck',OUT)
