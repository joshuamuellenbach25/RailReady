# Tie / fastener image evaluation set — REPORT

Generated 2026-10-24.
Detailed per-split counts: `REPORT_metrics.md` (regenerate with `python tools/report.py` after labelling).

## What is here
| path | content |
|---|---|
| `originals/wc###.jpg` | 37 Wikimedia Commons images (1280px Commons thumbnails), all CC0 / PD / CC BY / CC BY-SA with author, license, URL and retrieval time in the manifest |
| `derivatives/` | 3 builder derivatives (blur r=12 of wc004, brightness 0.25 of wc023, left-half crop of wc001). Each is in its source's capture group and split |
| `manifest.json` / `manifest.csv` | one row per image: id, file, sha256, source_url, license(+url), author, retrieved_at, capture_group, country, transformations, derivative_of, split, supplementary flag, all label fields (= UNKNOWN), and `proposed_label_NOT_GROUND_TRUTH` |
| `locked_test.lock.json` | 37 locked_test ids + sha256, locked 2026-10-24T22:43:45Z, **before** any revised-prompt run on them. `build_manifest.py` refuses to proceed if the set changes |
| `review_sheet.csv` | reviewer sheet. Fill `tie_deterioration` / `missing_or_displaced_fastener` / `unused_holes_present` (present / absent / cannot_assess), optional `label_regions` (JSON list of [x,y,w,h] 0..1), `reviewer`, `reviewed_at` |
| `contact_sheet.html` | each image beside the output of both prompts, with candidate boxes drawn on it. Marked "model output is NOT a label" |
| `results/` | 84 raw run records (prompt × image), including raw responses, attempts and latency |
| `tools/` | search / download / build_manifest / run_eval / report scripts (resumable, hard cap of 150 calls) |

Supplementary overhead collection (`/app/eval/supplementary_overhead/RAIL_TOP_DOWN_REFERENCE_MATCH/`): referenced by path + sha256 only, never moved or re-encoded.
- The 3 Hudson stills are kind=`supplementary_overhead`, capture_group `g-hudson-video`, CC0. They are 3 frames from ONE real video. The 2 videos belong to the same group but were not analysed.
- 2 of 315 UAV-RSOD photos were analysed (ov-uav_rsod_v1_001 and _158; CC BY 4.0; Rampriya R S). These are concrete ties in India with physically staged obstacles. They are not U.S. wood-tie defect ground truth and not extra defect classes. Attribution and limitation text are kept verbatim in the manifest rows.
- 3D reconstructions: none were sourced. A `kind=reconstruction` flag is reserved; none are counted.

Excluded after the contact-sheet triage (kept in the manifest as `excluded_out_of_scope`, not run): wc008, wc009, wc010, wc015, wc016, wc019, wc024. These show loose spikes/bolts/rail, a museum object, a historic flood scene or a distant concrete yard.

## Splits
- **dev (5):** the 4 Phase-1 photos (permanently dev) and wc029. wc029 is the same photographer, same day and same sequence as Phase-1 `tie_old_rotten`, so it stays in that capture group.
- **locked_test (37):**
  - 20 primary U.S. in-place images (including 3 derivatives)
  - 12 supplementary non-U.S./unknown-country images
  - 5 supplementary overhead images
- Splitting is by capture group. Same-sequence frames and derivatives always share a split.

## Run
- Model `claude-sonnet-5-5` via the production `ai_image.analyze()` path: same validation, ≤1 repair, ≤2 retries, concurrency 2.
- Prompts compared:
  - `img-v1.2-reconstructed`: the exact v1.2 text was not preserved in git, so it was rebuilt as the current prompt minus the six v1.3 tightening lines.
  - `img-v1.3.1` (current).
- **Image calls used: 85 of the 150 budget.** 84 runs plus 1 repair turn. Of these, 10 calls were on the overhead collection (5 images × 2 prompts), within the suggested ≤10.
- No prompt was changed after the locked_test results were viewed.
- Latency (s, p50/p95):
  - locked primary: v1.2 9.4/22.2, v1.3.1 8.2/15.9
  - locked supplementary: v1.2 8.8/14.1, v1.3.1 6.9/15.4
- Cost: UNKNOWN (the provider wrapper reports none).

## Results — labelled metrics
**Human-reviewed rows: 0 of 42.** Every label is UNKNOWN, so false alerts, misses, abstention correctness and highlight IoU **cannot be computed yet**. All rows are excluded from metrics (reported counts: dev 5, locked_test 37). Nothing below is an accuracy claim.

## Model-output counts (not accuracy; images with ≥1 candidate)
| split · group | prompt | deterioration | fastener | cannot assess | runs |
|---|---|---|---|---|---|
| locked · primary US (20) | v1.2-recon | 14 | 13 | 4 | 20 |
| locked · primary US (20) | v1.3.1 | **3** | 7 | 7 | 20 |
| locked · supplementary (17) | v1.2-recon | 9 | 10 | 5 | 17 |
| locked · supplementary (17) | v1.3.1 | 3 | 4 | 7 | 17 |
| dev (5) | v1.2-recon | 4 | 2 | 1 | 5 |
| dev (5) | v1.3.1 | 3 | 0 | 1 | 5 |

Per-image changes from v1.2-recon to v1.3.1 (CA = cannot assess):
- **New abstentions:** wc011, wc014, wc017, wc034, wc037.
- **Deterioration dropped, fastener flag kept:** wc001, wc001-crop, wc002, wc005, wc006, wc026, wc030.
- **Everything dropped:** wc003, wc012, wc013, wc022, wc028, wc032, wc033, wc036, both UAV photos and p1-negative_coledale.
- **Unchanged positives:** p1-tie_disintegrated, wc027 (source caption: rotting sleeper), wc004, wc007, wc018, wc031.
- **Unchanged CA:** the blurred and darkened derivatives, wc020, wc021, wc023, wc025 and all 3 Hudson frames.

## Interpretation (honest)
- v1.3.1 flags far fewer images. This cuts likely false alerts on normal weathering, which was the goal; the Phase-1 clean negative is now clean.
- **Possible regressions — flagged, not claimed as improvements:**
  - **wc028:** the source caption describes a broken fastening ("afgebroken bevestiging"). v1.2 flagged a fastener; v1.3.1 returns no candidate. If a reviewer confirms damage there, this is a regression.
  - **wc037** (caption: sleepers rotting) moved from deterioration to cannot-assess.
  - **wc036** (Missoula) and **wc013** lost their deterioration flags.
- Per the plan's rule, the comparison cannot be declared an improvement until a human labels these rows. A drop in false alerts that comes with lost genuine detections will be reported as a regression.
- Synthetic obscured derivatives (blur, dark) were abstained on by both prompts. They are a necessary check, not a sufficient one.
- The Hudson overhead frames were abstained on by both prompts. From that distance and angle the model would not judge fastenings or tie surfaces. This is consistent with "no verified defect label" and gives no evidence either way about overhead capability.

## Data gaps
- **No human labels yet:** 0 of 42 reviewed. This blocks every metric.
- **Low counts per cell:**
  - 20 primary U.S. locked images, many of them close-ups of a single tie plate.
  - Very few clearly damaged in-place U.S. wood ties (most candidates are weathered).
  - Almost no clear missing or displaced spike/clip examples. wc028 (Sweden) is the only caption-supported one.
  - No intentional unused-spike-hole examples identified.
  - No screw-spike, elastic-clip or anchor arrangements on U.S. wood.
- **Supplementary share:** 17 of 37 locked images are non-U.S. or overhead, and the countries of wc018 and wc021 are unknown.
- **Locations:** usually the source's stated place only. No GPS was used.
- **No real foreman phone photos.** Everything is enthusiast or archival photography.
- **Overhead:** the uploaded collection has 0 verified defect labels. The UAV images are concrete/India with staged obstacles; the Hudson set is a single capture. Only 5 overhead images were analysed, by design.
- **Prompt:** img-v1.2 is a reconstruction, so the old-vs-new comparison is approximate.
- **Cost:** UNKNOWN.


## B7 archive note (Phase 10)
The supplementary overhead collection (315 UAV-RSOD India concrete-tie staged-obstacle photos, 3 Hudson stills + 2 videos from one capture) is ARCHIVED and is no longer an active eval input. Removed from manifest/review sheet/contact sheet: ov-hudson_track_t10_5, ov-hudson_track_t11_5, ov-hudson_track_t12_5, ov-uav_rsod_v1_001, ov-uav_rsod_v1_158. Historical numbers above that mention it are kept as history only. Archive: /tmp/archive/supplementary_overhead.tar, manifest /tmp/archive/supplementary_overhead.manifest.json (per-file sha256).
