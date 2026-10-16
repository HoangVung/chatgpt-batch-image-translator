"""Synthetic unit contracts do not adjudicate the real page-114 evidence."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from layout_review_validation import VERSION,CHECKS,POLICY,digest,manifest_digest,template,validate,readiness,check_order,cyclic,schema,file_hash
from layout_review_package import page,build,SCRIPT
ROOT=Path(__file__).resolve().parents[1]
FINAL=ROOT/'output/task3i-page114-20261012-final'

def contract(category='alignment'):
 e={'test_only':True,'adjacent_evidence_available':False,'decoded_pixels_exact':True}
 i={'item_id':'test:item','category':category,'bindings':{'source_image_sha256':'a'*64},'evidence':e,'evidence_sha256':digest(e),'available_evidence':{'test:primary':'b'*64},'required_evidence':['test:primary']}
 if category=='reading_order':i['order_scope']={'source_regions':['a','b']}
 m={'schema_version':VERSION,'items':[i],'inputs':{},'assets':{},'policy':POLICY};m['package_id']=manifest_digest(m);return m

def decision(m,value='ACCEPT',promote=False):
 t=template(m);r=t['reviews'][0];r.update(decision=value,reviewer='Synthetic unit reviewer',basis='Test only, not page114 evidence',reviewed_at='2026-10-12T10:00:00+07:00',evidence_references=['test:primary'])
 if promote:r['independent_human']=True;r['checks']={k:True for k in r['checks']}
 if r['category']=='reading_order':r['order']['sequences']={k:[v] for k,v in m['items'][0]['order_scope'].items()}
 return t

def state(m,t):return validate(m,[t])['items'][0]['state']

@pytest.mark.parametrize('category',list(CHECKS))
def test_pending(category):
 m=contract(category);t=template(m);assert t['reviews'][0]['decision'] is None;assert state(m,t)=='PENDING_REVIEW';assert not any(t['reviews'][0]['checks'].values())

@pytest.mark.parametrize('category,value,expected',[('alignment','ACCEPT','ACCEPTED_UNVERIFIED'),('alignment','REJECT','REJECTED'),('alignment','UNCERTAIN','UNCERTAIN'),('geometry','COMPLETE','ACCEPTED_UNVERIFIED'),('geometry','INCOMPLETE','REJECTED'),('geometry','UNCERTAIN','UNCERTAIN'),('reading_order','ACCEPT','ACCEPTED_UNVERIFIED'),('page_boundary','ACCEPT','ACCEPTED_UNVERIFIED')])
def test_decisions(category,value,expected):
 m=contract(category);assert state(m,decision(m,value))==expected

@pytest.mark.parametrize('key,value',[('reviewer',''),('basis',''),('reviewed_at',''),('reviewed_at','2026-10-12T10:00:00'),('evidence_references',[]),('evidence_references',['invented']),('checks',{'verified':True}),('independent_human',1),('order',{'sequences':[]}),('bindings',[]),('evidence_sha256','x')])
def test_invalid_identity_schema(key,value):
 m=contract();t=decision(m,promote=True);t['reviews'][0][key]=value;assert validate(m,[t])['status']=='INVALID_REVIEW';assert state(m,t)!='VERIFIED_BY_POLICY'

def test_verified_flag_rejected():
 m=contract();t=decision(m,promote=True);t['reviews'][0]['verified']=True;assert validate(m,[t])['status']=='INVALID_REVIEW'

@pytest.mark.parametrize('category,value',[('alignment','ACCEPT'),('geometry','COMPLETE'),('reading_order','ACCEPT')])
def test_scoped_policy(category,value):
 m=contract(category);assert state(m,decision(m,value,True))=='VERIFIED_BY_POLICY'

def test_boundary_needs_adjacent():
 m=contract('page_boundary');assert state(m,decision(m,promote=True))=='ACCEPTED_UNVERIFIED'

def test_geometry_not_semantics():
 m=contract('geometry');r=validate(m,[decision(m,'COMPLETE',True)])['items'][0];assert r['state']=='VERIFIED_BY_POLICY' and r['crop_complete_attested'] and not r['geometry_semantics_verified']

@pytest.mark.parametrize('key',['source_image_sha256','crop_sha256','ocr_dataset_sha256','source_transcription_sha256','translation_evidence_sha256','alignment_dataset_sha256'])
def test_binding_stale(key):
 m=contract();t=decision(m);t['reviews'][0]['bindings'][key]='c'*64;assert state(m,t)=='STALE_REVIEW'

def test_content_stale():
 m=contract();t=decision(m);t['reviews'][0]['evidence_sha256']='d'*64;assert state(m,t)=='STALE_REVIEW'

def test_package_stale():
 m=contract();t=decision(m);t['package_id']='d'*64;assert state(m,t)=='STALE_REVIEW'

@pytest.mark.parametrize('kind',['inputs','assets'])
def test_live_file_stale(tmp_path,kind):
 p=tmp_path/'source';p.write_bytes(b'raw');m=contract();m[kind]['source']={'path':str(p) if kind=='inputs' else 'source','sha256':file_hash(p)};m['package_id']=manifest_digest(m);t=decision(m);p.write_bytes(b'changed');assert validate(m,[t],tmp_path)['items'][0]['state']=='STALE_REVIEW'

def test_path_escape(tmp_path):
 m=contract();m['assets']['bad']={'path':'../other','sha256':'c'*64};m['package_id']=manifest_digest(m);assert validate(m,[],tmp_path)['status']=='STALE_REVIEW'

def test_manifest_tamper():
 m=contract();t=decision(m,promote=True);m['items'][0]['evidence']['test_only']=False;assert validate(m,[t])['status']=='INVALID_REVIEW';assert state(m,t)!='VERIFIED_BY_POLICY'

def test_conflicting_decisions():
 m=contract();report=validate(m,[decision(m,promote=True),decision(m,'REJECT')]);assert report['items'][0]['state']=='UNCERTAIN';assert report['status']=='INVALID_REVIEW'

def test_unknown_id():
 m=contract();t=decision(m);t['reviews'][0]['item_id']='missing';assert validate(m,[t])['status']=='INVALID_REVIEW'

@pytest.mark.parametrize('value',[None,[],{'verified':True},{'schema_version':VERSION,'package_id':'x','reviews':{}}])
def test_invalid_envelope(value):assert validate(contract(),[value])['status']=='INVALID_REVIEW'

@pytest.mark.parametrize('order,error',[
 ({'sequences':{'source_regions':[['a']]},'unresolved':[],'edges':[]},'Missing'),
 ({'sequences':{'source_regions':[['a','b','a']]},'unresolved':[],'edges':[]},'Duplicate'),
 ({'sequences':{'source_regions':[['a','b']]},'unresolved':[],'edges':[['b','a']]},'cycle'),
 ({'sequences':{'source_regions':[['a','c']]},'unresolved':[],'edges':[]},'Foreign'),
 ({'sequences':{'source_regions':[['a','b']]},'unresolved':[],'edges':[['a','c']]},'Invalid precedence')])
def test_order_errors(order,error):
 errors,_=check_order(order,{'source_regions':['a','b']});assert any(error in x for x in errors)

def test_unresolved_retained():
 m=contract('reading_order');t=decision(m,promote=True);t['reviews'][0]['order']={'sequences':{'source_regions':[['a']]},'unresolved':['b'],'edges':[]};assert state(m,t)=='ACCEPTED_UNVERIFIED'

def test_conflicting_accepted_orders():
 m=contract('reading_order');a=decision(m,promote=True);b=deepcopy(a);b['reviews'][0]['order']['sequences']['source_regions']=[['b','a']];assert validate(m,[a,b])['items'][0]['state']=='UNCERTAIN'

def test_cross_item_cycle():
 m=contract('reading_order');i=deepcopy(m['items'][0]);i['item_id']='test:other';m['items'].append(i);m['package_id']=manifest_digest(m);t=template(m)
 for n,r in enumerate(t['reviews']):
  sample=decision(m,promote=True)['reviews'][0];sample['item_id']=r['item_id'];sample['order']['sequences']['source_regions']=[['a','b'] if not n else ['b','a']];t['reviews'][n]=sample
 assert all(r['state']=='UNCERTAIN' for r in validate(m,[t])['items'])

def test_transitive_cycle():assert cyclic([('a','b'),('b','c'),('c','a')])

def test_split_blocks():
 errors,_=check_order({'sequences':{'translation_blocks':[['a'],['b']]},'unresolved':[],'edges':[]},{'translation_blocks':['a','b']});assert errors

def test_no_overwrite(tmp_path):
 target=tmp_path/'existing';target.mkdir();(target/'keep').write_text('keep')
 with pytest.raises(FileExistsError):build(ROOT,target)
 assert (target/'keep').read_text()=='keep'

def test_static_html():
 html=page('test','',contract(),'alignment','test');assert 'connect-src' in html and 'Blob' in html and 'URL.createObjectURL' in html;assert 'localStorage.' not in SCRIPT and 'fetch(' not in SCRIPT;assert 'selected' not in html and ' checked' not in html

def test_schema():
 s=schema();assert s['additionalProperties'] is False;assert 'verified' not in s['properties']['reviews']['items']['properties']

def test_real_package_preservation_pending():
 if not FINAL.is_dir():pytest.skip('Final package not yet built')
 m=json.loads((FINAL/'review-manifest.json').read_text(encoding='utf8'));report=validate(m,[],FINAL);gates=readiness(m,report)
 assert report['counts']=={'PENDING_REVIEW':19};assert gates['status']=='HYBRID_PREVIEW_BLOCKED_UNVERIFIED_ALIGNMENT'
 assert gates['gates']['content_preservation']['pass'] and not gates['gates']['math_integrity']['semantic_verified'];assert gates['gates']['translation_coverage']['unlocalized_blocks']==36
 assert not (FINAL/'hybrid-preview.png').exists();assert {c:sum(i['category']==c for i in m['items']) for c in CHECKS}=={'alignment':7,'reading_order':8,'page_boundary':1,'geometry':3}
 protected=json.loads((FINAL/'preservation-before.json').read_text(encoding='utf8'));assert all(file_hash(p)==sha for p,sha in protected.items())

@pytest.mark.parametrize('refs',[[],['not-in-manifest']])
def test_boundary_flag_is_not_adjacent_evidence(refs):
 m=contract('page_boundary');i=m['items'][0];i['evidence'].update(adjacent_evidence_available=True,adjacent_evidence_references=refs);i['evidence_sha256']=digest(i['evidence']);m['package_id']=manifest_digest(m);assert state(m,decision(m,promote=True))=='ACCEPTED_UNVERIFIED'


def partial_fixture(tmp_path):
 """Test-only copies in memory; never export an ACCEPT for the real package."""
 m=json.loads((FINAL/'review-manifest.json').read_text(encoding='utf8'));m['inputs']={};m['assets']={};m['synthetic_unit_scope']=True
 adjacent=tmp_path/'unit-adjacent.txt';adjacent.write_text('synthetic unit evidence, not a real page');sha=file_hash(adjacent)
 m['inputs']['test-adjacent']={'path':str(adjacent),'sha256':sha}
 i=next(i for i in m['items'] if i['item_id']=='boundary:114');i['evidence'].update(adjacent_evidence_available=True,adjacent_evidence_references=['test-adjacent']);i['evidence_sha256']=digest(i['evidence']);i['available_evidence']['test-adjacent']=sha;i['required_evidence'].append('test-adjacent')
 # Every item remains bound to its own current content and manifest ID.
 m['package_id']=manifest_digest(m);t=template(m)
 selected={'alignment:paragraph:0','order:paragraph:0','order:page:114','boundary:114'}
 for r in t['reviews']:
  if r['item_id'] not in selected:continue
  i=next(i for i in m['items'] if i['item_id']==r['item_id'])
  r.update(decision='ACCEPT',reviewer='Synthetic gate unit reviewer',basis='Unit contract only, no actual page114 adjudication',reviewed_at='2026-10-12T10:00:00+07:00',evidence_references=list(i['required_evidence']),independent_human=True,checks={k:True for k in r['checks']})
  if r['category']=='reading_order':r['order']['sequences']={k:[v] if v else [] for k,v in i['order_scope'].items()}
 return m,t,adjacent


def test_partial_gate_with_safe_fallback_unit_only(tmp_path):
 m,t,_=partial_fixture(tmp_path);report=validate(m,[t]);gates=readiness(m,report)
 assert report['counts']['VERIFIED_BY_POLICY']==4
 assert gates['selection']['verified_anchor_count']==1
 assert gates['status']=='ELIGIBLE_EXPERIMENTAL_HYBRID'
 assert gates['gates']['content_preservation']['pass'] and not gates['qualified_preview_created']
 assert gates['readiness']=='HIGH_RISK_HOLD' and not gates['ready_for_pilot']


@pytest.mark.parametrize('failure',['stale','separate_anchor_streams','different_renderer_order','no_global_review'])
def test_partial_gate_abstains(tmp_path,failure):
 m,t,adjacent=partial_fixture(tmp_path)
 if failure=='stale':adjacent.write_text('changed unit evidence')
 else:
  r=next(r for r in t['reviews'] if r['item_id']=='order:page:114')
  if failure=='separate_anchor_streams':r['order']['sequences']['source_regions']=[[x] for x in r['order']['sequences']['source_regions'][0]]
  elif failure=='different_renderer_order':r['order']['sequences']['translation_blocks'][0].reverse()
  else:r['decision']=None
 report=validate(m,[t]);gates=readiness(m,report)
 assert gates['selection']['verified_anchor_count']==0 and gates['status']=='HYBRID_PREVIEW_BLOCKED_UNVERIFIED_ALIGNMENT'


def test_saved_verified_labels_cannot_open_gate():
 m=json.loads((FINAL/'review-manifest.json').read_text(encoding='utf8'))
 for link in m['alignment']['links']:link.update(verification_status='ALIGNED_VERIFIED',eligible_for_anchor=True)
 for row in m['reading_order']['paragraph_links']:row['verification_status']='READING_ORDER_VERIFIED'
 m['package_id']=manifest_digest(m)
 assert readiness(m,validate(m))['selection']['verified_anchor_count']==0
