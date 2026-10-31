# Image evaluation set: visible tie deterioration + missing/displaced fasteners
Location: eval/tie_fastener/ (data + manifest), results in eval/tie_fastener/REPORT.md.

## Scope and sourcing
- Small (target 30–60 originals), rights-cleared only: public domain, CC0, CC BY, CC BY-SA (record exact license + URL + author + retrieval date). No unlicensed/unclear images, no AI-generated images.
- Priority: actual in-place U.S. wooden ties. Cover: clearly damaged ties (splits through, crushed/plate-cut, rot cavities, broken ends); normal weathering, grey colour and surface checks (negatives); intentionally unused/abandoned spike holes; different fastening arrangements (cut spikes + tie plates, screw spikes, elastic clips, Pandrol/e-clip on wood, anchors); clearly missing or displaced spikes/clips with a clear view; shadows; obscured views (ballast-covered, vegetation, debris, motion blur, low light).
- Non-U.S. or concrete-tie images allowed only as labeled supplementary rows.
- Repo overhead collection: added 2026-10-24 at eval/supplementary_overhead/RAIL_TOP_DOWN_REFERENCE_MATCH/, hash-verified: 315/315 UAV-RSOD photos match PHOTO_MANIFEST.json (concrete ties, India, physically staged obstacles, CC BY 4.0), 3/3 Hudson NY wooden-tie stills (CC0, derived frames of ONE video, one capture group) and 2/2 video variants (same source) match their manifests; plus 1 preview contact sheet. README mentions import_dataset.py but it is not included (data only). Rules: supplementary context only; all human condition labels UNKNOWN; do NOT analyze the full collection automatically; staged obstacles are not extra defect classes; stills + both videos are one capture group in one split; videos are not foreman captures; keep source attribution/transformations verbatim. Any image calls on these count against the same 150-call budget (suggest <=10: a few UAV frames as concrete/staged-context negatives-for-scope + the 3 Hudson stills as one group).
- 3D reconstructions/renders: separate folder and manifest flag `kind=reconstruction`; never mixed with original photo evidence or counted in test metrics.

## Manifest (one row per image, CSV + JSON)
id, file, sha256, source_url, license, author, retrieved_at, capture_group (same photographer/location/sequence), location (as stated by source, else UNKNOWN), country, tie_material (wood/concrete/UNKNOWN), fastening_type, viewpoint (overhead/oblique/close-up/track-level/distance), lighting (shadow/low-light/normal), transformations (none / crop / resize / blur / rotate, with params; derivative_of id), split (dev | locked_test), human_label fields: tie_deterioration (present/absent/cannot_assess/UNKNOWN), missing_or_displaced_fastener (present/absent/cannot_assess/UNKNOWN), unused_holes_present, label_regions (normalized boxes, optional), reviewer, reviewed_at, notes.
- Model output is never a label. Any row without a human reviewer is UNKNOWN for every label field and excluded from metrics (reported as count).
- The evaluation tools may write a "proposed label" column for reviewer convenience, clearly marked proposed, not ground truth.

## Splits
- Split by capture_group: neighbouring frames, same-sequence shots and all derivatives of an original stay in the same split.
- dev set: used for prompt iteration. Already-used Phase 1 photos (tie_disintegrated, tie_old_rotten, negative_coledale, obscured_coledale_blurred) are dev, permanently.
- locked_test: chosen before any revised-prompt run on it; record a lock file (list of ids + sha256 + timestamp). No prompt changes after viewing locked_test results without bumping prompt version and reporting that the test set was then contaminated.

## Comparison (old prompt img-v1.2 vs current revised prompt)
Per prompt × split: false alerts (candidate where reviewer says absent), misses (reviewer present, no candidate), abstentions (cannot assess), correct abstentions on obscured, highlight accuracy (candidate region overlaps reviewer region IoU>=0.3, or "no region labeled"), latency p50/p95, attempts, cost/credits where reported (else UNKNOWN). Report per category separately. Counts, not accuracy percentages, while n is small. Rule: a revision that reduces false alerts by also dropping genuine damage detections is reported as a regression, not an improvement.

## Reviewer step
Human review is required for labels. Provide a simple staff-only review page or a sheet (eval/tie_fastener/review_sheet.csv + thumbnails contact sheet HTML) a reviewer can fill; until then labels are UNKNOWN.

## Data gaps to report
Missing categories, low counts per cell, non-U.S. share, absence of overhead collection, unknown locations, lack of real foreman phone photos.
