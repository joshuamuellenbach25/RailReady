# Tie/fastener image evaluation — REPORT

Lock: 37 locked_test items, locked_at 2026-10-24T22:43:45Z (before any revised-prompt run on them). Prompts: img-v1.2-reconstructed, img-v1.3.1. Model: claude-sonnet-5-5.
Human-reviewed rows: 0 of 42. Unreviewed rows are UNKNOWN and excluded from metrics.

## dev · primary (U.S. in-place)
- **img-v1.2-reconstructed** labelled metrics: `{"images": 0, "unreviewed_excluded": 0, "tie_deterioration": {}, "missing_or_displaced_fastener": {}}`
  - raw model-output counts (not accuracy): `{"runs": 0, "latency_p50_s": null, "latency_p95_s": null, "cost": "UNKNOWN"}`
- **img-v1.3.1** labelled metrics: `{"images": 0, "unreviewed_excluded": 0, "tie_deterioration": {}, "missing_or_displaced_fastener": {}}`
  - raw model-output counts (not accuracy): `{"runs": 0, "latency_p50_s": null, "latency_p95_s": null, "cost": "UNKNOWN"}`

## dev · supplementary (non-US / overhead)
- **img-v1.2-reconstructed** labelled metrics: `{"images": 5, "unreviewed_excluded": 5, "tie_deterioration": {}, "missing_or_displaced_fastener": {}}`
  - raw model-output counts (not accuracy): `{"runs": 5, "status_Done": 5, "images_with_possible missing/displaced fastener": 2, "images_with_visible tie-surface deterioration": 4, "unlocalized_candidates": 0, "attempts": 5, "image_cannot_assess": 1, "latency_p50_s": 8.89, "latency_p95_s": 14.41, "cost": "UNKNOWN"}`
- **img-v1.3.1** labelled metrics: `{"images": 5, "unreviewed_excluded": 5, "tie_deterioration": {}, "missing_or_displaced_fastener": {}}`
  - raw model-output counts (not accuracy): `{"runs": 5, "status_Done": 5, "images_with_visible tie-surface deterioration": 3, "unlocalized_candidates": 0, "attempts": 6, "image_cannot_assess": 1, "latency_p50_s": 5.74, "latency_p95_s": 11.43, "cost": "UNKNOWN"}`

## locked_test · primary (U.S. in-place)
- **img-v1.2-reconstructed** labelled metrics: `{"images": 20, "unreviewed_excluded": 20, "tie_deterioration": {}, "missing_or_displaced_fastener": {}}`
  - raw model-output counts (not accuracy): `{"runs": 20, "status_Done": 20, "images_with_possible missing/displaced fastener": 13, "images_with_visible tie-surface deterioration": 14, "unlocalized_candidates": 0, "attempts": 20, "image_cannot_assess": 4, "latency_p50_s": 9.43, "latency_p95_s": 22.24, "cost": "UNKNOWN"}`
- **img-v1.3.1** labelled metrics: `{"images": 20, "unreviewed_excluded": 20, "tie_deterioration": {}, "missing_or_displaced_fastener": {}}`
  - raw model-output counts (not accuracy): `{"runs": 20, "status_Done": 20, "images_with_possible missing/displaced fastener": 7, "unlocalized_candidates": 0, "attempts": 20, "images_with_visible tie-surface deterioration": 3, "image_cannot_assess": 7, "latency_p50_s": 8.16, "latency_p95_s": 15.94, "cost": "UNKNOWN"}`

## locked_test · supplementary (non-US / overhead)
- **img-v1.2-reconstructed** labelled metrics: `{"images": 17, "unreviewed_excluded": 17, "tie_deterioration": {}, "missing_or_displaced_fastener": {}}`
  - raw model-output counts (not accuracy): `{"runs": 17, "status_Done": 17, "images_with_possible missing/displaced fastener": 10, "images_with_visible tie-surface deterioration": 9, "unlocalized_candidates": 0, "attempts": 17, "image_cannot_assess": 5, "latency_p50_s": 8.78, "latency_p95_s": 14.1, "cost": "UNKNOWN"}`
- **img-v1.3.1** labelled metrics: `{"images": 17, "unreviewed_excluded": 17, "tie_deterioration": {}, "missing_or_displaced_fastener": {}}`
  - raw model-output counts (not accuracy): `{"runs": 17, "status_Done": 17, "images_with_possible missing/displaced fastener": 4, "images_with_visible tie-surface deterioration": 3, "unlocalized_candidates": 0, "attempts": 17, "image_cannot_assess": 7, "latency_p50_s": 6.85, "latency_p95_s": 15.41, "cost": "UNKNOWN"}`
