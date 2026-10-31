# Phase 1: Shared backend + Expo field app + evidence/AI review
Version: phase-1. Context: docs/spec/overview.md (features F-1..F-10, F-21).

## Goal
A foreman signs in on the Expo app, prepares a visit online, captures photos/audio/notes offline with durable local save, syncs to verified private storage with one complete receipt, gets real server Whisper transcription + local-LLM extraction + (on capable iPhones) Apple FM photo candidates, confirms/corrects findings, answers departure questions and submits. An estimator sees the submitted visit on mobile in the office inbox/review.

## Functional requirements
- REQ-1 [always] The system shall resolve user, role and workspace from the server-side JWT session only.
- REQ-2 [unwanted] If a request references a customer/site/visit/observation/evidence outside the caller's workspace, then the system shall return 404 with no side effect.
- REQ-3 [event] When a foreman opens an assigned site and taps Prepare, the system shall show "Offline ready" with the preparation timestamp after the context bundle is committed locally.
- REQ-4 [event] When a photo, audio recording or note is captured, the system shall show "Saved on this device" only after record and bytes are durably written with UUID and SHA-256.
- REQ-5 [unwanted] If camera, microphone or storage permission is denied, then the system shall show the reason and offer typed fallback without losing saved items.
- REQ-6 [always] The system shall let a saved audio recording replay offline.
- REQ-7 [event] When the foreman taps Sync now, the system shall upload each item and show its state Queued, Uploading, Uploaded unverified, Verified, Retry wait or Blocked.
- REQ-8 [event] When all manifest members are verified by server size+hash, the system shall return one complete receipt for that manifest.
- REQ-9 [unwanted] If a manifest member is missing or its hash mismatches, then the system shall keep the transfer "Receiving partial" with no complete receipt.
- REQ-10 [unwanted] If an upload is retried after a lost acknowledgement, then the system shall return the existing record and receipt without duplicates.
- REQ-11 [event] When a complete receipt is issued, the system shall enqueue one persisted processing job per authorized audio item.
- REQ-12 [event] When transcription completes, the system shall store original audio reference, machine transcript, model id and source hash.
- REQ-13 [event] When a user corrects a transcript, the system shall store a new transcript version keeping the machine version.
- REQ-14 [event] When extraction runs, the system shall store schema-validated proposed fields each with a source excerpt present in the input.
- REQ-15 [unwanted] If extraction output is malformed, then the system shall attempt one repair and otherwise mark the stage "Failed" with Retry processing.
- REQ-16 [always] The system shall keep inspected quantity separate from proposed repair quantity.
- REQ-17 [unwanted] If two sources state different repair quantities, then the system shall show both as a discrepancy requiring resolution.
- REQ-18 [always] The system shall leave unstated fields null with a "Missing required" state.
- REQ-19 [event] When a saved transcript or extraction is reopened, the system shall make zero new model calls.
- REQ-20 [event] When the foreman taps Retry processing on a failed stage, the system shall rerun that stage without reupload.
- REQ-21 [unwanted] If a visit's outside-processing permission is Unknown or Denied, then the system shall block the model job with a visible blocker while manual entry stays available. (interpreted: server models count as processing)
- REQ-22 [event] When a photo is verified in a complete receipt, the system shall run one server image-analysis job with Claude Sonnet 5.5 on the actual photo bytes and store an ImageAnalysisRun.
- REQ-23 [unwanted] If image analysis fails or the provider is unavailable, then the system shall show the stage "Failed" with Retry processing while Add observation manually stays available.
- REQ-24 [always] The system shall store with each candidate the photo UUID/hash, normalized region or "unlocalized", category, visible reason, assessability, uncertainty text, raw model output, model id and prompt version.
- REQ-24a [always] The system shall limit automatic candidate categories to "possible missing/displaced fastener" and "visible tie-surface deterioration". (interpreted from rev 4.2 §7)
- REQ-24b [unwanted] If the fastening location is not sufficiently visible, then the system shall mark the candidate "Cannot assess – request closer photo".
- REQ-25 [unwanted] If a candidate region is out of bounds or the output is malformed, then the system shall reject that candidate and record the failure.
- REQ-26 [always] The system shall label a photo with no candidate "No candidate identified in this image".
- REQ-27 [event] When a reviewer taps Confirm, Correct, Dismiss or Request closer photo, the system shall record the decision with actor, time and candidate revision.
- REQ-28 [event] When a candidate is confirmed, the system shall create or link a human-reviewed observation preserving the original candidate.
- REQ-29 [always] The system shall never set repair quantity, specification, method or rate from a model output.
- REQ-30 [event] When the foreman opens Departure check, the system shall ask one missing-field question at a time with Answer and Needs estimator input.
- REQ-31 [always] The system shall never mark a field satisfied by an untranscribed recording.
- REQ-32 [always] The system shall show readiness per field as Provided, Missing required, Needs review, Unknown with reason, Not applicable, or Needs estimator input.
- REQ-33 [unwanted] If uploads for a visit are incomplete, then the system shall block Submit visit with the count of missing items.
- REQ-34 [event] When a visit is submitted, the system shall make it read-only for the foreman.
- REQ-35 [unwanted] If a write carries a stale expected revision, then the system shall return 409 and keep a recovery copy on the device.
- REQ-36 [event] When an estimator opens the office inbox, the system shall list submitted visits separately from draft transfers.
- REQ-37 [always] The system shall record a Not inspected area with a reason and no quantities.
- REQ-38 [always] The system shall record audit events for confirmations, corrections, submits and reopens.
- REQ-39 [event] When a different user signs in on the same device, the system shall hide the previous user's unsynced drafts.
- REQ-40 [always] The system shall serve its API contract at /api/openapi.json.
- REQ-41 [event] When a note or transcript is saved on the server, the system shall run a Jev yes/no urgent-concern check and store the result with model id.
- REQ-42 [event] When the urgent-concern check returns yes, the system shall show "Possible urgent concern – check escalation procedure" with the configured escalation instruction and "Saving does not notify anyone." (interpreted: lowest priority; may be deferred if Phase 1 runs late)
- REQ-43 [event] When a note or transcript is saved on the server, the system shall run a Jev yes/no check for embedded instructions to the app.
- REQ-44 [event] When the embedded-instruction check returns yes, the system shall show "Contains instructions – treated as untrusted text" to staff.
- REQ-45 [event] When a departure question is answered by typing, the system shall run a Jev relevance score on the answer against the question.
- REQ-46 [event] When the answer relevance score is low, the system shall set that field to "Needs review" with "Answer may not address the question".
- REQ-47 [always] The system shall never change scope, quantity, price, readiness rule, role or confirmation from a Jev result.
- REQ-48 [unwanted] If a Jev call fails or processing permission is not Granted, then the system shall show no flag with the check marked "Not run" and keep manual work available.

## Quality requirements
Q-1 Tag: Capture.Durability | Scale: % saved items present with matching hash after app kill/reopen | Meter: manual + tester, 10 items | Must: 100 | Plan: 100
Q-2 Tag: Sync.Integrity | Scale: duplicate records after 3 forced retries | Meter: API test | Must: 0 | Plan: 0
Q-3 Tag: Transcription.Latency | Scale: seconds for 60s audio on server CPU | Meter: timed run x3 | Must: 120 | Plan: 40 (estimate)
Q-4 Tag: Extraction.Faithfulness | Scale: invented field values (no excerpt) per run | Meter: 5 runs on demo note | Must: 0 | Plan: 0
Q-5 Tag: Isolation.Exposure | Scale: foreign records returned in cross-workspace probes | Meter: API test, 10 probes | Must: 0 | Plan: 0
Q-6 Tag: Candidate.Trust | Scale: candidates stored without photo hash/raw output/model | Meter: DB check | Must: 0 | Plan: 0
Q-7 Tag: Field.Usability | Scale: minutes for a first-time foreman to capture 1 photo + 1 note + sync | Meter: human | Must: 5 | Plan: 2
Q-8 Tag: Device.Compat | Scale: capture + sync works on Expo Go iOS/Android and Expo web preview | Meter: human + tester | Must: pass | Plan: pass
Q-9 Tag: ImageAnalysis.Latency | Scale: seconds from verified photo to candidates shown | Meter: timed x3 | Must: 60 | Plan: 15 (estimate)
Q-10 Tag: ImageAnalysis.Honesty | Scale: forced/fabricated positives or invented boxes on negative/obscured set | Meter: 3 neg + 3 obscured photos | Must: 0 | Plan: 0
