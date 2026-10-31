"""Phase 7 rules (requirement §H). Pure functions, no I/O, no provider calls. Behaviour must match the reference exactly."""
import io
import json
import math

from PIL import Image

SUGGESTED, NEEDS_REVIEW = 0.70, 0.50
FALLBACK_CODES = ("other_rail_component", "not_a_rail_component", "not_assessable")
PROBABILITY_SOURCES = ("provider_distribution", "model_estimated_distribution")
CONCERN_CHOICES = ("present", "absent", "not_assessable")
PAD, JPEG_Q, MAX_SIDE, MIN_SIDE = 0.08, 88, 768, 64

TAXONOMY_ID, TAXONOMY_VERSION = "rail-components-v1", 1
TAXONOMY_LABEL = "product categories, not an engineering standard"
_SYS = {"R": "Running track", "F": "Fastening", "T": "Turnout", "S": "Track support"}
_SUB = {"R.01": "Rails and joints", "R.02": "Ties", "F.01": "Rail-to-tie hardware", "F.02": "Joint hardware",
        "T.01": "Turnout hardware", "S.01": "Ballast"}
_LEAVES = [("R.01.01", "Running rail segment"), ("R.01.02", "Joint bar"), ("R.01.03", "Rail joint assembly"),
           ("R.02.01", "Timber tie"), ("R.02.02", "Concrete tie"),
           ("F.01.01", "Tie plate"), ("F.01.02", "Rail spike"), ("F.01.03", "Elastic rail clip"), ("F.01.04", "Rail anchor hardware"),
           ("F.01.05", "Rail fastening assembly"), ("F.02.01", "Joint bolt or nut"),
           ("T.01.01", "Switch point"), ("T.01.02", "Frog"), ("T.01.03", "Guard or check rail"), ("S.01.01", "Ballast region")]
LEAVES = [{"code": c, "name": n, "subsystem_code": c[:4], "subsystem_name": _SUB[c[:4]], "system_code": c[0], "system_name": _SYS[c[0]],
           "countable": not c.startswith("S.")} for c, n in _LEAVES]
LEAF_BY_CODE = {leaf["code"]: leaf for leaf in LEAVES}
IDENTITY_CHOICES = [leaf["code"] for leaf in LEAVES] + list(FALLBACK_CODES)


class RuleError(ValueError):
    pass


def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise RuleError(f"duplicate key: {k}")
        out[k] = v
    return out


def _no_const(c):
    raise RuleError(f"non-finite constant: {c}")


def parse_json_response(text: str):
    return json.loads(text, object_pairs_hook=_no_dupes, parse_constant=_no_const)


def probability(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1


def validate_distribution(answer: dict, expected) -> dict:
    if not isinstance(answer, dict):
        raise RuleError("answer is not an object")
    if answer.get("probability_source") not in PROBABILITY_SOURCES:
        raise RuleError(f"probability_source not allowed: {answer.get('probability_source')!r}")
    probs = answer.get("probabilities")
    if not isinstance(probs, dict) or set(probs) != set(expected):
        raise RuleError("probabilities keys must equal the allowed choices exactly")
    for k, v in probs.items():
        if not probability(v):
            raise RuleError(f"invalid probability for {k}: {v!r}")
    if abs(math.fsum(probs.values()) - 1) > 0.001 + 1e-9:  # 1e-9: binary floating-point slack only (0.999 passes, 0.998 fails)
        raise RuleError(f"probabilities sum to {math.fsum(probs.values())}, not 1")
    if answer.get("choice") not in expected:
        raise RuleError(f"choice not allowed: {answer.get('choice')!r}")
    if answer.get("confidence") is not None and not probability(answer["confidence"]):
        raise RuleError(f"invalid confidence: {answer['confidence']!r}")
    return answer


def status_for(p: float) -> str:
    if p >= SUGGESTED:
        return "suggested"
    if p >= NEEDS_REVIEW:
        return "needs_review"
    return "unclassified"


def summarize_identity(answer: dict, leaves=LEAVES) -> dict:
    values = answer["probabilities"]
    ranked = sorted(leaves, key=lambda leaf: (-values[leaf["code"]], leaf["code"]))
    fallback = answer["choice"] in FALLBACK_CODES
    top = ranked[0]
    top_raw = values[top["code"]]
    runners = [leaf for leaf in (ranked[:3] if fallback else ranked[1:4]) if values[leaf["code"]] > 0]
    sub_raw = 0.0 if fallback else math.fsum(values[leaf["code"]] for leaf in leaves if leaf["subsystem_code"] == top["subsystem_code"])
    sys_raw = 0.0 if fallback else math.fsum(values[leaf["code"]] for leaf in leaves if leaf["system_code"] == top["system_code"])
    selected_raw = values[answer["choice"]] if fallback else top_raw
    pick = None if fallback else top
    return {
        "component_code": pick and pick["code"], "component_name": pick and pick["name"],
        "subsystem_code": pick and pick["subsystem_code"], "subsystem_name": pick and pick["subsystem_name"],
        "system_code": pick and pick["system_code"], "system_name": pick and pick["system_name"],
        "raw_probability": selected_raw, "probability": round(selected_raw, 4),
        "provider_confidence": answer.get("confidence"), "probability_source": answer["probability_source"],
        "subsystem_probability_raw": sub_raw, "subsystem_probability": round(min(sub_raw, 1), 4),
        "system_probability_raw": sys_raw, "system_probability": round(min(sys_raw, 1), 4),
        "status": "unclassified" if fallback else status_for(top_raw),
        "fallback_choice": answer["choice"] if fallback else None,
        "alternatives": [{"code": leaf["code"], "name": leaf["name"], "raw_probability": values[leaf["code"]],
                          "probability": round(values[leaf["code"]], 4)} for leaf in runners],
        "raw_probabilities": dict(values),
    }


def summarize_concern(answer: dict) -> dict:
    values = answer["probabilities"]
    choice = answer["choice"]
    return {"choice": choice, "raw_probability": values[choice], "probability": round(values[choice], 4),
            "status": "unclassified" if choice == "not_assessable" else status_for(values[choice]),
            "probability_source": answer["probability_source"], "provider_confidence": answer.get("confidence"),
            "raw_probabilities": dict(values), "evidence": answer.get("evidence"), "limitations": answer.get("limitations")}


def validate_box(box) -> bool:
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return False
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box):
        return False
    x, y, w, h = box
    return x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= 1 and y + h <= 1


def crop_for_classification(img: Image.Image, box) -> tuple[bytes, dict]:
    if not validate_box(box):
        raise RuleError(f"invalid box: {box!r}")
    W, H = img.size
    x, y, w, h = box
    left = int(max(0, x - PAD * w) * W)
    top = int(max(0, y - PAD * h) * H)
    right = max(left + 1, int(min(1, x + (1 + PAD) * w) * W))
    bottom = max(top + 1, int(min(1, y + (1 + PAD) * h) * H))
    crop = img.crop((left, top, right, bottom)).convert("RGB")
    native = crop.size
    upsampled = False
    if max(native) < MIN_SIDE:
        s = MIN_SIDE / max(native)
        crop = crop.resize((max(1, round(native[0] * s)), max(1, round(native[1] * s))), Image.LANCZOS)
        upsampled = True
    else:
        crop.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=JPEG_Q)
    return buf.getvalue(), {"source_box": list(box), "source_pixel_rect": [left, top, right, bottom], "source_image_size": [W, H],
                            "native_crop_size": list(native), "inference_crop_size": list(crop.size), "padding_fraction": PAD,
                            "jpeg_quality": JPEG_Q, "upsampled_for_inference": upsampled}
