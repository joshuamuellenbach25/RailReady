"""Build manifest (CSV+JSON), derivatives, splits and the locked_test lock file. Refuses to rewrite the lock once it exists."""
import csv, hashlib, json, os, time
from PIL import Image, ImageEnhance, ImageFilter

ROOT = "/app/eval/tie_fastener"
OV = None  # B7: supplementary overhead collection archived (/tmp/archive/supplementary_overhead.tar); not an active input
LOCK = f"{ROOT}/locked_test.lock.json"
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()

# Builder triage of downloaded files (from contact sheet). Not labels: only scope exclusions.
EXCLUDE = {"wc008": "loose spike on brick paving, not an in-place tie", "wc009": "loose spikes on ballast, no tie",
           "wc010": "loose bolt on ballast, no tie", "wc015": "1932 B&W flood scene, ties not discernible",
           "wc016": "distant yard with concrete ties", "wc019": "loose rail on leaves, no tie",
           "wc024": "museum display object, not track"}
DEV_GROUPS = {"g-strandberg-2005", "g-phase1-coledale", "g-phase1-baumeler", "g-phase1-strandberg-2005"}
LABEL_FIELDS = ["tie_deterioration", "missing_or_displaced_fastener", "unused_holes_present", "label_regions", "reviewer", "reviewed_at", "notes"]
# Builder proposals for reviewer convenience only (from source captions / visual impression). NOT ground truth.
PROPOSED = {"wc027": "tie_deterioration=present? (source caption: 'old sleeper rotting away')",
            "wc037": "tie_deterioration=present? (source caption: sleepers rotting)",
            "wc028": "missing_or_displaced_fastener=present? (source caption: 'afgebroken bevestiging' = broken fastening)",
            "wc021": "tie_deterioration=present? (fungus growing on tie end)",
            "wc025": "cannot_assess? (vegetation-covered abandoned ties)",
            "p1-tie_disintegrated": "tie_deterioration=present? (Phase-1 positive)", "p1-negative_coledale": "absent/absent? (Phase-1 negative)",
            "p1-obscured_coledale_blurred": "cannot_assess? (synthetic blur)"}

rows = []
for r in json.load(open(f"{ROOT}/tools/originals.json")):
    r = dict(r)
    if r["id"] in EXCLUDE:
        r["kind"], r["exclusion_reason"] = "excluded_out_of_scope", EXCLUDE[r["id"]]
    rows.append(r)

# Phase-1 photos: permanently dev (referenced in place).
P1 = {"tie_disintegrated.jpg": ("g-phase1-baumeler", "https://commons.wikimedia.org/wiki/File:Disintegrated_railroad_tie.jpg", "CC BY-SA 4.0", "Hp.Baumeler", "CH"),
      "tie_old_rotten.jpg": ("g-phase1-strandberg-2005", "https://commons.wikimedia.org/wiki/File:20050518_gammal_trasliper.jpg", "CC BY-SA 2.5", "Per Erik Strandberg (sv:User:PER9000)", "SE"),
      "negative_coledale.jpg": ("g-phase1-coledale", "https://commons.wikimedia.org/wiki/File:Train_tracks_in_Coledale.jpg", "CC BY-SA 2.5", "Sam Wilson", "AU"),
      "obscured_coledale_blurred.jpg": ("g-phase1-coledale", "derivative of negative_coledale.jpg", "CC BY-SA 2.5", "Sam Wilson (derivative by RailReady builder)", "AU")}
for f, (g, url, lic, au, c) in P1.items():
    p = f"/app/backend/test_photos/{f}"
    rows.append({"id": "p1-" + f[:-4], "file": p, "sha256": sha(p), "source_url": url, "license": lic, "author": au, "capture_group": g,
                 "country": c, "kind": "photo", "derivative_of": "p1-negative_coledale" if "blurred" in f else None,
                 "transformations": "Gaussian blur r=14, brightness 0.45" if "blurred" in f else "Commons 1280px thumbnail",
                 "builder_notes": "Phase-1 photo: permanently dev (used for prompt iteration)", "retrieved_at": "2026-10-24"})

# Derivatives (same capture group => same split as source).
os.makedirs(f"{ROOT}/derivatives", exist_ok=True)
DER = [("wc004", "blur", "Gaussian blur r=12"), ("wc023", "dark", "brightness 0.25"), ("wc001", "crop", "crop left 50% of width")]
by = {r["id"]: r for r in rows}
for src, tag, desc in DER:
    s = by[src]; out = f"{ROOT}/derivatives/{src}_{tag}.jpg"
    if not os.path.exists(out):
        im = Image.open(f"{ROOT}/{s['file']}").convert("RGB")
        im = im.filter(ImageFilter.GaussianBlur(12)) if tag == "blur" else ImageEnhance.Brightness(im).enhance(0.25) if tag == "dark" else im.crop((0, 0, im.width // 2, im.height))
        im.save(out, quality=90)
    rows.append({**{k: s[k] for k in ("source_url", "source_title", "license", "license_url", "author", "capture_group", "country")},
                 "id": f"{src}-{tag}", "file": f"derivatives/{src}_{tag}.jpg", "sha256": sha(out), "kind": "photo", "derivative_of": src,
                 "transformations": f"{desc} (applied by builder to {src})", "builder_notes": "synthetic derivative", "retrieved_at": s["retrieved_at"]})

# Supplementary overhead (referenced by path + sha256; originals untouched). Hudson stills + videos = ONE capture group.
# B7 archived: stills = json.load(open(f"{OV}/photos/US_WOOD_TIE_STILLS_MANIFEST.json"))
# B7 archived: for rec in stills["records"]:
# B7 archived:     p = f"{OV}/{rec['file']}"
# B7 archived:     rows.append({"id": "ov-" + os.path.basename(rec["file"])[:-4], "file": p, "sha256": rec["sha256"], "source_url": rec["source_url"],
# B7 archived:                  "license": rec["license"], "license_url": rec["license_url"], "author": rec["author"], "capture_group": "g-hudson-video",
# B7 archived:                  "country": "US", "location": rec.get("source_location"), "kind": "supplementary_overhead", "derivative_of": "connecthv_hudson_public_square (video)",
# B7 archived:                  "transformations": rec["transform"], "builder_notes": "3 frames of ONE real video, not independent captures; no verified defect label (verbatim manifest: defect_label=null)"})
# B7 archived: uav = json.load(open(f"{OV}/PHOTO_MANIFEST.json"))["photos"]
# B7 archived: for rec in (uav[0], uav[157]):
# B7 archived:     rows.append({"id": "ov-" + rec["id"], "file": f"{OV}/{rec['path']}", "sha256": rec["sha256"], "source_url": rec["source_url"], "license": rec["license"],
# B7 archived:                  "license_url": rec["license_url"], "author": rec["author"], "capture_group": "g-uav-rsod", "country": rec.get("country", "India"),
# B7 archived:                  "tie_material": "concrete", "kind": "supplementary_overhead", "transformations": "none (unchanged original)", "derivative_of": None,
# B7 archived:                  "builder_notes": "UAV-RSOD: concrete ties, India, physically staged obstacles; NOT U.S. wood-tie defect ground truth; not extra defect classes"})

for r in rows:
    r.setdefault("tie_material", "wood" if r["kind"] != "supplementary_overhead" else "wood")
    r["split"] = "dev" if r["capture_group"] in DEV_GROUPS else "locked_test"
    r["supplementary"] = r["country"] != "US" or r["kind"] == "supplementary_overhead"
    r["proposed_label_NOT_GROUND_TRUTH"] = PROPOSED.get(r["id"], "")
    for k in LABEL_FIELDS:
        r.setdefault(k, "UNKNOWN" if k in ("tie_deterioration", "missing_or_displaced_fastener", "unused_holes_present") else "")
    for k in ("location", "fastening_type", "viewpoint", "lighting"):
        r.setdefault(k, "UNKNOWN")
    # verify bytes match recorded hash
    path = r["file"] if r["file"].startswith("/") else f"{ROOT}/{r['file']}"
    assert sha(path) == r["sha256"], r["id"]

json.dump(rows, open(f"{ROOT}/manifest.json", "w"), indent=1)
cols = list(dict.fromkeys(k for r in rows for k in r))
with open(f"{ROOT}/manifest.csv", "w", newline="") as f:
    w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)

test = sorted((r["id"], r["sha256"]) for r in rows if r["split"] == "locked_test" and r["kind"] != "excluded_out_of_scope")
if os.path.exists(LOCK):
    old = json.load(open(LOCK))
    assert sorted(map(tuple, old["items"])) == test, "locked_test changed after lock — bump and report contamination"
    print("lock verified", old["locked_at"])
else:
    json.dump({"locked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "note": "locked before any revised-prompt run on these ids",
               "items": test}, open(LOCK, "w"), indent=1)
    print("lock written")
from collections import Counter
print(Counter((r["split"], r["kind"], r["supplementary"]) for r in rows))
