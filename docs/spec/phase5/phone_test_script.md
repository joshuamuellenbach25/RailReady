# Phase 5 – phone test script (Expo Go: real device)

You'll need Expo Go on an iPhone (the crash was reported on an iPhone 17 running iOS 27.1) or on an Android phone. Use the seeded foreman account, foreman@ridgeline.example, with the password set in `SEED_PASSWORD`. No photos or recordings are sent anywhere except the RailReady backend.

## A. Camera smoke test (run this first – it locates the crash)
1. Open the app. On the login screen, tap **Camera check**. You can also get there after signing in: **Account -> Camera check**.
2. Tap the buttons in order:
   1. **1. Check permission status**
   2. **2. Request permission**
   3. **3. Open camera (minimal options)**
   4. **4. Open photo library**
3. Before each native call, the app writes a breadcrumb to the device. Breadcrumbs contain step names only, never media or credentials.
4. If the app crashes, reopen it. On the next launch it uploads the stored breadcrumbs to `/api/diagnostics/breadcrumbs`.
5. The office team reads the breadcrumbs through `GET /api/diagnostics/breadcrumbs` (admin/estimator). `last_step` is the step that ran just before the crash.
6. Report which numbered step you were on when it crashed.

## B. Take photo (REQ-185..191)
1. **My work -> Assigned sites -> Pinecrest** (any site works). Tap **Start inspection**.
2. Tap **Take photo**.
   - First time: a short explanation sheet appears, then the system permission prompt. Allow it.
   - If you deny: the sheet offers **Open settings**, **Use photo library** and **Type a note instead**.
3. Take a photo and tap **Use Photo**. You should return to the inspection with "Photo – Saved on device", and the thumbnail should appear upright.
4. Tap **Take photo** twice quickly. Only one camera should open.
5. Lock the phone with the camera open, unlock it, and cancel the camera. The inspection should still be intact.
6. On Android, the photo should still save if the OS recreates the activity while the camera is open.

### B2. Record note on iPhone (regression check for the freeze)
1. In an inspection, tap **Record note**.
   - First time: the microphone explanation sheet and the system prompt appear **before** the recording sheet opens. Allow it.
2. The **Record note** sheet opens. Tap **Start recording**. The button shows a spinner for less than a second, then the timer runs and a **Stop** button appears. The app must not freeze.
3. Speak for 5 seconds, tap **Stop**, then **Play back**. You should hear the recording.
4. Tap **Save recording**. The sheet should close right away with "Recording – Saved on device". Saving doesn't wait for the network or transcription.
5. Turn on airplane mode and repeat steps 1–4. It should behave the same.
6. If anything hangs, force-quit and reopen the app. Then tell us the time. Each step's breadcrumb is uploaded on the next launch (record.tap, record.permission_before_sheet, record.start_tap, record.permission, record.mode, record.prepared, record.started, record.stopped, record.save, record.saved, record.error).

## C. Record note (REQ-192..194)
1. Tap **Record note**. A sheet opens; tap **Start recording**. The timer should run.
2. Tap **Stop**, then **Play** (playback), then **Save**. You should see "Recording – Saved on device".
3. Start another recording, then tap **Cancel**. Nothing should be saved.
4. Start a recording and switch to another app (or take a call). Come back. The partial recording should be kept with "Recording interrupted – kept what was captured".

## D. Automatic offline + sync (REQ-195..199)
1. Open a site while online. The status should change to **Available offline** by itself (there is no Prepare button).
2. Turn on airplane mode and take a photo. It should save with "Saved on device", and the My work status line should show "Offline – captures save on this device".
3. Turn airplane mode off and bring the app to the foreground. The status line should become "All captures synced". Tap it to open **Sync details**, where hashes and receipts are listed.

## E. Policy (REQ-206..212)
- There is no Granted/Denied/Unknown control on the capture screen any more.
- When an admin restricts the site, the inspection shows "Analysis not enabled for this site – contact your admin". Capture still works.

## F. Account
- Sign out is under **Account** (top right of My work).
- If items are unsynced, it warns you before signing out.
