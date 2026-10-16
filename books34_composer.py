"""Composer inspection/actions used only by the isolated ChatGPT worker.

Diagnostics contain structural counts/flags only, never page text, URLs or HTML.
"""
import json
import time
import uuid
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from worker_control import check_stop_requested

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
 const form=anchor && anchor.closest('form');
 let uploadRoot=form && !form.querySelector(outside)?form:root;
 // A picker may sit beside the form, but an ordinary page wrapper is not
 // evidence of ownership. Only adopt an explicitly marked composer ancestor.
 for(let parent=uploadRoot?.parentElement;parent;parent=parent.parentElement){
   if(parent.matches('body,html,main,[role="main"],'+outside) || parent.querySelector(outside) ||
      Array.from(parent.querySelectorAll(selector)).some(el=>el!==anchor && visible(el)) ||
      Array.from(parent.querySelectorAll('form')).some(el=>el!==form)) break;
   if(parent.matches('#composer-background,[data-testid="composer"],[data-testid="composer-container"],[data-type="unified-composer"],[class*="ComposerLayoutRoot-"]')) uploadRoot=parent;
 }
 const controls=uploadRoot?Array.from(uploadRoot.querySelectorAll('[aria-controls]')):[];
 const eligible=files.filter(el=>editor && root && !el.matches(':disabled,[capture],[webkitdirectory],[directory]') && !el.closest('[inert],[aria-disabled="true"],'+outside) &&
   el.closest('[role="dialog"]')===editor.closest('[role="dialog"]') && (
     uploadRoot.contains(el) || (form && el.form===form) ||
     Array.from(el.labels||[]).some(label=>uploadRoot.contains(label)) ||
     controls.some(control=>(control.getAttribute('aria-controls')||'').split(/\s+/).some(id=>{
       const target=document.getElementById(id); return target && (target===el || target.contains(el));
     })) || (el.id==='upload-files' && (!el.form || el.form===form))));
 let reason=!root?'composer_missing':!editor?'editor_disabled':uploadError?'upload_error':uploading?'uploading':generating?'generating':'ready';
 return {editor_index:editor?editors.indexOf(editor):-1, root, editor, upload_root:uploadRoot, files:eligible,
   file_indices:eligible.map(el=>files.indexOf(el)),
   state:{reason,editor_count:candidates.length,editable:!!editor,composer_found:!!root,attachment_count:attachments.length,uploading,upload_error:uploadError,generating,file_input_count:files.length,composer_file_input_count:eligible.length}};
}"""


def inspect(page):
    return page.evaluate('(' + PROBE + ')().state')


def editor(page):
    index = page.evaluate('(' + PROBE + ')().editor_index')
    return page.locator(EDITORS).nth(index) if index >= 0 else page.locator(':not(*)')


class UploadQuotaError(RuntimeError):
    """An explicit provider notice prevents this account from uploading."""

    def __init__(self, evidence, detected_at=None):
        self.evidence = str(evidence or '').strip()
        self.detected_at = time.time() if detected_at is None else detected_at
        super().__init__('Tài khoản ChatGPT đã hết lượt tải tệp lên')


UPLOAD_QUOTA = r"""menu => {
 const probe=(PROBE)();
 const outside='nav,aside,[role="navigation"],[data-testid^="conversation-turn"],[data-message-author-role],[data-turn="user"],[data-turn="assistant"],[data-content-search-turn-key],[data-content-search-unit-key],user-query,model-response';
 const excluded=outside+',script,style,svg,kbd,[contenteditable],textarea,input,[aria-hidden="true"]';
 const visible=el=>{
   const r=el.getBoundingClientRect(), s=getComputedStyle(el);
   return r.width>0 && r.height>0 && s.display!=='none' && !['hidden','collapse'].includes(s.visibility);
 };
 // Read only the active composer, its selected attachment menu, or a visible
 // alert. A historical answer or another open menu is never quota evidence.
 const root=probe.upload_root || probe.root;
 const sources=[root,menu,...document.querySelectorAll('[role="alert"]')].filter(el=>
   el && visible(el) && !el.closest(excluded) &&
   (el===root || el===menu || menu?.contains(el) ||
    (!el.closest('[role="menu"],[role="listbox"]') &&
     el.closest('[role="dialog"]')===(root?.closest('[role="dialog"]')||null))));
 const quota=/\bget\s+plus\s+for\s+more\s+uploads\b|\b(?:file\s+)?upload\s+limit\s+(?:reached|exceeded)\b|\b(?:reached|hit|exceeded)\b[^.!?]{0,100}\b(?:file\s+)?upload\s+limit\b|\b(?:out\s+of|no\s+more)\s+(?:file\s+)?uploads\b|\btoo\s+many\s+(?:file\s+)?uploads\b|(?:hết|đạt|vượt)[^.!?]{0,60}(?:lượt|giới hạn)[^.!?]{0,60}(?:tải|tệp|đính kèm)/i;
 const wait=/\bwait\s+\d[^.!?]{0,90}\bto\s+upload\s+again\b|(?:chờ|đợi)\s+\d[^.!?]{0,90}(?:tải lên|tải tệp|tải ảnh)[^.!?]{0,20}lại/i;
 const reset=/\b(?:wait|resets?\s+in|try\s+again\s+in)\s+\d|(?:chờ|đợi|sau)\s+\d/i;
 const evidence=[];
 for(const source of new Set(sources)){
   const texts=new Map();
   const read=el=>{
     if(el.matches(excluded) || !visible(el)) return '';
     if(el!==source && el.matches('[role="menu"],[role="listbox"],[role="dialog"]') && el!==menu) return '';
     const text=Array.from(el.childNodes).map(n=>n.nodeType===Node.TEXT_NODE?n.textContent:n.nodeType===Node.ELEMENT_NODE?read(n):'').join(' ').replace(/\s+/g,' ').trim();
     texts.set(el,text); return text;
   };
   read(source);
   const matches=Array.from(texts).filter(([,text])=>quota.test(text)||wait.test(text));
   for(const [el,text] of matches){
     if(matches.some(([child])=>child!==el && el.contains(child))) continue;
     let notice=el;
     // Keep the reset subtitle beside the quota heading, including when a
     // disabled menu item consists of several nested spans.
     for(let parent=el.parentElement;parent && source.contains(parent);parent=parent.parentElement){
       const parentText=texts.get(parent)||'';
       if(reset.test(parentText) && !parent.querySelector('button:not(:disabled):not([aria-disabled="true"]),[role="menuitem"]:not([aria-disabled="true"]):not(:disabled)')){
         notice=parent; break;
       }
       if(parent.matches('[role="menuitem"],button,[role="alert"]')) {notice=parent;break;}
       if(parent===source) break;
     }
     const value=texts.get(notice)||text;
     if(value && !evidence.includes(value)) evidence.push(value);
   }
 }
 return evidence.filter(value=>!evidence.some(other=>other!==value && other.includes(value))).join('\n');
}""".replace('(PROBE)', '(' + PROBE + ')')


def get_upload_quota_evidence(page, menu=None):
    if menu is not None:
        return page.evaluate(UPLOAD_QUOTA, menu)
    # A prior attempt can leave a modal attachment menu open and the editor
    # disabled. Its explicit composer ownership is sufficient to read it.
    owned_menu = page.evaluate_handle(OWNED_UPLOAD_MENU)
    try:
        return page.evaluate(UPLOAD_QUOTA, owned_menu)
    finally:
        owned_menu.dispose()


def _raise_upload_quota(page, menu=None):
    evidence = get_upload_quota_evidence(page, menu)
    if evidence:
        raise UploadQuotaError(evidence)


def _try_upload_input(page, image, errors, menu=None):
    # Keep the inspected elements themselves: a global nth(index) can change
    # ownership if another file input is inserted while the page hydrates.
    inputs = (page.evaluate_handle('(' + PROBE + ')().files') if menu is None else
              menu.evaluate_handle(r"""menu => Array.from(menu.querySelectorAll('input[type="file"]')).filter(el=>
                !el.matches(':disabled,[capture],[webkitdirectory],[directory]') &&
                !el.closest('[inert],[aria-disabled="true"],nav,aside,[data-message-author-role]'))"""))
    handles = []
    try:
        handles = list(inputs.get_properties().values())
        for handle in handles:
            element = handle.as_element()
            if element is None:
                continue
            try:
                element.set_input_files(str(image), timeout=2000)
                print('✓ Upload qua input của composer hiện tại')
                return True
            except Exception as exc:
                errors.add(type(exc).__name__)
        return False
    finally:
        for handle in handles:
            handle.dispose()
        inputs.dispose()


UPLOAD_TRIGGER = r"""() => {
 const root=(PROBE)().upload_root;
 if(!root) return null;
 return Array.from(root.querySelectorAll('button,[role="button"]')).find(el=>{
   const r=el.getBoundingClientRect(), s=getComputedStyle(el);
   if(!r.width || !r.height || s.visibility!=='visible' || el.matches(':disabled,[aria-disabled="true"]')) return false;
   if(el.id==='composer-plus-btn' || el.getAttribute('data-testid')==='composer-plus-btn') return true;
   const name=(el.getAttribute('aria-label')||el.textContent||'').trim();
   return /^(add (files|photos)|attach (files|photos)|upload (files|photos)|thêm (tệp|ảnh)|đính kèm|tải (tệp|ảnh) lên)/i.test(name);
 }) || null;
}""".replace('(PROBE)', '(' + PROBE + ')')

# Some attachment panels have no menu role or aria-controls. Only consider
# their explicit upload-limit rows after our own attachment action made them
# visible; pre-existing notices elsewhere are excluded by the before snapshot.
UPLOAD_NOTICE_ROWS = r"""() => {
 const excluded='nav,aside,[role="navigation"],[data-testid^="conversation-turn"],[data-message-author-role],[data-turn="user"],[data-turn="assistant"],[data-content-search-turn-key],[data-content-search-unit-key],user-query,model-response,script,style,svg,kbd,[contenteditable],textarea,input,[aria-hidden="true"]';
 const marker=/\bget\s+plus\s+for\s+more\s+uploads\b|\b(?:file\s+)?upload\s+limit\s+(?:reached|exceeded)\b|\bwait\s+\d[^.!?]{0,90}\bto\s+upload\s+again\b|(?:hết|đạt|vượt)[^.!?]{0,60}(?:lượt|giới hạn)[^.!?]{0,60}(?:tải|tệp|đính kèm)/i;
 const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.visibility==='visible'&&s.display!=='none';};
 const matches=Array.from(document.querySelectorAll('body *')).filter(el=>
   !el.closest(excluded)&&visible(el)&&marker.test(Array.from(el.childNodes).filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join(' ')));
 return [...new Set(matches.map(el=>{
   const row=el.closest('[aria-disabled="true"],button:disabled,[data-disabled]');
   const parent=el.parentElement;
   return row || (parent&&!parent.matches('body,html,main,[role="main"]')&&!parent.closest(excluded)?parent:el);
 }))];
}"""

VISIBLE_MENUS = r"""() => [...document.querySelectorAll('[role="menu"],[role="dialog"],[role="listbox"]'),...(NOTICES)()].filter(el=>{
 const r=el.getBoundingClientRect(); return r.width>0 && r.height>0 && getComputedStyle(el).visibility==='visible';
})""".replace('(NOTICES)', '(' + UPLOAD_NOTICE_ROWS + ')')

UPLOAD_MENU = r"""({before, trigger}) => {
 const controlled=(trigger.getAttribute('aria-controls')||'').split(/\s+/).map(id=>document.getElementById(id)).filter(Boolean);
 const menus=controlled.concat(Array.from(document.querySelectorAll('[role="menu"],[role="dialog"],[role="listbox"]')), (NOTICES)());
 const visible=el=>{const r=el.getBoundingClientRect();return r.width>0 && r.height>0 && getComputedStyle(el).visibility==='visible';};
 // Only the menu opened by our composer action may provide a local upload.
 return menus.find(menu=>visible(menu) && !menu.closest('nav,aside,[data-message-author-role]') &&
   (!before.includes(menu) || controlled.includes(menu))) || null;
}""".replace('(NOTICES)', '(' + UPLOAD_NOTICE_ROWS + ')')

OWNED_UPLOAD_MENU = r"""() => {
 const trigger=(TRIGGER)();
 if(!trigger) return null;
 const controlled=(trigger.getAttribute('aria-controls')||'').split(/\s+/).map(id=>document.getElementById(id)).filter(Boolean);
 return controlled.find(el=>{
   const r=el.getBoundingClientRect();
   return el.matches('[role="menu"],[role="dialog"],[role="listbox"]') &&
     !el.closest('nav,aside,[data-message-author-role]') &&
     r.width>0 && r.height>0 && getComputedStyle(el).visibility==='visible';
 }) || null;
}""".replace('(TRIGGER)', '(' + UPLOAD_TRIGGER + ')')

UPLOAD_MENU_ITEM = r"""menu => {
 const visible=el=>{const r=el.getBoundingClientRect();return r.width>0 && r.height>0 && getComputedStyle(el).visibility==='visible';};
 const label=el=>{
   if(el.getAttribute('aria-label')) return el.getAttribute('aria-label');
   const ids=(el.getAttribute('aria-labelledby')||'').split(/\s+/);
   const labelled=ids.map(id=>document.getElementById(id)?.textContent||'').join(' ').trim();
   if(labelled) return labelled;
   const copy=el.cloneNode(true);
   copy.querySelectorAll('svg,kbd,[aria-hidden="true"],[data-slot="shortcut"]').forEach(el=>el.remove());
   return copy.textContent||'';
 };
 for(const el of menu.querySelectorAll('[role="menuitem"],button,[role="button"],label')){
   const name=label(el).replace(/\s+/g,' ').trim();
   if(visible(el) && !el.matches(':disabled,[aria-disabled="true"]') &&
     /^(?:(?:add|upload|attach) (?:photos?(?:\s*(?:&|and)\s*files?)?|files?|from computer)|(?:thêm|tải lên|đính kèm) (?:ảnh(?:\s*(?:và|&)\s*tệp)?|tệp)|tải (?:ảnh|tệp)(?: và tệp)? lên)(?:\s*\([^)]*\))?(?:\s*(?:Ctrl|Control|Alt|Shift|⌘|⌥|⇧)[+\s]*[\w+⌘⌥⇧-]+)?$/i.test(name)) return el;
 }
 return null;
}"""


def _click_upload(page, element, image, *, keyboard=False):
    # Listen only around our own attach action, never while waiting for the
    # composer to hydrate (an unrelated page picker could open in that time).
    try:
        with page.expect_file_chooser(timeout=3500) as chooser:
            try:
                if keyboard:
                    element.press('Enter', timeout=2000, no_wait_after=True)
                else:
                    element.click(timeout=2000, no_wait_after=True)
            except PlaywrightTimeoutError:
                # A click can have dispatched before its completion times out.
                # Keep the chooser listener alive and inspect its effect first.
                pass
    except PlaywrightTimeoutError:
        return False  # The trigger may have opened an attachment menu instead.
    picker = chooser.value
    try:
        picker.set_files(str(image), timeout=8000)
    finally:
        picker.element.dispose()
    print('✓ Upload qua nút đính kèm của composer hiện tại')
    return True


def upload(page, image, timeout=20):
    """Resolve related inputs or open the current composer's local file picker."""
    deadline = time.monotonic() + timeout
    errors = set()
    trigger = before = None
    trigger_attempts = menu_attempts = 0
    last_action = 0
    try:
        while time.monotonic() < deadline:
            check_stop_requested()
            _raise_upload_quota(page)
            if inspect(page)['reason'] == 'ready':
                if _try_upload_input(page, image, errors):
                    return
                if trigger is None:
                    candidate = page.evaluate_handle(UPLOAD_TRIGGER)
                    if candidate.as_element() is None:
                        candidate.dispose()
                    else:
                        trigger = candidate
                        before = page.evaluate_handle(VISIBLE_MENUS)
                        trigger_attempts += 1
                        if _click_upload(page, trigger.as_element(), image):
                            return
                        last_action = time.monotonic()
            # A modal menu can temporarily disable pointer events on the
            # editor. Its upload action must remain usable in that state.
            if trigger is not None:
                menu = page.evaluate_handle(UPLOAD_MENU, {'before': before, 'trigger': trigger})
                try:
                    if menu.as_element() is not None:
                        _raise_upload_quota(page, menu)
                        if _try_upload_input(page, image, errors, menu=menu):
                            return
                        if menu_attempts < 2 and (menu_attempts == 0 or time.monotonic() - last_action >= 0.2):
                            item = menu.evaluate_handle(UPLOAD_MENU_ITEM)
                            try:
                                if item.as_element() is not None:
                                    if _click_upload(page, item.as_element(), image, keyboard=menu_attempts > 0):
                                        return
                                    menu_attempts += 1
                                    last_action = time.monotonic()
                            finally:
                                item.dispose()
                    elif trigger_attempts < 2 and time.monotonic() - last_action >= 0.5:
                        # Hydration may replace the original node or drop its
                        # first click. Resolve it again before a keyboard retry.
                        candidate = page.evaluate_handle(UPLOAD_TRIGGER)
                        if candidate.as_element() is not None:
                            trigger.dispose()
                            trigger = candidate
                            # An already-open unlabelled panel may have closed
                            # on the first click. Observe the closed state before
                            # reopening so newly visible quota rows stay attributable.
                            before.dispose()
                            before = page.evaluate_handle(VISIBLE_MENUS)
                            trigger_attempts += 1
                            if _click_upload(page, trigger.as_element(), image, keyboard=True):
                                return
                            last_action = time.monotonic()
                        else:
                            candidate.dispose()
                finally:
                    menu.dispose()
            page.wait_for_timeout(200)
        detail = ': ' + ', '.join(sorted(errors)) if errors else ''
        raise RuntimeError('Không thấy input tải ảnh thuộc composer hiện tại hoặc không mở được nút đính kèm' + detail)
    finally:
        if before is not None:
            before.dispose()
        if trigger is not None:
            trigger.dispose()


def diagnostic(page, directory, phase, reason):
    try:
        state = inspect(page)
    except Exception:
        state = {'reason': 'probe_failed'}
    payload = {'version': 2, 'phase': phase, 'reason': reason, 'composer': state}
    if phase == 'upload':
        try:
            # Structural flags only: enough to distinguish portal/menu/camera
            # pickers without collecting text, filenames, URLs, or HTML.
            payload['upload_controls'] = page.evaluate(r"""() => {
                const probe=(PROBE)();
                const trigger=(TRIGGER)();
                const files=Array.from(document.querySelectorAll('input[type="file"]'));
                const visible=el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(el).visibility==='visible';};
                return {
                    trigger_found:!!trigger,
                    trigger_expanded:trigger?.getAttribute('aria-expanded')==='true',
                    trigger_controls:!!trigger?.getAttribute('aria-controls'),
                    visible_menu_count:Array.from(document.querySelectorAll('[role="menu"]')).filter(visible).length,
                    file_inputs:files.slice(0,12).map(el=>({
                        eligible:probe.files.includes(el),disabled:el.matches(':disabled'),
                        capture:el.hasAttribute('capture'),directory:el.hasAttribute('webkitdirectory')||el.hasAttribute('directory'),
                        accepts_images:/image\/|\.(png|jpe?g|webp)/i.test(el.accept),
                        multiple:el.multiple,in_form:!!el.form,in_menu:!!el.closest('[role="menu"]'),
                        in_dialog:!!el.closest('[role="dialog"]'),in_upload_root:!!probe.upload_root?.contains(el)
                    }))
                };
            }""".replace('(PROBE)', '(' + PROBE + ')').replace('(TRIGGER)', '(' + UPLOAD_TRIGGER + ')'))
        except Exception:
            payload['upload_controls'] = {'reason': 'probe_failed'}
    if phase == 'send':
        try:
            payload['send_controls'] = page.evaluate(
                'selectors => (' + SEND_PROBE + ')(selectors).state', SEND_SELECTORS)
        except Exception:
            payload['send_controls'] = {'reason': 'probe_failed'}
    print('⚠ Composer: ' + json.dumps(payload, ensure_ascii=False))
    try:
        folder = Path(directory) / 'composer-diagnostics'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (str(time.time_ns()) + '-' + uuid.uuid4().hex[:8] + '.json')).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    except OSError:
        print('⚠ Không ghi được chẩn đoán composer')


SEND_SELECTORS = ('button[data-testid="send-button"],button[aria-label="Send message"],'
                  'button[aria-label="Gửi tin nhắn"],button[aria-label="Submit message"],'
                  'button[aria-label="Send prompt"],button[aria-label="Send"],button.send-button')

# Both readiness and clicking resolve the same concrete owned controls. The
# extra state is bounded structural evidence; it never returns page content.
SEND_PROBE = r"""selectors => {
    const probe=(PROBE)(), root=probe.upload_root || probe.root;
    const editor=probe.editor, form=editor?.closest('form');
    const outside='nav,aside,[role="navigation"],[data-testid^="conversation-turn"],[data-message-author-role],[data-turn="user"],[data-turn="assistant"],[data-content-search-turn-key],[data-content-search-unit-key],user-query,model-response';
    const matches=Array.from(document.querySelectorAll(selectors));
    const controls=matches.map(button=>{
        const inRoot=!!root?.contains(button);
        const sameDialog=!!editor && button.closest('[role="dialog"]')===editor.closest('[role="dialog"]');
        const sameForm=!button.form || button.form===form;
        const excluded=!!button.closest(outside);
        const blocked=!!button.closest('[inert],[aria-disabled="true"]');
        const disabled=button.matches(':disabled');
        const owned=!!editor && !!probe.root && inRoot && sameDialog && sameForm && !excluded;
        const r=button.getBoundingClientRect(), s=getComputedStyle(button);
        const visible=r.width>0 && r.height>0 && s.display!=='none' && !['hidden','collapse'].includes(s.visibility);
        return {button,flags:{in_root:inRoot,same_dialog:sameDialog,same_form:sameForm,
            excluded,blocked,disabled,visible,enabled:!disabled&&!blocked,owned,
            eligible:owned&&!disabled&&!blocked}};
    });
    const eligible=controls.filter(control=>control.flags.eligible);
    return {
        buttons:eligible.map(control=>control.button),
        state:{
            editor_found:!!editor,composer_found:!!probe.root,upload_root_found:!!probe.upload_root,
            root_is_form:!!root?.matches('form'),
            matched_count:matches.length,
            in_root_count:controls.filter(control=>control.flags.in_root).length,
            owned_count:controls.filter(control=>control.flags.owned).length,
            eligible_count:eligible.length,
            visible_count:controls.filter(control=>control.flags.visible).length,
            enabled_count:controls.filter(control=>control.flags.enabled).length,
            ready_count:eligible.filter(control=>control.flags.visible).length,
            controls:controls.slice(0,12).map(control=>control.flags)
        }
    };
}""".replace('(PROBE)', '(' + PROBE + ')')


def _send_control(page, *, click):
    # The send button may sit beside the inner composer or its form. Reuse
    # the probe's bounded composer ownership and retain concrete elements.
    buttons = page.evaluate_handle('selectors => (' + SEND_PROBE + ')(selectors).buttons', SEND_SELECTORS)
    handles = []
    try:
        handles = list(buttons.get_properties().values())
        for handle in handles:
            button = handle.as_element()
            if button is not None and button.is_visible() and button.is_enabled():
                if click:
                    button.click(timeout=4000)
                return True
        return False
    finally:
        for handle in handles:
            handle.dispose()
        buttons.dispose()


def send_ready(page):
    """Check for an enabled owned send control without changing the page."""
    return _send_control(page, click=False)


def click_send(page):
    return _send_control(page, click=True)
