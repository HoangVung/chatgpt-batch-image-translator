"""TASK 3C offline source-anchor feasibility. No inferred semantic matches."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from html import escape
import json
from pathlib import Path
import shutil
from PIL import Image, ImageDraw
from layout_rebuilder import RebuildProfile, Tree, STATUS
from layout_calibration import (load_inputs, content_with_placeholders, run_layout,
                                totals, math_integrity)
from translation_evidence import file_hash, digest


def assess_regions(dataset):
    """Raster counterparts are not translation-node correspondences.

    The current dataset has no reviewed source bbox -> DOM block contract.
    Do not promote region classifications, positions or shape confidence.
    """
    regions=dataset['region_qc']['regions']['source']
    return [{'id':r['id'],'source_bbox':r['bbox'],
             'predicted_type':r['comparison_type'],
             'classification_verified':r.get('classification_verified',False),
             'raster_counterpart':r.get('counterpart_id'),
             'translation_blocks':[], 'math_indices':[], 'status':'NOT_ANCHORABLE',
             'reason':'No reviewed source-pixel-to-translation-block correspondence; raster counterpart is not a DOM binding.'}
            for r in regions]


def union_area(boxes):
    """Rectangle union, not sum: candidate envelopes can overlap."""
    if not boxes:return 0.0
    xs=sorted({x for b in boxes for x in (b[0],b[2])});area=0.0
    for x0,x1 in zip(xs,xs[1:]):
        spans=sorted((b[1],b[3]) for b in boxes if b[0]<x1 and b[2]>x0)
        end=None;length=0.0
        for y0,y1 in spans:
            if end is None or y0>end:length+=y1-y0
            elif y1>end:length+=y1-end
            end=max(end if end is not None else y1,y1)
        area+=(x1-x0)*length
    return area


def project_boxes(regions,source_size,target_size,clip):
    sx,sy=target_size[0]/source_size[0],target_size[1]/source_size[1]
    result=[]
    for r in regions:
        x0,y0,x1,y1=r['source_bbox'];b=[max(clip[0],x0*sx),max(clip[1],y0*sy),min(clip[2],x1*sx),min(clip[3],y1*sy)]
        if b[2]>b[0] and b[3]>b[1]:result.append(b)
    return result


def feasibility(measurement,width,height,geometry_area):
    areas=totals(measurement);page=measurement['pages'][0]
    text_h=areas['text']/width;math_h=areas['display_math']/width
    content_bottom=max((b['box'][3] for b in page['blocks']),default=page['printable_box'][1])
    flow_h=content_bottom-page['printable_box'][1]
    # Placeholder notices are debug boxes, not translated page content. Excluding
    # their allocation is an optimistic scenario; nothing is deleted in output.
    placeholder_h=areas['placeholder']/width
    optimistic_h=text_h+math_h
    available=width*height-geometry_area
    return {'printable_width':width,'printable_height':height,'printable_area':width*height,
            'text_bands_height':text_h,'display_math_bands_height':math_h,
            'flow_height_including_debug_notices':flow_h,
            'placeholder_band_height':placeholder_h,
            'internal_whitespace_height':areas['internal_whitespace']/width,
            'text_math_band_area':areas['text']+areas['display_math'],
            'text_math_band_equivalent_height':optimistic_h,
            'band_deficit_without_geometry_px2':max(0,(optimistic_h-height)*width),
            'band_deficit_without_geometry_height':max(0,optimistic_h-height),
            'candidate_geometry_union_area':geometry_area,
            'available_area_after_candidate_geometry':available,
            'band_deficit_with_candidate_geometry_px2':max(0,optimistic_h*width-available),
            'continuous_flow_deficit_height':max(0,flow_h-height),
            'band_area_ratio_after_candidate_geometry':optimistic_h*width/available,
            'one_page_at_current_full_reflow':'DOES_NOT_FIT' if flow_h>height else 'FITS_FLOW_ONLY_GEOMETRY_UNVERIFIED',
            'source_anchored_feasibility':'NOT_ANCHORABLE',
            'limits':['Bands allocate full content width, not ink area or a mathematical packing lower bound.',
                      'Candidate geometry boxes omit captions/labels and a third visible diagram; area is incomplete.',
                      'No conclusion about all possible layouts; narrowed source columns would need measured wrapping after reviewed mapping.']}


def inventory(content):
    root=Tree(content).root
    def plain(n):
        if isinstance(n,str):return n
        if 'formula' in n.attrs.get('class','').split():return ''
        return ''.join(plain(c) for c in n.children)
    blocks=[]
    for n in root.walk():
        if n.tag in ('p','h1','h2','h3','h4') or 'display' in n.attrs.get('class','').split():
            blocks.append({'local_block_index':len(blocks),'tag':n.tag,'non_math_text':plain(n),
                           'math_indices':[int(x.attrs['data-math']) for x in n.walk() if 'data-math' in x.attrs],
                           'source_regions':[],'status':'NOT_ANCHORABLE'})
    return blocks


def diagnostic_html(regions,profile,size,source_size):
    w,h=size;left,right=profile.margins();boxes=''
    for r in regions:
        x0,y0,x1,y1=r['source_bbox'];x0*=w/source_size[0];x1*=w/source_size[0];y0*=h/source_size[1];y1*=h/source_size[1]
        color='#a35' if r['predicted_type'] in ('UNKNOWN','GEOMETRY_DIAGRAM') else '#688'
        boxes+=f'<div class="region" style="left:{x0}px;top:{y0}px;width:{x1-x0}px;height:{y1-y0}px;border-color:{color}"><span>{escape(r["id"])}</span></div>'
    return f'''<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="status" content="{STATUS}"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><style>
body{{margin:0;background:#ddd;font-family:'{profile.font}',serif;font-size:{profile.body_size}px;line-height:{profile.line_height}}}
.sheet{{position:relative;width:{w}px;height:{h}px;background:white}}.region{{position:absolute;box-sizing:border-box;border:1px dashed;background:#eef3f322}}.region span{{font-size:12px;background:white;color:#555}}
.printable{{position:absolute;left:{left}px;right:{right}px;top:{profile.top}px;bottom:{profile.bottom}px;border:2px solid #999;box-sizing:border-box}}
.notice{{position:absolute;top:20px;left:35px;right:35px;color:#a22;background:white;z-index:2;font-size:20px}}
.explanation{{position:absolute;left:{left}px;right:{right}px;top:{h+20}px;background:#fffef3;border:2px solid #a22;padding:20px;z-index:2}}
</style><title>Source anchored diagnostic — NOT_ANCHORABLE</title><div class="sheet"><div class="printable"></div>{boxes}
<div class="notice">EXPERIMENTAL_UNVERIFIED · HIGH_RISK_HOLD · NOT_ANCHORABLE<br>BẢN ĐỒ CHẨN ĐOÁN — KHÔNG PHẢI TRANG DỊCH · 0/{len(regions)} vùng neo</div><div class="explanation"><b>BẢN ĐỒ CHẨN ĐOÁN — KHÔNG PHẢI TRANG DỊCH</b><p>0 vùng được neo. {len(regions)} vùng nguồn chưa có phép ghép đủ căn cứ với đoạn dịch/MathML.</p><p>Không chèn chữ hoặc hình theo phỏng đoán. Toàn bộ nội dung vẫn ở hai trang Full Reflow kèm theo. Các khung chỉ là vùng heuristic trên ảnh nguồn.</p><p>Profile TASK 3B giữ nguyên: {profile.body_size}px, line-height {profile.line_height}. Không dùng trang trống này để tuyên bố vừa một trang.</p></div></div></html>'''


def build(dataset,fixture,baseline,output):
    from playwright.sync_api import sync_playwright
    baseline=Path(baseline);output=Path(output)
    d,candidate=load_inputs(dataset,fixture);content,rows,structure=content_with_placeholders(d,candidate)
    l=json.loads((baseline/'layout-metrics.json').read_text(encoding='utf8'))
    profile=RebuildProfile(**l['profile']);size=tuple(l['target_size'])
    if profile.body_size!=24:raise ValueError('Expected unchanged selected TASK 3B profile, not a new font trial')
    regions=assess_regions(d);blocks=inventory(content)
    paths=[Path(dataset),Path(fixture),*[Path(d[k]['path']) for k in ('source_image','translated_image')],*[Path(c['path']) for c in d['geometry_crops']],*[p for p in baseline.iterdir() if p.is_file()]]
    hashes={str(p.resolve()):file_hash(p) for p in paths}
    output.mkdir(parents=True,exist_ok=False)
    with Image.open(d['source_image']['path']) as im:source_size=im.size
    left,right=profile.margins();clip=[left,profile.top,size[0]-right,size[1]-profile.bottom]
    geometry=[r for r in regions if r['predicted_type']=='GEOMETRY_DIAGRAM']
    geo_boxes=project_boxes(geometry,source_size,size,clip);geo_area=union_area(geo_boxes)
    attempts=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True);context=browser.new_context(offline=True,viewport={'width':size[0]+80,'height':size[1]+80},device_scale_factor=1)
        def deny(route):attempts.append(route.request.url);route.abort()
        context.route('**/*',deny);page=context.new_page()
        metrics,measure=run_layout(page,content,profile,size,calibrated_style=True)
        expected=''.join(n['text'] for n in structure['nodes'] if n['kind']=='text')
        if metrics['content_text']!=expected:raise ValueError('Text changed')
        integrity=math_integrity(structure,rows,measure)
        if integrity['technical_preserved']!=len(rows) or metrics['issues'] or any(pg['overlaps'] for pg in measure['pages']):raise ValueError('Integrity or layout issue')
        (output/'unanchored-full-reflow.html').write_text(page.content(),encoding='utf8')
        for i in range(metrics['page_count']):page.locator('.page').nth(i).screenshot(path=str(output/f'unanchored-full-reflow-{i+1}.png'))
        # Same width, fonts, spacing; a taller diagnostic canvas only measures
        # uninterrupted flow. This is not an alternative print trim/profile.
        _,continuous=run_layout(page,content,profile,(size[0],7000),calibrated_style=True)
        if len(continuous['pages'])!=1:raise ValueError('Measurement canvas too short')
        fit=feasibility(continuous,clip[2]-clip[0],clip[3]-clip[1],geo_area)
        html=diagnostic_html(regions,profile,size,source_size);page.set_content(html);page.evaluate('document.fonts.ready')
        (output/'source-anchored-preview.html').write_text(page.content(),encoding='utf8')
        page.locator('.sheet').screenshot(path=str(output/'source-anchored-preview.png'))
        version=browser.version;browser.close()
    for name in ('source.png','chatgpt.png','rebuilt-calibrated.png','rebuilt-calibrated-continuation-1.png','geometry-debug-0.png','geometry-debug-1.png','geometry-context-0.png','geometry-context-1.png'):
        shutil.copyfile(baseline/name,output/name)
    # Derivative debug overlay only; source bytes/pixels remain untouched.
    with Image.open(output/'source.png') as im:
        im=im.convert('RGB').resize(size);draw=ImageDraw.Draw(im)
        for r in regions:
            x0,y0,x1,y1=r['source_bbox'];b=(round(x0*size[0]/source_size[0]),round(y0*size[1]/source_size[1]),round(x1*size[0]/source_size[0]),round(y1*size[1]/source_size[1]))
            draw.rectangle(b,outline='#c74455',width=2);draw.text((b[0],b[1]),r['id'],fill='#aa0022')
        draw.rectangle((0,0,size[0],28),fill='white');draw.text((10,8),'SOURCE REFERENCE / HEURISTIC REGIONS / NOT A TRANSLATED PAGE',fill='#aa0022')
        im.save(output/'source-regions-debug.png')
    from collections import Counter
    repeated=[{'latex':tex,'occurrences':count,'removed':False,'status':'REPEATED_AT_DISTINCT_DOM_NODES_UNVERIFIED_SEMANTICALLY'} for tex,count in Counter(r['latex'] for r in rows).items() if count>1]
    boundary={'source_previous_page_content':'UNVERIFIED','source_next_page_content':'UNVERIFIED',
              'reading_order':'DOM_ORDER_PRESERVED_NOT_SOURCE_VERIFIED','rendered_duplicate_math_nodes':len(measure['maths'])-len(set(n['index'] for n in measure['maths'])),
              'repeated_latex_groups':repeated,'raw_dom_dual_layers':'Saved KaTeX HTML + MathML + annotations duplicate text representations; output keeps one native MathML per node.',
              'tail_note':{'text':'(Phần chứng minh tiếp tục ở trang sau.)','status':'SOURCE_SUPPORT_UNVERIFIED','preserved':True},
              'visual_observations':['Source begins with sufficiency argument and contains Example 8; candidate follows these broad sections, not a line-level proof of correspondence.',
                                     'Source ends with MC=ME+EC=; candidate final math has this same prefix. Adjacent pages not inspected; page membership remains unverified.',
                                     'Source visibly contains diagrams 3-51, 3-52, 3-53; only two saved candidate geometry boxes/crops exist.',
                                     'Source printed footer reads 100; artifact label 114 is not established as printed page number. Footer stays unconfigured.'],
              'limits':'Visual observations by current assistant are not independent content certification, OCR, or new translation.'}
    result={'status':STATUS,'anchor_status':'NOT_ANCHORABLE','dataset_readiness_unchanged':d['readiness'],'profile':asdict(profile),'target_size':list(size),
            'reliably_matched_regions':0,'unverified_regions':len(regions),'unknown_type_regions':sum(r['predicted_type']=='UNKNOWN' for r in regions),
            'regions':regions,'translation_blocks':blocks,'boundary_audit':boundary,'feasibility':fit,
            'full_reflow_pages_before':l['pagination_metrics']['page_count'],'full_reflow_pages_after':metrics['page_count'],'diagnostic_sheets':1,'completed_source_anchored_pages':0,
            'improvement_over_3b':{'preview_page_reduction':0,'font_change':False,'anchored_content_improvement':'NOT_DEMONSTRATED'},
            'content_text_exact':True,'math_integrity':integrity,'flow_measurement':continuous,'geometry_boxes_projected_debug_only':geo_boxes,
            'original_hashes':hashes,'original_hashes_unchanged':all(file_hash(path)==sha for path,sha in hashes.items()),'network_attempts':attempts,'browser':version,'production_integration':False}
    if not result['original_hashes_unchanged'] or attempts:raise ValueError('Inputs changed or network request attempted')
    (output/'source-anchor-analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    (output/'content-inventory.json').write_text(json.dumps(blocks,ensure_ascii=False,indent=2),encoding='utf8')
    (output/'math-integrity.json').write_text(json.dumps(integrity,ensure_ascii=False,indent=2),encoding='utf8')
    comparison='''<!doctype html><html lang="vi"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'self' file:"><style>body{font:18px Georgia;background:#eee;margin:20px}.row{display:flex;align-items:start;gap:12px}figure{width:25%;margin:0}img{width:100%}</style><h1>TASK 3C — EXPERIMENTAL_UNVERIFIED / HIGH_RISK_HOLD</h1><p>NOT_ANCHORABLE: 0/39 vùng ghép đủ căn cứ. Bản đồ chẩn đoán không phải trang dịch. Nội dung vẫn đủ trong 2 trang reflow; chưa cải thiện số trang.</p><div class="row">'''
    for title,name in [('SOURCE — debug','source-regions-debug.png'),('Full Reflow 3B — trang 1','rebuilt-calibrated.png'),('Source Anchored — chẩn đoán','source-anchored-preview.png'),('3C nội dung chưa neo — trang 1','unanchored-full-reflow-1.png')]:comparison+=f'<figure><b>{title}</b><a href="{name}"><img src="{name}"></a></figure>'
    comparison+='</div><p><a href="unanchored-full-reflow.html">Toàn bộ nội dung chưa neo</a> · <a href="unanchored-full-reflow-2.png">Trang 2</a> · <a href="rebuilt-calibrated-continuation-1.png">3B trang 2</a> · <a href="source-anchor-analysis.json">Số đo và bằng chứng</a></p><h2>Hình chưa đủ nhãn/caption — chỉ debug</h2><div class="row">'
    for i in range(2):comparison+=f'<figure><img src="geometry-context-{i}.png"></figure>'
    (output/'comparison.html').write_text(comparison+'</div></html>',encoding='utf8')
    report=f'''# TASK 3C — Source-Anchored Layout Feasibility

EXPERIMENTAL_UNVERIFIED / HIGH_RISK_HOLD. Branch feat/book-layout-consistency.

## Kết luận

NOT_ANCHORABLE: 0 vùng ghép đáng tin cậy, {len(regions)} vùng chưa xác minh (3 UNKNOWN về loại). Không tạo một trang dịch bám nguồn khi chưa có phép ghép. 2 trang reflow trước và sau; 1 PNG chẩn đoán riêng không được tính là một trang dịch đã hoàn thành. Không cải thiện số trang so với TASK 3B.

## Ranh giới và nguyên nhân

39 vùng nguồn gồm 32 BODY_TEXT heuristic, 1 HEADER, 1 FOOTER, 2 GEOMETRY_DIAGRAM, 3 UNKNOWN. Không có vùng MATH_FORMULA được xác minh. Bốn counterpart_id là phép ghép raster heuristic, không nối tới đoạn dịch/66 math node. Không có independent_reviews; reading_order_verified=false. Không dùng thứ tự/shape/hash như bằng chứng ngữ nghĩa.

Raw DOM có cả MathML, KaTeX HTML và annotation nên textContent thô lặp; renderer đã lấy đúng một native MathML cho mỗi node. {len(rows)}/{len(rows)} cây MathML và LaTeX bảo toàn; 0 node render trùng. Có {len(repeated)} nhóm LaTeX lặp ở các DOM node khác nhau, giữ nguyên, không kết luận là nội dung thừa.

Đầu nguồn và phản hồi cùng có phần điều kiện đủ/cần và Ví dụ 8; cuối nguồn và math cuối cùng đều có MC=ME+EC=. Chưa có đối chiếu từng dòng hoặc trang liền kề để xác minh nội dung thuộc trang trước/sau. Ghi chú Việt cuối phản hồi về chứng minh tiếp ở trang sau chưa có nguồn đối chiếu chắc chắn, vẫn giữ. Số in nhìn thấy là 100; nhãn artifact 114 không được coi là số trang in đã xác minh.

Nguồn trình bày nhiều phép biến đổi trên cùng dòng; phản hồi tách các câu nối ngắn và 19 display node, gồm công thức nhiều dòng. Full Reflow giữ các khối này như đã lưu. Đây là khác biệt bố trí quan sát được, chưa cho phép tự ghép/rút gọn các khối về dòng nguồn. Không chứng minh nội dung ngoài ranh giới trang.

## Diện tích và chiều cao đo ở profile cố định

Times New Roman {profile.body_size}px, tiêu đề {profile.title_size}px, Cambria Math 1em; line-height {profile.line_height} (30px), gap đoạn/toán {profile.paragraph_gap}px. Khổ {size[0]}×{size[1]}, lề trái/phải {left}/{right}, trên/dưới {profile.top}/{profile.bottom}px. Profile thử nghiệm chưa duyệt chuẩn in. Không thử font nhỏ hơn, không đổi biểu thức.

- Vùng in: {fit['printable_width']:.0f}×{fit['printable_height']:.0f} = {fit['printable_area']:.0f} px².
- Dải text/inline math: {fit['text_bands_height']:.2f}px tương đương chiều cao toàn chiều rộng.
- Dải display math: {fit['display_math_bands_height']:.2f}px.
- Tổng dải text+math: {fit['text_math_band_equivalent_height']:.2f}px, thiếu {fit['band_deficit_without_geometry_height']:.2f}px / {fit['band_deficit_without_geometry_px2']:.2f}px² so với một vùng in, trước hình/khoảng cách.
- Chiều cao flow liên tục giữ gap và debug placeholder: {fit['flow_height_including_debug_notices']:.2f}px, vượt {fit['continuous_flow_deficit_height']:.2f}px. Khoảng trắng nội bộ: {fit['internal_whitespace_height']:.2f}px; dải placeholder: {fit['placeholder_band_height']:.2f}px.
- Union hai bbox hình candidate: {geo_area:.2f}px²; phần vùng in còn lại {fit['available_area_after_candidate_geometry']:.2f}px². Thiếu dải chữ+toán trong kịch bản dành chỗ hai bbox: {fit['band_deficit_with_candidate_geometry_px2']:.2f}px².

Các phép đo diện tích là dải ngang phân bổ full-width, KHÔNG phải cận dưới tối ưu packing. Hai bbox hình thiếu nhãn/caption và không bao phủ hình 3-51, nên chưa đủ đo không gian cho toàn bộ hình. Không tự bổ sung bbox/crop. Khi neo theo cột hẹp, phải đo wrapping thực tế sau khi có mapping; không ngoại suy từ diện tích mực. Canvas 7000px chỉ để đo flow liên tục, không phải khổ in mới.

## Prototype và giới hạn

source-anchored-preview.png/html chỉ là bản đồ vùng trên trang trắng, gắn rõ NOT_ANCHORABLE và không phải trang dịch. source-regions-debug.png là ảnh nguồn tham chiếu có overlay mới, không sửa ảnh nguồn. Không đưa crop chưa đủ nhãn vào trang. Toàn bộ nội dung được dựng lại ở unanchored-full-reflow.html và PNG hai trang bằng nguyên profile 3B. Không bỏ nội dung, không đổi LaTeX/MathML/nhãn hình.

Không chứng minh mục tiêu một trang khả thi với dữ liệu hiện tại. Full Reflow ở profile 24px không vừa; Source Anchored chưa đánh giá được vì thiếu mapping. Không tuyên bố bất khả thi với mọi bố cục.

## File và bước tiếp theo

Thêm layout_source_anchored.py, tests/test_layout_source_anchored.py và thư mục output mới; không sửa module cũ/worker/prompt/Playwright/parser/schema/API/retry/progress.csv. Module dùng Chromium offline hiện có, không thay code Playwright hay automation production. Hash baseline TASK 3B và đầu vào/crop được giữ nguyên.

Cần bản đối chiếu source bbox -> đoạn dịch và chỉ số math, gắn hash ảnh/capture, basis/reviewer, ranh giới đầu/cuối và thứ tự đọc. Cần kiểm tra trang trước/sau, ghi chú cuối và số in; các crop đầy đủ cho ba hình, nhãn/caption/vị trí. Sau duyệt mapping, đo từng khối ở đúng độ rộng vùng nguồn với cùng profile 3B. Chỉ kết luận một trang khi đủ nội dung, hình và không clipping/overlap. Không tiếp tục tối ưu font vô hạn.
'''
    (output/'report.md').write_text(report,encoding='utf8')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','fixture','baseline','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();r=build(a.dataset,a.fixture,a.baseline,a.output)
    print(json.dumps({'anchor_status':r['anchor_status'],'reliable_regions':r['reliably_matched_regions'],'unverified_regions':r['unverified_regions'],'pages':r['full_reflow_pages_after'],'math':r['math_integrity']['technical_preserved'],'feasibility':r['feasibility'],'output':a.output},ensure_ascii=False))

if __name__=='__main__':main()
