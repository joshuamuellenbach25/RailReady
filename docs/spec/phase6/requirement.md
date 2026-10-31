# Phase 6: Pueblo Rail Components dataset import, baseline, training, empirical calibration
Version: phase-6. Source: "complete Pueblo dataset, training support and empirical calibration" brief (2026-10-24). Builds on Phases 1–5. Staff-only; private research/calibration use (CC BY-NC-SA 4.0; commercial/public permission UNKNOWN).

## Source contract (must match exactly)
- Kaggle elvin1233/rail-components v1. ZIP https://www.kaggle.com/api/v1/datasets/download/elvin1233/rail-components, 500370877 bytes, sha256 af60904318e2a6e5f8f136fd2064ac7a00d04cb231a41c831e513c2cac209a83; 2102 members, 519538936 bytes uncompressed; prefix "Rail Components Dataset/" + annotations/train.json, annotations/val.json, train/*.jpg, val/*.jpg.
- train.json sha256 1e063d8d8dbafa2f64814bfdc254460a6571df2762f2c59923d554659ba29475 (1600 images / 33406 anns); val.json sha256 5bccc1ab170092b59481d11bc77e6decbb5ead6f55e6aa6ae4272459da5db53d (500 / 10139). Combined 43545 anns; category 11 "image" = 2100 whole-image anns; physical 41445. All JPEGs 512×512.
- Categories (Good/Bad): 1 clip 4306/204; 2 spike_and_bolt 10882/497; 3 tie 3709/409; 4 hole 5204/649; 5 rail 2168/0; 6 anchor 1711/14; 7 clip_base 3748/208; 8 joint_bar 169/5; 9 joint_gap 73/21; 10 baseplate 6820/648; 11 image 1662/438.
- Attribution: Youzhi Tang, Yu Qian; Automation in Construction 190 (2026) 107074, doi 10.1016/j.autcon.2026.107074; region Pueblo, Colorado (rip.trb.org/View/2572335); license CC BY-NC-SA 4.0.

## Functional requirements
- REQ-232 [event] When an admin/estimator starts import, the system shall stream-download the fixed ZIP in a durable resumable job with progress and bounded retries.
- REQ-233 [unwanted] If the ZIP hash, size or member list differs, then the system shall stop with the exact blocker and offer authenticated ZIP upload with the same verification.
- REQ-234 [unwanted] If a member has traversal, absolute path, duplicate name, unexpected path or excessive decompression ratio, then the system shall reject it.
- REQ-235 [always] The system shall store every original JPEG and both JSONs byte-identical in private object storage with per-file sha256, re-verified after storage.
- REQ-236 [always] The system shall mark the release complete only when all 2100 images decode at 512×512, both JSON hashes match, and 43545 annotations validate with parent links.
- REQ-237 [always] The system shall resume interrupted imports by release/hash/split/image key without duplicate records; partial stays partial.
- REQ-238 [always] The system shall persist DatasetRelease, DatasetImage, DatasetAnnotation, DataPartition, ModelRun and CalibrationProfile with immutable versions.
- REQ-239 [always] The system shall preserve source category IDs, Condition "Good"/"Bad", Type, occluded, bbox and polygons unmodified; transforms stored separately.
- REQ-240 [always] The system shall exclude category 11 "image" and virtual baseplates from physical-component detection, counts and metrics.
- REQ-241 [always] The system shall show on the Calibration page: import progress/counts, splits, category/condition stats, runs, profiles, attribution and license.
- REQ-242 [always] The system shall restrict all calibration APIs and dataset image fetches to staff of the owning workspace.
- REQ-243 [always] The system shall never create customer visits, findings, decisions or repair quantities from dataset images or labels.
- REQ-244 [event] When a baseline run starts, the system shall send up to 48 source-train images (mix of Good/Bad ties, spikes/bolts, clips) as real bytes to the existing vision adapter with labels, revealing filenames and overlays withheld, saving raw responses before parsing.
- REQ-245 [state] While the image-call budget is at its cap, the system shall block further provider runs with "Image-call budget reached – admin approval needed". (interpreted: existing 150-call budget)
- REQ-246 [always] The system shall lock source val (500) as the final test, unused for prompts, training, calibration fitting or threshold selection.
- REQ-247 [always] The system shall derive fit and calibration partitions only from source train with immutable membership, provisional near-duplicate/sequence grouping, and quarantine of groups overlapping test.
- REQ-248 [always] The system shall apply augmentation only to the fit partition with recorded seed and transforms.
- REQ-249 [event] When training is requested, the system shall run a real local CPU training job on the fit partition (if feasible) and record job id, checkpoint hash, config/data hashes, logs and status.
- REQ-250 [unwanted] If weight training of the hosted vision model is unsupported, then the system shall record that blocker and not label prompting/exemplars as training.
- REQ-251 [always] The system shall name score semantics explicitly: source_bad_condition_probability (supplied-crop classifier) and candidate_correctness_probability (localized candidates, IoU 0.50 one-to-one class-compatible matching).
- REQ-252 [event] When a profile is fitted, the system shall use only calibration-partition records with Platt scaling on logit scores and store a, b, bindings and memberships.
- REQ-253 [unwanted] If numeric scores, class support or reviewed independence are insufficient, then the system shall keep calibrated_probability null with the reason.
- REQ-254 [always] The system shall report precision, recall, false alerts, misses, confusion counts, abstentions, assessable coverage, Brier and reliability bins/ECE with denominators, and label supplied-box classification separately from end-to-end detection.
- REQ-255 [event] When a profile is activated, the system shall record the actor and apply it only to new runs within its declared task/class/domain, labelled "Pueblo source-domain calibration – not field-validated elsewhere".
- REQ-256 [always] The system shall mark SF validation UNKNOWN until separately sourced reviewed SF images are evaluated.
- REQ-257 [always] The system shall state "No Bad rail labels – broken-rail sensitivity unsupported" for category rail.

## Quality requirements
Q-37 Tag: Import.Completeness | Scale: images/JSON/annotations verified vs contract | Must: 2100/2/43545 | Plan: same
Q-38 Tag: Import.Idempotency | Scale: duplicate records after 3 interrupted resumes | Must: 0 | Plan: 0
Q-39 Tag: Test.Leakage | Scale: val images used in fit/calibration/prompt tuning | Must: 0 | Plan: 0
Q-40 Tag: Calibration.Honesty | Scale: probabilities shown without fitted profile or outside declared domain | Must: 0 | Plan: 0
Q-41 Tag: Budget | Scale: hosted image calls in this phase | Must: <= remaining of 150 cap | Plan: 48
