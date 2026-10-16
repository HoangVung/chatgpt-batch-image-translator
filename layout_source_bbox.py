"""Offline source OCR boxes. Text links are candidates, never certified math."""
from __future__ import annotations
from collections import Counter
import hashlib
import math
from pathlib import Path
import re


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def chinese_key(text):
    """Matching only: omit non-Chinese symbols, retain raw input unchanged."""
    return ''.join(re.findall(r'[\u4e00-\u9fff]', text or ''))


def make_boxes(polygons, texts, scores, source_hash, image_size):
    if not (len(polygons) == len(texts) == len(scores)):
        raise ValueError('OCR inventory lengths differ')
    w, h = image_size
    rows = []
    for i, (quad, text, score) in enumerate(zip(polygons, texts, scores)):
        points = [[float(x), float(y)] for x, y in quad]
        score = float(score)
        if len(points) != 4 or not all(math.isfinite(v) for p in points for v in p):
            raise ValueError('Invalid OCR quadrilateral')
        if not isinstance(text, str) or not text.strip() or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Missing text or invalid OCR confidence')
        xs, ys = zip(*points)
        box = [min(xs), min(ys), max(xs), max(ys)]
        if not (0 <= box[0] < box[2] <= w and 0 <= box[1] < box[3] <= h):
            raise ValueError('OCR bbox outside source image')
        kind = 'text_candidate' if chinese_key(text) else 'unknown'
        if re.fullmatch(r'\s*图\s*3\s*[-－—]\s*5[123]\s*', text):
            kind = 'caption_candidate'
        rows.append({'id': f'ocr:line:{i}', 'page_identifier': '114', 'source_image_sha256': source_hash,
                     'text': text, 'quadrilateral': points, 'bbox': box, 'confidence': score,
                     'classification': kind, 'extraction_method': 'RapidOCR_ONNX_CPU',
                     'verification_status': 'OCR_UNVERIFIED', 'reading_order_verified': False})
    return rows


def _stackable(a, b):
    x0,y0,x1,y1 = a['bbox']; u0,v0,u1,v1 = b['bbox']
    overlap = max(0, min(x1,u1)-max(x0,u0))
    return (v0 > y0 and -min(y1-y0,v1-v0)*.3 <= v0-y1 <= 2*max(y1-y0,v1-v0)
            and overlap >= .5*min(x1-x0,u1-u0))


def align_source_blocks(boxes, source_blocks, expected_source_hash, page_identifier='114'):
    """Unique CJK skeleton containment; no rank/fuzzy/math inference.

    Group only physically stacked OCR lines, at most four. Omitted math is
    explicitly NOT verified. Repeated skeletons and multiple locations abstain.
    """
    if page_identifier != '114' or any(b.get('source_image_sha256') != expected_source_hash
            or b.get('page_identifier') != page_identifier for b in boxes):
        raise ValueError('Wrong source page/hash')
    counts = Counter(chinese_key(b.get('non_math_text')) for b in source_blocks)
    ordered = sorted(boxes, key=lambda b: (b['bbox'][1],b['bbox'][0]))
    windows = []
    for first in ordered:
        group = [first]
        windows.append(group[:])
        for _ in range(3):
            choices = [b for b in ordered if b not in group and _stackable(group[-1], b)]
            if not choices: break
            following = min(choices, key=lambda b:(b['bbox'][1],b['bbox'][0]))
            group.append(following); windows.append(group[:])
    results = []
    for index, block in enumerate(source_blocks):
        key = chinese_key(block.get('non_math_text'))
        row = {'source_block_id':block.get('id', f'src:block:{index}'), 'ocr_box_ids':[],
               'source_bbox':None, 'status':'UNMATCHED','confidence':None,
               'method':'UNIQUE_CJK_SKELETON_CONTAINMENT_MEASURED_LINE_STACK',
               'matched_cjk_key':key,'math_verified':False,'reading_order_verified':False,
               'semantic_completeness':'NOT_PROVEN'}
        if counts[key] > 1 and key:
            row.update(status='AMBIGUOUS', reason='Repeated Chinese skeleton in saved source blocks')
        elif len(key) < 6 and key != '平面几何':
            row['reason'] = 'Insufficient distinctive Chinese text; math-only/short connectors not localized'
        else:
            hits = [g for g in windows if key and key in ''.join(chinese_key(b['text']) for b in g)
                    and min(b['confidence'] for b in g) >= .75]
            # Exclude larger windows containing an already sufficient smaller set.
            hits = [g for g in hits if not any(set(b['id'] for b in f) < set(b['id'] for b in g) for f in hits)]
            unique = {tuple(b['id'] for b in g):g for g in hits}
            if len(unique) == 1:
                group = next(iter(unique.values())); bounds = [b['bbox'] for b in group]
                row.update(status='ALIGNED_CANDIDATE',ocr_box_ids=[b['id'] for b in group],
                    source_bbox=[min(b[0] for b in bounds),min(b[1] for b in bounds),max(b[2] for b in bounds),max(b[3] for b in bounds)],
                    confidence=min(b['confidence'] for b in group),reason='Unique full Chinese skeleton found in measured OCR line(s); symbols/math not certified')
            elif unique:
                row.update(status='AMBIGUOUS', reason='Multiple measured OCR locations match',
                           candidate_box_groups=[list(k) for k in unique])
            else: row['reason']='No unique exact Chinese skeleton match in measured OCR lines'
        results.append(row)
    return results
