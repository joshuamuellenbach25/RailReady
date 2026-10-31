# Phase 4: Inspection workspace, photo-derived scenes, landing refresh, business-rule corrections
Version: phase-4. Context: docs/spec/overview.md. Source: research handoff of 2026-10-24. Builds on Phases 1–3 as delivered: shared FastAPI backend (backend), Expo app (mobile), React web (frontend), JWT, MongoDB, Emergent object storage, Claude Sonnet 5.5 image adapter img-v1.3.1, demo sessions.

## Goal
Every ordinary foreman photo gets its own private interactive photo-derived 3D view (server Depth Anything V2 Small ONNX relative depth -> coloured Gaussian samples -> SuperSplat viewer) inside an authenticated web inspection workspace at /office/visits/:id/scene, with inventory <-> marker <-> evidence selection tied to the same finding IDs. The marketing entry page is refreshed. Business-rule corrections and test-found polish land. No deployment, no external sharing.

## Constraints (from user)
- Keep everything private: do not use Emergent Publish/Re-publish, change sharing, or contact anyone. In-app proposal publish is fine.
- No new third-party service receives user photos. Depth model runs on our server via normal dependency install.
- Depth model: onnx-community/depth-anything-v2-small @ 4472b7362082ad9968fee890ca0f1e5aca36b93d, Apache-2.0; onnx/model.onnx sha256 afb6a5c28f3b6bf1618c6e43f02073ef9dfdc70e937502d51603e57b0a1df10c; preprocessor_config.json sha256 03576db3c13dd0471fdf5f5e1428befcb95de063fe699879150b293dc9e0a2c6. Verify hashes; if unobtainable report exact blocker, never fake output.
- Viewer: @playcanvas/supersplat-viewer (+ compatible playcanvas peer; reference 1.41.0 / 2.23.3), createViewer from its /viewer entry; only supported APIs.
- Image analysis budget unchanged; reopen/orbit/replay = zero provider calls.
- Do not restore deferred modules (invoices, payments, recurrence, advanced scheduling/signatures/POs, video inference, measurements, grading, certification, operating release).

## Functional requirements
Scene pipeline (backend)
- REQ-120 [event] When a photo evidence item becomes Verified, the system shall enqueue one persisted depth-scene job keyed by source hash + model revision + projection settings.
- REQ-121 [unwanted] If a depth job for the same key already exists, then the system shall reuse its scene without a new inference.
- REQ-122 [always] The system shall apply EXIF orientation before depth and image analysis and record the transform and oriented dimensions.
- REQ-123 [always] The system shall keep the original bytes, hash and full-resolution evidence unchanged.
- REQ-124 [always] The system shall sample display geometry at a bounded max side (default 384 px) and record that setting with each scene.
- REQ-125 [always] The system shall load verified model weights once per process and reuse the inference session.
- REQ-126 [unwanted] If the model artifact hash does not match the recorded hash, then the system shall mark scenes "Model unavailable" with the mismatch reason.
- REQ-127 [always] The system shall persist scene states Queued, Processing, Ready, Failed, Unsupported with bounded recoverable retries.
- REQ-128 [unwanted] If depth processing fails, then the system shall keep upload, receipt, image analysis and original-photo review unaffected.
- REQ-129 [unwanted] If a photo format is unsupported (e.g. HEIC without converter), then the system shall show "Unsupported photo format – view original or upload JPEG/PNG" keeping the original.
- REQ-130 [always] The system shall give each photo its own scene id, revision, source hash and anchors.
- REQ-131 [event] When a candidate or observation has a validated normalized region on a photo with a Ready scene, the system shall create an anchor at the region centre projected through that photo's estimated depth with location_basis "single_photo_estimated_depth".
- REQ-132 [unwanted] If an anchor cannot be placed, then the system shall keep the finding listed as "Unplaced" with a reason.
- REQ-133 [always] The system shall store with each anchor evidence id, scene id + revision, finding/candidate id, coordinates, image point, placement basis (auto/manual), uncertainty, actor/time and version.
- REQ-134 [event] When a reviewer moves an anchor, the system shall save a new anchor version with expected-revision check, without changing condition, quantities or issued documents.
- REQ-135 [always] The system shall never transfer anchor coordinates between photos.
- REQ-136 [event] When a scene is regenerated, the system shall create a new scene revision leaving old anchors bound to the old revision.
- REQ-137 [always] The system shall serve scene assets, crops and originals only to authorized actors of the parent workspace via short-lived scoped access.
Inspection workspace (web)
- REQ-138 [always] The system shall show /office/visits/:id/scene with top bar (product, breadcrumb, Original photo, Markers, Reset view), provenance strip, left inventory (~190px), centre scene (510–640px tall), right evidence drawer (230–300px) and footer (source filename, scene revision/mode).
- REQ-139 [always] The system shall display "AI-estimated depth. Geometry and scale unverified." whenever a photo-derived scene is shown.
- REQ-140 [event] When the user clicks a scene marker, the system shall select the same finding row and its evidence.
- REQ-141 [event] When the user clicks an inventory row, the system shall highlight its marker and restore its authored view.
- REQ-142 [event] When the user toggles Original photo, the system shall show the real image with normalized region boxes.
- REQ-143 [event] When the user toggles Markers, the system shall hide or show overlays without deleting data.
- REQ-144 [event] When the user taps Reset view, the system shall restore the capture camera.
- REQ-145 [always] The system shall reproject markers on camera, canvas, layout and orientation change, hiding behind-camera or off-viewport markers.
- REQ-146 [always] The system shall limit orbit excursion around the capture viewpoint.
- REQ-147 [event] When the user switches photos, the system shall destroy the previous viewer and show only the new photo's geometry and markers.
- REQ-148 [always] The system shall show distinct text+icon states Pending, Confirmed, Dismissed, Needs evidence, Unplaced.
- REQ-149 [always] The system shall show in the evidence drawer the finding name/id, crop, original link, visible-evidence text, source time/provenance, identity source, visible condition, human review and location basis as separate fields.
- REQ-150 [always] The system shall link from the drawer to the existing finding and estimate records, preserving selection on return.
- REQ-151 [always] The system shall show real states: Loading (progress), Ready (after first rendered frame), No photo, Unsupported, Access denied, Expired media, Model unavailable, Failed (Retry), Graphics unavailable (evidence-only), Unplaced.
- REQ-152 [always] The system shall disable camera keyboard controls while a text input has focus.
- REQ-153 [always] The system shall lay out at ~390px as scene above compact list with evidence bottom sheet, 44px touch targets, no horizontal overflow.
- REQ-154 [unwanted] If a legacy planar Hudson preview fixture is shown, then the system shall label it "Planar photo preview / depth not reconstructed", "Manual annotation", "Not assessed".
Landing page
- REQ-155 [always] The system shall render the public entry with nav How it works / What it handles / Example job / Contact, hero "Run the track work. Keep the business moving.", primary "View example job", secondary "Discuss your workflow", and a prototype-stage label.
- REQ-156 [always] The system shall label any illustrative job "Illustrative example, fictional data. No live transaction." and unbuilt capabilities "Planned workflow".
- REQ-157 [always] The system shall keep "Open demo workspace" and "Staff sign in" reachable from the entry page.
Business corrections / polish
- REQ-158 [unwanted] If an each-priced tie line quantity is not a whole positive number, then the system shall reject it with a field error.
- REQ-159 [event] When a customer media request arrives, the system shall revalidate token validity and revocation for that request.
- REQ-160 [event] When area-photo analysis runs on a visit photo without a finding, the system shall create candidates that a human review creates or links to a finding.
- REQ-161 [unwanted] If object storage returns a transient error during demo session creation, then the system shall retry up to 2 times and otherwise return 503 "Demo setup temporarily unavailable – try again".
- REQ-162 [state] While a work-order save is in flight, the system shall disable its planning controls.

## Quality requirements
Q-22 Tag: Scene.Latency | Scale: seconds from Verified photo to scene Ready on server CPU | Meter: timed x3 | Must: 60 | Plan: 15 (estimate)
Q-23 Tag: Scene.FirstFrame | Scale: seconds from opening scene route to first rendered frame on desktop Chrome | Meter: browser x3 | Must: 8 | Plan: 3
Q-24 Tag: Anchor.Correspondence | Scale: px error between box centre in Original photo and marker at capture view, portrait/landscape/EXIF-rotated | Meter: screenshot measure x3 | Must: 20 | Plan: 6
Q-25 Tag: Viewer.Leak | Scale: live WebGL contexts after switching photos 10 times | Meter: browser check | Must: 1 | Plan: 1
Q-26 Tag: Scene.Exposure | Scale: scene/crop/original bytes returned to another workspace or without auth | Meter: API probes x10 | Must: 0 | Plan: 0
Q-27 Tag: Scene.Honesty | Scale: scenes shown Ready without real depth inference (flat fallback presented as depth) | Meter: DB + UI check | Must: 0 | Plan: 0
Q-28 Tag: Workspace.Layout | Scale: clipped/overlapping panels at 1440, 1024, 390, 360 px | Meter: screenshots | Must: 0 | Plan: 0
