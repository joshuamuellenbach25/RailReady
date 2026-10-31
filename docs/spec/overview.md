# Requirements: RailReady (VibeCon cut of plan rev 4.2)

Source: RailReady plan, revision 4.2. This overview is the core scope built for VibeCon 2026. Everything in rev 4.2 not listed here is deferred.

## Core Value
A foreman captures rough site evidence once; AI flags possible visible damage/missing components and missing estimating details; the foreman confirms; the estimator turns it into a traceable tie-replacement proposal + contract packet; customer acceptance produces exactly one work order. Same records on phone and web.

## Personas & Roles
| Role | Can | Cannot |
|---|---|---|
| Foreman | Assigned visits, own draft capture, answer questions, confirm/defer findings, review visual candidates, submit | Edit submitted visit, publish, change rates |
| Estimator/ops | Submitted visits, corrections, estimate/package, agreement review, publish, share/revoke link, reopen, work-order crew/date/access | Modify published/accepted snapshots |
| Workspace admin | Seeded only (no admin UI) |, |
| Demo visitor | Own isolated fictional demo session with foreman+estimator powers on that session only | See other sessions or real records, bypass gates |
| Customer bearer link | Read one published version + selected photos, accept or request changes | Internal costs, markup, audio, transcripts, audit, dismissed candidates |
Roles, workspace and scope are always resolved server-side.

## Features
| id | Feature | Persona | Phase |
|---|---|---|---|
| F-1 | Seeded JWT email/password login, server-resolved roles, workspace isolation (2 workspaces) | all | 1 |
| F-2 | Customers/sites/tracks/visits; visit fields incl. coverage + Not inspected areas with reason | foreman | 1 |
| F-3 | Phone capture: photos, real audio recording + replay, typed notes, manual measurements, location text | foreman | 1 |
| F-4 | Durable on-device save of records + media bytes (UUID + SHA-256) shown "Saved on this device"; survives app restart; works offline after online prepare | foreman | 1 |
| F-5 | Outbox: Sync now, per-item states, retry; upload to private object storage with server hash/size verification; immutable transfer manifest + one complete receipt (idempotent) | foreman | 1 |
| F-6 | Server open-source Whisper transcription of audio, original + machine + corrected transcript versions with model provenance | foreman/estimator | 1 |
| F-7 | Server open-source local LLM text extraction -> schema-validated proposed fields with source excerpts, missing fields, discrepancies (12 inspected vs 8 replace, supplier) | foreman/estimator | 1 |
| F-8 | Server photo analysis (Claude Sonnet 5.5) -> VisualCandidate (region or unlocalized, category, visible reason, assessability, uncertainty, raw output, model/prompt metadata); Confirm/Correct/Dismiss/Request closer photo | foreman/estimator | 1 |
| F-9 | Departure check: one question at a time, Answer / Needs estimator input; deterministic readiness labels; submit visit online | foreman | 1 |
| F-10 | Office inbox (draft-transfer vs submitted), visit review with evidence, candidates, transcript, proposals, conflicts | estimator | 1 |
| F-11 | Estimate: tie-replacement package preview/add once, customer-supplied materials, manual lines, quantity origins, line review, exact decimal pricing, stale flags | estimator | 2 |
| F-12 | Versioned illustrative agreement template -> agreement preview; issue blocked on missing variables/stale versions | estimator | 2 |
| F-13 | Publish gate + atomic immutable proposal+agreement snapshot (hashes), numbered versions, supersede, idempotent | estimator | 2 |
| F-14 | Customer bearer link (>=128-bit, hashed), revoke, expiry (site TZ -> UTC), allowlisted view + media | customer | 2 |
| F-15 | Accept (name, email, checkbox) or request changes; transactional, one work order per engagement | customer | 2 |
| F-16 | Work order: frozen scope, crew/date, access Not arranged -> Requested -> Confirmed | estimator | 2 |
| F-17 | All estimator actions (F-10..F-16) available in the mobile app | estimator | 2 |
| F-18 | Web frontend on same backend: jobs, visit review, candidates, estimate, contracts list/detail/print, proposals, work orders; browser file upload fallback | estimator/visitor | 3 |
| F-19 | Public `/` + `/demo` entry, Open demo workspace creates isolated fictional session; test login | visitor | 3 |
| F-20 | Customer page `/p/:token` and printable proposal/contract HTML | customer | 3 |
| F-21 | Audit events, effort counters (capture/review time, clarification calls, corrections, repeat visit) | estimator | 1–3 |
| F-23 | Jev fast text decisions: urgent-concern flag, suspicious-instruction flag, departure-answer check (Phase 1); change-request topic (Phase 2) | foreman/estimator | 1–2 |
| F-24 | Per-photo AI-estimated depth scene + anchors (location_basis single_photo_estimated_depth), private assets | estimator | 4 |
| F-25 | Web inspection workspace /office/visits/:id/scene (inventory <-> markers <-> evidence drawer) | estimator/visitor | 4 |
| F-26 | Marketing entry refresh + business-rule corrections (whole tie counts, per-request token revalidation, area-photo analysis) | visitor/estimator | 4 |
| F-22 | Deployment health check + device test checklist + demo script | user | 4 |

## Phases
- Phase 1, Shared backend + Expo field app + evidence/AI review: F-1..F-10, F-21 (partial). Docs: [phase1/requirement.md](phase1/requirement.md), [phase1/journeys.md](phase1/journeys.md)
- Phase 2, Estimating, contract packet, publish, customer decision, work order (mobile + API): F-11..F-17
- Phase 3, Web frontend mirror, public demo entry, customer page, print: F-18..F-20 (delivered)
- Phase 4, Web inspection workspace with per-photo AI-estimated depth scenes (Depth Anything V2 Small ONNX on server + SuperSplat viewer), landing refresh, business-rule corrections: F-24..F-26
- Phase 5, E2E hardening, device checklist, demo script; no public deployment during the build: F-22

## UI/UX Rules
- Large field controls, 360px layouts, keyboard/focus/labels, non-color status cues, high contrast. Industrial, plain, no marketing fluff.
- Truthful states always: "Saved on this device" != "Backed up to server" != "Processed". Upload state and AI state shown separately.
- Never "Track clear" / "No defect": use "No candidate identified in this image". Poor view -> "Cannot assess – request closer photo".
- Urgent concern shows configured escalation text + "Saving does not notify anyone."
- Sample/illustrative labels on seeded terms, rates and agreement template. Labeled "Saved analysis" for any pre-recorded genuine output.
- Preserve user inputs on any failure.

## Integrations
| Need | Choice | Notes |
|---|---|---|
| Photo analysis | **Claude Sonnet 5.5 on the server via Emergent Universal Key** | Runs automatically after verified upload, from mobile sync or web upload; behind its own provider adapter. Apple Foundation Models on-device is DEFERRED (adapter seam only, no UI). |
| Speech-to-text | **Open-source Whisper on our server** (faster-whisper, CPU) | Model id/size recorded per run |
| Text extraction | **Open-source local LLM on our server** (small instruct model via llama.cpp, CPU) (interpreted from "Local LLMs") | Schema-validated; one repair retry |
| Media storage | Emergent Object Storage (private) | Never base64 in DB |
| Fast text decisions | **Jev (TypeSafe) via Emergent Universal Key** | Suggestion/flag only; never changes scope, price, readiness, confirmation. Gated by visit processing permission. Phase 1: urgent-concern yes/no, instruction-injection yes/no, departure-answer relevance score. Phase 2: change-request topic classification. |
| Auth | JWT email/password, seeded accounts | password from `SEED_PASSWORD` |
| DB | MongoDB with unique indexes + transactions for publish/accept/work order | Equivalent guarantees per rev 4.2 §9 |

## Edge Cases
Competing counts 8 vs 10 both preserved, block publish; audio-only detail never satisfies a field; stale revision -> 409 + recovery copy; duplicate acceptance returns same work order; revoked/expired links deny read + decide; cross-workspace IDs -> 404 with no side effects; Not inspected areas carry no quantities; multiple photos never multiply repair counts; customer-supplied ties omit material line; candidates never set quantity/spec/price.

## Seed Data
Fictional contractor "Ridgeline Rail Services" workspace + second isolation workspace; 2 customers/sites; foreman, estimator, admin users; 2 crews; sample tie catalog (crosstie + switch tie specs, labor/handling/equipment/mobilization), sample tax 0% with configured flags; illustrative agreement template v1; escalation text; one outstanding prior finding, one Not inspected area, a visit missing specification, a competing-count case, a customer-supplied tie case.
