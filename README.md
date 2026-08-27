# canvas-notion-sync

Runs on GitHub's servers every day at **08:00 Singapore time** — no dependency on
your laptop being on. It pulls outstanding (not yet submitted/graded, not yet
due) assignments from your Canvas courses and upserts them as rows into the
**Deadlines** database on the **NUS Deadlines** Notion page:

- **Course**: colored select tag, fixed color per course code
- **Urgency**: colored select tag — red "Due Soon" (≤1 day), yellow "This Week"
  (≤3 days), green "Upcoming" (>3 days)
- **Status**: a to-do/in-progress/done property you control by hand — the
  sync never overwrites it once you've set it. It only adds new deadlines
  and archives rows once the assignment is actually completed on Canvas or
  its due date has passed.
- A bold "Last synced" heading at the top of the page updates every run —
  green background on success, red on failure (with a short error message),
  so you can tell at a glance whether today's sync actually worked.
- Two views ship with the database: **All Deadlines** (table, sorted by due
  date — click any column to sort/filter further) and **Todo Board** (board,
  grouped by Status). Clicking a course tag on any row filters the current
  view to that course — standard Notion behavior, no extra setup.

## One-time setup

### 1. Push this repo to GitHub

```bash
cd ~/Documents/canvas-notion-sync
git init
git add .
git commit -m "Initial commit"
gh auth login          # interactive browser login to your own GitHub account
gh repo create canvas-notion-sync --private --source=. --push
```

### 2. Get a Canvas API token

In Canvas: **Account -> Settings -> Approved Integrations -> New Access Token**.
Copy the token (you'll only see it once).

### 3. Create a Notion integration and share the page with it

1. Go to <https://www.notion.so/my-integrations> -> **New integration**.
   - Give it access to your workspace.
   - Copy the "Internal Integration Secret" (starts with `secret_` or `ntn_`).
2. Open the **NUS Deadlines** page in Notion -> **···** menu (top right) ->
   **Connections** -> add the integration you just created. Without this
   step, the integration cannot see or edit the page.
3. Copy the page ID: it's the 32-character string in the page URL, e.g.
   `https://app.notion.com/p/3c9a07227bd281329da3e85885f07a60` ->
   `3c9a07227bd281329da3e85885f07a60` (dashes optional, both formats work).

### 4. Add the secrets to the GitHub repo

Do this yourself (in the GitHub web UI, or `gh secret set` in your own
terminal) — these are credentials, so add them directly rather than pasting
them into a chat with an assistant:

```bash
gh secret set CANVAS_URL --body "https://canvas.nus.edu.sg"
gh secret set CANVAS_TOKEN
gh secret set NOTION_TOKEN
gh secret set NOTION_PAGE_ID --body "3c9a07227bd281329da3e85885f07a60"
gh secret set NOTION_DATA_SOURCE_ID --body "4a1110ba-2abd-4109-9bd4-c6edfe550628"
```

`NOTION_DATA_SOURCE_ID` identifies the **Deadlines** database (not the page) —
it's the collection ID shown when you fetch the database, not a credential,
so it's fine to store the same way as `NOTION_PAGE_ID`.

(Omitting `--body` will prompt you to paste the value interactively, which
keeps it out of shell history.)

### 5. Test it

```bash
gh workflow run daily-sync.yml
gh run watch
```

Then check the Notion page updated.

## Maintenance

- **Course list**: `scripts/sync.py` has a hardcoded `COURSES` dict (Canvas
  course ID -> course code). Update it each semester as your enrollment
  changes — this script has no way to know which courses are "yours" beyond
  that list.
- **Course colors**: set on the "Course" select property in Notion itself
  (Deadlines database → edit the property → each option has its own color
  picker). A brand-new course code the script hasn't seen before will get
  auto-added as a plain default-colored option the first time it appears —
  recolor it in Notion whenever that happens.
- **Canvas token expiry**: if the workflow starts failing with an auth error,
  generate a new Canvas token (step 2) and update the `CANVAS_TOKEN` secret.
- **Status labels**: the "to do" option is named "Not started" rather than
  "To Do" — Notion auto-generates that name when a Status property is
  created and it can't be renamed through the API. Rename it once yourself
  in Notion (Deadlines database → Status property → edit the option) if you
  want different wording; the script only ever reads/writes it by whatever
  name is currently set as `DEFAULT_STATUS`.
- **Adding the Board view**: already set up (Todo Board, grouped by Status) —
  nothing to do. If you ever recreate the database from scratch, note that
  Notion's plain API can't create views; you'd add one manually via
  **+ Add view → Board → Group by Status**.
- **Canvas ID column**: hidden from both views but still in the schema —
  it's how the script matches a Notion row to a Canvas assignment across
  runs so it updates in place instead of creating duplicates. Don't delete
  it or the sync will start duplicating rows.
- **Points was removed** as a property entirely (not just hidden) since it
  wasn't needed.
