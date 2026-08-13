# Complete Manual Testing Steps — Admin & Kiosk Updates

## What Changed in this Session

| App / Component | Feature | Details |
|---|---|---|
| **Admin Dashboard** | **Live Metrics & Activity** | Live dashboard metric cards and recent scan event feed. |
| **Admin Devices** | **Device Registration** | Form factor + location picker modal generating 8-character pairing codes (fixes `NetworkError`). |
| **Admin Settings** | **App Settings** | Displays all 65 configurations in 9 collapsible categories using custom inputs. |
| **Kiosk App** | **PIN/QR Fallback** | Touchscreen numeric keypad and text input widget for alternative check-in. |
| **Kiosk App** | **Offline Queue** | IndexedDB storage queue that caches check-ins when offline. |
| **Kiosk App** | **Monotonic Replay** | Replays queued events with monotonic clock offset calculations for backdating. |
| **Kiosk App** | **Operator Safety** | Warning prompt before closing the tab with unsent queued scans. |

---

## Prerequisites

### 1. Run local Backend (IPv4 bind)
```bash
cd /Users/teng/Developer/Practical/Personal/Others/attendance-tracker-ai-app
uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 2. Run local Frontend
```bash
cd /Users/teng/Developer/Practical/Personal/Others/attendance-tracker-ai-app/frontend
bun run dev
```

### 3. URLs
- **Kiosk Application**: `http://localhost:5173`
- **Admin Dashboard**: `http://localhost:5178`

---

## Test 1: Admin Dashboard — Live Metrics

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open **http://localhost:5178** | Dashboard page loads. |
| 2 | Check **Active People** card | Shows `1` (Lester). |
| 3 | Check **Registered Kiosks** card | Shows current device count from database (e.g. `4` or more). |
| 4 | Check **Scans Today** card | Shows `0` (or real count if you ran scans today). |
| 5 | Scroll to **Recent Activity** section | Shows up to 10 recent scan events with name, status badge, and time. |

---

## Test 2: Admin Devices — Register New Device

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click **"Kiosks & Devices"** in the left sidebar | Navigates to `/devices` and loads the device list. |
| 2 | Click **"+ Register Device"** | Modal opens with **Form Factor** and **Location** dropdowns. |
| 3 | Select **Desktop / Laptop** and **Main Campus** | Both dropdown fields update. |
| 4 | Click **"Generate Pairing Code"** | ✅ Transitions to a success view displaying an 8-character pairing code (no `NetworkError`). |
| 5 | Click **"Done"** | Modal closes and the new device appears in the table as `UNPAIRED`. |

---

## Test 3: Admin Settings — App Configs

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click **"Settings"** in the left sidebar | Navigates to `/settings`. |
| 2 | Page loads | 9 collapsible category cards appear. |
| 3 | Collapsible behavior | Click any collapsed card (e.g. **Scan Behavior**) → expands smoothly with chevron rotation. Click again → collapses. |
| 4 | Numeric settings | Progress bar (min→max) + value badge (e.g. match threshold `0.45`). |
| 5 | Boolean settings | Cyan toggle switch if on, gray toggle if off. |
| 6 | Enum settings | Disabled dropdown displaying the current value. |
| 7 | Hex colors | Color swatch square + hex code. |

---

## Test 4: Kiosk Fallback — PIN / QR Check-In

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to **http://localhost:5173** | Kiosk page loads. |
| 2 | Click **"Connect Kiosk"** in header | WebSocket connects and shows **Connected** in green. |
| 3 | View **PIN / QR Code Fallback** card | Renders below camera status. Displays text input field and a tactile 0-9 numerical keypad. |
| 4 | Enter valid PIN `12345` | Type using the numeric keypad or your keyboard. Click **"Check In"** (or press Enter). |
| 5 | **Expected** | Screen shows a flash effect, and pops up the green **"Punch Success"** card showing check-in success. |
| 6 | Enter invalid PIN `99999` | Type it and click **"Check In"**. |
| 7 | **Expected** | Rose-red error bubble at bottom shows: `"Invalid PIN or QR code"`. |

---

## Test 5: Kiosk Offline Queue — Storage & Monotonic Replay

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click **"Disconnect Kiosk"** in header | WS disconnects and shows **Disconnected** in red. |
| 2 | Enter valid PIN `12345` | Click **"Check In"**. |
| 3 | **Expected** | Scans are queued! A pulsing amber badge appears in the top-right header: **"1 Offline scan queued"**. Bottom notification: `"Offline: Scan queued in local database."`. |
| 4 | Wait 30 seconds | (To verify elapsed monotonic offset calculation). |
| 5 | Enter PIN `12345` again | Click **"Check In"**. |
| 6 | **Expected** | Queue badge increments to **"2 Offline scans queued"**. |
| 7 | Click **"Connect Kiosk"** in header | WS reconnects and shows **Connected** in green. |
| 8 | **Expected** | Replay begins! The right logs console shows `Replaying 2 queued offline scans...` and `All offline scans replayed successfully.`. The queue badge disappears. |
| 9 | Verify Database Timestamps | Query `attendance_events`: the `occurred_at` times must correspond to when they were originally inputted (30+ seconds ago), not replay time, and `was_backdated` must be `True`. |

---

## Test 6: Operator Safety — Browser Exit Warning

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click **"Disconnect Kiosk"** in header | WS status shows red **Disconnected**. |
| 2 | Queue a scan | Enter `12345` and click **"Check In"** (header badge shows `"1 Offline scan queued"`). |
| 3 | Try to close browser tab / refresh page | Browser blocks action. |
| 4 | **Expected** | Confirmation dialog pops up warning the operator: `"Warning: You have unsent offline scans. If you close this page, they might be lost."`. |
| 5 | Connect Kiosk | Let queue replay to 0, then try closing/refreshing tab → closes cleanly with no warnings. |
