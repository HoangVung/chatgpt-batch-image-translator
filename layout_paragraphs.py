"""Offline OCR paragraph sidecar; geometric/lexical candidates never certify order."""
from copy import deepcopy
from statistics import median
import re
from layout_source_bbox import chinese_key, align_source_blocks


def envelope(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def reconstruct(boxes, source_hash, regions=()):
    """Partition every line exactly once, without modifying the OCR inventory.

    Continue only a unique aligned nearest text line. Symmetric alternatives,
    columns, section/indent boundaries and intervening math/captions abstain.
    Region references are auxiliary evidence, never semantic certification.
    """
    original = deepcopy(boxes)
    if len({b['id'] for b in boxes}) != len(boxes):
        raise ValueError('Duplicate OCR line IDs')
    for b in boxes:
        x,y,r,t = b['bbox']
        if b.get('source_image_sha256') != source_hash or not x < r or not y < t:
            raise ValueError('Invalid source binding/bbox')
    scale = median([b['bbox'][3]-b['bbox'][1] for b in boxes]) if boxes else 1
    ordered = sorted(boxes, key=lambda b:(b['bbox'][1],b['bbox'][0],b['id']))
    def kind(b):
        s=b['text'].strip()
        if b.get('classification')=='caption_candidate' or re.match(r'^图\s*\d+[-－]\d+',s):return 'CAPTION'
        if s=='平面几何' or b.get('classification')=='heading_candidate':return 'HEADING'
        if re.fullmatch(r'\d+',s) and b['bbox'][1]>max((v['bbox'][3] for v in boxes),default=0)-2*scale:return 'FOOTER'
        if len(chinese_key(s))>=2:return 'BODY_TEXT'
        if any(c in s for c in '=∠⊥·²') or b.get('classification')=='math_candidate':return 'MATH_CANDIDATE'
        return 'UNKNOWN'
    kinds={b['id']:kind(b) for b in ordered}
    def section(b):return bool(re.match(r'^(充分性|必要性|例\s*\d+|证明)',b['text'].strip()))
    def continuation(a,b):
        x,y,r,t=a['bbox']; u,v,w,z=b['bbox']; h=max(t-y,z-v)
        overlap=max(0,min(r,w)-max(x,u)); gap=v-t
        if kinds[b['id']]!='BODY_TEXT' or section(b):return False
        if not v>y or not -.12*h<=gap<=.65*h:return False
        if abs((z-v)-(t-y))>.45*h or overlap<.65*min(r-x,w-u):return False
        # Permit a source first-line indent to return left, never a new indent.
        if not -1.8*h<=u-x<=.65*h:return False
        corridor=[max(x,u),t,min(r,w),v]
        for c in ordered:
            if c['id'] in (a['id'],b['id']):continue
            q=c['bbox']
            if kinds[c['id']]!='BODY_TEXT' and q[1]<v and q[3]>t and q[0]<corridor[2] and q[2]>corridor[0]:return False
        return True
    used=set(); paragraphs=[]
    for first in ordered:
        if first['id'] in used:continue
        group=[first];used.add(first['id']);ambiguous=False
        if kinds[first['id']]=='BODY_TEXT':
            while True:
                choices=[b for b in ordered if b['id'] not in used and continuation(group[-1],b)]
                if not choices:break
                nearest=min(b['bbox'][1] for b in choices)
                choices=[b for b in choices if b['bbox'][1]<nearest+.35*scale]
                if len(choices)!=1:ambiguous=True;break
                nxt=choices[0]
                # Another aligned line at its y signals a column/fragment ambiguity.
                competitors=[b for b in ordered if b['id'] not in used and b['id']!=nxt['id'] and
                             kinds[b['id']]=='BODY_TEXT' and abs(b['bbox'][1]-nxt['bbox'][1])<.35*scale and
                             continuation(group[-1],b)]
                if competitors:ambiguous=True;break
                group.append(nxt);used.add(nxt['id'])
        bounds=envelope([b['bbox'] for b in group]);typ=kinds[first['id']]
        refs=sorted({r['id'] for r in regions if r['bbox'][0]<bounds[2] and r['bbox'][2]>bounds[0]
                     and r['bbox'][1]<bounds[3] and r['bbox'][3]>bounds[1]})
        state='PARAGRAPH_AMBIGUOUS' if ambiguous or typ in ('UNKNOWN','MATH_CANDIDATE') else 'PARAGRAPH_CANDIDATE'
        paragraphs.append({'paragraph_id':f'paragraph:{len(paragraphs)}','source_line_ids':[b['id'] for b in group],
            'source_bbox':bounds,'region_type':typ,'reading_order_candidate':len(paragraphs),
            'reading_order_verified':False,'confidence':min(b['confidence'] for b in group)*(.5 if ambiguous else .85),
            'verification_status':state,'text_candidate':''.join(b['text'] for b in group),
            'evidence':{'method':'UNIQUE_ALIGNED_LINE_CONTINUATION_WITH_SECTION_INDENT_AND_BARRIER_CHECKS',
                'source_image_sha256':source_hash,'region_references':refs,
                'line_evidence':[{'id':b['id'],'bbox':b['bbox'],'confidence':b['confidence'],
                    'extraction_method':b.get('extraction_method'),'region_reference':b.get('region_reference')} for b in group],
                'limits':'Geometric order and OCR content unverified; math/labels kept separate.'}})
    assert boxes==original
    return {'source_lines':original,'paragraphs':paragraphs,'source_image_sha256':source_hash,
            'verification_status':'EXPERIMENTAL_UNVERIFIED','all_lines_preserved':len(used)==len(boxes)}


def align_paragraphs(reconstruction, source_blocks, translation_blocks, block_links, math_alignment, provenance):
    """Reuse measured line lexical matching and saved block/math evidence.

    Uniquely contained paragraph text supplements the TASK 3F line windows.
    Many-source/target membership remains explicit, not positional pairing.
    """
    boxes=reconstruction['source_lines'];ps=reconstruction['paragraphs']
    measured=align_source_blocks(boxes,source_blocks,reconstruction['source_image_sha256']) if boxes else []
    by_source={r['source_block_id']:r for r in measured};links=[]
    for p in ps:
        sids=[];ambiguous=False;methods=[]
        if p['region_type'] not in ('BODY_TEXT','HEADING'):
            status='UNMATCHED'
        else:
            pkey=chinese_key(p['text_candidate'])
            for b in source_blocks:
                row=by_source.get(b['id'],{});key=chinese_key(b['non_math_text'])
                grounded=row.get('status')=='ALIGNED_CANDIDATE' and bool(set(row.get('ocr_box_ids',[])) & set(p['source_line_ids']))
                hits=[q for q in ps if key and key in chinese_key(q['text_candidate']) and q['region_type'] in ('BODY_TEXT','HEADING')]
                distinct=sum(chinese_key(v['non_math_text'])==key for v in source_blocks)==1
                lexical=bool(key and (len(key)>=6 or key=='平面几何') and key in pkey and len(hits)==1 and distinct
                             and min(e['confidence'] for e in p['evidence']['line_evidence'])>=.75)
                if grounded or lexical:
                    sids.append(b['id']);methods.append('MEASURED_LINE_LINK' if grounded else 'UNIQUE_PARAGRAPH_CJK_CONTAINMENT')
                elif len(key)>=6 and key in pkey and (not distinct or len(hits)>1):ambiguous=True
            status='AMBIGUOUS' if ambiguous or p['verification_status']=='PARAGRAPH_AMBIGUOUS' else ('ALIGNED_CANDIDATE' if sids else 'UNMATCHED')
        prior=[l for l in block_links if l['source_text_reference'] in sids]
        tids=sorted({t for l in prior for t in l['translation_block_ids']},key=lambda s:int(s.rsplit(':',1)[1]))
        nodes=sorted({i for b in translation_blocks if b['id'] in tids for i in b['math_indices']})
        math_links=[deepcopy(l) for l in math_alignment.get('links',[]) if set(l.get('source_text_references',[]))&set(sids)]
        links.append({'paragraph_id':p['paragraph_id'],'source_bbox':p['source_bbox'],'source_line_ids':p['source_line_ids'],
            'source_block_ids':sids,'source_block_paragraph_groups':{sid:[q['paragraph_id'] for q in ps if set(q['source_line_ids']) & set(by_source.get(sid,{}).get('ocr_box_ids',[]))] for sid in sids},'translation_block_ids':tids,'translation_math_node_ids':nodes,
            'source_math_node_ids':sorted({i for b in source_blocks if b['id'] in sids for i in b['math_indices']}),
            'lexical_math_candidates':math_links,'verification_status':status,
            'confidence':min([p['confidence'],*[l['confidence'] for l in prior]]) if tids else None,
            'provenance':deepcopy(provenance),'evidence':{'localization_methods':methods,'saved_block_links':deepcopy(prior)},
            'eligible_for_anchor':False,'reading_order_verified':False,'math_verified':False})
    linked={t for l in links for t in l['translation_block_ids']}
    return {'links':links,'unmatched_translation_block_ids':[b['id'] for b in translation_blocks if b['id'] not in linked],
            'verified_anchors':0,'status':'NOT_ANCHORABLE','math_alignment':deepcopy(math_alignment)}
