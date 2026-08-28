r"""Injected browser-side core (``window.__p1uidCore``).

Everything the tool learns about a page is computed here, in ONE pass, inside
the browser. Rationale (spec 28): a round-trip per element would cost
milliseconds each; a single evaluate over ~1k elements costs ~50-150 ms total.

Responsibilities
  * role / accessible-name computation (ARIA + HTML-AAM subset -- Playwright
    1.61 no longer exposes an accessibility snapshot API)
  * interactive-element harvesting, incl. open shadow DOM
  * uniqueness counters used by the locator generator
  * page-structure signals used for UI-state fingerprinting
  * OBSERVATION-ONLY event listeners for training mode (never clicks anything)

Security: element *values* are never read. ``input``/``textarea`` ``.value`` is
not touched, and any element of ``type=password`` is reduced to metadata only.
"""
from __future__ import annotations

CORE_JS = r"""
(() => {
if (window.__p1uidCore && window.__p1uidCore.version === 1) return;

const NAME_MAX = 120;
const TEXT_MAX = 160;

const TESTID_ATTRS = ['data-testid','data-test-id','data-test','data-cy','data-qa','data-automation-id','data-e2e'];
const SEL = [
  'a[href]','button','input','select','textarea','summary','details','label',
  '[role]','[tabindex]','[onclick]','[contenteditable=""]','[contenteditable="true"]',
  'table','h1','h2','h3','h4','h5','h6','nav','main','dialog','form','fieldset','legend'
].concat(TESTID_ATTRS.map(a => '[' + a + ']')).join(',');

// Roles whose accessible name may come from their own content (ARIA accname step 2F).
const NAME_FROM_CONTENT = new Set(['button','link','tab','menuitem','menuitemcheckbox','menuitemradio',
  'option','treeitem','heading','cell','gridcell','columnheader','rowheader','row','listitem','switch',
  'checkbox','radio','tooltip','status','legend','summary']);

// Generated / volatile ids we must never build a locator from (spec 10).
const VOLATILE_ID = [
  /^[0-9]/, /\d{4,}/, /^:r[0-9a-z]+:$/i, /^mat-/i, /^cdk-/i, /^ember\d/i, /^react-select/i,
  /^ng-?\d/i, /^radix-/i, /^headlessui-/i, /^mui-/i, /^:\w+:/, /[0-9a-f]{8}-[0-9a-f]{4}/i,
  /^[0-9a-f]{16,}$/i, /^tooltip-\d/i, /^popup-?\d/i, /^uid-?\d/i
];

const norm = (s) => (s == null ? '' : String(s)).replace(/\s+/g, ' ').trim();
const clip = (s, n) => { s = norm(s); return s.length > n ? s.slice(0, n) : s; };

function win(el) { const d = el.ownerDocument; return (d && d.defaultView) || window; }

function isVisible(el) {
  try {
    if (el.hasAttribute('hidden') || el.getAttribute('aria-hidden') === 'true') return false;
    const st = win(el).getComputedStyle(el);
    if (!st || st.display === 'none' || st.visibility === 'hidden' || st.visibility === 'collapse') return false;
    if (parseFloat(st.opacity || '1') === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0;
  } catch (e) { return false; }
}

// Roles that describe layout or containment rather than an action. An element
// carrying one of these may still BE a control in a design system that never
// set a role - see `isPointerLeaf`.
const LAYOUT_ROLES = new Set(['cell','gridcell','listitem','row','columnheader',
  'rowheader','generic','presentation','none','']);

// How many value-labelled siblings make the neighbourhood a data row.
const VALUE_PEER_MIN = 2;

// A label that carries a value instead of naming a control.
//
// Measured on real PhenomeOne (2026-08-28): the pointer-leaf rule below rescued
// the research-group tree and swallowed every data grid with it. `ui-map.json`
// filled up with records - "parchita pumkin - gimel g_1001.3 - observation -
// 2025-09-21", "itay-test - - list - 2023-10-22", "1,241", "5,547" - each with a
// locator built from the data itself (`getByText('1,241', { exact: true })`),
// which breaks the moment the data does. Business data in the map also breaks
// safety invariant 6, and clicking those rows spent a whole crawl budget.
//
// A control's name identifies the control; a number or a date identifies a
// record. Accepted cost: a navigation row named "5.6.1" or "1533" is left
// UNKNOWN and never clicked - the fail-closed direction, and one the operator
// can see in the log.
const VALUE_ONLY_RE = /^[0-9.,:%+\/\s-]+$/;
const DATE_IN_TEXT_RE = /[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}\/[0-9]{1,2}\/[0-9]{2,4}/;
function isValueLabel(text) {
  const t = norm(text);
  if (!t) return true;
  return VALUE_ONLY_RE.test(t) || DATE_IN_TEXT_RE.test(t);
}

function labelOf(el) {
  return directText(el)
    || (el.children.length === 1 ? directText(el.firstElementChild) : '');
}

// A cell surrounded by values is itself a value. This catches the word-labelled
// column - "Approved", "Draft" - that the label test alone cannot see.
//
// Counting labelled siblings instead would be wrong, and the mock proved it: a
// list of navigable rows ALSO has many labelled siblings, and an element sitting
// directly in <body> has the whole page for siblings. What separates a data row
// from a list of rows is not how many neighbours carry text, it is what that
// text IS - a row of a grid is mostly numbers and dates, a list is mostly names.
function amongValues(el) {
  const parent = el.parentElement;
  if (!parent) return false;
  let values = 0;
  for (const sib of parent.children) {
    if (sib === el) continue;
    const label = labelOf(sib);
    if (label && isValueLabel(label)) values++;
    if (values >= VALUE_PEER_MIN) return true;
  }
  return false;
}

// A control with no semantics at all.
//
// Measured on real PhenomeOne (2026-08-27): the entire research-group tree -
// Mine, **Tomato, Tomato Demo, Eggplant, Pepper-ID1533, Sorghum - is rendered by
// dhtmlxTree as `<td class="dhxTextCell standartTreeRow"><span>Tomato</span></td>`
// with no role, no href, no tabindex and no test id. Discovery collected 5
// elements on that screen and none of them was navigation, so an autonomous
// crawl had literally nothing to click.
//
// `cursor: pointer` is the signal a design system leaves behind when it makes
// something clickable. The cheap filters run first because reading a computed
// style forces layout work, and this is evaluated over the whole document.
function isPointerLeaf(el) {
  const tag = el.tagName;
  if (tag !== 'DIV' && tag !== 'SPAN' && tag !== 'TD' && tag !== 'LI'
      && tag !== 'P' && tag !== 'I' && tag !== 'A' && tag !== 'B') return false;
  if (el.children.length > 1) return false;             // a wrapper, not a leaf
  const label = labelOf(el);
  if (!label) return false;                             // unlabelled: nothing to target
  if (isValueLabel(label)) return false;                // a value, not a control
  if (amongValues(el)) return false;                    // a column in a data row
  try {
    if (el.querySelector('a[href],button,input,select,textarea,[role]')) return false;
    if (win(el).getComputedStyle(el).cursor !== 'pointer') return false;
  } catch (e) { return false; }
  // Prefer the INNERMOST such node. dhtmlx wraps every row twice, and harvesting
  // both would make each row's locator match 2 elements - which the crawler
  // then skips as ambiguous, so the whole tree would still be unreachable.
  const kid = el.firstElementChild;
  if (kid && el.children.length === 1 && directText(kid)) {
    try {
      if (win(kid).getComputedStyle(kid).cursor === 'pointer') return false;
    } catch (e) { }
  }
  return isVisible(el) && !isDisabled(el);
}

// Signature for "how many things on this page look exactly like this one".
// Corroboration: a lone pointer-div could be anything, but one row among many
// identical rows is a list, and a list is navigation.
//
// State modifiers are stripped first. A tab bar renders the current tab as
// `tabCell tabCell_actv`, which made the ACTIVE tab a shape of its own -
// `leafSiblings` counted 1, corroboration refused it, and the one tab the user
// is looking at was the one the crawler would not classify. If filtering leaves
// nothing (a row whose only class is `selectedTreeRow`), the raw list is kept
// rather than collapsing the element to a bare tag name.
function leafSignature(el) {
  const raw = (typeof el.className === 'string' ? el.className : '').trim()
    .split(/\s+/).filter(Boolean);
  const stable = raw.filter((c) => !STATE_CLASS.test(c));
  const cls = (stable.length ? stable : raw).sort().join('.');
  return el.tagName.toLowerCase() + (cls ? '.' + cls : '');
}

function isDisabled(el) {
  if (el.disabled === true) return true;
  if (el.getAttribute('aria-disabled') === 'true') return true;
  return !!(el.closest && el.closest('fieldset[disabled]'));
}

// ---------------------------------------------------------------- role
function explicitRole(el) {
  const r = el.getAttribute && el.getAttribute('role');
  if (!r) return '';
  const first = norm(r).split(' ')[0].toLowerCase();
  return (first === 'presentation' || first === 'none') ? '' : first;
}

const INPUT_ROLE = {
  button:'button', submit:'button', reset:'button', image:'button',
  checkbox:'checkbox', radio:'radio', range:'slider', number:'spinbutton',
  search:'searchbox', email:'textbox', tel:'textbox', url:'textbox', text:'textbox',
  password:'textbox', date:'textbox', 'datetime-local':'textbox', month:'textbox',
  week:'textbox', time:'textbox', file:'button', color:'textbox'
};
const TAG_ROLE = {
  A:'link', BUTTON:'button', TEXTAREA:'textbox', SUMMARY:'button', TABLE:'table',
  TH:'columnheader', TR:'row', TD:'cell', NAV:'navigation', MAIN:'main', DIALOG:'dialog',
  FORM:'form', H1:'heading', H2:'heading', H3:'heading', H4:'heading', H5:'heading', H6:'heading',
  HEADER:'banner', FOOTER:'contentinfo', ASIDE:'complementary', SECTION:'region',
  UL:'list', OL:'list', LI:'listitem', OPTION:'option', PROGRESS:'progressbar', LABEL:'label',
  IFRAME:'iframe', FIELDSET:'group', LEGEND:'legend'
};

function computeRole(el) {
  const ex = explicitRole(el);
  if (ex) return ex;
  const tag = el.tagName;
  if (tag === 'INPUT') return INPUT_ROLE[(el.getAttribute('type') || 'text').toLowerCase()] || 'textbox';
  if (tag === 'SELECT') return (el.multiple || (el.size && el.size > 1)) ? 'listbox' : 'combobox';
  if (tag === 'A') return el.hasAttribute('href') ? 'link' : '';
  if (tag === 'DETAILS') return 'group';
  return TAG_ROLE[tag] || '';
}

// ------------------------------------------------------- accessible name
function directText(el) {
  let out = '';
  for (const n of el.childNodes) if (n.nodeType === 3) out += n.nodeValue;
  return norm(out);
}

function contentText(el, depth) {
  depth = depth || 0;
  if (depth > 4) return '';
  let out = '';
  for (const n of el.childNodes) {
    if (n.nodeType === 3) { out += n.nodeValue + ' '; }
    else if (n.nodeType === 1) {
      if (n.tagName === 'SCRIPT' || n.tagName === 'STYLE') continue;
      if (!isVisible(n)) continue;
      const al = n.getAttribute && n.getAttribute('aria-label');
      out += (al ? al : contentText(n, depth + 1)) + ' ';
    }
    if (out.length > 400) break;
  }
  return norm(out);
}

function labelText(el) {
  const doc = el.ownerDocument;
  if (el.id) {
    const ls = doc.querySelectorAll('label[for="' + CSS.escape(el.id) + '"]');
    if (ls.length) return norm(Array.from(ls).map(l => contentText(l)).join(' '));
  }
  const wrap = el.closest && el.closest('label');
  if (wrap) {
    const clone = wrap.cloneNode(true);
    clone.querySelectorAll('input,select,textarea,button').forEach(n => n.remove());
    return contentText(clone);
  }
  return '';
}

function accessibleName(el, role) {
  const doc = el.ownerDocument;
  const lb = el.getAttribute('aria-labelledby');
  if (lb) {
    const parts = [];
    for (const id of norm(lb).split(' ')) {
      const t = id && doc.getElementById(id);
      if (t) parts.push(t.getAttribute('aria-label') || contentText(t));
    }
    const j = norm(parts.join(' '));
    if (j) return { name: clip(j, NAME_MAX), src: 'aria-labelledby' };
  }
  const al = el.getAttribute('aria-label');
  if (norm(al)) return { name: clip(al, NAME_MAX), src: 'aria-label' };

  const tag = el.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') {
    const lt = labelText(el);
    if (lt) return { name: clip(lt, NAME_MAX), src: 'label' };
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'INPUT' && (type === 'button' || type === 'submit' || type === 'reset')) {
      const v = el.getAttribute('value');
      if (norm(v)) return { name: clip(v, NAME_MAX), src: 'value-attr' };
    }
    if (type === 'image') {
      const a = el.getAttribute('alt');
      if (norm(a)) return { name: clip(a, NAME_MAX), src: 'alt' };
    }
    const ph = el.getAttribute('placeholder');
    if (norm(ph)) return { name: clip(ph, NAME_MAX), src: 'placeholder' };
    const ti = el.getAttribute('title');
    if (norm(ti)) return { name: clip(ti, NAME_MAX), src: 'title' };
    return { name: '', src: '' };
  }

  if (NAME_FROM_CONTENT.has(role) || role === '') {
    const ct = contentText(el);
    if (ct && ct.length <= 200) return { name: clip(ct, NAME_MAX), src: 'content' };
    const img = el.querySelector && el.querySelector('img[alt]');
    if (img && norm(img.getAttribute('alt'))) return { name: clip(img.getAttribute('alt'), NAME_MAX), src: 'img-alt' };
  }
  if (role === 'dialog' || role === 'alertdialog' || role === 'region' || role === 'table' ||
      role === 'grid' || role === 'treegrid' || role === 'navigation' || role === 'form') {
    const h = el.querySelector && el.querySelector('h1,h2,h3,h4,[role="heading"],legend,caption');
    if (h) { const t = contentText(h); if (t) return { name: clip(t, NAME_MAX), src: 'heading' }; }
  }
  const ti = el.getAttribute('title');
  if (norm(ti)) return { name: clip(ti, NAME_MAX), src: 'title' };
  return { name: '', src: '' };
}

// ------------------------------------------------------------ classification
const CONTAINER_ROLES = new Set(['dialog','alertdialog','table','grid','treegrid','tree','tablist',
  'toolbar','menu','menubar','navigation','main','banner','contentinfo','complementary','region',
  'form','group','tabpanel','listbox','list','heading','status','alert','progressbar','iframe']);

function classify(el, role) {
  const tag = el.tagName;
  if (role === 'textbox') {
    const t = (el.getAttribute('type') || '').toLowerCase();
    if (t === 'password') return 'password';
    return tag === 'TEXTAREA' ? 'textarea' : 'textbox';
  }
  if (role === 'searchbox') return 'searchbox';
  if (role === 'tab') return 'tab';
  if (role === 'tabpanel') return 'tabpanel';
  if (role === 'menuitem' || role === 'menuitemcheckbox' || role === 'menuitemradio') return 'menuitem';
  if (role === 'menu' || role === 'menubar') return 'menu';
  if (role === 'dialog' || role === 'alertdialog') return 'dialog';
  if (role === 'treeitem') return 'treeitem';
  if (role === 'tree') return 'tree';
  if (role === 'grid' || role === 'treegrid') return 'grid';
  if (role === 'table') return 'table';
  if (role === 'toolbar') return 'toolbar';
  if (role === 'combobox') return 'combobox';
  if (role === 'listbox') return 'listbox';
  if (role === 'option') return 'option';
  if (role === 'checkbox') return 'checkbox';
  if (role === 'radio') return 'radio';
  if (role === 'switch') return 'switch';
  if (role === 'slider') return 'slider';
  if (role === 'spinbutton') return 'spinbutton';
  if (role === 'link') return 'link';
  if (role === 'button') return 'button';
  if (role === 'heading') return 'heading';
  if (role === 'navigation') {
    const n = ((el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('class') || '')).toLowerCase();
    return /pagin|pager/.test(n) ? 'pagination' : 'navigation';
  }
  // A design-system control that declared no semantics. Checked before the
  // layout role wins, or a dhtmlxTree row would be reported as a table cell.
  if (LAYOUT_ROLES.has(role) && isPointerLeaf(el)) return 'clickable';
  if (role) return role;
  if (el.hasAttribute('contenteditable')) return 'textarea';
  if (el.hasAttribute('onclick')) return 'clickable';
  const ti = el.getAttribute('tabindex');
  if (ti !== null && ti !== '-1') return 'focusable';
  if (TESTID_ATTRS.some(a => el.hasAttribute(a))) return 'testid-element';
  return '';
}

const INTERACTIVE_TYPES = new Set(['button','link','tab','menuitem','textbox','searchbox','textarea',
  'combobox','listbox','option','checkbox','radio','switch','slider','spinbutton','treeitem',
  'clickable','focusable','password','pagination','testid-element']);

// ------------------------------------------- action / form / link metadata
// Everything the safety classifier needs to judge an action WITHOUT clicking it
// (spec: autonomous discovery phase 1).

const FILE_HREF = /\.(pdf|csv|tsv|xlsx?|docx?|pptx?|zip|gz|tgz|tar|7z|rar|png|jpe?g|gif|bmp|svg|txt|log|json|xml|exe|msi|dmg|iso|apk)(\?|#|$)/i;

function formInfo(el) {
  const f = (el.form !== undefined && el.form) || (el.closest && el.closest('form'));
  if (!f) return null;
  let action = '';
  try {
    const raw = f.getAttribute('action');
    action = raw ? new URL(raw, location.href).pathname : '';
  } catch (e) { action = ''; }
  const index = Array.from(document.forms).indexOf(f);
  const named = clip(f.getAttribute('id') || f.getAttribute('name') ||
                     f.getAttribute('aria-label') || f.getAttribute('data-testid') || '', 60);
  return {
    identity: named || action || ('form#' + index),
    id: named,
    index: index,
    method: clip((f.getAttribute('method') || 'get').toLowerCase(), 10),
    action: clip(action, 100),
    controls: f.querySelectorAll ? f.querySelectorAll('input,select,textarea').length : 0
  };
}

function linkInfo(el) {
  if (!el.hasAttribute || !el.hasAttribute('href')) return null;
  const raw = el.getAttribute('href') || '';
  const m = raw.match(/^([a-z][a-z0-9+.\-]*):/i);
  let scheme = m ? m[1].toLowerCase() : location.protocol.replace(':', '');
  let sameOrigin = false, pathname = '', origin = '', search = '';
  try {
    const u = new URL(raw, location.href);
    origin = u.origin;
    sameOrigin = u.origin === location.origin;
    pathname = u.pathname + (u.hash || '');
    search = u.search || '';
  } catch (e) { /* opaque scheme */ }
  return {
    raw: clip(raw, 140),
    scheme: scheme,
    origin: clip(origin, 80),
    sameOrigin: sameOrigin,
    pathname: clip(pathname, 120),
    search: clip(search, 160),
    download: el.hasAttribute('download'),
    fileLike: FILE_HREF.test(raw),
    target: clip(el.getAttribute('target') || '', 20),
    empty: raw === '' || raw === '#'
  };
}

// Per-collect memo caches. Ancestor names (a dialog title, a grid label) are
// otherwise recomputed for every descendant, which is O(elements x subtree).
let _nameCache = null;
let _headCache = null;

function cachedName(node, role) {
  if (!_nameCache) {
    try { return clip(accessibleName(node, role).name, 60); } catch (e) { return ''; }
  }
  if (_nameCache.has(node)) return _nameCache.get(node);
  let v = '';
  try { v = clip(accessibleName(node, role).name, 60); } catch (e) { v = ''; }
  _nameCache.set(node, v);
  return v;
}

function nearestHeading(el) {
  const key = el.parentElement || el;
  if (_headCache && _headCache.has(key)) return _headCache.get(key);
  const out = computeNearestHeading(el);
  if (_headCache) _headCache.set(key, out);
  return out;
}

function computeNearestHeading(el) {
  // Cheap: inspect previous siblings' own tags only, walking up a few levels.
  let node = el;
  for (let up = 0; node && up < 6; up++) {
    let sib = node.previousElementSibling, seen = 0;
    while (sib && seen < 6) {
      if (/^H[1-6]$/.test(sib.tagName) || sib.getAttribute('role') === 'heading') {
        return clip(contentText(sib), 60);
      }
      sib = sib.previousElementSibling;
      seen++;
    }
    node = node.parentElement;
  }
  return '';
}

function contextOf(el) {
  const c = {};
  if (!el.closest) return c;
  const named = cachedName;
  const dlg = el.closest('[role="dialog"],[role="alertdialog"],dialog,[aria-modal="true"]');
  if (dlg) c.dialog = named(dlg, 'dialog') || '(untitled dialog)';
  const tb = el.closest('[role="toolbar"]');
  if (tb) c.toolbar = named(tb, 'toolbar') || '(unnamed toolbar)';
  const grid = el.closest('table,[role="grid"],[role="treegrid"]');
  if (grid) c.grid = named(grid, computeRole(grid)) || '(unnamed grid)';
  if (el.closest('tr,[role="row"]')) c.inRow = true;
  const menu = el.closest('[role="menu"],[role="menubar"]');
  if (menu) c.menu = named(menu, 'menu') || '(unnamed menu)';
  const lm = el.closest('main,[role="main"],nav,[role="navigation"],header,[role="banner"],' +
                        'footer,[role="contentinfo"],aside,[role="complementary"],[role="region"]');
  if (lm) c.landmark = computeRole(lm);
  const h = nearestHeading(el);
  if (h) c.heading = h;
  return c;
}

function actionInfo(el, rec) {
  const tag = el.tagName;
  if (tag === 'INPUT') rec.inputType = clip((el.getAttribute('type') || 'text').toLowerCase(), 20);
  const form = formInfo(el);
  if (form) {
    rec.form = form;
    rec.inForm = true;
  }
  if (tag === 'BUTTON') {
    const t = clip((el.getAttribute('type') || '').toLowerCase(), 10);
    rec.buttonType = t;
    // A <button> with no type inside a form submits it - the single most
    // common way an "innocent looking" click writes data.
    rec.effectiveButtonType = t || (form ? 'submit' : 'button');
  }
  const link = linkInfo(el);
  if (link) rec.link = link;
  const pop = el.getAttribute('aria-haspopup');
  if (pop) rec.hasPopup = clip(pop.toLowerCase(), 20);
  const ctrls = el.getAttribute('aria-controls');
  if (ctrls) rec.controls = clip(ctrls, 60);
  if (el.hasAttribute('download')) rec.download = true;
  if (el.hasAttribute('formaction')) {
    rec.formAction = clip(el.getAttribute('formaction'), 100);
  }
  if (el.hasAttribute('formmethod')) {
    rec.formMethod = clip((el.getAttribute('formmethod') || '').toLowerCase(), 10);
  }
  const ctx = contextOf(el);
  if (Object.keys(ctx).length) rec.context = ctx;
  // Icon-only: a control a human recognises by picture alone. Safe to click
  // only if it carries an accessible label saying what it does.
  const textish = rec.directText || rec.name;
  if (!textish && (rec.role === 'button' || rec.role === 'link' || rec.role === 'menuitem' ||
                   rec.role === 'tab' || rec.type === 'clickable')) {
    rec.iconOnly = true;
    rec.labelled = !!rec.name;
  }
  return rec;
}

// ------------------------------------------------------------ grid metadata
// Structural metadata ONLY -- never row values (spec 18).
function gridMeta(el) {
  const heads = el.querySelectorAll('th,[role="columnheader"]');
  const cols = [];
  const seen = new Set();
  for (const h of heads) {
    const t = clip(contentText(h), 60);
    if (t && !seen.has(t)) { seen.add(t); cols.push(t); }
    if (cols.length >= 40) break;
  }
  let rows = el.querySelectorAll('tbody tr,[role="row"]').length;
  if (el.tagName === 'TABLE' && !el.querySelector('tbody')) {
    rows = Math.max(0, el.querySelectorAll('tr').length - 1);
  }
  return { columns: cols, rowCount: rows };
}

// A <table> used purely for layout, nested inside a table we are already
// recording. Older enterprise UIs (PhenomeOne is Dojo) nest tables many levels
// deep for layout: the real run on 2026-08-26 produced 222 unnamed nested
// tables out of 583 elements - 38% of the map - every one LOW confidence with a
// `getByRole('table').nth(11)` locator no test can use.
//
// This only ever skips a table DOMINATED by another table, so the outermost
// grid always survives; and anything carrying a name, caption, test id or a
// non-table role (a real `role=grid`) is kept regardless of nesting.
function isLayoutTable(el) {
  if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return false;
  if (el.getAttribute('title')) return false;
  const role = el.getAttribute('role');
  if (role && role !== 'table') return false;
  for (const a of TESTID_ATTRS) { if (el.getAttribute(a)) return false; }
  try { if (el.querySelector(':scope > caption')) return false; } catch (e) { }
  const parent = el.parentElement;
  if (parent && parent.closest('table,[role="grid"],[role="treegrid"],[role="table"]')) {
    return true;                            // dominated by another table
  }
  // Not nested, but still anonymous AND header-free.
  //
  // Measured on real PhenomeOne (2026-08-28): the dominance rule above only
  // catches a table INSIDE another table, and this UI lays out each widget as
  // its own top-level table - so 231 of the 272 elements recorded for the
  // landing state were anonymous tables. Their only identity was a position
  // (`table:table:#219`), which shifts between visits, so every revisit minted
  // 12 more of them: 44 elements grew to 272 over 19 visits, and the map
  // reached 8.2 MB for 7 states with validation taking 33 s on one scan.
  //
  // Column headers are what separates a data grid from a layout box, and a
  // table WITH headers is still recorded wherever it sits. Skipping the table
  // element does not skip its contents: every control inside is harvested on
  // its own merits.
  try { return !el.querySelector('th,[role="columnheader"]'); } catch (e) { return false; }
}

// ------------------------------------------------------------ harvest
function harvest(rootDoc, limit) {
  const els = [];
  const stack = [{ root: rootDoc, depth: 0 }];
  let scanned = 0;
  while (stack.length) {
    const item = stack.pop();
    let all;
    try { all = item.root.querySelectorAll('*'); } catch (e) { continue; }
    for (const el of all) {
      scanned++;
      if (el.shadowRoot && item.depth < 5) stack.push({ root: el.shadowRoot, depth: item.depth + 1 });
      const tag = el.tagName;
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'LINK' || tag === 'META' || tag === 'HEAD') continue;
      try { if (!el.matches(SEL) && !isPointerLeaf(el)) continue; } catch (e) { continue; }
      if (tag === 'TABLE' && isLayoutTable(el)) continue;
      els.push(el);
      if (els.length >= limit) return { els: els, scanned: scanned };
    }
  }
  return { els: els, scanned: scanned };
}

function attrsOf(el) {
  const a = {};
  for (const k of TESTID_ATTRS) { const v = el.getAttribute(k); if (v) a[k] = clip(v, 80); }
  const simple = ['id','name','type','placeholder','title','aria-label','aria-labelledby','role','href','for'];
  for (const k of simple) {
    let v = el.getAttribute(k);
    if (v == null || v === '') continue;
    if (k === 'href') { v = v.split('?')[0]; if (v.length > 120) v = v.slice(0, 120); }
    a[k] = clip(v, 120);
  }
  if (a['id'] && VOLATILE_ID.some(re => re.test(a['id']))) a['idVolatile'] = '1';
  return a;
}

function elementRecord(el, frame) {
  const role = computeRole(el);
  const type = classify(el, role);
  const nm = accessibleName(el, role);
  const attrs = attrsOf(el);
  const rec = {
    tag: el.tagName.toLowerCase(),
    role: role,
    type: type,
    name: nm.name,
    nameSource: nm.src,
    attrs: attrs,
    visible: isVisible(el),
    enabled: !isDisabled(el),
    interactive: INTERACTIVE_TYPES.has(type),
    container: CONTAINER_ROLES.has(role),
    directText: clip(directText(el), TEXT_MAX),
    inDialog: !!(el.closest && el.closest('[role="dialog"],[role="alertdialog"],dialog[open],[aria-modal="true"]')),
    frame: frame
  };
  if (rec.type === 'password') { rec.name = rec.name || 'password'; rec.directText = ''; }
  const exp = el.getAttribute('aria-expanded');
  if (exp !== null) { rec.expanded = exp === 'true'; rec.expandable = true; }
  if (el.tagName === 'DETAILS') { rec.expanded = el.open === true; rec.expandable = true; }
  const sel = el.getAttribute('aria-selected');
  if (sel !== null) rec.selected = sel === 'true';
  const chk = el.getAttribute('aria-checked');
  if (chk !== null) rec.checked = chk === 'true';
  else if (el.type === 'checkbox' || el.type === 'radio') rec.checked = !!el.checked;
  if (el.required || el.getAttribute('aria-required') === 'true') rec.required = true;
  actionInfo(el, rec);
  if (rec.type === 'grid' || rec.type === 'table') rec.grid = gridMeta(el);
  // Shape signature for a semantics-free control, so the classifier can ask
  // 'how many things on this page look exactly like this?' before trusting it.
  if (rec.type === 'clickable') rec.leafSig = leafSignature(el);
  // A class-based scope for elements whose only handle is their text, so an
  // ambiguous label can still yield a unique locator.
  if (rec.directText) {
    const cs = classSelector(el);
    if (cs) rec.classSel = cs;
  }
  if (el.tagName === 'SELECT') {
    rec.options = Array.from(el.options).slice(0, 25).map(o => clip(o.textContent, 60)).filter(Boolean);
  }
  return rec;
}

// A class-based selector for an element whose only other handle is its text.
//
// Measured on real PhenomeOne (2026-08-28): 308 of the last crawl's refusals
// were `locator-not-unique`, and they were navigable controls, not junk - the
// `Germplasms` TAB and the `Germplasms 10` summary CARD carry the same label, so
// `getByText('Germplasms')` matches two elements and the crawler refuses both.
// Scoping the text to the control's own design-system class separates them.
//
// Only a framework's own vocabulary qualifies. Rejected:
//  * anything with a digit run, a hash, or a CSS-module/emotion shape
//    (`css-1x2y3z`, `jsx-1234`) - generated, so it changes on every build;
//  * state modifiers (`...actv`, `selected`, `open`, `focus`) - they describe
//    the moment, not the control, and a locator built from one stops matching
//    the instant the user clicks something else.
const VOLATILE_CLASS = [
  /\d{3,}/, /^css-[a-z0-9]{4,}$/i, /^jsx-\d+/i, /^sc-[a-z0-9]{5,}$/i,
  /^emotion-/i, /^[a-z]+-[a-z0-9]{6,}$/i, /^ng-tns-/i, /^_[a-zA-Z0-9]{5,}$/
];
const STATE_CLASS = /(actv|active|selected|checked|current|open(ed)?|expand(ed)?|collaps|focus|hover|hidden|disabled|dragging|highlight)/i;

function stableClasses(el) {
  const raw = (typeof el.className === 'string' ? el.className : '').trim();
  if (!raw) return [];
  return raw.split(/\s+/).filter((c) => {
    if (!c || c.length < 3 || c.length > 40) return false;
    if (STATE_CLASS.test(c)) return false;
    for (const re of VOLATILE_CLASS) if (re.test(c)) return false;
    return true;
  }).slice(0, 2);
}

// `div.dhxtabbar_tab_text` - the shape, without the text. The generator pairs it
// with `:text-is(...)` only when that pair is unique on the page.
function classSelector(el) {
  const cls = stableClasses(el);
  if (!cls.length) return '';
  return el.tagName.toLowerCase() + '.' + cls.join('.');
}

// ------------------------------------------------- uniqueness counters
function buildCounts(records) {
  const c = { roleName: {}, role: {}, text: {}, testid: {}, id: {}, nameAttr: {},
              placeholder: {}, label: {}, title: {}, href: {}, classText: {} };
  const bump = (m, k) => { if (k) m[k] = (m[k] || 0) + 1; };
  for (const r of records) {
    if (r.role) {
      bump(c.role, r.role);
      bump(c.roleName, r.role + ' ' + r.name.toLowerCase());
    }
    if (r.directText) {
      bump(c.text, r.directText.toLowerCase());
      // How many elements share BOTH this shape and this text - the question the
      // scoped-text locator needs answered before it can be trusted.
      if (r.classSel) bump(c.classText, r.classSel + ' ' + r.directText.toLowerCase());
    }
    for (const k of TESTID_ATTRS) if (r.attrs[k]) bump(c.testid, k + ' ' + r.attrs[k]);
    bump(c.id, r.attrs['id']);
    bump(c.nameAttr, r.attrs['name']);
    bump(c.placeholder, r.attrs['placeholder']);
    bump(c.title, r.attrs['title']);
    bump(c.href, r.attrs['href']);
    if (r.nameSource === 'label' && r.name) bump(c.label, r.name.toLowerCase());
  }
  return c;
}

// ------------------------------------------------- structure / fingerprint
function structureOf(records) {
  // First *visible* match: SPAs keep whole hidden views (login screens, other
  // routes) in the DOM, and their headings must not describe the live state.
  const first = (sel) => {
    for (const e of document.querySelectorAll(sel)) {
      if (isVisible(e)) return clip(contentText(e), 100);
    }
    return '';
  };
  const tabs = [], dialogs = [], landmarks = [], headings = [];
  const LANDMARK_ROLES = ['main','navigation','banner','complementary','contentinfo','region',
                          'form','tablist','toolbar','grid','table','tree'];
  let activeTab = '';
  for (const r of records) {
    if (r.type === 'tab' && r.visible) {
      tabs.push(r.name);
      if (r.selected) activeTab = r.name;
    }
    if (r.type === 'dialog' && r.visible) dialogs.push(r.name || '(untitled dialog)');
    if (r.container && r.visible && LANDMARK_ROLES.indexOf(r.role) >= 0) {
      landmarks.push(r.role + (r.name ? ':' + r.name : ''));
    }
    if (r.type === 'heading' && r.visible && r.name) headings.push(r.name);
  }
  return {
    url: location.href,
    origin: location.origin,
    path: location.pathname,
    hash: location.hash,
    search: location.search,
    title: clip(document.title, 120),
    h1: first('h1') || first('[role="heading"][aria-level="1"]'),
    headings: headings.slice(0, 8),
    activeTab: activeTab,
    tabs: tabs.slice(0, 30),
    dialogs: dialogs.slice(0, 5),
    landmarks: Array.from(new Set(landmarks)).slice(0, 25)
  };
}

function collect(opts) {
  const t0 = performance.now();
  const limit = (opts && opts.maxElements) || 1500;
  const frame = (opts && opts.frame) || '';
  const h = harvest(document, limit);
  _nameCache = new Map();
  _headCache = new Map();
  const records = [];
  for (const el of h.els) {
    try { records.push(elementRecord(el, frame)); } catch (e) { /* skip hostile node */ }
  }
  _nameCache = null;
  _headCache = null;
  // Corroboration pass: count how many harvested controls share each shape. One
  // pointer-div could be anything; one row among seven identical rows is a list.
  const shapes = new Map();
  for (const r of records) {
    if (r.leafSig) shapes.set(r.leafSig, (shapes.get(r.leafSig) || 0) + 1);
  }
  for (const r of records) {
    if (r.leafSig) r.leafSiblings = shapes.get(r.leafSig) || 1;
  }
  const keep = records.filter(r => r.type && (r.interactive || r.container));
  return {
    structure: structureOf(records),
    elements: keep,
    counts: buildCounts(records),
    stats: { nodesScanned: h.scanned, candidates: records.length, kept: keep.length,
             truncated: h.els.length >= limit, jsMs: Math.round(performance.now() - t0) }
  };
}

// ================================================== TRAINING OBSERVATION
// Passive only: listeners are capture-phase/passive and never call
// preventDefault, stopPropagation, or dispatch synthetic events (spec 23).
const state = { observing: false, installed: false, seq: 0, sig: '', timer: null,
                lastAction: null, lastPointer: null };

function emit(payload) {
  try {
    payload.seq = ++state.seq;
    payload.url = location.href;
    if (window.__p1uidEmit) window.__p1uidEmit(payload);
  } catch (e) { /* never break the host app */ }
}

function describeTarget(el) {
  let cur = el, best = null, hops = 0;
  while (cur && cur.nodeType === 1 && hops < 6) {
    const role = computeRole(cur);
    const type = classify(cur, role);
    if (type && INTERACTIVE_TYPES.has(type)) { best = cur; break; }
    const root = cur.getRootNode && cur.getRootNode();
    cur = cur.parentElement || (root && root.host) || null;
    hops++;
  }
  const target = best || el;
  if (!target || target.nodeType !== 1) return null;
  const rec = elementRecord(target, '');
  delete rec.grid;
  delete rec.options;
  return rec;
}

function domSignature() {
  // Cheap structural signature: which controls are visible, never their data.
  let s = location.pathname + '|' + location.hash + '|' + document.title + '|';
  const nodes = document.querySelectorAll(
    '[role="tab"][aria-selected="true"],[role="dialog"],[role="alertdialog"],dialog[open],h1,h2,[role="heading"]');
  let i = 0;
  for (const n of nodes) {
    s += (n.getAttribute('role') || n.tagName) + ':' + clip(contentText(n), 40) + ';';
    if (++i > 12) break;
  }
  s += 'n=' + document.querySelectorAll('button,a[href],[role="tab"],[role="menuitem"],input').length;
  return s;
}

// Which interactive controls are actually VISIBLE right now.
//
// `domSignature` counts interactive nodes whether or not they are shown, so
// revealing an already-present menu does not move it - and the crawler read
// that as "the click did nothing" and pruned the control. An opened dropdown is
// not a route, a tab, a dialog or a landmark either, so no state fingerprint
// input moves. This is the signal that separates "nothing happened" from "a
// surface opened", and it is deliberately separate from `domSignature` so the
// stability wait keeps its exact, well-tested sensitivity.
function visibleSignature() {
  const sel = 'button,a[href],[role="button"],[role="tab"],[role="menuitem"],' +
              '[role="option"],[role="menu"],[role="listbox"],input,select,textarea';
  let n = 0, surfaces = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (!isVisible(el)) continue;
    n++;
    const role = el.getAttribute('role');
    if (role === 'menu' || role === 'listbox') surfaces++;
  }
  return 'v=' + n + '|s=' + surfaces;
}

// Diagnostic: things a person would obviously click that we did NOT harvest.
//
// Measured on real PhenomeOne (2026-08-27): a whole application screen yielded
// 5 harvested elements, none of them navigation, because a Dojo UI renders its
// tree and toolbars as <div>/<span> with JavaScript handlers - matching none of
// the selectors in SEL. `cursor: pointer` is the cheapest reliable signal that
// a design system considers something clickable, so this reports those, with
// enough shape (tag, class, role, tabindex) to decide what rule would catch
// them. Text is clipped and no field value is ever read.
function missedClickables(limit) {
  const out = [];
  const max = limit || 25;
  let scanned = 0;
  for (const el of document.querySelectorAll('div,span,li,td,i,a')) {
    if (out.length >= max || scanned > 4000) break;
    scanned++;
    try {
      if (el.matches(SEL)) continue;           // already collected
      if (!isVisible(el)) continue;
      const st = win(el).getComputedStyle(el);
      if (!st || st.cursor !== 'pointer') continue;
      // Only leaf-ish nodes: a clickable wrapper around a real control is not
      // the thing we are missing.
      if (el.querySelector('a[href],button,input,select,textarea')) continue;
      out.push({
        tag: el.tagName.toLowerCase(),
        cls: clip(typeof el.className === 'string' ? el.className : '', 70),
        text: clip(directText(el) || contentText(el), 40),
        role: el.getAttribute('role') || '',
        tabindex: el.getAttribute('tabindex') || '',
        kids: el.children.length
      });
    } catch (e) { }
  }
  return out;
}

function checkState(reason) {
  const sig = domSignature();
  if (sig === state.sig) return;
  state.sig = sig;
  // Carry the action that caused THIS change. Attribution must not depend on
  // how long the Python side takes to scan, otherwise a fast click sequence
  // credits the wrong control (dialog opened by "Add", closed by "Close").
  const cause = state.lastAction;
  state.lastAction = null;
  emit({ kind: 'state-changed', reason: reason, cause: cause });
}

function scheduleCheck(reason, delay) {
  if (state.timer) clearTimeout(state.timer);
  state.timer = setTimeout(() => { state.timer = null; checkState(reason); }, delay || 350);
}

function recordActivation(ev, kind) {
  const rec = describeTarget(ev.target);
  if (!rec) return;
  state.lastAction = { element: rec, action: kind };
  emit({ kind: 'action', action: kind, element: rec, trusted: ev.isTrusted === true });
  scheduleCheck('after-' + kind, 250);
}

function onPointer(ev) {
  if (!state.observing) return;
  try {
    state.lastPointer = { target: ev.target, t: Date.now() };
    const rec = describeTarget(ev.target);
    if (!rec) return;
    state.lastAction = { element: rec, action: 'click' };
    emit({ kind: 'action', action: 'click', element: rec, trusted: ev.isTrusted === true });
    scheduleCheck('after-click', 250);
  } catch (e) { }
}

function onClick(ev) {
  if (!state.observing) return;
  try {
    const p = state.lastPointer;
    if (p && p.target === ev.target && (Date.now() - p.t) < 600) return;  // already recorded
    recordActivation(ev, 'click');
  } catch (e) { }
}

function onKey(ev) {
  if (!state.observing) return;
  if (ev.key !== 'Enter' && ev.key !== ' ') return;
  try {
    const rec = describeTarget(ev.target);
    const ok = rec && ['button','link','tab','menuitem','treeitem','checkbox','switch'].indexOf(rec.type) >= 0;
    if (ok) {
      state.lastAction = { element: rec, action: 'key-activate' };
      emit({ kind: 'action', action: 'key-activate', element: rec, trusted: ev.isTrusted === true });
      scheduleCheck('after-key', 250);
    }
  } catch (e) { }
}

function onChange(ev) {
  if (!state.observing) return;
  try {
    const rec = describeTarget(ev.target);
    if (!rec) return;
    state.lastAction = { element: rec, action: 'change' };
    // NO VALUES: we record only that the control was used (spec 16).
    emit({ kind: 'action', action: 'change', element: rec, trusted: ev.isTrusted === true });
  } catch (e) { }
}

function installObservers() {
  if (state.installed) return;
  state.installed = true;
  const opt = { capture: true, passive: true };
  document.addEventListener('pointerup', onPointer, opt);
  document.addEventListener('click', onClick, opt);
  document.addEventListener('keydown', onKey, { capture: true, passive: true });
  document.addEventListener('change', onChange, opt);

  const mo = new MutationObserver((muts) => {
    if (!state.observing) return;
    let significant = 0;
    for (const m of muts) {
      if (m.type === 'childList') significant += m.addedNodes.length + m.removedNodes.length;
      else if (m.type === 'attributes' && m.attributeName !== 'class') significant += 4;
      if (significant > 3) break;
    }
    if (significant > 3) scheduleCheck('dom-mutation', 400);
  });
  mo.observe(document.documentElement, { childList: true, subtree: true, attributes: true,
    attributeFilter: ['aria-selected','aria-expanded','aria-hidden','open','hidden','class'] });
  state.mo = mo;

  for (const fn of ['pushState', 'replaceState']) {
    const orig = history[fn];
    if (!orig || orig.__p1uidWrapped) continue;
    const wrapped = function () {
      const r = orig.apply(this, arguments);
      if (state.observing) { emit({ kind: 'route', via: fn }); scheduleCheck('history-' + fn, 250); }
      return r;
    };
    wrapped.__p1uidWrapped = true;
    history[fn] = wrapped;
  }
  window.addEventListener('popstate', () => { if (state.observing) scheduleCheck('popstate', 250); });
  window.addEventListener('hashchange', () => { if (state.observing) scheduleCheck('hashchange', 250); });
}

// ------------------------------------------------------------- waitStable
// Resolves once the page has stopped changing: no DOM mutations for `quietMs`
// AND the structural signature identical across that window. Event-driven -
// no fixed sleeps, and deliberately NOT tied to network idle, which never
// settles on an app that polls or keeps a socket open.
// In-flight application requests.
//
// Measured on real PhenomeOne (2026-08-28): selecting a research group changes
// the route, fires an XHR, and renders the screen when it returns. The gap in
// between is longer than the 250 ms quiet window, so `waitStable` called the
// skeleton settled and the crawler scanned 40 elements of a 97-element screen -
// the tabs (Overview, Germplasms, Variables...) were simply not there yet. Every
// state's exploration then had nothing but the navigation tree to click.
//
// This is NOT `networkidle`, which the design rejects for good reason: a page
// that polls, streams or holds a socket open never reaches it. Only fetch and
// XMLHttpRequest are counted, a request older than STALE_REQUEST_MS stops being
// counted so a long-poll cannot pin the page as busy forever, and the caller's
// timeout still bounds the whole wait.
const STALE_REQUEST_MS = 8000;
const _inflight = new Map();          // id -> started-at
let _reqSeq = 0;

function inflightCount() {
  const now = performance.now();
  for (const [id, started] of _inflight) {
    if (now - started > STALE_REQUEST_MS) _inflight.delete(id);
  }
  return _inflight.size;
}

function trackRequests() {
  if (window.__p1uidRequestsPatched) return;
  window.__p1uidRequestsPatched = true;
  const open = () => { const id = ++_reqSeq; _inflight.set(id, performance.now()); return id; };
  const close = (id) => { _inflight.delete(id); };

  try {
    const nativeFetch = window.fetch;
    if (typeof nativeFetch === 'function') {
      window.fetch = function (...args) {
        const id = open();
        let p;
        try { p = nativeFetch.apply(this, args); } catch (e) { close(id); throw e; }
        return p.then((r) => { close(id); return r; }, (e) => { close(id); throw e; });
      };
    }
  } catch (e) { /* leave fetch alone if anything is unusual */ }

  try {
    const send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function (...args) {
      const id = open();
      // loadend covers load, error, abort and timeout - never leak a counter.
      try { this.addEventListener('loadend', () => close(id)); } catch (e) { close(id); }
      try { return send.apply(this, args); } catch (e) { close(id); throw e; }
    };
  } catch (e) { /* ditto */ }
}

function waitStable(opts) {
  opts = opts || {};
  const quiet = opts.quietMs || 250;
  const timeout = opts.timeoutMs || 5000;
  // A request in flight means content is on its way: not settled, whatever the
  // DOM is doing. Opt-out kept so a caller can measure the old behaviour.
  const waitRequests = opts.waitRequests !== false;
  return new Promise((resolve) => {
    const t0 = performance.now();
    let sig = domSignature();
    let changes = 0;
    let waitedForRequests = false;
    let quietTimer = null, hardTimer = null, mo = null, done = false;

    const finish = (reason) => {
      if (done) return;
      done = true;
      if (mo) mo.disconnect();
      if (quietTimer) clearTimeout(quietTimer);
      if (hardTimer) clearTimeout(hardTimer);
      resolve({ stable: reason === 'quiet', reason: reason, changes: changes,
                ms: Math.round(performance.now() - t0), signature: sig,
                pending: inflightCount(), waited: waitedForRequests,
                readyState: document.readyState });
    };

    const settle = () => {
      const now = domSignature();
      if (now !== sig) {            // changed without a mutation we saw: keep waiting
        sig = now;
        changes++;
        arm();
        return;
      }
      if (waitRequests && inflightCount() > 0) {
        // The DOM is quiet only because it is waiting for data. Re-arm: the
        // response will mutate the page and restart the quiet window properly.
        waitedForRequests = true;
        arm();
        return;
      }
      finish('quiet');
    };

    const arm = () => {
      if (quietTimer) clearTimeout(quietTimer);
      quietTimer = setTimeout(settle, quiet);
    };

    try {
      mo = new MutationObserver(() => { changes++; arm(); });
      mo.observe(document.documentElement, { childList: true, subtree: true, attributes: true,
        attributeFilter: ['aria-selected','aria-expanded','aria-hidden','aria-busy','open','hidden','class','style','disabled'] });
    } catch (e) { /* no document yet */ }
    hardTimer = setTimeout(() => finish('timeout'), timeout);
    arm();
  });
}

window.__p1uidCore = {
  version: 1,
  collect: collect,
  waitStable: waitStable,
  signature: function () { return domSignature(); },
  visibleSignature: function () { return visibleSignature(); },
  missedClickables: function (n) { return missedClickables(n); },
  inflight: function () { return inflightCount(); },
  startObserving: function () {
    installObservers();
    state.observing = true;
    state.sig = '';
    scheduleCheck('observation-started', 150);
    return true;
  },
  stopObserving: function () { state.observing = false; return true; },
  isObserving: function () { return state.observing; },
  _internals: { computeRole: computeRole, accessibleName: accessibleName,
                classify: classify, domSignature: domSignature }
};

// Installed with the core, which the context adds as an init script - so the
// patch is in place before the application's own scripts run and no request is
// missed. Idempotent: a second injection into the same document is a no-op.
trackRequests();

if (window.__p1uidWantObserve) window.__p1uidCore.startObserving();
})();
"""

# Added as a separate init script when training starts, so freshly created pages
# and post-navigation documents begin observing without an extra round-trip.
WANT_OBSERVE_JS = "window.__p1uidWantObserve = true;"
