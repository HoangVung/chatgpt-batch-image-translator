"""Offline experimental book renderer. No worker imports or provider access.

Saved MathML is rendered by local Chromium; LaTeX is retained verbatim, never
reconstructed from text. Rendering success is not semantic verification.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
from PIL import Image
from translation_evidence import audit_fallback, digest, file_hash, structured_math

STATUS = 'EXPERIMENTAL_UNVERIFIED'

@dataclass(frozen=True)
class RebuildProfile:
    width: int = 1200
    height: int | None = None
    inner: int = 110
    outer: int = 85
    top: int = 110
    bottom: int = 100
    font: str = 'Times New Roman'
    math_font: str = 'Cambria Math'
    body_size: int = 27
    title_size: int = 36
    line_height: float = 1.42
    paragraph_gap: int = 12
    indent: int = 27
    math_gap: int = 14
    page_number: int | None = None
    chapter: str | None = None
    decoration: bool = False

    def __post_init__(self):
        for k in ('width','inner','outer','top','bottom','body_size','title_size','paragraph_gap','indent','math_gap'):
            v=getattr(self,k)
            if type(v) is not int or v < (1 if k in ('width','body_size','title_size') else 0):
                raise ValueError('Invalid profile: '+k)
        if self.height is not None and (type(self.height) is not int or self.height < 1):
            raise ValueError('Invalid height')
        if not 0.8 <= self.line_height <= 3 or self.width > 5000:
            raise ValueError('Invalid profile dimensions/line height')
        if self.page_number is not None and (type(self.page_number) is not int or self.page_number < 1):
            raise ValueError('Invalid page number')
        if not all(isinstance(v,str) and v and all(c.isalnum() or c in ' -' for c in v) for v in (self.font,self.math_font)):
            raise ValueError('Use a local font family name')

    def dimensions(self, source_size):
        height=self.height or round(self.width*source_size[1]/source_size[0])
        if not self.width > self.inner+self.outer+100 or not self.top+self.bottom+100 < height <= 7000:
            raise ValueError('Margins leave no printable area')
        return self.width,height

    def margins(self):
        # Even pages have the binding edge on the right. Unknown parity is explicit.
        return (self.outer,self.inner) if self.page_number is not None and self.page_number%2==0 else (self.inner,self.outer)

class Node:
    def __init__(self,tag='',attrs=()):
        self.tag=tag;self.attrs=dict(attrs);self.children=[]
    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c,Node):yield from c.walk()
    def text(self):
        return ''.join(c if isinstance(c,str) else c.text() for c in self.children)

class Tree(HTMLParser):
    VOID={'br','hr','img','input','meta','link','wbr','source','area','base','embed','param','col'}
    def __init__(self,html):
        super().__init__(convert_charrefs=True);self.root=Node();self.stack=[self.root]
        self.feed(html);self.close()
        if len(self.stack)!=1:raise ValueError('Unbalanced evidence HTML')
    def handle_starttag(self,tag,attrs):
        n=Node(tag,attrs);self.stack[-1].children.append(n)
        if tag not in self.VOID:self.stack.append(n)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.VOID:self.stack.pop()
    def handle_endtag(self,tag):
        if len(self.stack)<2 or self.stack[-1].tag!=tag:raise ValueError('Unbalanced tag '+tag)
        self.stack.pop()
    def handle_data(self,data):self.stack[-1].children.append(data)

MATH_TAGS=set('math semantics mrow mi mn mo mtext mspace mfrac msqrt mroot msup msub msubsup munder mover munderover mtable mtr mtd mstyle mpadded mphantom menclose mmultiscripts mprescripts none'.split())
MATH_ATTRS=set('display mathvariant stretchy fence separator accent accentunder largeop movablelimits symmetric form lspace rspace linethickness columnalign rowalign columnspacing rowspacing scriptlevel displaystyle width height depth voffset notation'.split())

def math_root(n):
    return n.attrs.get('data-d-component')=='math' or 'data-tex' in n.attrs or bool(set(n.attrs.get('class','').split())&{'katex','katex-display','katex-mathml'}) or n.tag=='math'

def native_math(n):
    if isinstance(n,str):return escape(n)
    if n.tag in ('annotation','annotation-xml'):return ''
    if n.tag not in MATH_TAGS:raise ValueError('Unsupported MathML tag '+n.tag)
    attrs=''.join(f' {k}="{escape(v,quote=True)}"' for k,v in n.attrs.items() if k in MATH_ATTRS)
    return f'<{n.tag}{attrs}>'+''.join(native_math(c) for c in n.children)+f'</{n.tag}>'

def build_content(candidate):
    structure=structured_math(candidate.get('html'),formulas=candidate.get('formulas',[]))
    if structure['status']!='AUXILIARY_UNVERIFIED':raise ValueError('Structured evidence incomplete')
    maths=[n for n in structure['nodes'] if n['kind']=='math'];rows=[]
    def emit(n):
        if isinstance(n,str):return escape(n)
        if math_root(n):
            i=len(rows);saved=maths[i];ml=[x for x in n.walk() if x.tag=='math']
            display=bool([x for x in n.walk() if 'katex-display' in x.attrs.get('class','').split()]) or bool(ml and ml[0].attrs.get('display')=='block')
            row={'index':i,'latex':saved['latex_candidate'],'verified':False,'display':display,'status':'PLACEHOLDER','reason':None}
            markup='[MATH_UNRESOLVED]'
            if saved['latex_candidate'] is not None and len(ml)==1:
                try:markup=native_math(ml[0]);row['status']='NATIVE_MATHML'
                except ValueError as exc:row['reason']=str(exc)
            else:row['reason']='Missing or ambiguous native MathML/LaTeX'
            rows.append(row)
            if row['status']=='PLACEHOLDER':markup='<code>'+escape(saved['latex_candidate'] or '[MATH_UNRESOLVED]')+'</code>'
            tag='div' if display else 'span'
            return f'<{tag} class="formula {"display" if display else "inline"}" data-math="{i}" title="UNVERIFIED">{markup}</{tag}>'
        if n.tag in ('script','style','img','iframe','object','link'):raise ValueError('Unsafe/unsupported evidence element '+n.tag)
        inside=''.join(emit(c) for c in n.children)
        if n.tag in ('p','h1','h2','h3','h4','ul','ol','li','blockquote','table','tbody','tr','td','th','sup','sub','strong','em','b','i'):
            return f'<{n.tag}>{inside}</{n.tag}>'
        if n.tag in ('br','hr'):return '<'+n.tag+'>'
        if n.attrs.get('data-d-font-style')=='italic':return '<em>'+inside+'</em>'
        if 'data-d-default-strong' in n.attrs:return '<strong>'+inside+'</strong>'
        return inside
    markup=emit(Tree(candidate['html']).root)
    if len(rows)!=len(maths):raise ValueError('Math inventory mismatch')
    return markup,rows,structure

PAGINATE = r'''async cfg => {
 await document.fonts.ready;
 const flow=document.querySelector('#flow'), blocks=[...flow.childNodes];
 const pages=[]; let body;
 function addPage(){
  const page=document.createElement('section');page.className='page';
  page.innerHTML='<header></header><div class="notice"></div><main></main><footer></footer>';
  page.querySelector('header').textContent=cfg.chapter||'';
  page.querySelector('.notice').textContent='EXPERIMENTAL_UNVERIFIED · Thứ tự DOM chưa xác minh'+(pages.length?' · Preview nối tiếp '+pages.length:'');
  page.querySelector('footer').textContent=cfg.page_number===null?'':String(cfg.page_number);
  document.querySelector('#pages').append(page);pages.push(page);body=page.querySelector('main');return body;
 }
 addPage();let oversized=[];
 for(const block of blocks){
  body.append(block);
  if(body.scrollHeight>body.clientHeight+1){
   if(body.childNodes.length>1){block.remove();addPage();body.append(block);}
   if(body.scrollHeight>body.clientHeight+1){
    oversized.push(pages.length-1);
    // Preserve the entire oversized block in a visibly taller preview sheet.
    // Target size PNG is still exported; a full overflow PNG is also mandatory.
    pages.at(-1).classList.add('oversized');
    pages.at(-1).style.height=(body.scrollHeight+cfg.top+cfg.bottom)+'px';
    addPage();
   }
  }
 }
 if(!body.childNodes.length&&pages.length>1){pages.pop().remove();}
 flow.remove();
 const box=e=>{let r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
 const issues=[],formula=[];
 pages.forEach((page,pi)=>{
  const main=page.querySelector('main'),m=main.getBoundingClientRect();
  page.querySelectorAll('.formula').forEach(e=>{
   const math=e.querySelector('math'),r=(math||e).getBoundingClientRect();
   let clipped=r.left<m.left-1||r.right>m.right+1||r.top<m.top-1||r.bottom>m.bottom+1;
   if(clipped)issues.push({type:'MATH_CLIP',index:Number(e.dataset.math),page:pi});
   formula.push({index:Number(e.dataset.math),page:pi,box:box(math||e),clipped,has_math:!!math});
  });
  for(const e of main.children){let r=e.getBoundingClientRect();if(r.right>m.right+1||r.bottom>m.bottom+1)issues.push({type:'CONTENT_OVERFLOW',page:pi,tag:e.tagName});}
  const imgs=[...main.querySelectorAll('img')],texts=[...main.querySelectorAll('p,.formula')];
  for(const img of imgs)for(const t of texts){let a=img.getBoundingClientRect(),b=t.getBoundingClientRect();if(a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top)issues.push({type:'IMAGE_TEXT_OVERLAP',page:pi});}
 });
 return {page_count:pages.length,oversized,issues,formula,content_text:[...document.querySelectorAll('main')].map(main=>{let c=main.cloneNode(true);c.querySelectorAll('.formula,.geometry-placeholder').forEach(e=>e.remove());return c.textContent;}).join(''),printable_boxes:pages.map(p=>box(p.querySelector('main'))),
 typography:{font:getComputedStyle(pages[0].querySelector('main')).fontFamily,font_size:getComputedStyle(pages[0].querySelector('main')).fontSize,line_height:getComputedStyle(pages[0].querySelector('main')).lineHeight}};
}'''

def preview_html(content,profile,size):
    w,h=size;left,right=profile.margins()
    css=f'''body{{margin:0;background:#ddd;color:#161616}}.page{{position:relative;box-sizing:border-box;width:{w}px;height:{h}px;background:white;margin:20px auto}}
main{{position:absolute;left:{left}px;right:{right}px;top:{profile.top}px;bottom:{profile.bottom}px;font-family:'{profile.font}',serif;font-size:{profile.body_size}px;line-height:{profile.line_height};overflow:visible}}
p{{margin:0 0 {profile.paragraph_gap}px;text-indent:{profile.indent}px;white-space:pre-wrap;overflow-wrap:break-word}}h1,h2,h3,h4{{font-size:{profile.title_size}px;line-height:1.2;margin:0 0 20px}}.display{{text-align:center;margin:{profile.math_gap}px 0;break-inside:avoid}}math{{font-family:'{profile.math_font}';font-size:1em}}.inline{{white-space:nowrap}}header,footer,.notice{{position:absolute;font-family:'{profile.font}',serif}}header{{top:30px;left:{left}px;right:{right}px;{'border-bottom:1px solid #aaa;' if profile.decoration else ''}}}footer{{bottom:30px;{'left' if profile.page_number is not None and profile.page_number%2==0 else 'right'}:{profile.outer}px}}.notice{{top:66px;left:{left}px;font-size:15px;color:#a33}}.geometry-placeholder{{border:1px dashed #a33;padding:10px;font-size:19px;margin:14px 0}}#flow{{display:none}}'''
    return '<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="status" content="'+STATUS+'"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data: file:"><title>Offline book preview</title><style>'+css+'</style><body><div id="pages"></div><div id="flow">'+content+'</div></body></html>'

def image_reference(source,target):
    with Image.open(source) as im:
        im.load()
        with target.open('xb') as f:im.save(f,format='PNG')
        return list(im.size)

def render(dataset_path,fixture_path,output,profile=RebuildProfile(),*,browser_executable=None):
    """Read immutable dataset + corroboration; create an entirely NEW output dir."""
    from playwright.sync_api import sync_playwright
    dataset_path=Path(dataset_path);fixture_path=Path(fixture_path);output=Path(output)
    d=json.loads(dataset_path.read_text(encoding='utf8'));f=json.loads(fixture_path.read_text(encoding='utf8'))
    evidence_path=Path(f['source_artifact'])
    if not evidence_path.is_absolute():evidence_path=Path(__file__).parent/evidence_path
    if file_hash(evidence_path)!=f['source_artifact_sha256']:raise ValueError('Fixture/capture hash mismatch')
    if digest({k:v for k,v in d.items() if k!='dataset_sha256'})!=d['dataset_sha256']:raise ValueError('Dataset hash mismatch')
    if json.loads(evidence_path.read_text(encoding='utf8'))['capture_audit']!=d['translation']['capture_audit']:raise ValueError('Capture audit mismatch')
    for k in ('source_image','translated_image'):
        if file_hash(d[k]['path'])!=d[k]['sha256']:raise ValueError('Image hash mismatch: '+k)
    fallback=audit_fallback(d['translation'].get('capture_audit'),evidence=d['translation'],corroboration=f.get('corroboration'))
    if not fallback.get('candidate'):raise ValueError('No bounded saved translation candidate: '+str(fallback['reasons']))
    content,maths,structure=build_content(fallback['candidate'])
    geometry=[]
    for crop in d.get('geometry_crops',[]):
        # Prototype conservatively withholds every crop; it has no adjudication UI.
        geometry.append({'region_id':crop['region_id'],'status':'UNVERIFIED_PLACEHOLDER','original':crop,'inserted':False})
        content+='<div class="geometry-placeholder">Hình nguồn '+escape(crop['region_id'])+' chưa xác minh đủ nhãn/caption và vị trí — xem khu vực debug trong comparison.</div>'
    unknown=[r['id'] for r in (d.get('region_qc') or {}).get('regions',{}).get('source',[]) if r.get('comparison_type')=='UNKNOWN']
    output.mkdir(parents=True,exist_ok=False)
    sizes={k:image_reference(d[key]['path'],output/(k+'.png')) for k,key in [('source','source_image'),('chatgpt','translated_image')]}
    size=profile.dimensions(sizes['source'])
    html=preview_html(content,profile,size);requests=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,**({'executable_path':browser_executable} if browser_executable else {}))
        context=browser.new_context(viewport={'width':size[0]+80,'height':size[1]+80},device_scale_factor=1,offline=True)
        def deny(route):
            requests.append(route.request.url);route.abort()
        context.route('**/*',deny)
        page=context.new_page();page.set_content(html)
        metrics=page.evaluate(PAGINATE,dict(asdict(profile),top=profile.top,bottom=profile.bottom))
        expected_text=''.join(n['text'] for n in structure['nodes'] if n['kind']=='text')
        if metrics['content_text'] != expected_text:raise ValueError('Non-math text changed during rendering')
        metrics['text_preserved']=True
        del metrics['content_text']
        # Saved HTML is already paginated and script free; browser opening is offline.
        (output/'rebuilt-preview.html').write_text(page.content(),encoding='utf8')
        pages=page.locator('.page')
        for i in range(metrics['page_count']):
            target=output/('rebuilt-preview.png' if i==0 else f'rebuilt-preview-continuation-{i}.png')
            element=pages.nth(i);box=element.bounding_box()
            page.screenshot(path=str(target),full_page=True,clip={'x':box['x'],'y':box['y'],'width':size[0],'height':size[1]})
            if i in metrics['oversized']:element.screenshot(path=str(output/f'overflow-full-{i}.png'))
        browser_version=browser.version;browser.close()
    rendered={x['index'] for x in metrics['formula'] if x['has_math']}
    if len(metrics['formula'])!=len(maths) or len({x['index'] for x in metrics['formula']})!=len(maths):raise ValueError('Rendered math inventory mismatch')
    overflow=metrics['page_count']>1 or bool(metrics['issues']) or bool(metrics['oversized'])
    report={'status':STATUS,'verified':False,'eligible_for_final_page':False,'publication_status':'NOT_APPROVED',
        'dataset_readiness_unchanged':d['readiness'],'capture_status':fallback['status'],'association_status':fallback['association_status'],
        'page_number_status':'UNKNOWN' if profile.page_number is None else 'USER_CONFIGURED_UNVERIFIED','chapter_status':'UNKNOWN' if profile.chapter is None else 'USER_CONFIGURED_UNVERIFIED',
        'reading_order_verified':False,'order_basis':'Saved DOM sequence; paragraph boundaries preserved',
        'profile':asdict(profile),'target_size':list(size),'size_basis':'Experimental source scan aspect ratio; no approved print trim',
        'image_sizes':sizes,'aspect_ratios':{k:v[0]/v[1] for k,v in dict(sizes,rebuilder=list(size)).items()},
        'renderer':{'engine':'Local Chromium native MathML','version':browser_version,'offline':True,'network_attempts':requests,'provider_access':False},
        'math':{'total':len(maths),'rendered_native':len(rendered),'placeholder_count':len(maths)-len(rendered),'nodes':maths,
                'latex_unchanged':True,'semantic_verified':False,'note':'Native saved MathML rendered once. LaTeX archived verbatim, not rerendered or inferred.'},
        'layout_status':'OVERFLOW' if overflow else 'TECHNICAL_FIT_UNVERIFIED','metrics':metrics,'geometry':geometry,'unknown_regions':unknown,
        'translation_candidate_sha256':digest(fallback['candidate']),'non_math_text_preserved':metrics['text_preserved'],
        'input_hashes':{'dataset':file_hash(dataset_path),'fixture':file_hash(fixture_path),'capture':file_hash(evidence_path)},
        'limits':['Translation, image association, reading order and math semantics remain unverified.',
                  'Geometry withheld; placeholders at end are debug notices, not inferred source positions.',
                  'Continuation index does not change the original book page number.',
                  'Block-level pagination; oversized blocks get an additional full-height overflow artifact.',
                  'Native MathML technical rendering does not certify equality with LaTeX or source.',
                  'Page artifact name is not a verified printed page number. Footer/header omitted if unconfigured.',
                  'Raster source and ChatGPT typography/margins not measured semantically; no comparative improvement claim.']}
    (output/'layout-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    debug=''
    for i,g in enumerate(geometry):
        crop=g['original'];path=Path(crop['path'])
        if file_hash(path)!=crop['sha256']:raise ValueError('Crop hash mismatch')
        shutil.copyfile(path,output/f'geometry-debug-{i}.png')
        debug+=f'<p>{escape(g["region_id"])} — CANDIDATE_UNVERIFIED, không đưa vào trang</p><img src="geometry-debug-{i}.png">'
    continuations=''.join(f'<a href="rebuilt-preview-continuation-{i}.png">Preview nối tiếp {i}</a> ' for i in range(1,metrics['page_count']))
    comparison=f'''<!doctype html><html lang="vi"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'self' file:"><title>TASK 3A</title><style>body{{font:18px Georgia;background:#eee;margin:24px}}.compare{{display:flex;align-items:start;gap:12px}}figure{{width:33%;margin:0}}img{{max-width:100%}}figcaption{{font-weight:bold}}pre{{white-space:pre-wrap}}</style><h1>Trang 114 · EXPERIMENTAL_UNVERIFIED</h1><p>HIGH_RISK_HOLD · Thứ tự đọc, nội dung toán và hình học chưa hậu kiểm. {report['layout_status']}, {metrics['page_count']} trang preview.</p><div class="compare">'''+''.join(f'<figure><figcaption>{label}</figcaption><a href="{name}.png"><img src="{name}.png"></a></figure>' for label,name in [('SOURCE','source'),('CHATGPT','chatgpt'),('REBUILDER — preview đầu','rebuilt-preview')])+f'</div><p>{continuations}</p><p><a href="rebuilt-preview.html">HTML đầy đủ</a> · <a href="layout-report.json">Số đo</a></p><h2>Debug hình nguồn</h2>{debug}</html>'
    (output/'comparison.html').write_text(comparison,encoding='utf8')
    summary=f'''# TASK 3A — trang 114\n\nEXPERIMENTAL_UNVERIFIED; HIGH_RISK_HOLD giữ nguyên.\n\nRenderer: Chromium {browser_version}, native MathML offline, không CDN/API.\n\n- Scan nguồn: {sizes['source']}; ChatGPT: {sizes['chatgpt']}; target thử nghiệm: {list(size)}.\n- Math: {len(rendered)}/{len(maths)} native MathML; {len(maths)-len(rendered)} placeholder. LaTeX giữ nguyên trong JSON.\n- {report['layout_status']}: {metrics['page_count']} trang preview, {len(metrics['issues'])} lỗi biên/chồng lấn đo được.\n- Typography đo được: {metrics['typography']}. Lề: {profile.margins()}, trên/dưới: {profile.top}/{profile.bottom}px.\n- {len(geometry)} crop chưa xác minh được giữ trong debug; {len(unknown)} UNKNOWN nguồn.\n\nTemplate cố định và bố cục text/math có số đo; chưa có bằng chứng cải thiện nội dung hoặc mức giống bản gốc. Không suy ra font/lề của raster từ cảm nhận. Header chỉ xuất nếu cấu hình đã cung cấp; tiêu đề nội dung được giữ. Khổ target bám tỷ lệ scan, chưa phải khổ in được duyệt.\n\nKhông dùng quota, không chạy worker, không tích hợp production, không đổi trạng thái dataset.\n\nTASK 3B: hậu kiểm association/LaTeX–MathML, thứ tự đọc, crop đủ nhãn/caption và vị trí; duyệt khổ in/font/template, rồi cải thiện phân trang trong đoạn và đo đối chiếu raster có hiệu chuẩn.\n'''
    (output/'report.md').write_text(summary,encoding='utf8')
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',required=True);parser.add_argument('--fixture',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--profile');parser.add_argument('--browser-executable')
    args=parser.parse_args()
    profile=RebuildProfile(**json.loads(Path(args.profile).read_text(encoding='utf8'))) if args.profile else RebuildProfile()
    report=render(args.dataset,args.fixture,args.output,profile,browser_executable=args.browser_executable)
    print(json.dumps({'status':report['status'],'layout_status':report['layout_status'],'math':report['math']['rendered_native'],'output':str(Path(args.output).resolve())}))

if __name__=='__main__':main()
