"""Offline tests: synthetic negative cases plus persisted TASK 2G real snapshots."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from test_layout_evidence import Page, baseline, translated, PROMPT
from translation_evidence import CaptureSession, digest
from layout_live_evidence import verify_safely

class LiveEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        self.source=root/'page.png';self.generated=root/'translated.png'
        for p in (self.source,self.generated):Image.new('RGB',(10,10),'white').save(p)
        session=CaptureSession(Page([baseline(),translated(),translated()]),self.source,root/'fixture-batch')
        b=session.before_translation();session.after_translation(b,PROMPT)
        self.d=session.finalize(self.source,self.generated)
    def seal(self):
        e=self.d['translation'];self.d['evidence_sha256']=digest(e)
        self.d['regions_sha256']=digest(self.d.get('region_qc'))
        self.d.pop('dataset_sha256',None);self.d['dataset_sha256']=digest(self.d)
    def attest(self):
        e=self.d['translation']
        return {**{k:e[k] for k in ('conversation_url','user_message_id','assistant_message_id','capture_token','source_sha256','generated_sha256','response_sha256','batch_id','page_id')},
                'dataset_sha256':self.d['dataset_sha256'],'reviewer':'fixture reviewer','basis':'synthetic observed mapping',
                'live_observed':True,'image_turn_pairing_verified':True,'generated_message_id':'image-response',
                'image_turn_observation':{'evidence_reference':'synthetic fixture observation, not live proof',
                    'conversation_url':e['conversation_url'],'capture_token':e['capture_token'],
                    'translation_response_id':e['assistant_message_id'],'generation_prompt':'Tạo ảnh với bản dịch',
                    'generation_user_message_id':'image-user','generated_message_id':'image-response','generation_complete':True,
                    'download':{'response_message_id':'image-response','ui_asset_id':'fixture-asset',
                        'download_asset_id':'fixture-asset','sha256':e['generated_sha256']}}}
    def test_capture_valid_is_not_live_or_translation_verified(self):
        r=verify_safely(self.d);self.assertEqual(r['capture_status'],'CAPTURE_VALID');self.assertEqual(r['status'],'ASSOCIATION_UNVERIFIED')
        self.assertFalse(r['live_origin_verified']);self.assertEqual(r['translation_status'],'TRANSLATION_UNVERIFIED')
    def test_explicit_attestation_still_needs_independent_readiness(self):
        r=verify_safely(self.d,provenance=self.attest());self.assertEqual(r['association_status'],'ASSOCIATION_VERIFIED')
        self.assertEqual(r['status'],'EVIDENCE_INCOMPLETE');self.assertFalse(r['eligible_for_final_page'])
    def test_legacy_missing_audit_never_ready(self):
        self.d['translation'].pop('capture_audit');self.seal()
        self.assertEqual(verify_safely(self.d)['capture_status'],'CAPTURE_UNVERIFIED')
    def test_audit_hash_tampering(self):
        self.d['translation']['capture_audit']['page_id']='other';self.seal()
        self.assertEqual(verify_safely(self.d)['capture_status'],'CAPTURE_UNVERIFIED')
    def test_wrong_conversation_old_copy_multiple_missing_ids_virtualized_streaming(self):
        for kind in ('conversation','old','copy','multiple','id','virtualized','streaming'):
            d=copy.deepcopy(self.d);a=d['translation']['capture_audit'];after=a['after']
            if kind=='conversation':after['conversation_url']='https://chatgpt.com/c/other'
            if kind=='old':after['messages']=after['messages'][:-2]
            if kind=='copy':after['messages'][-2]['text']='chép lại nguyên văn'
            if kind=='multiple':after['messages'].append(dict(after['messages'][-1],id='extra'))
            if kind=='id':after['messages'][-1]['id']=''
            if kind=='virtualized':after['messages'].pop(0)
            if kind=='streaming':after['generating']=True
            a['stable_after']=copy.deepcopy(after);d['translation']['capture_audit_sha256']=digest(a)
            r=verify_safely(d);self.assertEqual(r['capture_status'],'CAPTURE_UNVERIFIED',kind)
    def test_cross_session_missing_page_batch_id(self):
        for k in ('page_session_id','page_id','batch_id'):
            d=copy.deepcopy(self.d);d['translation'][k]='other'
            self.assertEqual(verify_safely(d)['association_status'],'ASSOCIATION_UNVERIFIED')
    def test_image_hash_source_path_and_response_hash_mismatch(self):
        for k in ('source_sha256','generated_sha256','source_path','generated_path','response_sha256'):
            d=copy.deepcopy(self.d);d['translation'][k]='wrong'
            self.assertEqual(verify_safely(d)['association_status'],'ASSOCIATION_UNVERIFIED')
    def test_current_image_changed(self):
        self.source.write_bytes(b'changed');self.assertEqual(verify_safely(self.d)['association_status'],'ASSOCIATION_UNVERIFIED')
    def test_unicode_latex_and_block_inventory_unchanged(self):
        before=copy.deepcopy(self.d);r=verify_safely(self.d)
        self.assertEqual(self.d,before);self.assertEqual(r['representations']['formula_representations'],self.d['translation']['formulas'])
        self.assertGreater(r['representations']['symbols']['∑'],0);self.assertEqual(r['representations']['blocks_in_stored_order'],[0])
    def test_math_layers_vietnamese_super_sub_preserved(self):
        a=translated();m=a['messages'][-1]
        m['text']='Tiếng Việt: ∠ ∥ ⊥ ∈ ⊂ ≤ ≥ ∑ ∏ ∫ x² x₁ \\(a^2\\).'
        m['html']='<p>Tiếng Việt <sup>2</sup><sub>1</sub><span class="katex"><span class="katex-mathml"></span><span class="katex-html"></span></span></p>'
        m['blocks']=[{'tag':'P','text':m['text']}]
        m['formulas']=[{'representation':'latex_annotation','raw':r'\int_0^1 x^2 dx'}, {'representation':'data-tex','raw':r'\int_0^1 x^2 dx'}]
        session=CaptureSession(Page([baseline(),a,a]),self.source,self.generated.parent/'math-fixture')
        b=session.before_translation();session.after_translation(b,PROMPT);d=session.finalize(self.source,self.generated)
        r=verify_safely(d);inventory=r['representations']
        self.assertEqual(r['capture_status'],'CAPTURE_VALID');self.assertEqual(inventory['sup_tags'],1);self.assertEqual(inventory['sub_tags'],1)
        self.assertTrue(all(v==1 for v in inventory['symbols'].values()))
        self.assertEqual(d['translation']['text'],m['text']);self.assertEqual(d['translation']['formulas'][:2],m['formulas'])
        self.assertEqual(r['translation_status'],'TRANSLATION_UNVERIFIED')
    def test_unstable_response_abstains(self):
        self.d['translation']['capture_audit']['stable_after']['messages'][-1]['text']='changed'
        self.assertEqual(verify_safely(self.d)['capture_status'],'CAPTURE_UNVERIFIED')
    def test_region_hash_mismatch_abstains(self):
        self.d['region_qc']={'regions':{'source':[],'generated':[]}}
        self.assertEqual(verify_safely(self.d)['association_status'],'ASSOCIATION_UNVERIFIED')
    def test_reordered_blocks_abstain_even_with_recomputed_hash(self):
        self.d['translation']['blocks'][0]['order']=2;self.seal()
        self.assertEqual(verify_safely(self.d)['capture_status'],'CAPTURE_UNVERIFIED')
    def test_high_risk_hold_has_precedence(self):
        self.d['region_qc']={'high_risk':True};self.seal()
        self.assertEqual(verify_safely(self.d)['status'],'HIGH_RISK_HOLD')
    def test_wrong_generated_turn_and_old_provenance(self):
        for k in ('generated_message_id','dataset_sha256','page_id'):
            p=self.attest();p[k]=self.d['translation']['assistant_message_id'] if k=='generated_message_id' else 'old'
            self.assertEqual(verify_safely(self.d,provenance=p)['association_status'],'ASSOCIATION_UNVERIFIED')
    def reviewed(self):
        from layout_dataset import CHECKS
        self.d['region_qc']={'regions':{'source':[],'generated':[]},'warnings':[],'high_risk':False}
        self.seal()
        self.d['independent_reviews']=[{'verified':True,'reviewer':'independent fixture','basis':'synthetic whole page audit',
            'source_sha256':self.d['source_image']['sha256'],'generated_sha256':self.d['translated_image']['sha256'],
            'evidence_sha256':self.d['evidence_sha256'],'regions_sha256':self.d['regions_sha256'],
            'checks':{k:True for k in CHECKS}}]
        self.seal()
    def test_readiness_requires_capture_association_and_all_independent_checks(self):
        self.reviewed();r=verify_safely(self.d,provenance=self.attest())
        self.assertEqual(r['status'],'READY_FOR_PILOT');self.assertEqual(r['translation_status'],'TRANSLATION_VERIFIED')
        self.assertFalse(r['eligible_for_final_page']);self.assertFalse(r['blocks_batch'])
    def test_all_reviews_cannot_bypass_missing_live_association(self):
        self.reviewed();r=verify_safely(self.d)
        self.assertEqual(r['status'],'ASSOCIATION_UNVERIFIED');self.assertEqual(r['translation_status'],'TRANSLATION_UNVERIFIED')
    def test_capture_audit_conclusion_does_not_request_approval_or_claim_live(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        from layout_live_evidence import main
        output=self.source.parent/'offline-review'
        args=['layout_live_evidence.py','--dataset-root',str(self.source.parent),'--output',str(output),'--limit','3']
        with patch('sys.argv',args), redirect_stdout(StringIO()):main()
        report=json.loads((output/'verification.json').read_text(encoding='utf8'))
        self.assertEqual(report['conclusion'],'OFFLINE_CAPTURE_AUDIT_COMPLETED — LIVE_ORIGIN_UNVERIFIED')
        self.assertEqual(report['live_end_to_end_verified'],0)
        self.assertEqual(report['ready_for_pilot'],0)
    def test_malformed_artifact_nonblocking(self):
        r=verify_safely({'translation':{'capture_audit':{'after':None}}})
        self.assertFalse(r['blocks_batch']);self.assertEqual(r['status'],'EVIDENCE_INCOMPLETE')

class Page114OfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((Path(__file__).parent/'fixtures/layout_task2g_page114.json').read_text(encoding='utf8'))
    def audit(self): return copy.deepcopy(self.fixture['capture_audit'])
    def test_real_capture_missing_user_ids_is_candidate_only(self):
        from translation_evidence import audit_fallback, extract_translation
        a=self.audit(); original=copy.deepcopy(a)
        r=audit_fallback(a,corroboration=self.fixture['corroboration'])
        self.assertEqual(r['status'],'CAPTURE_CANDIDATE_UNVERIFIED')
        self.assertEqual(r['confidence_level'],'CORROBORATED_DOM_CANDIDATE')
        self.assertEqual(r['association_status'],'ASSOCIATION_UNVERIFIED'); self.assertFalse(r['verified'])
        self.assertIsNone(r['candidate']['user_message_id'])
        self.assertEqual(r['candidate']['assistant_message_id'],'3fd9af86-fcd4-427d-a94b-a7ea577a88dc')
        self.assertEqual(a,original)
        self.assertEqual(extract_translation(a['before'],a['after'],expected_prompt=PROMPT,complete=True)['status'],'EVIDENCE_INCOMPLETE')
    def test_real_snapshot_negative_mutations_abstain(self):
        from translation_evidence import audit_fallback
        for kind in ('conversation','old','baseline','id','prompt','streaming','unstable','session','duplicate','positional'):
            with self.subTest(kind=kind):
                a=self.audit();after=a['after']
                if kind=='conversation':after['conversation_url']='https://chatgpt.com/c/other'
                if kind=='old':after['messages']=copy.deepcopy(a['before']['messages'])
                if kind=='baseline':after['messages'][0]['text']='other page'
                if kind=='id':after['messages'][-1]['id']=a['before']['messages'][-1]['id']
                if kind=='prompt':after['messages'][-2]['text']=PROMPT+' '
                if kind=='streaming':after['generating']=True
                if kind=='session':a['capture_token']=''
                if kind=='duplicate':after['messages'][-1]['text']=a['before']['messages'][-1]['text']
                if kind=='positional':after['messages'][-2]['id']='fallback-turn-1:0:user'
                a['stable_after']=copy.deepcopy(after)
                if kind=='unstable':a['stable_after']['messages'][-1]['text']='changed'
                r=audit_fallback(a);self.assertEqual(r['status'],'CAPTURE_UNVERIFIED');self.assertIsNone(r['candidate'])
    def test_real_unicode_latex_html_unchanged_and_no_invented_math(self):
        from translation_evidence import structured_math, digest
        a=self.audit();before=digest(a);response=a['after']['messages'][-1]
        r=structured_math(response['html'],formulas=response['formulas'])
        self.assertEqual(digest(a),before);self.assertEqual(len(response['text']),2850)
        self.assertNotIn('\ufffd',response['text']);self.assertEqual(r['original_formulas'],response['formulas'])
        self.assertEqual(len(r['original_formulas']),66);self.assertTrue(r['formula_inventory_preserved'])
        self.assertEqual(r['math_nodes'],66);self.assertEqual(r['ambiguous_math_nodes'],0)
        nodes=[n for n in r['nodes'] if n['kind']=='math']
        self.assertEqual([n['latex_candidate'] for n in nodes],[f['raw'] for f in response['formulas']])
        self.assertTrue(all(n['raw_html'] in response['html'] and not n['verified'] for n in nodes))
        self.assertFalse(r['reading_order_verified']);self.assertFalse(r['eligible_for_final_page'])
    def test_real_corroboration_wrong_conversation_or_response_abstains(self):
        from translation_evidence import audit_fallback
        for kind in ('conversation','payload'):
            p=copy.deepcopy(self.fixture['corroboration'])
            if kind=='conversation':p['conversation_url']='https://chatgpt.com/c/other'
            else:p['messages'][3]['content_html']=p['messages'][3]['content_html'].replace('HÌNH','KHÁC',1)
            self.assertEqual(audit_fallback(self.audit(),corroboration=p)['status'],'CAPTURE_UNVERIFIED')
    def test_missing_or_conflicting_math_never_guessed(self):
        from translation_evidence import structured_math
        for html in ('<span class="katex">x+x</span>',
                     '<span class="katex" data-tex="x"><annotation encoding="application/x-tex">y</annotation></span>',
                     '<span class="katex"><annotation encoding="application/x-tex">x</annotation>',
                     '<span class="katex-display"><span class="katex" data-tex="x"></span><span class="katex" data-tex="x"></span></span>'):
            r=structured_math(html);n=next(n for n in r['nodes'] if n['kind']=='math')
            self.assertEqual(n['status'],'AMBIGUOUS');self.assertIsNone(n['latex_candidate'])
    def test_real_fixture_matches_persisted_audit_when_available(self):
        from translation_evidence import file_hash
        p=Path(__file__).resolve().parents[1]/self.fixture['source_artifact']
        if p.exists():
            self.assertEqual(file_hash(p),self.fixture['source_artifact_sha256'])
            self.assertEqual(json.loads(p.read_text(encoding='utf8'))['capture_audit'],self.audit())

class ImageObservationHardeningTests(unittest.TestCase):
    setUp = LiveEvidenceTests.setUp
    attest = LiveEvidenceTests.attest
    def test_claimed_id_without_observation_is_unverified(self):
        p=self.attest();p.pop('image_turn_observation')
        self.assertEqual(verify_safely(self.d,provenance=p)['association_status'],'ASSOCIATION_UNVERIFIED')
    def test_wrong_asset_parent_prompt_completion_never_verified(self):
        for kind in ('asset','parent','prompt','completion','download','reference'):
            p=self.attest();o=p['image_turn_observation']
            if kind=='asset':o['download']['download_asset_id']='other'
            if kind=='parent':o['translation_response_id']='old-response'
            if kind=='prompt':o['generation_prompt']='other'
            if kind=='completion':o['generation_complete']=False
            if kind=='download':o['download']['response_message_id']='old-image'
            if kind=='reference':o['evidence_reference']=''
            self.assertEqual(verify_safely(self.d,provenance=p)['association_status'],'ASSOCIATION_UNVERIFIED',kind)

if __name__=='__main__':unittest.main()
