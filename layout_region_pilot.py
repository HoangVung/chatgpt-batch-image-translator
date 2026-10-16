"""Replay TASK2C region evidence against immutable real rasters, no provider calls.

Run: py -3.12 layout_region_pilot.py --task2b DIR --task2c DIR --output NEW_DIR
Optional --labels FILE applies independent, hash-bound region annotations.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import html
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from PIL import Image, ImageDraw
from layout_profile import load_profile
from layout_regions import compare_regions, load_independent_labels, REGION_TYPES, RISK_TYPES
from layout_qc import check_layout

COLORS={'HEADER':'#047857','BODY_TEXT':'#2563eb','MATH_FORMULA':'#c026d3','GEOMETRY_DIAGRAM':'#dc2626',
        'FOOTER':'#0891b2','DECORATION':'#b45309','UNKNOWN':'#64748b'}

def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
def sha(p):
    d=hashlib.sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):d.update(chunk)
    return d.hexdigest()
def write(p,data):
    with Path(p).open('x',encoding='utf8') as f:json.dump(data,f,ensure_ascii=False,indent=2)

def visual(source,generated,report,target):
    canvas=Image.new('RGB',(1320,1100),'#eeeeee');draw=ImageDraw.Draw(canvas)
    for side,path,x in [('source',source,20),('generated',generated,680)]:
        draw.text((x,10),side.upper()+' (candidate boxes; labels independent)',fill='black')
        with Image.open(path) as im:
            rgba=im.convert('RGBA');paper=Image.new('RGBA',rgba.size,'white');paper.alpha_composite(rgba)
            preview=paper.convert('RGB');preview.thumbnail((620,900))
            px=x+(620-preview.width)//2;py=40+(900-preview.height)//2
            canvas.paste(preview,(px,py));sx=preview.width/im.width;sy=preview.height/im.height
            for r in report['regions'][side]:
                b=r['bbox'];box=[px+b[0]*sx,py+b[1]*sy,px+b[2]*sx,py+b[3]*sy]
                color=COLORS[r['comparison_type']]
                draw.rectangle(box,outline=color,width=2)
                draw.text((box[0],max(40,box[1]-10)),r['id'].split(':')[1],fill=color)
            preview.close();rgba.close();paper.close()
    y=955
    for k,c in COLORS.items():draw.text((20,y),k+'  '+c,fill=c);y+=18
    draw.text((410,960),'HIGH_RISK: '+str(report['high_risk'])+'   QC accepted: '+str(report['qc_accepted']),fill='black')
    draw.text((410,984),'Boxes are provisional. Raster does not verify translation or mathematics.',fill='black')
    draw.text((410,1008),'See per-pair JSON for confidence, links, methods and independent labels.',fill='black')
    with Path(target).open('xb') as f:canvas.save(f,format='PNG')
    canvas.close()

def run(task2b,task2c,output,labels_path=None):
    b,c,out=map(Path,(task2b,task2c,output));out.mkdir(parents=True)  # exclusively new
    old_files={str(p):sha(p) for root in (b,c) for p in root.rglob('*') if p.is_file()}
    originals=read(b/'input-hashes-before.json')
    # Real image inventory, not synthetic or report-only proxy inputs.
    if not all(Path(p).is_file() and sha(p)==v for p,v in originals.items()):
        raise ValueError('Real input inventory no longer matches TASK2B')
    old=read(b/'final-reports.json');previous=read(c/'after-reports.json')
    with (b/'pairs_manifest.csv').open(encoding='utf-8-sig',newline='') as f:
        manifest=[r for r in csv.DictReader(f) if r['status']=='MATCHED']
    if len(manifest)!=len(old) or len(old)!=len(previous):raise ValueError('Pilot report/manifest length conflict')
    edges={r['pair_id']:r['annotations'] for r in read(c/'edge-verification.json')}
    labels=load_independent_labels(labels_path) if labels_path else []
    write(out/'independent-labels.json',{'region_labels':labels,'reused_task2c_labels':read(c/'reused-independent-labels.json'),
                                      'localized_edge_labels':read(c/'edge-verification.json'),
                                      'note':'Independent historical human annotations, not model predictions. No accuracy estimated.'})
    profile=replace(load_profile(b/'profile.json'),max_pixels=60000000,normalize_enabled=False)
    records=[];rows=[];queue=[];image_hashes={};counts=Counter();predictions=Counter();risks=Counter()
    improvements=[]
    for a,p,m in zip(old,previous,manifest):
        pair_id=m['pair_id']
        if pair_id!=p['pair_id']:raise ValueError('Pilot ordering conflict')
        source,generated=Path(p['source_copy']),Path(p['original_copy'])
        hs={'source':sha(source),'generated':sha(generated)}
        if hs['generated']!=a['original_sha256'] or hs['source']!=a['source_sha256']:
            raise ValueError('TASK2C cached measurements require unchanged input snapshots')
        image_hashes.update({str(source):hs['source'],str(generated):hs['generated']})
        metadata=dict(a.get('metadata',{}))
        if pair_id in ('1_1','3_3','4_4'):metadata['page_type']='cover'
        metadata['edge_verification']=edges.get(pair_id,[])
        metadata['pairing_method']=m['method'];metadata['storage_id']=pair_id
        if m['printed_page']:
            metadata['page_number']=int(m['printed_page'])
            metadata['printed_page_basis']='Inherited TASK2B printed-page mapping; not storage parity'
        r=compare_regions(p['qc'],profile,metadata=metadata,labels=labels,image_hashes=hs)
        d=out/pair_id;d.mkdir();write(d/'regions.json',r);visual(source,generated,r,d/'comparison.png')
        insufficient=0
        for rs in r['regions'].values():
            for region in rs:
                counts[region['comparison_type']]+=1;predictions[region['predicted_type']]+=1
                if region['comparison_type']=='UNKNOWN' or (region['confidence']<profile.source_thresholds['min_confidence'] and not region['classification_verified']):insufficient+=1
        for w in r['warnings']:risks[w['risk']]+=1
        math_old=[f['code'] for f in p['qc'].get('findings',[]) if f['code'].startswith('SOURCE_GEOMETRY_')]
        if metadata.get('page_type')=='cover' and math_old and not any(w['risk']=='MATH_HIGH_RISK' for w in r['warnings']):
            improvements.append(dict(pair_id=pair_id,old_codes=math_old,new_risk='UNKNOWN',reason='Cover abstention; not mathematical error or PASS'))
        rec=dict(pair_id=pair_id,metadata=metadata,image_hashes=hs,source_copy=str(source),generated_copy=str(generated),
                 measurement_provenance=p['provenance'],region_report=str(d/'regions.json'),
                 task2c_layout_status=p['qc']['layout_status'],task2c_content_risk=p['qc']['content_risk'],
                 region_qc=r)
        records.append(rec)
        rows.append(dict(pair_id=pair_id,task2c_layout_status=p['qc']['layout_status'],task2c_content_risk=p['qc']['content_risk'],
                         high_risk=r['high_risk'],qc_accepted=r['qc_accepted'],source_regions=len(r['regions']['source']),
                         generated_regions=len(r['regions']['generated']),insufficient_regions=insufficient,
                         risks='|'.join(sorted({w['risk'] for w in r['warnings']})),pairing=r['pairing']['status']))
        codes=[w['code'] for w in r['warnings']]
        priority=0 if r['high_risk'] else 1 if any('MISSING' in x or 'FORMULA' in x for x in codes) else 2 if insufficient else 3
        queue.append(dict(pair_id=pair_id,priority=priority,high_risk=r['high_risk'],codes=sorted(set(codes)),
                          independent_review='Verify pairing, diagram/formula identity and UNKNOWN regions; no action required during batch'))
        if len(records)%10==0:print(f'{len(records)}/{len(previous)} pairs',flush=True)
    queue.sort(key=lambda r:(r['priority'],int(r['pair_id'].split('_')[0])))
    normalized=[]
    for i in (2,42,64):
        old_p=read(c/'pilots'/str(i)/'report.json');path=c/'pilots'/str(i)/'normalized.png'
        rec=next(r for r in records if r['pair_id']==f'{i}_{i}')
        qc=check_layout(rec['source_copy'],path,profile,metadata=rec['metadata'])
        r=compare_regions(qc,profile,metadata=rec['metadata'])
        d=out/f'normalized-{i}';d.mkdir();write(d/'regions.json',r);visual(rec['source_copy'],path,r,d/'comparison.png')
        normalized.append(dict(pair_id=f'{i}_{i}',task2c_pixel_proof=old_p['pixel_proof'],input=str(path),sha256=sha(path),
                               qc_status=qc['status'],high_risk=r['high_risk'],risks=dict(Counter(w['risk'] for w in r['warnings'])),
                               note='Derivative already canvas-normalized by TASK2C, inspected without modification; warnings remain provisional.'))
    write(out/'records.json',records);write(out/'review-queue.json',queue);write(out/'normalized-inspection.json',normalized)
    with (out/'results.csv').open('x',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    integrity={'real_inputs':len(originals),'real_inputs_unchanged':all(sha(p)==v for p,v in originals.items()),
               'snapshot_inputs_unchanged':all(sha(p)==v for p,v in image_hashes.items()),
               'task2b_task2c_files_unchanged':all(sha(p)==v for p,v in old_files.items())}
    write(out/'integrity.json',integrity)
    if not all(integrity[k] for k in integrity if k!='real_inputs'):raise ValueError('Integrity verification failed')
    summary=dict(pairs=len(records),images=len(image_hashes),regions_by_comparison_type={k:counts[k] for k in REGION_TYPES},
                 regions_by_predicted_type={k:predictions[k] for k in REGION_TYPES},insufficient_regions=sum(r['insufficient_regions'] for r in rows),
                 warnings_by_risk={k:risks[k] for k in RISK_TYPES},high_risk_pairs=[r['pair_id'] for r in rows if r['high_risk']],
                 task2c_high_risk_pairs=[r['pair_id'] for r in rows if r['task2c_content_risk']=='HIGH_RISK'],
                 geometry_warning_abstentions=improvements,localized_independent_decorations=counts['DECORATION'],
                 independent_region_accuracy='NOT_ESTIMATED',measurement_mode='cached TASK2C plus real-raster/hash verification; fresh QC on normalized 2/42/64',
                 limitations=['Historical page-level labels do not provide a complete region gold standard.',
                              'Heuristic matching can overflag geometry/reflow. High risk is a review priority, not confirmed math error.',
                              'Code 6 storage tuple agrees; printed page/source lineage not independently known; AI addition cause not established.'])
    write(out/'summary.json',summary)
    page=['<!doctype html><meta charset="utf-8"><title>TASK 2D - Region QC</title><style>body{font:16px sans-serif;max-width:1400px;margin:auto}img{width:100%;height:auto}article{margin:32px 0;padding:20px;border:1px solid #ccc}.high{border:3px solid #b91c1c}</style>',
          '<h1>TASK 2D — Hậu kiểm vùng ảnh</h1><p>Dự đoán heuristic; HIGH_RISK chưa chứng minh lỗi toán. Không có độ chính xác được giả định. Không chặn batch.</p>',
          '<p><a href="summary.json">Tổng hợp</a> · <a href="independent-labels.json">Nhãn độc lập</a> · <a href="review-queue.json">Ưu tiên hậu kiểm</a></p>']
    for item in queue:
        ident=item['pair_id'];row=next(r for r in rows if r['pair_id']==ident)
        page.append(f'<article class="{"high" if item["high_risk"] else ""}"><h2>{ident} — HIGH_RISK: {item["high_risk"]}</h2><p>{html.escape(row["risks"])}</p><a href="{ident}/regions.json">Tọa độ / bằng chứng / liên kết vùng</a><img loading="lazy" src="{ident}/comparison.png"></article>')
    for i in (2,42,64):page.append(f'<h2>Ảnh {i} sau chuẩn hóa TASK 2C</h2><img loading="lazy" src="normalized-{i}/comparison.png">')
    (out/'review.html').write_text('\n'.join(page),encoding='utf8')
    notes=f'''# TASK 2D — Pilot vùng ảnh thật

- {summary['pairs']} cặp / {summary['images']} ảnh thật; tái dùng phép đo TASK 2C gắn với hash ảnh bất biến.
- Vùng theo loại đối chiếu: {summary['regions_by_comparison_type']}.
- Vùng thiếu căn cứ: {summary['insufficient_regions']}.
- Cảnh báo theo rủi ro (số finding, không phải số trang): {summary['warnings_by_risk']}.
- HIGH_RISK: {', '.join(summary['high_risk_pairs'])}.
- TASK 2C HIGH_RISK: {summary['task2c_high_risk_pairs']}; TASK 2D xét thêm từng vùng, nên các mức không tương đương.
- {sum(len(r['old_codes']) for r in improvements)} raw finding hình học trên {len(improvements)} bìa được diễn giải UNKNOWN; giữ nguyên QC TASK 2C. {counts['DECORATION']} vùng trang trí theo nhãn mép độc lập được đối chiếu riêng, không kết luận nội dung dịch sai.

Mã 3: bìa màu ngoài mô hình giấy trắng, UNKNOWN thay vì mất hình toán. Mã 6: ghép tuple 6_6 khớp metadata/tệp và hash; chưa biết trang in/lịch sử nguồn nên không quy nguyên nhân là AI thêm nội dung. Vẫn ưu tiên hậu kiểm vì nguồn gần trắng khác bản dịch có thân bài.

Ảnh 2/42/64: dùng nguyên derivative đã lưu TASK 2C và đo QC mới; xem normalized-inspection.json. Padding bảo toàn pixel không khắc phục dịch chuyển theo tỷ lệ trang, hình hoặc chữ; không tạo derivative khác.

Không có bộ nhãn vùng đầy đủ: không tính accuracy/precision/recall giả định. Nhãn lịch sử và nhãn vùng bổ sung lưu riêng. Người duyệt có thể bổ sung sau batch bằng labels.json (hash, bbox tương đối, type, reviewer, basis, verified=true), rồi chạy lại vào thư mục mới. Nhãn máy không tự chuyển thành ground truth.

Các phép sửa tự động an toàn có thể xét: thêm canvas trắng/dịch toàn raster theo normalizer hiện có khi vừa khung, không cắt/scale/đổi pixel, và không có rủi ro nội dung hoặc vùng toán chưa xử lý. Đây là đề xuất, pilot không sửa ảnh. Không tự xóa họa tiết vì có thể làm mất thông tin.

TASK 3 cần văn bản Việt đáng tin cậy, thứ tự đọc, công thức có biểu diễn đã kiểm chứng, hình nguồn kèm mặt nạ và nhãn/caption liên kết, vùng đặt không chồng lấn, mẫu trang chẵn/lẻ và bộ nhãn độc lập đa dạng. rebuilder_input chỉ là hợp đồng vùng, ready_for_rebuild luôn false; chưa có engine dàn trang.

Bảo toàn: {integrity}. Đây là kiểm nghiệm offline, không phải chạy provider hoặc quan sát worker đang hoạt động.
'''
    (out/'summary.md').write_text(notes,encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return summary

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--task2b',required=True);p.add_argument('--task2c',required=True);p.add_argument('--output',required=True);p.add_argument('--labels')
    a=p.parse_args();run(a.task2b,a.task2c,a.output,a.labels)
if __name__=='__main__':main()
