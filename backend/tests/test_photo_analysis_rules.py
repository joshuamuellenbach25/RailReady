"""Phase 7 offline rule tests (V17–V20 exact numbers + validation). Zero provider calls.
Run: cd /app/backend && /root/.venv/bin/python -m pytest -q tests/test_photo_analysis_rules.py
"""
import math
import sys

import pytest
from PIL import Image

sys.path.insert(0, "/app/backend")
import photo_analysis_rules as R  # noqa: E402


def dist(**over):
    p = {c: 0.0 for c in R.IDENTITY_CHOICES}
    p.update(over)
    return p


def ans(choice, probs, src="model_estimated_distribution", conf=None):
    return {"name": "identity", "choice": choice, "probability_source": src, "probabilities": probs, "confidence": conf}


@pytest.mark.parametrize("p,want", [(0.70, "suggested"), (0.69996, "needs_review"), (0.50, "needs_review"), (0.4999, "unclassified")])
def test_v17_status_thresholds_raw(p, want):
    assert R.status_for(p) == want
    a = ans("F.01.01", dist(**{"F.01.01": p, "not_assessable": 1 - p}))
    R.validate_distribution(a, R.IDENTITY_CHOICES)
    s = R.summarize_identity(a)
    assert s["status"] == want and s["raw_probability"] == p


def test_v17_display_rounding_does_not_change_status():
    s = R.summarize_identity(ans("F.01.01", dist(**{"F.01.01": 0.69996, "other_rail_component": 0.30004})))
    assert s["probability"] == 0.7 and s["status"] == "needs_review"


@pytest.mark.parametrize("bad,msg", [
    ({"probability_source": "calibrated"}, "probability_source"),
    ({"probabilities": {"F.01.01": 1.0}}, "keys"),
    ({"probabilities": dist(**{"F.01.01": 0.9})}, "sum"),
    ({"probabilities": dist(**{"F.01.01": 1.2, "R.01.01": -0.2})}, "invalid probability"),
    ({"probabilities": dist(**{"F.01.01": True})}, "invalid probability"),
    ({"choice": "X.99"}, "choice"),
    ({"confidence": 1.5}, "confidence"),
])
def test_v18_distribution_validation(bad, msg):
    a = {**ans("F.01.01", dist(**{"F.01.01": 1.0})), **bad}
    with pytest.raises(R.RuleError, match=msg):
        R.validate_distribution(a, R.IDENTITY_CHOICES)


def test_v18_sum_tolerance_edges():
    ok = ans("R.02.01", dist(**{"R.02.01": 0.95, "R.01.01": 0.003, "S.01.01": 0.004, "other_rail_component": 0.01,
                                "not_a_rail_component": 0.01, "not_assessable": 0.005, "F.01.01": 0.017}))
    assert math.isclose(math.fsum(ok["probabilities"].values()), 0.999)
    R.validate_distribution(ok, R.IDENTITY_CHOICES)
    bad = ans("R.02.01", dist(**{"R.02.01": 0.95, "F.01.01": 0.048}))
    with pytest.raises(R.RuleError, match="sum"):
        R.validate_distribution(bad, R.IDENTITY_CHOICES)


def test_v18_json_parsing_rejects_duplicates_and_nan():
    with pytest.raises(R.RuleError):
        R.parse_json_response('{"a": 1, "a": 2}')
    with pytest.raises(R.RuleError):
        R.parse_json_response('{"a": NaN}')
    with pytest.raises(R.RuleError):
        R.parse_json_response('{"a": Infinity}')
    assert R.parse_json_response('{"a": 0.5}') == {"a": 0.5}


def test_v19_fallback_unclassified_even_with_leaf_over_070():
    a = ans("not_assessable", dist(**{"F.01.01": 0.72, "F.01.02": 0.1, "R.02.01": 0.05, "T.01.01": 0.03, "not_assessable": 0.10}))
    s = R.summarize_identity(a)
    assert s["status"] == "unclassified" and s["fallback_choice"] == "not_assessable"
    assert s["component_code"] is s["subsystem_code"] is s["system_code"] is None
    assert s["subsystem_probability"] == 0 and s["system_probability"] == 0
    assert s["raw_probability"] == 0.10
    assert [x["code"] for x in s["alternatives"]] == ["F.01.01", "F.01.02", "R.02.01"]


def test_v20_rollups_and_separate_confidence():
    a = ans("F.01.01", dist(**{"F.01.01": 0.72, "F.01.03": 0.12, "F.02.01": 0.11, "R.02.01": 0.02, "other_rail_component": 0.03}), conf=0.51)
    R.validate_distribution(a, R.IDENTITY_CHOICES)
    s = R.summarize_identity(a)
    assert s["probability"] == 0.72 and s["subsystem_probability"] == 0.84 and s["system_probability"] == 0.95
    assert s["provider_confidence"] == 0.51 and s["status"] == "suggested"
    assert s["component_name"] == "Tie plate" and s["subsystem_name"] == "Rail-to-tie hardware" and s["system_name"] == "Fastening"
    assert "F.01.01" not in [x["code"] for x in s["alternatives"]]
    assert math.isclose(s["system_probability_raw"], 0.95)


def test_v21_concern_not_assessable_is_unclassified():
    c = R.summarize_concern({"choice": "not_assessable", "probability_source": "model_estimated_distribution",
                             "probabilities": {"present": 0.05, "absent": 0.05, "not_assessable": 0.9}})
    assert c["status"] == "unclassified"
    c = R.summarize_concern({"choice": "present", "probability_source": "model_estimated_distribution",
                             "probabilities": {"present": 0.7, "absent": 0.2, "not_assessable": 0.1}})
    assert c["status"] == "suggested"


@pytest.mark.parametrize("box,ok", [([0.1, 0.1, 0.2, 0.2], True), ([0, 0, 1, 1], True), ([0.9, 0.1, 0.2, 0.2], False),
                                    ([0.1, 0.1, 0, 0.2], False), ([-0.1, 0.1, 0.2, 0.2], False), ([0.1, 0.1, True, 0.2], False),
                                    ([0.1, 0.1, float("nan"), 0.2], False), ([0.1, 0.2, 0.3], False), ("0,0,1,1", False)])
def test_validate_box(box, ok):
    assert R.validate_box(box) is ok


def test_crop_padding_and_metadata():
    img = Image.new("RGB", (1000, 500), "gray")
    data, meta = R.crop_for_classification(img, [0.5, 0.5, 0.2, 0.2])
    assert meta["source_pixel_rect"] == [484, 242, 716, 358]
    assert meta["padding_fraction"] == 0.08 and meta["jpeg_quality"] == 88 and not meta["upsampled_for_inference"]
    _, small = R.crop_for_classification(img, [0.0, 0.0, 0.02, 0.04])
    assert small["upsampled_for_inference"] and max(small["inference_crop_size"]) == 64
    _, big = R.crop_for_classification(Image.new("RGB", (4000, 3000)), [0, 0, 1, 1])
    assert max(big["inference_crop_size"]) == 768
