"""TASK 3H offline reading-order review. Confidence is never verification."""
from collections import Counter, defaultdict
from copy import deepcopy
import re

ORDER_STATES=('READING_ORDER_VERIFIED','READING_ORDER_CANDIDATE','READING_ORDER_AMBIGUOUS','READING_ORDER_UNRESOLVED')


def independent_review(review,bindings,reference,checks):
    """Require explicit independent adjudication of exact bound sidecar evidence."""
    return bool(bindings and all(isinstance(v,str) and re.fullmatch(r'[0-9a-f]{64}',v) for v in bindings.values())
        and isinstance(review,dict) and review.get('verified') is True and review.get('independent') is True
        and review.get('reference')==reference
        and isinstance(review.get('reviewer'),str) and review['reviewer'].strip()
        and isinstance(review.get('basis'),str) and review['basis'].strip()
        and review.get('bindings')==bindings
        and all((review.get('checks') or {}).get(k) is True for k in checks))


def overlap(a,b):
    return min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1])


def candidate_order(paragraphs,columns=(),figure_regions=()):
    """Column-first within bands separated by spanning headings/text.

    Column boundaries, floating figures and order are candidate annotations.
    No y-only promotion; unknown/math fragments remain ambiguous and floats
    have a separate stream instead of becoming prose order by OCR index.
    """
    if any(len(c)!=4 or not c[0]<c[2] or not c[1]<c[3] for c in columns):raise ValueError('Invalid column boxes')
    if any(overlap(a,b) for i,a in enumerate(columns) for b in columns[i+1:]):raise ValueError('Overlapping candidate columns')
    rows=[];body=[]
    for p in paragraphs:
        row={'source_reference':p['paragraph_id'],'source_line_ids':deepcopy(p['source_line_ids']),
             'bbox':deepcopy(p['source_bbox']),'region_type':p['region_type'],'column_candidates':[],
             'proposed_reading_order_index':None,'verification_status':'READING_ORDER_CANDIDATE',
             'confidence':min(.65,p.get('confidence',.5)),
             'evidence':{'basis':'Paragraph geometry, column bands and role; never raw OCR/DOM sequence verification'},
             'reason':'No independent source reading-order adjudication'}
        b=p['source_bbox'];cx=(b[0]+b[2])/2;cy=(b[1]+b[3])/2
        figures=[g['figure_id'] for g in figure_regions if g['bbox'][0]<=cx<=g['bbox'][2] and g['bbox'][1]<=cy<=g['bbox'][3]]
        if p['region_type']=='FOOTER':row.update(stream='footer',verification_status='READING_ORDER_UNRESOLVED')
        elif figures and p['region_type'] not in ('BODY_TEXT','HEADING'):
            row.update(stream='figure_caption' if p['region_type']=='CAPTION' else 'figure_label_candidate',figure_references=figures,
                       verification_status='READING_ORDER_AMBIGUOUS' if len(figures)>1 else 'READING_ORDER_CANDIDATE')
            row['evidence']['basis']='Measured location inside candidate figure ROI; label semantics/attachment not certified'
        else:
            row['stream']='main_candidate'
            hits=[i for i,c in enumerate(columns) if min(b[2],c[2])-max(b[0],c[0])>.5*(b[2]-b[0])]
            row['column_candidates']=hits
            row['spanning']=bool(columns and b[0]<=min(c[2] for c in columns) and b[2]>=max(c[0] for c in columns) and len(hits)!=1)
            if p['region_type'] in ('UNKNOWN','MATH_CANDIDATE') or (columns and not hits and not row['spanning']):
                row['verification_status']='READING_ORDER_AMBIGUOUS'
                row['reason']='OCR formula/unknown fragment or unresolved column; no certified math bbox'
            body.append(row)
        rows.append(row)
    spanning=sorted([r for r in body if r.get('spanning')],key=lambda r:(r['bbox'][1],r['bbox'][0]))
    def key(r):
        # A spanning paragraph separates column flow above and below it.
        band=sum(s['bbox'][1]<r['bbox'][1] for s in spanning)
        if r in spanning:return (band,2,0,r['bbox'][1],r['bbox'][0])
        col=r['column_candidates'][0] if len(r['column_candidates'])==1 else 0
        return (band,1,col,r['bbox'][1],r['bbox'][0])
    ordered=sorted(body,key=key)
    for i,r in enumerate(ordered):r['proposed_reading_order_index']=i
    y_order=sorted(body,key=lambda r:(r['bbox'][1],r['bbox'][0]))
    return {'regions':rows,'main_candidate_sequence':[r['source_reference'] for r in ordered],
            'naive_y_sequence':[r['source_reference'] for r in y_order],
            'column_order_differs_from_naive_y':[r['source_reference'] for r in ordered]!=[r['source_reference'] for r in y_order],
            'columns':deepcopy(columns),'status_counts':dict(Counter(r['verification_status'] for r in rows)),
            'reading_order_verified':False}


def audit_order(source_blocks,translation_blocks,paragraphs,alignment,math_alignment,columns=(),figures=(),bindings=None,reviews=(),rendered_block_ids=None):
    """Keep localization-backed candidates separate from DOM-only/unresolved nodes."""
    source_ids=[b['id'] for b in source_blocks];target_ids=[b['id'] for b in translation_blocks]
    if len(set(source_ids))!=len(source_ids) or len(set(target_ids))!=len(target_ids):raise ValueError('Duplicate block identifiers')
    order=candidate_order(paragraphs,columns,figures);by_region={r['source_reference']:r for r in order['regions']}
    links=[]
    for l in alignment['links']:
        if not l['translation_block_ids']:continue
        r=by_region[l['paragraph_id']];state=r['verification_status']
        if l['verification_status']=='AMBIGUOUS':state='READING_ORDER_AMBIGUOUS'
        if l['verification_status']=='UNMATCHED':state='READING_ORDER_UNRESOLVED'
        review=next((v for v in reviews if independent_review(v,bindings or {},l['paragraph_id'],('source_order','translation_order','page_boundary','math_order'))),None)
        # Explicit index adjudication is required; neither confidence nor status label suffices.
        if review and type(review.get('proposed_reading_order_index')) is int and review['proposed_reading_order_index']>=0:
            state='READING_ORDER_VERIFIED'
        row={'paragraph_reference':l['paragraph_id'],'source_references':deepcopy(l['source_block_ids']),
             'translation_references':deepcopy(l['translation_block_ids']),
             'source_math_node_references':deepcopy(l['source_math_node_ids']),
             'translation_math_node_references':deepcopy(l['translation_math_node_ids']),
             'proposed_reading_order_index':review['proposed_reading_order_index'] if state=='READING_ORDER_VERIFIED' else r['proposed_reading_order_index'],
             'confidence':min(l.get('confidence') or .4,r['confidence']),
             'verification_status':state,'evidence':{'paragraph_bbox':l['source_bbox'],'provenance':deepcopy(l['provenance']),
                  'localization':deepcopy(l['evidence']),'independent_review':deepcopy(review)},
             'reason':None if state=='READING_ORDER_VERIFIED' else 'Source geometry/lexical link usable for review, independent order and semantics unverified'}
        links.append(row)
    # Contradictory rank across disjoint source regions vs disjoint target blocks.
    inversions=[]
    index_t={b['id']:i for i,b in enumerate(translation_blocks)}
    for i,a in enumerate(links):
        for b in links[i+1:]:
            ai=a['proposed_reading_order_index'];bi=b['proposed_reading_order_index']
            if ai is None or bi is None or ai==bi:continue
            at=[index_t[v] for v in a['translation_references']];bt=[index_t[v] for v in b['translation_references']]
            if set(at)&set(bt):continue
            if (ai<bi and min(at)>max(bt)) or (ai>bi and max(at)<min(bt)):
                inversions.append({'a':a['paragraph_reference'],'b':b['paragraph_reference'],'status':'CANDIDATE_ORDER_INVERSION','not_semantic_proof':True})
                for row in (a,b):row.update(verification_status='READING_ORDER_AMBIGUOUS',reason='Candidate source order conflicts with target DOM sequence; must review')
    def block_rows(blocks,side):
        result=[]
        for i,b in enumerate(blocks):
            related=[l for l in links if b['id'] in l[side+'_references']]
            indices=sorted({l['proposed_reading_order_index'] for l in related if l['proposed_reading_order_index'] is not None})
            status='READING_ORDER_UNRESOLVED' if not related else ('READING_ORDER_AMBIGUOUS' if len(indices)!=1 or any(l['verification_status']=='READING_ORDER_AMBIGUOUS' for l in related) else 'READING_ORDER_CANDIDATE')
            if related and all(l['verification_status']=='READING_ORDER_VERIFIED' for l in related) and len(indices)==1:status='READING_ORDER_VERIFIED'
            result.append({'reference':b['id'],'source_references':sorted({v for l in related for v in l['source_references']}),
                'translation_references':sorted({v for l in related for v in l['translation_references']}),
                'math_node_references':deepcopy(b['math_indices']),'saved_dom_index':i,
                'proposed_reading_order_index':indices[0] if len(indices)==1 else None,
                'verification_status':status,'confidence':min([l['confidence'] for l in related],default=0),
                'evidence':{'paragraph_references':[l['paragraph_reference'] for l in related],'basis':'Saved DOM ownership retained; source order only where localized'},
                'reason':None if status=='READING_ORDER_VERIFIED' else 'DOM index is inventory order, not verified reading order'})
        return result
    src_rows=block_rows(source_blocks,'source');vi_rows=block_rows(translation_blocks,'translation')
    repeated_text=defaultdict(list)
    for b in translation_blocks:
        key=' '.join(b['non_math_text'].split())
        if len(key)>=12:repeated_text[key].append(b['id'])
    duplicate_candidates=[{'text':k,'block_ids':v,'status':'REPEATED_TEXT_REVIEW_REQUIRED','removed':False} for k,v in repeated_text.items() if len(v)>1]
    math_rows=[]
    for side,blocks,rows,key in [('source',source_blocks,src_rows,'source_math_ids'),('translation',translation_blocks,vi_rows,'math_node_ids')]:
        for b,r in zip(blocks,rows):
            for idx in b['math_indices']:
                lexical=[deepcopy(l) for l in math_alignment.get('links',[]) if idx in l.get(key,[])]
                math_rows.append({'side':side,'index':idx,'block_reference':b['id'],'proposed_reading_order_index':r['proposed_reading_order_index'],
                    'verification_status':r['verification_status'],'lexical_links':lexical,'math_verified':False,
                    'evidence':'Saved math/block ownership; lexical alignment not equivalence or individually measured bbox'})
    rendered=rendered_block_ids if rendered_block_ids is not None else []
    coverage={'expected_translation_block_ids':target_ids,'rendered_block_ids':rendered,
              'render_check_performed':rendered_block_ids is not None,
              'missing_rendered_block_ids':[i for i in target_ids if i not in rendered],
              'duplicate_rendered_block_ids':[i for i,n in Counter(rendered).items() if n>1],
              'unexpected_rendered_block_ids':[i for i in rendered if i not in target_ids],
              'unlocalized_translation_block_ids':[r['reference'] for r in vi_rows if r['verification_status']=='READING_ORDER_UNRESOLVED']}
    source_text=''.join(b['non_math_text'] for b in source_blocks)
    notes=[{'translation_reference':b['id'],'text':b['non_math_text'],'status':'SOURCE_SUPPORT_NOT_FOUND_IN_SAVED_TRANSCRIPTION_UNVERIFIED',
            'reason':'Vietnamese continuation note; no next-page marker found in saved CN transcription. Adjacent pages unavailable; preserved, not proven extra.'}
           for b in translation_blocks if 'tiếp tục ở trang sau' in b['non_math_text'] and not re.search(r'下[页頁]|[续續]',source_text)]
    return {'status':'EXPERIMENTAL_UNVERIFIED','source_region_order':order,'paragraph_links':links,
            'source_blocks':src_rows,'translation_blocks':vi_rows,'math_nodes':math_rows,'inversions':inversions,
            'duplicate_text_candidates':duplicate_candidates,'translation_only_note_candidates':notes,'render_coverage':coverage,
            'source_order_counts':dict(Counter(r['verification_status'] for r in src_rows)),
            'translation_order_counts':dict(Counter(r['verification_status'] for r in vi_rows)),
            'link_order_counts':dict(Counter(r['verification_status'] for r in links)),
            'file_identifier':'114','printed_page_number_observation':'100','printed_page_number_verified':False,
            'adjacent_page_membership':'UNVERIFIED','limits':'No independent reviews supplied; geometry/DOM agreement alone does not verify reading order.'}
