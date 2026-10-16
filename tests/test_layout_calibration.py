import copy
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw
from layout_profile import LayoutProfile
from layout_qc import calibrate_source_result, check_layout
from layout_normalizer import normalize_image

class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.profile=LayoutProfile(enabled=True,source_aware_enabled=True,target_size=(600,900))
    def raw(self):
        m={'confidence':.92,'frame_confidence':1.,'ink_fraction':.1,'normalized_bbox':[.1,.1,.9,.9], 'size':[600,900],'page_frame':[0,0,600,900],'analysis_size':[600,900],'edge_regions':[]}
        return {'status':'WARNING','findings':[{'code':'RUNNING_HEADER_UNVERIFIED','severity':'WARNING','evidence':'unassessed'}],'metrics':{'source':copy.deepcopy(m),'generated':copy.deepcopy(m)}}
    def test_missing_header_is_evidence_not_layout(self):
        r=self.raw();q=calibrate_source_result(r,self.profile)
        self.assertEqual((q['layout_status'],q['evidence_status'],q['content_risk']),('PASS','PARTIAL','UNVERIFIED'));self.assertEqual(q['status'],'WARNING');self.assertNotIn('layout_status',r)
    def test_insufficient_not_pass(self):
        r=self.raw();r['metrics']['source']['confidence']=.3
        q=calibrate_source_result(r,self.profile);self.assertEqual(q['layout_status'],'REVIEW_REQUIRED');self.assertEqual(q['evidence_status'],'INSUFFICIENT')
    def test_cover_abstains_but_retains_raw(self):
        r=self.raw()
        for m in r['metrics'].values():m['ink_fraction']=.95
        r['findings'].append({'code':'SOURCE_GEOMETRY_MISSING','severity':'WARNING','evidence':'suspected'})
        q=calibrate_source_result(r,self.profile,metadata={'page_type':'cover'})
        self.assertEqual(q['layout_status'],'REVIEW_REQUIRED');self.assertEqual(q['findings'],r['findings'])
        self.assertEqual(calibrate_source_result(r,self.profile)['layout_status'],'WARNING')
    def test_body_geometry_never_filtered_for_size_or_position(self):
        r=self.raw();r['findings'].append({'code':'SOURCE_GEOMETRY_MISSING','severity':'WARNING','evidence':'suspected','region':[0,2,5,6]})
        q=calibrate_source_result(r,self.profile);self.assertEqual(q['content_risk'],'SUSPECTED');self.assertEqual(q['layout_status'],'WARNING')
    def test_edge_annotation_exact_verified_region_only(self):
        r=self.raw();a=[0,.02,.4,.08];b=[0,.4,.2,.6];r['metrics']['generated']['edge_regions']=[a,b]
        annotation={'region':a,'classification':'DECORATIVE_EDGE','basis':'independent visual check','verified':True}
        q=calibrate_source_result(r,self.profile,metadata={'edge_verification':[annotation]})
        self.assertEqual([v['classification'] for v in q['edge_assessments']],['DECORATIVE_EDGE','CONTENT_EDGE_RISK']);self.assertEqual(q['layout_status'],'WARNING')
        annotation['verified']=False
        self.assertEqual(calibrate_source_result(r,self.profile,metadata={'edge_verification':[annotation]})['edge_assessments'][0]['classification'],'CONTENT_EDGE_RISK')
    def test_scan_noise_needs_evidence(self):
        r=self.raw();box=[0,0,1,.002];r['metrics']['generated']['edge_regions']=[box]
        q=calibrate_source_result(r,self.profile,metadata={'edge_verification':[{'region':box,'classification':'SCAN_BORDER_NOISE','basis':'verified synthetic scan line','verified':True}]})
        self.assertEqual(q['edge_assessments'][0]['classification'],'SCAN_BORDER_NOISE')
    def test_recorded_real_cover_three_regression(self):
        import json
        fixture=json.loads((Path(__file__).parent/'fixtures/layout_calibration_real.json').read_text(encoding='utf8'))['3']
        self.assertTrue(fixture['source_name'].startswith('3_003'))
        self.assertTrue(any(f['code']=='SOURCE_GEOMETRY_MISSING' for f in fixture['qc']['findings']))
        q=calibrate_source_result(fixture['qc'],self.profile,metadata={'page_type':'cover'})
        self.assertEqual(q['layout_status'],'REVIEW_REQUIRED')
        self.assertFalse(any(f['code']=='SOURCE_GEOMETRY_MISSING' for f in q['layout_findings']))
    def test_recorded_real_six_regression(self):
        import json
        fixture=json.loads((Path(__file__).parent/'fixtures/layout_calibration_real.json').read_text(encoding='utf8'))['6']
        self.assertTrue(fixture['source_name'].startswith('6_006'))
        self.assertTrue(fixture['generated_name'].startswith('00006_00006'))
        q=calibrate_source_result(fixture['qc'],self.profile)
        self.assertEqual(q['content_risk'],'HIGH_RISK')
        self.assertEqual(q['layout_status'],'WARNING')
        self.assertTrue(q['content_findings'])
        twice=calibrate_source_result(q,self.profile)
        self.assertEqual(sum(f['code']=='UNEXPECTED_CONTENT_ADDITION' for f in twice['findings']),1)
    def raster(self,root,name,kind):
        p=root/name
        with Image.new('RGB',(600,900),'white') as im:
            d=ImageDraw.Draw(im)
            if kind=='noise':
                for x in range(70,550,50):d.point((x,500),fill='black')
            if kind=='decoration':d.ellipse((50,25,85,60),outline='black',width=3)
            if kind=='sparse':d.rectangle((200,300,300,312),fill='black')
            if kind=='body':
                for y in range(250,550,30):
                    for x in range(100,500,12):d.rectangle((x,y,x+6,y+9),fill='black')
            im.save(p)
        return p
    def test_blank_noise_decoration_do_not_add_content(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for kind in ['blank','noise','decoration']:
                s=self.raster(root,'s.png','blank');g=self.raster(root,'g.png',kind)
                q=check_layout(s,g,self.profile)
                self.assertNotEqual(q['content_risk'],'HIGH_RISK',kind)
    def test_blank_to_body_high_risk_and_normalizer_blocked(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);s=self.raster(root,'s.png','noise');g=self.raster(root,'g.png','body')
            q=check_layout(s,g,self.profile)
            self.assertEqual(q['content_risk'],'HIGH_RISK');self.assertTrue(q['publication_review_required'])
            report,image=normalize_image(g,self.profile,q);self.assertIsNone(image);self.assertEqual(report['status'],'NEEDS_RELAYOUT')
    def test_sparse_source_not_blank(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);q=check_layout(self.raster(root,'s.png','sparse'),self.raster(root,'g.png','body'),self.profile)
            self.assertNotEqual(q['content_risk'],'HIGH_RISK')

if __name__=='__main__':unittest.main()
