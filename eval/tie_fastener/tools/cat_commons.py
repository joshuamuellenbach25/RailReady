"""List rights-cleared JPEGs in Commons categories (metadata only). Appends to candidates.json."""
import json, re, sys, time, requests
from search_commons_lib import UA, API, OK, strip
out = json.load(open("candidates.json"))
for c in sys.argv[1:]:
    r = requests.get(API, headers=UA, params={"action": "query", "format": "json", "generator": "categorymembers", "gcmtitle": "Category:" + c,
        "gcmtype": "file", "gcmlimit": 60, "prop": "imageinfo", "iiprop": "url|sha1|extmetadata|size|mime", "iiurlwidth": 1280}).json()
    pages = (r.get("query", {}).get("pages") or {}).values()
    print("##", c, len(pages))
    for p in pages:
        if "imageinfo" not in p: continue
        ii = p["imageinfo"][0]; md = ii.get("extmetadata", {})
        lic = strip(md.get("LicenseShortName", {}).get("value"))
        if not OK.match(lic) or ii.get("mime") != "image/jpeg": continue
        out[p["title"]] = {"title": p["title"], "query": "Category:" + c, "page": ii["descriptionurl"], "thumb": ii.get("thumburl"), "w": ii["width"], "h": ii["height"],
            "license": lic, "license_url": strip(md.get("LicenseUrl", {}).get("value")), "author": strip(md.get("Artist", {}).get("value"))[:120],
            "date": strip(md.get("DateTimeOriginal", {}).get("value"))[:40], "desc": strip(md.get("ImageDescription", {}).get("value"))[:300]}
        v = out[p["title"]]; print(f"{v['title'][5:60]!r}|{lic}|{v['author'][:18]}|{v['date'][:10]}|{v['desc'][:90]!r}")
    time.sleep(0.5)
json.dump(out, open("candidates.json", "w"), indent=1)
