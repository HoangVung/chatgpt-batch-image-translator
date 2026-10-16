"""Opt-in, read-only translation capture. Never sends a prompt or changes worker state."""
from __future__ import annotations
import hashlib
import json
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_ACTIVE = ContextVar('translation_evidence_session', default=None)
# Deliberately stricter than the response-wait parser: stable role/message IDs
# and assistant markdown are mandatory. Unsupported DOM is incomplete evidence.
SNAPSHOT_JS = r'''() => {
 const roots = Array.from(document.querySelectorAll('[data-message-id][data-message-author-role], [data-content-search-unit-key$=":user"], [data-content-search-unit-key$=":assistant"], [data-chatgpt-search-unit-key$=":user"], [data-chatgpt-search-unit-key$=":assistant"]'));
 if (roots.length > 200) return {supported:false, reason:'conversation_too_large'};
 const ignore='button,[role="button"],[role="toolbar"],script,style,[aria-hidden="true"],.sr-only';
 const strip = n => { const c=n.cloneNode(true); c.querySelectorAll(ignore).forEach(x=>x.remove()); return c; };
 const messages=roots.filter(n=>!roots.some(p=>p!==n && p.contains(n))).map(n=>{
  const role=n.getAttribute('data-message-author-role') || (n.getAttribute('data-content-search-unit-key') || n.getAttribute('data-chatgpt-search-unit-key') || '').split(':').pop();
  const id=n.getAttribute('data-message-id') || n.querySelector('[data-message-id]')?.getAttribute('data-message-id') || n.querySelector('[data-chatgpt-selection-message-id]')?.getAttribute('data-chatgpt-selection-message-id');
  const selector=role==='assistant'?'.markdown,[data-markdown-text-style="assistant-message"]':'[data-markdown-text-style="user-message"]';
  let content=Array.from(n.querySelectorAll(selector));
  content=content.filter(x=>!content.some(p=>p!==x && p.contains(x)));
  if (!content.length && role==='user') content=[n];
  if (!content.length) return {id,role,unsupported:true};
  const clones=content.map(strip);
  return {id,role,
   text:clones.map(x=>x.textContent).join('\n'),html:content.map(x=>x.outerHTML).join('\n'),
   blocks:clones.flatMap(x=>Array.from(x.children).map((p,i)=>({tag:p.tagName,text:p.textContent}))),
   formulas:content.flatMap(x=>Array.from(x.querySelectorAll('annotation[encoding="application/x-tex"], [data-tex]')).map(a=>({
     representation:a.hasAttribute('data-tex')?'data-tex':'latex_annotation',raw:a.hasAttribute('data-tex')?a.getAttribute('data-tex'):a.textContent})))
  };
 });
 const ids=messages.map(m=>m.id);
 const generating=Array.from(document.querySelectorAll('button[data-testid="stop-button"],button[aria-label="Stop generating" i],button[aria-label="Stop streaming" i],button[aria-label="Dừng tạo" i],button[aria-label="Dừng phản hồi" i]')).some(n=>n.getClientRects().length);
 const supported=messages.length>0 && ids.every(Boolean) && new Set(ids).size===ids.length && messages.every(m=>['user','assistant'].includes(m.role)&&!m.unsupported);
 if (messages.some(m=>(m.text||'').length>2000000)) return {supported:false,reason:'response_too_large'};
 return {supported,conversation_url:location.origin+location.pathname,generating,messages};
}'''


def digest(data):
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()


def file_hash(path):
    d=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):d.update(chunk)
    return d.hexdigest()


def read_snapshot(page):
    return page.evaluate(SNAPSHOT_JS)


def incomplete(reason):
    return {'status':'EVIDENCE_INCOMPLETE','verified':False,'confidence':0.,'reasons':[reason],
            'text':None,'blocks':[],'formulas':[]}


def _valid_snapshot(s):
    if not isinstance(s,dict) or s.get('supported') is not True or s.get('generating') is not False:return False
    if not re.fullmatch(r'https://(?:chatgpt\.com|chat\.openai\.com)/c/[A-Za-z0-9_-]+',str(s.get('conversation_url',''))):return False
    rows=s.get('messages')
    return (isinstance(rows,list) and bool(rows) and all(isinstance(r,dict) and isinstance(r.get('id'),str) and r['id']
             and r.get('role') in ('user','assistant') and isinstance(r.get('text'),str) and not r.get('unsupported') for r in rows)
            and len({r['id'] for r in rows})==len(rows))


def extract_translation(before,after,*,expected_prompt,complete):
    """Only exactly one new user/assistant pair after the immutable baseline."""
    if complete is not True or not _valid_snapshot(before) or not _valid_snapshot(after):
        return incomplete('Missing stable IDs, conversation identity or completed response')
    if before['conversation_url']!=after['conversation_url']:return incomplete('Conversation changed')
    old,new=before['messages'],after['messages']
    if len(new)!=len(old)+2:return incomplete('Ambiguous response count; no previous/copy turn selected')
    if [(r['id'],r['role'],r['text']) for r in new[:len(old)]]!=[(r['id'],r['role'],r['text']) for r in old]:
        return incomplete('Baseline history changed or was virtualized')
    user,response=new[-2:]
    if user['role']!='user' or user['text'].strip()!=expected_prompt or response['role']!='assistant' or not response['text'].strip():
        return incomplete('New response is not uniquely attached to the translation prompt')
    if {user['id'],response['id']} & {r['id'] for r in old}:return incomplete('Reused message identity')
    formulas=[dict(f) for f in response.get('formulas',[]) if isinstance(f,dict)]
    # Preserve literal original delimiters verbatim; these are syntax candidates,
    # not a semantic formula inventory or links to raster regions.
    for match in re.finditer(r'\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]|\$\$[\s\S]*?\$\$',response['text']):
        formulas.append({'representation':'literal_latex_in_dom_text','raw':match.group(0),
                         'text_span':[match.start(),match.end()],'verified':False})
    result={'status':'COLLECTED_UNVERIFIED','verified':False,'confidence':.85,
            'confidence_scope':'Provisional DOM/turn association, not translation accuracy',
            'conversation_url':after['conversation_url'],'user_message_id':user['id'],'assistant_message_id':response['id'],
            'text':response['text'],'html':response.get('html'),
            'blocks':[dict(b,order=i) for i,b in enumerate(response.get('blocks',[]))],
            'formulas':formulas,'reasons':[],
            'representation':'DOM textContent and DOM HTML; not provider raw Markdown',
            'limitations':['Rendered KaTeX may duplicate symbols in DOM text; original available LaTeX is stored separately.',
                           'No semantic translation, formula or reading-order verification.']}
    result['text_sha256']=hashlib.sha256(result['text'].encode('utf8')).hexdigest()
    result['response_sha256']=digest({k:result[k] for k in ('text','html','blocks','formulas')})
    return result


class CaptureSession:
    def __init__(self,page,source,root):
        self.page=page;self.source=Path(source).resolve();self.source_sha256=file_hash(self.source)
        self.token=uuid4().hex;self.directory=Path(root).resolve()/('capture-'+self.token)
        self.directory.mkdir(parents=True);self.attempt=0;self.evidence=incomplete('Translation response not captured')
        self.batch_id=str(Path(root).resolve());self.page_id=self.source.name
        self.page_session_id=uuid4().hex
        self.evidence['source_sha256']=self.source_sha256
    def before_translation(self):
        # Drop prior attempt before reading, including when the DOM read fails.
        self.evidence=incomplete('No completed translation for current attempt');self.attempt+=1
        return read_snapshot(self.page)
    def after_translation(self,before,prompt):
        a=b=None
        try:
            a=read_snapshot(self.page);b=read_snapshot(self.page)
            if a!=b:self.evidence=incomplete('Response changed during capture')
            else:self.evidence=extract_translation(before,a,expected_prompt=prompt,complete=True)
        except Exception as exc:self.evidence=incomplete('DOM capture unavailable: '+type(exc).__name__)
        audit={'version':'capture-audit-v1','before':before,'after':a,'stable_after':b,
               'expected_prompt':prompt,'page_session_id':self.page_session_id,
               'capture_token':self.token,'attempt':self.attempt,'batch_id':self.batch_id,'page_id':self.page_id,
               'source_path':str(self.source),'source_sha256':self.source_sha256,
               'origin':'worker_dom_capture_unattested','completion_basis':'existing_worker_wait_and_two_equal_snapshots'}
        self.evidence['capture_audit']=audit
        self.evidence['capture_audit_sha256']=digest(audit)
        self.evidence.update(capture_token=self.token,source_path=str(self.source),source_sha256=self.source_sha256,
                             captured_at=datetime.now(timezone.utc).isoformat(),attempt=self.attempt)
        with (self.directory/f'translation-attempt-{self.attempt}.json').open('x',encoding='utf8') as f:
            json.dump(self.evidence,f,ensure_ascii=False,indent=2)
    def finalize(self,source,generated,layout_report=None):
        from layout_dataset import build_dataset, write_dataset
        if Path(source).resolve()!=self.source or file_hash(source)!=self.source_sha256:
            raise ValueError('Source changed; refuse text/image association')
        evidence=dict(self.evidence)
        evidence.update(capture_token=self.token,source_sha256=self.source_sha256,generated_sha256=file_hash(generated),
                        association='same_page_worker_capture_session',generated_path=str(Path(generated).resolve()),
                        batch_id=self.batch_id,page_id=self.page_id,page_session_id=self.page_session_id)
        region_qc=None
        if layout_report and layout_report.get('source_sha256')==self.source_sha256 and layout_report.get('original_sha256')==evidence['generated_sha256']:
            region_qc=layout_report.get('region_qc')
        dataset=build_dataset(source,generated,evidence=evidence,region_qc=region_qc,
                              metadata={'pairing_method':'worker','pairing_basis':'source_used_for_this_download','capture_token':self.token})
        return write_dataset(dataset,self.directory/'dataset',export_crops=True)


def _notice(stage,exc):
    try:print(f'[evidence] EVIDENCE_INCOMPLETE: {stage} ({type(exc).__name__}); batch continues')
    except Exception:pass


def begin_safely(page,source,root):
    _ACTIVE.set(None)
    try:
        session=CaptureSession(page,source,root);_ACTIVE.set(session);return session
    except Exception as exc:
        _notice('capture initialization failed',exc);return None


def checkpoint_safely(page):
    s=_ACTIVE.get()
    if not s or s.page is not page:return None
    try:return s.before_translation()
    except Exception:
        s.evidence=incomplete('Translation baseline unavailable');return None


def capture_safely(page,before,prompt):
    s=_ACTIVE.get()
    if s and s.page is page:
        try:s.after_translation(before,prompt)
        except Exception as exc:
            s.evidence=incomplete('Evidence could not be persisted');_notice('response persistence failed',exc)


def finalize_safely(session,source,generated,layout_report=None):
    try:return session.finalize(source,generated,layout_report) if session else None
    except Exception as exc:
        _notice('dataset persistence failed',exc);return None
    finally:
        if _ACTIVE.get() is session:_ACTIVE.set(None)


def audit_fallback(audit, *, evidence=None, corroboration=None):
    """Offline candidate only. Never supplies IDs or promotes worker evidence.

    Snapshot consistency, content hashes and session tokens are local evidence,
    not independent proof of provider origin. Corroboration is a separately
    persisted UI observation, still requiring independent review.
    """
    result = {'status': 'CAPTURE_UNVERIFIED', 'association_status': 'ASSOCIATION_UNVERIFIED',
              'verified': False, 'confidence_level': 'INSUFFICIENT', 'checks': {},
              'reasons': [], 'candidate': None,
              'limitations': ['No provider user ID is synthesized.',
                             'DOM order is not verified reading order.',
                             'Hashes/tokens establish local consistency, not live origin.',
                             'No image-generation/download association is inferred.']}
    checks = result['checks']
    if not isinstance(audit, dict):
        result['reasons'].append('Missing capture audit')
        return result
    before, after = audit.get('before'), audit.get('after')
    def usable(s):
        if not isinstance(s, dict) or s.get('generating') is not False:
            return False
        if not re.fullmatch(r'https://(?:chatgpt\.com|chat\.openai\.com)/c/[A-Za-z0-9_-]+', str(s.get('conversation_url', ''))):
            return False
        rows = s.get('messages')
        if not isinstance(rows, list) or not 0 < len(rows) <= 200:
            return False
        ids = []
        for row in rows:
            if (not isinstance(row, dict) or row.get('role') not in ('user', 'assistant')
                or not isinstance(row.get('text'), str) or row.get('unsupported')):
                return False
            ident = row.get('id')
            if ident is not None and (not isinstance(ident, str) or not ident
                                     or ident.startswith('fallback-turn-')):
                return False
            if row['role'] == 'assistant' and not ident:
                return False
            if ident:
                ids.append(ident)
        return len(ids) == len(set(ids))
    checks['usable_snapshots_missing_user_ids_only'] = usable(before) and usable(after)
    checks['stable_after'] = isinstance(after, dict) and after == audit.get('stable_after')
    checks['session_boundary'] = (audit.get('origin') == 'worker_dom_capture_unattested'
        and audit.get('completion_basis') == 'existing_worker_wait_and_two_equal_snapshots'
        and type(audit.get('attempt')) is int and audit['attempt'] > 0
        and all(isinstance(audit.get(k), str) and bool(audit[k]) for k in
                ('capture_token', 'page_session_id', 'batch_id', 'page_id', 'source_path', 'source_sha256')))
    if evidence is not None:
        checks['persisted_audit_binding'] = (evidence.get('capture_audit_sha256') == digest(audit)
            and all(evidence.get(k) == audit.get(k) for k in
                    ('capture_token', 'page_session_id', 'batch_id', 'page_id', 'source_path', 'source_sha256', 'attempt')))
    if not checks['usable_snapshots_missing_user_ids_only']:
        result['reasons'].append('Unsupported snapshot beyond missing user IDs or unfinished response')
        return result
    checks['same_conversation'] = before['conversation_url'] == after['conversation_url']
    old, new = before['messages'], after['messages']
    checks['exact_new_pair'] = len(new) == len(old) + 2
    checks['immutable_baseline'] = new[:len(old)] == old
    user, response = new[-2:]
    checks['exact_translation_prompt'] = (user['role'] == 'user'
        and user['text'] == audit.get('expected_prompt') == 'dịch bản chép lại'
        and response['role'] == 'assistant' and bool(response['text'].strip()))
    checks['new_assistant_identity_and_payload'] = (response.get('id') is not None
        and response['id'] not in {r.get('id') for r in old}
        and not any(r['role'] == 'assistant' and
                    (r['text'] == response['text'] or digest(r) == digest(response)) for r in old))
    if not all(checks.values()):
        result['reasons'].extend(k for k, passed in checks.items() if not passed)
        return result
    result.update(status='CAPTURE_CANDIDATE_UNVERIFIED', confidence_level='BOUNDED_DOM_CANDIDATE')
    result['candidate'] = {'conversation_url': after['conversation_url'],
        'user_message_id': user.get('id'), 'assistant_message_id': response['id'],
        'prompt_exact': user['text'], 'dom_turn_index': len(old),
        'text': response['text'], 'html': response.get('html'),
        'formulas': [dict(f) for f in response.get('formulas', [])],
        'text_sha256': hashlib.sha256(response['text'].encode('utf8')).hexdigest(),
        'snapshot_before_sha256': digest(before), 'snapshot_after_sha256': digest(after),
        'response_payload_sha256': digest(response), 'capture_token': audit['capture_token']}
    if isinstance(corroboration, dict):
        rows = corroboration.get('messages', [])
        matches = [i for i, r in enumerate(rows) if isinstance(r, dict)
                   and r.get('selection_id') == response['id']]
        observed_html = rows[matches[0]].get('content_html') if len(matches) == 1 else None
        captured_tree = structured_math(response.get('html'), formulas=response.get('formulas', []))
        observed_tree = structured_math(observed_html, formulas=response.get('formulas', []))
        same_content = (captured_tree['status'] == observed_tree['status'] == 'AUXILIARY_UNVERIFIED'
                        and math_dom_signature(captured_tree) == math_dom_signature(observed_tree))
        corroborated = (corroboration.get('conversation_url') == after['conversation_url']
            and len(matches) == 1 and matches[0] > 0
            and rows[matches[0]-1].get('text') == user['text']
            and same_content)
        checks['separate_ui_observation'] = corroborated
        if corroborated:
            result['confidence_level'] = 'CORROBORATED_DOM_CANDIDATE'
        else:
            result.update(status='CAPTURE_UNVERIFIED', confidence_level='CONFLICTING_OBSERVATION', candidate=None)
            result['reasons'].append('Separate UI observation conflicts or lacks exact text/math payload and prompt')
    return result


def structured_math(html, *, formulas=()):
    """Auxiliary DOM tree, never a replacement text or semantic math inventory."""
    from html.parser import HTMLParser
    class Node:
        def __init__(self, tag, attrs, start):
            self.tag, self.attrs, self.start = tag, dict(attrs), start
            self.end = start; self.children = []
    class Tree(HTMLParser):
        VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
        def __init__(self, raw):
            super().__init__(convert_charrefs=True)
            self.raw = raw; self.lines = [0]
            for i, c in enumerate(raw):
                if c == '\n': self.lines.append(i+1)
            self.root = Node('root', [], 0); self.stack = [self.root]; self.errors = []
        def source_offset(self):
            line, col = self.getpos(); return self.lines[line-1] + col
        def handle_starttag(self, tag, attrs):
            n = Node(tag, attrs, self.source_offset()); n.end = n.start + len(self.get_starttag_text())
            self.stack[-1].children.append(n)
            if tag not in self.VOID: self.stack.append(n)
        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            if tag not in self.VOID: self.stack.pop()
        def handle_endtag(self, tag):
            if len(self.stack) < 2 or self.stack[-1].tag != tag:
                self.errors.append('Unbalanced HTML tag: '+tag); return
            n = self.stack.pop(); n.end = self.raw.find('>', self.source_offset())+1
        def handle_data(self, data): self.stack[-1].children.append(data)
    result = {'version': 'auxiliary-math-dom-v1', 'status': 'EVIDENCE_INCOMPLETE',
              'verified': False, 'reading_order_verified': False, 'eligible_for_final_page': False,
              'nodes': [], 'errors': [], 'original_formulas': [dict(f) for f in formulas],
              'scope': 'DOM order only; single exact LaTeX spelling does not verify formula correctness'}
    if not isinstance(html, str) or len(html) > 2000000:
        result['errors'].append('Missing or oversized HTML'); return result
    tree = Tree(html); tree.feed(html); tree.close()
    if len(tree.stack) != 1: tree.errors.append('Unclosed HTML elements')
    result['errors'] = tree.errors
    def classes(n): return set((n.attrs.get('class') or '').split())
    def math_root(n):
        return (n.attrs.get('data-d-component') == 'math' or 'data-tex' in n.attrs
                or bool(classes(n) & {'katex', 'katex-display', 'katex-mathml'}) or n.tag == 'math')
    def descendants(n):
        yield n
        for c in n.children:
            if isinstance(c, Node): yield from descendants(c)
    def text(n): return ''.join(c if isinstance(c, str) else text(c) for c in n.children)
    observed = []
    def walk(n, path):
        if isinstance(n, str):
            if n: result['nodes'].append({'kind': 'text', 'dom_path': path, 'text': n})
            return
        if math_root(n):
            representations = []
            for c in descendants(n):
                if 'data-tex' in c.attrs:
                    representations.append({'representation': 'data-tex', 'raw': c.attrs['data-tex']})
                if c.tag == 'annotation' and c.attrs.get('encoding') == 'application/x-tex':
                    representations.append({'representation': 'latex_annotation', 'raw': text(c)})
            observed.extend(representations)
            unique = list(dict.fromkeys(r['raw'] for r in representations if isinstance(r['raw'], str) and r['raw'].strip()))
            multiple_roots = sum('katex' in classes(c) for c in descendants(n)) > 1
            single = len(unique) == 1 and not multiple_roots and not tree.errors
            result['nodes'].append({'kind': 'math', 'dom_path': path, 'raw_dom_text': text(n),
                'raw_html': html[n.start:n.end], 'representations': representations,
                'status': 'SINGLE_REPRESENTATION_UNVERIFIED' if single else 'AMBIGUOUS',
                'latex_candidate': unique[0] if single else None, 'verified': False})
            return
        for i, c in enumerate(n.children): walk(c, path+[i])
    walk(tree.root, [])
    for i, n in enumerate(result['nodes']): n['dom_order'] = i
    result['html_sha256'] = hashlib.sha256(html.encode('utf8')).hexdigest()
    result['formula_inventory_preserved'] = observed == list(formulas)
    maths = [n for n in result['nodes'] if n['kind'] == 'math']
    result['math_nodes'] = len(maths)
    result['ambiguous_math_nodes'] = sum(n['status'] == 'AMBIGUOUS' for n in maths)
    result['status'] = 'AUXILIARY_UNVERIFIED' if not tree.errors and result['formula_inventory_preserved'] else 'EVIDENCE_INCOMPLETE'
    return result


def math_dom_signature(structure):
    """Compare exact text/math sequence across stream-word wrapper changes.

    Only adjacent text node boundaries are joined. No whitespace/symbol/LaTeX
    normalization and no inferred reading order; raw HTML remains untouched.
    """
    sequence = ['']
    for node in structure['nodes']:
        if node['kind'] == 'text':
            sequence[-1] += node['text']
        else:
            sequence.extend([node['representations'], ''])
    return sequence

# TASK 2I: metadata only, opt-in. URLs are used in-memory solely to match the
# existing downloader's selected resource; signed URLs are never persisted.
IDENTITY_JS = r'''({selectedUrl}) => {
 const selector='[data-message-author-role], [data-content-search-unit-key$=":user"], [data-content-search-unit-key$=":assistant"], [data-chatgpt-search-unit-key$=":user"], [data-chatgpt-search-unit-key$=":assistant"]';
 const all=Array.from(document.querySelectorAll(selector));
 const roots=all.filter(n=>!all.some(p=>p!==n && p.contains(n)));
 if(roots.length>200) return {status:'LIMIT_EXCEEDED',messages:[]};
 const allowed=['data-message-id','data-chatgpt-selection-message-id','data-dil-message-id','data-dil-source-message-id','data-parent-message-id','data-parent-id','data-turn-id','data-message-author-role','data-turn','data-content-search-unit-key','data-chatgpt-search-unit-key','id'];
 const identNames=['data-message-id','data-chatgpt-selection-message-id','data-dil-message-id','data-dil-source-message-id'];
 const safe=v=>typeof v==='string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(v);
 const attrs=n=>Object.fromEntries(allowed.filter(k=>safe(n.getAttribute(k))).map(k=>[k,n.getAttribute(k)]));
 const statusId=(records,names)=>{
   const values=[...new Set(records.flatMap(r=>names.map(k=>r.attributes[k]).filter(v=>v && !v.startsWith('fallback-turn-'))))];
   return {status:values.length===1?'OBSERVED':values.length?'AMBIGUOUS':'NOT_OBSERVED',value:values.length===1?values[0]:null,candidates:values};
 };
 const messages=roots.map((n,i)=>{
   const key=n.getAttribute('data-content-search-unit-key')||n.getAttribute('data-chatgpt-search-unit-key')||'';
   const role=n.getAttribute('data-message-author-role')||(['user','assistant'].includes(n.getAttribute('data-turn'))?n.getAttribute('data-turn'):key.split(':').pop());
   const records=[{scope:'root',attributes:attrs(n)}];
   let p=n.parentElement;
   for(let depth=1;p && depth<=3;depth++,p=p.parentElement){
     if(roots.some(r=>r!==n && p.contains(r))) break;
     const a=attrs(p); if(Object.keys(a).length) records.push({scope:'ancestor',depth,attributes:a});
   }
   const descendants=Array.from(n.querySelectorAll(allowed.map(k=>'['+k+']').join(',')));
   descendants.slice(0,24).forEach(d=>{const a=attrs(d);if(Object.keys(a).length)records.push({scope:'descendant',attributes:a});});
   const images=Array.from(n.querySelectorAll('img')).slice(0,12).map(img=>{
     const assetRecords=[];
     let q=img;
     for(let depth=0;q && n.contains(q) && depth<=3;depth++,q=q.parentElement){
       const a={};['data-asset-id','data-image-id','data-file-id'].forEach(k=>{if(safe(q.getAttribute(k))) a[k]=q.getAttribute(k);});
       if(Object.keys(a).length)assetRecords.push({scope:depth?'ancestor':'image',depth,attributes:a});
     }
     return {asset_identity:statusId(assetRecords,['data-asset-id','data-image-id','data-file-id']),
             selected_resource:!!selectedUrl && (img.currentSrc===selectedUrl || img.getAttribute('src')===selectedUrl),
             response_identity:statusId(records,identNames),records:assetRecords};
   });
   return {dom_order:i,role:['user','assistant'].includes(role)?role:'NOT_OBSERVED',identity:statusId(records,identNames),
           parent_identity:statusId(records,['data-parent-message-id','data-parent-id']),
           turn_identity:statusId(records,['data-turn-id']),container_identity:statusId(records,['id']),
           positional_key:safe(key)?key:null,records,images,
           metadata_truncated:descendants.length>24 || n.querySelectorAll('img').length>12};
 });
 const generating=Array.from(document.querySelectorAll('button[data-testid="stop-button"],button[aria-label="Stop generating" i],button[aria-label="Stop streaming" i],button[aria-label="Dừng tạo" i],button[aria-label="Dừng phản hồi" i]')).some(n=>n.getClientRects().length);
 const conversation=location.origin+location.pathname;
 return {status:'OBSERVED',conversation_url:/^https:\/\/(chatgpt\.com|chat\.openai\.com)\/c\/[A-Za-z0-9_-]+$/.test(conversation)?conversation:'NOT_OBSERVED',generating,messages};
}'''

PROVENANCE_PHASES = ('translation_before_send', 'translation_sent', 'translation_complete',
                     'generation_before_send', 'generation_sent', 'generation_complete', 'download_complete')


def provenance_enabled():
    import os
    return os.environ.get('BATCH_PROVENANCE_EVENTS') == '1'


def record_provenance(session, phase, *, prompt=None, asset_url=None, downloaded=None):
    """Bounded local sidecar events; every conclusion remains unverified.

    CaptureSession owns the page/source/session. This adds no workflow state,
    timers, network hooks, retries or account changes.
    """
    if phase not in PROVENANCE_PHASES:
        raise ValueError('Unknown provenance phase')
    if prompt is not None and prompt not in ('dịch bản chép lại', 'Tạo ảnh với bản dịch'):
        raise ValueError('Only the two existing provenance prompts may be persisted')
    count = getattr(session, '_provenance_count', 0)
    total = getattr(session, '_provenance_bytes', 0)
    if count >= 64 or total >= 4*1024*1024:
        return None
    if phase == 'translation_before_send':
        session._translation_attempt_token = uuid4().hex
        session._generation_attempt_token = None
    if phase == 'generation_before_send':
        session._generation_attempt_token = uuid4().hex
    token = getattr(session, '_translation_attempt_token', None)
    generation = getattr(session, '_generation_attempt_token', None)
    timestamp = datetime.now(timezone.utc).isoformat()
    snapshot = session.page.evaluate(IDENTITY_JS, {'selectedUrl': asset_url})
    # Allowlisting occurs again on the Python boundary: an unexpected evaluator
    # result cannot persist arbitrary DOM fields or credentials.
    snapshot = sanitize_identity_snapshot(snapshot)
    event = {'version': 'provenance-events-v1', 'sequence': count, 'phase': phase,
        'event_timestamp': timestamp, 'capture_token': session.token,
        'page_session_id': session.page_session_id, 'batch_id': session.batch_id,
        'page_id': session.page_id, 'source_path': str(session.source),
        'source_sha256': session.source_sha256,
        'translation_attempt_token': token or 'NOT_OBSERVED',
        'generation_attempt_token': generation or 'NOT_OBSERVED',
        'conversation_url': snapshot['conversation_url'], 'snapshot': snapshot,
        'snapshot_reference': 'provenance-events.jsonl#'+str(count), 'snapshot_sha256': digest(snapshot),
        'status': 'OBSERVED_UNVERIFIED', 'verified': False,
        'completion_basis': 'existing_worker_wait_returned' if phase.endswith('_complete') else 'existing_send_hook',
        'previous_event_sha256': getattr(session, '_previous_event_sha256', None)}
    if phase == 'translation_complete':
        reference = session.directory / f'translation-attempt-{session.attempt}.json'
        audit = session.evidence.get('capture_audit') or {}
        event['translation_capture'] = {'reference': reference.name if reference.is_file() else 'NOT_OBSERVED',
            'sha256': file_hash(reference) if reference.is_file() else 'NOT_OBSERVED',
            'capture_audit_sha256': session.evidence.get('capture_audit_sha256', 'NOT_OBSERVED')}
    if prompt:
        event.update(prompt=prompt, prompt_sha256=hashlib.sha256(prompt.encode('utf8')).hexdigest())
    if asset_url:
        # This is a resource locator digest, NOT an observed provider asset ID.
        event['selected_resource_sha256'] = hashlib.sha256(asset_url.encode('utf8')).hexdigest()
        event['resource_digest_scope'] = 'Local URL equality only; not stable provider asset identity'
    if downloaded is not None:
        event['download'] = {'path': str(Path(downloaded).resolve()), 'sha256': file_hash(downloaded),
                             'basis': 'existing_downloader_saved_selected_resource'}
    event['event_sha256'] = digest(event)
    line = json.dumps(event, ensure_ascii=False, separators=(',', ':'))+'\n'
    size = len(line.encode('utf8'))
    if size > 256*1024 or total+size > 4*1024*1024:
        return None
    with (session.directory/'provenance-events.jsonl').open('a', encoding='utf8') as f:
        f.write(line)
    session._provenance_count = count+1
    session._provenance_bytes = total+size
    session._previous_event_sha256 = event['event_sha256']
    return event


def sanitize_identity_snapshot(snapshot):
    """No HTML/text/URL/auth material is permitted in metadata event logs."""
    allowed = {'data-message-id','data-chatgpt-selection-message-id','data-dil-message-id',
               'data-dil-source-message-id','data-parent-message-id','data-parent-id','data-turn-id',
               'data-message-author-role','data-turn','data-content-search-unit-key','data-chatgpt-search-unit-key',
               'id','data-asset-id','data-image-id','data-file-id'}
    def safe(value):
        return isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',value) is not None
    def identity(value):
        value = value if isinstance(value,dict) else {}
        candidates = [v for v in value.get('candidates',[]) if safe(v) and not v.startswith('fallback-turn-')][:24]
        status = value.get('status')
        if status not in ('OBSERVED','AMBIGUOUS','NOT_OBSERVED'): status='NOT_OBSERVED'
        valid = status=='OBSERVED' and safe(value.get('value')) and candidates==[value['value']]
        return {'status':status if valid or status=='AMBIGUOUS' else 'NOT_OBSERVED',
                'value':value['value'] if valid else None,'candidates':candidates}
    def records(rows):
        return [{'scope':r.get('scope') if r.get('scope') in ('root','ancestor','descendant','image') else 'NOT_OBSERVED',
                 'attributes':{k:v for k,v in r.get('attributes',{}).items() if k in allowed and safe(v)}}
                for r in rows[:28] if isinstance(r,dict)]
    if not isinstance(snapshot,dict): raise ValueError('Invalid metadata snapshot')
    url=snapshot.get('conversation_url')
    if not isinstance(url,str) or not re.fullmatch(r'https://(?:chatgpt\.com|chat\.openai\.com)/c/[A-Za-z0-9_-]+',url):url='NOT_OBSERVED'
    rows=snapshot.get('messages',[])
    if not isinstance(rows,list) or len(rows)>200:raise ValueError('Metadata message limit')
    messages=[]
    for i,r in enumerate(rows):
        if not isinstance(r,dict):raise ValueError('Invalid message metadata')
        m={'dom_order':i,'role':r.get('role') if r.get('role') in ('user','assistant') else 'NOT_OBSERVED',
           'positional_key':r.get('positional_key') if safe(r.get('positional_key')) else None,
           'records':records(r.get('records',[])), 'metadata_truncated':r.get('metadata_truncated') is True,
           'images':[]}
        for k in ('identity','parent_identity','turn_identity','container_identity'):m[k]=identity(r.get(k))
        for image in r.get('images',[])[:12]:
            m['images'].append({'asset_identity':identity(image.get('asset_identity')),
                'response_identity':identity(image.get('response_identity')),
                'selected_resource':image.get('selected_resource') is True,'records':records(image.get('records',[]))})
        messages.append(m)
    return {'status':snapshot.get('status') if snapshot.get('status') in ('OBSERVED','LIMIT_EXCEEDED') else 'NOT_OBSERVED',
            'conversation_url':url,'generating':snapshot.get('generating') if type(snapshot.get('generating')) is bool else 'NOT_OBSERVED',
            'messages':messages}


def observe_safely(page, phase, **kwargs):
    """No reads/writes when OFF; optional errors never propagate to workers."""
    if not provenance_enabled():return None
    session = _ACTIVE.get()
    if session is None or session.page is not page:return None
    try:return record_provenance(session, phase, **kwargs)
    except Exception as exc:
        _notice('provenance '+phase+' unavailable', exc)
        return None
