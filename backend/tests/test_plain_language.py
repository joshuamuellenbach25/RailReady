"""Phase 8: banned-term scan of user-visible mobile text (JSX text nodes and visible string props).

Run: python /app/backend/tests/test_plain_language.py [--list]
Exits 1 if any user-visible string contains an internal/technical term. Admin-only diagnostics screens are exempt.
"""
import os
import pathlib
import re
import sys

ROOT = pathlib.Path("/app/mobile")
EXEMPT = {"app/camera-smoke.tsx", "app/diagnostics.tsx", "src/crumbs.ts"}  # admin/support diagnostics only
BANNED = re.compile(r"\b(jev|claude|whisper|sonnet|gpt|llm|ai|model|models|server|servers|backend|sync|syncs|synced|syncing|upload|uploads|uploaded|uploading|"
                    r"transcription|transcribe|processing|processed|confidence|probability|score|hash|sha-?256|bytes|receipt|"
                    r"json|api|error code|http|candidate|candidates|extraction|policy|template|verified|manifest|uuid|id)\b|%", re.I)
VISIBLE_PROPS = r"(?:title|label|text|subtitle|placeholder|accessibilityLabel)"
PATTERNS = [
    re.compile(r">([^<>{}\n]*[A-Za-z][^<>{}\n]*)<"),                       # JSX text nodes
    re.compile(VISIBLE_PROPS + r"=\"([^\"]+)\""),                        # title="…"
    re.compile(VISIBLE_PROPS + r"=\{`([^`]+)`\}"),                         # title={`…`}
    re.compile(r"(?:flash|setErr|setToast|setMsg)\(\s*[`\"]([^`\"]+)[`\"]"),  # toasts/errors
    re.compile(r"text: [`\"]([^`\"]+)[`\"]"),
    # string literals inside JSX expressions / helpers that start with a capital (e.g. ternaries, procLine, status maps)
    re.compile(r"(?<![\w.])[\"`]([A-Z][A-Za-z’' ,.:–\-()]{3,}[^\"`]*)[\"`]"),
]
SKIP_LINE = re.compile(r"^\s*(import|//|\*)|testID=|icon=|name=|kind=|fontWeight|routes?\b|pathname|\.push\(|STATUS|case \"|=== \"|!== \"|status: \"|\"Content-Type\"|^\s*\"?[A-Za-z ]+\"?: \{ icon|const PLAIN|^\s*\"[A-Za-z ]+\": \"")


def visible_strings(src: str):
    lines = src.split("\n")
    seen = set()
    for p in PATTERNS:
        for m in p.finditer(src):
            ln = src.count("\n", 0, m.start()) + 1
            if p is PATTERNS[-1] and SKIP_LINE.search(lines[ln - 1]):
                continue
            s = re.sub(r"\$\{[^}]*\}", " ", m.group(1)).strip()
            if s and not s.startswith(("http", "/")) and (ln, s) not in seen:
                seen.add((ln, s))
                yield ln, s


def scan():
    hits = []
    for f in sorted(list(ROOT.glob("app/**/*.tsx")) + list(ROOT.glob("src/**/*.tsx"))):
        rel = str(f.relative_to(ROOT))
        if rel in EXEMPT or "/node_modules/" in rel:
            continue
        for line, s in visible_strings(f.read_text()):
            m = BANNED.search(s) or NON_ASCII.search(s)
            if m:
                hits.append((rel, line, m.group(0), s[:90]))
    return hits


NON_ASCII = re.compile(r"[^\x00-\x7f]")  # B8/U4: user-facing copy is plain ASCII


def api_scan(base="http://localhost:8001/api"):
    """Scan the plain view model (GET /visits/{id}/review-questions) for banned terms."""
    import requests
    tok = requests.post(f"{base}/auth/login", json={"email": "foreman@ridgeline.example", "password": os.environ["SEED_PASSWORD"]}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    hits = []
    vids = [i["visit_id"] for i in requests.get(f"{base}/inspections", headers=h, params={"status": "all"}).json()["inspections"]]
    for vid in vids or ["v-seed-pinecrest", "v-seed-cascade"]:
        v = {"uuid": vid}
        d = requests.get(f"{base}/visits/{v['uuid']}/review-questions", headers=h).json()
        for q in d.get("questions", []):
            texts = [q.get("text"), q.get("hint"), q.get("detail"), q.get("label")] + [c["label"] for c in q.get("choices", [])]
            hits += [(v["uuid"], t) for t in texts if t and (BANNED.search(t) or NON_ASCII.search(t))]
        if d.get("summary") and BANNED.search(d["summary"]):
            hits.append((v["uuid"], d["summary"]))
    return hits


if __name__ == "__main__":
    hits = scan()
    for h in hits:
        print(f"{h[0]}:{h[1]}  [{h[2]}]  {h[3]}")
    print(f"{len(hits)} banned-term hit(s)")
    if "--api" in sys.argv:
        ah = api_scan()
        for v, t in ah:
            print(f"API {v}: {t}")
        print(f"{len(ah)} banned-term hit(s) in review-questions")
        hits += ah
    sys.exit(1 if hits else 0)
