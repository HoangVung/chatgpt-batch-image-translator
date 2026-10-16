"""TASK 3H raw-pixel geometry crop and completeness review; no AI redraw."""
from pathlib import Path
from copy import deepcopy
import hashlib
import re
from PIL import Image
from translation_evidence import file_hash
from layout_reading_order import independent_review, overlap

GEOMETRY_STATES=('GEOMETRY_VERIFIED','GEOMETRY_CANDIDATE','GEOMETRY_AMBIGUOUS','GEOMETRY_INCOMPLETE')
SOURCE_114_SHA='9a237e8398c8db4d75ac3b17c7c27930654662899b533f7d290dd5348f7e2cca'

# Current assistant's source/crop visual observations, explicitly not an independent
# adjudication. Every ROI/observation is bound to the existing source image hash.
PAGE114_PROPOSALS=[
    {'figure_id':'figure:3-51','caption_candidate':'图3-51','roi':[2640,430,3740,1665],
     'observations':{'label_candidates':['O','O₁','O₂','M','N','S','T'],
         'visible_components':'Three visible circular outlines, OM and MN segments, marked centres; no inference of mathematical relations.',
         'visual_extent_candidate':True,'uncertain_marks':[],
         'basis':'Assistant viewed full source and saved top-right crop; no independent review.',
         'crop_improvement':'More raw-source margin than the original ink-envelope crop.'}},
    {'figure_id':'figure:3-52','caption_candidate':'图3-52','roi':[2700,1730,3680,3130],
     'observations':{'label_candidates':['K','O','O₁','O₂','M','N','P','Q','S','S₁','S₂','T'],
         'visible_components':'Several circular outlines, solid/dashed connecting segments and angle marks; relations not certified.',
         'visual_extent_candidate':True,'uncertain_marks':['Small angle numerals and crowded S/S₁/S₂ marks need independent review.'],
         'basis':'Assistant viewed full source and saved middle crop; no independent review.',
         'crop_improvement':'Remove adjacent left prose and add top/bottom source context without trimming visible figure labels.'}},
    {'figure_id':'figure:3-53','caption_candidate':'图3-53','roi':[2680,3690,3710,4880],
     'observations':{'label_candidates':['A','B','C','D','E','F','I','M','N','O','P','Q'],
         'visible_components':'Triangle edges/extended segments, one visible circle, marked centres and crossing segments; no relation/redraw inference.',
         'visual_extent_candidate':True,'uncertain_marks':['Crowded A/F and centre labels require review at native resolution.'],
         'basis':'Assistant viewed full source and saved bottom crop; no independent review.',
         'crop_improvement':'Exclude top/left prose present in prior padded crop and preserve B/C/P/Q plus caption.'}},
]


def contains(outer,inner):
    return outer[0]<=inner[0] and outer[1]<=inner[1] and outer[2]>=inner[2] and outer[3]>=inner[3]


def border_ink(image,band=8):
    mask=image.convert('L').point(lambda p:255 if p<180 else 0)
    w,h=mask.size;band=min(band,w,h)
    strips={'left':(0,0,band,h),'right':(w-band,0,w,h),'top':(0,0,w,band),'bottom':(0,h-band,w,h)}
    return {side:mask.crop(box).histogram()[255] for side,box in strips.items()}


def review_geometry(source,expected_hash,proposals,ocr_boxes,output,reviews=()):
    """Save exclusive new crops with exact source-pixel provenance.

    Caption containment, white border and assistant observations are not review
    certification. OCR labels are not augmented with invented OCR observations.
    """
    source=Path(source);output=Path(output)
    if file_hash(source)!=expected_hash:raise ValueError('Source geometry hash mismatch')
    if any(b.get('source_image_sha256')!=expected_hash for b in ocr_boxes):raise ValueError('OCR hash mismatch')
    if len({p['figure_id'] for p in proposals})!=len(proposals):raise ValueError('Duplicate geometry IDs')
    with Image.open(source) as original:
        original.load();w,h=original.size
        for proposal in proposals:
            b=proposal['roi']
            if len(b)!=4 or any(type(v) is not int for v in b) or not 0<=b[0]<b[2]<=w or not 0<=b[1]<b[3]<=h:
                raise ValueError('Unsafe geometry ROI')
        output.mkdir(parents=True,exist_ok=False);rows=[]
        for proposal in proposals:
            b=proposal['roi'];crop=original.crop(b);name=proposal['figure_id'].replace(':','-')+'.png';path=output/name
            with path.open('xb') as f:crop.save(f,format='PNG')
            with Image.open(path) as saved:
                pixels_exact=saved.mode==crop.mode and saved.size==crop.size and saved.tobytes()==crop.tobytes()
            if not pixels_exact:raise ValueError('Geometry crop pixels changed')
            hits=[deepcopy(v) for v in ocr_boxes if overlap(v['bbox'],b)]
            cap=[v for v in hits if v['text'].replace(' ','')==proposal['caption_candidate'].replace(' ','')]
            cap_inside=[v for v in cap if contains(b,v['bbox'])]
            crossing=[v for v in hits if not contains(b,v['bbox'])]
            label_hits=[v for v in hits if v.get('classification')!='caption_candidate' and not re.search(r'[\u4e00-\u9fff]',v['text'])]
            prose=[v for v in hits if re.search(r'[\u4e00-\u9fff]',v['text']) and v not in cap]
            edges=border_ink(crop);observations=deepcopy(proposal.get('observations',{}))
            state='GEOMETRY_INCOMPLETE' if not cap_inside else ('GEOMETRY_AMBIGUOUS' if crossing or prose or any(edges.values()) else 'GEOMETRY_CANDIDATE')
            bindings={'source_image_sha256':expected_hash,'crop_sha256':file_hash(path)}
            reference=proposal['figure_id'];review=next((r for r in reviews if independent_review(r,bindings,reference,
                ('figure_extent','all_point_labels','caption','no_adjacent_prose','pixel_fidelity')) and r.get('roi')==b),None)
            if review and pixels_exact:state='GEOMETRY_VERIFIED'
            rows.append({'figure_id':reference,'roi':deepcopy(b),'source_image_sha256':expected_hash,
                'source_image_path':str(source.resolve()),'path':str(path.resolve()),'asset_reference':'geometry-crops/'+name,
                'crop_sha256':bindings['crop_sha256'],'pixel_sha256':hashlib.sha256(crop.tobytes()).hexdigest(),
                'mode':crop.mode,'size':list(crop.size),'decoded_pixels_exact':pixels_exact,'rotation':0,'resized':False,
                'caption_candidate':proposal['caption_candidate'],'caption_ocr_references':[v['id'] for v in cap_inside],
                'caption_bbox_candidates':[v['bbox'] for v in cap_inside],'ocr_label_candidates':label_hits,
                'edge_crossing_ocr':crossing,'adjacent_prose_candidates':prose,'border_ink_counts':edges,
                'visual_observations':observations,'verification_status':state,
                'crop_extent_candidate':bool(observations.get('visual_extent_candidate') and cap_inside),
                'labels_complete_verified':state=='GEOMETRY_VERIFIED','caption_verified':state=='GEOMETRY_VERIFIED',
                'independent_review':deepcopy(review),'binding':bindings,'inserted_in_qualified_preview':False,
                'reason':None if state=='GEOMETRY_VERIFIED' else 'Raw pixels and caption location preserved; assistant inspection/border/OCR do not independently certify all labels or complete figure.'})
    if file_hash(source)!=expected_hash:raise ValueError('Source changed during crop')
    return {'status':'EXPERIMENTAL_UNVERIFIED','source_image_sha256':expected_hash,'figures':rows,
            'verified_figures':sum(r['verification_status']=='GEOMETRY_VERIFIED' for r in rows),
            'crop_extent_candidates':sum(r['crop_extent_candidate'] for r in rows),
            'source_unchanged':True,'limits':'Completeness requires an independent bound review, not merely caption containment or an empty border.'}
