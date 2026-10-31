# Phase 3 journeys (web: desktop)

- JRN-68 steps: fresh private browser opens `/`. expected: product entry with "Open demo workspace" and "Field app", instructions, "Fictional sample data" label; no sign-in required to see it.
- JRN-69 steps: tap Open demo workspace. expected: signed in to a new demo session; jobs list shows fictional jobs incl. one "Saved analysis" job and one ready-to-estimate job; session id visible.
- JRN-70 steps: in demo session, request a seeded Ridgeline staff visit id or another demo session's id via API. expected: 404; no data.
- JRN-71 steps: tap Reset demo. expected: new session with new job ids; earlier session's decisions still exist server-side.
- JRN-72 steps: open a job -> visit review. expected: photos with highlighted candidate boxes, visible reason/uncertainty, model id + prompt version, "Saved analysis" label where prepared; transcript, proposed fields with excerpts, discrepancies, Not inspected areas.
- JRN-73 steps: confirm one candidate, dismiss another on web. expected: decisions persist after reload; dismissed one stays in staff history; mobile app shows the same decisions for that job.
- JRN-74 steps: upload a rail photo file on web into a draft visit and sync. expected: Verified + receipt; real image analysis runs and shows a candidate or "No candidate identified in this image" / "Cannot assess – request closer photo".
- JRN-75 steps: open estimate, preview tie package, add it, review lines, add a manual line. expected: server totals shown; origins visible; same numbers as API/mobile.
- JRN-76 steps: open agreement preview; Validate. expected: illustrative label, populated variables; blockers listed if any; Publish disabled while blocked.
- JRN-77 steps: publish; open contract detail; print. expected: version 1, contract Issued with template + document hash; print HTML legible, no internal data.
- JRN-78 steps: Share -> open `/p/:token` in a new private window. expected: customer page shows scope, photos, totals, agreement, terms, expiry; no cost/markup/margin/transcript/model data.
- JRN-79 steps: customer Accept with name/email/checkbox. expected: "Accepted"; contract Accepted; one work order; jobs list row shows work order.
- JRN-80 steps: open work order; assign crew/date; set access Requested. expected: frozen scope unchanged; access history attributed; no "repaired"/"released" wording.
- JRN-81 steps: alternate path: customer Request changes. expected: staff proposal screen shows the comment + topic suggestion; copy to new draft keeps history.
- JRN-82 steps: sign in on web as foreman. expected: estimate/publish actions hidden; direct API call returns 403.
- JRN-83 steps: capture on mobile (Expo) and sync, then open the job on web. expected: same visit/evidence/candidate ids and receipt id; no retyping.
- JRN-84 steps: view web app at 1440px and 360px. expected: no clipped or overlapping sections; keyboard focus visible; status uses text labels not color only.
- JRN-85 steps: force an API error (e.g. publish blocked / network failure). expected: server message shown; form inputs kept.
