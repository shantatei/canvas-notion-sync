# canvas-notion-sync

Runs on GitHub's servers every day at **08:00 Singapore time** — no dependency on
your laptop being on. It pulls outstanding (not yet submitted/graded, not yet
due) assignments from your Canvas courses and replaces the content of your
**NUS Deadlines** Notion page with a color-coded table:

- Course column: fixed color per course code
- Row highlight: red = due within 1 day, yellow = within 3 days, green = more
  than 3 days out

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
```

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
- **Course colors**: also in `scripts/sync.py`, `COURSE_COLOR`. New courses
  not in that map get an automatically assigned fallback color.
- **Canvas token expiry**: if the workflow starts failing with an auth error,
  generate a new Canvas token (step 2) and update the `CANVAS_TOKEN` secret.
