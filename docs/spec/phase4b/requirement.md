# Phase 4b: Photo-derived 3D viewer: reference-processor adoption + viewer hardening (V01–V15)
Version: phase-4b. Source: "interactive photo-derived 3D inspection viewer" implementation prompt (2026-10-24), which includes a reference Python processor and frontend snippets. Builds on Phase 4 as delivered and tested CLEAN (iteration_3: 11/11): existing routes /api/visits/{id}/scenes, /api/evidence/{id}/scene, /api/scenes/{id}/asset, /api/visits/{id}/inventory, /api/inventory-items/{id}/crop, PUT /api/anchors/{id}; web /office/visits/:id/scene (SceneViewer.jsx, PhotoView.jsx, Inventory.jsx, EvidenceDrawer.jsx, MoveAnchor.jsx); supersplat-viewer 1.41.0 + playcanvas 2.23.3 already pinned; model verified at models/depth-anything-v2-small.

## Deltas to implement (adapt names to existing code; keep old routes as aliases; record a mapping)
Processor (backend)
- REQ-163 [always] The system shall generate scenes with this algorithm: model input max side 518 rounded to multiples of 14, ImageNet normalization, display max side 384, 2nd/98th percentile disparity, z = 3/(0.5+d), horizontal FOV 55°, focal = 0.5·W/tan(27.5°), 14-property PLY (x y z f_dc_0..2 opacity scale_0..2 rot_0..3), processor_revision "photo-scene-v1".
- REQ-164 [always] The system shall write manifest schema_version 1 (mode, source sha, raw/oriented/sampled dims, exif orientation applied, model id/revision/sha, processor revision, depth range, focal_pixels, coordinate convention, camera {position [0,0,0], target [0,0,-4], fov 55, horizontal_fov true}, projection, units "arbitrary_display_units", metric false, hidden_surfaces "not_reconstructed", artifact files + sha256, processing_seconds).
- REQ-165 [unwanted] If decoded content is not JPEG/PNG/WebP, multi-frame, >20 MiB, >32 MP, <32 px side, transparent, truncated or corrupt, then the system shall mark the scene unsupported/failed with a safe message keeping the original.
- REQ-166 [unwanted] If depth variation is below threshold, then the system shall set status "depth_uninformative" keeping original access.
- REQ-167 [always] The system shall provision the model via temp download + hash verify + atomic install at RAILREADY_DEPTH_MODEL_PATH, reuse a valid cache, reject mismatches and clean partial files; requests never download weights.
- REQ-168 [always] The system shall store a ready scene only after all artifacts and hashes are stored privately; failed staging is cleaned.
- REQ-169 [always] The system shall key processing on workspace + evidence + source hash + orientation/derivative transform + model hash + processor revision + projection params; a new key creates a new immutable revision.
Anchors
- REQ-170 [always] The system shall convert raw-image regions to oriented coordinates with the 8 EXIF corner transforms (envelope) and undo crop/letterbox transforms before anchoring; already-oriented regions are not transformed.
- REQ-171 [always] The system shall compute auto anchors at box centre sampled to the pixel centre via anchor_from_box, unique on (scene revision, evidence, finding).
- REQ-172 [unwanted] If a manual placement exists, then the system shall keep it on automatic refresh unless the user explicitly replaces it.
- REQ-173 [event] When a finding region changes, the system shall update or mark stale only its automatic anchor without new findings or detection.
API
- REQ-174 [event] When POST /api/evidence/{id}/photo-scene is called, the system shall return 200 with the ready scene for a matching key or 202 with the queued/processing job.
- REQ-175 [always] The system shall serve GET /api/photo-scene-jobs/{job_id}, GET /api/photo-scenes/{scene_id} {scene_id, evidence_id, revision, scene_hash, status, manifest, assets{splat, oriented_photo, original: {kind signed_url|authenticated_route, url, content_type, byte_length, sha256, expires_at}}}, GET /api/photo-scenes/{scene_id}/anchors, PUT /api/photo-scenes/{scene_id}/anchors/{finding_id} {u,v,expected_version}, and optional GET/PUT saved view.
- REQ-176 [always] The system shall return errors as {code, message, retryable} without paths, credentials or stack traces.
Viewer (web)
- REQ-177 [always] The system shall offer a "3D view" action beside each original photo in the visit/photo interface, opening the selected evidence; refresh and direct links restore that photo (evidence id in URL).
- REQ-178 [always] The system shall fit an inner viewport to the oriented photo aspect inside the scene panel (s=min(pW/iW,pH/iH), letterboxed) and size the canvas to it.
- REQ-179 [always] The system shall project 3D pins with the live camera view-projection (NDC->CSS px, DPR-aware), rejecting behind-camera/clipped points, updated after camera evaluation.
- REQ-180 [always] The system shall set camera horizontal FOV from the manifest, orbit mode, and verify/correct gsplat entity rotation so reset view aligns with the original photo.
- REQ-181 [always] The system shall use a monotonically increasing load generation, abort stale requests, destroy late-resolving stale viewers, and revoke Blob URLs on teardown.
- REQ-182 [always] The system shall show distinct states: no photo, queued, processing, downloading scene, rendering first frame, interactive ready, depth_uninformative, access denied, media expired, unsupported, graphics failure.
- REQ-183 [unwanted] If a signed asset URL expires, then the system shall refresh the descriptor once and reload the same asset without regeneration.
- REQ-184 [always] The system shall constrain orbit/pan/zoom near the capture viewpoint so the camera can't pass through the surface or view a fabricated rear.

## Acceptance (V01–V15 = journeys file)
Q-29 Tag: Pin.Projection | Scale: CSS px error at reset beyond half-sample tolerance, DPR 1 and 2, wide + tall | Must: 2 | Plan: 1
Q-30 Tag: Scene.Size | Scale: PLY MB for 384 sampling | Must: 16 | Plan: 8.3
