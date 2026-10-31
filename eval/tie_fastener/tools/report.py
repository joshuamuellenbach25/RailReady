"""Build review_sheet.csv (if absent), contact_sheet.html and REPORT.md from manifest + results.
Labels come ONLY from review_sheet.csv rows with a reviewer; everything else is UNKNOWN and excluded from metrics."""
import csv, html, json, os, statistics
from collections import Counter, defaultdict

ROOT = "/app/eval/tie_fastener"
CATS = {"tie_deterioration": "visible tie-surface deterioration", "missing_or_displaced_fastener": "possible missing/displaced fastener"}
rows = json.load(open(f"{ROOT}/manifest.json"))
runnable = [r for r in rows if r["kind"] != "excluded_out_of_scope"]
lock = json.load(open(f"{ROOT}/locked_test.lock.json"))
res = defaultdict(dict)
for f in os.listdir(f"{ROOT}/results"):
    d = json.load(open(f"{ROOT}/results/{f}"))
    res[d["prompt_version"]][d["id"]] = d
PVS = sorted(res)

# ---- review sheet (never overwritten once a human may have edited it) ----
SHEET = f"{ROOT}/review_sheet.csv"
SCOLS = ["id", "split", "supplementary", "kind", "thumbnail", "source_url", "proposed_label_NOT_GROUND_TRUTH",
         "tie_deterioration", "missing_or_displaced_fastener", "unused_holes_present", "label_regions", "reviewer", "reviewed_at", "notes"]
if not os.path.exists(SHEET):
    with open(SHEET, "w", newline="") as f:
        w = csv.DictWriter(f, SCOLS); w.writeheader()
        for r in runnable:
            w.writerow({"id": r["id"], "split": r["split"], "supplementary": r["supplementary"], "kind": r["kind"], "thumbnail": r["file"],
                        "source_url": r["source_url"], "proposed_label_NOT_GROUND_TRUTH": r["proposed_label_NOT_GROUND_TRUTH"],
                        "tie_deterioration": "UNKNOWN", "missing_or_displaced_fastener": "UNKNOWN", "unused_holes_present": "UNKNOWN",
                        "label_regions": "", "reviewer": "", "reviewed_at": "", "notes": ""})
labels = {}
for s in csv.DictReader(open(SHEET)):
    if s["reviewer"].strip():
        labels[s["id"]] = s


def iou(a, b):
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw, ih = max(0, min(ax2, bx2) - max(a[0], b[0])), max(0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    return inter / (a[2] * a[3] + b[2] * b[3] - inter) if inter else 0.0


def metrics(pv, split, supp):
    ids = [r["id"] for r in runnable if r["split"] == split and r["supplementary"] == supp]
    out = {"images": len(ids), "unreviewed_excluded": sum(1 for i in ids if i not in labels)}
    for key, cat in CATS.items():
        m = Counter()
        for i in ids:
            d = res[pv].get(i)
            if not d or i not in labels:
                continue
            lab = labels[i][key].strip().lower()
            if lab not in ("present", "absent", "cannot_assess"):
                m["label_unknown"] += 1; continue
            if d["status"] != "Done":
                m["run_failed"] += 1; continue
            abst = d.get("image_assessability") == "cannot_assess"
            cands = [c for c in d.get("candidates") or [] if c["category"] == cat]
            if abst:
                m["abstentions"] += 1
                if lab == "cannot_assess":
                    m["correct_abstentions_on_obscured"] += 1
            if lab == "absent" and cands:
                m["false_alerts"] += 1
            if lab == "present" and not cands and not abst:
                m["misses"] += 1
            if lab == "present" and cands:
                m["detections"] += 1
                regs = json.loads(labels[i]["label_regions"] or "[]")
                if not regs:
                    m["highlight_no_region_labeled"] += 1
                elif any(c["region"] != "unlocalized" and any(iou(c["region"], g) >= 0.3 for g in regs) for c in cands):
                    m["highlight_iou>=0.3"] += 1
                else:
                    m["highlight_miss"] += 1
        out[key] = dict(m)
    return out


def raw_counts(pv, split, supp):
    ids = [r["id"] for r in runnable if r["split"] == split and r["supplementary"] == supp]
    ds = [res[pv][i] for i in ids if i in res[pv]]
    dur = sorted(d["duration_s"] for d in ds)
    c = Counter()
    for d in ds:
        c["status_" + d["status"]] += 1
        if d.get("image_assessability") == "cannot_assess":
            c["image_cannot_assess"] += 1
        for cat in {x["category"] for x in d.get("candidates") or []}:
            c["images_with_" + cat] += 1
        c["unlocalized_candidates"] += sum(1 for x in d.get("candidates") or [] if x["region"] == "unlocalized")
        c["attempts"] += d["attempts"]
    p = lambda q: dur[min(len(dur) - 1, int(q * len(dur)))] if dur else None
    return {"runs": len(ds), **dict(c), "latency_p50_s": p(0.5), "latency_p95_s": p(0.95), "cost": "UNKNOWN"}


# ---- contact sheet ----
def boxes(d):
    out = ""
    for c in d.get("candidates") or []:
        if c["region"] != "unlocalized":
            x, y, w, h = c["region"]
            col = "#e11" if "fastener" in c["category"] else "#fa0"
            out += f'<div style="position:absolute;left:{x*100}%;top:{y*100}%;width:{w*100}%;height:{h*100}%;border:2px solid {col}"></div>'
    return out


def summ(d):
    if not d:
        return "not run"
    if d["status"] != "Done":
        return f"FAILED ({html.escape(d.get('error_stage') or '')})"
    if d.get("image_assessability") == "cannot_assess":
        return "cannot assess: " + html.escape(d.get("cannot_assess_reason") or "")
    cs = d.get("candidates") or []
    return "no candidate" if not cs else "<br>".join(f"<b>{html.escape(c['category'])}</b>: {html.escape(c['visible_reason'][:160])}" for c in cs)


cells = []
for r in runnable:
    src = r["file"] if not r["file"].startswith("/app/eval/tie_fastener/") else r["file"][len(ROOT) + 1:]
    src = os.path.relpath(r["file"], ROOT) if r["file"].startswith("/") else r["file"]
    cols = "".join(f'<td><div style="position:relative;display:inline-block"><img src="{src}" width="300">{boxes(res[pv].get(r["id"], {}))}</div>'
                   f'<div class="o">{summ(res[pv].get(r["id"]))}</div></td>' for pv in PVS)
    cells.append(f'<tr><td><b>{r["id"]}</b><br>{r["split"]}{" · supplementary" if r["supplementary"] else ""}<br>{html.escape(r["license"])}<br>'
                 f'{html.escape(r["author"][:60])}<br><a href="{html.escape(r["source_url"])}">source</a><br><i>{html.escape(r["transformations"][:120])}</i>'
                 f'<br><span class="p">{html.escape(r["proposed_label_NOT_GROUND_TRUTH"])}</span></td>{cols}</tr>')
open(f"{ROOT}/contact_sheet.html", "w").write(
    "<html><head><meta charset='utf-8'><style>body{font:13px sans-serif}td{vertical-align:top;border-bottom:1px solid #ccc;padding:6px;max-width:320px}"
    ".o{font-size:12px;color:#333}.p{color:#06c}</style></head><body><h2>Tie/fastener eval — contact sheet</h2>"
    "<p><b>Model output shown here is NOT a label.</b> Boxes: orange = deterioration candidate, red = fastener candidate. Blue text = builder proposal, not ground truth. "
    "Label in review_sheet.csv (set reviewer + reviewed_at), then rerun tools/report.py.</p>"
    f"<table><tr><th>image</th>{''.join(f'<th>{pv}</th>' for pv in PVS)}</tr>{''.join(cells)}</table></body></html>")

# ---- report ----
L = ["# Tie/fastener image evaluation — REPORT", "",
     f"Lock: {len(lock['items'])} locked_test items, locked_at {lock['locked_at']} (before any revised-prompt run on them). Prompts: {', '.join(PVS)}. Model: "
     + ", ".join(sorted({d['model_id'] for pv in res for d in res[pv].values()})) + ".",
     f"Human-reviewed rows: {len(labels)} of {len(runnable)}. Unreviewed rows are UNKNOWN and excluded from metrics.", ""]
for split in ("dev", "locked_test"):
    for supp in (False, True):
        L.append(f"## {split} · {'supplementary (non-US / overhead)' if supp else 'primary (U.S. in-place)'}")
        for pv in PVS:
            L.append(f"- **{pv}** labelled metrics: `{json.dumps(metrics(pv, split, supp))}`")
            L.append(f"  - raw model-output counts (not accuracy): `{json.dumps(raw_counts(pv, split, supp))}`")
        if len(PVS) == 2 and labels:
            a, b = (metrics(pv, split, supp) for pv in PVS)
            for key in CATS:
                fa = (a[key].get("false_alerts", 0), b[key].get("false_alerts", 0)); de = (a[key].get("detections", 0), b[key].get("detections", 0))
                if fa[1] < fa[0] and de[1] < de[0]:
                    L.append(f"  - **REGRESSION ({key})**: false alerts {fa[0]}→{fa[1]} but genuine detections {de[0]}→{de[1]}")
        L.append("")
open(f"{ROOT}/REPORT_metrics.md", "w").write("\n".join(L))
print("\n".join(L))
