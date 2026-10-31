"""Download selected rights-cleared Commons images (1280px thumbnails), record provenance. Idempotent."""
import hashlib, json, os, re, time
import requests
from search_commons_lib import UA, API, OK, strip

ROOT = "/app/eval/tie_fastener"
# (title, capture_group, country, notes_for_reviewer) — capture group = same photographer + same day/site
SEL = [
    ("Tie plate 20-10-17 058.jpg", "g-light-demotte-2020", "US", ""),
    ("Two Types of Rail Fastening Systems.jpg", "g-trainsandotherthings-2021", "US", ""),
    ("Track attachments 2.jpg", "g-downtowngal-2011", "US", ""),
    ("Railroad Tie Plate 1.jpg", "g-abair-2026", "US", ""),
    ("Railroad Tie Plate 2.jpg", "g-abair-2026", "US", ""),
    ("Railroad Tie Plate 3.jpg", "g-abair-2026", "US", ""),
    ("Plate 19-10-16 424.jpg", "g-light-madison-2019", "US", ""),
    ("Rail spike 3039.jpg", "g-light-plymouth-2021", "US", ""),
    ("Rail spikes 3063.jpg", "g-light-plymouth-2021", "US", ""),
    ("Rail bolt 3036.jpg", "g-light-plymouth-2021", "US", ""),
    ("Weathered Railroad Ties of the BAT.JPG", "g-joeyfeets-2015", "US", ""),
    ("Railroad Tracks.jpg", "g-powerkites-2008", "US", ""),
    ("Found the Tracks (6254499907).jpg", "g-cogdog-2011", "US", ""),
    ("Damage from Hurricane Ida, New York, USA (9426).jpg", "g-hermann-ida-2021", "US", ""),
    ("Railroad tracks damaged in flood, 1932.jpg", "g-seattle-1932", "US", ""),
    ("New Ties for new track at Sunnyside Yard.jpg", "g-bonnachoven", "US", ""),
    ("End of railway siding and ties by Tustin station.jpg", "g-xnatedawgx-2016", "US", ""),
    ("Close-up Railroad Track Spike PLC-RR-6.jpg", "g-shadowmeld-2014", "UNKNOWN", ""),
    ("Middle-prong-trail-tennessee.jpg", "g-stansberry-2007", "US", ""),
    ("Gillette Castle Railroad Remains.jpg", "g-dimartino-gillette", "US", ""),
    ("Coprinus disseminatus around railroad spike 2.jpg", "g-treetale-2009", "UNKNOWN", ""),
    ("Weekend work 2012-01-30 19 (6789438989).jpg", "g-mta-2012-01", "US", ""),
    ("Humbertren.jpg", "g-humberto-2007", "US", ""),
    ("PanamaRR Rail Spike Tie.jpg", "g-centpacrr-panama", "PA", "supplementary non-US"),
    ("Abandoned railroad ties, near Elmira, PEI. (35078267016).jpg", "g-larry-pei-2017", "CA", "supplementary non-US"),
    ("Rusty track hardware, Orangeville-Brampton Railway, Caledon.jpg", "g-edk7-2006", "CA", "supplementary non-US"),
    ("Old Railway Sleeper - geograph.org.uk - 1776512.jpg", "g-dace-2010", "GB", "supplementary non-US"),
    ("Dwarsligger - zweden.JPG", "g-spoorjan-2007", "SE", "supplementary non-US"),
    ("20050518 trasliper m heyback o ralspik.JPG", "g-strandberg-2005", "SE", "supplementary non-US; same capture group as Phase-1 dev photo tie_old_rotten"),
    ("Pandrol-on-wooden.jpg", "g-wong-au", "AU", "supplementary non-US"),
    ("Dogspike-on-wooden.jpg", "g-wong-au", "AU", "supplementary non-US"),
    ("Vía sobre durmientes de madera 08.jpg", "g-durmientes-ar", "AR", "supplementary non-US"),
    ("Deserted railroad (2495337012).jpg", "g-titkov-2008", "RU", "supplementary non-US"),
    ("Deserted railroad (2495337044).jpg", "g-titkov-2008", "RU", "supplementary non-US"),
    ("Missoula (MT, USA), Fort Missoula, Historical Museum, Railroad Track -- 2022 -- 2353.jpg", "g-rabich-missoula-2022", "US", ""),
    ("Missoula (MT, USA), Fort Missoula, Historical Museum, Railroad Track -- 2022 -- 2355.jpg", "g-rabich-missoula-2022", "US", ""),
    ("Track repair materials at Dovey Junction - geograph.org.uk - 580904.jpg", "g-olu-dovey-2007", "GB", "supplementary non-US"),
]


def resolve(title):
    r = requests.get(API, headers=UA, params={"action": "query", "format": "json", "titles": "File:" + title, "prop": "imageinfo",
                                             "iiprop": "url|extmetadata|mime|size", "iiurlwidth": 1280}).json()
    p = next(iter(r["query"]["pages"].values()))
    if "imageinfo" not in p:
        r = requests.get(API, headers=UA, params={"action": "query", "format": "json", "list": "search", "srnamespace": 6,
                                                 "srsearch": "intitle:" + re.sub(r"[^\w ]", " ", title[:50]), "srlimit": 1}).json()
        hits = r["query"]["search"]
        return resolve(hits[0]["title"][5:]) if hits and hits[0]["title"][5:] != title else None
    return p["title"][5:], p["imageinfo"][0]


os.makedirs(f"{ROOT}/originals", exist_ok=True)
rows, n = [], 0
for title, grp, country, notes in SEL:
    got = resolve(title)
    if not got:
        print("MISSING", title); continue
    real, ii = got
    md = ii["extmetadata"]
    lic = strip(md.get("LicenseShortName", {}).get("value"))
    if not OK.match(lic):
        print("SKIP license", real, lic); continue
    n += 1
    fid = f"wc{n:03d}"
    path = f"{ROOT}/originals/{fid}.jpg"
    if not os.path.exists(path):
        b = requests.get(ii.get("thumburl") or ii["url"], headers=UA, timeout=60).content
        if b[:3] != b"\xff\xd8\xff":
            print("NOT JPEG", real, b[:60]); n -= 1; continue
        open(path, "wb").write(b)
        time.sleep(0.6)
    b = open(path, "rb").read()
    rows.append({"id": fid, "file": f"originals/{fid}.jpg", "sha256": hashlib.sha256(b).hexdigest(), "source_title": real,
                 "source_url": ii["descriptionurl"], "license": lic, "license_url": strip(md.get("LicenseUrl", {}).get("value")),
                 "author": strip(md.get("Artist", {}).get("value"))[:200], "credit": strip(md.get("Credit", {}).get("value"))[:200],
                 "date_original": strip(md.get("DateTimeOriginal", {}).get("value"))[:60],
                 "source_description": strip(md.get("ImageDescription", {}).get("value"))[:400],
                 "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "capture_group": grp, "country": country,
                 "builder_notes": notes, "transformations": "resize: Commons 1280px-wide thumbnail of original (Commons-rendered)",
                 "derivative_of": None, "kind": "photo"})
    print(fid, real[:60], lic)
json.dump(rows, open(f"{ROOT}/tools/originals.json", "w"), indent=1)
print(len(rows))
