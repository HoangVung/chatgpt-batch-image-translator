"""Composer inspection/actions used only by the isolated ChatGPT worker.

Diagnostics contain structural counts/flags only, never page text, URLs or HTML.
"""
import json
import time
import uuid
from pathlib import Path

EDITORS = '#prompt-textarea, .ql-editor[contenteditable="true"], rich-textarea [contenteditable="true"], .ProseMirror[contenteditable="true"], [role="textbox"][contenteditable="true"], div[contenteditable="true"]'
PROBE = r"""() => {
 const visible = el => {
   const r=el.getBoundingClientRect(), s=getComputedStyle(el);
   return r.width>0 && r.height>0 && s.display!=='none' && !['hidden','collapse'].includes(s.visibility);
 };
 const outside='nav,aside,[role="navigation"],[data-testid^="conversation-turn"],[data-message-author-role],[data-turn="user"],[data-turn="assistant"],[data-content-search-turn-key],[data-content-search-unit-key],user-query,model-response';
 const selector='#prompt-textarea, .ql-editor[contenteditable="true"], rich-textarea [contenteditable="true"], .ProseMirror[contenteditable="true"], [role="textbox"][contenteditable="true"], div[contenteditable="true"]';
 const editors=Array.from(document.querySelectorAll(selector));
 const editable=el => !el.matches(':disabled') && !el.readOnly && !el.closest('[aria-disabled="true"],[inert]') && getComputedStyle(el).pointerEvents!=='none' && (el.isContentEditable || el.matches('textarea,input'));
 const rank=el => el.id==='prompt-textarea'?0:el.matches('.ql-editor')?1:el.closest('rich-textarea')?2:3;
 const candidates=editors.filter(el=>visible(el)&&!el.closest(outside)).sort((a,b)=>rank(a)-rank(b));
 const editor=candidates.find(editable), anchor=editor || candidates[0];
 let root=null;
 if(anchor){
   const boundary=anchor.closest('form,.input-area-container,#composer-background,[data-testid="composer"],[data-type="unified-composer"]');
   if(boundary && !boundary.querySelector(outside)) root=boundary;
   else for(let el=anchor.parentElement;el && el!==document.body && el!==document.documentElement;el=el.parentElement){
     if(el.matches('main,[role="main"]') || el.matches(outside) || el.querySelector(outside)) break;
     root=el;
   }
 }
 const attachmentSelector='[data-testid*="attachment"],.composer-attachment-surface,[data-testid*="upload"]';
 const attachments=root?Array.from(root.querySelectorAll('img')).filter(img=>{
   if(!visible(img)||img.closest(outside))return false;
   const r=img.getBoundingClientRect(), src=img.currentSrc||img.getAttribute('src')||'';
   const icon=!src.startsWith('data:')&&!src.startsWith('blob:')&&/avatar|emoji|icon/i.test(src);
   return r.width>40&&r.height>40&&img.complete&&img.naturalWidth>0&&!icon&&!src.startsWith('data:image/svg');
 }):[];
 const uploadNodes=root?Array.from(root.querySelectorAll(attachmentSelector)):[];
 const uploading=uploadNodes.some(el=>visible(el)&&(el.matches('[aria-busy="true"],[role="progressbar"]')||Array.from(el.querySelectorAll('[role="progressbar"],[aria-busy="true"]')).some(visible))) || !!(root && Array.from(root.querySelectorAll('[role="progressbar"]')).some(visible));
 const uploadError=uploadNodes.some(el=>visible(el)&&Array.from(el.querySelectorAll('[role="alert"],[data-testid*="error"]')).some(visible));
 const generationSelector='button[data-testid="stop-button"],button[aria-label="Stop generating" i],button[aria-label="Stop streaming" i],button[aria-label="Stop response" i],button[aria-label="Dừng tạo" i],button[aria-label="Dừng phản hồi" i]';
 const generating=Array.from(document.querySelectorAll(generationSelector)).some(el=>visible(el)&&!el.closest('nav,aside,[role="dialog"],'+attachmentSelector));
 const files=Array.from(document.querySelectorAll('input[type="file"]'));
 const eligible=files.filter(el=>!el.disabled&&!el.closest(outside)&&((root&&root.contains(el))||el.id==='upload-files'));
 let reason=!root?'composer_missing':!editor?'editor_disabled':uploadError?'upload_error':uploading?'uploading':generating?'generating':'ready';
 return {editor_index:editor?editors.indexOf(editor):-1, root, editor,
   file_indices:eligible.map(el=>files.indexOf(el)),
   state:{reason,editor_count:candidates.length,editable:!!editor,composer_found:!!root,attachment_count:attachments.length,uploading,upload_error:uploadError,generating}};
}"""


def inspect(page):
    return page.evaluate('(' + PROBE + ')().state')


def editor(page):
    index = page.evaluate('(' + PROBE + ')().editor_index')
    return page.locator(EDITORS).nth(index) if index >= 0 else page.locator(':not(*)')


def upload(page, image):
    indices = page.evaluate('(' + PROBE + ')().file_indices')
    if not indices:
        raise RuntimeError('Không thấy input tải ảnh thuộc composer hiện tại')
    errors = []
    for index in indices:
        try:
            page.locator('input[type="file"]').nth(index).set_input_files(str(image), timeout=8000)
            print('✓ Upload qua input của composer hiện tại')
            return
        except Exception as exc:
            errors.append(type(exc).__name__)
    raise RuntimeError('Không upload được ảnh: ' + ', '.join(errors))


def diagnostic(page, directory, phase, reason):
    try:
        state = inspect(page)
    except Exception:
        state = {'reason': 'probe_failed'}
    payload = {'version': 1, 'phase': phase, 'reason': reason, 'composer': state}
    print('⚠ Composer: ' + json.dumps(payload, ensure_ascii=False))
    try:
        folder = Path(directory) / 'composer-diagnostics'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (str(time.time_ns()) + '-' + uuid.uuid4().hex[:8] + '.json')).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    except OSError:
        print('⚠ Không ghi được chẩn đoán composer')


def click_send(page):
    # Scope the submit action to the same freshly resolved composer.
    root = page.evaluate_handle('(' + PROBE + ')().root').as_element()
    if root is None:
        return False
    selectors = ('button[data-testid="send-button"],button[aria-label="Send message"],'
                 'button[aria-label="Gửi tin nhắn"],button[aria-label="Submit message"],'
                 'button[aria-label="Send prompt"],button[aria-label="Send"],button.send-button')
    for button in root.query_selector_all(selectors):
        if button.is_visible() and button.is_enabled():
            button.click(timeout=4000)
            return True
    return False
