"""TASK 3G offline measured paragraph layout. No production integrations."""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict
from html import escape
import json
import math
from copy import deepcopy
from pathlib import Path
import shutil
from PIL import Image, ImageDraw
from layout_paragraphs import reconstruct, align_paragraphs
from layout_rebuilder import Tree, RebuildProfile, preview_html, build_content
from layout_calibration import load_inputs, run_layout, math_integrity, MEASURE
from translation_evidence import file_hash


def intersects(a,b,tolerance=1):
    return min(a[2],b[2])-max(a[0],b[0])>tolerance and min(a[3],b[3])-max(a[1],b[1])>tolerance


def solve(items, printable=(110,110,1115,1568), gap=6, obstacles=()):
    """Use measured heights, reference x/width and soft source y, fixed DOM order.

    Source y attracts a candidate within one baseline line (30px). Larger gaps
    cannot establish source order and are not invented. Unknown geometry is
    never inserted. Oversized units are retained and explicitly infeasible.
    """
    x,top,right,bottom=printable;cursor=top;page=0;placements=[];issues=[]
    for item in items:
        height=item['height'];width=item['width']
        if not all(math.isfinite(v) and v>0 for v in (height,width)):raise ValueError('Missing/invalid measured dimensions')
        left=max(x,min(item.get('left',x),right-width))
        if height>bottom-top or width>right-x:
            issues.append({'id':item['id'],'status':'LAYOUT_INFEASIBLE','height':height,'width':width})
        y=cursor
        preferred=item.get('reference_top')
        if page==0 and preferred is not None and 0<=preferred-y<=30:y=preferred
        if y+height>bottom and cursor>top:
            page+=1;cursor=top;y=top
        relevant=[o for o in obstacles if o.get('page',0)==page and o.get('verified') is True]
        while True:
            hit=next((o for o in relevant if intersects([left,y,left+width,y+height],o['bbox'],0)),None)
            if not hit:break
            y=hit['bbox'][3]+gap
            if y+height>bottom:
                page+=1;cursor=top;y=top
                relevant=[o for o in obstacles if o.get('page',0)==page and o.get('verified') is True]
        placements.append(dict(item,page=page,bbox=[left,y,left+width,y+height],
            reference_displacement_y=None if preferred is None else y-preferred))
        cursor=y+height+gap
    return {'placements':placements,'page_count':page+1 if items else 0,'issues':issues,
            'status':'LAYOUT_INFEASIBLE' if issues else 'MEASURED_CANDIDATE_LAYOUT'}


def serialize(n):
    if isinstance(n,str):return escape(n)
    attrs=''.join(f' {k}="{escape(v,quote=True)}"' for k,v in n.attrs.items())
    if n.tag in Tree.VOID:return f'<{n.tag}{attrs}>'
    return f'<{n.tag}{attrs}>'+''.join(serialize(c) for c in n.children)+f'</{n.tag}>'


def make_units(nodes,alignment,source_size,printable=(110,110,1115,1568)):
    """Unique paragraph owners may group consecutive DOM blocks, never reorder.

    Conflicting many-to-one localizations stay unresolved; each block/math is
    emitted exactly once. A group may contain multiple CN and VI blocks.
    """
    owners={}
    for link in alignment['links']:
        if link['verification_status']!='ALIGNED_CANDIDATE':continue
        for tid in link['translation_block_ids']:owners.setdefault(tid,[]).append(link)
    units=[];i=0;left,top,right,bottom=printable
    while i<len(nodes):
        block_id=f'vi:block:{i}';choices=owners.get(block_id,[])
        link=choices[0] if len(choices)==1 else None;indices=[i];i+=1
        if link:
            while i<len(nodes) and len(owners.get(f'vi:block:{i}',[]))==1 and owners[f'vi:block:{i}'][0]['paragraph_id']==link['paragraph_id']:
                indices.append(i);i+=1
        if link:
            b=link['source_bbox'];sx=1200/source_size[0];sy=1668/source_size[1]
            x=max(left,min(b[0]*sx,right-100));width=min(right-x,max(100,(b[2]-b[0])*sx))
            ref=b[1]*sy
            if any(nodes[j].tag.startswith('h') for j in indices):x=left;width=right-left
        else:x=left;width=right-left;ref=None
        units.append({'id':f'unit:{len(units)}','block_ids':[f'vi:block:{j}' for j in indices],
            'paragraph_id':link['paragraph_id'] if link else None,'left':x,'width':width,'reference_top':ref,
            'status':'PARAGRAPH_CANDIDATE' if link else ('AMBIGUOUS' if choices else 'UNMATCHED'),
            'html':''.join(serialize(nodes[j]) for j in indices)})
    return units


MEASURE_UNITS=r'''async () => {
 await document.fonts.ready;
 const box=e=>{const r=e.getBoundingClientRect();return [r.left,r.top,r.right,r.bottom]};
 return [...document.querySelectorAll('#flow>.unit')].map(e=>{
   let r=box(e);const children=[...e.querySelectorAll('math,p,h1,h2,h3,h4,.formula')].map(box);
   const low=Math.min(r[1],...children.map(b=>b[1])),high=Math.max(r[3],...children.map(b=>b[3]));
   const maths=[...e.querySelectorAll('math')].map(box);
   return {id:e.dataset.id,height:high-low,width:r[2]-r[0],ink_offset:low-r[1],
      math_overflow:maths.some(b=>b[0]<r[0]-1||b[2]>r[2]+1),
      math_max_width:Math.max(0,...maths.map(b=>b[2]-b[0]))};
 });
}'''

POST_MEASURE=r'''() => {
 const box=e=>{let r=e.getBoundingClientRect();return [r.left,r.top,r.right,r.bottom]};
 let collisions=[],overflow=[],units=[],glyphs=[];
 for(const [pi,page] of [...document.querySelectorAll('.page')].entries()){
  const main=page.querySelector('main'),limit=box(main),atoms=[];
  for(const u of main.children){
   const r=box(u);units.push({id:u.dataset.id,page:pi,bbox:r,height:r[3]-r[1],block_ids:JSON.parse(u.dataset.blocks)});
   const extent=[...u.querySelectorAll('p,h1,h2,h3,h4,math')].map(box);
   const excess=Math.max(0,r[0]-Math.min(r[0],...extent.map(b=>b[0])),Math.max(r[2],...extent.map(b=>b[2]))-r[2],
     r[1]-Math.min(r[1],...extent.map(b=>b[1])),Math.max(r[3],...extent.map(b=>b[3]))-r[3],r[3]-limit[3],r[2]-limit[2]);
   if(excess>1)overflow.push({type:'OVERFLOW',id:u.dataset.id,page:pi,px:excess});
   const walker=document.createTreeWalker(u,NodeFilter.SHOW_TEXT);
   while(walker.nextNode()){
    const n=walker.currentNode;if(!n.textContent.trim()||n.parentElement.closest('.formula'))continue;
    // Per-character ranges avoid bounding a wrapped text node across inline math.
    for(let k=0;k<n.length;k++){if(!n.textContent[k].trim())continue;
     const range=document.createRange();range.setStart(n,k);range.setEnd(n,k+1);
     for(const r of range.getClientRects())if(r.width&&r.height)atoms.push({type:'TEXT',unit:u.dataset.id,text_block:[...u.querySelectorAll('p,h1,h2,h3,h4')].indexOf(n.parentElement.closest('p,h1,h2,h3,h4')),box:[r.left,r.top,r.right,r.bottom]});
    }
   }
   for(const e of u.querySelectorAll('math')){
    const b=box(e),id=Number(e.closest('.formula').dataset.math);atoms.push({type:'MATH',unit:u.dataset.id,id,box:b});
    if(b[0]<limit[0]-1||b[2]>limit[2]+1)overflow.push({type:'MATH_OVERFLOW',index:id,page:pi,px:Math.max(limit[0]-b[0],b[2]-limit[2])});
   }
  }
  for(const e of page.querySelectorAll('header,footer,.notice'))if(e.textContent.trim())atoms.push({type:e.tagName==='FOOTER'?'FOOTER':'HEADER',unit:e.className||e.tagName,box:box(e)});
  const seen=new Set();
  for(let i=0;i<atoms.length;i++)for(let j=i+1;j<atoms.length;j++){
   let a=atoms[i],b=atoms[j];if(a.type==='TEXT'&&b.type==='TEXT'&&a.unit===b.unit&&a.text_block===b.text_block)continue;
   if(['HEADER','FOOTER'].includes(a.type)&&['HEADER','FOOTER'].includes(b.type))continue;
   if(Math.min(a.box[2],b.box[2])-Math.max(a.box[0],b.box[0])>1&&Math.min(a.box[3],b.box[3])-Math.max(a.box[1],b.box[1])>1){
    const key=JSON.stringify([a.type,b.type,a.unit,b.unit,a.id,b.id]);
    if(!seen.has(key)){seen.add(key);collisions.push({page:pi,type:a.type+'–'+b.type,a:a.unit,b:b.unit,math_ids:[a.id,b.id].filter(x=>x!==undefined),boxes:[a.box,b.box]});}
   }
  }
  glyphs.push({page:pi,atom_count:atoms.length});
 }
 const text=[...document.querySelectorAll('main')].map(m=>{const c=m.cloneNode(true);c.querySelectorAll('.formula').forEach(e=>e.remove());return c.textContent}).join('');
 return {collisions,overflow,units,glyphs,content_text:text};
}'''


def render_adaptive(page,units,profile,size):
    """Measure at source widths; broaden an overflowing math unit without scaling."""
    markup=''.join(f'<div class="unit" data-id="{u["id"]}" data-blocks="{escape(json.dumps(u["block_ids"]),quote=True)}" style="width:{u["width"]}px">{u["html"]}</div>' for u in units)
    page.set_content(preview_html(markup,profile,size))
    page.add_style_tag(content='#flow{display:block;position:absolute;left:0;top:0;width:1005px;font-family:"Times New Roman";font-size:24px;line-height:1.25}.unit{display:flow-root;box-sizing:border-box}.unit h1,.unit h2,.unit h3,.unit h4{margin-bottom:10px}')
    measures=page.evaluate(MEASURE_UNITS)
    # Width adjustment is typographic wrapping, not math alteration/font fitting.
    for u,m in zip(units,measures):
        if m['math_overflow']:
            u.update(left=110,width=1005,width_adjustment='EXPAND_TO_PRINTABLE_FOR_MATH')
            page.locator(f'[data-id="{u["id"]}"]').evaluate('(e)=>e.style.width="1005px"')
    measures=page.evaluate(MEASURE_UNITS)
    items=[dict(u,**m) for u,m in zip(units,measures)]
    solution=solve(items)
    # A tall paragraph is split only at its saved DOM block boundaries.
    # Never split a math node or omit any block; retries are local layout only.
    if solution['issues']:
        return solution,None,None
    placements=[{k:v for k,v in p.items() if k!='html'} for p in solution['placements']]
    page.evaluate(r'''cfg=>{
      const pages=document.querySelector('#pages');
      for(let i=0;i<cfg.page_count;i++){
       const p=document.createElement('section');p.className='page';
       p.innerHTML='<header></header><div class="notice">EXPERIMENTAL_UNVERIFIED · HIGH_RISK_HOLD · NOT_ANCHORABLE · HÌNH HỌC THIẾU/CHƯA XÁC MINH</div><main></main><footer></footer>';pages.append(p);
      }
      const mains=[...pages.querySelectorAll('main')];
      for(const u of cfg.placements){
       const e=document.querySelector('[data-id="'+u.id+'"]');mains[u.page].append(e);
       e.style.position='absolute';e.style.left=(u.bbox[0]-110)+'px';e.style.top=(u.bbox[1]-110-u.ink_offset)+'px';
       // Height follows rendered content, never the original Chinese line bbox.
       e.dataset.status=u.status;e.title=u.status+' / source correspondence unverified';
      }
      document.querySelector('#flow').remove();
    }''',{'placements':placements,'page_count':solution['page_count']})
    measurement=page.evaluate(MEASURE);post=page.evaluate(POST_MEASURE)
    solution['placements']=placements
    return solution,measurement,post


def build(root,output):
    from playwright.sync_api import sync_playwright
    root=Path(root).resolve();output=Path(output).resolve()
    f=root/'output/task3f-page114-20261011-ocr';dpath=root/'output/task3d-page114-20261011-final/alignment-dataset.json'
    baseline=root/'output/task3b-page114-20261011-recheck'
    read=lambda p:json.loads(Path(p).read_text(encoding='utf-8-sig'))
    ocr=read(f/'source-bboxes.json');d=read(dpath);before=read(f/'pilot-result.json')
    geometry=read(f/'geometry-review.json');profile_data=read(baseline/'layout-metrics.json')
    profile=RebuildProfile(**profile_data['profile']);size=tuple(profile_data['target_size'])
    assert size==(1200,1668) and profile.body_size==24 and profile.title_size==28 and profile.line_height==1.25
    capture=root/'output/task2g-live-resume-20261010-192802/capture/capture-50a0ac2d28e3424c9f8a40befdcab1c1'
    fixture=root/'tests/fixtures/layout_task2g_page114.json';dataset_path=capture/'dataset/dataset.json'
    dataset,candidate=load_inputs(dataset_path,fixture)
    if file_hash(ocr['source_image_path'])!=ocr['source_image_sha256'] or dataset['source_image']['sha256']!=ocr['source_image_sha256']:
        raise ValueError('OCR source binding no longer valid')
    content,rows,structure=build_content(candidate)
    nodes=[n for n in Tree(content).root.walk() if n.tag in ('p','h1','h2','h3','h4') or 'display' in n.attrs.get('class','').split()]
    if len(nodes)!=len(d['translation_blocks']) or len(rows)!=66:raise ValueError('Content inventory changed')
    historical=[p for folder in (f,baseline,dpath.parent) for p in folder.rglob('*') if p.is_file()]
    historical += [Path(ocr['source_image_path']),Path(dataset['translated_image']['path']),dataset_path,fixture,Path(json.loads(fixture.read_text(encoding='utf8'))['source_artifact'])]
    protected=[p for p in root.glob('layout*.py') if p.name not in ('layout_paragraphs.py','layout_adaptive.py')]
    protected += [root/n for n in ('run_chatgpt_batch.py','run_chatgpt_batch_books34.py','books34_composer.py')]
    hashes={str(p.resolve()):file_hash(p) for p in historical+protected}
    reconstruction=reconstruct(ocr['boxes'],ocr['source_image_sha256'],dataset['region_qc']['regions']['source'])
    provenance={'source_image_sha256':ocr['source_image_sha256'],'ocr_artifact_sha256':file_hash(f/'source-bboxes.json'),
                'saved_alignment_sha256':file_hash(dpath),'scope':'Local inventory references, not provider identities'}
    alignment=align_paragraphs(reconstruction,d['source_blocks'],d['translation_blocks'],d['block_links'],d['math_alignment'],provenance)
    units=make_units(nodes,alignment,ocr['source_image_size'])
    output.mkdir(parents=True,exist_ok=False)
    def save(n,v):(output/n).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
    save('paragraph-regions.json',reconstruction);save('paragraph-alignment.json',alignment)
    expected=''.join(n['text'] for n in structure['nodes'] if n['kind']=='text')
    attempts=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(offline=True,viewport={'width':1280,'height':1760},device_scale_factor=1)
        context.route('**/*',lambda route:(attempts.append(route.request.url),route.abort()))
        page=context.new_page()
        # Safe fallback always generated from identical saved text/native MathML.
        metrics,safe_measure=run_layout(page,content,profile,size,calibrated_style=True)
        safe_integrity=math_integrity(structure,rows,safe_measure)
        if metrics['content_text']!=expected or safe_integrity['technical_preserved']!=66:raise ValueError('Fallback integrity failed')
        (output/'safe-full-reflow.html').write_text(page.content(),encoding='utf8')
        for i in range(metrics['page_count']):page.locator('.page').nth(i).screenshot(path=str(output/f'safe-full-reflow-{i+1}.png'))
        solution,measurement,post=render_adaptive(page,units,profile,size)
        width_trials=[{'factor':1.0,'pages':solution['page_count'],'safe':post is not None and not post['collisions'] and not post['overflow']}]
        # Under page pressure, relax candidate widths within the printable area,
        # retaining the source left edge. Choose the smallest relaxation reaching
        # safe reflow page count. Typography, DOM/math and source evidence stay fixed.
        initial=deepcopy(units)
        best=(deepcopy(solution),deepcopy(measurement),deepcopy(post),deepcopy(units))
        if measurement is not None and solution['page_count']>metrics['page_count']:
            for factor in (1.25,1.5,2.0):
                trial=deepcopy(initial)
                for u in trial:
                    if u.get('paragraph_id'):
                        u['width']=min(1115-u['left'],u['width']*factor)
                        u['width_adjustment']='SOURCE_LEFT_PRESERVED_WIDTH_RELAXATION_'+str(factor)
                sol,meas,check=render_adaptive(page,trial,profile,size)
                safe=check is not None and not check['collisions'] and not check['overflow']
                width_trials.append({'factor':factor,'pages':sol['page_count'],'safe':safe})
                if safe and (best[2] is None or sol['page_count']<best[0]['page_count']):best=(sol,meas,check,trial)
                if safe and sol['page_count']<=metrics['page_count']:break
            units=best[3];solution,measurement,post=render_adaptive(page,units,profile,size)
        solution['width_trials']=width_trials
        # If paragraph envelope is taller than a page, retain exact DOM nodes in
        # individual units and remeasure; no hidden overflow or sliced formula.
        if measurement is None:
            singleton=dict(alignment,links=[]);units=make_units(nodes,singleton,ocr['source_image_size'])
            solution,measurement,post=render_adaptive(page,units,profile,size)
            solution['fallback_reason']='Paragraph unit infeasible; all saved DOM blocks reflow separately'
        if measurement is None:
            post={'collisions':[],'overflow':solution['issues'],'content_text':None,'units':[]}
            integrity=safe_integrity;status='PREVIEW_BLOCKED'
            (output/'adaptive-preview.html').write_text('<!doctype html><meta charset="utf-8"><h1>PREVIEW_BLOCKED / NOT_ANCHORABLE</h1><p>Không đủ dữ liệu bố trí an toàn.</p><a href="safe-full-reflow.html">Toàn bộ nội dung reflow an toàn</a>',encoding='utf8')
        else:
            integrity=math_integrity(structure,rows,measurement)
            if post['content_text']!=expected or integrity['technical_preserved']!=66:raise ValueError('Adaptive content/math changed')
            status='PREVIEW_BLOCKED' if post['collisions'] or post['overflow'] else 'SAFE_DIAGNOSTIC_PREVIEW'
            (output/'adaptive-preview.html').write_text(page.content(),encoding='utf8')
            if status!='PREVIEW_BLOCKED':
                screenshots=[]
                for i in range(solution['page_count']):
                    path=output/f'adaptive-preview-{i+1}.png';page.locator('.page').nth(i).screenshot(path=str(path));screenshots.append(path)
                canvas=Image.new('RGB',(1200*len(screenshots),1668),'#ddd')
                for i,path in enumerate(screenshots):
                    with Image.open(path) as image:canvas.paste(image,(1200*i,0))
                canvas.save(output/'adaptive-preview.png')
        browser_version=browser.version;browser.close()
    # Raw pixels in geometry crops remain exact. They occur only in diagnostic.
    geometry_assets=[]
    for i,g in enumerate(geometry):
        source=Path(g['path']);target=output/f'geometry-debug-{i+1}.png'
        if file_hash(source)!=g['sha256']:raise ValueError('Geometry crop changed')
        shutil.copyfile(source,target)
        geometry_assets.append({'path':target.name,'sha256':file_hash(target),'source_sha256':g['sha256'],
            'status':'GEOMETRY_UNKNOWN_UNVERIFIED','inserted_in_layout':False})
    with Image.open(ocr['source_image_path']) as image:
        overlay=image.convert('RGB');draw=ImageDraw.Draw(overlay)
        for p in reconstruction['paragraphs']:
            b=p['source_bbox'];color='#138060' if p['region_type']=='BODY_TEXT' else '#cc7700'
            draw.rectangle(b,outline=color,width=5);draw.text((b[0],b[1]),p['paragraph_id'],fill=color)
        overlay.save(output/'paragraph-overlay.png')
    for title,source in [('source',baseline/'source.png'),('chatgpt',baseline/'chatgpt.png'),('task3b-1',baseline/'rebuilt-calibrated.png'),
                          ('task3b-2',baseline/'rebuilt-calibrated-continuation-1.png'),('task3f',f/'anchored-preview.png')]:
        shutil.copyfile(source,output/(title+'.png'))
    unchanged=all(file_hash(p)==sha for p,sha in hashes.items())
    if not unchanged or attempts:raise ValueError('Historical mutation or network attempt')
    counts=Counter(p['verification_status'] for p in reconstruction['paragraphs'])
    linked={t for l in alignment['links'] for t in l['translation_block_ids']}
    result={'status':'EXPERIMENTAL_UNVERIFIED','readiness':'HIGH_RISK_HOLD','anchor_status':'NOT_ANCHORABLE','preview_status':status,
        'paragraph_count':len(reconstruction['paragraphs']),'paragraph_status_counts':dict(counts),
        'paragraph_type_counts':dict(Counter(p['region_type'] for p in reconstruction['paragraphs'])),
        'paragraph_alignment_counts':dict(Counter(l['verification_status'] for l in alignment['links'])),
        'source_blocks_linked':len({s for l in alignment['links'] for s in l['source_block_ids']}),
        'translation_blocks_linked':len(linked),'verified_anchors':0,'math_nodes_preserved':integrity['technical_preserved'],
        'rendered_block_count':len([t for u in post['units'] for t in u['block_ids']]),'expected_block_count':53,
        'text_exact':post['content_text']==expected,'content_preservation_ratio':1.0 if post['content_text']==expected and integrity['technical_preserved']==66 else None,
        'geometry_complete':False,'geometry':geometry_assets,'profile':asdict(profile),'target_size':list(size),
        'typography_unchanged':True,'solution':solution,'post_render_measurement':post,'math_integrity':integrity,
        'comparison':{'task3f_partial_only':True,'task3f_candidate_blocks':before['linked_translation_blocks'],
           'overflow_before':before['anchors_with_vertical_overflow'],'max_overflow_before_px':before['max_anchor_overflow_px'],
           'collision_pairs_before':len(before['content_overlap_pairs']),
           'overflow_after':len(post['overflow']),'max_overflow_after_px':max((v.get('px',0) for v in post['overflow']),default=0),
           'collision_pairs_after':len(post['collisions']),'full_reflow_pages_before':before['full_reflow_pages_after'],
           'adaptive_pages_after':solution['page_count'],'safe_full_reflow_pages':metrics['page_count'],
           'scope_limit':'3F measures 16 candidate blocks; 3G measures all 53 blocks. Geometry not in either translated layout.'},
        'browser':browser_version,'network_attempts':attempts,'original_hashes':hashes,'original_hashes_unchanged':unchanged,
        'production_integration':False,'limits':['OCR paragraph geometry and DOM reading order remain candidate.',
           'No independently verified source-to-Vietnamese binding or full geometry; not a finished source-faithful page.',
           'Source y is a soft reference; unresolved blocks stay in DOM order. No new translation or font reduction.']}
    save('adaptive-layout.json',result)
    save('collision-report.json',{'status':status,'method':'Chromium post-render unit and character-range/math bbox inspection',
        'before_3f_pairs':before['content_overlap_pairs'],'after':post['collisions'],'overflow':post['overflow'],
        'geometry_collision_status':'NOT_ASSESSED_GEOMETRY_NOT_INSERTED','caption_figure_status':'NOT_ASSESSED_UNVERIFIED_DEBUG_ONLY',
        'header_body_footer_checked':True})
    save('pagination-report.json',{'baseline_full_reflow_pages':2,'adaptive_pages':solution['page_count'],
        'safe_full_reflow_pages':metrics['page_count'],'geometry_complete':False,'status':status,'issues':solution['issues'],
        'blocks_preserved':result['rendered_block_count'],'math_preserved':result['math_nodes_preserved']})
    compare='''<!doctype html><html lang="vi"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'self' file:"><style>body{font:18px Arial;margin:24px;background:#eee}.row{display:flex;gap:12px;align-items:start}figure{margin:0;flex:1;min-width:0}img{width:100%}a{color:#075b97}</style><h1>TASK 3G · EXPERIMENTAL_UNVERIFIED / HIGH_RISK_HOLD / NOT_ANCHORABLE</h1><p>Diagnostic đủ văn bản/toán; hình học chưa ghép/chưa xác minh. Thứ tự DOM và liên kết nguồn là candidate. Không phải trang dịch hoàn chỉnh đã duyệt.</p><div class="row">'''
    for label,name in [('SOURCE','source.png'),('CHATGPT','chatgpt.png'),('3B Full Reflow p1','task3b-1.png'),('3F Line-Bbox (16/53 khối)','task3f.png'),('3G Paragraph-Adaptive p1','adaptive-preview-1.png' if status!='PREVIEW_BLOCKED' else 'safe-full-reflow-1.png')]:
        compare+=f'<figure><b>{escape(label)}</b><a href="{name}"><img src="{name}"></a></figure>'
    compare+='</div><p><a href="adaptive-preview.html">3G toàn bộ preview</a> · <a href="safe-full-reflow.html">Reflow an toàn</a> · <a href="paragraph-overlay.png">Paragraph overlay</a> · <a href="report.md">Báo cáo</a></p><h2>Trang tiếp theo — không bỏ nội dung</h2><div class="row"><figure><b>3B p2</b><img src="task3b-2.png"></figure>'
    if status!='PREVIEW_BLOCKED':
        for i in range(1,solution['page_count']):compare+=f'<figure><b>3G p{i+1}</b><img src="adaptive-preview-{i+1}.png"></figure>'
    compare+='</div><h2>Ba crop nguyên pixel — chỉ debug; thiếu chứng cứ nhãn/caption</h2><div class="row">'
    for g in geometry_assets:compare+=f'<figure><img src="{g["path"]}"><figcaption>GEOMETRY_UNKNOWN_UNVERIFIED</figcaption></figure>'
    (output/'comparison.html').write_text(compare+'</div></html>',encoding='utf8')
    c=result['comparison']
    report=f'''# TASK 3G — Source Paragraph Reconstruction & Adaptive Layout

Branch feat/book-layout-consistency. EXPERIMENTAL_UNVERIFIED / HIGH_RISK_HOLD / NOT_ANCHORABLE.
Preview status: {status}. Offline, không OCR lại, không dịch/gọi ChatGPT.

## Kết quả

91 bbox OCR gốc giữ đủ ở source_lines; tạo {result['paragraph_count']} vùng phụ trợ: {dict(counts)}.
Loại vùng: {result['paragraph_type_counts']}. Nhãn hình, công thức rời, caption không gom vào chữ.
Gom đoạn dựa trên overlap ngang, chiều cao dòng, gap dọc, lề/thụt dòng, marker mục, cột và barrier.
Mỗi dòng thuộc đúng một vùng; ID/toạ độ/confidence/hash/method gốc giữ nguyên.

{result['source_blocks_linked']}/35 khối Trung Quốc nối candidate tới {len(linked)}/53 khối Việt.
Trạng thái liên kết vùng: {result['paragraph_alignment_counts']}; 0 verified anchor.
CJK skeleton chỉ hỗ trợ định vị chữ, không xác minh ký hiệu/toán/đủ nghĩa.
Chuỗi paragraph → source block → VI block → math có provenance riêng và bằng chứng lexical cũ.
Một-nhiều/nhiều-một giữ membership; khi nhiều paragraph tranh một khối Việt, solver giữ unresolved thay vì chọn vị trí.

Đủ {result['rendered_block_count']}/53 khối Việt, text exact={result['text_exact']},
{result['math_nodes_preserved']}/66 MathML/LaTeX bảo toàn, không render trùng math node.
Tỷ lệ nội dung text/math giữ: {result['content_preservation_ratio']}; không bao gồm hình học chưa xác minh.
Ba crop TASK 3F được sao chép byte-exact và chỉ hiển thị trong comparison debug.

## Solver và so sánh thực đo

Đo Chromium tại độ rộng paragraph, mở rộng sang vùng in nếu math vượt chiều rộng tham chiếu;
không giảm font, kéo giãn math, sửa LaTeX hoặc thay MathML. Bbox nguồn là tham chiếu mềm.
Khi áp lực phân trang tăng, thử nới độ rộng candidate 1.25/1.5/2 lần trong vùng in, giữ mép trái nguồn;
chọn mức nới nhỏ nhất đạt số trang reflow an toàn. Mọi trial được đo thật và ghi width_trials.
Giữ luồng DOM đã lưu, nhóm các khối liên tiếp cùng paragraph, mở rộng theo chiều cao đo được,
dịch chuyển vùng tiếp theo với gap 6px và phân trang khi vượt đáy. Không dùng thứ tự OCR như chứng cứ thứ tự đọc.
Đo lại bbox sau render, kiểm tra character range/text, MathML, unit, header/footer và biên in.
Text–geometry/caption–figure chưa đánh giá vì không chèn geometry chưa xác minh.

| Chỉ số | 3F | 3G |
|---|---:|---:|
| Khối Việt trong diagnostic đo | 16/53 | {result['rendered_block_count']}/53 |
| Vùng tràn | {c['overflow_before']} | {c['overflow_after']} |
| Tràn lớn nhất px | {c['max_overflow_before_px']:.2f} | {c['max_overflow_after_px']:.2f} |
| Collision pairs | {c['collision_pairs_before']} | {c['collision_pairs_after']} |
| Trang đủ văn bản/toán | 2 (Full Reflow riêng) | {c['adaptive_pages_after']} |

Giảm collision/tràn là kết quả cơ học của bố trí vùng thực đo; hai diagnostic có phạm vi khác nhau.
Không chứng minh cải thiện fidelity hình học/đọc nguồn hoặc đạt một trang hoàn chỉnh.
Baseline typography giữ nguyên 1200×1668, Times New Roman 24px, title 28px, Cambria Math 1em,
line-height 1.25, gap 6px, lề 110/85/110/100. Đây là profile thử nghiệm chưa được duyệt chuẩn in.

## Bảo vệ và artifact

Hash lịch sử/input/module cũ: original_hashes_unchanged={unchanged}. Network attempts={attempts}.
Thêm layout_paragraphs.py, layout_adaptive.py và test mới; không production hooks hoặc thay feature flag.
Không commit/push/merge/reset/stash; không sửa worker/prompt/parser/Playwright/API/progress.csv.
Các JSON, overlay và comparison ở thư mục mới. adaptive-preview.png là contact sheet các trang render thật;
chỉ xuất khi không có collision/overflow. Khi PREVIEW_BLOCKED xem safe-full-reflow và JSON lỗi.

## Giới hạn và TASK 3H

Association, thứ tự đọc, transcription và math equivalence chưa độc lập xác minh.
UNKNOWN gồm nhãn hình/mảnh công thức không đủ dữ liệu gom đoạn. Không suy ra vị trí math từ OCR fragments.
Cần review có binding hash cho paragraph/block/math, thứ tự và ranh giới trang; xác nhận ba crop đầy đủ nhãn/caption.
Sau đó mới bố trí vùng hình/caption đã xác minh và kiểm tra collision thực render với geometry.
Không triển khai batch production. Test/compile được bổ sung sau chạy trong validation-results.txt.
'''
    (output/'report.md').write_text(report,encoding='utf8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',default=str(Path(__file__).parent));parser.add_argument('--output',required=True)
    a=parser.parse_args();r=build(a.root,a.output)
    print(json.dumps({k:r[k] for k in ('paragraph_count','paragraph_status_counts','paragraph_alignment_counts','source_blocks_linked','translation_blocks_linked','math_nodes_preserved','preview_status','comparison')},ensure_ascii=False))
