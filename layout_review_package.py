"""Build a standalone TASK 3I human review package from saved TASK 3H evidence.

Only copies existing evidence. No OCR, translation, renderer, solver or network.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from html import escape
import json
from pathlib import Path
import shutil
import subprocess
from layout_review_validation import (VERSION,CHECKS,POLICY,digest,file_hash,read_json,
    manifest_digest,template,schema,validate,readiness)

H_DIR='output/task3h-page114-20261011-final'
G_DIR='output/task3g-page114-20261011-release-diagnostic'
F_DIR='output/task3f-page114-20261011-ocr'
D_DIR='output/task3d-page114-20261011-final'
CHECK_LABELS={
 'page_pairing':'Đã đối chiếu đúng ảnh nguồn và nội dung cặp bản chép–dịch',
 'bbox_content':'Bbox chứa đúng nội dung được liên kết; đã kiểm tra chữ ngoài mép',
 'translation_content':'Đã so sánh đầy đủ từng khối Trung–Việt trong scope',
 'all_scoped_math_compared':'Đã đối chiếu TỪNG math node trong scope với ảnh/LaTeX; không suy ra từ lexical match',
 'source_order':'Đã xác nhận thứ tự nguồn từ ảnh, không dùng DOM/OCR làm ground truth',
 'translation_order':'Đã xác nhận chuỗi Việt tương ứng, giữ riêng các stream cần thiết',
 'all_scoped_math_order':'Đã kiểm tra thứ tự và vị trí mọi math node trong scope',
 'all_regions_accounted':'Đã phân loại/đặt tất cả ID trong scope; không bỏ vùng unknown',
 'identifier_vs_printed_number':'Đã phân biệt file identifier 114 và số in quan sát 100',
 'first_last_lines':'Đã đối chiếu dòng đầu/cuối với ảnh nguồn',
 'adjacent_page_membership':'Có chứng cứ trang liền kề đủ để xác nhận ranh giới',
 'continuation_note_support':'Đã xác định bằng chứng hỗ trợ ghi chú Việt tiếp trang sau',
 'figure_extent':'Crop chứa toàn bộ hình, không cắt nét', 'all_point_labels':'Từng nhãn điểm đều đủ và đọc được',
 'caption':'Caption đúng hình và nằm trọn trong crop','no_adjacent_prose':'Không lẫn phần văn bản cạnh hình',
 'pixel_fidelity':'Đã so sánh crop với ảnh nguồn nguyên pixel',
 'source_figure_content':'Đã đối chiếu nội dung crop với đúng hình trên toàn trang (không chứng nhận định lý)',
}
CSS='''body{font:17px system-ui,Arial;margin:24px auto;padding:0 20px;max-width:1500px;background:#eef1f5;color:#17232d}h1{font-size:28px}h2{font-size:22px}a{color:#125a9e}nav{display:flex;flex-wrap:wrap;gap:16px;margin:20px 0}.warning{background:#fff1ce;border-left:5px solid #a65a00;padding:16px}.card{background:white;border:1px solid #b9c5cf;border-radius:8px;padding:20px;margin:24px 0}.cols{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.cols>div{min-width:0}img{max-width:100%;height:auto}.crop{max-height:850px;object-fit:contain;object-position:left top}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7f9;padding:12px}code{overflow-wrap:anywhere}textarea,input,select,button{font:inherit;box-sizing:border-box}textarea,input[type=text],input[type=datetime-local]{width:100%;padding:8px}textarea{min-height:90px}label{display:block;margin:12px 0}button{padding:10px 16px;cursor:pointer;margin:8px}.review{border-top:3px solid #4b6b85;margin-top:20px;padding-top:12px}.checks label{background:#f1f5f8;padding:8px}details{margin:14px 0}summary{cursor:pointer;font-weight:600}table{border-collapse:collapse;width:100%;table-layout:fixed}td,th{padding:8px;border:1px solid #ccc;overflow-wrap:anywhere;text-align:left}svg{width:100%;height:auto;background:white}.export{background:white;border:2px solid #7995ac;padding:14px}#json-output{min-height:200px}.badge{font-weight:bold;color:#884400}.math{font-family:Consolas,monospace}@media(max-width:850px){.cols{grid-template-columns:1fr}body{margin:12px auto;padding:0 10px}}'''
SCRIPT=r'''
const data=JSON.parse(document.getElementById('review-data').textContent);
function collect(){
 const result=JSON.parse(JSON.stringify(data.template));result.reviews=[];
 document.querySelectorAll('[data-review]').forEach(form=>{
  const id=form.dataset.review;
  const row=JSON.parse(JSON.stringify(data.template.reviews.find(x=>x.item_id===id)));
  const get=name=>form.querySelector('[name="'+name+'"]');
  row.decision=get('decision').value||null;
  ['reviewer','basis','reviewed_at','notes'].forEach(k=>row[k]=get(k).value.trim());
  row.independent_human=get('independent_human').checked;
  row.evidence_references=Array.from(form.querySelectorAll('[data-evidence]:checked')).map(x=>x.dataset.evidence);
  Object.keys(row.checks).forEach(k=>row.checks[k]=form.querySelector('[data-check="'+k+'"]').checked);
  if(row.category==='reading_order')row.order=JSON.parse(get('order').value);
  result.reviews.push(row);
 });return result;
}
function exportJSON(download){
 try{
  const value=JSON.stringify(collect(),null,2);const box=document.getElementById('json-output');box.value=value;
  document.getElementById('export-status').textContent='JSON đã tạo. Đây là quyết định khai báo, chưa qua validator.';
  if(download){const blob=new Blob([value],{type:'application/json;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=data.page+'-decisions.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  else{box.focus();box.select();document.getElementById('export-status').textContent+=' Nhấn Ctrl+C để sao chép.';}
 }catch(e){document.getElementById('export-status').textContent='Chưa xuất: kiểm tra JSON thứ tự. '+e.message;}
}
document.getElementById('download').addEventListener('click',()=>exportJSON(true));
document.getElementById('copy').addEventListener('click',()=>exportJSON(false));
document.querySelectorAll('[name=decision]').forEach(el=>el.addEventListener('change',()=>{
 const date=el.closest('[data-review]').querySelector('[name=reviewed_at]');if(el.value&&!date.value)date.value=new Date().toISOString();
}));
'''


def pre(value):return '<pre>'+escape(json.dumps(value,ensure_ascii=False,indent=2))+'</pre>'


def image(path,caption):return '<figure><a href="'+escape(path,quote=True)+'" target="_blank"><img class="crop" src="'+escape(path,quote=True)+'" alt="'+escape(caption,quote=True)+'"></a><figcaption>'+escape(caption)+' — nhấn mở ảnh để zoom</figcaption></figure>'


def evidence_form(item):
    opts=['COMPLETE','INCOMPLETE','UNCERTAIN'] if item['category']=='geometry' else ['ACCEPT','REJECT','UNCERTAIN']
    form='<section class="review" data-review="'+escape(item['item_id'],quote=True)+'"><h3>Quyết định của người hậu kiểm</h3>'
    form+='<label>Quyết định <select name="decision"><option value="">PENDING_REVIEW — chưa quyết định</option>'+''.join('<option>'+v+'</option>' for v in opts)+'</select></label>'
    for key,label in [('reviewer','Reviewer (tên người)'),('basis','Lý do / căn cứ kiểm tra'),('reviewed_at','Ngày giờ ISO 8601, có múi giờ'),('notes','Ghi chú, nhãn khó đọc hoặc sai khác')]:
        form+='<label>'+label+('<textarea name="'+key+'"></textarea>' if key in ('basis','notes') else '<input type="text" name="'+key+'" autocomplete="off">')+'</label>'
    form+='<fieldset><legend>Evidence reference đã trực tiếp xem (không tự chọn)</legend>'
    for ref,sha in item['available_evidence'].items():
        form+='<label><input type="checkbox" data-evidence="'+escape(ref,quote=True)+'"> <code>'+escape(ref)+'</code> · '+sha[:16]+'…'+(' · bắt buộc để mở gate' if ref in item['required_evidence'] else '')+'</label>'
    form+='</fieldset><div class="checks"><p>Các xác nhận dưới đây là kiểm tra thực tế, không phải confidence của máy.</p>'
    for check in CHECKS[item['category']]:form+='<label><input type="checkbox" data-check="'+check+'"> '+escape(CHECK_LABELS[check])+'</label>'
    form+='</div><label><input type="checkbox" name="independent_human"> Tôi là người hậu kiểm độc lập với việc tạo candidate; đã tự xem bằng chứng cho các ô đã chọn.</label>'
    if item['category']=='reading_order':
        form+='<p>Nhập JSON gồm sequences (mỗi scope chứa các stream, mỗi stream là mảng ID), unresolved (ID chưa đặt), edges (cặp trước/sau). Mọi ID phải xuất hiện đúng một lần trong sequences hoặc unresolved. unresolved không rỗng sẽ giữ ACCEPTED_UNVERIFIED. Không dùng thứ tự candidate làm quyết định tự động.</p>'+pre({'order_scope':item['order_scope']})
        form+='<label>Thứ tự đã kiểm tra <textarea name="order" rows="12">'+escape(json.dumps({'sequences':{},'unresolved':[],'edges':[]},indent=2))+'</textarea></label>'
    form+='<details><summary>Binding và hash nội dung đang xem</summary>'+pre({'bindings':item['bindings'],'evidence_sha256':item['evidence_sha256']})+'</details></section>'
    return form


def page(title,content,manifest,category=None,page_name='review-package'):
    nav='<nav>'+''.join('<a href="'+name+'.html">'+label+'</a>' for name,label in [('review-package','Hướng dẫn'),('alignment-review','7 alignment'),('reading-order-review','Thứ tự đọc'),('page-boundary-review','Ranh giới trang'),('geometry-review','3 hình học')])+'</nav>'
    t=template(manifest);t['reviews']=[r for r in t['reviews'] if category is None or r['category']==category]
    # JSON script content escapes '<' so saved text can never close the script.
    payload=json.dumps({'template':t,'page':page_name},ensure_ascii=False).replace('<','\\u003c')
    controls='<section class="export"><h2>Xuất quyết định JSON</h2><p>Trang tĩnh không ghi file tự động. Tải JSON của trang này, hoặc tạo JSON rồi Ctrl+C. Không có localStorage. Đóng trang trước khi xuất sẽ mất các nhập liệu chưa lưu. Không xuất tên reviewer giả để thử trên dữ liệu thật.</p><button id="download">Tải JSON</button><button id="copy">Tạo JSON để sao chép</button><p id="export-status" role="status"></p><textarea id="json-output" readonly aria-label="JSON review để sao chép"></textarea></section>' if category else ''
    js='<script type="application/json" id="review-data">'+payload+'</script><script>'+SCRIPT+'</script>' if category else ''
    return '<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\' file: data:; style-src \'unsafe-inline\'; script-src \'unsafe-inline\'; connect-src \'none\'; form-action \'none\'; base-uri \'none\'"><title>'+escape(title)+'</title><style>'+CSS+'</style></head><body><h1>'+escape(title)+'</h1><p class="warning">REVIEW_PACKAGE_READY — HUMAN_REVIEW_PENDING<br>EXPERIMENTAL_UNVERIFIED · HIGH_RISK_HOLD · NOT_ANCHORABLE<br>File identifier 114 ≠ số in quan sát 100 (chưa xác minh). Không có quyết định được điền sẵn.</p>'+nav+content+controls+js+'</body></html>'


def overlay(regions,figures=()):
    body='<svg viewBox="0 0 4056 5639" role="img" aria-label="Nguồn và bbox candidate"><image href="assets/source-image.jpg" width="4056" height="5639"/>'
    for row in regions:
        x,y,x2,y2=row['bbox'];label=row['source_reference']
        body+=f'<g><title>{escape(label)} — {escape(row["verification_status"])}</title><rect x="{x}" y="{y}" width="{x2-x}" height="{y2-y}" fill="none" stroke="#d41454" stroke-width="5"/><text x="{x}" y="{y-8}" fill="#83002e" stroke="white" stroke-width="1" font-size="40">{escape(label)}</text></g>'
    for row in figures:
        x,y,x2,y2=row['roi'];body+=f'<rect x="{x}" y="{y}" width="{x2-x}" height="{y2-y}" fill="none" stroke="#005fd3" stroke-width="9"/>'
    return body+'</svg>'


def block_list(rows,math_rows):
    maths={n['index']:n for n in math_rows}
    return ''.join('<article><h4>'+escape(b['id'])+'</h4><p>'+escape(b['non_math_text'])+'</p>'+''.join('<pre class="math">math:'+str(mid)+' · '+escape(maths.get(mid,{}).get('latex','[see math inventory]'))+'</pre>' for mid in b['math_indices'])+'</article>' for b in rows)


def build(root,output):
    root=Path(root).resolve();output=Path(output).resolve();h=root/H_DIR;g=root/G_DIR;f=root/F_DIR;d=root/D_DIR
    if output.exists():raise FileExistsError('TASK 3I output already exists; no overwrite')
    prior=read_json(h/'hybrid-layout.json');ar=read_json(h/'alignment-review.json');order=read_json(h/'reading-order.json');geometry=read_json(h/'geometry-inventory.json');coverage=read_json(h/'coverage-report.json')
    alignment=read_json(g/'paragraph-alignment.json');ocr=read_json(f/'source-bboxes.json');saved=read_json(d/'alignment-dataset.json')
    old_geometry=read_json(f/'geometry-review.json')
    if len(ar)!=7 or len(geometry['figures'])!=3 or len(saved['source_blocks'])!=35 or len(saved['translation_blocks'])!=53:raise ValueError('Unexpected TASK 3H inventory')
    protected=dict(prior['original_hashes'])
    for p in h.rglob('*'):
        if p.is_file():protected[str(p)]=file_hash(p)
    for name in ['layout_hybrid.py','layout_reading_order.py','layout_geometry_review.py','tests/test_layout_hybrid.py']:
        protected[str(root/name)]=file_hash(root/name)
    if not all(Path(p).is_file() and file_hash(p)==sha for p,sha in protected.items()):raise ValueError('Protected TASK 3H/earlier evidence changed')
    branch=subprocess.run(['git','branch','--show-current'],cwd=root,capture_output=True,text=True,check=True).stdout.strip()
    if branch!='feat/book-layout-consistency':raise ValueError('Unexpected branch; no automatic checkout')
    status=subprocess.run(['git','status','--porcelain'],cwd=root,capture_output=True,text=True,check=True).stdout
    fixture=read_json(root/'tests/fixtures/layout_task2g_page114.json');capture=Path(fixture['source_artifact']);capture=capture if capture.is_absolute() else root/capture
    source=Path(ocr['source_image_path'])
    inputs={}
    def add_input(name,path):
        p=Path(path).resolve();inputs[name]={'path':str(p),'sha256':file_hash(p)};return inputs[name]['sha256']
    bindings={
      'source_image_sha256':add_input('source-image',source),
      'ocr_dataset_sha256':add_input('ocr-dataset',f/'source-bboxes.json'),
      'source_transcription_sha256':add_input('cn-transcription',d/'alignment-dataset.json'),
      'translation_evidence_sha256':add_input('vi-translation',capture),
      'alignment_dataset_sha256':add_input('alignment-dataset',g/'paragraph-alignment.json'),
      'reading_order_sha256':add_input('reading-order-dataset',h/'reading-order.json')}
    add_input('alignment-review-dataset',h/'alignment-review.json');add_input('geometry-dataset',h/'geometry-inventory.json');add_input('hybrid-diagnostic',h/'hybrid-layout.json');add_input('coverage',h/'coverage-report.json')
    add_input('ocr-capture-dataset',capture.parent/'dataset/dataset.json');add_input('paragraph-regions',g/'paragraph-regions.json')
    add_input('previous-geometry-dataset',f/'geometry-review.json')
    if bindings['source_image_sha256']!=ocr['source_image_sha256']:raise ValueError('Source image does not match OCR binding')
    output.mkdir(parents=True,exist_ok=False);(output/'assets').mkdir()
    assets={}
    def copy_asset(ref,src,name):
        dest=output/'assets'/name;shutil.copyfile(src,dest);assets[ref]={'path':'assets/'+name,'sha256':file_hash(dest)}
        add_input('asset-origin:'+ref,src)
        return assets[ref]['path']
    copy_asset('source-image',source,'source-image.jpg')
    for name in ['chatgpt.png','candidate-diagnostic.png','reflow-reference-1.png','reflow-reference-2.png']:
        copy_asset(name,h/name,name)
    items=[]
    def add_item(ref,category,evidence,required,scope=None,crop=None):
        bound=deepcopy(bindings)
        if crop:bound['crop_sha256']=assets[crop]['sha256']
        refs={k:inputs[k]['sha256'] for k in ['source-image','ocr-dataset','cn-transcription','vi-translation','alignment-dataset','reading-order-dataset']}
        refs['item-content:'+ref]=digest(evidence)
        if crop:refs[crop]=assets[crop]['sha256']
        i={'item_id':ref,'category':category,'bindings':bound,'evidence':evidence,'evidence_sha256':digest(evidence),
           'available_evidence':refs,'required_evidence':required+['item-content:'+ref]}
        if scope is not None:i['order_scope']=scope
        items.append(i);return i
    alignment_cards=[];order_cards=[];geometry_cards=[]
    from layout_alignment import blocks_for
    from layout_calibration import load_inputs
    _,cn_math,_=blocks_for(saved['source_content_inventory']['candidate'],'src')
    _,candidate=load_inputs(capture.parent/'dataset/dataset.json',root/'tests/fixtures/layout_task2g_page114.json')
    vi_blocks,vi_math,_=blocks_for(candidate,'vi')
    if vi_blocks!=saved['translation_blocks'] or len(cn_math)!=67 or len(vi_math)!=66:raise ValueError('Saved math/text inventory mismatch')
    from PIL import Image
    with Image.open(source) as im: source_pixels=im.copy()
    def assert_crop(path,bbox):
        with Image.open(output/path) as crop:
            expected=source_pixels.crop(tuple(bbox))
            if crop.mode!=expected.mode or crop.size!=expected.size or crop.tobytes()!=expected.tobytes():raise ValueError('Crop pixels do not match source ROI')
    for n,row in enumerate(ar,1):
        p=row['paragraph_id'];crop_ref='alignment-crop:'+p
        crop_path=copy_asset(crop_ref,h/'alignment-crops'/('paragraph-'+str(n)+'.png'),'alignment-'+p.replace(':','-')+'.png')
        assert_crop(crop_path,row['source_bbox'])
        link=next(l for l in alignment['links'] if l['paragraph_id']==p)
        e=deepcopy(row);e['candidate_link']=link;e['crop_asset']=crop_path
        item=add_item('alignment:'+p,'alignment',e,['source-image','cn-transcription','vi-translation',crop_ref],crop=crop_ref)
        content='<h2>'+escape(item['item_id'])+'</h2><p class="badge">ALIGNED_CANDIDATE · chưa được hậu kiểm</p><div class="cols"><div>'+image(crop_path,'Crop nguồn nguyên pixel '+p)+pre({'bbox':row['source_bbox'],'confidence':link['confidence'],'methods':link['evidence'].get('localization_methods'),'OCR':row['ocr_text']})+'</div><div><h3>Bản chép Trung</h3>'+block_list(row['source_blocks'],row['source_math'])+'<h3>Bản dịch Việt</h3>'+block_list(row['translation_blocks'],row['translation_math'])+'</div></div><h3>Điểm chưa chắc chắn</h3>'+pre(row.get('review_points',row.get('uncertainties','Lexical/DOM candidates do not prove source equivalence or boundary')))+'<details><summary>Math links, bằng chứng và provenance nguyên bản</summary>'+pre(e)+'</details>'+evidence_form(item)
        alignment_cards.append('<section class="card">'+content+'</section>')
        order_row=next(r for r in order['paragraph_links'] if r['paragraph_reference']==p)
        scope={'source_regions':[p],'source_blocks':link['source_block_ids'],'translation_blocks':link['translation_block_ids'],
          'source_math':['source:math:'+str(x) for x in link['source_math_node_ids']],
          'translation_math':['translation:math:'+str(x) for x in link['translation_math_node_ids']]}
        oi=add_item('order:'+p,'reading_order',{'order_candidate':order_row,'alignment_evidence':e},['source-image','cn-transcription','vi-translation','reading-order-dataset',crop_ref],scope,crop_ref)
        order_cards.append('<section class="card"><h2>'+escape(oi['item_id'])+'</h2>'+image(crop_path,'Vùng '+p)+pre({'candidate':order_row,'math_source':row['source_math'],'math_translation':row['translation_math']})+evidence_form(oi)+'</section>')
    regions=order['source_region_order']['regions']
    scope={'source_regions':[r['source_reference'] for r in regions], 'source_blocks':[r['reference'] for r in order['source_blocks']],
      'translation_blocks':[r['reference'] for r in order['translation_blocks']],
      'source_math':['source:math:'+str(r['index']) for r in order['math_nodes'] if r['side']=='source'],
      'translation_math':['translation:math:'+str(r['index']) for r in order['math_nodes'] if r['side']=='translation']}
    global_item=add_item('order:page:114','reading_order',{'reading_order':order,'cn_blocks':saved['source_blocks'],'vi_blocks':saved['translation_blocks'],'source_math':cn_math,'translation_math':vi_math},['source-image','cn-transcription','vi-translation','reading-order-dataset'],scope)
    # Inventory stays visible even if no order can yet be assigned to it.
    order_intro='<section class="card"><h2>Toàn trang: 75 vùng / 35 CN / 53 VI / 67+66 math</h2><p>37 candidate, 37 ambiguous, 1 unresolved. DOM index chỉ là ID kiểm kê. Các math node luôn được giữ riêng; không gộp công thức giống chữ.</p>'+overlay(regions,geometry['figures'])+'<details open><summary>75 bbox, stream, candidate và trạng thái chưa rõ</summary>'+pre(order['source_region_order'])+'</details><details><summary>35 khối Trung và nội dung</summary>'+block_list(saved['source_blocks'],cn_math)+'</details><details><summary>53 khối Việt và nội dung</summary>'+block_list(saved['translation_blocks'],vi_math)+'</details><details><summary>133 math node, ownership và LaTeX lexical (không phải proof)</summary>'+pre({'source_math':cn_math,'translation_math':vi_math,'order_and_ownership':order['math_nodes']})+'</details>'+evidence_form(global_item)+'</section>'
    boundary_evidence={'page_identifier':'114','printed_page_number_observation':'100','printed_page_number_verified':False,
      'first_ocr_lines':ocr['boxes'][:4],'last_ocr_lines':ocr['boxes'][-5:],
      'source_first_blocks':saved['source_blocks'][:2],'source_last_blocks':saved['source_blocks'][-2:],
      'translation_last_blocks':saved['translation_blocks'][-3:],
      'translation_only_notes':order['translation_only_note_candidates'],
      'adjacent_page_suspects':order['adjacent_page_membership'],
      'adjacent_evidence_available':False,'adjacent_evidence_references':[],
      'limits':'OCR line order is an inventory. Observe actual top/bottom on the source. No adjacent-page evidence in TASK 3H; never delete the VI note or renumber.'}
    bi=add_item('boundary:114','page_boundary',boundary_evidence,['source-image','cn-transcription','vi-translation'])
    boundary_card='<section class="card"><h2>PAGE_BOUNDARY_UNVERIFIED</h2><p>Chưa có trang liền kề trong bundle. ACCEPT vẫn không đủ mở gate. Nếu bổ sung chứng cứ, tạo package mới; review hiện tại không được tự chuyển sang package mới.</p>'+image('assets/source-image.jpg','Toàn trang nguồn')+pre(boundary_evidence)+evidence_form(bi)+'</section>'
    for row in geometry['figures']:
        ref=row['figure_id'];crop_ref='geometry-crop:'+ref
        path=copy_asset(crop_ref,Path(row['path']),'geometry-'+ref.replace(':','-')+'.png')
        assert_crop(path,row['roi'])
        e=deepcopy(row);e['crop_asset']=path
        previous=next((x for x in old_geometry if any(c['text']==row['caption_candidate'] for c in x.get('ocr_captions_inside_crop',[]))),None)
        e['original_bbox']=previous.get('original_bbox') if previous else None
        e['previous_expanded_bbox']=previous.get('padded_bbox') if previous else None
        e['original_bbox_limit']='No detector original bbox for figure 3-51; raster ROI proposal only' if e['original_bbox'] is None else 'Saved TASK 3F original bbox, not independently verified'
        item=add_item('geometry:'+ref,'geometry',e,['source-image',crop_ref],crop=crop_ref)
        geometry_cards.append('<section class="card"><h2>'+escape(ref)+' — GEOMETRY_CANDIDATE</h2><p>COMPLETE chỉ xác nhận crop đầy đủ. Độ đúng nội dung toán học vẫn UNVERIFIED.</p><div class="cols"><div>'+image(path,'Crop giữ nguyên pixel')+'</div><div>'+overlay([], [row])+pre({'original_bbox':e['original_bbox'],'original_bbox_limit':e['original_bbox_limit'],'previous_expanded_bbox':e['previous_expanded_bbox'],'expanded_bbox':row['roi'],'caption':row['caption_candidate'],'visible_labels_candidates':row['visual_observations'],'risk':{'edge_ink':row['border_ink_counts'],'crossing_ocr':row['edge_crossing_ocr'],'adjacent_prose':row['adjacent_prose_candidates']},'crop_sha256':row['crop_sha256'],'pixel_sha256':row['pixel_sha256'],'decoded_pixels_exact':row['decoded_pixels_exact']})+'</div></div><details><summary>Toàn bộ inventory gốc và bằng chứng OCR</summary>'+pre(e)+'</details>'+evidence_form(item)+'</section>')
    manifest={'schema_version':VERSION,'inputs':inputs,'assets':assets,'items':items,'policy':POLICY,
      'alignment':alignment,'reading_order':order,'hybrid_bindings':prior['binding'],
      'anchor_indices':{r['paragraph_reference']:r['proposed_reading_order_index'] for r in order['paragraph_links']},'coverage':coverage}
    manifest['package_id']=manifest_digest(manifest)
    def save(name,value):(output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    save('review-manifest.json',manifest);save('review-template.json',template(manifest));save('review-schema.json',schema())
    validation=validate(manifest,(),output);gates=readiness(manifest,validation)
    save('review-validation.json',validation);save('hybrid-readiness.json',gates)
    commands='python -X utf8 layout_review_validation.py --package "'+str(output)+'" --reviews "alignment-review-decisions.json" "reading-order-review-decisions.json" "page-boundary-review-decisions.json" "geometry-review-decisions.json" --output "output/task3i-import-NEW"'
    intro='<section class="card"><h2>Cách review và lưu bằng chứng</h2><ol><li>Mở bốn trang review bằng trình duyệt, không cần server hoặc Internet.</li><li>Đối chiếu ảnh nguyên pixel, chữ Trung/Việt, từng math node; chọn quyết định, ghi tên/căn cứ/evidence/ngày giờ và các kiểm tra đã thực hiện. Không rõ thì UNCERTAIN.</li><li>Tải JSON riêng từng trang. Đây là bản ghi cần giữ lại; không dựa vào localStorage.</li><li>Chạy CLI với đường dẫn thực tế tới các JSON. Output phải là thư mục mới. Không sửa file template/manifest để nâng gate.</li></ol><p>7 alignment + 8 order + 3 geometry + 1 boundary = 19 mục chờ review. 36 khối Việt chưa định vị vẫn giữ trong Full Reflow.</p><p>Hash thay đổi → STALE_REVIEW. Chỉ VERIFIED_BY_POLICY mở gate đúng scope. Một ACCEPT không có đủ kiểm tra vẫn ACCEPTED_UNVERIFIED. Danh tính là khai báo của người review, không phải chữ ký số hoặc xác thực bên ngoài.</p><h3>CLI nhập nhiều JSON</h3>'+pre(commands)+'<p><a href="review-template.json">Template</a> · <a href="review-schema.json">JSON Schema</a> · <a href="review-validation.json">Validation hiện tại</a> · <a href="hybrid-readiness.json">Hybrid gates</a> · <a href="decision-report.md">Quyết định kỹ thuật</a></p><h3>Chính sách verification</h3>'+pre(POLICY)+'</section><section class="card"><h2>Đối chiếu bản lưu (không phải hybrid đã duyệt)</h2><div class="cols"><div>'+image('assets/chatgpt.png','Ảnh ChatGPT đã lưu')+'</div><div>'+image('assets/candidate-diagnostic.png','Candidate diagnostic TASK 3H — không qualified')+'</div></div><details><summary>Full Reflow tham chiếu: hai trang</summary>'+image('assets/reflow-reference-1.png','Full Reflow trang 1')+image('assets/reflow-reference-2.png','Full Reflow trang 2')+'</details></section>'
    for filename,title,content,category in [('review-package','Independent Evidence Review — trang 114',intro,None),('alignment-review','7 alignment candidates',''.join(alignment_cards),'alignment'),('reading-order-review','Reading Order Review',order_intro+''.join(order_cards),'reading_order'),('page-boundary-review','Page Boundary Review',boundary_card,'page_boundary'),('geometry-review','Geometry Crop Review',''.join(geometry_cards),'geometry')]:
        (output/(filename+'.html')).write_text(page(title,content,manifest,category,filename),encoding='utf8')
    decision='''# Quyết định sau TASK 3I

Đề xuất **C — Whole-Book Reflow** làm hướng kỹ thuật tiếp theo; chỉ là đề xuất, chưa chạy toàn sách. Không chọn A với 0 anchor verified. B là pilot có điều kiện nếu một phần alignment được hậu kiểm đủ scope và có boundary/order hợp lệ; phần còn lại giữ reflow, không mất nội dung.

Hiện còn 7 alignment, 8 reading-order item (7 vùng và 1 scope toàn trang), 3 crop và 1 boundary: tổng 19 quyết định chưa có người hậu kiểm. Scope toàn trang giữ 75 vùng, 35 khối Trung, 53 khối Việt và 133 math node. Có 36 khối Việt chưa định vị trực tiếp. Alignment/math lexical và thứ tự DOM không phải ground truth.

Chi phí thao tác quan sát từ UI: tối thiểu 19 lần chọn quyết định, 19 lần ghi căn cứ và chọn evidence reference, 19 danh tính/ngày giờ, 8 bản kê thứ tự JSON, 4 lần tải JSON và 1 lệnh import. Để promotion còn có 7×4 + 8×4 + 3×6 + 1×4 = 82 xác nhận kiểm tra theo scope, cộng attestation độc lập. Các scope có phần trùng lặp; 82 ô không phải 82 phép chứng minh độc lập. Nội dung cần xem gồm tối đa 75 vùng, 35 CN, 53 VI, 67 CN math và 66 VI math, 3 hình/nhãn/caption và ranh giới. Không có đo thời gian thao tác người thật, nên không ước lượng phút/trang hay giờ/toàn sách.

Ranh giới cần thêm bằng chứng trang liền kề và hỗ trợ ghi chú Việt tiếp trang sau; bundle hiện không có. Kể cả tất cả ô được chọn, gate boundary vẫn không mở. Bổ sung chứng cứ cần package mới và review mới theo hash; không sửa manifest để chuyển review cũ. File 114 / số in 100 giữ nguyên.

C giảm nhu cầu neo theo bbox nhưng vẫn phải kiểm tra nội dung dịch, toán, hình và page boundary; không biến bản dịch thành đúng chỉ nhờ reflow. Reflow tham chiếu TASK 3H có 2 trang, 0 collision/overflow, 53/53 khối và 66/66 math được bảo toàn về kỹ thuật; đây không phải bằng chứng toàn sách. B chỉ có ích sau review thật; any new hybrid must be measured with the unchanged renderer before acceptance.

Giữ EXPERIMENTAL_UNVERIFIED, HIGH_RISK_HOLD, NOT_ANCHORABLE. Không tạo hybrid-preview.png, không READY_FOR_PILOT, không tích hợp production.
'''
    (output/'decision-report.md').write_text(decision,encoding='utf8')
    after={p:file_hash(p) for p in protected};unchanged=after==protected
    save('preservation-before.json',protected);save('preservation-validation.json',{'protected_files':len(protected),'unchanged':unchanged,'changed':[p for p in protected if after[p]!=protected[p]]})
    (output/'git-status-before.txt').write_text(status,encoding='utf8')
    report=f'''# TASK 3I

REVIEW_PACKAGE_READY — HUMAN_REVIEW_PENDING

Branch {branch}. Added layout_review_package.py, layout_review_validation.py, tests/test_layout_review.py. No old source module edited. Offline package: 7 alignment, 8 reading order, 3 geometry, 1 boundary, all PENDING_REVIEW. No human decisions supplied or fabricated.

Boundary PAGE_BOUNDARY_UNVERIFIED. Validator {validation['status']}. Hybrid {gates['status']}; 0 verified anchors, 0 inserted figures. EXPERIMENTAL_UNVERIFIED / HIGH_RISK_HOLD / NOT_ANCHORABLE retained.

Translation 53/53 blocks, math 66/66 technically preserved in saved hash-bound TASK 3H evidence. No new render or semantic proof. 36 unlocalized VI blocks retained. Geometry completeness distinct from mathematical correctness. No adjacent-page evidence available; boundary cannot be promoted using this package.

Protected {len(protected)} existing files: unchanged={unchanged}. No network/provider requests, OCR, worker changes, renderer/solver changes, commit/push/merge, or old artifact overwrite.

Build: python -X utf8 layout_review_package.py --output "{output}"
Import command (replace review paths):
{commands}

See validation-results.txt and offline-ui-validation.json for actual checks after build. Next: human review/export/import; recommendation C with conditional B described in decision-report.md. No whole-book execution authorized by this report.
'''
    (output/'report.md').write_text(report,encoding='utf8')
    if not unchanged:raise ValueError('Protected files changed during build')
    return {'output':str(output),'items':len(items),'validation':validation['status'],'hybrid':gates['status'],'protected_files':len(protected)}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,default=Path(__file__).parent);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();print(json.dumps(build(args.root,args.output),ensure_ascii=False))

if __name__=='__main__':main()
