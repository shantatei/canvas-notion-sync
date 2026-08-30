# canvas-notion-sync

**Your Canvas deadlines and announcements, synced automatically into a Notion dashboard you actually want to look at.**

A scheduled job pulls outstanding assignments and announcements from your Canvas courses and keeps two Notion databases up to date — no browser tab, no manual copy-pasting, no dependency on any one device being on. Fork it, point it at your own Canvas account and Notion workspace, and it's yours.

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat&logo=python&logoColor=white">
  <img alt="Notion API" src="https://img.shields.io/badge/Notion-API-000000?style=flat&logo=notion&logoColor=white">
  <img alt="GitHub Actions" src="https://img.shields.io/badge/GitHub_Actions-Automation-2088FF?style=flat&logo=githubactions&logoColor=white">
  <img alt="Canvas LMS" src="https://img.shields.io/badge/Canvas_LMS-REST_API-E4002B?style=flat&logo=instructure&logoColor=white">
  <img alt="cron-job.org" src="https://img.shields.io/badge/cron--job.org-Scheduler-4CAF50?style=flat&logo=clockify&logoColor=white">
</p>

> No license file is included — this repo is private by default when forked. Add one yourself if you plan to make your fork public and want to set terms for reuse.

---

## Tech stack

| | Technology | Role |
|---|---|---|
| 🐍 | **Python 3.11** | The sync script — talks to both APIs directly via `requests`, no framework, no dependencies beyond that one library |
| 🎓 | **Canvas LMS REST API** | Source of truth for assignments and announcements, read via a personal access token |
| 📓 | **Notion API** (2025-09-03) | Destination — two databases (Deadlines, Announcements) upserted via the multi-source-database Pages API |
| ⚙️ | **GitHub Actions** | Runs the script in the cloud on a schedule, no server or laptop required |
| ⏰ | **cron-job.org** | Free external scheduler that reliably triggers the GitHub Actions workflow (see [Known limitations](#known-limitations--troubleshooting) for why this is used instead of GitHub's own `schedule:` trigger alone) |
| 🔑 | **GitHub Actions Secrets** | Encrypted storage for every credential the workflow needs — nothing sensitive ever touches the repo itself |

---

## How it works

```
Canvas LMS  ──REST API──▶  sync.py (GitHub Actions runner)  ──REST API──▶  Notion
                                     ▲
                            triggered daily by
                              cron-job.org
                          (POST → workflow_dispatch)
```

Each run:
1. Fetches assignments + announcements for a fixed list of Canvas courses
2. Filters out anything already submitted/graded or past its due date
3. Upserts the result into two Notion databases, matching existing rows by a stored Canvas ID so nothing is ever duplicated
4. Updates a "Last synced" heading at the top of the Notion page — green on success, red on failure — so you can tell at a glance whether it actually worked

## What you get

**Deadlines** database
- **Course** — colored tag per course
- **Urgency** — colored tag: red "Due Soon" (≤1 day), yellow "This Week" (≤3 days), green "Upcoming" (>3 days)
- **Day** — the day of the week, computed live from the due date
- **Status** — a to-do / in-progress / done property that's entirely yours: the sync never overwrites it once you've set it, and only removes a row once that assignment is actually done on Canvas or its due date has passed
- **Table view** (sorted by due date, sort/filter any column) and a **Board view** grouped by Status for a Kanban-style workflow — drag a card between columns to update its status

**Announcements** database
- **Course** tag, same colors as Deadlines
- **Read** checkbox — yours to control; once ticked, the title gets a strikethrough on the next sync
- Full announcement text saved as the page body, click in to read
- Nothing is ever removed, only added to
- **All Announcements** (newest first) and **Unread**-only views

---

## Fork this and use it for your own Canvas courses

This whole setup is generic — nothing here is tied to any one school beyond the Canvas instance URL. Budget **~25 minutes** for first-time setup, mostly manual Notion clicking (no API can script Notion database schemas or views for you) and a couple of one-time credential generations. After that, it runs itself.

### 1. Fork and clone

Click **Fork** on GitHub, then:

```bash
git clone https://github.com/<your-username>/canvas-notion-sync.git
cd canvas-notion-sync
gh auth login          # browser login to your own GitHub account, if you haven't already
```

### 2. Build the Notion side

You're building this by hand, once — the Notion API can create database *rows*, but not a schema with select options, nor views.

1. Create a new blank Notion page. Name it whatever you like (e.g. "My Canvas Dashboard").
2. Inside it, add a database (**Table** view) named **Deadlines**:

   | Property | Type | Notes |
   |---|---|---|
   | Name | Title | Notion adds this by default |
   | Course | Select | One option per course you're taking this semester — pick any colors |
   | Due Date | Date | |
   | Urgency | Select | Three options, names must match exactly: `Due Soon` (red), `This Week` (yellow), `Upcoming` (green) |
   | Day | Formula | `formatDate(prop("Due Date"), "dddd")` — shows the weekday, e.g. "Monday" |
   | Status | Status | Notion auto-creates 3 default groups — note whatever it names the "to-do" option (often "Not started"), you'll need it in step 6 |
   | Canvas ID | Number | Leave empty. Used internally to match rows across syncs — don't delete it once running |

3. Add a **Board view**: **+ Add view → Board → Group by → Status**.
4. In the same page, add a second database named **Announcements**:

   | Property | Type | Notes |
   |---|---|---|
   | Name | Title | |
   | Course | Select | Same options as above |
   | Posted | Date | |
   | Read | Checkbox | |
   | Canvas ID | Number | Same purpose as above — leave empty |

5. Add an **Unread** view: **+ Add view → Table**, filter `Read` **is not checked**, sort by `Posted` descending.

### 3. Get a Canvas API token

In Canvas: **Account → Settings → Approved Integrations → New Access Token**. Copy it immediately — it's shown once. Note your Canvas instance's base URL too (e.g. `https://canvas.yourschool.edu`).

### 4. Create a Notion integration and connect it

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) → **New integration**, grant workspace access, copy the **Internal Integration Secret**.
2. Open the page from step 2 → **···** menu (or **Share**) → **Connections** → add the integration. Without this it can't see or edit anything.

### 5. Find your Notion IDs

You need three: the page ID, and each database's *data source ID* (Notion's newer multi-source-database concept).

```bash
NOTION_TOKEN="paste-your-integration-token-here"

# Page ID: the 32-char string at the end of the page's URL — no API call needed.
# https://www.notion.so/My-Canvas-Dashboard-3c9a07227bd281329da3e85885f07a60
# -> 3c9a07227bd281329da3e85885f07a60

curl -s https://api.notion.com/v1/databases/<deadlines-database-id> \
  -H "Authorization: Bearer $NOTION_TOKEN" \
  -H "Notion-Version: 2025-09-03" | grep -A2 '"data_sources"'

curl -s https://api.notion.com/v1/databases/<announcements-database-id> \
  -H "Authorization: Bearer $NOTION_TOKEN" \
  -H "Notion-Version: 2025-09-03" | grep -A2 '"data_sources"'
```

Each call prints an `"id"` under `data_sources` — that's the ID you need (a UUID, distinct from the database's own URL).

### 6. Configure the script for your courses

Edit `scripts/sync.py`:

- **`COURSES`** — replace with your own `{canvas_course_id: "COURSE_CODE"}` pairs. Find each course's numeric ID in its Canvas URL (`.../courses/93698/...` → `93698`). Each code must exactly match a Select option from step 2.
- **`DEFAULT_STATUS`** — set to whatever Notion actually named your Status property's "to-do" option (step 2, point 2).

Commit and push.

### 7. Add the GitHub secrets

Add these yourself, directly — never share raw tokens in chat, even with an assistant you trust, since there's no way to un-send it:

```bash
gh secret set CANVAS_URL --body "https://canvas.yourschool.edu"
gh secret set CANVAS_TOKEN
gh secret set NOTION_TOKEN
gh secret set NOTION_PAGE_ID --body "<page-id-from-step-5>"
gh secret set NOTION_DATA_SOURCE_ID --body "<deadlines-data-source-id>"
gh secret set NOTION_ANNOUNCEMENTS_DATA_SOURCE_ID --body "<announcements-data-source-id>"
```

(Omitting `--body` on the two tokens prompts an interactive paste instead, keeping them out of shell history.)

### 8. Test it

```bash
gh workflow run daily-sync.yml
gh run watch
```

Confirm the Notion page updated. A failure's cause is almost always a `COURSES` code that doesn't exactly match a Select option, or the integration not being connected to both databases.

### 9. Set up reliable daily triggering

GitHub Actions supports a built-in `schedule:` trigger (already in `daily-sync.yml`, defaulting to `00:00 UTC`), but **relying on it alone is not recommended** — see [Known limitations](#known-limitations--troubleshooting) below for why. The setup used in production for this project instead has an external service call the workflow directly:

1. Generate a **fine-grained GitHub personal access token**: [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new) → repository access limited to this repo only → **Actions: Read and write** permission. Copy it.
2. Create a free account at [cron-job.org](https://cron-job.org) and add a new cron job:
   - **URL**: `https://api.github.com/repos/<you>/<repo>/actions/workflows/daily-sync.yml/dispatches`
   - **Method**: `POST`
   - **Headers**: `Authorization: Bearer <your token>`, `Accept: application/vnd.github+json`, `Content-Type: application/json`
   - **Body**: `{"ref":"main"}`
   - **Schedule**: daily, a few minutes past your target hour in UTC (e.g. `00:05`) — avoid scheduling exactly on the hour
3. Use cron-job.org's "Run now" to test, then confirm with:
   ```bash
   gh api repos/<you>/<repo>/actions/runs --jq '.workflow_runs[0] | {event, created_at, conclusion}'
   ```
   Look for `"event": "workflow_dispatch"` with a matching timestamp.

The built-in `schedule:` trigger can stay in the workflow file as a harmless secondary trigger — it costs nothing to leave in, it just shouldn't be your only one.

---

## Maintenance

- **Course list changes each semester** — update `COURSES` in `scripts/sync.py` (add any new course as a Select option in both databases first).
- **Course colors** — set on the "Course" select property in Notion directly. An unrecognized course code gets auto-created with a default gray option the first time it appears; recolor it whenever that happens.
- **Canvas token expiry** — if the workflow starts failing with an auth error, generate a fresh token and update `CANVAS_TOKEN`.
- **Status labels** — `DEFAULT_STATUS` in `scripts/sync.py` must exactly match whatever Notion named your "to-do" status option; it can't be renamed via the API.
- **Adding/recreating views** — Notion's plain API can't create or delete views; that's UI-only. Re-add the Board/Unread views manually if you ever rebuild a database from scratch.
- **Canvas ID columns** — present but hidden in every view. They're how the script matches a Notion row to a Canvas item across runs. Don't delete them, or the sync will start duplicating rows.
- **Long announcements** — split across multiple paragraph blocks at creation time (Notion caps a single rich-text run at 2000 characters). Nothing to maintain.

## Known limitations / troubleshooting

- **GitHub's `schedule:` trigger is not reliable on its own.** Directly observed on this project: a brand-new scheduled workflow went **three consecutive days with zero scheduled runs firing**, despite a fully valid config (verified: correct branch, active workflow state, clean YAML, not a fork, Actions enabled). When it finally did fire on day three, it was still **over three hours late** relative to its configured time. This is a platform-level behavior with GitHub's scheduler, not something fixable through workflow configuration — which is why step 9 sets up cron-job.org as the real trigger. `workflow_dispatch` (which both cron-job.org and manual runs use) has fired correctly on every single attempt.
- **Notion select/status options can't be renamed via the API** — see the Status labels note above.
- **Notion views can't be created or deleted via the plain public API** — only the schema and rows can be managed programmatically; views are a one-time manual setup (step 2).
