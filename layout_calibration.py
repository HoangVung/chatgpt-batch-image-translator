"""TASK 3B offline calibration, additive to the unchanged TASK 3A renderer."""
from __future__ import annotations
import argparse
from dataclasses import asdict, replace
from html import escape
import json
from pathlib import Path
import shutil
from statistics import median
from PIL import Image
from layout_rebuilder import (RebuildProfile, Tree, build_content, native_math,
                              math_root, preview_html, PAGINATE, STATUS)
from translation_evidence import audit_fallback, file_hash, digest

# Keep headings + following block; keep short connectors with display formula.
# Math tables remain atomic. Paragraphs are kept whole; very tall blocks retain
# the TASK 3A full overflow sheet rather than discarding their final lines.
COHESION = r'''() => {
 const flow=document.querySelector('#flow');
 for(const n of [...flow.children]){
  const next=n.nextElementSibling;
  if(!next)continue;
  const heading=/^H[1-4]$/.test(n.tagName);
  const connector=n.tagName==='P'&&!n.querySelector('.formula')&&n.textContent.trim().length<=45&&next.classList.contains('display');
  if(heading||connector){const group=document.createElement('div');group.className='keep-group';n.before(group);group.append(n,next);}
 }
}'''

MEASURE = r'''() => {
 const box=e=>{let r=e.getBoundingClientRect();return [r.left,r.top,r.right,r.bottom];};
 let pages=[];
 for(const [pi,page] of [...document.querySelectorAll('.page')].entries()){
  const main=page.querySelector('main'),m=box(main),width=m[2]-m[0],height=m[3]-m[1];
  const bands=[];let textRects=[],mathRects=[],blocks=[];
  const walker=document.createTreeWalker(main,NodeFilter.SHOW_TEXT);
  while(walker.nextNode()){
   const n=walker.currentNode;if(!n.textContent||n.parentElement.closest('.formula,.geometry-placeholder'))continue;
   const range=document.createRange();range.selectNodeContents(n);
   for(const r of range.getClientRects()){if(r.width>0&&r.height>0){textRects.push([r.left,r.top,r.right,r.bottom]);bands.push([r.top,r.bottom,'text']);}}
  }
  for(const e of main.querySelectorAll('.display')){let r=box(e);bands.push([r[1],r[3],'display_math']);}
  for(const e of main.querySelectorAll('.geometry-placeholder')){let r=box(e);bands.push([r[1],r[3],'placeholder']);}
  for(const e of main.querySelectorAll('math')){let r=box(e);mathRects.push(r);if(e.closest('.inline'))bands.push([r[1],r[3],'text']);}
  for(const e of main.children){let r=box(e),c=getComputedStyle(e);blocks.push({tag:e.tagName,box:r,margin_top:parseFloat(c.marginTop),margin_bottom:parseFloat(c.marginBottom),text_length:e.textContent.length,math_nodes:e.querySelectorAll('.formula').length});}
  const cuts=[...new Set([m[1],m[3],...bands.flatMap(b=>[Math.max(m[1],Math.min(m[3],b[0])),Math.max(m[1],Math.min(m[3],b[1]))])])].sort((a,b)=>a-b);
  const extent=Math.min(m[3],Math.max(m[1],...blocks.map(b=>b.box[3])));
  const used={text:0,display_math:0,placeholder:0,internal_whitespace:0,trailing_whitespace:0};
  for(let i=1;i<cuts.length;i++){const mid=(cuts[i]+cuts[i-1])/2,active=bands.filter(b=>b[0]<=mid&&b[1]>=mid);let key=active.some(b=>b[2]==='placeholder')?'placeholder':active.some(b=>b[2]==='display_math')?'display_math':active.length?'text':mid<extent?'internal_whitespace':'trailing_whitespace';used[key]+=(cuts[i]-cuts[i-1])*width;}
  const headings=[...main.querySelectorAll('h1,h2,h3,h4')].map(h=>({text:h.textContent,box:box(h),grouped:h.parentElement.classList.contains('keep-group'),orphan:!h.parentElement.classList.contains('keep-group')&&!h.nextElementSibling}));
  const overlaps=[];const math=[...main.querySelectorAll('math')];
  for(let i=0;i<math.length;i++)for(let j=i+1;j<math.length;j++){let a=box(math[i]),b=box(math[j]);if(Math.min(a[2],b[2])-Math.max(a[0],b[0])>1&&Math.min(a[3],b[3])-Math.max(a[1],b[1])>1)overlaps.push({type:'MATH_OVERLAP',a:Number(math[i].closest('.formula').dataset.math),b:Number(math[j].closest('.formula').dataset.math)});}
  // Non-math character ranges catch collisions with adjacent text, including
  // inline formulas, without treating an enclosing paragraph as overlap.
  for(const e of math){let a=box(e);for(const b of textRects)if(Math.min(a[2],b[2])-Math.max(a[0],b[0])>1&&Math.min(a[3],b[3])-Math.max(a[1],b[1])>1){overlaps.push({type:'MATH_TEXT_OVERLAP',index:Number(e.closest('.formula').dataset.math)});break;}}
  pages.push({index:pi,printable_box:m,printable_area:width*height,area_bands:used,text_rects:textRects,math_rects:mathRects,blocks,headings,overlaps,
    fonts:{body:getComputedStyle(main).fontFamily,size:getComputedStyle(main).fontSize,line_height:getComputedStyle(main).lineHeight,math:main.querySelector('math')?getComputedStyle(main.querySelector('math')).fontFamily:null}});
 }
 const maths=[...document.querySelectorAll('.formula')].map(e=>({index:Number(e.dataset.math),mathml:e.querySelector('math')?.outerHTML||null,page:[...document.querySelectorAll('.page')].indexOf(e.closest('.page'))}));
 return {pages,maths};
}'''

def raster_metrics(path):
    """Pixel-only proxies at common resolution; no OCR/font identification."""
    with Image.open(path) as original:
        size=original.size
        im=original.convert('L').resize((1200,1668))
    mask=im.point(lambda x:255 if x<180 else 0)
    bbox=mask.getbbox();ink=mask.histogram()[255]/(1200*1668)
    # Central-left strip avoids most diagrams; still an uncalibrated glyph proxy.
    strip=mask.crop((180,210,650,1500));active=[]
    for y in range(strip.height):active.append(strip.crop((0,y,strip.width,y+1)).histogram()[255]>=3)
    runs=[];start=None
    for y,value in enumerate(active+[False]):
        if value and start is None:start=y
        if not value and start is not None:runs.append([start,y]);start=None
    glyph=[b-a for a,b in runs if 3<=b-a<=35]
    return {'original_size':list(size),'aspect_ratio':size[0]/size[1],
            'common_size':[1200,1668],'ink_fraction_threshold180':ink,'ink_bbox':bbox,
            'outer_ink_margins':[bbox[0],bbox[1],1200-bbox[2],1668-bbox[3]] if bbox else None,
            'glyph_band_height_median_proxy':median(glyph) if glyph else None,
            'text_strip_runs':runs,'header_ink_fraction':mask.crop((0,0,1200,200)).histogram()[255]/240000,
            'footer_ink_fraction':mask.crop((0,1500,1200,1668)).histogram()[255]/201600,
            'limitations':'Decoration/diagram/text all count as ink. Strip run height is not font size; no OCR or semantic region match.'}

def canonical_math(markup):
    if not markup:return None
    tree=Tree(markup).root
    def canonical(n):
        if isinstance(n,str):return n
        return [n.tag,sorted(n.attrs.items()),[canonical(c) for c in n.children]]
    return canonical(tree)

def math_integrity(structure,rows,measurement):
    source=[n for n in structure['nodes'] if n['kind']=='math'];rendered=measurement['maths'];by_id={}
    for n in rendered:by_id.setdefault(n['index'],[]).append(n)
    results=[]
    for i,s in enumerate(source):
        roots=[n for n in Tree(s['raw_html']).root.walk() if n.tag=='math']
        render_rows=by_id.get(i,[]);expected=native_math(roots[0]) if len(roots)==1 else None
        original_latex=s['latex_candidate'];latex=rows[i]['latex']
        equal=len(render_rows)==1 and canonical_math(expected)==canonical_math(render_rows[0]['mathml'])
        tags={k:sum(n.tag==k for n in roots[0].walk()) if len(roots)==1 else 0 for k in ('mfrac','msup','msub','msubsup','msqrt','mroot','mtable','mtr')}
        # Limited syntax checks only; unsupported TeX equivalence remains manual.
        checks={}
        if original_latex is not None and roots:
            checks['frac_count']=original_latex.count('\\frac')==tags['mfrac']
            checks['sqrt_count']=original_latex.count('\\sqrt')==tags['msqrt']+tags['mroot']
            checks['sup_count']=original_latex.count('^')==tags['msup']+tags['msubsup']
            checks['sub_count']=original_latex.count('_')==tags['msub']+tags['msubsup']
            visual=''.join(n.text() for n in roots[0].walk() if n.tag in ('mi','mn','mo'))
            for command,symbol in [('\\angle','∠'),('\\perp','⊥'),('\\cdot','⋅')]:
                if command in original_latex:checks[command+'_count']=original_latex.count(command)==visual.count(symbol)
        results.append({'index':i,'latex':latex,'latex_exact':original_latex==latex,
                        'render_occurrences':len(render_rows),'mathml_tree_preserved':equal,'structure_counts':tags,
                        'limited_tex_checks':checks,'limited_checks_pass':all(checks.values()),
                        'technical_status':'PRESERVED' if equal and original_latex==latex else 'REVIEW_REQUIRED',
                        'latex_mathml_equivalence':'NOT_PROVEN','semantic_verified':False})
    return {'status':STATUS,'math_nodes':len(source),'technical_preserved':sum(n['technical_status']=='PRESERVED' for n in results),
            'limited_checks_passed':sum(n['limited_checks_pass'] for n in results),'nodes':results,
            'uncertain_comparison_nodes':[n['index'] for n in results],
            'limits':'All 66 require independent LaTeX–MathML/source adjudication. Structural equality and limited symbol/count checks do not certify TeX equivalence or math correctness.'}

def load_inputs(dataset,fixture):
    d=json.loads(Path(dataset).read_text(encoding='utf8'));f=json.loads(Path(fixture).read_text(encoding='utf8'))
    evidence=Path(f['source_artifact'])
    if not evidence.is_absolute():evidence=Path(__file__).parent/evidence
    if file_hash(evidence)!=f['source_artifact_sha256']:raise ValueError('Capture hash mismatch')
    if digest({k:v for k,v in d.items() if k!='dataset_sha256'})!=d['dataset_sha256']:raise ValueError('Dataset hash mismatch')
    if json.loads(evidence.read_text(encoding='utf8'))['capture_audit']!=d['translation']['capture_audit']:raise ValueError('Capture binding mismatch')
    for k in ('source_image','translated_image'):
        if file_hash(d[k]['path'])!=d[k]['sha256']:raise ValueError('Input image hash mismatch')
    audit=audit_fallback(d['translation']['capture_audit'],evidence=d['translation'],corroboration=f.get('corroboration'))
    if not audit.get('candidate'):raise ValueError('Missing bounded translation candidate')
    return d,audit['candidate']

def content_with_placeholders(d,candidate):
    content,rows,structure=build_content(candidate)
    for c in d['geometry_crops']:
        content+='<div class="geometry-placeholder">'+escape(c['region_id'])+' — HÌNH CHƯA HOÀN CHỈNH / CHƯA XÁC MINH; xem ảnh gốc trong debug, không ghép vào nội dung.</div>'
    return content,rows,structure

def run_layout(page,content,profile,size,cohesion=True,calibrated_style=False):
    page.set_content(preview_html(content,profile,size))
    # Placeholder typography follows this same profile rather than the 3A
    # hardcoded 19px debug box; no source content is removed.
    if calibrated_style:page.add_style_tag(content=f'.geometry-placeholder{{font-size:{profile.body_size}px;padding:6px;margin:6px 0}}h1,h2,h3,h4{{margin-bottom:10px}}.keep-group{{display:flow-root;break-inside:avoid}}')
    if cohesion:page.evaluate(COHESION)
    metrics=page.evaluate(PAGINATE,asdict(profile));measurement=page.evaluate(MEASURE)
    return metrics,measurement

def totals(measurement):
    sums={k:sum(p['area_bands'][k] for p in measurement['pages']) for k in ('text','display_math','placeholder','internal_whitespace','trailing_whitespace')}
    sums['printable_area']=sum(p['printable_area'] for p in measurement['pages'])
    return sums

def choose_trial(trials):
    eligible=[t for t in trials if t['safe'] and t['profile']['body_size']>=20 and t['profile']['line_height']>=1.15]
    if not eligible:raise ValueError('No technically safe readable experimental candidate')
    # Prioritize fewer preview sheets, then the largest fixed body type.
    return min(eligible,key=lambda t:(t['pages'],-t['profile']['body_size'],-t['profile']['line_height']))

def calibrate(dataset,fixture,baseline,output):
    from playwright.sync_api import sync_playwright
    output=Path(output);baseline=Path(baseline)
    d,candidate=load_inputs(dataset,fixture);content,rows,structure=content_with_placeholders(d,candidate)
    baseline_files=list(baseline.glob('*'));inputs=[Path(dataset),Path(fixture),*[Path(d[k]['path']) for k in ('source_image','translated_image')],*[Path(c['path']) for c in d['geometry_crops']],*baseline_files]
    hashes={str(p.resolve()):file_hash(p) for p in inputs if p.is_file()}
    output.mkdir(parents=True,exist_ok=False)
    with Image.open(d['source_image']['path']) as im:source_size=im.size
    original=RebuildProfile(**json.loads((baseline/'layout-report.json').read_text(encoding='utf8'))['profile'])
    size=original.dimensions(source_size)
    candidates=[replace(original,body_size=s,title_size=28 if s>=22 else 26,line_height=l,paragraph_gap=g,math_gap=g,indent=s) for s,l,g in [(24,1.25,6),(22,1.20,5),(21,1.20,5),(20,1.15,4)]]
    trials=[];attempts=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True);context=browser.new_context(offline=True,viewport={'width':size[0]+80,'height':size[1]+80},device_scale_factor=1)
        def deny(route):attempts.append(route.request.url);route.abort()
        context.route('**/*',deny);page=context.new_page()
        page.set_content((baseline/'rebuilt-preview.html').read_text(encoding='utf8'));base_measure=page.evaluate(MEASURE)
        baseline_content=page.locator('main').evaluate_all('(nodes)=>nodes.map(n=>n.innerHTML).join("")')
        # Controlled ablations isolate font, paragraph, math and pagination costs.
        ablations=[]
        for name,profile,cohesion in [('3a-reproduced',original,False),('line-height-only',replace(original,line_height=1.20),False),('paragraph-gap-only',replace(original,paragraph_gap=5),False),('math-gap-only',replace(original,math_gap=5),False),('font-size-only',replace(original,body_size=22),False),('cohesion-only',original,True)]:
            metrics,measure=run_layout(page,baseline_content,profile,size,cohesion)
            ablations.append({'name':name,'pages':metrics['page_count'],'areas':totals(measure),'profile':asdict(profile)})
        for index,profile in enumerate(candidates):
            metrics,measure=run_layout(page,content,profile,size,calibrated_style=True)
            expected=''.join(n['text'] for n in structure['nodes'] if n['kind']=='text')
            if expected!=metrics['content_text']:raise ValueError('Translation text changed')
            overlap=[x for pg in measure['pages'] for x in pg['overlaps']]
            safe=not metrics['issues'] and not metrics['oversized'] and not overlap and len(measure['maths'])==len(rows)
            trials.append({'id':index,'profile':asdict(profile),'pages':metrics['page_count'],'safe':safe,'issues':metrics['issues']+overlap,'areas':totals(measure)})
        chosen=choose_trial(trials);profile=RebuildProfile(**chosen['profile'])
        metrics,measure=run_layout(page,content,profile,size,calibrated_style=True)
        integrity=math_integrity(structure,rows,measure)
        if integrity['technical_preserved']!=len(rows):raise ValueError('Math structure changed or duplicated')
        (output/'rebuilt-calibrated.html').write_text(page.content(),encoding='utf8')
        for i in range(metrics['page_count']):
            target=output/('rebuilt-calibrated.png' if i==0 else f'rebuilt-calibrated-continuation-{i}.png')
            element=page.locator('.page').nth(i);box=element.bounding_box()
            page.screenshot(path=str(target),full_page=True,clip={'x':box['x'],'y':box['y'],'width':size[0],'height':size[1]})
            if i in metrics['oversized']:element.screenshot(path=str(output/f'overflow-full-{i}.png'))
        version=browser.version;browser.close()
    geometry=[]
    with Image.open(d['source_image']['path']) as source:
        for i,c in enumerate(d['geometry_crops']):
            with Image.open(c['path']) as crop:
                with source.crop(c['bbox']) as original_crop:exact=crop.mode==original_crop.mode and crop.size==original_crop.size and crop.tobytes()==original_crop.tobytes()
                border=crop.convert('L').point(lambda x:255 if x<180 else 0)
                touch={edge:border.crop(box).getbbox() is not None for edge,box in {'left':(0,0,3,crop.height),'right':(crop.width-3,0,crop.width,crop.height),'top':(0,0,crop.width,3),'bottom':(0,crop.height-3,crop.width,crop.height)}.items()}
            if not exact or file_hash(c['path'])!=c['sha256']:raise ValueError('Crop pixel/hash mismatch')
            shutil.copyfile(c['path'],output/f'geometry-debug-{i}.png')
            # Wider context is debug only, never a newly qualified geometry crop.
            x0,y0,x1,y1=c['bbox'];source.crop((max(0,x0-160),max(0,y0-160),min(source.width,x1+160),min(source.height,y1+240))).save(output/f'geometry-context-{i}.png')
            geometry.append({'region_id':c['region_id'],'pixel_exact':exact,'border_ink':touch,'classification':'CANDIDATE_UNVERIFIED','caption_verified':False,'labels_complete_verified':False,'inserted':False,
                             'visual_observation':('Caption 3-52 and Q below bottom are outside saved crop.' if i==0 else 'Caption 3-53 and boundary labels P/Q/B/D are absent or cut in saved crop; wider source context displays them.')})
    for name,key in [('source','source_image'),('chatgpt','translated_image')]:
        with Image.open(d[key]['path']) as im:im.save(output/(name+'.png'))
    shutil.copyfile(baseline/'rebuilt-preview.png',output/'task3a-before.png')
    for i in range(1,len(base_measure['pages'])):shutil.copyfile(baseline/f'rebuilt-preview-continuation-{i}.png',output/f'task3a-before-continuation-{i}.png')
    raster={name:raster_metrics(output/(name+'.png')) for name in ('source','chatgpt')}
    raster['task3a']=raster_metrics(output/'task3a-before.png');raster['task3b']=raster_metrics(output/'rebuilt-calibrated.png')
    unknown=[r['id'] for r in d['region_qc']['regions']['source'] if r.get('comparison_type')=='UNKNOWN']
    analysis={'status':STATUS,'before_pages':len(base_measure['pages']),'after_pages':metrics['page_count'],'trial_profiles':trials,'ablations':ablations,'selected_trial':chosen,
              'selection_rule':'Fewer safe pages, then largest body size; experimental minimum 20px and line height 1.15, not approved print sizes.',
              'one_page_possible_in_trials':any(t['safe'] and t['pages']==1 for t in trials),
              'characters_non_math':len(''.join(n['text'] for n in structure['nodes'] if n['kind']=='text')),
              'math_inventory':{'total':len(rows),'inline':sum(not n['display'] for n in rows),'display':sum(n['display'] for n in rows),'duplicates':len(measure['maths'])-len(set(n['index'] for n in measure['maths']))},
              'paragraphs':sum(n.tag=='p' for n in Tree(candidate['html']).root.walk()),
              'before_areas':totals(base_measure),'after_areas':totals(measure),'geometry':geometry,'unknown_regions':unknown,
              'one_sheet_printable_area':base_measure['pages'][0]['printable_area'],
              'smallest_trial_text_math_area':trials[-1]['areas']['text']+trials[-1]['areas']['display_math'],
              'minimum_trial_text_math_to_one_sheet_ratio':(trials[-1]['areas']['text']+trials[-1]['areas']['display_math'])/base_measure['pages'][0]['printable_area'],
              'source_boundary_status':'UNVERIFIED: raster cannot establish exact translation page boundary without independent review/OCR; no content deleted.',
              'area_method':'Disjoint full-width vertical bands from DOM range line boxes; inline math belongs to text bands. Display math and debug placeholders separate. Residual split into internal and trailing whitespace. These are layout allocation proxies, not glyph ink areas.'}
    before_totals=totals(base_measure);after_totals=totals(measure)
    changes={'preview_pages_reduction_percent':100*(1-metrics['page_count']/len(base_measure['pages'])),
             'text_math_area_reduction_percent':100*(1-(after_totals['text']+after_totals['display_math'])/(before_totals['text']+before_totals['display_math'])),
             'internal_whitespace_reduction_percent':100*(1-after_totals['internal_whitespace']/before_totals['internal_whitespace']),
             'trailing_whitespace_reduction_percent':100*(1-after_totals['trailing_whitespace']/before_totals['trailing_whitespace']),
             'first_page_ink_density':{k:v['ink_fraction_threshold180'] for k,v in raster.items()}}
    layout={'measured_changes':changes,'status':STATUS,'source_fidelity':raster,'baseline_measurement':base_measure,'calibrated_measurement':measure,'target_size':list(size),'profile':asdict(profile),'pagination_metrics':{k:v for k,v in metrics.items() if k!='content_text'},
            'dataset_readiness_unchanged':d['readiness'],'network_attempts':attempts,'renderer':version,'original_hashes':hashes,'all_original_hashes_unchanged':all(file_hash(path)==sha for path,sha in hashes.items()),'content_text_exact':True,
            'limits':['Source/ChatGPT glyph bands and outer ink include diagrams/decoration; no font identification or verified content margins.','Math placement matches saved DOM, not source formula regions.','Geometry withheld; comparison density includes absence of original diagrams.','All print parameters and reading order remain unverified; no automatic batch integration.']}
    if not layout['all_original_hashes_unchanged']:raise ValueError('Historical input changed')
    for filename,data in [('pagination-analysis.json',analysis),('math-integrity.json',integrity),('layout-metrics.json',layout),('selected-profile.json',asdict(profile))]:
        (output/filename).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    before=totals(base_measure);after=totals(measure)
    reduction=100*(1-(after['text']+after['display_math'])/(before['text']+before['display_math']))
    html='<!doctype html><html lang="vi"><meta charset="utf-8"><style>body{font:18px Georgia;margin:20px;background:#eee}.row{display:flex;gap:10px;align-items:start}figure{width:25%;margin:0}img{width:100%}a{margin:8px}</style><h1>TASK 3B · EXPERIMENTAL_UNVERIFIED</h1><p>HIGH_RISK_HOLD; chưa xác minh toán/hình học. Preview 3A '+str(len(base_measure['pages']))+' → 3B '+str(metrics['page_count'])+'.</p><div class="row">'
    for label,name in [('SOURCE','source'),('CHATGPT','chatgpt'),('TASK 3A','task3a-before'),('TASK 3B','rebuilt-calibrated')]:html+=f'<figure><b>{label}</b><a href="{name}.png"><img src="{name}.png"></a></figure>'
    html+='</div><p><a href="rebuilt-calibrated.html">Toàn bộ preview 3B</a></p>'
    for i in range(1,metrics['page_count']):html+=f'<a href="rebuilt-calibrated-continuation-{i}.png">3B nối tiếp {i}</a>'
    for i in range(1,len(base_measure['pages'])):html+=f'<a href="task3a-before-continuation-{i}.png">3A nối tiếp {i}</a>'
    html+='<h2>Hình chưa hoàn chỉnh — chỉ debug</h2>'
    for i in range(len(geometry)):html+=f'<div class="row"><figure>Crop gốc<img src="geometry-debug-{i}.png"></figure><figure>Context nguồn chưa xác minh<img src="geometry-context-{i}.png"></figure></div>'
    (output/'comparison.html').write_text(html+'</html>',encoding='utf8')
    report=f'''# TASK 3B — artifact trang 114\n\nEXPERIMENTAL_UNVERIFIED. HIGH_RISK_HOLD giữ nguyên. Branch feat/book-layout-consistency.\n\n## Kết quả\n\nPreview {len(base_measure['pages'])} → {metrics['page_count']} trang. Có thể 1 trang trong các thử nghiệm: {analysis['one_page_possible_in_trials']}. Cấu hình nhỏ nhất thử 20px dùng dải chữ+toán {analysis['minimum_trial_text_math_to_one_sheet_ratio']*100:.2f}% diện tích một vùng in, chưa kể khoảng cách/hình. Không giảm nội dung, không đổi LaTeX, không kéo giãn hoặc thu nhỏ ảnh trang. Chromium {version} offline, {len(attempts)} request mạng.\n\nProfile cố định thử nghiệm: {profile.font}, body {profile.body_size}px, title {profile.title_size}px, math {profile.math_font} 1em, line height {profile.line_height}; đoạn {profile.paragraph_gap}px, math {profile.math_gap}px; lề {profile.margins()}, trên/dưới {profile.top}/{profile.bottom}px. Khổ {size}; khổ in và minimum cỡ chữ chưa duyệt, không quy đổi sang point in khi chưa có DPI.\n\n## Nguyên nhân đo được\n\n{analysis['characters_non_math']} ký tự ngoài toán, {analysis['paragraphs']} đoạn, {len(rows)} math node ({analysis['math_inventory']['inline']} inline/{analysis['math_inventory']['display']} display). Mỗi math index xuất hiện đúng một lần. Không loại bỏ công thức giống nhau ở vị trí hợp lệ.\n\nPhân bổ diện tích (px² dải ngang toàn vùng in; không phải diện tích mực):\n\n| Thành phần | 3A | 3B |\n|---|---:|---:|\n'''
    for key in before:report+=f'| {key} | {before[key]:.1f} | {after[key]:.1f} |\n'
    report+=f'''\nChữ + display math giảm diện tích phân bổ {reduction:.2f}%. Ablation tách riêng line-height, gap đoạn, gap math, cỡ font và cohesion trong pagination-analysis.json. Profile chọn theo số trang an toàn nhỏ nhất, sau đó cỡ chữ lớn nhất; không điều chỉnh font tùy trang. Group giữ heading và block kế tiếp, câu nối ngắn với display math; mtable nhiều dòng không tách. Đo giữ nguyên toàn chuỗi text ngoài toán và inventory math.\n\n## Math fidelity\n\n{integrity['technical_preserved']}/{len(rows)} native MathML giữ nguyên cây tag/attribute/token; {integrity['limited_checks_passed']} node đạt phép kiểm hạn chế về số frac/script/root/ký hiệu góc/vuông góc/tích. Không suy ra LaTeX tương đương MathML chỉ từ rendering. Cả {len(rows)} node được liệt kê cần hậu kiểm tương đương LaTeX–MathML/source. Không tự xác minh toán học.\n\n## Hình học và giới hạn\n\nHai crop nguyên pixel nguồn đã đối chiếu, cả hai thiếu caption và có nét/nhãn sát biên; crop thứ hai thấy nhãn biên bị cắt khi soát ảnh. Vẫn placeholder, không ghép hình; context mở rộng chỉ debug, không phải crop đã duyệt. UNKNOWN: {unknown}. Ranh giới phản hồi so với trang nguồn UNVERIFIED: không OCR/AI mới nên chưa thể chứng minh nội dung dư. Không bỏ câu tiếp tục ở trang sau hoặc phần khác theo suy đoán.\n\nSo sánh raster dùng chung 1200×1668, threshold180, bbox/ink density/glyph row bands. Chỉ là proxy có thể bị hình và trang trí ảnh hưởng; không gọi đó là font size hoặc lề nội dung thật. Vị trí MathML được lưu theo trang/box, chưa nối chắc với vùng công thức nguồn. Header/footer chưa có tên/số đã duyệt thì bỏ trống; số artifact114 không phải số in. Không tuyên bố đạt chuẩn in.\n\n## Thay đổi đo được và phần chưa cải thiện\n\nSố trang giảm {changes['preview_pages_reduction_percent']:.2f}%; khoảng trắng nội bộ giảm {changes['internal_whitespace_reduction_percent']:.2f}%, vùng trống cuối trang cộng dồn giảm {changes['trailing_whitespace_reduction_percent']:.2f}%. Ink density trang preview đầu (threshold180, gồm cả nhãn thử nghiệm) SOURCE {raster['source']['ink_fraction_threshold180']*100:.3f}%, CHATGPT {raster['chatgpt']['ink_fraction_threshold180']*100:.3f}%, 3A {raster['task3a']['ink_fraction_threshold180']*100:.3f}%, 3B {raster['task3b']['ink_fraction_threshold180']*100:.3f}%. Chỉ so mật độ proxy trang đầu: lượng nội dung và hình giữa các bản khác nhau, không chứng minh fidelity ngữ nghĩa.\n\nTỷ lệ/lề target giữ nguyên, chưa cải thiện vùng hình hoặc header/footer. Vị trí công thức source không xác minh; chưa có phép đối chiếu vùng đủ tin cậy. Hình nguồn/caption còn bị giữ ngoài trang. Layout hai trang thử không phải bản sao một trang nguồn.\n\n## TASK 3C\n\nCần duyệt khổ in/DPI/minimum font và profile cố định; xác minh association, ranh giới trang, reading order, LaTeX–MathML, crop đủ nhãn/caption và vị trí. Sau đó thử offline nhiều trang với profile chung và gate không overlap/clipping/đủ nội dung, output mới riêng; không thay production ảnh ChatGPT khi chưa được duyệt.\n'''
    (output/'report.md').write_text(report,encoding='utf8')
    return analysis,layout,integrity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',required=True);p.add_argument('--fixture',required=True);p.add_argument('--baseline',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();analysis,_,integrity=calibrate(a.dataset,a.fixture,a.baseline,a.output)
    print(json.dumps({'pages_before':analysis['before_pages'],'pages_after':analysis['after_pages'],'math_preserved':integrity['technical_preserved'],'selected':analysis['selected_trial']['profile'],'output':a.output}))

if __name__=='__main__':main()
