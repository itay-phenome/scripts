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
    landmarks: count('main,[role=main],nav,[role=navigation],[role=tablist]'),
    controls: count('button,[role=button],a[href],[role=tab],[role=menuitem]'),
    fields: count('input,select,textarea')
  };
}
"""


async def looks_authenticated(page: Any) -> bool:
    """Heuristic: does this page look like the application rather than a gate?

    Used only to distinguish "already signed in" from "the form has not rendered
    yet" - never to claim a successful sign-in on its own.
    """
    try:
        info = await page.evaluate(APP_MARKERS_JS)
    except Exception:
        return False
    return bool(info.get("landmarks", 0) >= 1 and info.get("controls", 0) >= 5)


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
