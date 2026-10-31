"""Emergent-managed email (Resend behind the Emergent integration proxy). Used only by the invoice email channel.
Recipients come from the operator config (server side), bodies from the server template in routes_repair. Every attempt is
recorded in db.email_sends (to, subject, status, provider id) so deliveries can be audited."""
import ipaddress
import logging
import os
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from core import db, iso

logger = logging.getLogger(__name__)
EMAIL_BASE_URL = "https://integrations.emergentagent.com"  # constant by design (survives deployment)


class EmailRefused(Exception):
    """The provider definitely did not accept the email (safe to retry later)."""


class EmailUnknown(Exception):
    """The request may have reached the provider; the outcome is unknown (never auto-resend)."""


def connected() -> bool:
    return bool(os.environ.get("EMERGENT_EMAIL_KEY") and os.environ.get("EMAIL_FROM_NAME"))


# ---- guardrail gate (from the integration playbook; call on every send) ----
_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "reply with the code", "send your password", "cvv",
             "send us your password", "enter your password below", "confirm your card number",
             "your full card number", "seed phrase", "recovery phrase", "verify your card",
             "social security number", "confirm your bank details")
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan()
    scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} does not match link host {real!r} (G3)")


async def _post(payload: dict) -> httpx.Response:
    """The only network call. Tests replace this function."""
    async with httpx.AsyncClient(timeout=30) as client:
        return await client.post(f"{EMAIL_BASE_URL}/api/v1/email/send", headers={"X-Email-Key": os.environ["EMERGENT_EMAIL_KEY"]}, json=payload)


async def send(*, to: str, subject: str, html: str, key: str, workspace_id: str) -> str:
    """One recipient (from server-side config). Returns the provider id. Raises EmailRefused / EmailUnknown."""
    if not connected():
        raise EmailRefused("Email sending not connected")
    _assert_safe_email(subject, html)
    rec = {"key": key, "to": to, "subject": subject, "workspace_id": workspace_id, "status": "Sending", "at": iso()}
    await db.email_sends.insert_one(rec)
    payload = {"to": [to], "subject": subject, "html": html, "from_name": os.environ["EMAIL_FROM_NAME"]}
    try:
        resp = await _post(payload)
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:  # never reached the provider
        await db.email_sends.update_one({"_id": rec["_id"]}, {"$set": {"status": "Refused", "error": type(e).__name__}})
        raise EmailRefused("Email service unreachable. Try again.")
    except Exception as e:  # may have reached the provider
        await db.email_sends.update_one({"_id": rec["_id"]}, {"$set": {"status": "Unknown", "error": type(e).__name__}})
        raise EmailUnknown("Delivery result unknown. Check with the recipient before sending again.")
    if resp.status_code in (200, 201, 202):
        pid = (resp.json() or {}).get("id")
        await db.email_sends.update_one({"_id": rec["_id"]}, {"$set": {"status": "Accepted", "provider_id": pid}})
        return pid
    try:
        code = resp.json().get("code", "")
    except ValueError:
        code = ""
    status = "Unknown" if resp.status_code >= 500 else "Refused"
    await db.email_sends.update_one({"_id": rec["_id"]}, {"$set": {"status": status, "http_status": resp.status_code, "code": code}})
    logger.warning("email send %s: %s %s", status, resp.status_code, code)
    if status == "Unknown":
        raise EmailUnknown("Delivery result unknown. Check with the recipient before sending again.")
    raise EmailRefused("Email service is unavailable right now." if code in ("insufficient_credits", "integration_disabled", "daily_limit_reached")
                       else f"Email refused ({resp.status_code}).")
