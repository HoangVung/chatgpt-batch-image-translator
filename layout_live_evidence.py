"""Offline capture/association audit. Never opens a browser or changes a batch."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from layout_dataset import assess_readiness
from translation_evidence import audit_fallback, digest, extract_translation, file_hash, structured_math

PROMPT='dịch bản chép lại'
SYMBOLS='∠∥⊥∈⊂≤≥∑∏∫'


def assess_image_observation(provenance, evidence):
    """Require a reviewable UI/download observation, not arbitrary image-turn IDs.

    This validates the independent review contract; it cannot attest live origin
    itself. No file name, timestamp, or locally computed hash substitutes for
    an observed UI asset -> download mapping.
    """
    p, e = provenance, evidence
    o = p.get('image_turn_observation') or {}
    download = o.get('download') or {}
    checks = {
        'reviewable_observation_reference': isinstance(o.get('evidence_reference'), str) and bool(o['evidence_reference'].strip()),
        'same_conversation_and_session': all(o.get(k) == e.get(k) and bool(e.get(k)) for k in ('conversation_url', 'capture_token')),
        'translation_parent_observed': bool(e.get('assistant_message_id')) and o.get('translation_response_id') == e.get('assistant_message_id'),
        'exact_generation_prompt': o.get('generation_prompt') == 'Tạo ảnh với bản dịch',
        'completed_image_response': o.get('generation_complete') is True,
        'distinct_observed_turn_ids': all(isinstance(o.get(k), str) and bool(o[k].strip()) and not o[k].startswith('fallback-turn-') for k in ('generation_user_message_id', 'generated_message_id'))
            and len({o.get('generation_user_message_id'), o.get('generated_message_id'), e.get('assistant_message_id'), e.get('user_message_id')}) == 4,
        'reviewed_generated_message_id': bool(p.get('generated_message_id')) and o.get('generated_message_id') == p.get('generated_message_id'),
        'download_response_binding': bool(o.get('generated_message_id')) and download.get('response_message_id') == o.get('generated_message_id'),
        'observed_ui_asset_download_mapping': isinstance(download.get('ui_asset_id'), str) and bool(download['ui_asset_id'].strip()) and download.get('download_asset_id') == download.get('ui_asset_id'),
        'download_bytes_binding': bool(e.get('generated_sha256')) and download.get('sha256') == e.get('generated_sha256'),
    }
    return {'status': 'REVIEWED_OBSERVATION_BOUND' if all(checks.values()) else 'ASSOCIATION_UNVERIFIED',
            'verified': False, 'checks': checks,
            'missing': ['Missing image-turn evidence: '+k for k,v in checks.items() if not v],
            'scope': 'Independent observation contract only; no automatic live verification'}


def verify_dataset(d, *, provenance=None, corroboration=None):
    """Hashes prove integrity, not provider origin or mathematical correctness."""
    capture_errors=[]; association_errors=[]
    e=d.get('translation') or {}; audit=e.get('capture_audit')
    result={'capture_status':'CAPTURE_UNVERIFIED','association_status':'ASSOCIATION_UNVERIFIED',
            'status':'EVIDENCE_INCOMPLETE','translation_status':'TRANSLATION_UNVERIFIED',
            'live_origin_verified':False,'blocks_batch':False,'eligible_for_final_page':False}
    result['fallback_capture'] = audit_fallback(audit, evidence=e, corroboration=corroboration)
    candidate = result['fallback_capture'].get('candidate')
    if candidate:
        result['structured_math'] = structured_math(candidate.get('html'), formulas=candidate['formulas'])
    elif isinstance(e.get('html'), str):
        result['structured_math'] = structured_math(e['html'], formulas=e.get('formulas', []))
    if not isinstance(audit,dict):capture_errors.append('No persisted baseline/stable response audit (legacy artifact)')
    else:
        if e.get('capture_audit_sha256')!=digest(audit):capture_errors.append('Capture audit hash mismatch')
        if audit.get('expected_prompt')!=PROMPT:capture_errors.append('Wrong translation prompt')
        if audit.get('after')!=audit.get('stable_after'):capture_errors.append('Response not stable')
        derived=extract_translation(audit.get('before'),audit.get('after'),expected_prompt=PROMPT,complete=True)
        if derived.get('status')!='COLLECTED_UNVERIFIED':capture_errors.extend(derived['reasons'])
        elif any(derived.get(k)!=e.get(k) for k in ('text','html','blocks','formulas','text_sha256','response_sha256','conversation_url','user_message_id','assistant_message_id')):
            capture_errors.append('Persisted response/IDs differ from captured turn')
        for k in ('capture_token','page_session_id','batch_id','page_id','source_path','source_sha256'):
            if not isinstance(audit.get(k),str) or not audit[k] or audit[k]!=e.get(k):association_errors.append('Missing/mismatched '+k)
        if audit.get('origin')!='worker_dom_capture_unattested':association_errors.append('Unsupported capture origin')
    if e.get('status')!='COLLECTED_UNVERIFIED':capture_errors.append('No completed translation evidence')
    if d.get('evidence_sha256')!=digest(e):association_errors.append('Evidence hash mismatch')
    if d.get('regions_sha256')!=digest(d.get('region_qc')):association_errors.append('Region QC hash mismatch')
    payload={k:v for k,v in d.items() if k!='dataset_sha256'}
    if d.get('dataset_sha256')!=digest(payload):association_errors.append('Dataset hash mismatch')
    for key,ek,pathkey in (('source_image','source_sha256','source_path'),('translated_image','generated_sha256','generated_path')):
        im=d.get(key) or {}
        try:
            path=Path(im['path']).resolve()
            if file_hash(path)!=im.get('sha256'):association_errors.append(key+' current image hash mismatch')
            if e.get(ek)!=im.get('sha256') or not e.get(pathkey) or Path(e[pathkey]).resolve()!=path:association_errors.append(key+' response binding mismatch')
        except (OSError,KeyError,TypeError,ValueError):association_errors.append(key+' image/path unavailable')
    if e.get('association')!='same_page_worker_capture_session':association_errors.append('Missing worker association boundary')
    # A DOM snapshot is also reproducible by fixtures. Require explicit, hash-bound
    # independent provenance and image-turn review before calling association verified.
    p=provenance or {}
    image_observation = assess_image_observation(p, e)
    result['image_generation_association'] = image_observation
    association_errors.extend(image_observation['missing'])
    attested=(image_observation['status'] == 'REVIEWED_OBSERVATION_BOUND' and p.get('live_observed') is True and p.get('image_turn_pairing_verified') is True
              and p.get('dataset_sha256')==d.get('dataset_sha256')
              and all(isinstance(p.get(k),str) and p[k].strip() for k in ('reviewer','basis','generated_message_id'))
              and p.get('generated_message_id') not in (e.get('user_message_id'),e.get('assistant_message_id'))
              and all(p.get(k)==e.get(k) and bool(e.get(k)) for k in
                      ('conversation_url','user_message_id','assistant_message_id','capture_token',
                       'source_sha256','generated_sha256','response_sha256','batch_id','page_id')))
    if not attested:association_errors.append('No independent live-origin and generated-image turn attestation')
    result['live_origin_verified']=bool(attested and not capture_errors and not association_errors)
    if not capture_errors:result['capture_status']='CAPTURE_VALID'
    if not capture_errors and not association_errors:result['association_status']='ASSOCIATION_VERIFIED'
    text=e.get('text')
    if isinstance(text,str):
        result['representations']={'utf8_sha256':hashlib.sha256(text.encode('utf8')).hexdigest(),
            'symbols':{s:text.count(s) for s in SYMBOLS},'replacement_characters':text.count('\ufffd'),
            'blocks_in_stored_order':[b.get('order') for b in e.get('blocks',[])],
            'formula_representations':e.get('formulas',[]),'sup_tags':(e.get('html') or '').lower().count('<sup'),
            'sub_tags':(e.get('html') or '').lower().count('<sub'),
            'katex_layers':(e.get('html') or '').count('katex'),
            'scope':'Inventory only; absence/duplicates are not corrected or certified'}
        if '\ufffd' in text:capture_errors.append('Unicode replacement character needs source review')
        if [b.get('order') for b in e.get('blocks',[])]!=list(range(len(e.get('blocks',[])))):capture_errors.append('Stored block order is inconsistent')
    if capture_errors:result['capture_status']='CAPTURE_UNVERIFIED';result['live_origin_verified']=False;result['association_status']='ASSOCIATION_UNVERIFIED'
    readiness=assess_readiness(d)
    if readiness['status']=='HIGH_RISK_HOLD':result['status']='HIGH_RISK_HOLD'
    elif capture_errors:result['status']='EVIDENCE_INCOMPLETE'
    elif association_errors:result['status']='ASSOCIATION_UNVERIFIED'
    else:result['status']=readiness['status']
    result['capture_errors']=capture_errors;result['association_errors']=association_errors
    result['missing_readiness']=readiness.get('missing',[])
    # Content review stays separate from successful byte/turn capture.
    result['independent_checks']=readiness.get('verified_checks',{})
    if result['independent_checks'].get('translation') is True and result['association_status']=='ASSOCIATION_VERIFIED':result['translation_status']='TRANSLATION_VERIFIED'
    return result


def verify_safely(d, **kw):
    try:return verify_dataset(d,**kw)
    except Exception as exc:
        return {'capture_status':'CAPTURE_UNVERIFIED','association_status':'ASSOCIATION_UNVERIFIED',
                'status':'EVIDENCE_INCOMPLETE','translation_status':'TRANSLATION_UNVERIFIED',
                'live_origin_verified':False,'blocks_batch':False,'eligible_for_final_page':False,
                'capture_errors':['Malformed evidence: '+type(exc).__name__]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--limit',type=int,default=5)
    parser.add_argument('--provenance',type=Path,help='Independent attestations JSON; never generated automatically')
    parser.add_argument('--corroboration',type=Path,help='Previously saved UI observation; offline only')
    args=parser.parse_args()
    if not 1<=args.limit<=5:parser.error('--limit must be between 1 and 5')
    if not args.dataset_root.is_dir():parser.error('Dataset root does not exist')
    if args.output.exists():parser.error('Output must be a new directory')
    files=sorted(args.dataset_root.rglob('dataset.json'))
    # Audit prospective live datasets first; otherwise show bounded legacy gaps.
    loaded=[(p,json.loads(p.read_text(encoding='utf8'))) for p in files]
    loaded.sort(key=lambda row: not bool((row[1].get('translation') or {}).get('capture_audit')))
    corroboration=None if not args.corroboration else json.loads(args.corroboration.read_text(encoding='utf8'))
    attestations=[] if not args.provenance else json.loads(args.provenance.read_text(encoding='utf8'))['attestations']
    before={str(p):file_hash(p) for p,_ in loaded}
    associations={}
    for _,d in loaded:
        key=((d.get('source_image') or {}).get('sha256'),(d.get('translated_image') or {}).get('sha256'))
        associations.setdefault(key,set()).add(d.get('evidence_sha256'))
    rows=[]
    for p,d in loaded[:args.limit]:
        matches=[a for a in attestations if a.get('dataset_sha256')==d.get('dataset_sha256')]
        provenance=matches[0] if len(matches)==1 else None
        r=verify_safely(d,provenance=provenance,corroboration=corroboration)
        event_path=p.parent.parent/'provenance-events.jsonl'
        if event_path.is_file():
            r['event_provenance']=audit_provenance_file(event_path,source=(d.get('source_image') or {}).get('path'),generated=(d.get('translated_image') or {}).get('path'))
        key=((d.get('source_image') or {}).get('sha256'),(d.get('translated_image') or {}).get('sha256'))
        if len(associations[key])>1:
            r['association_status']='ASSOCIATION_UNVERIFIED';r['live_origin_verified']=False
            r.setdefault('association_errors',[]).append('Multiple distinct evidence records bind the same image hashes')
            r['translation_status']='TRANSLATION_UNVERIFIED'
            if r['status']!='HIGH_RISK_HOLD':r['status']='ASSOCIATION_UNVERIFIED'
        rows.append({'dataset':str(p.resolve()),'dataset_sha256':d.get('dataset_sha256'),**r})
    unchanged=all(file_hash(p)==h for p,h in before.items())
    report={'conclusion':'IMPLEMENTED — LIVE_VERIFICATION_PENDING_USER_APPROVAL',
        'datasets_discovered':len(files),'audited_pairs':len(rows),
        'live_end_to_end_verified':sum(r['live_origin_verified'] and r['association_status']=='ASSOCIATION_VERIFIED' for r in rows),
        'ready_for_pilot':sum(r['status']=='READY_FOR_PILOT' for r in rows),
        'input_datasets_unchanged':unchanged,'rows':rows,
        'limits':['Offline audit does not establish a logged-in provider session.',
                  'Source/generated pixel hashes and worker boundary cannot prove generated image belongs to the translation turn.',
                  'KaTeX layers, mathematical meaning, geometry labels and whole-page reading order require independent review.']}
    if any(isinstance((d.get('translation') or {}).get('capture_audit'),dict) for _,d in loaded[:args.limit]):
        report['conclusion']='OFFLINE_CAPTURE_AUDIT_COMPLETED — LIVE_ORIGIN_UNVERIFIED'
    if report['live_end_to_end_verified']:
        report['conclusion']='OFFLINE_REAL_ARTIFACT_AUDIT_COMPLETED'
    args.output.mkdir(parents=True)
    (args.output/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    (args.output/'provenance.example.json').write_text(json.dumps({'attestations':[],'required_fields':{'dataset_sha256':'exact dataset hash','reviewer':'independent reviewer','basis':'observed real session, source page and generation turn IDs/artifact mapping','live_observed':True,'image_turn_pairing_verified':True,
        'conversation_url':'exact captured conversation','user_message_id':'translation prompt ID',
        'assistant_message_id':'translation response ID','generated_message_id':'independently observed image-generation response ID',
        'capture_token':'exact token','source_sha256':'exact source hash','generated_sha256':'exact image hash',
        'response_sha256':'exact response hash','batch_id':'exact batch identity','page_id':'exact source page identity',
        'image_turn_observation':{'evidence_reference':'saved UI observation/event record independently reviewed',
            'conversation_url':'exact conversation', 'capture_token':'same processing session',
            'translation_response_id':'observed parent translation response',
            'generation_prompt':'Tạo ảnh với bản dịch', 'generation_user_message_id':'observed stable generation prompt ID',
            'generated_message_id':'observed stable image response ID', 'generation_complete':True,
            'download':{'response_message_id':'same image response ID', 'ui_asset_id':'observed UI asset identity',
                'download_asset_id':'same identity from observed download event', 'sha256':'exact downloaded bytes hash'}}}},ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('rows','limits')},ensure_ascii=False))




def audit_provenance_events(events, *, source=None, generated=None, translation_capture=None):
    """Offline event consistency only, never live-origin/association VERIFIED."""
    result = {'status':'PROVENANCE_UNVERIFIED','verified':False,
              'association_status':'ASSOCIATION_UNVERIFIED','eligible_for_final_page':False,
              'errors':[], 'observed_chain':{},
              'scope':'Self-recorded event/DOM consistency; independent live review still required'}
    errors=result['errors']
    from translation_evidence import PROVENANCE_PHASES, sanitize_identity_snapshot
    if not isinstance(events,list) or not 0<len(events)<=64:
        errors.append('Missing or oversized event log');return result
    # Repeated attempts are retained for review, but cannot silently select one.
    # A later evaluator may adjudicate retry chains; this minimal pilot is one attempt.
    if [e.get('phase') for e in events if isinstance(e,dict)] != list(PROVENANCE_PHASES):
        errors.append('Missing, repeated or reordered phase; retry chain requires review');return result
    base=events[0];previous=None;timestamps=[]
    for i,e in enumerate(events):
        if not isinstance(e,dict):errors.append('Malformed event');return result
        if e.get('event_sha256') != digest({k:v for k,v in e.items() if k!='event_sha256'}):errors.append('Event hash mismatch')
        if e.get('previous_event_sha256')!=previous:errors.append('Event chain mismatch')
        previous=e.get('event_sha256')
        if e.get('sequence')!=i or e.get('snapshot_reference')!='provenance-events.jsonl#'+str(i):errors.append('Snapshot reference/sequence mismatch')
        snapshot=e.get('snapshot') or {}
        if e.get('snapshot_sha256')!=digest(snapshot):errors.append('Snapshot hash mismatch')
        if snapshot!=sanitize_identity_snapshot(snapshot):errors.append('Unrecognized or unsafe snapshot metadata')
        if snapshot.get('status')!='OBSERVED' or any(m.get('metadata_truncated') for m in snapshot.get('messages',[])):errors.append('Incomplete metadata observation')
        if snapshot.get('conversation_url')!=e.get('conversation_url'):errors.append('Snapshot/event conversation mismatch')
        if not isinstance(e.get('conversation_url'),str) or not __import__('re').fullmatch(r'https://(?:chatgpt\.com|chat\.openai\.com)/c/[A-Za-z0-9_-]+',e['conversation_url']):errors.append('Conversation NOT_OBSERVED')
        for k in ('capture_token','page_session_id','batch_id','page_id','source_path','source_sha256','conversation_url','translation_attempt_token'):
            if not isinstance(e.get(k),str) or e[k] in ('','NOT_OBSERVED') or e[k]!=base.get(k):errors.append('Session/source/conversation mismatch: '+k)
        from datetime import datetime
        try:
            dt=datetime.fromisoformat(e['event_timestamp'])
            if dt.tzinfo is None:raise ValueError()
            timestamps.append(dt)
        except (KeyError,TypeError,ValueError):errors.append('Timestamp NOT_OBSERVED')
    if timestamps!=sorted(timestamps):errors.append('Event timestamps out of order')
    for i,prompt in ((0,PROMPT),(1,PROMPT),(3,'Tạo ảnh với bản dịch'),(4,'Tạo ảnh với bản dịch')):
        if events[i].get('prompt')!=prompt or events[i].get('prompt_sha256')!=hashlib.sha256(prompt.encode('utf8')).hexdigest():errors.append('Exact prompt/hash mismatch')
    generation=events[3].get('generation_attempt_token')
    if not isinstance(generation,str) or generation in ('','NOT_OBSERVED') or any(e.get('generation_attempt_token')!=generation for e in events[3:]):errors.append('Generation attempt token mismatch')
    def messages(i):return events[i]['snapshot']['messages']
    def signature(rows):return [(m['role'],m['identity']) for m in rows]
    def new_pair(before,sent,complete,label):
        old,post=messages(before),messages(complete)
        if len(post)!=len(old)+2 or signature(post[:len(old)])!=signature(old):
            errors.append(label+' baseline changed/old response/ambiguous pair');return None,None
        user,response=post[-2:]
        if user['role']!='user' or response['role']!='assistant':errors.append(label+' role mismatch')
        ids=[m['identity'].get('value') for m in (user,response)]
        if any(m['identity']['status']!='OBSERVED' or not m['identity']['value'] for m in (user,response)):errors.append(label+' stable user/response identity NOT_OBSERVED')
        if any(ident and ident in {m['identity'].get('value') for m in old} for ident in ids) or ids[0]==ids[1]:errors.append(label+' old/reused identity')
        sent_rows=messages(sent)
        if len(sent_rows)<len(old)+1 or signature(sent_rows[:len(old)])!=signature(old) or signature(sent_rows[len(old):len(old)+1])!=signature([user]):errors.append(label+' sent/completed identity changed')
        if len(sent_rows)>len(old)+2 or (len(sent_rows)==len(old)+2 and signature(sent_rows[-1:])!=signature([response])):errors.append(label+' response identity changed during send')
        if events[complete]['snapshot'].get('generating') is not False:errors.append(label+' completion not observed idle')
        parent=response['parent_identity']
        if parent['status']!='OBSERVED' or parent['value']!=ids[0]:errors.append(label+' response parent NOT_OBSERVED/mismatch')
        return ids[0],ids[1]
    tu,ta=new_pair(0,1,2,'Translation')
    gu,ga=new_pair(3,4,5,'Generation')
    if messages(5) and len(messages(5)) >= 2:
        generation_parent=messages(5)[-2]['parent_identity']
        if generation_parent['status']!='OBSERVED' or generation_parent['value']!=ta:
            errors.append('Generation user parent translation NOT_OBSERVED/mismatch')
    if signature(messages(2))!=signature(messages(3)):errors.append('Translation -> generation baseline mismatch')
    if signature(messages(5))!=signature(messages(6)):errors.append('Generation -> download message identity changed')
    if ta and ta in (gu,ga):errors.append('Translation response reused for generation')
    assets=[]
    for i in (5,6):
        matches=[(m,image) for m in messages(i) for image in m['images'] if image.get('selected_resource')]
        if len(matches)!=1:errors.append('Selected download resource not uniquely linked to UI response');assets.append(None);continue
        m,image=matches[0];asset=image['asset_identity']
        if m['identity'].get('value')!=ga or image['response_identity'].get('value')!=ga:errors.append('Download not linked to generation response')
        if asset['status']!='OBSERVED' or not asset['value']:errors.append('UI asset identity NOT_OBSERVED')
        assets.append(asset['value'])
    if len(assets)==2 and (not assets[0] or assets[0]!=assets[1]):errors.append('UI asset identity changed/missing at download')
    if not events[5].get('selected_resource_sha256') or events[5].get('selected_resource_sha256')!=events[6].get('selected_resource_sha256'):errors.append('Selected resource locator mismatch')
    download=events[6].get('download') or {}
    for path,expected,label in ((source,base.get('source_sha256'),'Source'),(generated,download.get('sha256'),'Generated')):
        try:
            if path is None or file_hash(path)!=expected:errors.append(label+' current hash mismatch/unavailable')
            recorded=base.get('source_path') if label=='Source' else download.get('path')
            if not recorded or Path(recorded).resolve()!=Path(path).resolve():errors.append(label+' path mismatch')
        except (OSError,TypeError,ValueError):errors.append(label+' current file unavailable')
    capture=events[2].get('translation_capture') or {}
    try:
        cp=Path(translation_capture)
        if cp.name!=capture.get('reference') or file_hash(cp)!=capture.get('sha256'):errors.append('Translation capture reference/hash mismatch')
        evidence=json.loads(cp.read_text(encoding='utf8'));audit=evidence.get('capture_audit') or {}
        if capture.get('capture_audit_sha256')!=digest(audit) or evidence.get('capture_audit_sha256')!=digest(audit):errors.append('Translation capture audit hash mismatch')
        if audit.get('after')!=audit.get('stable_after'):errors.append('Translation capture not stable')
        if audit.get('expected_prompt')!=PROMPT or (audit.get('after') or {}).get('conversation_url')!=base.get('conversation_url'):errors.append('Translation capture prompt/conversation mismatch')
        for k in ('source_sha256','capture_token','page_session_id','batch_id','page_id','source_path'):
            if audit.get(k)!=base.get(k):errors.append('Translation capture session binding mismatch: '+k)
        raw=(audit.get('after') or {}).get('messages') or []
        if len(raw)<2 or raw[-1].get('id')!=ta or raw[-2].get('text')!=PROMPT:errors.append('Translation capture response binding mismatch')
    except (OSError,TypeError,ValueError):errors.append('Translation capture NOT_OBSERVED/unavailable')
    result['observed_chain']={'translation_user_id':tu,'translation_response_id':ta,
        'generation_user_id':gu,'generation_response_id':ga,'asset_id':assets[0] if assets else None,
        'download':download,'capture_token':base.get('capture_token')}
    if not errors:result['status']='EVENT_CHAIN_CONSISTENT_UNVERIFIED'
    result['errors']=list(dict.fromkeys(errors))
    return result


def audit_provenance_safely(events, **kwargs):
    try:return audit_provenance_events(events,**kwargs)
    except Exception as exc:
        return {'status':'PROVENANCE_UNVERIFIED','verified':False,'association_status':'ASSOCIATION_UNVERIFIED',
                'eligible_for_final_page':False,'errors':['Malformed provenance: '+type(exc).__name__]}


def audit_provenance_file(path, **kwargs):
    """Bound the reader as well as the writer; never modifies historical logs."""
    try:
        if Path(path).stat().st_size > 4*1024*1024:raise ValueError('Oversized event log')
        events=[json.loads(line) for line in Path(path).read_text(encoding='utf8').splitlines() if line]
        reference=(events[2].get('translation_capture') or {}).get('reference') if len(events)>2 else None
        if isinstance(reference,str) and Path(reference).name==reference and reference not in ('.','..','NOT_OBSERVED'):
            kwargs['translation_capture']=Path(path).parent/reference
        return audit_provenance_safely(events,**kwargs)
    except Exception as exc:
        return {'status':'PROVENANCE_UNVERIFIED','verified':False,'association_status':'ASSOCIATION_UNVERIFIED',
                'eligible_for_final_page':False,'errors':['Unreadable provenance: '+type(exc).__name__]}


if __name__=='__main__':main()
