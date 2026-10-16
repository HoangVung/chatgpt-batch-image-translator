"""TASK 3H review/Hybrid pilot, reusing the unchanged offline renderer/solver."""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from copy import deepcopy
from dataclasses import asdict
from html import escape
import json
from pathlib import Path
import shutil
import subprocess
from PIL import Image
from layout_reading_order import audit_order,independent_review
from layout_geometry_review import review_geometry,PAGE114_PROPOSALS,SOURCE_114_SHA
from layout_adaptive import make_units,render_adaptive,POST_MEASURE
from layout_rebuilder import Tree,RebuildProfile,build_content
from layout_calibration import load_inputs,run_layout,math_integrity
from layout_alignment import blocks_for
from translation_evidence import file_hash

BLOCKED='HYBRID_PREVIEW_BLOCKED_UNVERIFIED_ALIGNMENT'


def select_anchors(alignment,order,bindings,reviews=()):
    """Do not trust pre-set VERIFIED labels; require exact independent binding."""
    order_links={l['paragraph_reference']:l for l in order['paragraph_links']};eligible=[];rejected=[]
    for link in alignment['links']:
        if not link['translation_block_ids']:continue
        ref=link['paragraph_id'];r=order_links.get(ref)
        review=next((v for v in reviews if independent_review(v,bindings,ref,
             ('page_pairing','bbox_content','translation_content','math','reading_order'))
             and v.get('source_bbox')==link['source_bbox'] and v.get('source_block_ids')==link['source_block_ids']
             and v.get('translation_block_ids')==link['translation_block_ids']
             and v.get('translation_math_node_ids')==link['translation_math_node_ids']),None)
        if (review and r and r['verification_status']=='READING_ORDER_VERIFIED'
            and independent_review((r.get('evidence') or {}).get('independent_review'),bindings,ref,
                ('source_order','translation_order','page_boundary','math_order'))
            and r['proposed_reading_order_index']==r['evidence']['independent_review'].get('proposed_reading_order_index')):
            eligible.append(dict(deepcopy(link),verification_status='ALIGNED_VERIFIED',independent_review=deepcopy(review),
                eligible_for_anchor=True,reading_order_verified=True,reading_order_index=r['proposed_reading_order_index']))
        else:rejected.append({'paragraph_id':ref,'status':'CANDIDATE_ONLY','reason':'No exact bound independent alignment and reading-order review'})
    owners=defaultdict(list)
    for l in eligible:
        for t in l['translation_block_ids']:owners[t].append(l['paragraph_id'])
    conflicts={p for values in owners.values() if len(values)>1 for p in values}
    index_counts=Counter(l['reading_order_index'] for l in eligible)
    conflicts.update(l['paragraph_id'] for l in eligible if index_counts[l['reading_order_index']]>1)
    valid=[]
    for l in eligible:
        if l['paragraph_id'] in conflicts:rejected.append({'paragraph_id':l['paragraph_id'],'status':'AMBIGUOUS','reason':'Conflicting reviewed block ownership/order index'})
        else:valid.append(l)
    return {'eligible_anchors':valid,'rejected_anchors':rejected,'verified_anchor_count':len(valid),
            'qualified_preview_status':'ELIGIBLE_EXPERIMENTAL_HYBRID' if valid else BLOCKED}


def hybrid_layout_preview(nodes,selection,source_size):
    """Prepare verified-reference units plus unlinked Full Reflow without reordering.

    The existing solver handles measured expansion/pagination. Source reference
    placement is adaptive, not a claim of exact pixel-height anchoring.
    """
    verified=selection['eligible_anchors']
    adapter={'links':[dict(l,verification_status='ALIGNED_CANDIDATE') for l in verified]}
    units=make_units(nodes,adapter,source_size)
    for u in units:
        u['status']='VERIFIED_REFERENCE_ADAPTIVE' if u['paragraph_id'] else 'UNRESOLVED_REFLOW'
    return {'units':units,'verified_anchors':len(verified),'anchored_block_ids':sorted({t for l in verified for t in l['translation_block_ids']}),
            'reflow_block_ids':[t for u in units if not u['paragraph_id'] for t in u['block_ids']],
            'status':selection['qualified_preview_status']}


def document(title,content):
    return '''<!doctype html><html lang="vi"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'self' file: data:"><style>body{font:17px Arial;margin:24px;background:#f0f1f3;color:#182124}h1{font-size:25px}.warning{background:#fff1cc;padding:14px}table{border-collapse:collapse;background:white;width:100%}td,th{border:1px solid #bbb;padding:10px;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:6px 0}figure{margin:0}img{max-width:100%}.row{display:flex;gap:14px;align-items:start}.row>figure{flex:1;min-width:0}.panel{background:white;border:1px solid #bbb;padding:16px;margin:18px 0}.crop{max-width:650px;max-height:700px;object-fit:contain}.status{color:#913f09}a{color:#1261a4}</style><title>'''+escape(title)+'</title><h1>'+escape(title)+'</h1><p class="warning">EXPERIMENTAL_UNVERIFIED · HIGH_RISK_HOLD · NOT_ANCHORABLE. File identifier 114; số in quan sát 100, chưa xác minh. Candidate/assistant inspection không phải independent review.</p>'+content+'</html>'


def json_pre(value):return '<pre>'+escape(json.dumps(value,ensure_ascii=False,indent=2))+'</pre>'


def additional_page_coverage(root,current_sha):
    """Inspect only existing TASK 2G capture dataset manifests, no book traversal."""
    found=[]
    for base in sorted((root/'output').glob('task2g-*')):
        for p in sorted(base.glob('capture/capture-*/dataset/dataset.json')):
            try:
                d=json.loads(p.read_text(encoding='utf8'));s=d.get('source_image',{});t=d.get('translated_image',{})
                capture=d.get('translation',{}).get('capture_audit')
                source_valid=bool(s.get('path') and Path(s['path']).is_file() and file_hash(s['path'])==s.get('sha256'))
                target_valid=bool(t.get('path') and Path(t['path']).is_file() and file_hash(t['path'])==t.get('sha256'))
                found.append({'dataset_reference':str(p.resolve()),'source_sha256':s.get('sha256'),'current_page':s.get('sha256')==current_sha,
                    'source_hash_matches':source_valid,'translation_image_hash_matches':target_valid,'saved_capture_audit_present':bool(capture),
                    'eligibility':'CURRENT_PAGE_ONLY' if s.get('sha256')==current_sha else 'NEEDS_COMPLETE_BOUND_TRANSCRIPTION_TRANSLATION_MATH_REVIEW'})
            except (OSError,ValueError,KeyError) as exc:found.append({'dataset_reference':str(p),'eligibility':'INVALID_MANIFEST','reason':str(exc)})
    extra=[r for r in found if not r.get('current_page')]
    return {'scope':'Existing TASK 2G capture/dataset manifests only; no raster-only pairing or provider request',
            'manifests':found,'additional_pages_run':0,'status':'ADDITIONAL_PAGES_BLOCKED_NO_COMPLETE_BOUND_EVIDENCE',
            'reason':'No validated distinct-page transcription+Vietnamese+math bundle in inspected pilot manifests; adjacent raster files alone are not sufficient.',
            'distinct_other_source_hashes':sorted({r['source_sha256'] for r in extra if r.get('source_sha256')})}


def build(root,output):
    from playwright.sync_api import sync_playwright
    root=Path(root).resolve();output=Path(output).resolve();read=lambda p:json.loads(Path(p).read_text(encoding='utf-8-sig'))
    g=root/'output/task3g-page114-20261011-release-diagnostic';f=root/'output/task3f-page114-20261011-ocr';droot=root/'output/task3d-page114-20261011-final'
    baseline=root/'output/task3b-page114-20261011-recheck';prior=read(g/'adaptive-layout.json');alignment=read(g/'paragraph-alignment.json')
    reconstruction=read(g/'paragraph-regions.json');ocr=read(f/'source-bboxes.json');saved=read(droot/'alignment-dataset.json');old_geometry=read(f/'geometry-review.json')
    if not all(file_hash(p)==sha for p,sha in prior['original_hashes'].items()):raise ValueError('TASK 3G original evidence changed')
    if ocr['source_image_sha256']!=SOURCE_114_SHA or reconstruction['source_image_sha256']!=SOURCE_114_SHA:raise ValueError('Wrong pilot source')
    candidate_links=[l for l in alignment['links'] if l['translation_block_ids']]
    if len(candidate_links)!=7:raise ValueError('Expected seven saved paragraph links')
    fixture=root/'tests/fixtures/layout_task2g_page114.json';fixture_data=read(fixture);capture=Path(fixture_data['source_artifact'])
    if not capture.is_absolute():capture=root/capture
    dataset_path=capture.parent/'dataset/dataset.json'
    dataset,candidate=load_inputs(dataset_path,fixture)
    content,rows,structure=build_content(candidate)
    source_blocks,source_rows,source_structure=blocks_for(saved['source_content_inventory']['candidate'],'src')
    if source_blocks!=saved['source_blocks'] or len(source_rows)!=67 or len(rows)!=66:raise ValueError('Saved source/target inventory mismatch')
    nodes=[n for n in Tree(content).root.walk() if n.tag in ('p','h1','h2','h3','h4') or 'display' in n.attrs.get('class','').split()]
    if len(nodes)!=53:raise ValueError('Vietnamese inventory mismatch')
    profile=RebuildProfile(**prior['profile']);size=tuple(prior['target_size'])
    status=subprocess.run(['git','status','--porcelain','-z'],cwd=root,capture_output=True,text=True,check=True).stdout
    existing=[root/entry[3:] for entry in status.split('\0') if entry and entry[3:] not in ('layout_reading_order.py','layout_geometry_review.py','layout_hybrid.py','tests/test_layout_hybrid.py')]
    historical=[p for folder in (g,f,droot) for p in folder.rglob('*') if p.is_file()]
    # Hash-only protection of dirty files is not broad code/content inspection.
    protected={**prior['original_hashes'],**{str(p.resolve()):file_hash(p) for p in historical+existing if p.is_file()},
               str(capture.resolve()):file_hash(capture),str(fixture.resolve()):file_hash(fixture),str(dataset_path.resolve()):file_hash(dataset_path)}
    bindings={'source_image_sha256':SOURCE_114_SHA,'capture_sha256':file_hash(capture),
              'source_html_sha256':source_structure['html_sha256'],'translation_html_sha256':structure['html_sha256'],
              'paragraph_alignment_sha256':file_hash(g/'paragraph-alignment.json')}
    output.mkdir(parents=True,exist_ok=False)
    def save(name,value):(output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    geometry=review_geometry(ocr['source_image_path'],SOURCE_114_SHA,PAGE114_PROPOSALS,ocr['boxes'],output/'geometry-crops')
    figure_regions=[{'figure_id':r['figure_id'],'bbox':r['roi']} for r in geometry['figures']]
    rendered_prior=[t for u in prior['post_render_measurement']['units'] for t in u['block_ids']]
    order=audit_order(source_blocks,saved['translation_blocks'],reconstruction['paragraphs'],alignment,saved['math_alignment'],
                     figures=figure_regions,bindings=bindings,rendered_block_ids=rendered_prior)
    selection=select_anchors(alignment,order,bindings)
    hybrid=hybrid_layout_preview(nodes,selection,ocr['source_image_size'])
    # Qualified output is blocked without a reviewed anchor; Full Reflow is a
    # separate reference, never renamed into hybrid success.
    attempts=[];expected=''.join(n['text'] for n in structure['nodes'] if n['kind']=='text')
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);context=browser.new_context(offline=True,viewport={'width':1280,'height':1760},device_scale_factor=1)
        context.route('**/*',lambda route:(attempts.append(route.request.url),route.abort()));page=context.new_page()
        metrics,reflow_measure=run_layout(page,content,profile,size,calibrated_style=True)
        reflow_integrity=math_integrity(structure,rows,reflow_measure)
        if metrics['content_text']!=expected or reflow_integrity['technical_preserved']!=66 or metrics['issues'] or any(p['overlaps'] for p in reflow_measure['pages']):
            raise ValueError('Safe reflow failed preservation/layout')
        (output/'reflow-reference.html').write_text(page.content(),encoding='utf8')
        for i in range(metrics['page_count']):page.locator('.page').nth(i).screenshot(path=str(output/f'reflow-reference-{i+1}.png'))
        # Reuse the TASK 3G measured widths for clearly separated candidate
        # diagnostic. No new heuristic is promoted to a true anchor.
        units=make_units(nodes,alignment,ocr['source_image_size'])
        prior_units={tuple(u['block_ids']):u for u in prior['solution']['placements']}
        for u in units:
            old=prior_units.get(tuple(u['block_ids']))
            if old:u.update(width=old['width'],left=old['left'])
        diagnostic_solution,measurement,post=render_adaptive(page,units,profile,size)
        if measurement is None:raise ValueError('Candidate diagnostic infeasible; safe reflow remains available')
        page.evaluate("() => document.querySelectorAll('.notice').forEach(e=>e.textContent='TASK 3H · CANDIDATE DIAGNOSTIC · NOT_ANCHORABLE · HÌNH CHƯA XÁC MINH')")
        page.add_style_tag(content='.unit[data-status="PARAGRAPH_CANDIDATE"]{outline:1px dashed #bf7600}.unit[data-status="UNMATCHED"]{background:#f6f8fa}')
        post=page.evaluate(POST_MEASURE)
        integrity=math_integrity(structure,rows,measurement)
        if post['content_text']!=expected or integrity['technical_preserved']!=66:raise ValueError('Diagnostic content/math changed')
        diagnostic_safe=not post['collisions'] and not post['overflow']
        (output/'candidate-diagnostic.html').write_text(page.content(),encoding='utf8')
        if diagnostic_safe:
            paths=[]
            for i in range(diagnostic_solution['page_count']):
                p=output/f'candidate-diagnostic-{i+1}.png';page.locator('.page').nth(i).screenshot(path=str(p));paths.append(p)
            canvas=Image.new('RGB',(1200*len(paths),1668),'white')
            for i,p in enumerate(paths):
                with Image.open(p) as im:canvas.paste(im,(1200*i,0))
            canvas.save(output/'candidate-diagnostic.png')
        qualified=None
        if selection['verified_anchor_count']:
            qsol,qmeasure,qpost=render_adaptive(page,hybrid['units'],profile,size)
            if qmeasure is not None:
                page.evaluate("() => document.querySelectorAll('.notice').forEach(e=>e.textContent='EXPERIMENTAL_UNVERIFIED · REVIEWED SOURCE REFERENCES + UNRESOLVED REFLOW · GEOMETRY NOT INSERTED')")
                qpost=page.evaluate(POST_MEASURE);qintegrity=math_integrity(structure,rows,qmeasure)
                if qpost['content_text']==expected and qintegrity['technical_preserved']==66 and not qpost['collisions'] and not qpost['overflow']:
                    qualified={'solution':qsol,'post_render_measurement':qpost,'math_integrity':qintegrity}
                    (output/'hybrid-preview.html').write_text(page.content(),encoding='utf8')
                    page.locator('.page').first.screenshot(path=str(output/'hybrid-preview.png'))
        version=browser.version;browser.close()
    if qualified is None:
        (output/'hybrid-preview.html').write_text(document('TASK 3H — '+BLOCKED,
            '<p class="status">0 anchor đủ review độc lập. Không tạo trang Hybrid đúng nguồn hoặc hybrid-preview.png.</p><p><a href="candidate-diagnostic.html">Candidate diagnostic (không phải Hybrid đủ điều kiện)</a> · <a href="reflow-reference.html">Full Reflow tham chiếu đủ nội dung</a> · <a href="alignment-review.html">Review 7 liên kết</a></p>'),encoding='utf8')
    # Export source/old crop context and literal link review from immutable inputs.
    (output/'alignment-crops').mkdir();(output/'old-geometry-crops').mkdir()
    source_map={b['id']:b for b in source_blocks};target_map={b['id']:b for b in saved['translation_blocks']};line_map={b['id']:b for b in ocr['boxes']}
    alignment_html='<p>Bảy liên kết được review; không nâng trạng thái do các thuật toán dùng cùng dữ liệu OCR.</p>'
    alignment_review=[]
    with Image.open(ocr['source_image_path']) as source:
        for i,l in enumerate(candidate_links):
            roi=[int(v) for v in l['source_bbox']];path=output/f'alignment-crops/paragraph-{i+1}.png'
            with path.open('xb') as fp:source.crop(roi).save(fp,format='PNG')
            lexical=[p for p in saved['math_alignment']['links'] if set(p['source_math_ids'])&set(l['source_math_node_ids']) or set(p['math_node_ids'])&set(l['translation_math_node_ids'])]
            sm=[{'index':m,'latex':source_rows[m]['latex']} for m in l['source_math_node_ids']]
            vm=[{'index':m,'latex':rows[m]['latex']} for m in l['translation_math_node_ids']]
            review={'paragraph_id':l['paragraph_id'],'source_bbox':roi,'ocr_text':[line_map[k]['text'] for k in l['source_line_ids']],
               'source_blocks':[source_map[k] for k in l['source_block_ids']],'translation_blocks':[target_map[k] for k in l['translation_block_ids']],
               'source_math':sm,'translation_math':vm,'lexical_math_links':lexical,'original_evidence':l['evidence'],'bindings':bindings,
               'verification_status':'ALIGNED_CANDIDATE','eligible_for_anchor':False,
               'review_points':['CJK key omits mathematical symbols; OCR can misread labels/operators.',
                    'Shared/normalized math links are not mathematical equivalence; inspect raw LaTeX.',
                    'Only linked saved blocks shown; paragraph lexical containment does not prove semantic completeness.',
                    'Source/target DOM order and page boundary need independent review.']}
            alignment_review.append(review)
            alignment_html+=f'<section class="panel"><h2>{escape(l["paragraph_id"])} — ALIGNED_CANDIDATE</h2><div class="row"><figure><b>Bbox nguồn {escape(str(roi))}</b><img class="crop" src="alignment-crops/paragraph-{i+1}.png"></figure><figure><b>OCR nguyên văn</b>'+json_pre(review['ocr_text'])+'</figure></div><table><tr><th>Khối Trung</th><th>Khối Việt</th></tr><tr><td>'+json_pre(review['source_blocks'])+'</td><td>'+json_pre(review['translation_blocks'])+'</td></tr><tr><td><b>Math nguồn</b>'+json_pre(sm)+'</td><td><b>Math Việt</b>'+json_pre(vm)+'</td></tr></table><details><summary>Căn cứ ghép, khác biệt lexical và điểm cần review</summary>'+json_pre(review['original_evidence'])+json_pre(lexical)+json_pre(review['review_points'])+json_pre(bindings)+'</details></section>'
    (output/'alignment-review.html').write_text(document('TASK 3H — Review 7 paragraph alignments',alignment_html),encoding='utf8');save('alignment-review.json',alignment_review)
    geometry_html='<p>Crop mới nguyên pixel, không resize/rotate/redraw. Nhãn dưới đây là quan sát candidate của assistant; cần review độc lập.</p>'
    # Match by explicit caption, never list position (saved order is 52,53,51).
    for fig in geometry['figures']:
        old=next((g for g in old_geometry if any(b['text'].replace(' ','')==fig['caption_candidate'] for b in g['ocr_captions_inside_crop'])),None)
        if old is None:raise ValueError('Missing caption-bound old crop')
        oldname=fig['figure_id'].replace(':','-')+'.png';shutil.copyfile(old['path'],output/'old-geometry-crops'/oldname)
        fig['previous_crop']={'sha256':file_hash(old['path']),'roi':old['padded_bbox'],'path':'old-geometry-crops/'+oldname}
        geometry_html+=f'<section class="panel"><h2>{escape(fig["figure_id"])} — {fig["verification_status"]}</h2><div class="row"><figure><b>3F crop cũ</b><img class="crop" src="old-geometry-crops/{oldname}"></figure><figure><b>3H ROI mới — raw pixels</b><img class="crop" src="{fig["asset_reference"]}"></figure></div>'+json_pre({k:fig[k] for k in ('roi','visual_observations','caption_ocr_references','border_ink_counts','edge_crossing_ocr','adjacent_prose_candidates','crop_sha256','decoded_pixels_exact','reason')})+'</section>'
    (output/'geometry-review.html').write_text(document('TASK 3H — Review 3 hình nguồn',geometry_html),encoding='utf8')
    for src,dst in [('source.png','source.png'),('chatgpt.png','chatgpt.png'),('task3b-1.png','task3b-1.png'),('task3b-2.png','task3b-2.png'),
                     ('adaptive-preview-1.png','task3g-1.png'),('adaptive-preview-2.png','task3g-2.png')]:shutil.copyfile(g/src,output/dst)
    order_content='<p>Thứ tự có định vị và thứ tự DOM chưa định vị được tách rõ. Hình/caption/nhãn có luồng phụ; không ép vào đoạn chữ theo y.</p>'
    order_content+='<h2>Luồng nguồn theo paragraph/bbox</h2><table><tr><th>Source</th><th>Vị trí/luồng</th><th>Thứ tự đề xuất</th><th>Trạng thái/căn cứ</th></tr>'
    for r in order['source_region_order']['regions']:
        order_content+='<tr><td>'+escape(r['source_reference'])+'</td><td>'+json_pre({'bbox':r['bbox'],'type':r['region_type'],'stream':r['stream'],'figures':r.get('figure_references',[])})+'</td><td>'+escape(str(r['proposed_reading_order_index']))+'</td><td>'+escape(r['verification_status'])+json_pre(r['evidence'])+escape(r['reason'])+'</td></tr>'
    order_content+='</table><h2>35 khối Trung / 53 khối Việt</h2>'
    for title,blocks in [('Nguồn',order['source_blocks']),('Bản Việt',order['translation_blocks'])]:
        order_content+='<h3>'+title+'</h3><table><tr><th>Khối/Math refs</th><th>Source → VI refs</th><th>DOM / order đề xuất</th><th>Trạng thái</th></tr>'
        for r in blocks:order_content+='<tr><td>'+escape(r['reference'])+json_pre(r['math_node_references'])+'</td><td>'+json_pre({'source':r['source_references'],'vi':r['translation_references']})+'</td><td>'+json_pre({'saved_dom_index':r['saved_dom_index'],'proposed':r['proposed_reading_order_index']})+'</td><td>'+escape(r['verification_status'])+'<p>'+escape(r['reason'] or '')+'</p></td></tr>'
        order_content+='</table>'
    order_content+='<h2>Đảo thứ tự / khối lặp / ghi chú trang sau</h2>'+json_pre({k:order[k] for k in ('inversions','duplicate_text_candidates','translation_only_note_candidates','render_coverage')})
    (output/'reading-order-review.html').write_text(document('TASK 3H — Reading order review',order_content),encoding='utf8')
    coverage=additional_page_coverage(root,SOURCE_114_SHA)
    actual_ids=[t for u in post['units'] for t in u['block_ids']]
    if actual_ids!=[b['id'] for b in saved['translation_blocks']]:raise ValueError('Missing/repeated/reordered Vietnamese block')
    coverage.update({'current_page':'114','printed_page_observation':'100','source_blocks':35,'source_math_nodes':67,
        'translation_blocks_preserved':len(actual_ids),'translation_math_nodes_preserved':integrity['technical_preserved'],
        'duplicate_rendered_math_nodes':sum(n['render_occurrences']!=1 for n in integrity['nodes']),
        'text_exact':post['content_text']==expected,'direct_paragraph_linked_translation_blocks':prior['translation_blocks_linked'],
        'unlocalized_translation_block_ids':order['render_coverage']['unlocalized_translation_block_ids'],
        'saved_lexical_math_linked_nodes':len({m for l in saved['math_alignment']['links'] for m in l['math_node_ids']}),
        'direct_paragraph_linked_math_nodes':len({m for l in candidate_links for m in l['translation_math_node_ids']}),
        'verified_math_nodes':0,'verified_figures':geometry['verified_figures'],'verified_anchors_used':0,
        'qualified_hybrid_pages':0 if qualified is None else qualified['solution']['page_count'],
        'reference_reflow_pages':metrics['page_count'],'candidate_diagnostic_pages':diagnostic_solution['page_count'],
        'candidate_diagnostic_collisions':post['collisions'],'candidate_diagnostic_overflow':post['overflow'],
        'geometry_collision_status':'NOT_ASSESSED_GEOMETRY_NOT_INSERTED','figure_caption_status':'DEBUG_REVIEW_ONLY_NOT_PLACED'})
    unchanged=all(file_hash(p)==sha for p,sha in protected.items())
    if not unchanged or attempts:raise ValueError('Protected evidence changed or network attempt')
    result={'mode':'hybrid_layout_preview','status':BLOCKED if qualified is None else 'EXPERIMENTAL_UNVERIFIED_HYBRID',
        'readiness':'HIGH_RISK_HOLD','anchor_status':'NOT_ANCHORABLE' if not selection['verified_anchor_count'] else 'PARTIAL_REVIEWED_REFERENCES',
        'selection':selection,'hybrid_plan':{k:v for k,v in hybrid.items() if k!='units'},'qualified_preview':qualified,
        'candidate_diagnostic':{'status':'SAFE_UNVERIFIED_DIAGNOSTIC' if diagnostic_safe else 'DIAGNOSTIC_LAYOUT_ISSUES',
            'solution':diagnostic_solution,'post_render_measurement':post,'math_integrity':integrity,'is_qualified_hybrid':False},
        'safe_reflow':{'page_count':metrics['page_count'],'issues':metrics['issues'],'math_integrity':reflow_integrity,'is_hybrid':False},
        'profile':asdict(profile),'target_size':list(size),'binding':bindings,'geometry_inserted':0,
        'original_hashes':protected,'original_hashes_unchanged':unchanged,'git_status_before':status,
        'production_integration':False,'network_attempts':attempts,'browser':version,
        'omitted_artifacts':[] if qualified else [{'name':'hybrid-preview.png','reason':BLOCKED+'; exporting reflow as Hybrid would misrepresent evidence.'}]}
    save('reading-order.json',order);save('geometry-inventory.json',geometry);save('hybrid-layout.json',result);save('coverage-report.json',coverage)
    compare='<p class="status">'+BLOCKED+'</p><p>3H hiển thị candidate diagnostic có viền cam cho vùng đề xuất, nền xám nhạt cho reflow. Không phải Hybrid đủ điều kiện; 0 anchor thực sự, không chèn hình chưa xác minh.</p><div class="row">'
    panels=[('SOURCE','source.png'),('CHATGPT','chatgpt.png'),('3B Full Reflow p1','task3b-1.png'),('3G Adaptive p1','task3g-1.png'),('3H Candidate diagnostic p1 — HYBRID BLOCKED','candidate-diagnostic-1.png' if diagnostic_safe else 'reflow-reference-1.png')]
    for label,name in panels:compare+=f'<figure><b>{escape(label)}</b><a href="{name}"><img src="{name}"></a></figure>'
    compare+='</div><h2>Toàn bộ trang tiếp theo</h2><div class="row">'
    for label,name in [('3B p2','task3b-2.png'),('3G p2','task3g-2.png')]:compare+=f'<figure><b>{label}</b><img src="{name}"></figure>'
    if diagnostic_safe:
        for i in range(1,diagnostic_solution['page_count']):compare+=f'<figure><b>3H diagnostic p{i+1}</b><img src="candidate-diagnostic-{i+1}.png"></figure>'
    compare+='</div><p><a href="hybrid-preview.html">Hybrid blocker</a> · <a href="candidate-diagnostic.html">Candidate diagnostic</a> · <a href="reflow-reference.html">Full Reflow reference</a> · <a href="reading-order-review.html">Reading order</a> · <a href="alignment-review.html">7 alignments</a> · <a href="geometry-review.html">3 hình</a></p><h2>Hình nguồn mới — chỉ debug</h2><div class="row">'
    for fig in geometry['figures']:compare+=f'<figure><b>{fig["figure_id"]} — {fig["verification_status"]}</b><img src="{fig["asset_reference"]}"></figure>'
    (output/'comparison.html').write_text(document('TASK 3H — Source / ChatGPT / 3B / 3G / 3H diagnostic',compare+'</div>'),encoding='utf8')
    text=f'''# TASK 3H — Reading Order, Geometry Verification & Hybrid Layout Pilot

Branch feat/book-layout-consistency. Offline only. EXPERIMENTAL_UNVERIFIED / HIGH_RISK_HOLD / NOT_ANCHORABLE.

{BLOCKED}: 0 anchor verified, 0 hình verified. Hoàn thành review/diagnostic; chưa tạo Hybrid đúng nguồn.
Không xuất hybrid-preview.png; hybrid-preview.html báo blocker và dẫn tới diagnostic/reflow tách riêng.

## Reading order và alignment

75 vùng nguồn: {order['source_region_order']['status_counts']}.
35 khối Trung: {order['source_order_counts']}; 53 khối Việt: {order['translation_order_counts']}.
7 liên kết paragraph: {order['link_order_counts']}; 0 alignment verified / 7 candidate / 0 ambiguous.
Định vị trực tiếp: 12 khối Trung → 17 khối Việt. {len(coverage['unlocalized_translation_block_ids'])} khối Việt chưa định vị từ paragraph nguồn, vẫn giữ.
{coverage['saved_lexical_math_linked_nodes']}/66 math có link lexical lưu từ TASK 3D; {coverage['direct_paragraph_linked_math_nodes']}/66 thuộc khối paragraph có liên kết trực tiếp. 0 math verified.
{len(order['inversions'])} đảo thứ tự candidate; không suy ra toàn bộ thứ tự đúng chỉ vì không tìm được đảo ở các khối đã ghép.
{len(order['duplicate_text_candidates'])} nhóm chữ lặp cần review; công thức lặp ở ID DOM khác nhau được giữ nguyên.
Ghi chú tiếp trang sau vẫn giữ; chưa thấy marker tương ứng trong bản chép Trung, chưa có bằng chứng trang liền kề.
File identifier 114 tách khỏi số in quan sát 100; không cấu hình footer như số đã duyệt.

## Ba hình

Tạo 3 crop mới từ nguồn hash {SOURCE_114_SHA}, raw pixel exact, không resize/rotate/thay nhãn.
ROI và quan sát nhãn/thành phần là candidate của assistant. Crop 3-52/3-53 loại bớt chữ lân cận,
crop 3-51 tăng khoảng trắng bao quanh. Caption và nhãn OCR có vị trí truy vết; không coi caption/border trắng là xác minh đầy đủ.
Trạng thái: {dict(Counter(g['verification_status'] for g in geometry['figures']))}; {geometry['crop_extent_candidates']} crop có extent candidate qua quan sát, 0 crop được độc lập chứng nhận đầy đủ.
Hình/caption/nhãn đi theo luồng phụ, không gán vào luồng chữ bằng y đơn thuần. Hình không chèn vào trang đủ điều kiện.

## Prototype và render thực tế

layout_hybrid.py chọn anchor bằng review độc lập có đầy đủ hash/bbox/block/math IDs và reading order; nhãn VERIFIED/confidence đơn lẻ không đủ.
Giữ renderer layout_rebuilder.py và solver layout_adaptive.py nguyên trạng; adapter chỉ dùng bản sao alignment khi chuẩn bị units.
0 anchor sử dụng thật, {len(hybrid['reflow_block_ids'])}/53 khối nằm trong reflow reference. Candidate diagnostic riêng có 17/53 khối tham chiếu nguồn, cảnh báo và viền rõ ràng.
Đủ 53/53 khối Việt, text exact={coverage['text_exact']}, 66/66 MathML/LaTeX bảo toàn, 0 node render trùng.
3G: 2 trang / 0 collision / 0 overflow. 3H candidate diagnostic: {diagnostic_solution['page_count']} trang / {len(post['collisions'])} collision / {len(post['overflow'])} overflow.
3H qualified Hybrid: 0 trang, BLOCKED. Full Reflow reference riêng: {metrics['page_count']} trang; không gọi đây là Hybrid mới.
Typography TASK 3B giữ nguyên 1200×1668, Times New Roman 24px, title 28px, Cambria Math 1em, line-height 1.25, gap 6px, lề 110/85/110/100.
Chưa đánh giá text–geometry/figure–caption trong trang vì không chèn hình. Không báo cải thiện bố cục thành phẩm.

## Phạm vi và bảo vệ

Thêm layout_reading_order.py, layout_geometry_review.py, layout_hybrid.py và tests/test_layout_hybrid.py.
Không sửa module cũ/worker/prompt/Playwright/parser/API/schema/retry/resume/progress.csv hoặc feature flag production.
Hash {len(protected)} file đầu vào/artifact/module/dirty-file bảo toàn: {unchanged}. Network attempts={attempts}.
Chỉ kiểm tra manifest dataset/capture TASK 2G có sẵn để tìm trang thêm: {coverage['status']}.
Không đủ bundle transcription+translation+math có hash cho 2–3 trang khác; giữ phạm vi trang 114, không tạo dữ liệu hoặc gọi ChatGPT bổ sung.

## TASK 3I

Review độc lập 7 liên kết và thứ tự có hash/bbox/block/math binding; adjudicate ký hiệu toán, note cuối và ranh giới trang.
Review ba ROI/nhãn/caption tại pixel gốc và đúng vị trí gắn vào nội dung; sau đó mới mở pilot Hybrid với anchor/hình đủ căn cứ.
Cần thêm 2–3 bundle nguồn–chép–dịch–math lưu offline có binding hợp lệ để kiểm tra khả năng tổng quát.
Không phát triển thêm heuristic QC để thay thế chứng cứ còn thiếu; chưa tích hợp batch production.

Kiểm thử/compile và lệnh chạy được bổ sung sau validation.
'''
    (output/'report.md').write_text(text,encoding='utf8')
    return result,coverage,geometry,order


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',default=str(Path(__file__).parent));p.add_argument('--output',required=True)
    a=p.parse_args();r,c,g,o=build(a.root,a.output)
    print(json.dumps({'status':r['status'],'reading_order':o['source_region_order']['status_counts'],
      'source_blocks':o['source_order_counts'],'vi_blocks':o['translation_order_counts'],'link_order':o['link_order_counts'],
      'geometry':dict(Counter(x['verification_status'] for x in g['figures'])),'coverage':{k:c[k] for k in ('translation_blocks_preserved','translation_math_nodes_preserved','saved_lexical_math_linked_nodes','direct_paragraph_linked_math_nodes','candidate_diagnostic_pages','verified_anchors_used','qualified_hybrid_pages')}},ensure_ascii=False))
