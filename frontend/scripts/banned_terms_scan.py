"""Banned-term DOM text scan (phase 8 plain-language rule).

Scans visible text + title/aria-label/placeholder/alt of every screen people see as
landing visitor, customer (/p/:token), foreman and estimator. Admin Diagnostics is
excluded (it is the one place technical content may appear).

Standalone:  pip install playwright && playwright install chromium
             BASE=http://localhost:3000 python3 scripts/banned_terms_scan.py
In the screenshot tool: exec(open('/app/frontend/scripts/banned_terms_scan.py').read()); hits = await run_all(page, BASE)
"""
import asyncio
import json
import os
import re

BANNED = [
    r"\bJev\b", r"Claude", r"Whisper", r"Qwen", r"Depth Anything", r"(?-i:\bAI\b)", r"\bmodels?\b", r"provider", r"\bserver\b",
    r"backend", r"\bsync", r"upload", r"receipt", r"manifest", r"\bhash", r"\bbytes?\b", r"transcri", r"processing",
    r"confidence", r"probabilit", r"\bscores?\b", r"\bversion\b", r"\bprompt", r"Saved analysis", r"\bdepth\b", r"error code",
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-", r"\b[a-z]+_[a-z_]+\b", r"\b\d+(\.\d+)?\s?%",
]
RX = re.compile("|".join(f"(?:{b})" for b in BANNED), re.I)
# Phase 10 (U4): ASCII punctuation in owned copy + filler phrases + rhetorical Q&A openers.
PUNCT = re.compile("[\u2013\u2014\u2018\u2019\u201c\u201d\u2026\u00b7\u00d7\u2192\u2022]")
PHRASES = re.compile(r"seamless|leverag|\bdelve|\bunlock|revolutionar|genuinely|worth noting|something went wrong|the answer\?|why\? because", re.I)
# Exact viewer label required by the product spec for an older 3D revision kept on screen during a rebuild.
ALLOW = re.compile(r"Previous version shown")
# Pricing percentages (tax, markup, margin) are business numbers for the estimator, not scores.
PRICING = re.compile(r"\b(tax|markup|margin)\b|×", re.I)

SCAN_JS = """() => {
  const out = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) {
    const n = w.currentNode, el = n.parentElement;
    if (!el || ['SCRIPT','STYLE','NOSCRIPT'].includes(el.tagName)) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const t = n.textContent.trim(); if (t) out.push((el.closest('[data-raw]') ? '\u0000RAW' : '') + t);
  }
  document.querySelectorAll('[title],[aria-label],[placeholder],img[alt]').forEach(e => ['title','aria-label','placeholder','alt'].forEach(a => { const v = e.getAttribute(a); if (v) out.push(v); }));
  return out;
}"""


ESCAPE = re.compile(r"\\u(201[3489cdCD]|2026|00[bB]7|00[dD]7|2192|2022)")
SRC_ALLOW = re.compile(r"\.replace\(/|PRICING|ALLOW")  # regexes that match server text, not owned copy


def source_scan(root=os.environ.get("SRC_DIR", "/app/frontend/src")):
    """Static check of owned copy: non-ASCII punctuation, written literally or as \\uXXXX escapes, in src/**/*.js(x).
    Catches strings on states the DOM walk never reaches (rare errors, busy labels)."""
    hits = []
    for d, _, files in os.walk(root):
        for f in files:
            if not f.endswith((".js", ".jsx")):
                continue
            p = os.path.join(d, f)
            for i, line in enumerate(open(p, encoding="utf-8"), 1):
                if SRC_ALLOW.search(line):
                    continue
                for m in list(PUNCT.finditer(line)) + list(ESCAPE.finditer(line)):
                    hits.append(f"{os.path.relpath(p, root)}:{i}: {m.group(0)!r}  <<  {line.strip()[:100]}")
    print(f"[{'PASS' if not hits else 'FAIL'}] source scan: {len(hits)} hit(s)")
    for h in hits[:20]:
        print("     ", h)
    return hits


async def scan(page, label, hits):
    await page.wait_for_timeout(1800)
    texts = await page.evaluate(SCAN_JS)
    found = set()
    for t in texts:
        raw = t.startswith("\u0000RAW")  # server evidence / provider text / issued documents: never altered, punctuation not scored
        t = t.replace("\u0000RAW", "")
        found |= {m.group(0) + "  <<  " + t[:110] for m in RX.finditer(ALLOW.sub("", t)) if not (m.group(0).rstrip().endswith("%") and PRICING.search(t))}
        found |= {"phrase:" + m.group(0) + "  <<  " + t[:110] for m in PHRASES.finditer(t)}
        if not raw:
            found |= {"punct:" + repr(m.group(0)) + "  <<  " + t[:110] for m in PUNCT.finditer(t)}
    found = sorted(found)
    hits[label] = found
    print(f"[{'PASS' if not found else 'FAIL'}] {label}: {len(found)} hit(s)")
    for f in found[:12]:
        print("     ", f)


async def login(page, base, email):
    await page.goto(f"{base}/login")
    await page.fill('[data-testid="login-email-input"]', email)
    await page.fill('[data-testid="login-password-input"]', os.environ["SEED_PASSWORD"])
    await page.click('[data-testid="login-submit-button"]')
    await page.wait_for_url("**/office/**", timeout=20000)


async def hrefs(page, part):
    return await page.eval_on_selector_all(f'a[href*="{part}"]', "els => [...new Set(els.map(e => e.getAttribute('href')))]")


async def run_all(page, base, customer_path=None):
    hits = {"source scan": source_scan()}
    for p in ["/", "/demo", "/login"]:
        await page.goto(base + p)
        await scan(page, f"landing {p}", hits)
    # estimator via a fresh demo workspace
    await page.goto(base + "/")
    await page.click('[data-testid="open-demo-button"]')
    try:
        await page.wait_for_url("**/office/jobs", timeout=40000)
    except Exception:
        await scan(page, "landing / (demo could not open)", hits)
        print("NOTE: demo workspace did not open – scanning as the seeded estimator instead")
        await page.evaluate("localStorage.clear()")
        await login(page, base, "estimator@ridgeline.example")
        await page.goto(base + "/office/jobs")
    await scan(page, "estimator /office/jobs", hits)
    visits = [h for h in await hrefs(page, "/office/visits/") if h.count("/") == 3][:4]
    props = (await hrefs(page, "/office/proposals/"))[:1]
    for v in visits:
        await page.goto(base + v)
        await page.wait_for_selector('[data-testid="review-page"], [role="alert"]', timeout=30000)
        await scan(page, f"estimator {v}", hits)
    if visits:
        for sub in ["/estimate", "/scene"]:
            await page.goto(base + visits[-1] + sub)
            await page.wait_for_timeout(4000)
            await scan(page, f"estimator {visits[-1]}{sub}", hits)
    for p in props:
        await page.goto(base + p)
        await scan(page, f"estimator {p}", hits)
        wo = await hrefs(page, "/office/work-orders/")
        for w in wo[:1]:
            await page.goto(base + w)
            await scan(page, f"estimator {w}", hits)
    for p in ["/office/contracts", "/office/inbox", "/office/settings/templates", "/office/settings/templates/tpl-tie-replacement", "/office/settings/processing", "/office/diagnostics"]:
        await page.goto(base + p)
        await scan(page, f"estimator {p}", hits)
    await page.goto(base + "/office/contracts")
    await page.wait_for_timeout(2000)
    c = await hrefs(page, "/office/contracts/")
    for x in c[:1]:
        await page.goto(base + x)
        await scan(page, f"estimator {x}", hits)
    if customer_path:
        await page.goto(base + customer_path)
        await scan(page, f"customer {customer_path.split('/p/')[0]}/p/<link>", hits)
    # dynamic states (errors / empty / not found / loading)
    for p in ["/office/visits/does-not-exist", "/office/visits/does-not-exist/scene", "/office/proposals/does-not-exist", "/office/work-orders/does-not-exist", "/no-such-page"]:
        await page.goto(base + p)
        await scan(page, f"error-state {p}", hits)
    await page.goto(base + "/office/jobs", wait_until="commit")
    await page.wait_for_timeout(150)
    texts = await page.evaluate(SCAN_JS)
    print("  loading-state sample:", [t for t in texts if "oad" in t][:3])
    await scan(page, "loading-state /office/jobs", hits)
    await page.goto(base + "/p/not-a-real-link")
    await scan(page, "error-state customer /p/<bad>", hits)
    await page.evaluate("localStorage.clear()")
    await page.goto(f"{base}/login")
    await page.fill('[data-testid="login-email-input"]', "nobody@example.com")
    await page.fill('[data-testid="login-password-input"]', "wrong-password")
    await page.click('[data-testid="login-submit-button"]')
    await page.wait_for_timeout(1500)
    await scan(page, "error-state login wrong password", hits)
    # foreman
    await page.evaluate("localStorage.clear()")
    await login(page, base, "foreman@ridgeline.example")
    await scan(page, "foreman /office/inbox", hits)
    fv = [h for h in await hrefs(page, "/office/visits/") if h.count("/") == 3][:2]
    for v in fv:
        await page.goto(base + v)
        await page.wait_for_timeout(2500)
        await scan(page, f"foreman {v}", hits)
    await page.goto(base + "/office/diagnostics")
    await scan(page, "foreman /office/diagnostics", hits)
    total = sum(len(v) for v in hits.values())
    print(f"SUMMARY: {len(hits)} screens, {total} hits, {'PASS' if total == 0 else 'FAIL'}")
    return hits


async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        page = await b.new_page(viewport={"width": 1440, "height": 900})
        hits = await run_all(page, os.environ.get("BASE", "http://localhost:3000"), os.environ.get("CUSTOMER_PATH"))
        print(json.dumps(hits, indent=1))
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
