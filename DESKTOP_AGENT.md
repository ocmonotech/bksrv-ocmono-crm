# Desktop activity tracking agent

This document describes how the **desktop app** (agent) that reports user usage should behave so it does not get in the way of normal work.

## Auth: avoid 401 on snapshot

The backend and desktop app must use the **same token and same API base URL**.

1. **Login**  
   - Call **POST /login** with `{ "username": "...", "password": "..." }` on the **same base URL** as the CRM (e.g. `https://bkcrm.ocmono.com`).  
   - Response includes **both** `access_token` and `token` (same value). Read either:  
     `const token = data.token ?? data.access_token ?? data.bearer_token;`

2. **Protected routes (e.g. POST /user-usage/snapshot)**  
   - Send the token in **one** of these ways:  
     - **Authorization:** `Authorization: Bearer <token>`  
     - **Or header:** `X-Access-Token: <token>`  
   - Backend validates with the same secret and algorithm used at login (HS256, 24h expiry).  
   - If you get **401**, the response body is JSON: `{"detail": "...", "code": "token_expired" | "invalid_token" | "missing_token" | "user_not_found"}`. Always use `response.json()` (do not parse as HTML). On 401, **log out and log in again** in the desktop app (same base URL).

3. **Base URL**  
   - Use the **exact** CRM API base (e.g. `https://bkcrm.ocmono.com`). If the app used a different host or port, the token from one server will not work on the other.

## Do not minimize to taskbar

- **Do not** minimize the app to the taskbar like a normal window. Users need to do other work; if the app sits in the taskbar or pops up, it gets in the way.
- **Do** run in the **system tray** (notification area). The app should:
  - Start minimized to tray (no main window on taskbar).
  - Optionally show a small tray icon; user can open settings from there.
  - Never steal focus or minimize other windows.

So: **minimize to tray only, not to taskbar.** The app should be invisible in the taskbar and only visible in the system tray.

## What to report to the API

Send data to:

- **POST /user-usage/snapshot** (with Bearer token)

Body (JSON):

| Field | Meaning |
|-------|--------|
| `screen_active_seconds` | **Overall** screen visible/on time in the period (total time the screen was on and visible, not per-app). |
| `mouse_active_seconds` | Time the user was **actively using the PC**: mouse moved/clicked or keyboard used. Use this to know “how long the user worked” on the PC. |
| `bandwidth_received_bytes` | Bytes received (optional). |
| `bandwidth_sent_bytes` | Bytes sent (optional). |
| `applications_running_count` | Number of running apps (optional). |

- **POST /user-usage/applications** (with Bearer token)

Body (JSON):

- `applications`: array of `{ "application_name": "e.g. Chrome", "usage_seconds": 1200 }`

So the backend can show **which app** the user used and **for how long**.

## Random screenshots (5 per user per day)

Take **5 random screenshots per user per day** and upload them so admins can see activity.

- **POST /user-usage/screenshot** (with Bearer token)

  - **Content-Type:** `multipart/form-data`
  - **Body:** `file` = image file (PNG/JPEG/WebP, max 5 MB); optional `captured_at` = ISO datetime when the screenshot was taken (e.g. `2026-02-20T10:30:00Z`).
  - The backend allows **at most 5 screenshots per user per calendar day**. If you send more than 5 for the same day, you get 400.
  - Schedule the desktop app to take screenshots at **random times** during the day (e.g. 5 random times between login and end of day), then POST each one to this endpoint.

- **GET /user-usage/screenshots** – list current user’s screenshots (optional `from_date`, `to_date`).
- **GET /user-usage/screenshots/{id}/image** – get the image (same auth; Admin can view any user’s).

## Summary

- **Screen time**: total time the screen was visible (overall).
- **Mouse/input time**: time with mouse/keyboard activity = “worked on PC” time.
- **Per-app**: which application was used and for how many seconds.

Implement the desktop app so it **minimizes to system tray only** and reports the three metrics above; the web app will show them in the activity report.
