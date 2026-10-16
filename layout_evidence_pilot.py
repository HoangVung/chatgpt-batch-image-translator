"""Offline dataset preparation using genuine TASK2D rasters. No invented text."""
import argparse
import csv
import html
import json
import shutil
from collections import Counter
from pathlib import Path
from layout_dataset import build_dataset,write_dataset,load_reviews
from translation_evidence import digest,file_hash,incomplete


def run(task2d,output,*,evidence_dir=None,review_path=None):
    root,out=Path(task2d),Path(output);out.mkdir(parents=True)
    reports_before={str(p):file_hash(p) for p in root.rglob('*') if p.is_file()}
    records=json.loads((root/'records.json').read_text(encoding='utf8'))
    reviews=load_reviews(review_path) if review_path else []
    artifacts=[]
    if evidence_dir:
        artifacts=[json.loads(p.read_text(encoding='utf8')) for p in Path(evidence_dir).rglob('translation-attempt-*.json')]
        # Completed capture datasets have generated-image bindings; attempts alone do not.
        artifacts.extend(json.loads(p.read_text(encoding='utf8'))['translation'] for p in Path(evidence_dir).rglob('dataset.json'))
    datasets=[];rows=[];image_hashes={};queue=[];crops=0;page=['<!doctype html><meta charset="utf-8"><title>TASK 2E</title><style>body{font:16px sans-serif;max-width:1400px;margin:auto}img{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}.hold{border:3px solid #b91c1c}article{padding:18px;margin:24px 0;border:1px solid #aaa}</style>',
        '<h1>TASK 2E — Translation evidence & readiness</h1><p>Offline: không gọi ChatGPT, không OCR, không giả lập phản hồi. Dữ liệu thu thập chưa chứng minh dịch/toán đúng.</p>']
    for a in records:
        ident=a['pair_id'];source,generated=a['source_copy'],a['generated_copy']
        if file_hash(source)!=a['image_hashes']['source'] or file_hash(generated)!=a['image_hashes']['generated']:
            raise ValueError('TASK2D image binding changed: '+ident)
        image_hashes.update({source:a['image_hashes']['source'],generated:a['image_hashes']['generated']})
        matches=[e for e in artifacts if e.get('source_sha256')==a['image_hashes']['source'] and e.get('generated_sha256')==a['image_hashes']['generated'] and e.get('status')=='COLLECTED_UNVERIFIED']
        distinct={digest(e):e for e in matches}
        evidence=next(iter(distinct.values())) if len(distinct)==1 else incomplete('Multiple distinct captured responses; association ambiguous') if distinct else None
        d=build_dataset(source,generated,evidence=evidence,region_qc=a['region_qc'],metadata=dict(a['metadata'],pair_id=ident,offline_provenance='TASK2D immutable snapshots and cached region measurements'),reviews=reviews)
        d=write_dataset(d,out/ident,export_crops=True);datasets.append(d)
        crops+=sum(r.get('decoded_pixels_exact') is True for r in d['geometry_crops'])
        r=d['readiness'];unknown=sum(x.get('comparison_type')=='UNKNOWN' for rs in a['region_qc']['regions'].values() for x in rs)
        rows.append(dict(pair_id=ident,translation_status=d['translation']['status'],readiness=r['status'],source_geometry_crops=len(d['geometry_crops']),unknown_regions=unknown,missing=' | '.join(r['missing'])))
        if r['status']=='HIGH_RISK_HOLD':queue.append({'pair_id':ident,'dataset':str((out/ident/'dataset.json').resolve()),'status':r['status'],'independent_review_status':'NOT_VERIFIED'})
        with (root/ident/'comparison.png').open('rb') as src,(out/ident/'comparison.png').open('xb') as dst:shutil.copyfileobj(src,dst)
        text=d['translation'].get('text')
        page.append(f'<article class="{"hold" if r["status"]=="HIGH_RISK_HOLD" else ""}"><h2>{html.escape(ident)} — {r["status"]}</h2><a href="{ident}/dataset.json">Dataset / hashes / vùng / nhãn</a><p>Văn bản: {d["translation"]["status"]}</p><pre>{html.escape(text if text is not None else "Chưa có phản hồi văn bản ChatGPT trong dữ liệu TASK 2D.")}</pre><p>{html.escape("; ".join(r["missing"]))}</p><img loading="lazy" src="{ident+'/comparison.png'}">')
        for crop in d['geometry_crops']:
            if crop.get('decoded_pixels_exact'):page.append(f'<p>Hình nguồn ứng viên {html.escape(crop["region_id"])} — CANDIDATE_UNVERIFIED</p><img loading="lazy" style="max-width:450px" src="{ident}/geometry/{Path(crop["path"]).name}">')
        page.append('</article>')
        if len(rows)%10==0:print(f'{len(rows)}/{len(records)} datasets',flush=True)
    with (out/'results.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    summary={'pairs':len(rows),'images':len(image_hashes),'translation_statuses':dict(Counter(r['translation_status'] for r in rows)),
             'readiness':dict(Counter(r['readiness'] for r in rows)),'pages_with_complete_verified_data':sum(r['readiness']=='READY_FOR_PILOT' for r in rows),
             'pages_missing_translation':sum(r['translation_status']!='COLLECTED_UNVERIFIED' for r in rows),'exact_pixel_geometry_crops':crops,
             'unknown_regions':sum(r['unknown_regions'] for r in rows),'ready_pairs':[r['pair_id'] for r in rows if r['readiness']=='READY_FOR_PILOT'],
             'high_risk_pairs':[r['pair_id'] for r in queue],'accuracy':'NOT_ESTIMATED',
             'blocker':'Historical TASK2D contains rasters/QC, no captured translation turns; future opt-in DOM capture is fixture-tested, not proven in a live provider session.'}
    integrity={'images_unchanged':all(file_hash(p)==h for p,h in image_hashes.items()),'task2d_files_unchanged':all(file_hash(p)==h for p,h in reports_before.items())}
    assert all(integrity.values()),integrity
    for name,value in [('summary.json',summary),('integrity.json',integrity),('high-risk-review-queue.json',queue),('datasets.json',datasets)]:
        with (out/name).open('x',encoding='utf8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
    # Historical independent labels are retained separately, not inferred from predictions.
    with (out/'reused-independent-labels.json').open('x',encoding='utf8') as f:
        json.dump(json.loads((root/'independent-labels.json').read_text(encoding='utf8')),f,ensure_ascii=False,indent=2)
    (out/'reviews.example.json').write_text(json.dumps({'reviews':[]},indent=2),encoding='utf8')
    (out/'review.html').write_text('\n'.join(page),encoding='utf8')
    (out/'summary.md').write_text('# TASK 2E — Offline pilot\n\n'+json.dumps(summary,ensure_ascii=False,indent=2)+'\n\nBảo toàn: '+str(integrity)+'\n\nChưa đủ văn bản/công thức đã kiểm chứng, dữ liệu hình học và nhãn vùng/thứ tự đọc/template để dựng trang. Không có READY_FOR_PILOT vì QC không thay thế kiểm chứng độc lập. Crops giữ đúng pixel giải mã nguồn; không thay hình trong ảnh dịch.\n',encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--task2d',required=True);p.add_argument('--output',required=True);p.add_argument('--evidence-dir');p.add_argument('--reviews')
    a=p.parse_args();run(a.task2d,a.output,evidence_dir=a.evidence_dir,review_path=a.reviews)
if __name__=='__main__':main()
