"""TASK 3D offline alignment sidecar. Candidates never certify source pixels."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from html import escape
import json
from pathlib import Path
import re
import shutil
from PIL import Image, ImageDraw
from layout_rebuilder import build_content, STATUS
from layout_source_anchored import inventory, build as build_pilot
from translation_evidence import structured_math, file_hash, digest
from layout_calibration import load_inputs

STATES=('ALIGNED_VERIFIED','ALIGNED_CANDIDATE','AMBIGUOUS','UNMATCHED','INSUFFICIENT_EVIDENCE')


def recover_source(capture,expected_source_sha256):
    """Recover a saved transcription response; no provider/DOM access."""
    result={'status':'INSUFFICIENT_EVIDENCE','candidate':None,'verified':False,'reasons':[]}
    if not isinstance(capture,dict) or capture.get('source_sha256')!=expected_source_sha256:
        result['reasons']=['Missing source binding or incorrect page pairing'];return result
    audit=capture.get('capture_audit') or {};before=audit.get('before') or {};after=audit.get('after') or {}
    messages=before.get('messages',[]);candidates=[]
    for i,m in enumerate(messages):
        if (i and m.get('role')=='assistant' and messages[i-1].get('role')=='user'
                and messages[i-1].get('text')=='chép lại nguyên văn'
                and isinstance(m.get('html'),str) and re.search(r'[\u4e00-\u9fff]',m.get('text') or '')):
            candidates.append((i,m))
    if len(candidates)!=1:
        result['status']='AMBIGUOUS' if candidates else 'INSUFFICIENT_EVIDENCE'
        result['reasons']=['No unique saved Chinese response following the existing transcription prompt'];return result
    i,m=candidates[0];later=after.get('messages',[])
    if (before.get('generating') or not before.get('conversation_url')
            or before.get('conversation_url')!=after.get('conversation_url')
            or len(later)<len(messages) or digest(later[:len(messages)])!=digest(messages)):
        result['reasons']=['Response generating or before/after payload conflict'];return result
    structure=structured_math(m['html'],formulas=m.get('formulas',[]))
    if structure['status']!='AUXILIARY_UNVERIFIED':
        result['reasons']=['Incomplete source math/HTML inventory'];return result
    result.update(status='ALIGNED_CANDIDATE',candidate=m,
                  provenance={'snapshot':'capture_audit.before','message_array_index':i,
                              'captured_response_id':m.get('id'),'response_payload_sha256':digest(m),
                              'source_image_sha256':expected_source_sha256,'before_snapshot_sha256':digest(before),
                              'capture_token':capture.get('capture_token'),
                              'identity_scope':'Observed saved response ID; user/source association unverified'},
                  reasons=['Existing response usable offline, not independently certified against source pixels'])
    return result


def math_key(tex):
    """Candidate fingerprint only; originals unchanged, no math equivalence."""
    if not isinstance(tex,str) or not tex.strip():return ()
    tex=re.sub(r'\\(?:begin|end)\{aligned\}','',tex)
    if tex.startswith('\\boxed{') and tex.endswith('}'):tex=tex[7:-1]
    tex=tex.replace('\\dfrac','\\frac')
    tex=re.sub(r'\\(?:qquad|quad|,|;|!| )','',tex).replace('\\\\','').replace('&','')
    return tuple(t for t in re.findall(r'\\[A-Za-z]+|\\.|[A-Za-z]|\d+|[^\s]',tex) if t not in (',','.'))


def align_math(source,target):
    """Monotone DP with gaps and bounded 1:N/N:1 lexical groups."""
    n,m=len(source),len(target);sk=[math_key(r.get('latex')) for r in source];tk=[math_key(r.get('latex')) for r in target]
    sc,tc=Counter(sk),Counter(tk)
    sg={(i,a):sum(sk[i:i+a],()) for i in range(n) for a in range(1,min(4,n-i)+1)}
    tg={(j,b):sum(tk[j:j+b],()) for j in range(m) for b in range(1,min(4,m-j)+1)}
    score=[[float('-inf')]*(m+1) for _ in range(n+1)];back={};score[0][0]=0
    def offer(i,j,value,prev):
        if value>score[i][j]+1e-9:score[i][j]=value;back[(i,j)]=prev
    for i in range(n+1):
        for j in range(m+1):
            if score[i][j]==float('-inf'):continue
            if i<n:offer(i+1,j,score[i][j]-2,(i,j,'source_gap',1,0))
            if j<m:offer(i,j+1,score[i][j]-2,(i,j,'target_gap',0,1))
            for a in range(1,min(4,n-i)+1):
                for b in range(1,min(4,m-j)+1):
                    if a>1 and b>1:continue
                    key=sg[(i,a)]
                    if not key or key!=tg[(j,b)] or any(not k for k in sk[i:i+a]+tk[j:j+b]):continue
                    raw=[r['latex'] for r in source[i:i+a]+target[j:j+b]]
                    if a+b>2 and not any('\\begin{aligned}' in t or '\\quad' in t or ',' in t for t in raw):continue
                    offer(i+a,j+b,score[i][j]+8+.01*len(key)-.2*(a+b-2),(i,j,'match',a,b))
    pairs=[];gaps_s=[];gaps_t=[];i,j=n,m
    while i or j:
        pi,pj,kind,a,b=back[(i,j)]
        if kind=='source_gap':gaps_s.append(pi)
        elif kind=='target_gap':gaps_t.append(pj)
        else:
            exact=a==b==1 and source[pi]['latex']==target[pj]['latex']
            repeated=a==b==1 and (sc[sk[pi]]>1 or tc[tk[pj]]>1)
            pairs.append({'source_math_ids':list(range(pi,pi+a)),'math_node_ids':list(range(pj,pj+b)),
                          'alignment_method':'EXACT_LATEX_LEXICAL' if exact else 'NORMALIZED_TEX_LEXICAL_GROUP',
                          'confidence':.35 if repeated else (.85 if exact else .65),
                          'verification_status':'AMBIGUOUS' if repeated else 'ALIGNED_CANDIDATE',
                          'source_latex':[r['latex'] for r in source[pi:pi+a]],'translation_latex':[r['latex'] for r in target[pj:pj+b]],
                          'candidate_fingerprint_sha256':digest(list(sg[(pi,a)])),
                          'normalization_changes':not exact,'mathematical_equivalence':'NOT_PROVEN',
                          'reading_order_index':None,'order_basis':'Monotone candidate search, not verified reading order'})
        i,j=pi,pj
    return {'links':list(reversed(pairs)),'unmatched_source_math_ids':sorted(gaps_s),'unmatched_translation_math_ids':sorted(gaps_t),
            'limits':'Key ignores layout wrappers and comma/period punctuation; not math equivalence. Missing triangle/circle operators are not aliased.'}


def blocks_for(candidate,prefix):
    html,rows,structure=build_content(candidate);blocks=inventory(html)
    for b in blocks:
        b['id']=f'{prefix}:block:{b["local_block_index"]}'
        b['content_reference_sha256']=digest({'text':b['non_math_text'],'math_indices':b['math_indices']})
    return blocks,rows,structure


def markers(block):
    text=block['non_math_text'];out=[]
    for pattern,kind in [(r'(?:例|Ví dụ)\s*(\d+)','example'),(r'(?:定理|Định lý)\s*(\d+)','theorem'),(r'(?:图|Hình)\s*(\d+[-–]\d+)','figure')]:
        out += [kind+':'+v.replace('–','-') for v in re.findall(pattern,text,re.I)]
    for words,kind in [(('充分性','Điều kiện đủ'),'sufficiency'),(('必要性','Điều kiện cần'),'necessity')]:
        if any(w in text for w in words):out.append(kind)
    if re.match(r'^(?:证明|Chứng minh\.)',text.strip()):out.append('proof')
    if block['tag'].startswith('h') and text in ('平面几何','HÌNH HỌC PHẲNG'):out.append('heading:plane_geometry')
    return out


def link_blocks(source,target,math):
    owners_s={idx:b['id'] for b in source for idx in b['math_indices']};owners_t={idx:b['id'] for b in target for idx in b['math_indices']}
    edges=defaultdict(lambda:{'target':set(),'math':set(),'methods':set(),'ambiguous':False})
    for pair in math['links']:
        for sid in {owners_s[i] for i in pair['source_math_ids']}:
            e=edges[sid];e['target'].update(owners_t[i] for i in pair['math_node_ids']);e['math'].update(pair['math_node_ids']);e['methods'].add('shared_saved_math_lexical_anchor')
            e['ambiguous'] |= pair['verification_status']=='AMBIGUOUS'
    sm=defaultdict(list);tm=defaultdict(list)
    for b in source:
        for marker in markers(b):sm[marker].append(b['id'])
    for b in target:
        for marker in markers(b):tm[marker].append(b['id'])
    for marker,sids in sm.items():
        if len(sids)==len(tm.get(marker,[]))==1:
            e=edges[sids[0]];e['target'].add(tm[marker][0]);e['methods'].add('explicit_section_marker:'+marker)
    ti={b['id']:i for i,b in enumerate(target)}
    for e in edges.values():
        for tid in list(e['target']):
            index=ti[tid]
            if target[index]['tag']=='div' and index:
                prev=target[index-1]
                if prev['tag']=='p' and not prev['math_indices'] and len(prev['non_math_text'].strip())<=25:
                    e['target'].add(prev['id']);e['methods'].add('preceding_short_connector_candidate')
    result=[]
    for b in source:
        if b['id'] not in edges:continue
        e=edges[b['id']];tids=sorted(e['target'],key=ti.get)
        result.append({'source_text_reference':b['id'],'translation_block_id':tids[0] if len(tids)==1 else None,
                       'translation_block_ids':tids,'math_node_ids':sorted(e['math']),
                       'reading_order_index':None,'alignment_method':sorted(e['methods']),
                       'confidence':.45 if e['ambiguous'] else .70,'verification_status':'ALIGNED_CANDIDATE',
                       'semantic_translation_complete':'NOT_PROVEN'})
    return result


def region_candidates(regions,source_blocks,block_links,provenance):
    """Rank-only localization candidates without source OCR/bbox evidence."""
    body=sorted([r for r in regions if r['comparison_type'] in ('BODY_TEXT','MATH_FORMULA','UNKNOWN')],key=lambda r:(r['bbox'][1],r['bbox'][0]))
    source_body=[b for b in source_blocks if not b['tag'].startswith('h') and not re.search(r'图3-51.*100',b['non_math_text'])]
    rank={b['id']:i for i,b in enumerate(source_body)};result=[]
    for block in block_links:
        sid=block['source_text_reference']
        if sid in rank and body:
            index=round(rank[sid]*(len(body)-1)/max(1,len(source_body)-1));r=body[index]
            alternatives=[v['id'] for v in body[max(0,index-1):min(len(body),index+2)] if v['id']!=r['id']]
            method='MATH_OR_MARKER_BLOCK_LINK_PLUS_RASTER_RANK_ONLY';confidence=.22;status='AMBIGUOUS'
        elif any(b['id']==sid and b['tag'].startswith('h') for b in source_blocks):
            headers=[r for r in regions if r['comparison_type']=='HEADER']
            if len(headers)!=1:continue
            r=headers[0];alternatives=[];method='HEADING_TYPE_AND_MARKER_CANDIDATE';confidence=.40;status='ALIGNED_CANDIDATE'
        else:continue
        row=dict(block,source_region_id=r['id'],source_bbox=r['bbox'],alignment_method=[method,*block['alignment_method']],confidence=confidence,
                 verification_status=status,alternative_region_ids=alternatives,eligible_for_anchor=False,provenance=dict(provenance),
                 localization_limit='No source pixel text extraction; relative rank is a hypothesis, not bbox content evidence.')
        row['alignment_id']='local-alignment:'+digest({k:row[k] for k in ('source_region_id','source_bbox','source_text_reference','translation_block_ids','math_node_ids')})
        result.append(row)
    return result


def apply_reviews(links,reviews,bindings):
    """Optional independent adjudication; no confidence-based promotion."""
    import copy
    result=copy.deepcopy(links)
    required=('source_image_sha256','capture_sha256','source_html_sha256','translation_html_sha256')
    if any(not isinstance(bindings.get(k),str) or not re.fullmatch(r'[0-9a-f]{64}',bindings[k]) for k in required):return result
    for row in result:
        for review in reviews:
            if (review.get('alignment_id')==row['alignment_id'] and review.get('verified') is True and review.get('independent') is True
                and all(review.get(k)==v for k,v in bindings.items()) and review.get('source_bbox')==row['source_bbox']
                and isinstance(review.get('reviewer'),str) and review['reviewer'].strip()
                and isinstance(review.get('basis'),str) and review['basis'].strip()
                and type(review.get('reading_order_index')) is int and review['reading_order_index']>=0
                and all((review.get('checks') or {}).get(k) is True for k in ('page_pairing','bbox_content','translation_content','math','reading_order'))):
                row.update(verification_status='ALIGNED_VERIFIED',eligible_for_anchor=True,independent_review=review,reading_order_index=review['reading_order_index'])
    return result


def padded_crops(source,regions,output,padding=240):
    """New raw-pixel debug assets only; padding does not prove labels."""
    output=Path(output);output.mkdir();results=[]
    with Image.open(source) as im:
        im.load()
        for r in regions:
            if r['comparison_type']!='GEOMETRY_DIAGRAM':continue
            x0,y0,x1,y1=r['bbox'];box=[max(0,x0-padding),max(0,y0-padding),min(im.width,x1+padding),min(im.height,y1+padding)]
            path=output/(r['id'].replace(':','-')+'-padded.png');crop=im.crop(box);crop.save(path)
            with Image.open(path) as saved:exact=saved.mode==crop.mode and saved.size==crop.size and saved.tobytes()==crop.tobytes()
            ink=crop.convert('L').point(lambda p:255 if p<180 else 0)
            touch={side:ink.crop(b).getbbox() is not None for side,b in {'left':(0,0,3,crop.width),'right':(crop.width-3,0,crop.width,crop.height),'top':(0,0,crop.width,3),'bottom':(0,crop.height-3,crop.width,crop.height)}.items()}
            results.append({'source_region_id':r['id'],'original_bbox':r['bbox'],'padded_bbox':box,'path':str(path.resolve()),'sha256':file_hash(path),'decoded_pixels_exact':exact,
                            'border_ink':touch,'status':'GEOMETRY_UNVERIFIED','labels_complete':False,'caption_complete':False,'inserted':False,
                            'reason':'Padding expands context; absence of border ink does not prove complete labels/caption.'})
        # Bounded raster proposal for the third figure seen during TASK 3C.
        # This is page-specific debug, not a semantic detector or saved region.
        roi=[round(im.width*.64),round(im.height*.07),round(im.width*.95),round(im.height*.29)]
        mask=im.crop(roi).convert('L').point(lambda p:255 if p<180 else 0);bbox=mask.getbbox()
        if bbox:
            box=[max(0,roi[0]+bbox[0]-80),max(0,roi[1]+bbox[1]-80),min(im.width,roi[0]+bbox[2]+80),min(im.height,roi[1]+bbox[3]+80)]
            path=output/'top-right-raster-proposal.png';crop=im.crop(box);crop.save(path)
            with Image.open(path) as saved:exact=saved.mode==crop.mode and saved.size==crop.size and saved.tobytes()==crop.tobytes()
            results.append({'source_region_id':None,'proposal_id':'local-top-right-ink-envelope','padded_bbox':box,'path':str(path.resolve()),'sha256':file_hash(path),'decoded_pixels_exact':exact,
                            'status':'GEOMETRY_UNVERIFIED','labels_complete':False,'caption_complete':False,'inserted':False,
                            'reason':'Page-114-specific ROI, not a general detector. May contain nearby text; no caption identity inferred.'})
    return results


def build_alignment(dataset,fixture,capture,baseline3b,baseline3c,output):
    output=Path(output);dataset=Path(dataset);fixture=Path(fixture);capture=Path(capture)
    d,vi=load_inputs(dataset,fixture);e=json.loads(capture.read_text(encoding='utf8'))
    fixture_data=json.loads(fixture.read_text(encoding='utf8'))
    if file_hash(capture)!=fixture_data['source_artifact_sha256']:raise ValueError('Capture hash mismatch')
    regions=d['region_qc']['regions']['source'];source_audit=recover_source(e,d['source_image']['sha256'])
    vi_blocks,vi_rows,vi_structure=blocks_for(vi,'vi')
    if source_audit['candidate']:src_blocks,src_rows,src_structure=blocks_for(source_audit['candidate'],'src')
    else:src_blocks=[];src_rows=[];src_structure=None
    math=align_math(src_rows,vi_rows);blocks=link_blocks(src_blocks,vi_blocks,math)
    provenance={'source_image_sha256':d['source_image']['sha256'],'capture_sha256':file_hash(capture),
                'source_html_sha256':src_structure['html_sha256'] if src_structure else None,'translation_html_sha256':vi_structure['html_sha256'],
                'source_recovery_status':source_audit['status'],'scope':'Local block/node IDs are inventory IDs, not provider message IDs.'}
    owners_s={idx:b['id'] for b in src_blocks for idx in b['math_indices']}
    owners_t={idx:b['id'] for b in vi_blocks for idx in b['math_indices']}
    for pair in math['links']:
        pair['provenance']=dict(provenance)
        pair['source_text_references']=sorted({owners_s[i] for i in pair['source_math_ids']})
        pair['translation_block_ids']=sorted({owners_t[i] for i in pair['math_node_ids']})
    links=apply_reviews(region_candidates(regions,src_blocks,blocks,provenance),[],provenance)
    with Image.open(d['source_image']['path']) as im:source_size=im.size
    target_size=json.loads((Path(baseline3b)/'layout-metrics.json').read_text(encoding='utf8'))['target_size']
    for link in links:
        link['layout_position_candidate']={'page_index':0,'target_bbox':[v*target_size[i%2]/source_size[i%2] for i,v in enumerate(link['source_bbox'])],
                                           'status':'NOT_PLACED','basis':'Projected source coordinates only; unresolved bbox/content correspondence.'}
    historical=[dataset,fixture,capture,*[Path(d[k]['path']) for k in ('source_image','translated_image')],*[Path(c['path']) for c in d['geometry_crops']]]
    for base in (Path(baseline3b),Path(baseline3c)):historical += [p for p in base.rglob('*') if p.is_file()]
    hashes={str(p.resolve()):file_hash(p) for p in historical}
    output.mkdir(parents=True,exist_ok=False)
    geometry=padded_crops(d['source_image']['path'],regions,output/'geometry-debug')
    # No independent bbox links in current data: keep candidates in diagnostic,
    # reuse existing offline renderer for all content, never insert candidates.
    pilot=build_pilot(dataset,fixture,baseline3b,output/'source-anchored-pilot')
    if any(r['eligible_for_anchor'] for r in links):raise ValueError('Verified placement implementation required; do not silently drop anchors')
    linked_ids={r['source_region_id'] for r in links}
    region_report=[{'source_region_id':r['id'],'source_bbox':r['bbox'],'type':r['comparison_type'],
                    'status':(('ALIGNED_CANDIDATE' if any(l['verification_status']=='ALIGNED_CANDIDATE' for l in links if l['source_region_id']==r['id']) else 'AMBIGUOUS') if r['id'] in linked_ids else ('INSUFFICIENT_EVIDENCE' if not src_blocks or r['comparison_type']=='GEOMETRY_DIAGRAM' else 'UNMATCHED')),
                    'localization_verified':False,'candidate_alignment_ids':[l['alignment_id'] for l in links if l['source_region_id']==r['id']]}
                   for r in regions]
    matched_vi={i for pair in math['links'] for i in pair['math_node_ids']};candidate_vi={i for pair in math['links'] if pair['verification_status']=='ALIGNED_CANDIDATE' for i in pair['math_node_ids']}
    boundary={'page_file_identifier':'114','printed_page_number_observation':'100','printed_page_number_status':'VISUALLY_OBSERVED_UNVERIFIED',
              'file_identifier_is_printed_page':False,'source_boundary':'UNVERIFIED','translation_boundary':'UNVERIFIED','adjacent_pages_available_in_this_audit':False,
              'source_last_latex':src_rows[-1]['latex'] if src_rows else None,'translation_last_latex':vi_rows[-1]['latex'],
              'translation_only_note':'(Phần chứng minh tiếp tục ở trang sau.)','note_source_support':'NOT_FOUND_IN_SAVED_SOURCE_TRANSCRIPTION; boundary unverified; preserved.',
              'source_caption_footer_block':src_blocks[-1]['non_math_text'] if src_blocks else None,
              'reading_order_status':'DOM_SEQUENCE_ONLY_UNVERIFIED','verified_reading_order_indices':0,
              'math_order_method':'Monotone lexical grouping with gaps, not index pairing or verified reading order',
              'association_status_unchanged':d['pairing_status']}
    counts={'region_status_counts':dict(Counter(r['status'] for r in region_report)), 'source_regions':len(regions),'source_blocks':len(src_blocks),'translation_blocks':len(vi_blocks),
            'regions_with_candidates':len(linked_ids),'regions_without_candidates':len(regions)-len(linked_ids),'verified_regions':0,
            'source_math_nodes':len(src_rows),'translation_math_nodes':len(vi_rows),'math_nodes_with_candidate_or_ambiguous_links':len(matched_vi),
            'math_nodes_with_unambiguous_lexical_candidates':len(candidate_vi),'verified_math_nodes':0,'geometry_debug_proposals':len(geometry),'verified_complete_figures':0}
    result={'status':STATUS,'dataset_readiness_unchanged':d['readiness'],'source_content_inventory':source_audit,
            'counts':counts,'source_blocks':src_blocks,'translation_blocks':vi_blocks,'block_links':blocks,
            'alignments':links,'math_alignment':math,'region_report':region_report,'geometry_report':geometry,'page_boundary':boundary,
            'pilot':{'anchor_status':'NOT_ANCHORABLE','verified_anchors':0,'full_reflow_pages':pilot['full_reflow_pages_after'],'profile':pilot['profile'],'math_preserved':pilot['math_integrity']['technical_preserved'],'network_attempts':pilot['network_attempts']},
            'original_hashes':hashes,'original_hashes_unchanged':all(file_hash(p)==sha for p,sha in hashes.items()),
            'limits':['CN transcription not certified source OCR; bbox->CN remains rank candidate.','Confidence is heuristic, not calibrated probability.','No math equivalence, content correctness or complete figure certification.','No production hooks or extra prompts.']}
    if not result['original_hashes_unchanged']:raise ValueError('Historical input changed')
    unmatched={'source_regions':[r for r in region_report if r['status'] not in ('ALIGNED_CANDIDATE','AMBIGUOUS')],
               'source_blocks':[b for b in src_blocks if b['id'] not in {l['source_text_reference'] for l in blocks}],
               'translation_blocks':[b for b in vi_blocks if b['id'] not in {tid for l in blocks for tid in l['translation_block_ids']}],
               'math_source':math['unmatched_source_math_ids'],'math_translation':math['unmatched_translation_math_ids']}
    for name,value in [('alignment-dataset.json',result),('region-report.json',region_report),('candidate-alignments.json',links),('unmatched.json',unmatched),('page-boundary-reading-order.json',boundary),('geometry-report.json',geometry),('math-alignment.json',math)]:
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    if source_audit['candidate']:
        (output/'source-transcription-sidecar.json').write_text(json.dumps({'status':'CAPTURE_UNVERIFIED','verified':False,'source_image_sha256':d['source_image']['sha256'],'provenance':source_audit['provenance'],'response':source_audit['candidate']},ensure_ascii=False,indent=2),encoding='utf8')
    shutil.copyfile(Path(baseline3c)/'source-anchored-preview.png',output/'task3c-before.png')
    shutil.copyfile(output/'source-anchored-pilot/source-anchored-preview.png',output/'source-anchored-preview.png')
    overlay_and_html(d,regions,result,output);write_report(result,output)
    return result


def overlay_and_html(d,regions,result,output):
    with Image.open(d['source_image']['path']) as source:
        sx=1200/source.width;sy=1668/source.height;im=source.convert('RGB').resize((1200,1668));draw=ImageDraw.Draw(im)
        for row in result['region_report']:
            box=tuple(round(v*(sx if i%2==0 else sy)) for i,v in enumerate(row['source_bbox']))
            draw.rectangle(box,outline='#df8800' if row['candidate_alignment_ids'] else '#aa3344',width=2);draw.text((box[0],box[1]),row['source_region_id'],fill='#a23')
        draw.rectangle((0,0,1200,35),fill='white');draw.text((10,10),'CANDIDATE / AMBIGUOUS ONLY - NOT SOURCE-VERIFIED - NO ANCHORS',fill='#a22')
        canvas=Image.new('RGB',(1800,1668),'white');canvas.paste(im,(0,0));legend=ImageDraw.Draw(canvas)
        legend.text((1220,15),'RANK / MARKER PROPOSALS ONLY - NOT VERIFIED',fill='#aa2222')
        for i,link in enumerate(result['alignments']):
            y=55+i*45;box=link['source_bbox'];cx=min(1185,round(box[2]*sx));cy=round((box[1]+box[3])/2*sy)
            legend.line((cx,cy,1205,y+8),fill='#dd8800',width=1)
            legend.text((1210,y),link['source_region_id']+' -> '+', '.join(link['translation_block_ids']),fill='#653400')
            legend.text((1210,y+15),link['verification_status']+' / '+link['source_text_reference']+' / c='+str(link['confidence']),fill='#aa2222')
        canvas.save(output/'alignment-overlay.png')
    sm={b['id']:b for b in result['source_blocks']};tm={b['id']:b for b in result['translation_blocks']}
    html='''<!doctype html><html lang="vi"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'self' file:"><style>body{font:18px Georgia;margin:24px;background:#eee}table{border-collapse:collapse;background:white;width:100%}td,th{padding:10px;border:1px solid #bbb;vertical-align:top}pre{white-space:pre-wrap;word-break:break-word}.top{display:flex;gap:20px}.top img{width:32%;object-fit:contain;align-self:start}</style><h1>TASK 3D — EXPERIMENTAL_UNVERIFIED / HIGH_RISK_HOLD</h1><p>Liên kết lexical/marker là candidate. Bbox là giả thuyết rank, chưa xác minh. Không dùng candidate để neo chữ. NOT_ANCHORABLE.</p><div class="top"><img src="alignment-overlay.png"><img src="task3c-before.png"><img src="source-anchored-preview.png"></div><p><a href="source-anchored-pilot/unanchored-full-reflow.html">Toàn bộ bản Việt 2 trang</a> · <a href="alignment-dataset.json">JSON truy vết</a></p><table><tr><th>Bbox/source</th><th>Bản chép Trung Quốc</th><th>Khối Việt / math</th><th>Căn cứ và trạng thái</th></tr>'''
    for link in result['alignments']:
        sb=sm[link['source_text_reference']];targets=[tm[t] for t in link['translation_block_ids']]
        html+=f'<tr><td>{escape(link["source_region_id"])}<pre>{escape(str(link["source_bbox"]))}</pre>Alternatives: {escape(str(link["alternative_region_ids"]))}</td><td>{escape(sb["id"])}<pre>{escape(sb["non_math_text"])}</pre>Math source {sb["math_indices"]}</td><td>'+''.join(f'<b>{escape(b["id"])}</b><pre>{escape(b["non_math_text"])}</pre>Math VI {b["math_indices"]}<br>' for b in targets)+f'</td><td>{link["verification_status"]}<br>confidence {link["confidence"]}<pre>{escape(str(link["alignment_method"]))}</pre>NOT eligible for anchoring</td></tr>'
    html+='</table><h2>Math lexical links — không chứng minh tương đương</h2>'
    for pair in result['math_alignment']['links']:
        html+=f'<details><summary>Source {pair["source_math_ids"]} → VI {pair["math_node_ids"]}: {pair["verification_status"]}</summary><pre>'+escape(str(pair['source_latex']))+'</pre><pre>'+escape(str(pair['translation_latex']))+'</pre></details>'
    html+='<h2>Hình nguồn — GEOMETRY_UNVERIFIED, chỉ debug</h2>'
    for g in result['geometry_report']:html+=f'<p>{escape(g.get("source_region_id") or g["proposal_id"])} — {g["status"]}; pixel exact {g["decoded_pixels_exact"]}</p><img style="max-width:600px" src="geometry-debug/{escape(Path(g["path"]).name)}">'
    (output/'comparison.html').write_text(html+'</html>',encoding='utf8')


def write_report(r,output):
    c=r['counts'];m=r['math_alignment']
    text=f'''# TASK 3D — Automatic Source-to-Translation Region Alignment

Branch feat/book-layout-consistency. EXPERIMENTAL_UNVERIFIED / HIGH_RISK_HOLD giữ nguyên.

## Kết quả thực tế

Có bản chép tiếng Trung đã lưu ngay sau prompt chép lại nguyên văn: {c['source_blocks']} khối/{c['source_math_nodes']} math node. Bản Việt: {c['translation_blocks']} khối/{c['translation_math_nodes']} math node. Payload Trung Quốc trùng giữa before/after, gắn hash capture/ảnh nguồn; chưa độc lập xác minh với pixel. Không gọi ChatGPT/OCR/AI mới, không thêm prompt.

{c['source_regions']} vùng nguồn: {c['regions_with_candidates']} có đề xuất bbox candidate, {c['regions_without_candidates']} chưa ghép; {c['verified_regions']} vùng verified. Phân loại vùng: {c['region_status_counts']}. Bbox candidate theo rank/type, KHÔNG phải trích nội dung từ pixel. Mỗi link ghi bbox/text ref, khối Việt một-nhiều/nhiều-một, math IDs, method/confidence/provenance; reading_order_index=null khi chưa đủ căn cứ.

{c['math_nodes_with_candidate_or_ambiguous_links']}/66 math node Việt có liên kết lexical hoặc ambiguous, trong đó {c['math_nodes_with_unambiguous_lexical_candidates']} có candidate lexical không lặp; verified=0. Nhóm lặp giữ AMBIGUOUS, không ghép biểu thức khác nhau bằng chỉ số. Node chưa ghép: source {m['unmatched_source_math_ids']}; Việt {m['unmatched_translation_math_ids']}.

Normalization chỉ tìm candidate, bỏ spacing/display wrapper và dấu phẩy/chấm; không sửa input/output và không chứng minh tương đương toán học. Các khác biệt triangle ABC/ABC và odot O/(O) không được alias. math-alignment.json giữ nguyên LaTeX hai phía.

## Hình học

{c['geometry_debug_proposals']} crop debug nguyên pixel mới: hai crop đệm từ bbox cũ và một ink-envelope ROI trên bên phải theo vị trí hình thứ ba đã quan sát ở TASK 3C. ROI riêng trang 114, không phải detector tổng quát hoặc caption đã nhận diện. {c['verified_complete_figures']} hình verified đầy đủ. GEOMETRY_UNVERIFIED; padding/border ink không chứng minh đủ nhãn/caption. Không dựng lại hình/nhãn hoặc chèn vào preview.

## Ranh giới

File identifier 114 tách riêng số in quan sát 100. Bản chép có block cuối caption 3-51/3-52/3-53 và 100; bản Việt có ghi chú tiếp trang sau không tìm thấy trong bản chép. Cả hai có đuôi MC=ME+EC=, nhưng chưa có trang liền kề/bbox text để xác minh nội dung dư/thiếu hoặc ranh giới. Giữ ghi chú và cả 66 math node Việt. DOM/monotone alignment không nâng thành verified reading order.

## Pilot

NOT_ANCHORABLE: bbox->source content vẫn thiếu chứng cứ. Không neo rank candidate. Nguyên profile 3B, đầy đủ nội dung Việt và 66/66 MathML trong 2 trang reflow. Diagnostic PNG so với TASK 3C không phải trang dịch hoàn thiện; chưa cải thiện số trang/bố cục. Tiến bộ là phục hồi bản chép nguồn và tạo liên kết nội dung có truy vết, bao gồm tách/gộp math/khối. Không ép một trang hoặc giảm font.

## File và bước tiếp theo

Thêm layout_alignment.py, tests/test_layout_alignment.py, thư mục TASK 3D mới; không sửa module cũ, worker, prompt, parser/schema/API, retry/resume/progress.csv. Không production integration hoặc commit/push/merge/reset/stash.

future-source-capture.md thiết kế sidecar cho phản hồi chép nguồn sẵn có trong batch tương lai: hash ảnh/capture/prompt/raw text+HTML+formula, snapshots/identity quan sát và completed state; thiếu ID/binding vẫn UNVERIFIED, không tạo ID giả/không thêm prompt. Chưa cài hook workflow.

Cần local OCR/PDF text có bbox/binding hoặc đối chiếu độc lập để định vị source content. Sau đó dùng công thức/mốc mục tự động liên kết, chỉ gửi trường hợp ambiguous vào review thay vì gán nhãn từng trang. Chỉ ALIGNED_VERIFIED mới đủ điều kiện neo, confidence không thay verification. Hiện association, bbox text, math equivalence, crop và reading order chưa xác minh.
'''
    (output/'report.md').write_text(text,encoding='utf8')
    (output/'future-source-capture.md').write_text('''# Thiết kế capture bản chép — chưa tích hợp production

Không thêm prompt. Sau phản hồi chép lại nguyên văn hiện có hoàn tất, lấy snapshot trước/sau và lưu sidecar bằng exclusive create.

Lưu source_image_sha256, capture_token, đúng prompt/hash, complete/generating, raw text/HTML/formula và hash, conversation identity/message/parent identity nếu thực sự quan sát. Positional DOM index chỉ truy vết snapshot, không phải stable provider ID; không tạo ID giả, không lưu signed URL/auth token.

Kiểm tra prefix, prompt/role boundary, content không đổi khi translation bắt đầu, source hash khớp. Capture thất bại ghi INSUFFICIENT_EVIDENCE/AMBIGUOUS trong sidecar, không đổi retry/resume hoặc chặn worker, không ghi progress.csv/schema cũ.

Bản chép không có bbox ảnh nguồn. Stage offline OCR/PDF-to-bbox riêng phải cung cấp content+location+source hash, rồi alignment lexical/math/marker tìm candidate. Independent validation đúng binding mới nâng ALIGNED_VERIFIED. TASK 3D chưa gọi OCR/cài engine/hook worker.
''',encoding='utf8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','fixture','capture','baseline3b','baseline3c','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();r=build_alignment(a.dataset,a.fixture,a.capture,a.baseline3b,a.baseline3c,a.output)
    print(json.dumps({'counts':r['counts'],'anchor_status':r['pilot']['anchor_status'],'output':a.output}))

if __name__=='__main__':main()
