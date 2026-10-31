# RailReady

Field-to-invoice software for small rail inspection and repair contractors. Built at VibeCon 2026 (Construction track) by Team Railready.

A foreman walks the track with a phone, captures photos, voice notes and measurements offline, and syncs them when signal returns. The office reviews AI-suggested findings, prices the repair, and sends the customer a proposal link. Acceptance creates exactly one work order.

## What it does

- **Offline field capture.** Expo app with a local SQLite store, SHA-256 hashed evidence and an outbox that syncs with backoff.
- **Photo and voice analysis.** Image findings and speech-to-text extraction come back as candidates. A person confirms every one before it reaches an estimate.
- **Interactive 3D view per photo.** Depth Anything V2 Small (ONNX, pinned and hash-verified) turns a single photo into a Gaussian-splat scene in the browser, with finding markers linked to the original image.
- **Estimating and proposals.** Decimal money math, frozen agreement packets, immutable versions, and public proposal links that store only a token hash.
- **Accept to work order.** Compare-and-swap writes plus unique indexes guarantee one accepted proposal yields one work order.
- **Map-first inspections.** Start an inspection from a pin on a rail-only map (public GTFS, NTAD and Caltrans data), by GPS, coordinates or a verified milepost.
- **Repairs, paperwork and invoicing.** Office-started repairs with PO references, generated work-order, invoice and packet PDFs, contract progress packets and an optional invoice email channel.
- **Video capture and review**, plus a step guide (Capture, Review, Details) and handoff checklists that block submission until required items are answered.
- **Role scoping.** JWT auth. Foremen, estimators and customers each see only their own routes and data.

## Stack

| Part | Technology |
| --- | --- |
| API | Python, FastAPI, MongoDB |
| Web app | React 19, Tailwind, PlayCanvas SuperSplat viewer |
| Field app | Expo 58, React Native, expo-router, expo-sqlite |
| Models | Depth Anything V2 Small (ONNX), LLM image and text adapters, Whisper transcription |

## Layout

```
backend/    FastAPI service, domain modules, seed data, tests
frontend/   Web workspace (office, estimating, 3D scene, proposals)
mobile/     Expo field app
eval/       Tie and fastener image evaluation set (openly licensed images, manifest, results)
docs/spec/  Product requirements and user journeys, by build phase
```

## Running locally

1. Start MongoDB. In `backend/`, `frontend/` and `mobile/`, copy `env.example` to `.env` and fill it in. The seed script and the tests read the demo account password from `SEED_PASSWORD`.
2. Install the API dependencies (Python 3.11). `emergentintegrations` comes from Emergent's package index, and `llama_cpp_python` is only needed for the optional local text model:
   ```
   cd backend
   grep -vE '^(emergentintegrations|llama_cpp_python)' requirements.txt > /tmp/req.txt
   pip install -r /tmp/req.txt
   pip install --no-deps emergentintegrations==0.2.2 --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
   uvicorn server:app --port 8001
   ```
3. `cd frontend && yarn install && yarn start`
4. `cd mobile && yarn install && yarn start`
5. Tests: with the API running, `cd backend && pytest api_tests`.

AI features need `EMERGENT_LLM_KEY` (or your own adapter) and `RAILREADY_DEPTH_MODEL_PATH` pointing to the downloaded depth model. The app was built on the Emergent platform, and some integrations route through its proxy by default.

## Team

Joshua Muellenbach and Karthik Reddy Pagilla.

## License

MIT. See `LICENSE`.

## Credits

- Depth Anything V2 Small, Apache-2.0: https://huggingface.co/depth-anything/Depth-Anything-V2-Small
- SuperSplat viewer: https://github.com/playcanvas/supersplat-viewer
- Evaluation images are Wikimedia Commons files under CC0, PD, CC BY or CC BY-SA. Authors and licenses are listed per row in `eval/tie_fastener/manifest.csv`.
- The blank work-order layout in `backend/form_templates/` comes from a free public Smartsheet template; source and disclaimer are in `generic_repair_work_order_v1.json`. It is not covered by this repo's MIT license.
