"""Offline review contracts. Human decisions and policy verification are distinct.

No renderer, provider, worker, OCR, or production integration. Identity is a human
attestation, not authentication; policy verification is limited to the item scope.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
from pathlib import Path

VERSION = 'task3i-review-v1'
BLOCKED = 'HYBRID_PREVIEW_BLOCKED_UNVERIFIED_ALIGNMENT'
CHECKS = {
 'alignment': ['page_pairing', 'bbox_content', 'translation_content', 'all_scoped_math_compared'],
 'reading_order': ['source_order', 'translation_order', 'all_scoped_math_order', 'all_regions_accounted'],
 'page_boundary': ['identifier_vs_printed_number', 'first_last_lines', 'adjacent_page_membership', 'continuation_note_support'],
 'geometry': ['figure_extent', 'all_point_labels', 'caption', 'no_adjacent_prose', 'pixel_fidelity', 'source_figure_content'],
}
POLICY = {
 'id': VERSION,
 'identity': 'Named human attests independence from candidate creation; offline identity is not authenticated.',
 'promotion': 'ACCEPT (or geometry COMPLETE) + current exact bindings/content + reason/time/evidence + independent human attestation + every scoped check true + cited primary evidence. No confidence threshold or verified flag.',
 'order': 'All scoped IDs accounted exactly once; no unresolved IDs for promotion; no missing/foreign IDs, duplicate placement, conflicting precedence, or cycles. Candidate order is never a decision.',
 'boundary': 'Adjacent-page evidence must already exist in the package and be explicitly cited; a note or page number alone cannot verify membership.',
 'geometry': 'COMPLETE concerns crop extent only. source_figure_content requires comparison with the full source. This does not certify the mathematical theorem/geometry semantics.',
 'limits': 'VERIFIED_BY_POLICY is a scoped, human-attested offline result, not provider provenance, release approval, or mathematical proof. Existing HIGH_RISK_HOLD is retained.',
}
RECORD_FIELDS = {'item_id','category','decision','reviewer','basis','evidence_references','reviewed_at','notes','bindings','evidence_sha256','independent_human','checks','order'}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def manifest_digest(manifest):return digest({k:v for k,v in manifest.items() if k!='package_id'})


def template(manifest):
    return {'schema_version':VERSION,'package_id':manifest['package_id'],'reviews':[
      {'item_id':i['item_id'],'category':i['category'],'decision':None,'reviewer':'','basis':'',
       'evidence_references':[],'reviewed_at':'','notes':'','bindings':deepcopy(i['bindings']),
       'evidence_sha256':i['evidence_sha256'],'independent_human':False,
       'checks':{k:False for k in CHECKS[i['category']]},
       'order':{'sequences':{},'unresolved':[],'edges':[]}} for i in manifest['items']]}


def schema():
    string={'type':'string'}
    record={'type':'object','additionalProperties':False,'required':sorted(RECORD_FIELDS), 'properties':{
      'item_id':string,'category':{'enum':list(CHECKS)},'decision':{'enum':[None,'ACCEPT','REJECT','UNCERTAIN','COMPLETE','INCOMPLETE']},
      'reviewer':string,'basis':string,'evidence_references':{'type':'array','uniqueItems':True,'items':string},'reviewed_at':string,'notes':string,
      'bindings':{'type':'object','additionalProperties':{'type':'string','pattern':'^[0-9a-f]{64}$'}},
      'evidence_sha256':{'type':'string','pattern':'^[0-9a-f]{64}$'},'independent_human':{'type':'boolean'},
      'checks':{'type':'object','additionalProperties':{'type':'boolean'}},
      'order':{'type':'object','additionalProperties':False,'required':['sequences','unresolved','edges'],'properties':{
       'sequences':{'type':'object','additionalProperties':{'type':'array','items':{'type':'array','items':string}}},
       'unresolved':{'type':'array','uniqueItems':True,'items':string},
       'edges':{'type':'array','items':{'type':'array','minItems':2,'maxItems':2,'items':string}}}}}}
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'urn:task3i:offline-review',
      'type':'object','additionalProperties':False,'required':['schema_version','package_id','reviews'],
      'properties':{'schema_version':{'const':VERSION},'package_id':{'type':'string','pattern':'^[0-9a-f]{64}$'},'reviews':{'type':'array','items':record}}}


def cyclic(edges):
    graph=defaultdict(set);indegree=Counter()
    for a,b in set(map(tuple,edges)):
        graph[a].add(b);indegree[b]+=1;indegree.setdefault(a,0)
    ready=[n for n,v in indegree.items() if not v];seen=0
    while ready:
        a=ready.pop();seen+=1
        for b in graph[a]:
            indegree[b]-=1
            if not indegree[b]:ready.append(b)
    return seen != len(indegree)


def check_order(value,scope):
    errors=[];edges=[];covered=[]
    if not isinstance(value,dict) or set(value)!={'sequences','unresolved','edges'}:return ['Invalid order object'],[]
    sequences=value['sequences'];unresolved=value['unresolved'];explicit=value['edges']
    if not isinstance(sequences,dict) or not isinstance(unresolved,list) or not isinstance(explicit,list):return ['Invalid order field types'],[]
    allowed={x for ids in scope.values() for x in ids}
    for key,streams in sequences.items():
        if key not in scope or not isinstance(streams,list):errors.append('Unknown order scope or non-array streams');continue
        if key!='source_regions' and len(streams)>1:errors.append('Block/math scope needs one ordered stream; use unresolved for ambiguity')
        for seq in streams:
            if not isinstance(seq,list) or not all(isinstance(x,str) for x in seq):errors.append('Invalid sequence');continue
            if any(x not in scope[key] for x in seq):errors.append('Foreign ID in sequence')
            covered.extend(seq);edges.extend(zip(seq,seq[1:]))
    if not all(isinstance(x,str) for x in unresolved):errors.append('Invalid unresolved IDs')
    else:covered.extend(unresolved)
    if all(isinstance(x,str) for x in covered):
        if len(covered)!=len(set(covered)):errors.append('Duplicate region placement')
        if set(covered)!=allowed:errors.append('Missing or foreign regions')
    for pair in explicit:
        if not isinstance(pair,list) or len(pair)!=2 or not all(isinstance(x,str) and x in allowed for x in pair):errors.append('Invalid precedence edge')
        else:edges.append(tuple(pair))
    if cyclic(edges):errors.append('Reading-order cycle')
    return errors,edges


def record_errors(r,item):
    if not isinstance(r,dict):return ['Review must be an object']
    errors=[]
    if set(r)!=RECORD_FIELDS:errors.append('Schema fields missing or unknown (verified flags are not accepted)')
    for k in ['item_id','category','reviewer','basis','reviewed_at','notes','evidence_sha256']:
        if not isinstance(r.get(k),str):errors.append('Invalid string: '+k)
    if r.get('category')!=item['category']:errors.append('Category does not match item')
    allowed=[None,'COMPLETE','INCOMPLETE','UNCERTAIN'] if item['category']=='geometry' else [None,'ACCEPT','REJECT','UNCERTAIN']
    if r.get('decision') not in allowed:errors.append('Invalid decision for category')
    if type(r.get('independent_human')) is not bool:errors.append('Invalid independence attestation')
    if not isinstance(r.get('bindings'),dict) or any(not isinstance(k,str) or not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for k,v in r.get('bindings',{}).items()):errors.append('Invalid bindings')
    if not isinstance(r.get('evidence_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',r['evidence_sha256']):errors.append('Invalid evidence hash')
    checks=r.get('checks')
    if not isinstance(checks,dict) or set(checks)!=set(CHECKS[item['category']]) or any(type(v) is not bool for v in checks.values()):errors.append('Invalid scoped checks')
    refs=r.get('evidence_references')
    if not isinstance(refs,list) or not all(isinstance(x,str) for x in refs):errors.append('Invalid evidence references');refs=[]
    elif len(refs)!=len(set(refs)):errors.append('Duplicate evidence references')
    if any(x not in item['available_evidence'] for x in refs):errors.append('Unknown evidence reference')
    # Validate order object schema even for a pending/non-order record.
    order=r.get('order')
    if not isinstance(order,dict) or set(order)!={'sequences','unresolved','edges'}:errors.append('Invalid order object')
    elif item['category']!='reading_order' and order!={'sequences':{},'unresolved':[],'edges':[]}:errors.append('Order data on non-order item')
    elif item['category']=='reading_order':
        if not isinstance(order['sequences'],dict) or not isinstance(order['unresolved'],list) or not all(isinstance(x,str) for x in order['unresolved']) or not isinstance(order['edges'],list):errors.append('Invalid order field types')
        elif any(not isinstance(k,str) or not isinstance(streams,list) or any(not isinstance(seq,list) or not all(isinstance(x,str) for x in seq) for seq in streams) for k,streams in order['sequences'].items()) or any(not isinstance(pair,list) or len(pair)!=2 or not all(isinstance(x,str) for x in pair) for pair in order['edges']):errors.append('Invalid order sequence/edge schema')
    if r.get('decision') is not None:
        if not all(isinstance(r.get(k),str) and r[k].strip() for k in ['reviewer','basis','reviewed_at']):errors.append('Reviewer, basis, and timestamp required')
        if not refs:errors.append('Evidence reference required')
        try:
            dt=datetime.fromisoformat(r.get('reviewed_at','').replace('Z','+00:00'))
            if dt.tzinfo is None:errors.append('Review timestamp must include timezone')
        except (ValueError,TypeError):errors.append('Invalid review timestamp')
    return errors


def validate(manifest,submissions=(),package_dir=None):
    """Rehash every input/asset on every import; never update submitted decisions."""
    errors=[];stale=[];items=manifest.get('items',[]);by_id={i['item_id']:i for i in items}
    if len(items)!=len(by_id):errors.append('Duplicate manifest item IDs')
    if manifest.get('package_id')!=manifest_digest(manifest):errors.append('Manifest content hash mismatch')
    for i in items:
        if digest(i['evidence'])!=i['evidence_sha256']:errors.append('Manifest item content hash mismatch: '+i['item_id'])
    for ref,row in manifest.get('inputs',{}).items():
        p=Path(row['path'])
        if not p.is_file() or file_hash(p)!=row['sha256']:stale.append(ref)
    if package_dir is not None:
        base=Path(package_dir).resolve()
        for ref,row in manifest.get('assets',{}).items():
            p=(base/row['path']).resolve()
            if not p.is_relative_to(base) or not p.is_file() or file_hash(p)!=row['sha256']:stale.append(ref)
    records=defaultdict(list);schema_errors=[]
    for n,sub in enumerate(submissions):
        if not isinstance(sub,dict) or set(sub)!={'schema_version','package_id','reviews'} or sub.get('schema_version')!=VERSION or not isinstance(sub.get('reviews'),list):
            schema_errors.append(f'Submission {n}: invalid envelope');continue
        wrong_package=sub.get('package_id')!=manifest.get('package_id')
        for r in sub['reviews']:
            if not isinstance(r,dict) or not isinstance(r.get('item_id'),str) or r['item_id'] not in by_id:
                schema_errors.append(f'Submission {n}: unknown or missing item ID');continue
            records[r['item_id']].append((r,wrong_package))
    result=[];all_edges=[];order_results=[]
    for item in items:
        ref=item['item_id'];rows=records[ref];row_errors=[];state='PENDING_REVIEW';valid_records=[];is_stale=bool(stale)
        for r,wrong_package in rows:
            re=record_errors(r,item);row_errors.extend(re)
            if wrong_package or r.get('bindings')!=item['bindings'] or r.get('evidence_sha256')!=item['evidence_sha256']:is_stale=True
            if not re and r['decision'] is not None:valid_records.append(r)
        decisions={r['decision'] for r in valid_records}
        conflict=len(decisions)>1
        # Different accepted order declarations are a conflict even if both say ACCEPT.
        if item['category']=='reading_order' and len({digest(r['order']) for r in valid_records if r['decision']=='ACCEPT'})>1:conflict=True
        if conflict:row_errors.append('Conflicting decisions; no automatic last-write-wins')
        accepted=[r for r in valid_records if r['decision'] in ('ACCEPT','COMPLETE')]
        if is_stale:state='STALE_REVIEW'
        elif conflict:state='UNCERTAIN'
        elif valid_records:
            d=valid_records[0]['decision']
            state='REJECTED' if d in ('REJECT','INCOMPLETE') else 'UNCERTAIN' if d=='UNCERTAIN' else 'ACCEPTED_UNVERIFIED'
        chosen=None;order_edges=[]
        for r in accepted:
            promotion=not (row_errors or errors or is_stale or conflict)
            promotion &= r['independent_human'] is True and all(r['checks'].values())
            promotion &= set(item['required_evidence']).issubset(r['evidence_references'])
            if item['category']=='page_boundary':
                adjacent=item['evidence'].get('adjacent_evidence_references',[])
                promotion &= item['evidence'].get('adjacent_evidence_available') is True and bool(adjacent)
                promotion &= all(ref in manifest.get('inputs',{}) and ref in item['available_evidence'] and ref in r['evidence_references'] for ref in adjacent)
            if item['category']=='geometry':promotion &= item['evidence'].get('decoded_pixels_exact') is True
            if item['category']=='reading_order':
                oe,order_edges=check_order(r['order'],item['order_scope']);row_errors.extend(oe)
                promotion &= not oe and not r['order']['unresolved']
                if not oe:all_edges.extend(order_edges);order_results.append(ref)
            if promotion:chosen=r;state='VERIFIED_BY_POLICY'
        if row_errors and state=='VERIFIED_BY_POLICY':state='ACCEPTED_UNVERIFIED';chosen=None
        result.append({'item_id':ref,'category':item['category'],'state':state,'structurally_valid':not row_errors,
          'hash_valid':not is_stale and not errors,'errors':sorted(set(row_errors)),
          'human_decision':valid_records[0]['decision'] if len(decisions)==1 and valid_records else None,
          'verified_review':deepcopy(chosen),'crop_complete_attested':bool(accepted) if item['category']=='geometry' else None,
          'geometry_semantics_verified':False if item['category']=='geometry' else None})
    if cyclic(all_edges):
        for row in result:
            if row['item_id'] in order_results:
                row['errors'].append('Cross-review reading-order cycle/conflict');row['structurally_valid']=False
                row['state']='UNCERTAIN' if row['state']!='STALE_REVIEW' else row['state'];row['verified_review']=None
    if errors or schema_errors:
        for row in result:
            if row['state']=='VERIFIED_BY_POLICY':row['state']='ACCEPTED_UNVERIFIED';row['verified_review']=None
    counts=Counter(r['state'] for r in result)
    return {'schema_version':VERSION,'package_id':manifest.get('package_id'),'status':
      'INVALID_REVIEW' if errors or schema_errors or any(r['errors'] for r in result) else 'STALE_REVIEW' if stale or counts['STALE_REVIEW'] else 'HUMAN_REVIEW_PENDING' if counts['PENDING_REVIEW'] else 'VALIDATED_SCOPED_DECISIONS',
      'schema_valid':not schema_errors and not any(r['errors'] for r in result),'manifest_valid':not errors,
      'errors':errors+schema_errors,'changed_inputs_or_assets':stale,'counts':dict(counts),'items':result,'policy':POLICY}


def readiness(manifest,validation):
    """Adapt only policy-verified records to the existing TASK 3H anchor gate."""
    from layout_hybrid import select_anchors
    rows={r['item_id']:r for r in validation['items']};verified={k for k,v in rows.items() if v['state']=='VERIFIED_BY_POLICY'}
    alignment=deepcopy(manifest['alignment']);order=deepcopy(manifest['reading_order']);bindings=manifest['hybrid_bindings'];reviews=[]
    boundary='boundary:114' in verified
    for link in alignment['links']:
        p=link['paragraph_id'];ar=rows.get('alignment:'+p);orr=rows.get('order:'+p)
        if not(boundary and ar and orr and ar['state']==orr['state']=='VERIFIED_BY_POLICY'):continue
        review=ar['verified_review'];orv=orr['verified_review'];index=manifest['anchor_indices'][p]
        base={'verified':True,'independent':True,'reference':p,'reviewer':review['reviewer'],'basis':review['basis'],'bindings':bindings}
        reviews.append(dict(base,source_bbox=link['source_bbox'],source_block_ids=link['source_block_ids'],translation_block_ids=link['translation_block_ids'],translation_math_node_ids=link['translation_math_node_ids'],checks={k:True for k in ('page_pairing','bbox_content','translation_content','math','reading_order')}))
        for row in order['paragraph_links']:
            if row['paragraph_reference']!=p:continue
            # Candidate rank cannot become verified merely by pressing ACCEPT.
            scope=next(i['order_scope'] for i in manifest['items'] if i['item_id']=='order:'+p)
            actual=orv['order']['sequences']['source_regions']
            if actual!=[scope['source_regions']]:continue
            row['verification_status']='READING_ORDER_VERIFIED';row['proposed_reading_order_index']=index
            row['evidence']['independent_review']=dict(base,reviewer=orv['reviewer'],basis=orv['basis'],proposed_reading_order_index=index,checks={k:True for k in ('source_order','translation_order','page_boundary','math_order')})
    selection=select_anchors(alignment,order,bindings,reviews)
    # Global rank is human reviewed only when the global sequence contains all
    # anchors in the saved candidate order; other orders need a new scoped plan.
    global_row=rows.get('order:page:114');global_verified=global_row and global_row['state']=='VERIFIED_BY_POLICY'
    if global_verified:
        seqs=global_row['verified_review']['order']['sequences'].get('source_regions',[])
        ordered=[x for seq in seqs for x in seq if x in manifest['anchor_indices']]
        expected=sorted(manifest['anchor_indices'],key=manifest['anchor_indices'].get)
        global_verified=ordered==expected and any([x for x in stream if x in manifest['anchor_indices']]==expected for stream in seqs)
        # Existing hybrid solver retains inventory order. A reviewed different
        # order is valid evidence but requires a separately reviewed layout plan.
        for key in ('source_blocks','translation_blocks'):
            actual=global_row['verified_review']['order']['sequences'].get(key,[])
            expected_ids=[r['reference'] for r in manifest['reading_order'][key]]
            global_verified &= actual==[expected_ids]
    if not global_verified:selection['eligible_anchors']=[];selection['verified_anchor_count']=0;selection['qualified_preview_status']=BLOCKED
    geometry=[i['item_id'] for i in manifest['items'] if i['category']=='geometry' and i['item_id'] in verified]
    c=manifest['coverage'];preserved=c['translation_blocks_preserved']==53 and c['translation_math_nodes_preserved']==66 and c['text_exact'] is True and c['duplicate_rendered_math_nodes']==0
    gates={
      'alignment':{'verified':sum(i.startswith('alignment:') for i in verified),'total':7},
      'reading_order':{'verified':sum(i.startswith('order:') for i in verified),'total':8,'global_sequence_policy_valid':bool(global_verified),'render_order_requirement':'Reviewed CN/VI stream must match existing renderer inventory order; differing valid orders require a new reviewed plan'},
      'page_boundary':{'status':'VERIFIED_BY_POLICY' if boundary else 'PAGE_BOUNDARY_UNVERIFIED'},
      'geometry':{'verified_crops':len(geometry),'total':3,'eligible_for_insertion':geometry if boundary and selection['verified_anchor_count'] else [],'geometry_semantics':'UNVERIFIED'},
      'translation_coverage':{'preserved_blocks':c['translation_blocks_preserved'],'unlocalized_blocks':len(c['unlocalized_translation_block_ids']),'semantic_completeness':'UNVERIFIED'},
      'math_integrity':{'technical_preservation':c['translation_math_nodes_preserved']==66 and c['duplicate_rendered_math_nodes']==0,'semantic_verified':False,'source_nodes':67,'translation_nodes':66},
      'content_preservation':{'pass':preserved,'evidence':'Hash-bound TASK 3H saved metrics, no new render'},
      'collision_overflow':{'saved_diagnostic_collision_count':len(c['candidate_diagnostic_collisions']),'saved_diagnostic_overflow_count':len(c['candidate_diagnostic_overflow']),'new_hybrid':'NOT_MEASURED','geometry_inserted':0}}
    if not preserved or validation['status'] in ('INVALID_REVIEW','STALE_REVIEW'):selection['eligible_anchors']=[];selection['verified_anchor_count']=0;selection['qualified_preview_status']=BLOCKED
    return {'status':selection['qualified_preview_status'],'readiness':'HIGH_RISK_HOLD','anchor_status':'NOT_ANCHORABLE' if not selection['verified_anchor_count'] else 'EXPERIMENTAL_REVIEWED_PLAN',
      'gates':gates,'selection':selection,'fallback':'Preserve all 53 VI blocks and 66 math nodes in existing safe Full Reflow; unlocalized content is retained.',
      'qualified_preview_created':False,'production_integration':False,'ready_for_pilot':False,'limits':'Eligibility is a plan only. Any future partial hybrid needs unchanged renderer measurements, preservation checks and geometry collision checks before preview acceptance.'}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--package',type=Path,required=True);ap.add_argument('--reviews',type=Path,nargs='*',default=[]);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    m=read_json(args.package/'review-manifest.json');submissions=[]
    for p in args.reviews:
        try:submissions.append(read_json(p))
        except (OSError,ValueError):submissions.append(None)
    report=validate(m,submissions,args.package);gates=readiness(m,report)
    args.output.mkdir(parents=True,exist_ok=False)
    for name,value in [('review-validation.json',report),('hybrid-readiness.json',gates)]:
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'validation':report['status'],'hybrid':gates['status'],'output':str(args.output)},ensure_ascii=False))
    return 1 if report['status'] in ('INVALID_REVIEW','STALE_REVIEW') else 0

if __name__=='__main__':raise SystemExit(main())
