#!/usr/bin/env python3
"""Daily Canvas -> Notion deadline sync.

Pulls outstanding (not submitted/graded, not yet due) assignments from a
fixed list of Canvas courses and upserts them into a Notion database as
rows, so the user can sort/filter/group them natively in Notion and track
progress with a Status property that this script never overwrites.

The "Last synced" heading at the top of the page always reflects the
outcome of the most recent run: green on success, red if anything failed.

Required environment variables:
    CANVAS_URL            e.g. https://canvas.nus.edu.sg
    CANVAS_TOKEN          Canvas API access token
    NOTION_TOKEN          Notion internal integration token
    NOTION_PAGE_ID        The "NUS Deadlines" page ID (holds the "Last synced" heading)
    NOTION_DATA_SOURCE_ID The "Deadlines" database's data source ID
"""
import os
import sys
import time
import datetime
import traceback
import requests

CANVAS_URL = os.environ["CANVAS_URL"].rstrip("/")
CANVAS_TOKEN = os.environ["CANVAS_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_PAGE_ID = os.environ["NOTION_PAGE_ID"]
NOTION_DATA_SOURCE_ID = os.environ["NOTION_DATA_SOURCE_ID"]

NOTION_VERSION = "2025-09-03"  # multi-source database API

# Course id -> course code. Update this each semester as enrollment changes.
COURSES = {
    98530: "THE1008",
    93575: "CFG1002",
    93698: "CS2030S",
    93730: "CS2100",
    94257: "GEA1000",
    99079: "HLH001",
    97325: "IS1128",
    97359: "MA1301",
    91713: "OTH391",
    40630: "THE1001",
    40629: "THE1002",
}

# Default Status option name for newly-created rows. Notion auto-named the
# "to do" group option "Not started" when the Status property was created;
# renaming it via the API isn't supported, so this must match that exactly.
DEFAULT_STATUS = "Not started"

SGT = datetime.timezone(datetime.timedelta(hours=8))


def canvas_get(path, params=None):
    url = f"{CANVAS_URL}{path}"
    headers = {"Authorization": f"Bearer {CANVAS_TOKEN}"}
    out = []
    while url:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        out.extend(resp.json())
        params = None
        url = None
        link = resp.headers.get("Link", "")
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
    return out


def is_completed(assignment):
    sub = assignment.get("submission")
    if not isinstance(sub, dict):
        return False
    if sub.get("workflow_state") not in ("submitted", "graded"):
        return False
    submitted_at = sub.get("submitted_at")
    return bool(submitted_at) and not str(submitted_at).startswith("0001-01-01")


def fetch_deadlines(now):
    deadlines = []
    for course_id, code in COURSES.items():
        assignments = canvas_get(
            f"/api/v1/courses/{course_id}/assignments",
            params={"include[]": "submission", "per_page": 100},
        )
        for a in assignments:
            if is_completed(a):
                continue
            due = a.get("due_at")
            if not due or str(due).startswith("0001-01-01"):
                continue
            due_dt = datetime.datetime.fromisoformat(due.replace("Z", "+00:00"))
            if due_dt < now:
                continue
            deadlines.append({
                "canvas_id": a["id"],
                "course": code,
                "title": a.get("name") or "Untitled",
                "date": due,
            })
    return deadlines


def urgency_label(due_iso, now):
    due = datetime.datetime.fromisoformat(due_iso.replace("Z", "+00:00"))
    diff_days = (due - now).total_seconds() / 86400
    if diff_days <= 1:
        return "Due Soon"
    elif diff_days <= 3:
        return "This Week"
    return "Upcoming"


def notion_request(method, path, **kwargs):
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    resp = requests.request(method, f"https://api.notion.com/v1{path}", headers=headers, timeout=30, **kwargs)
    if resp.status_code == 429:
        time.sleep(int(resp.headers.get("Retry-After", "1")) + 1)
        resp = requests.request(method, f"https://api.notion.com/v1{path}", headers=headers, timeout=30, **kwargs)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def fetch_existing_rows():
    """Returns {canvas_id: notion_page_id} for all non-archived rows."""
    rows = {}
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = notion_request("POST", f"/data_sources/{NOTION_DATA_SOURCE_ID}/query", json=body)
        for page in data["results"]:
            cid_prop = page["properties"].get("Canvas ID", {})
            cid = cid_prop.get("number")
            if cid is not None:
                rows[int(cid)] = page["id"]
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]
    return rows


def build_properties(item, now, include_status):
    props = {
        "Name": {"title": [{"text": {"content": item["title"]}}]},
        "Course": {"select": {"name": item["course"]}},
        "Due Date": {"date": {"start": item["date"]}},
        "Urgency": {"select": {"name": urgency_label(item["date"], now)}},
        "Canvas ID": {"number": item["canvas_id"]},
    }
    if include_status:
        props["Status"] = {"status": {"name": DEFAULT_STATUS}}
    return props


def sync_rows(deadlines, now):
    existing = fetch_existing_rows()
    target_ids = {d["canvas_id"] for d in deadlines}

    created = updated = archived = 0

    for item in deadlines:
        cid = item["canvas_id"]
        if cid in existing:
            notion_request(
                "PATCH", f"/pages/{existing[cid]}",
                json={"properties": build_properties(item, now, include_status=False)},
            )
            updated += 1
        else:
            notion_request(
                "POST", "/pages",
                json={
                    "parent": {"type": "data_source_id", "data_source_id": NOTION_DATA_SOURCE_ID},
                    "properties": build_properties(item, now, include_status=True),
                },
            )
            created += 1

    for cid, page_id in existing.items():
        if cid not in target_ids:
            notion_request("PATCH", f"/pages/{page_id}", json={"archived": True})
            archived += 1

    return created, updated, archived


def set_status_heading(now, success, detail):
    """Find the heading_3 "Last synced" block at the top of the page and
    update it in place (color + text) rather than recreating it, so its
    position on the page never moves."""
    sgt_str = now.astimezone(SGT).strftime("%a, %-d %b %Y, %-I:%M %p")
    if success:
        text = f"✅ Last synced: {sgt_str} SGT"
        color = "green_background"
    else:
        text = f"❌ Sync failed: {sgt_str} SGT — {detail}"
        color = "red_background"

    data = notion_request("GET", f"/blocks/{NOTION_PAGE_ID}/children", params={"page_size": 50})
    target_block_id = None
    for block in data["results"]:
        btype = block["type"]
        if btype not in ("heading_1", "heading_2", "heading_3", "paragraph"):
            continue
        texts = block[btype].get("rich_text", [])
        joined = "".join(t.get("plain_text", "") for t in texts)
        if "sync" in joined.lower():
            target_block_id = block["id"]
            target_type = btype
            break

    body = {"heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}], "color": color}}
    if target_block_id and target_type == "heading_3":
        notion_request("PATCH", f"/blocks/{target_block_id}", json=body)
    elif target_block_id:
        # Block exists but isn't a heading_3 (e.g. leftover paragraph from an
        # older version of this script) - block type can't be changed via
        # PATCH, so replace it: delete then insert fresh at the top.
        notion_request("DELETE", f"/blocks/{target_block_id}")
        notion_request(
            "PATCH", f"/blocks/{NOTION_PAGE_ID}/children",
            json={"children": [{"object": "block", "type": "heading_3", **body}]},
        )
    else:
        notion_request(
            "PATCH", f"/blocks/{NOTION_PAGE_ID}/children",
            json={"children": [{"object": "block", "type": "heading_3", **body}]},
        )


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        deadlines = fetch_deadlines(now)
        print(f"{len(deadlines)} outstanding deadlines found", file=sys.stderr)

        created, updated, archived = sync_rows(deadlines, now)

        soon = [d for d in deadlines if urgency_label(d["date"], now) != "Upcoming"]
        print(
            f"Synced: {created} new, {updated} updated, {archived} archived (done/overdue). "
            f"{len(deadlines)} outstanding total, {len(soon)} due within 3 days."
        )
    except Exception as e:
        traceback.print_exc()
        try:
            set_status_heading(now, success=False, detail=str(e)[:200])
        except Exception:
            print("Additionally failed to update the status heading itself.", file=sys.stderr)
            traceback.print_exc()
        sys.exit(1)

    set_status_heading(now, success=True, detail="")


if __name__ == "__main__":
    main()
