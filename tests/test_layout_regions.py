"""Region regressions. Synthetic images are tests only, never the real pilot."""
import copy
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
from layout_profile import LayoutProfile
from layout_qc import calibrate_source_result
from layout_regions import compare_regions, segment_regions, load_independent_labels, pairing_evidence
from layout_pipeline import process_page, process_download_safely

class RegionTests(unittest.TestCase):
    def setUp(self):
        self.p=LayoutProfile(enabled=True,source_aware_enabled=True,normalize_enabled=False,target_size=(600,900))
    def metric(self):
        return dict(size=[600,900],page_frame=[0,0,600,900],analysis_size=[600,900],confidence=.92,frame_confidence=.92,
                    ink_fraction=.04,normalized_bbox=[.1,.1,.9,.8],bands={},geometry_regions=[],formula_candidates=[],text_line_regions=[],edge_regions=[])
    def qc(self):
        return dict(status='PASS',findings=[],metrics={s:self.metric() for s in ('source','generated')})
    def geometry(self,box):
        return dict(box=box,confidence=.82,signature=[1/144]*144)
    def compare(self,q,**kw):
        return compare_regions(q,self.p,**kw)
    def fixture(self,code):
        return json.loads((Path(__file__).parent/'fixtures/layout_calibration_real.json').read_text(encoding='utf8'))[str(code)]['qc']
    def test_real_three_cover_does_not_claim_missing_math(self):
        q=self.compare(self.fixture(3),metadata={'page_type':'cover'})
        self.assertFalse(q['high_risk']);self.assertFalse(any(w['risk']=='MATH_HIGH_RISK' for w in q['warnings']))
        self.assertEqual(q['regions']['source'][0]['predicted_type'],'UNKNOWN');self.assertFalse(q['qc_accepted'])
    def test_real_three_abstains_automatically_without_page_metadata(self):
        r=self.compare(self.fixture(3))
        self.assertFalse(r['high_risk']);self.assertEqual(r['regions']['source'][0]['predicted_type'],'UNKNOWN')
        self.assertFalse(r['qc_accepted'])
    def test_real_six_pairing_not_ai_attribution(self):
        qc=calibrate_source_result(self.fixture(6),self.p)
        q=self.compare(qc,metadata={'pairing_method':'exact_two_integer_tokens','storage_id':'6_6'})
        self.assertTrue(q['high_risk']);self.assertFalse(q['qc_accepted']);self.assertEqual(q['pairing']['status'],'STORAGE_ONLY')
        w=next(w for w in q['warnings'] if w['code']=='NEAR_BLANK_NEW_BODY')
        self.assertEqual(w['risk'],'CONTENT_SUSPECTED');self.assertIn('wrong original',w['reason']);self.assertFalse(q['blocks_batch'])
    def test_sparse_page_not_content_suspected(self):
        q=self.qc()
        for m in q['metrics'].values():m.update(ink_fraction=.001,text_line_regions=[[.3,.4,.5,.42]])
        r=self.compare(q);self.assertFalse(any(w['risk']=='CONTENT_SUSPECTED' for w in r['warnings']))
    def test_missing_geometry_is_high_risk(self):
        q=self.qc();q['metrics']['source']['geometry_regions']=[self.geometry([.2,.4,.5,.7])]
        r=self.compare(q);self.assertTrue(r['high_risk']);self.assertIn('GEOMETRY_DIAGRAM_MISSING',[w['code'] for w in r['warnings']])
    def test_new_geometry_is_also_high_risk(self):
        q=self.qc();q['metrics']['generated']['geometry_regions']=[self.geometry([.2,.4,.5,.7])]
        self.assertTrue(self.compare(q)['high_risk'])
    def test_matches_one_to_one_and_links_both_sides(self):
        q=self.qc()
        q['metrics']['source']['geometry_regions']=[self.geometry([.1,.3,.3,.5]),self.geometry([.35,.3,.55,.5])]
        q['metrics']['generated']['geometry_regions']=[self.geometry([.1,.3,.3,.5])]
        r=self.compare(q);self.assertEqual(len(r['matches']),1)
        self.assertEqual(r['regions']['generated'][0]['counterpart_id'],r['regions']['source'][0]['id'])
        self.assertEqual(sum(w['code']=='GEOMETRY_DIAGRAM_MISSING' for w in r['warnings']),1)
    def test_uncertain_standalone_text_is_unknown(self):
        q=self.qc();q['metrics']['source']['formula_candidates']=[dict(box=[.2,.4,.6,.43],confidence=.55)]
        r=self.compare(q);self.assertEqual(r['regions']['source'][0]['predicted_type'],'UNKNOWN')
        self.assertFalse(any(w['risk']=='MATH_HIGH_RISK' for w in r['warnings']))
    def test_low_confidence_geometry_not_high_risk(self):
        q=self.qc();g=self.geometry([.2,.3,.4,.5]);g['confidence']=.4;q['metrics']['source']['geometry_regions']=[g]
        r=self.compare(q);self.assertFalse(r['high_risk']);self.assertIn('REGION_UNKNOWN',[w['code'] for w in r['warnings']])
    def test_verified_decoration_is_cosmetic_not_math(self):
        q=self.qc();box=[0,.01,.5,.08];q['metrics']['generated']['geometry_regions']=[self.geometry(box)]
        meta={'edge_verification':[dict(region=box,classification='DECORATIVE_EDGE',verified=True,basis='independent crop review')]}
        r=self.compare(q,metadata=meta);self.assertFalse(r['high_risk'])
        region=r['regions']['generated'][0];self.assertEqual(region['comparison_type'],'DECORATION')
        self.assertEqual(region['predicted_type'],'GEOMETRY_DIAGRAM')
        self.assertIn('COSMETIC',[w['risk'] for w in r['warnings']])
    def test_unverified_decoration_cannot_clear_math_risk(self):
        q=self.qc();box=[0,.01,.5,.08];q['metrics']['generated']['geometry_regions']=[self.geometry(box)]
        r=self.compare(q,metadata={'edge_verification':[dict(region=box,classification='DECORATIVE_EDGE',verified=False,basis='prediction')]})
        self.assertTrue(r['high_risk'])
    def test_shape_change_is_suspected_math_only(self):
        q=self.qc()
        for m in q['metrics'].values():m['geometry_regions']=[self.geometry([.2,.4,.5,.7])]
        q['metrics']['generated']['geometry_regions'][0]['signature']=[1.]+[0.]*143
        r=self.compare(q);self.assertIn('GEOMETRY_DIAGRAM_SHAPE',[w['code'] for w in r['warnings']])
        self.assertEqual(r['warnings'][0]['evidence'],'suspected')
    def test_header_footer_shift(self):
        q=self.qc()
        for m in q['metrics'].values():m['bands']={'header':dict(box=[.1,.03,.8,.08],confidence=.84)}
        q['metrics']['generated']['bands']['header']['box']=[.1,.11,.8,.16]
        self.assertIn('HEADER_POSITION',[w['code'] for w in self.compare(q)['warnings']])
    def test_text_line_reflow_is_allowed(self):
        q=self.qc();q['metrics']['source']['text_line_regions']=[[.1,.3,.8,.32]]
        q['metrics']['generated']['text_line_regions']=[[.1,y,.8,y+.02] for y in (.3,.35,.4)]
        r=self.compare(q);self.assertFalse(any(w['risk']=='LAYOUT' for w in r['warnings']))
    def test_storage_id_never_implies_parity(self):
        r=self.compare(self.qc(),metadata={'storage_id':'42_42','pairing_method':'filename'})
        self.assertEqual(r['parity']['status'],'UNASSESSED')
    def test_conflicting_pages_skip_region_comparison(self):
        q=self.qc();q['metrics']['source']['geometry_regions']=[self.geometry([.2,.4,.5,.7])]
        r=self.compare(q,metadata={'source_page_number':9,'generated_page_number':10})
        self.assertFalse(r['matches']);self.assertFalse(r['high_risk']);self.assertEqual(r['pairing']['status'],'CONFLICT')
    def test_rebuilder_always_unready_and_qc_not_mutated(self):
        q=self.qc();before=copy.deepcopy(q);r=self.compare(q)
        self.assertEqual(q,before);self.assertFalse(r['rebuilder_input']['source']['ready_for_rebuild'])
    def test_label_store_validation_and_hash_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'labels.json';box=[.2,.4,.6,.43];digest='a'*64
            label=dict(image_sha256=digest,region=box,type='MATH_FORMULA',reviewer='human',basis='independent review',verified=True)
            p.write_text(json.dumps({'labels':[label]}));labels=load_independent_labels(p)
            m=self.metric();m['formula_candidates']=[dict(box=box,confidence=.55)]
            r=segment_regions(m,side='source',labels=labels,image_sha256=digest)
            self.assertEqual(r[0]['predicted_type'],'UNKNOWN');self.assertEqual(r[0]['comparison_type'],'MATH_FORMULA')
            self.assertNotIn('independent_label',segment_regions(m,side='source',labels=labels,image_sha256='b'*64)[0])
            label['verified']='true';p.write_text(json.dumps({'labels':[label]}))
            with self.assertRaises(ValueError):load_independent_labels(p)
    def test_bbox_uses_original_pixels(self):
        m=self.metric();m['text_line_regions']=[[.1,.3,.8,.32]]
        self.assertEqual(segment_regions(m,side='source')[0]['bbox'],[60,270,480,288])
    def test_near_blank_generated_body_is_suspected_missing_content(self):
        q=self.qc()
        q['metrics']['source']['content_evidence']=dict(body_ink_fraction=.03,body_text_lines=4,substantial_body_components=80)
        q['metrics']['generated']['content_evidence']=dict(body_ink_fraction=0.,body_text_lines=0,substantial_body_components=0,body_geometry_candidates=0)
        r=self.compare(q);self.assertTrue(r['high_risk']);self.assertIn('BODY_MISSING_SUSPECTED',[w['code'] for w in r['warnings']])
    def test_printed_parity_metric_is_reused_without_storage_inference(self):
        q=self.qc();q['source_aware']={'metrics':[dict(name='header_alignment',status='WARNING',reason='trusted printed parity',confidence=.84)]}
        r=self.compare(q,metadata={'page_number':10})
        self.assertEqual(r['parity']['status'],'SOURCE_QC_TEMPLATE');self.assertIn('PARITY_HEADER_ALIGNMENT',[w['code'] for w in r['warnings']])
    def test_both_worker_hooks_high_risk_continue_next_page(self):
        import test_layout_integration as worker_tests
        for harness_type in (worker_tests.PrimaryWorkerLayoutTests,worker_tests.Books34WorkerLayoutTests):
            harness=harness_type();harness.setUp();harness.enable_layout()
            try:
                def high_risk(*args):
                    harness._layout(*args)
                    return {'region_qc':{'high_risk':True,'blocks_batch':False},'qc_accepted':False}
                harness.layout.side_effect=high_risk
                with patch('builtins.input',side_effect=AssertionError('must not pause')):
                    harness.assert_two_pages_complete()
                self.assertEqual(harness.layout.call_count,2)
            finally:harness.doCleanups()
    def images(self,tmp):
        root=Path(tmp);s=root/'s.png';g=root/'g.png'
        with Image.new('RGB',(600,900),'white') as im:im.save(s)
        with Image.new('RGB',(600,900),'white') as im:
            d=ImageDraw.Draw(im)
            for y in range(250,550,30):
                for x in range(100,500,12):d.rectangle((x,y,x+6,y+9),fill='black')
            im.save(g)
        return s,g
    def test_high_risk_real_pipeline_retains_download_and_returns(self):
        with tempfile.TemporaryDirectory() as tmp:
            s,g=self.images(tmp);before=g.read_bytes();config=Path(tmp)/'profile.json'
            config.write_text(json.dumps(dict(enabled=True,source_aware_enabled=True,normalize_enabled=False,target_size=[600,900],output_dir=str(Path(tmp)/'out'))))
            r=process_download_safely(s,g,config,logger=lambda _:None)
            self.assertEqual(r['processing_status'],'COMPLETED',r);self.assertTrue(r['region_qc']['high_risk'])
            self.assertFalse(r['qc_accepted']);self.assertFalse(r['region_qc']['blocks_batch'])
            self.assertEqual(g.read_bytes(),before);self.assertEqual(Path(r['original_copy']).read_bytes(),before)
    def test_feature_off_never_calls_regions(self):
        with tempfile.TemporaryDirectory() as tmp:
            s,g=self.images(tmp)
            with patch('layout_regions.compare_regions',side_effect=AssertionError('must not call')):
                r=process_page(s,g,replace(self.p,source_aware_enabled=False,output_dir=Path(tmp)/'out'),logger=lambda _:None)
            self.assertNotIn('region_qc',r);self.assertEqual(r['processing_status'],'COMPLETED')
    def test_region_exception_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            s,g=self.images(tmp)
            with patch('layout_regions.compare_regions',side_effect=RuntimeError('region error')):
                r=process_page(s,g,replace(self.p,output_dir=Path(tmp)/'out'),logger=lambda _:None)
            self.assertEqual(r['processing_status'],'COMPLETED');self.assertFalse(r['qc_accepted'])
            self.assertFalse(r['region_qc']['blocks_batch'])

if __name__=='__main__':unittest.main()
