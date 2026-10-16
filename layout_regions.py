"""Additive region evidence for raster QC. No OCR, verified math, or rebuilding."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from layout_qc import _pixel_box, _boxes_overlap, _box_distance

REGION_TYPES = ('HEADER', 'BODY_TEXT', 'MATH_FORMULA', 'GEOMETRY_DIAGRAM',
                'FOOTER', 'DECORATION', 'UNKNOWN')
RISK_TYPES = ('COSMETIC', 'LAYOUT', 'CONTENT_SUSPECTED', 'MATH_HIGH_RISK', 'UNKNOWN')
LIMITATIONS = [
    'All raster classes and confidences are provisional heuristics, not calibrated probabilities.',
    'UNKNOWN includes standalone text/formula candidates; no inline math or mathematical correctness is verified.',
    'Region envelopes may overlap; component segmentation may merge or miss content.',
    'No independent labels means no accuracy, precision or recall can be reported.',
    'Storage filename pairing alone cannot exclude a wrong original or incorrect page order.',
]


def _valid_box(box):
    return (isinstance(box, (list, tuple)) and len(box) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) and 0 <= v <= 1 for v in box)
            and box[0] < box[2] and box[1] < box[3])


def load_independent_labels(path):
    """Read human annotations separately. Exact hash + bbox binds each label.

    File: {labels: [{image_sha256, region, type, reviewer, basis, verified:true}]}.
    Machine confidence is never converted into a label.
    """
    data = json.loads(Path(path).read_text(encoding='utf8'))
    if not isinstance(data, dict) or not isinstance(data.get('labels'), list):
        raise ValueError('Expected an independent labels list')
    rows = data['labels']
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Each label must be an object')
        digest = row.get('image_sha256', '')
        if (not isinstance(digest, str) or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)
                or not _valid_box(row.get('region')) or row.get('type') not in REGION_TYPES
                or row.get('verified') is not True
                or any(not isinstance(row.get(k), str) or not row[k].strip()
                       for k in ('reviewer', 'basis'))):
            raise ValueError('Labels need exact image hash, valid box, type, reviewer and independent basis')
    return copy.deepcopy(rows)


def segment_regions(metrics, *, side, metadata=None, labels=(), image_sha256=None):
    """Reuse bounded TASK2C measurements. Coordinates refer to detected page frame."""
    metadata = metadata or {}
    regions = []
    cover = metrics.get('ink_fraction', 0) > .85

    def add(box, kind, confidence, method, **extra):
        if not _valid_box(box):
            return
        confidence = min(float(confidence), float(metrics.get('confidence', 0)),
                         float(metrics.get('frame_confidence', 0)))
        regions.append(dict(id=f'{side}:{len(regions)+1}', bbox=_pixel_box(box, metrics),
                            normalized_bbox=list(box), predicted_type=kind,
                            confidence=confidence, method=method, evidence='heuristic',
                            counterpart_id=None, **extra))

    if cover:
        add(metrics.get('normalized_bbox'), 'UNKNOWN', .25, 'broad_dark_background_outside_white_paper_model')
    else:
        for kind in ('header', 'footer'):
            band = metrics.get('bands', {}).get(kind, {})
            add(band.get('box'), kind.upper(), band.get('confidence', 0), 'connected_band_candidate')
        geometry = metrics.get('geometry_regions', [])
        for candidate in geometry:
            add(candidate['box'], 'GEOMETRY_DIAGRAM', candidate.get('confidence', 0),
                'connected_line_shape_candidate_not_semantic', signature=candidate.get('signature'))
        formulas = metrics.get('formula_candidates', [])
        for candidate in formulas:
            add(candidate['box'], 'UNKNOWN', min(.55, candidate.get('confidence', 0)),
                'standalone_text_or_formula_ambiguous', candidate_types=['BODY_TEXT', 'MATH_FORMULA'])
        for box in metrics.get('text_line_regions', []):
            if any(_boxes_overlap(box, f['box']) for f in formulas):
                continue
            add(box, 'BODY_TEXT', .72, 'glyph_row_candidate_not_ocr')
        # Retain unexplained marks rather than silently removing them.
        for box in metrics.get('edge_regions', []):
            if not any(max(abs(a-b) for a,b in zip(box, r['normalized_bbox'])) <= .001 for r in regions):
                add(box, 'UNKNOWN', .45, 'unclassified_edge_component')
        if not regions:
            add(metrics.get('normalized_bbox'), 'UNKNOWN', .40, 'unclassified_ink_envelope')

    # Existing independent TASK2C edge evidence is localized to the exact box.
    annotations = metadata.get('edge_verification', []) if side == 'generated' else []
    for annotation in annotations:
        box = annotation.get('region') if isinstance(annotation, dict) else None
        if (not _valid_box(box) or annotation.get('verified') is not True
                or annotation.get('classification') != 'DECORATIVE_EDGE'
                or not isinstance(annotation.get('basis'), str) or not annotation['basis'].strip()):
            continue
        matches = [r for r in regions if max(abs(a-b) for a,b in zip(box,r['normalized_bbox'])) <= .001]
        if not matches:
            add(box, 'UNKNOWN', .45, 'independently_reviewed_edge_component')
            matches = regions[-1:]
        for r in matches:
            r['independent_label'] = dict(type='DECORATION', basis=annotation['basis'],
                                          provenance='TASK2C localized edge verification')

    for label in labels:
        if not image_sha256 or label.get('image_sha256') != image_sha256:
            continue
        matches = [r for r in regions if max(abs(a-b) for a,b in zip(label['region'],r['normalized_bbox'])) <= .001]
        if not matches:
            add(label['region'], 'UNKNOWN', .40, 'independently_annotated_region')
            matches = regions[-1:]
        for r in matches:
            r['independent_label'] = copy.deepcopy(label)
    for r in regions:
        r['comparison_type'] = r.get('independent_label', {}).get('type', r['predicted_type'])
        r['classification_verified'] = 'independent_label' in r
    return regions


def pairing_evidence(metadata):
    metadata = metadata or {}
    pages = [metadata.get(k) for k in ('page_number', 'source_page_number', 'generated_page_number')]
    pages = [p for p in pages if p is not None]
    if any(isinstance(p, bool) or not isinstance(p, int) or p < 1 for p in pages) or len(set(pages)) > 1:
        return {'status': 'CONFLICT', 'reason': 'Explicit page metadata conflicts or is invalid'}
    if metadata.get('pairing_method') == 'worker' and metadata.get('pairing_basis') == 'source_used_for_this_download':
        return {'status': 'WORKER_BOUND', 'reason': 'Exact source supplied by this download worker; no semantic verification'}
    if (metadata.get('pairing_verified') is True and pages
            and isinstance(metadata.get('pairing_basis'), str) and metadata['pairing_basis'].strip()):
        return {'status': 'INDEPENDENTLY_VERIFIED', 'reason': metadata['pairing_basis']}
    return {'status': 'STORAGE_ONLY' if metadata.get('pairing_method') else 'UNVERIFIED',
            'reason': 'Storage mapping available, but wrong original/page cannot be excluded independently'}


def compare_regions(qc, profile, *, metadata=None, labels=(), image_hashes=None):
    """Independent region report; preserve legacy QC/schema and worker decisions."""
    metadata, image_hashes = metadata or {}, image_hashes or {}
    metrics = qc.get('metrics', {})
    regions = {side: segment_regions(metrics.get(side, {}), side=side, metadata=metadata,
                                    labels=labels, image_sha256=image_hashes.get(side))
               for side in ('source', 'generated')}
    pair = pairing_evidence(metadata)
    warnings, matches = [], []
    minimum = profile.source_thresholds['min_confidence']
    supported = all(metrics.get(s) and min(metrics[s].get('confidence', 0),
                         metrics[s].get('frame_confidence', 0)) >= minimum for s in regions)
    cover = any(metrics.get(s, {}).get('ink_fraction', 0) > .85 for s in regions)

    def warning(code, risk, reason, confidence=0., source=None, generated=None, high=False):
        warnings.append(dict(code=code, risk=risk, reason=reason, confidence=confidence,
                             evidence='suspected' if risk != 'UNKNOWN' else 'insufficient',
                             source_region_id=source, generated_region_id=generated, high_risk=high))

    if pair['status'] == 'CONFLICT':
        warning('PAIRING_CONFLICT', 'UNKNOWN', pair['reason'])
    elif not supported or cover:
        warning('REGIONS_UNRELIABLE', 'UNKNOWN', 'Missing/low-confidence measurements or cover outside paper model')
    else:
        # Global nearest candidates per kind, one-to-one and bidirectional.
        # BODY_TEXT is compared as an envelope: translated line counts may differ.
        for kind in ('HEADER', 'FOOTER', 'GEOMETRY_DIAGRAM', 'MATH_FORMULA', 'DECORATION'):
            src = [r for r in regions['source'] if r['comparison_type'] == kind and (r['confidence'] >= minimum or r['classification_verified'])]
            gen = [r for r in regions['generated'] if r['comparison_type'] == kind and (r['confidence'] >= minimum or r['classification_verified'])]
            edges = sorted((_box_distance(a['normalized_bbox'], b['normalized_bbox']), a['id'], b['id']) for a in src for b in gen)
            used_s, used_g = set(), set()
            for distance, sid, gid in edges:
                if sid in used_s or gid in used_g or distance > .30:
                    continue
                a=next(r for r in src if r['id']==sid); b=next(r for r in gen if r['id']==gid)
                used_s.add(sid); used_g.add(gid)
                a['counterpart_id']=gid; b['counterpart_id']=sid
                ab,bb=a['normalized_bbox'],b['normalized_bbox']
                size=max(abs((bb[2]-bb[0])/(ab[2]-ab[0])-1),abs((bb[3]-bb[1])/(ab[3]-ab[1])-1))
                confidence=min(a['confidence'],b['confidence'])
                shape=None
                if a.get('signature') and b.get('signature'):
                    shape=sum(abs(x-y) for x,y in zip(a['signature'],b['signature']))/2
                matches.append(dict(source=sid,generated=gid,type=kind,position_delta=distance,size_delta=size,
                                    shape_delta=shape,confidence=confidence,method='one_to_one_nearest_candidate_heuristic'))
                risk='COSMETIC' if kind=='DECORATION' else 'MATH_HIGH_RISK' if kind in ('MATH_FORMULA','GEOMETRY_DIAGRAM') else 'LAYOUT'
                if distance > (profile.source_thresholds['header_footer_warning'] if kind in ('HEADER','FOOTER') else .08):
                    warning(kind+'_POSITION',risk,'Matched region shifted in page-relative coordinates; identity remains provisional',confidence,sid,gid,high=risk=='MATH_HIGH_RISK')
                if size > .35:
                    warning(kind+'_SIZE',risk,'Matched region size differs substantially; raster does not verify content',confidence,sid,gid,high=risk=='MATH_HIGH_RISK')
                if shape is not None and shape > profile.source_thresholds['geometry_structure_warning']:
                    warning(kind+'_SHAPE',risk,'Coarse shape changed; labels/incidence cannot be validated',confidence,sid,gid,high=True)
            for side,items,used in (('source',src,used_s),('generated',gen,used_g)):
                for r in items:
                    math_kind=kind in ('GEOMETRY_DIAGRAM','MATH_FORMULA')
                    if r['id'] not in used:
                        risk='COSMETIC' if kind=='DECORATION' else 'MATH_HIGH_RISK' if math_kind else 'UNKNOWN'
                        warning(kind+('_MISSING' if side=='source' else '_UNMATCHED'),risk,
                                'No counterpart candidate; investigate segmentation and pairing before attributing content error',
                                r['confidence'], r['id'] if side=='source' else None,
                                r['id'] if side=='generated' else None, high=math_kind)
                    box=r['normalized_bbox']
                    if math_kind and min(box[0],box[1],1-box[2],1-box[3]) <= profile.source_thresholds['edge_warning']:
                        warning(kind+'_CLIPPING_SUSPECTED','MATH_HIGH_RISK','Region reaches page edge; clipping suspected, not proven',
                                r['confidence'],r['id'] if side=='source' else None,r['id'] if side=='generated' else None,high=True)
        body_boxes={}
        for side in regions:
            bs=[r['normalized_bbox'] for r in regions[side] if r['comparison_type']=='BODY_TEXT']
            body_boxes[side]=[min(b[0] for b in bs),min(b[1] for b in bs),max(b[2] for b in bs),max(b[3] for b in bs)] if bs else None
        a,b=body_boxes['source'],body_boxes['generated']
        if a and b and max(abs(a[0]-b[0]),abs(a[2]-b[2])) > profile.source_thresholds['margin_warning']:
            warning('BODY_MARGINS','LAYOUT','Text envelope horizontal margins differ; line breaks and text length are allowed',.72)
        density=[metrics[s].get('content_evidence',{}).get('body_ink_fraction') for s in ('source','generated')]
        if all(v is not None for v in density) and abs(density[1]-density[0])>.10:
            warning('BODY_DENSITY','LAYOUT','Body raster density differs unusually; not proof of missing translated text',.70)
        for r in regions['generated']:
            if r['comparison_type']=='BODY_TEXT' and min(r['normalized_bbox'][0],1-r['normalized_bbox'][2]) <= .01:
                warning('BODY_OVERFLOW','LAYOUT','Text-like region reaches horizontal page safety margin',r['confidence'],generated=r['id'])

    if pair['status'] != 'CONFLICT' and qc.get('content_addition_evidence',{}).get('source_near_blank_body') and qc.get('content_addition_evidence',{}).get('large_new_body'):
        warning('NEAR_BLANK_NEW_BODY','CONTENT_SUSPECTED',
                'Near-blank source has substantial translated body. '+pair['reason']+'; no AI-cause conclusion.',.90,high=True)
    if pair['status'] != 'CONFLICT' and not cover:
        sm, gm = metrics.get('source', {}), metrics.get('generated', {})
        se, ge = sm.get('content_evidence', {}), gm.get('content_evidence', {})
        source_body = (se.get('body_ink_fraction', 0) >= .005 and se.get('body_text_lines', 0) >= 2
                       and se.get('substantial_body_components', 0) >= 8)
        target_blank = (ge.get('body_ink_fraction') is not None and ge['body_ink_fraction'] <= .0003
                        and ge.get('body_text_lines') == 0 and ge.get('body_geometry_candidates') == 0
                        and ge.get('substantial_body_components') == 0)
        resolution = all(min(metrics.get(side, {}).get('analysis_size', [0, 0])) >= 150 for side in regions)
        if source_body and target_blank and resolution and sm.get('confidence', 0) >= minimum:
            warning('BODY_MISSING_SUSPECTED', 'CONTENT_SUSPECTED',
                    'Substantial source text-like body absent from near-blank translation; verify pairing and segmentation', .85, high=True)
    for side in regions:
        for r in regions[side]:
            if r['comparison_type']=='UNKNOWN' or (r['confidence']<minimum and not r['classification_verified']):
                warning('REGION_UNKNOWN','UNKNOWN','Region identity lacks evidence: '+r['method'],r['confidence'],
                        r['id'] if side=='source' else None,r['id'] if side=='generated' else None)
    if pair['status'] in ('STORAGE_ONLY','UNVERIFIED'):
        warning('PAIRING_NOT_INDEPENDENT','UNKNOWN',pair['reason'])
    page=metadata.get('page_number')
    parity={'status':'UNASSESSED','reason':'Printed page number and trusted parity template unavailable'}
    if isinstance(page,int) and not isinstance(page,bool) and page>0:
        # Existing source-aware metrics already apply the profile's parity template.
        pm=[m for m in qc.get('source_aware',{}).get('metrics',[]) if m.get('name') in ('header_alignment', 'footer_alignment')]
        parity=dict(status='SOURCE_QC_TEMPLATE' if pm else 'UNASSESSED', printed_page=page,
                    metrics=pm, reason='Reuse source-aware template metrics; no parity derived from storage IDs')
    for m in parity.get('metrics', []):
        if m.get('status') == 'WARNING':
            warning('PARITY_'+m['name'].upper(), 'LAYOUT', m['reason'], m.get('confidence', 0))
    high=any(w['high_risk'] for w in warnings)
    unknown=any(w['risk']=='UNKNOWN' for w in warnings)
    return dict(version=1,regions=regions,matches=matches,warnings=warnings,pairing=pair,parity=parity,
                high_risk=high,qc_accepted=not (high or unknown or warnings) and qc.get('status') == 'PASS',
                publication_review_required=high,blocks_batch=False,next_action='continue',
                limitations=list(LIMITATIONS),
                rebuilder_input={side:{'content_regions':[r['id'] for r in rs if r['comparison_type']=='BODY_TEXT'],
                    'geometry_to_preserve':[r['id'] for r in rs if r['comparison_type']=='GEOMETRY_DIAGRAM'],
                    'formulas_to_preserve':[r['id'] for r in rs if r['comparison_type']=='MATH_FORMULA'],
                    'header_footer':[r['id'] for r in rs if r['comparison_type'] in ('HEADER','FOOTER')],
                    'uncertain_regions':[r['id'] for r in rs if r['comparison_type']=='UNKNOWN' or r['confidence']<minimum],
                    'ready_for_rebuild':False} for side,rs in regions.items()})
