"""Authentication (spec 6).

Automatic login is *confidence-gated*: the form is analysed first and fields are
only filled when the tool is sure which is which. Anything less falls back to
Manual Login, where the user authenticates in the visible browser themselves.

The password never leaves memory: it is passed straight to ``fill()`` and is
registered with the log redactor so it can never reach a file.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..logging_setup import get, register_secret

log = get("auth")

HIGH, MEDIUM, LOW = "HIGH", "MEDIUM", "LOW"

_USER_HINT = re.compile(r"user|email|e-mail|login|account|logon|ident|mail", re.I)
_SUBMIT_HINT = re.compile(r"\b(log ?in|sign ?in|log ?on|submit|continue|enter|authenticate|connect)\b", re.I)
_DENY_HINT = re.compile(r"forgot|reset|register|sign ?up|create|help|cancel|sso|google|microsoft|okta|saml", re.I)

# Collected in-browser: enough to decide, never any field values.
FIELDS_JS = r"""
() => {
  const vis = (el) => {
    const st = getComputedStyle(el);
    if (!st || st.display === 'none' || st.visibility === 'hidden') return false;
    if (parseFloat(st.opacity || '1') === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  const norm = (s) => (s == null ? '' : String(s)).replace(/\s+/g, ' ').trim().slice(0, 80);
  const labelOf = (el) => {
    if (el.getAttribute('aria-label')) return norm(el.getAttribute('aria-label'));
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = document.getElementById(lb.split(' ')[0]); if (t) return norm(t.textContent); }
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) return norm(l.textContent); }
    const w = el.closest('label'); if (w) return norm(w.textContent);
    return '';
  };
  // Why is this element not visible? "NOT-VISIBLE" alone cannot be acted on;
  // knowing it is a zero-height wrapper mid-animation vs. display:none on an
  // ancestor is the difference between waiting and giving up.
  const whyHidden = (el) => {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const s = getComputedStyle(e);
      const why = s.display === 'none' ? 'display:none'
                : s.visibility === 'hidden' ? 'visibility:hidden'
                : parseFloat(s.opacity || '1') === 0 ? 'opacity:0' : '';
      if (why) {
        const who = e === el ? 'self' : e.tagName.toLowerCase() + (e.id ? '#' + e.id : '');
        return who + ' ' + why;
      }
    }
    const r = el.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1) {
      return 'zero-size ' + Math.round(r.width) + 'x' + Math.round(r.height);
    }
    return 'off-screen or covered';
  };
  const inputs = Array.from(document.querySelectorAll('input')).map((el, i) => ({
    index: i,
    type: (el.getAttribute('type') || 'text').toLowerCase(),
    name: norm(el.getAttribute('name')),
    id: norm(el.getAttribute('id')),
    placeholder: norm(el.getAttribute('placeholder')),
    autocomplete: norm(el.getAttribute('autocomplete')),
    label: labelOf(el),
    testid: norm(el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-cy')),
    visible: vis(el),
    hiddenBy: vis(el) ? '' : whyHidden(el),
    disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
    formIndex: el.form ? Array.from(document.forms).indexOf(el.form) : -1
  }));
  const buttons = Array.from(document.querySelectorAll(
      'button, input[type="submit"], input[type="button"], [role="button"]')).map((el, i) => ({
    index: i,
    tag: el.tagName.toLowerCase(),
    type: (el.getAttribute('type') || '').toLowerCase(),
    text: norm(el.tagName === 'INPUT' ? (el.getAttribute('value') || '') : el.textContent),
    ariaLabel: norm(el.getAttribute('aria-label')),
    testid: norm(el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-cy')),
    visible: vis(el),
    disabled: !!el.disabled,
    formIndex: el.form ? Array.from(document.forms).indexOf(el.form) : -1
  }));
  const errors = Array.from(document.querySelectorAll('[role="alert"],.error,.alert-danger,[aria-live="assertive"]'))
    .filter(vis).map(el => norm(el.textContent)).filter(Boolean).slice(0, 3);
  return { inputs, buttons, errors, url: location.href, title: norm(document.title) };
}
"""


@dataclass
class LoginPlan:
    confidence: str = LOW
    username_index: int | None = None
    password_index: int | None = None
    submit_index: int | None = None
    submit_by_enter: bool = False
    reasons: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.confidence in (HIGH, MEDIUM) and self.password_index is not None


def _score_username(fld: dict[str, Any]) -> tuple[int, str]:
    """Higher is better. Returns (score, why)."""
    if fld["type"] == "email":
        return 100, "input[type=email]"
    if fld["autocomplete"] in ("username", "email"):
        return 95, f"autocomplete={fld['autocomplete']}"
    hint_keys = ("label", "placeholder", "name", "id", "testid")
    for i, key in enumerate(hint_keys):
        if fld.get(key) and _USER_HINT.search(fld[key]):
            return 90 - i * 5, f"{key}={fld[key]!r}"
    if fld["type"] in ("text", "tel"):
        return 30, "generic text input"
    return 0, "not a username-looking field"


def analyse(fields: dict[str, Any]) -> LoginPlan:
    """Decide, deterministically, which fields form the login form."""
    plan = LoginPlan()
    inputs = fields.get("inputs", [])
    buttons = fields.get("buttons", [])

    pwds = [f for f in inputs if f["type"] == "password" and f["visible"] and not f["disabled"]]
    if not pwds:
        plan.reasons.append("no visible password field on this page")
        return plan
    if len(pwds) > 1:
        plan.reasons.append(f"{len(pwds)} visible password fields - ambiguous (change-password form?)")
        return plan
    pwd = pwds[0]
    plan.password_index = pwd["index"]
    plan.reasons.append("password field identified by input[type=password]")

    cands = [f for f in inputs
             if f["visible"] and not f["disabled"] and f["type"] not in ("password", "hidden", "checkbox",
                                                                        "radio", "submit", "button", "file")]
    same_form = [f for f in cands if f["formIndex"] == pwd["formIndex"]] or cands
    before = [f for f in same_form if f["index"] < pwd["index"]]
    pool = before or same_form

    best, best_score, best_why = None, 0, ""
    for f in pool:
        score, why = _score_username(f)
        if before and f in before:
            score += 5                      # a field before the password is the usual layout
        if score > best_score:
            best, best_score, best_why = f, score, why
    if best is None:
        plan.reasons.append("no username field candidate found")
        plan.confidence = LOW
        return plan

    plan.username_index = best["index"]
    plan.reasons.append(f"username field via {best_why}")
    strong_user = best_score >= 85
    only_one = len(pool) == 1

    # Submit control.
    form_buttons = [b for b in buttons if b["visible"] and not b["disabled"]
                    and (b["formIndex"] == pwd["formIndex"] or b["formIndex"] == -1)]
    scored: list[tuple[int, dict[str, Any]]] = []
    for b in form_buttons:
        text = f"{b['text']} {b['ariaLabel']} {b['testid']}".strip()
        if _DENY_HINT.search(text):
            continue
        s = 0
        if _SUBMIT_HINT.search(text):
            s += 60
        if b["type"] == "submit":
            s += 30
        if b["formIndex"] == pwd["formIndex"] and b["formIndex"] != -1:
            s += 10
        if s:
            scored.append((s, b))
    if scored:
        scored.sort(key=lambda t: -t[0])
        plan.submit_index = scored[0][1]["index"]
        plan.reasons.append(f"submit via {scored[0][1]['text'] or scored[0][1]['ariaLabel'] or 'type=submit'!r}")
    else:
        plan.submit_by_enter = True
        plan.reasons.append("no confident submit button - will press Enter in the password field")

    if strong_user or only_one:
        plan.confidence = HIGH
    else:
        plan.confidence = MEDIUM
        plan.reasons.append("username field chosen by position, not by label/type")
    return plan


STRONG_USERNAME = 85          # score at which a candidate is worth waiting for


async def analyse_when_ready(frame: Any, settle_s: float = 10.0) -> tuple[LoginPlan, dict[str, Any]]:
    """Analyse the form, giving a still-rendering field time to appear.

    Live failure (PhenomeOne, 2026-08-26): the password field became visible
    18.1 s after load, and at that instant `#usernameLoginInput` - a field that
    scores 85 - was still not visible. The form was therefore refused as having
    "no username field candidate", even though a human could fill it a moment
    later. `find_login_form` returns as soon as a *password* field appears, so
    the snapshot can catch a half-rendered form.

    This waits only while there is something specific to wait for: an invisible,
    enabled, strongly-scoring username candidate. If it never becomes visible the
    original refusal stands - the gate is not loosened, only given time.
    """
    fields = await read_fields(frame)
    plan = analyse(fields)
    if plan.usable:
        return plan, fields

    started = time.monotonic()
    deadline = started + settle_s
    logged = False
    timed_out = True            # False when the loop breaks for lack of anything pending
    while time.monotonic() < deadline:
        pending = [f for f in fields.get("inputs", [])
                   if not f.get("visible") and not f.get("disabled")
                   and f.get("type") not in ("password", "hidden")
                   and _score_username(f)[0] >= STRONG_USERNAME]
        if not pending:
            timed_out = False           # nothing is on its way; the verdict is final
            break
        if not logged:
            log.info("A likely username field is present but not visible yet "
                     "(%s) - waiting up to %.0fs for the form to finish rendering",
                     ", ".join(f"id={f['id']!r}" if f.get("id") else f"index={f['index']}"
                               for f in pending[:3]), settle_s)
            logged = True
        await asyncio.sleep(0.3)
        fields = await read_fields(frame)
        plan = analyse(fields)
        if plan.usable:
            log.info("The form finished rendering after %.1fs; analysis now confidence=%s",
                     time.monotonic() - started, plan.confidence)
            return plan, fields
    if logged:
        waited = time.monotonic() - started
        if timed_out:
            log.warning("The username field never became visible within %.0fs - "
                        "refusing automatic login (unchanged behaviour)", settle_s)
        else:
            # Distinct outcome, and the one the real application produced: the
            # form stopped being a login form while we were waiting - it was a
            # transient render, or the app replaced it once the session resolved.
            log.warning("The login form changed while settling (%.1fs in) and no longer "
                        "offers a username field - refusing automatic login", waited)
    return plan, fields


def describe_fields(fields: dict[str, Any]) -> str:
    """Inventory of the form's inputs, for the log when analysis refuses.

    Without this, a refusal says only *that* it could not identify the username
    field, and diagnosing a real application means guessing. Printing what was
    actually on the page turns that into a fact.

    **Metadata only.** `FIELDS_JS` never reads a field's value, so no value can
    reach this string - not even from the password field, which is listed by
    type and attributes like any other input.
    """
    rows = fields.get("inputs") or []
    if not rows:
        return "    (no <input> elements were present on the page at all)"
    out = [f"    {len(rows)} input(s) found:"]
    for f in rows:
        bits = [f"type={f.get('type') or '?'}"]
        for key in ("label", "placeholder", "autocomplete", "name", "id", "testid"):
            value = f.get(key)
            if value:
                bits.append(f"{key}={value!r}")
        if f.get("visible"):
            state = "visible"
        else:
            why = f.get("hiddenBy") or ""
            state = f"NOT-VISIBLE({why})" if why else "NOT-VISIBLE"
        if f.get("disabled"):
            state += "+disabled"
        bits.append(state)
        form_index = f.get("formIndex", -1)
        bits.append(f"form#{form_index}" if form_index >= 0 else "no-form")
        if f.get("type") != "password":
            score, why = _score_username(f)
            bits.append(f"usernameScore={score} ({why})")
        out.append(f"      [{f.get('index')}] " + " ".join(bits))
    out.append("    A username candidate must be visible, enabled, and not a "
               "password/hidden/checkbox/radio/submit/button/file input.")
    return "\n".join(out)


@dataclass
class LoginOutcome:
    ok: bool
    detail: str
    errors: list[str] = field(default_factory=list)


async def read_fields(frame: Any) -> dict[str, Any]:
    return await frame.evaluate(FIELDS_JS)


def _has_password(fields: dict[str, Any]) -> bool:
    return any(f["type"] == "password" and f["visible"] and not f["disabled"]
               for f in fields.get("inputs", []))


async def find_login_form(page: Any, timeout_s: float = 20.0) -> tuple[Any, dict[str, Any] | None]:
    """Locate the frame holding the login form.

    A single immediate look at the main frame is not enough for a real SPA:
    the form may render after `domcontentloaded`, or live in an iframe (an
    identity provider embed), which `page.locator` never sees. So every frame
    is inspected, repeatedly, until the form appears or we give up.

    There is no browser event for "a password field appeared in any frame", so
    this is the one place the tool polls - cheaply, and bounded.
    """
    deadline = time.monotonic() + timeout_s
    seen_frames = 0
    while True:
        frames = list(page.frames)
        seen_frames = max(seen_frames, len(frames))
        for frame in frames:
            try:
                fields = await read_fields(frame)
            except Exception:
                continue                      # frame navigating or cross-origin hiccup
            if _has_password(fields):
                where = "main frame" if frame is page.main_frame else f"iframe {frame.url[:80]}"
                log.info("Login form found in %s after %.1fs",
                         where, timeout_s - (deadline - time.monotonic()))
                return frame, fields
        if time.monotonic() >= deadline:
            log.debug("No login form in any of %d frame(s) within %.0fs", seen_frames, timeout_s)
            return None, None
        await asyncio.sleep(0.4)


async def describe_page(page: Any) -> str:
    """Diagnostics for when no login form turns up. Structure only, no values."""
    lines: list[str] = []
    try:
        lines.append(f"url={page.url}")
        for i, frame in enumerate(page.frames):
            try:
                info = await frame.evaluate(
                    """() => {
                         const vis = (e) => {
                           const r = e.getBoundingClientRect();
                           const s = getComputedStyle(e);
                           return r.width > 1 && r.height > 1 && s.display !== 'none' && s.visibility !== 'hidden';
                         };
                         const n = (s) => (s || '').replace(/\\s+/g, ' ').trim().slice(0, 60);
                         const btns = Array.from(document.querySelectorAll('button,[role=button],a[href],input[type=submit]'))
                           .filter(vis).map(e => n(e.getAttribute('aria-label') || e.value || e.textContent))
                           .filter(Boolean).slice(0, 12);
                         const types = {};
                         for (const e of document.querySelectorAll('input')) {
                           const t = (e.getAttribute('type') || 'text').toLowerCase();
                           types[t] = (types[t] || 0) + 1;
                         }
                         return { title: n(document.title), h1: n((document.querySelector('h1') || {}).textContent),
                                  inputs: types, iframes: document.querySelectorAll('iframe').length,
                                  controls: btns, ready: document.readyState };
                       }""")
                lines.append(f"  frame[{i}]{'(main)' if frame is page.main_frame else ''} "
                             f"url={frame.url[:90]} ready={info['ready']} title={info['title']!r} "
                             f"h1={info['h1']!r} inputs={info['inputs']} iframes={info['iframes']}")
                if info["controls"]:
                    lines.append(f"    visible controls: {info['controls']}")
            except Exception as exc:
                lines.append(f"  frame[{i}] url={frame.url[:90]} - could not inspect ({type(exc).__name__})")
    except Exception as exc:
        lines.append(f"(diagnostics failed: {type(exc).__name__})")
    return "\n".join(lines)


async def wait_until_no_password(page: Any, timeout_s: float = 30.0,
                                 should_cancel: Any = None) -> bool:
    """True once no frame shows a visible password field (i.e. we are past login).

    `should_cancel` is polled so a long manual-login wait can be superseded by
    the user pressing LOGIN instead.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        if should_cancel is not None and should_cancel():
            return False
        if page.is_closed():
            return False
        remaining = False
        for frame in list(page.frames):
            try:
                if _has_password(await read_fields(frame)):
                    remaining = True
                    break
            except Exception:
                continue                      # detached / navigating frame: not a login form
        if not remaining:
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.4)


APP_MARKERS_JS = r"""
() => {
  const vis = (e) => {
    const r = e.getBoundingClientRect();
    const s = getComputedStyle(e);
    return r.width > 1 && r.height > 1 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const count = (sel) => Array.from(document.querySelectorAll(sel)).filter(vis).length;
  return {
    landmarks: count('main,[role=main],nav,[role=navigation],[role=tablist],'
                     + '[role=toolbar],[role=grid],[role=treegrid],[role=tree]'),
    controls: count('button,[role=button],a[href],[role=tab],[role=menuitem]'),
    fields: count('input,select,textarea'),
    // A visible password field means this is a gate, not the application.
    passwords: count('input[type=password]'),
    // Evidence of a rendered data surface, for applications that use no ARIA
    // landmarks at all.
    dataRows: count('table tr,[role=row]')
  };
}
"""


def _app_markers_say_app(info: dict[str, Any]) -> bool:
    """Do these page markers describe the application rather than a gate?"""
    if info.get("passwords", 0):
        return False                    # a visible password field is a gate
    if info.get("landmarks", 0) >= 1 and info.get("controls", 0) >= 5:
        return True
    # An application built from tables (PhenomeOne is Dojo) has NO ARIA
    # landmarks at all - measured 2026-08-26: the fully rendered main frame
    # reported none, so the landmark requirement alone could never be met and
    # "already signed in" was unreachable. A rich control surface or a populated
    # data grid is equally strong evidence, and a sign-in page has neither: it
    # carries a couple of fields and one or two buttons.
    return info.get("controls", 0) >= 8 or info.get("dataRows", 0) >= 5


async def looks_authenticated(page: Any, wait_s: float = 0.0) -> bool:
    """Heuristic: does this page look like the application rather than a gate?

    Used only to distinguish "already signed in" from "the form has not rendered
    yet" - never to claim a successful sign-in on its own.

    `wait_s` polls for that long before giving up. It defaults to 0 so callers
    that need a fast, strict answer - Safe Crawl's session-loss check runs after
    every click - are unchanged. Interactive sign-in passes a real budget,
    because this application had painted no controls at all 38 s after load.
    """
    deadline = time.monotonic() + max(0.0, wait_s)
    while True:
        try:
            info = await page.evaluate(APP_MARKERS_JS)
        except Exception:
            info = {}
        if _app_markers_say_app(info):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.4)


_ENTRY_NAME = re.compile(r"^\s*(log ?in|sign ?in|log ?on|sign ?on)\s*$", re.I)


async def click_login_entry(page: Any) -> str:
    """Some apps show a landing page with a single "Sign in" entry point before
    the form itself. Clicking it is within the intent of pressing LOGIN, so it
    is allowed here - but only when exactly ONE visible control matches an
    unambiguous sign-in label. Nothing else is ever clicked.
    """
    for frame in page.frames:
        try:
            cands = await frame.evaluate(
                """() => {
                     const vis = (e) => {
                       const r = e.getBoundingClientRect();
                       const s = getComputedStyle(e);
                       return r.width > 1 && r.height > 1 && s.display !== 'none' && s.visibility !== 'hidden';
                     };
                     const n = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                     return Array.from(document.querySelectorAll('button,[role=button],a[href],input[type=submit]'))
                       .filter(vis)
                       .map((e, i) => ({ name: n(e.getAttribute('aria-label') || e.value || e.textContent) }))
                       .filter(c => c.name);
                   }""")
        except Exception:
            continue
        matches = [c["name"] for c in cands if _ENTRY_NAME.match(c["name"])]
        if len(matches) == 1:
            try:
                await frame.get_by_role("button", name=matches[0], exact=True).first.click(timeout=5000)
            except Exception:
                try:
                    await frame.get_by_role("link", name=matches[0], exact=True).first.click(timeout=5000)
                except Exception:
                    return ""
            return matches[0]
    return ""


async def perform_login(frame: Any, page: Any, username: str, password: str, plan: LoginPlan,
                        timeout_ms: int = 30000) -> LoginOutcome:
    """Fill and submit the analysed login form. Never logs credentials."""
    register_secret(password)
    if not plan.usable:
        return LoginOutcome(False, "form confidence too low: " + "; ".join(plan.reasons))

    inputs = frame.locator("input")
    try:
        if plan.username_index is not None:
            user_field = inputs.nth(plan.username_index)
            # Re-verify we are still pointing at a non-password field.
            if (await user_field.get_attribute("type") or "text").lower() == "password":
                return LoginOutcome(False, "page changed while filling; aborted before typing")
            await user_field.fill(username, timeout=10000)
        pwd_field = inputs.nth(plan.password_index)
        if (await pwd_field.get_attribute("type") or "").lower() != "password":
            return LoginOutcome(False, "password field moved; aborted before typing")
        await pwd_field.fill(password, timeout=10000)
    except Exception as exc:
        return LoginOutcome(False, f"could not fill the login form: {type(exc).__name__}")

    log.info("Login form filled; submitting")
    try:
        if plan.submit_by_enter or plan.submit_index is None:
            await inputs.nth(plan.password_index).press("Enter")
        else:
            btns = frame.locator('button, input[type="submit"], input[type="button"], [role="button"]')
            await btns.nth(plan.submit_index).click(timeout=10000)
    except Exception as exc:
        return LoginOutcome(False, f"could not submit the login form: {type(exc).__name__}")

    # Deterministic success signal: no visible password field remains anywhere.
    # Checked across frames because the form's own iframe is often torn down on
    # success - waiting on that frame alone would throw instead of succeeding.
    if not await wait_until_no_password(page, timeout_ms / 1000.0):
        errs: list[str] = []
        try:
            errs = (await read_fields(frame)).get("errors", [])
        except Exception:
            pass
        return LoginOutcome(False, "still on the login form after submitting", errs)

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    return LoginOutcome(True, "authenticated")
