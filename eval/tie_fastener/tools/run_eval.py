"""Run old (img-v1.2, reconstructed) and current prompt on manifest images. Resumable; hard cap on total model calls."""
import asyncio, json, os, sys, time
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
import ai_image

ROOT = "/app/eval/tie_fastener"
OUT = f"{ROOT}/results"
CAP = 150
CURRENT = ai_image.SYSTEM
# img-v1.2 text was not preserved in git (single squashed commit). Reconstructed = current prompt minus the v1.3 tightening
# clauses ("What is NOT a candidate…", "Only flag … deterioration …", "Only flag … fastener …"). Reported as a deviation.
OLD = "\n".join(l for l in CURRENT.split("\n") if not (
    l.startswith("- What is NOT a candidate") or l.startswith("  shadows. These are typical") or
    l.startswith("- Only flag") or l.startswith("  sections, plate cutting") or l.startswith("  view and visibly empty")))
PROMPTS = {"img-v1.2-reconstructed": OLD, ai_image.PROMPT_VERSION: CURRENT}


def calls_used():
    n = 0
    for f in os.listdir(OUT):
        n += json.load(open(f"{OUT}/{f}"))["attempts"]
    return n


async def main():
    os.makedirs(OUT, exist_ok=True)
    rows = [r for r in json.load(open(f"{ROOT}/manifest.json")) if r["kind"] != "excluded_out_of_scope"]
    for pv, text in PROMPTS.items():
        ai_image.SYSTEM = text  # provider reads the module-level SYSTEM per call; runs are sequential per prompt
        todo = [r for r in rows if not os.path.exists(f"{OUT}/{pv}__{r['id']}.json")]

        async def one(r):
            used = calls_used()
            if used + 2 > CAP:
                print("BUDGET STOP", used); return
            path = r["file"] if r["file"].startswith("/") else f"{ROOT}/{r['file']}"
            res = await ai_image.analyze(open(path, "rb").read(), f"eval-{pv}-{r['id']}")
            res.update({"id": r["id"], "prompt_version": pv, "model_id": ai_image.PROVIDER.model_id, "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "cost": "UNKNOWN (not reported by provider wrapper)"})
            json.dump(res, open(f"{OUT}/{pv}__{r['id']}.json", "w"), indent=1)
            print(pv, r["id"], res["status"], res.get("image_assessability"), len(res.get("candidates") or []), res["duration_s"], flush=True)

        for i in range(0, len(todo), 2):  # concurrency 2 (matches SEM)
            await asyncio.gather(*(one(r) for r in todo[i:i + 2]))
    print("calls used", calls_used())

asyncio.run(main())
