# Phase 5: Camera crash fix + field/office redesign + automatic prep/sync + org policy + contractor checklists
Version: phase-5. Source: redesign brief (2026-10-24 evening). Builds on Phases 1–4b as delivered (all tested CLEAN). Preserve auth, roles, shared backend, private storage, local drafts, evidence IDs, AI adapters, photo-scene viewer and commercial workflow. Supersedes: manual "Prepare for offline" gate and per-visit Granted/Denied/Unknown selection on capture.

## Order of work
1 camera/recording crash + data safety -> 2 automatic prep/connectivity/policy inheritance -> 3 navigation + capture layout -> 4 checklist templates + adaptive review -> 5 remaining mobile/office screens -> 6 regression.

## Functional requirements
Camera & recording (mobile)
- REQ-185 [event] When the user taps Take photo, the system shall request camera permission in context, launch the camera once, and return to the inspection without crashing.
- REQ-186 [unwanted] If camera permission is denied or permanently denied, then the system shall show the reason with "Open settings" and "Use photo library".
- REQ-187 [unwanted] If the camera is unavailable (web/simulator), then the system shall offer "Use photo library" / file picker.
- REQ-188 [unwanted] If Take photo is tapped again while a launch is in progress, then the system shall ignore the extra tap.
- REQ-189 [event] When a photo returns from camera/picker, the system shall copy it to durable app storage, hash it, commit the record, then show "Saved on device".
- REQ-190 [always] The system shall keep full-resolution media out of component state as base64 and use oriented thumbnails in lists.
- REQ-191 [unwanted] If the format is unsupported (e.g. HEIC on server), then the system shall keep the original and show the JPEG/PNG fallback message without crashing.
- REQ-192 [event] When the user taps Record note, the system shall open a recording sheet with timer, stop, cancel, playback and save.
- REQ-193 [unwanted] If recording is interrupted (backgrounded, call), then the system shall keep the bytes captured so far as a recoverable draft.
- REQ-194 [always] The system shall keep the unsaved inspection intact after any camera, picker or recorder error.
Automatic prep, sync, connectivity
- REQ-195 [event] When the user is authenticated online, the system shall cache assigned site summaries, assigned checklist templates and active inspections in the background.
- REQ-196 [always] The system shall show "Available offline" for a site only after its bundle has committed locally.
- REQ-197 [always] The system shall let capture proceed regardless of preparation state.
- REQ-198 [event] When a capture is saved and the backend is reachable, the system shall sync it automatically and enqueue permitted processing after verified receipt.
- REQ-199 [always] The system shall determine connectivity by backend reachability, with bounded backoff retries on reconnect and foreground.
- REQ-200 [always] The system shall show one quiet sync status: "All changes synced", "N items waiting to sync", or "Offline · saved on this device", opening Sync details on tap.
- REQ-201 [always] The system shall keep Sync now / Retry inside Sync details.
- REQ-202 [event] When a previously authenticated user starts an inspection at an uncached site offline, the system shall create a local draft with a provisional site label, generic checklist and "Site details unavailable offline".
- REQ-203 [event] When a provisional draft reconnects, the system shall require the user to pick the authorized server site before syncing, never auto-creating a customer/site.
- REQ-204 [unwanted] If auth has expired, then the system shall keep that user's local drafts usable and require sign-in before syncing.
- REQ-205 [always] The system shall list server-side authorized inspections (not only those created on this device) under In progress, labelled not available offline until cached.
Organization processing policy
- REQ-206 [always] The system shall resolve processing permission from a versioned organization policy with site/customer restrictions and evidence-level exceptions, recorded on each inspection with policy version and basis.
- REQ-207 [always] The system shall remove the Granted/Denied/Unknown controls from the capture screen.
- REQ-208 [always] The system shall let only admin (configuration) roles change organization policy.
- REQ-209 [always] The system shall preserve existing per-visit Denied/Unknown values as restrictions, not convert them to Granted. (interpreted: migration)
- REQ-210 [unwanted] If effective policy blocks processing, then the system shall show a compact message "Analysis not enabled for this site – contact your admin" and keep manual capture/review.
- REQ-211 [always] The system shall recheck effective policy when each job executes.
- REQ-212 [always] The system shall seed a fictional demo site with processing allowed by policy.
Checklist templates
- REQ-213 [always] The system shall seed versioned editable templates "Tie replacement", "Fastener repair", "Pavement/track-edge repair", "General observation", labelled "Sample contractor template – not a validated engineering standard".
- REQ-214 [always] The system shall define per template field: applicability, unit, conditional questions, stage (capture/handoff/pricing), allowed Unknown/Defer/Not applicable, and confirming role.
- REQ-215 [event] When an inspection starts, the system shall assign a default template from site/work type, changeable visibly by estimator/admin.
- REQ-216 [event] When an authorized user edits a template, the system shall create a new version without rewriting active inspections or issued documents.
- REQ-217 [always] The system shall ask material responsibility and access once at inspection level, inherited by findings with explicit overrides.
- REQ-218 [always] The system shall keep inspected count optional and never derive repair count from it.
- REQ-219 [event] When AI suggestions arrive, the system shall ask only unresolved, contradictory or newly relevant questions and never re-ask a confirmed answer.
- REQ-220 [event] When a pavement note is processed, the system shall ask repair area + unit, depth/specification where required, material, responsibility and access, never adding a tie package.
- REQ-221 [always] The system shall price pavement/general work through manual estimator lines under the same gates.
Review (mobile)
- REQ-222 [always] The system shall show Review inspection grouped as Needs your review / Missing information / Ready, with jump-to-item.
- REQ-223 [event] When an item is opened, the system shall show source excerpt/photo beside the proposed answer with Confirm, Correct, Ask estimator.
- REQ-224 [event] When Ask estimator is chosen, the system shall require a short reason and keep the item visibly unresolved.
- REQ-225 [always] The system shall show blockers next to the relevant item rather than silently disabling controls.
Design (both frontends)
- REQ-226 [always] The system shall use tokens: canvas #F3F4F4, surface #FFFFFF, text #202428, secondary #59636B, border #D9DEE2, nav #22272B, action #B32624; teal only for scene selection; status = text + line icon.
- REQ-227 [always] The system shall use system sans; mobile body 16, secondary 13–14, titles 22–24; 8px rhythm; 6–8px radii; 1px separators; controls 44–48px (capture 52–56px).
- REQ-228 [always] The system shall keep hashes, byte counts, receipts and model metadata out of default views, available under Evidence details / Sync details.
- REQ-229 [always] The system shall use the terms Inspection, Start inspection, Resume inspection, Review inspection, Saved on device, Synced, Processing, Needs review.
- REQ-230 [always] The system shall place Sign out in an account menu.
- REQ-231 [always] The system shall render the same design system across web login, jobs, visit review, evidence, estimate, agreement, proposal, customer page and work order, preserving the charcoal scene workspace.

## Quality requirements
Q-31 Tag: Camera.Stability | Scale: crashes in 20 camera launch/cancel/capture cycles incl. rapid taps + background/foreground | Meter: physical device (human) | Must: 0 | Plan: 0
Q-32 Tag: Start.Speed | Scale: taps from Home to camera open for a fresh foreman | Meter: tester | Must: 3 | Plan: 2
Q-33 Tag: Sync.Auto | Scale: manual actions needed to get an online capture to Synced | Meter: tester | Must: 0 | Plan: 0
Q-34 Tag: UI.Layout | Scale: clipped labels/overflow at 360, 390, 1440 and 200% text | Meter: screenshots | Must: 0 | Plan: 0
Q-35 Tag: Policy.Safety | Scale: provider calls under blocked policy | Meter: API test | Must: 0 | Plan: 0
Q-36 Tag: Questions.Repeat | Scale: confirmed answers re-asked after new AI results | Meter: API test | Must: 0 | Plan: 0
