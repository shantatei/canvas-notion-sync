# canvas-notion-sync

A daily GitHub Action that syncs outstanding **Canvas** deadlines and
**announcements** into two **Notion** databases on one dashboard page. Runs
entirely on GitHub's servers on a schedule — no dependency on your laptop
being on.

**Deadlines** database:
- **Course**: colored select tag
- **Urgency**: colored select tag — red "Due Soon" (≤1 day), yellow "This
  Week" (≤3 days), green "Upcoming" (>3 days)
- **Status**: a to-do/in-progress/done property you control by hand — the
  sync never overwrites it once you've set it. It only adds new deadlines
  and archives rows once the assignment is actually completed on Canvas or
  its due date has passed.
- Ships with a **Table view** (sorted by due date, click any column to
  sort/filter further) and a **Board view** grouped by Status for a
  Kanban-style todo workflow.

**Announcements** database:
- **Course**: colored select tag, same colors as Deadlines
- **Read**: a checkbox you control by hand — the sync never touches it once
  ticked. Once ticked, the title gets a strikethrough on the *next* sync run
  (there's no way to make this instant without the script running).
- Opening a row shows the announcement's full text (synced in as the page
  body when first created). Nothing is ever removed, only added to.
- Ships with an **All Announcements** view (newest first) and an
  **Unread** view (filtered to unticked rows only).

A bold "Last synced" heading at the top of the page updates every run —
green background on success, red on failure with a short error message, so
you can tell at a glance whether today's sync actually worked.

---

## Fork this and use it for your own Canvas courses

This whole setup is generic — nothing here is specific to any one school
beyond the Canvas instance URL. Expect **~20 minutes** the first time,
almost all of it manual Notion clicking (the API can't build database
schemas or views for you). Once it's running, there's nothing more to do
until course enrollment changes each semester.

### 1. Fork and clone

Click **Fork** on GitHub, then:

```bash
git clone https://github.com/<your-username>/canvas-notion-sync.git
cd canvas-notion-sync
gh auth login          # if you haven't already, browser login to your own GitHub account
```

### 2. Build the Notion side

You're building this by hand once — the public Notion API can create
database *rows* but not database *schemas with select options* or *views*
in a way worth scripting for a one-time setup.

1. Create a new blank Notion page. Call it whatever you like (e.g. "My
   Canvas Dashboard").
2. Inside it, add a database (**Table** view) named **Deadlines** with
   these properties:

   | Property | Type | Notes |
   |---|---|---|
   | Name | Title | (Notion adds this by default) |
   | Course | Select | Add one option per course code you're enrolled in this semester, pick any colors you like |
   | Due Date | Date | |
   | Urgency | Select | Three options: `Due Soon` (red), `This Week` (yellow), `Upcoming` (green) — names must match exactly |
   | Status | Status | Notion auto-creates 3 groups (to-do/in-progress/complete) with default option names — note whatever the "to-do" option is actually called (often "Not started"), you'll need it in step 4 |
   | Canvas ID | Number | Leave empty — the script uses this internally to avoid creating duplicate rows. Don't delete it once the sync is running. |

3. Add a **Board view** on the same database: **+ Add view → Board →
   Group by → Status**. Name it whatever you like.
4. Below that, add a second database named **Announcements** with:

   | Property | Type | Notes |
   |---|---|---|
   | Name | Title | |
   | Course | Select | Same course options as above, matching colors if you want visual consistency |
   | Posted | Date | |
   | Read | Checkbox | |
   | Canvas ID | Number | Same purpose as above — leave empty |

5. Add an **Unread** view on it: **+ Add view → Table**, then filter
   `Read` **is not** checked, sort by `Posted` descending.

### 3. Get a Canvas API token

In Canvas: **Account → Settings → Approved Integrations → New Access
Token**. Copy it — you'll only see it once. Also note your Canvas
instance's base URL (e.g. `https://canvas.yourschool.edu`).

### 4. Create a Notion integration and connect it

1. Go to <https://www.notion.so/my-integrations> → **New integration**,
   give it access to your workspace, and copy its **Internal Integration
   Secret** (starts with `secret_` or `ntn_`).
2. Open the page you built in step 2 → **···** menu (or **Share**) →
   **Connections** → add the integration. Without this, it can't see or
   edit anything on the page.

### 5. Find your IDs

You need three IDs: the page, and each database's *data source ID* (a
newer Notion concept — every database has one, needed for the API calls
this script makes). Get them with `curl`, using the integration token from
step 4:

```bash
NOTION_TOKEN="paste-your-integration-token-here"

# Page ID: the 32-char string at the end of the page's URL, e.g.
# https://www.notion.so/My-Canvas-Dashboard-3c9a07227bd281329da3e85885f07a60
# -> 3c9a07227bd281329da3e85885f07a60 (dashes optional, no API call needed)

# Deadlines database ID: the 32-char string in ITS URL, same way.
curl -s https://api.notion.com/v1/databases/<deadlines-database-id> \
  -H "Authorization: Bearer $NOTION_TOKEN" \
  -H "Notion-Version: 2025-09-03" | grep -A2 '"data_sources"'

# Repeat for the Announcements database
curl -s https://api.notion.com/v1/databases/<announcements-database-id> \
  -H "Authorization: Bearer $NOTION_TOKEN" \
  -H "Notion-Version: 2025-09-03" | grep -A2 '"data_sources"'
```

Each call prints an `"id"` under `data_sources` — that's the data source ID
you need (a UUID, separate from the database's own ID/URL).

### 6. Configure the script for your courses

Edit `scripts/sync.py`:

- `COURSES`: replace with your own `{canvas_course_id: "COURSE_CODE"}`
  pairs. Find each course's numeric ID in its Canvas URL, e.g.
  `.../courses/93698/assignments` → `93698`. The course code string must
  exactly match a Select option you created in step 2.
- `DEFAULT_STATUS`: set this to whatever Notion actually named your
  Status property's "to-do" option (see step 2, point 2 — commonly "Not
  started").

Commit and push your changes.

### 7. Add the GitHub secrets

Do this yourself — never paste API tokens into a chat with an assistant,
even one you trust, since there's no way to un-paste it:

```bash
gh secret set CANVAS_URL --body "https://canvas.yourschool.edu"
gh secret set CANVAS_TOKEN
gh secret set NOTION_TOKEN
gh secret set NOTION_PAGE_ID --body "<page-id-from-step-5>"
gh secret set NOTION_DATA_SOURCE_ID --body "<deadlines-data-source-id>"
gh secret set NOTION_ANNOUNCEMENTS_DATA_SOURCE_ID --body "<announcements-data-source-id>"
```

(Omitting `--body` on `CANVAS_TOKEN`/`NOTION_TOKEN` prompts you to paste
interactively instead, which keeps it out of shell history.)

`NOTION_PAGE_ID` and the two data source IDs aren't credentials — they're
just object identifiers — but they're still specific to your Notion
workspace, so they go in as secrets purely for convenience of not editing
the workflow file.

### 8. Test it

```bash
gh workflow run daily-sync.yml
gh run watch
```

Check the Notion page updated. If it fails, the run logs will say why —
the most common causes are a course code in `COURSES` not matching a
Select option exactly, or the integration not being connected to both
databases.

### 9. Adjust the schedule (optional)

`.github/workflows/daily-sync.yml` runs at `0 0 * * *` (00:00 UTC), which
is 08:00 in Singapore (no DST there, so it never drifts). GitHub Actions
cron is always UTC — convert your own timezone's desired run time to UTC
and edit that line.

---

## Maintenance

- **Course list changes each semester** — update `COURSES` in
  `scripts/sync.py` (and add any new course as a Select option in both
  Notion databases first, or the sync will fail on that course).
- **Course colors**: set directly on the "Course" select property in
  Notion (either database → edit the property → each option has its own
  color picker). A brand-new course code not yet added as an option gets
  auto-created by Notion with a default gray color the first time it
  appears — recolor it whenever that happens.
- **Canvas token expiry**: if the workflow starts failing with an auth
  error, generate a new Canvas token and update the `CANVAS_TOKEN` secret.
- **Status labels**: whatever you named the Status options in step 2 is
  what `DEFAULT_STATUS` in `scripts/sync.py` must match exactly, since the
  script sets it by name and Notion doesn't support renaming a status
  option through the API.
- **Adding/recreating views**: Notion's plain API can't create or delete
  views — that's UI-only. If you ever rebuild a database from scratch,
  re-add the Board/Unread views manually as described in step 2.
- **Canvas ID columns**: present but hidden in every view — they're how
  the script matches a Notion row to a Canvas item across runs so it
  updates in place instead of duplicating. Don't delete them.
- **Very long announcements**: text is split across multiple paragraph
  blocks at creation time (Notion limits a single rich-text run to 2000
  characters) — nothing to maintain, just why a long announcement's body
  is several blocks instead of one.
