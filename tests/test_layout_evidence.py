"""Translation capture and dataset fixtures; never use ChatGPT quota."""
import ast
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image,ImageDraw
from translation_evidence import extract_translation,read_snapshot,begin_safely,checkpoint_safely,capture_safely,finalize_safely,digest,file_hash
from layout_dataset import build_dataset,write_dataset,load_reviews,CHECKS

ROOT=Path(__file__).resolve().parents[1]
PROMPT='dịch bản chép lại'
TEXT='Cho tam giác ABC.\n\nTa có α + β = 180°, ∑ xᵢ ≥ 0 và \\(x^2 + y^2\\).'


def message(ident,role,text):
    return dict(id=ident,role=role,text=text,html='<p>'+text+'</p>',blocks=[dict(tag='P',text=text)],formulas=[])
def baseline():
    return dict(supported=True,generating=False,conversation_url='https://chatgpt.com/c/fixture-one',messages=[message('copy-user','user','chép lại nguyên văn'),message('copy-answer','assistant','原文')])
def translated():
    s=baseline();s['messages'] += [message('translate-user','user',PROMPT),message('translate-answer','assistant',TEXT)]
    s['messages'][-1]['formulas']=[dict(representation='latex_annotation',raw=r'\sum_i x_i\ge0')]
    return s
class Page:
    def __init__(self,snapshots):self.snapshots=list(snapshots)
    def evaluate(self,js):
        if not self.snapshots:raise RuntimeError('no DOM')
        value=self.snapshots.pop(0)
        if isinstance(value,Exception):raise value
        return value

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.s=self.root/'source.png';self.g=self.root/'translated.png'
        for p in (self.s,self.g):
            with Image.new('RGB',(120,180),'white') as im:
                ImageDraw.Draw(im).line((10,20,100,140),fill='black',width=2);im.save(p)
    def extract(self,b=None,a=None,complete=True):return extract_translation(b or baseline(),a or translated(),expected_prompt=PROMPT,complete=complete)
    def evidence(self):
        e=self.extract();e.update(source_sha256=file_hash(self.s),generated_sha256=file_hash(self.g),capture_token='fixture',association='same_page_worker_capture_session');return e
    def regions(self):
        r=dict(id='source:1',bbox=[10,20,100,140],normalized_bbox=[.1,.1,.8,.8],comparison_type='BODY_TEXT',confidence=.8,classification_verified=False)
        return dict(high_risk=False,regions={'source':[r],'generated':[dict(r,id='generated:1')]},warnings=[],pairing={'status':'WORKER_BOUND'})
    def dataset(self,**kw):return build_dataset(self.s,self.g,evidence=kw.pop('evidence',self.evidence()),region_qc=kw.pop('region_qc',self.regions()),**kw)
    def review(self,d):
        return dict(source_sha256=d['source_image']['sha256'],generated_sha256=d['translated_image']['sha256'],evidence_sha256=d['evidence_sha256'],regions_sha256=d['regions_sha256'],reviewer='independent human fixture',basis='explicit whole-page audit fixture',verified=True,checks={k:True for k in CHECKS})
    def test_correct_translation_and_unicode_latex_exact(self):
        e=self.extract();self.assertEqual(e['text'],TEXT);self.assertEqual(e['formulas'][0]['raw'],r'\sum_i x_i\ge0')
        self.assertEqual(e['text_sha256'],hashlib.sha256(TEXT.encode('utf8')).hexdigest());self.assertFalse(e['verified'])
    def test_literal_latex_is_preserved_as_unverified_syntax(self):
        e=self.extract();candidate=next(f for f in e['formulas'] if f['representation']=='literal_latex_in_dom_text')
        self.assertEqual(candidate['raw'],r'\(x^2 + y^2\)');self.assertFalse(candidate['verified'])
    def test_previous_response_is_not_selected(self):self.assertEqual(self.extract(a=baseline())['status'],'EVIDENCE_INCOMPLETE')
    def test_copy_prompt_is_not_translation(self):
        a=translated();a['messages'][-2]['text']='chép lại nguyên văn';self.assertIsNone(self.extract(a=a)['text'])
    def test_different_conversation_rejected(self):
        a=translated();a['conversation_url']='https://chatgpt.com/c/other';self.assertEqual(self.extract(a=a)['status'],'EVIDENCE_INCOMPLETE')
    def test_virtualized_or_changed_history_rejected(self):
        a=translated();a['messages'][0]['text']='new page';self.assertIsNone(self.extract(a=a)['text'])
    def test_duplicate_ids_rejected(self):
        a=translated();a['messages'][-1]['id']='copy-answer';self.assertIsNone(self.extract(a=a)['text'])
    def test_generating_or_missing_completion_rejected(self):
        a=translated();a['generating']=True;self.assertIsNone(self.extract(a=a)['text']);self.assertIsNone(self.extract(complete=False)['text'])
    def test_multiple_assistant_turns_abstain(self):
        a=translated();a['messages'].append(message('extra','assistant','ambiguous'));self.assertIsNone(self.extract(a=a)['text'])
    def test_missing_stable_id_abstains(self):
        a=translated();a['messages'][-1].pop('id');self.assertIsNone(self.extract(a=a)['text'])
    def test_stable_session_persists_before_image_generation(self):
        page=Page([baseline(),translated(),translated()]);s=begin_safely(page,self.s,self.root/'capture')
        capture_safely(page,checkpoint_safely(page),PROMPT)
        self.assertTrue((s.directory/'translation-attempt-1.json').is_file())
        d=finalize_safely(s,self.s,self.g,dict(source_sha256=file_hash(self.s),original_sha256=file_hash(self.g),region_qc=self.regions()))
        self.assertEqual(d['pairing_status'],'BOUND');self.assertEqual(d['translation']['text'],TEXT)
    def test_changed_during_capture_is_incomplete(self):
        changed=translated();changed['messages'][-1]['text']+=' streaming'
        page=Page([baseline(),translated(),changed]);s=begin_safely(page,self.s,self.root/'capture');capture_safely(page,checkpoint_safely(page),PROMPT)
        self.assertEqual(s.evidence['status'],'EVIDENCE_INCOMPLETE')
    def test_other_page_cannot_read_active_session(self):
        s=begin_safely(Page([]),self.s,self.root/'capture');self.assertIsNone(checkpoint_safely(Page([baseline()])))
    def test_missing_baseline_keeps_batch_and_dataset(self):
        page=Page([RuntimeError('missing'),translated(),translated()]);s=begin_safely(page,self.s,self.root/'capture')
        capture_safely(page,checkpoint_safely(page),PROMPT);d=finalize_safely(s,self.s,self.g)
        self.assertEqual(d['readiness']['status'],'EVIDENCE_INCOMPLETE');self.assertFalse(d['readiness']['blocks_batch'])
    def test_new_session_drops_previous_translation(self):
        page=Page([baseline(),translated(),translated()]);first=begin_safely(page,self.s,self.root/'capture');capture_safely(page,checkpoint_safely(page),PROMPT)
        next_session=begin_safely(page,self.s,self.root/'capture');self.assertIsNone(next_session.evidence['text']);self.assertNotEqual(first.token,next_session.token)
    def test_mismatched_image_hash_and_tampered_text_rejected(self):
        for key,value in [('generated_sha256','0'*64),('text','tampered')]:
            e=self.evidence();e[key]=value;d=self.dataset(evidence=e);self.assertEqual(d['translation']['status'],'EVIDENCE_INCOMPLETE')
    def test_source_change_refuses_binding(self):
        page=Page([]);s=begin_safely(page,self.s,self.root/'capture');self.s.write_bytes(b'changed')
        self.assertIsNone(finalize_safely(s,self.s,self.g))
    def test_qc_pass_never_implies_ready_without_review(self):
        d=self.dataset();self.assertEqual(d['readiness']['status'],'EVIDENCE_INCOMPLETE')
    def test_ready_requires_explicit_hash_bound_independent_checks(self):
        d=self.dataset();r=self.review(d);ready=self.dataset(reviews=[r]);self.assertEqual(ready['readiness']['status'],'READY_FOR_PILOT')
        self.assertFalse(ready['readiness']['eligible_for_final_page']);r['source_sha256']='f'*64
        self.assertEqual(self.dataset(reviews=[r])['readiness']['status'],'EVIDENCE_INCOMPLETE')
    def test_high_risk_never_ready_even_with_all_checks(self):
        q=self.regions();q['high_risk']=True;d=self.dataset(region_qc=q);r=self.review(d)
        self.assertEqual(self.dataset(region_qc=q,reviews=[r])['readiness']['status'],'HIGH_RISK_HOLD')
    def test_unknown_regions_are_not_verified_by_machine(self):
        q=self.regions();q['regions']['source'][0]['comparison_type']='UNKNOWN';d=self.dataset(region_qc=q)
        self.assertEqual(self.dataset(region_qc=q,reviews=[self.review(d)])['readiness']['status'],'EVIDENCE_INCOMPLETE')
    def test_known_formula_without_original_representation_incomplete(self):
        q=self.regions();q['regions']['source'][0]['comparison_type']='MATH_FORMULA';e=self.evidence();e['formulas']=[]
        e['response_sha256']=digest({k:e[k] for k in ('text','html','blocks','formulas')});d=self.dataset(evidence=e,region_qc=q)
        self.assertEqual(self.dataset(evidence=e,region_qc=q,reviews=[self.review(d)])['readiness']['status'],'EVIDENCE_INCOMPLETE')
    def test_lossless_crop_preserves_original_and_unverified_status(self):
        q=self.regions();q['regions']['source'][0]['comparison_type']='GEOMETRY_DIAGRAM';before=self.s.read_bytes()
        d=write_dataset(self.dataset(region_qc=q),self.root/'dataset',export_crops=True);crop=d['geometry_crops'][0]
        self.assertEqual(self.s.read_bytes(),before);self.assertTrue(crop['decoded_pixels_exact']);self.assertFalse(crop['eligible_for_final_page'])
        with Image.open(self.s) as original,Image.open(crop['path']) as saved:
            self.assertEqual(original.crop(crop['bbox']).tobytes(),saved.tobytes())
    def test_invalid_crop_not_silently_clipped(self):
        q=self.regions();q['regions']['source'][0].update(comparison_type='GEOMETRY_DIAGRAM',bbox=[-1,0,100,140])
        d=write_dataset(self.dataset(region_qc=q),self.root/'dataset',export_crops=True)
        self.assertEqual(d['geometry_crops'][0]['status'],'EVIDENCE_INCOMPLETE');self.assertEqual(d['readiness']['status'],'EVIDENCE_INCOMPLETE')
    def test_review_store_rejects_machine_boolean_coercion(self):
        d=self.dataset();r=self.review(d);r['checks']['formulas']='true';p=self.root/'reviews.json';p.write_text(json.dumps({'reviews':[r]}))
        with self.assertRaises(ValueError):load_reviews(p)
    def test_both_translation_hooks_only_capture_after_translation(self):
        for filename in ('run_chatgpt_batch.py','run_chatgpt_batch_books34.py'):
            tree=ast.parse((ROOT/filename).read_text(encoding='utf8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_dich_step')
            calls=[];page=Page([baseline(),translated(),translated()]);s=begin_safely(page,self.s,self.root/filename)
            ns=dict(SERVICE='chatgpt',os=SimpleNamespace(environ={'BATCH_TRANSLATION_EVIDENCE_DIR':str(self.root)}),MAX_RETRY_DICH=1,
                    PROMPT_CHEP_LAI='chép lại nguyên văn',PROMPT_DICH=PROMPT,get_assistant_response_signature=lambda _: {},
                    send_prompt=lambda p,t:calls.append(t),wait_response_after_send=lambda *a,**k:True,sleep=lambda _:None,print=lambda *a:None)
            exec(compile(ast.Module(body=[fn],type_ignores=[]),filename,'exec'),ns)
            self.assertTrue(ns['run_dich_step'](page));self.assertEqual(calls,['chép lại nguyên văn',PROMPT]);self.assertEqual(s.evidence['text'],TEXT)
    def test_translation_feature_off_has_no_evidence_dom_reads(self):
        fn=next(n for n in ast.parse((ROOT/'run_chatgpt_batch.py').read_text(encoding='utf8')).body if isinstance(n,ast.FunctionDef) and n.name=='run_dich_step')
        page=Page([]);ns=dict(SERVICE='chatgpt',os=SimpleNamespace(environ={}),MAX_RETRY_DICH=1,PROMPT_CHEP_LAI='chép lại nguyên văn',PROMPT_DICH=PROMPT,
            get_assistant_response_signature=lambda _: {},send_prompt=lambda *a:None,wait_response_after_send=lambda *a,**k:True,sleep=lambda _:None,print=lambda *a:None)
        with patch('translation_evidence.checkpoint_safely',side_effect=AssertionError('OFF')):
            exec(compile(ast.Module(body=[fn],type_ignores=[]),'worker','exec'),ns);self.assertTrue(ns['run_dich_step'](page))
    def test_both_process_hooks_high_risk_sidecar_preserves_done(self):
        import test_layout_integration as workers
        for cls in (workers.PrimaryWorkerLayoutTests,workers.Books34WorkerLayoutTests):
            h=cls();h.setUp();h.enable_layout();h.environ['BATCH_TRANSLATION_EVIDENCE_DIR']=str(h.root/'evidence')
            try:
                def high_report(source,generated,profile):
                    h._layout(source,generated,profile)
                    return {'source_sha256':file_hash(source),'original_sha256':file_hash(generated),
                            'region_qc':{'high_risk':True,'regions':{'source':[],'generated':[]},'warnings':[]}}
                h.layout.side_effect=high_report
                h.assert_two_pages_complete()
                data=[json.loads(p.read_text()) for p in (h.root/'evidence').rglob('dataset.json')]
                self.assertEqual(len(data),2);self.assertTrue(all(d['readiness']['status']=='HIGH_RISK_HOLD' for d in data))
                self.assertTrue(all(d['readiness']['eligible_for_final_page'] is False for d in data))
            finally:h.doCleanups()
    def test_both_process_hooks_missing_evidence_continue_next_page(self):
        import test_layout_integration as workers
        for cls in (workers.PrimaryWorkerLayoutTests,workers.Books34WorkerLayoutTests):
            h=cls();h.setUp();h.environ['BATCH_TRANSLATION_EVIDENCE_DIR']=str(h.root/'evidence')
            try:
                with patch('builtins.input',side_effect=AssertionError('no user pause')):h.assert_two_pages_complete()
                data=list((h.root/'evidence').rglob('dataset.json'));self.assertEqual(len(data),2)
                self.assertTrue(all(json.loads(p.read_text())['readiness']['status']=='EVIDENCE_INCOMPLETE' for p in data))
            finally:h.doCleanups()

class EvidenceDOMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.manager=sync_playwright().start()
            edge=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
            cls.browser=cls.manager.chromium.launch(headless=True,**({'executable_path':str(edge)} if edge.exists() else {}))
        except Exception as exc:
            if hasattr(cls,'manager'):cls.manager.stop()
            raise unittest.SkipTest('Offline browser fixture unavailable: '+type(exc).__name__)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.manager.stop()
    def setUp(self):
        self.page=self.browser.new_page();self.addCleanup(self.page.close)
        self.page.route('**/*',lambda route:route.fulfill(status=200,body='<html><body></body></html>',content_type='text/html'))
        self.page.goto('https://chatgpt.com/c/offline-fixture')
    def old(self):return '<div data-message-id="copy" data-message-author-role="assistant"><div class="markdown"><p>原文</p></div></div>'
    def test_real_dom_role_ids_unicode_and_original_latex(self):
        self.page.set_content(self.old());before=read_snapshot(self.page)
        self.page.set_content(self.old()+f'<div data-message-id="u" data-message-author-role="user">{PROMPT}<button>Copy</button></div><div data-message-id="a" data-message-author-role="assistant"><div class="markdown"><p>Cho α ≥ 0.</p><p>Công thức:</p><math><semantics><mi>x</mi><annotation encoding="application/x-tex">x^2+α</annotation></semantics></math></div></div>')
        e=extract_translation(before,read_snapshot(self.page),expected_prompt=PROMPT,complete=True)
        self.assertEqual(e['status'],'COLLECTED_UNVERIFIED');self.assertIn('α ≥ 0',e['text']);self.assertEqual(e['formulas'][0]['raw'],'x^2+α');self.assertEqual(e['blocks'][0]['text'],'Cho α ≥ 0.')
    def unit(self,role,ident,text):return f'<div data-content-search-unit-key="turn:{role}"><div data-chatgpt-selection-message-id="{ident}"><div data-markdown-text-style="{role}-message"><p>{text}</p></div></div></div>'
    def test_current_search_unit_dom_with_selection_id(self):
        old=self.unit('assistant','copy','原文');self.page.set_content(old);before=read_snapshot(self.page)
        self.page.set_content(old+self.unit('user','u',PROMPT)+self.unit('assistant','a','Cho tam giác ABC.'))
        e=extract_translation(before,read_snapshot(self.page),expected_prompt=PROMPT,complete=True);self.assertEqual(e['status'],'COLLECTED_UNVERIFIED')
    def test_search_unit_without_stable_id_is_incomplete(self):
        self.page.set_content('<div data-content-search-unit-key="turn:assistant"><p>no ID</p></div>');self.assertFalse(read_snapshot(self.page)['supported'])

if __name__=='__main__':unittest.main()
