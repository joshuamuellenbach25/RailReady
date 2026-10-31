"""Search Wikimedia Commons for rights-cleared tie/fastener photos; writes candidates.json (metadata only, no downloads)."""
import json, re, sys, time
import requests

UA = {"User-Agent": "RailReadyEvalBuilder/1.0 (image eval set; contact: builder@railready.example) requests"}
API = "https://commons.wikimedia.org/w/api.php"
QUERIES = sys.argv[1:] or [
    "rotten railroad tie", "railroad tie plate spike", "wooden railway sleeper rot", "railroad ties weathered",
    "tie plate cut spike", "railroad spike missing", "split railroad tie", "crosstie track United States",
    "railroad track wooden ties close up", "spike holes railroad tie", "Pandrol clip wooden sleeper",
    "screw spike railroad", "rail anchor tie plate", "railroad track ballast covered ties", "railroad track shadow ties",
    "abandoned railroad track ties", "railroad track vegetation overgrown ties",
]
OK = re.compile(r"^(CC0|Public domain|PD.*|CC BY(-SA)? ?[0-9.]+.*|CC-BY(-SA)?-[0-9.]+)$", re.I)


def strip(h):
    return re.sub(r"<[^>]+>", "", h or "").strip()


out = {}
for q in QUERIES:
    r = requests.get(API, headers=UA, params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"filetype:bitmap {q}", "gsrnamespace": 6,
        "gsrlimit": 25, "prop": "imageinfo", "iiprop": "url|sha1|extmetadata|size|mime", "iiurlwidth": 1280}).json()
    for p in (r.get("query", {}).get("pages") or {}).values():
        ii = p["imageinfo"][0]
        md = ii.get("extmetadata", {})
        lic = strip(md.get("LicenseShortName", {}).get("value"))
        if not OK.match(lic) or ii.get("mime") != "image/jpeg":
            continue
        out[p["title"]] = {
            "title": p["title"], "query": q, "page": ii["descriptionurl"], "thumb": ii.get("thumburl"), "w": ii["width"], "h": ii["height"],
            "license": lic, "license_url": strip(md.get("LicenseUrl", {}).get("value")), "author": strip(md.get("Artist", {}).get("value"))[:120],
            "date": strip(md.get("DateTimeOriginal", {}).get("value"))[:40], "desc": strip(md.get("ImageDescription", {}).get("value"))[:300],
            "categories": strip(md.get("Categories", {}).get("value"))[:300], "gps": bool(md.get("GPSLatitude")),
        }
    time.sleep(0.5)
json.dump(out, open("/app/eval/tie_fastener/tools/candidates.json", "w"), indent=1)
for v in out.values():
    print(f"{v['title'][5:70]!r} | {v['license']} | {v['author'][:25]} | {v['date'][:10]} | {v['desc'][:110]}")
print(len(out))
