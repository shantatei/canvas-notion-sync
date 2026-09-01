#!/usr/bin/env python3
"""Daily Canvas -> Notion deadline + announcement sync.

Deadlines: pulls outstanding (not submitted/graded, not yet due) assignments
from a fixed list of Canvas courses and upserts them into a "Deadlines"
Notion database, tracked with a Status property this script never
overwrites once you've set it.

Announcements: pulls every announcement from the same courses into an
"Announcements" Notion database, with a "Read" checkbox this script never
overwrites once you've ticked it.

The "Last synced" heading at the top of the page always reflects the
outcome of the most recent run: green on success, red if anything failed.

Required environment variables:
    CANVAS_URL                          e.g. https://canvas.nus.edu.sg
    CANVAS_TOKEN                        Canvas API access token
    NOTION_TOKEN                        Notion internal integration token
    NOTION_PAGE_ID                      The "NUS Deadlines" page ID (holds the "Last synced" heading)
    NOTION_DATA_SOURCE_ID               The "Deadlines" database's data source ID
    NOTION_ANNOUNCEMENTS_DATA_SOURCE_ID The "Announcements" database's data source ID
"""
import os
import re
import sys
import html
import time
import datetime
import traceback
import requests

CANVAS_URL = os.environ["CANVAS_URL"].rstrip("/")
CANVAS_TOKEN = os.environ["CANVAS_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_PAGE_ID = os.environ["NOTION_PAGE_ID"]
NOTION_DATA_SOURCE_ID = os.environ["NOTION_DATA_SOURCE_ID"]
NOTION_ANNOUNCEMENTS_DATA_SOURCE_ID = os.environ["NOTION_ANNOUNCEMENTS_DATA_SOURCE_ID"]

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
    # 91713: "OTH391" removed - a placement/diagnostic-test course (QET1/DET1/EPT)
    # that concluded and access was revoked; every request to it now 403s.
    40630: "THE1001",
    40629: "THE1002",
}

# Default Status option name for newly-created deadline rows. Notion
# auto-named the "to do" group option "Not started" when the Status
# property was created; renaming it via the API isn't supported, so this
# must match that exactly.
DEFAULT_STATUS = "Not started"

SGT = datetime.timezone(datetime.timedelta(hours=8))


# ---------------------------------------------------------------- Canvas ---

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


def strip_html(s):
    if not s:
        return ""
    s = re.sub(r'(?i)</p>|<br\s*/?>', '\n', s)
    s = re.sub(r'(?i)<li[^>]*>', '• ', s)
    s = re.sub(r'(?i)</li>', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n\s*\n+', '\n\n', s)
    return s.strip()


def fetch_announcements():
    announcements = []
    for course_id, code in COURSES.items():
        topics = canvas_get(
            f"/api/v1/courses/{course_id}/discussion_topics",
            params={"only_announcements": "true", "per_page": 100},
        )
        for t in topics:
            date = t.get("posted_at") or t.get("delayed_post_at") or t.get("created_at")
            if not date or str(date).startswith("0001-01-01"):
                continue
            announcements.append({
                "canvas_id": t["id"],
                "course": code,
                "title": t.get("title") or "Untitled",
                "date": date,
                "text": strip_html(t.get("message", "")),
            })
    return announcements


def urgency_label(due_iso, now):
    due = datetime.datetime.fromisoformat(due_iso.replace("Z", "+00:00"))
    diff_days = (due - now).total_seconds() / 86400
    if diff_days <= 1:
        return "Due Soon"
    elif diff_days <= 3:
        return "This Week"
    return "Upcoming"


# ---------------------------------------------------------------- Notion ---

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


def fetch_existing_rows(data_source_id):
    """Returns {canvas_id: notion_page_id} for all non-archived rows."""
    rows = {}
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = notion_request("POST", f"/data_sources/{data_source_id}/query", json=body)
        for page in data["results"]:
            cid_prop = page["properties"].get("Canvas ID", {})
            cid = cid_prop.get("number")
            if cid is not None:
                rows[int(cid)] = page["id"]
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]
    return rows


# ------------------------------------------------------------- Deadlines ---

def build_deadline_properties(item, now, include_status):
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


def sync_deadlines(deadlines, now):
    existing = fetch_existing_rows(NOTION_DATA_SOURCE_ID)
    target_ids = {d["canvas_id"] for d in deadlines}

    created = updated = archived = 0

    for item in deadlines:
        cid = item["canvas_id"]
        if cid in existing:
            notion_request(
                "PATCH", f"/pages/{existing[cid]}",
                json={"properties": build_deadline_properties(item, now, include_status=False)},
            )
            updated += 1
        else:
            notion_request(
                "POST", "/pages",
                json={
                    "parent": {"type": "data_source_id", "data_source_id": NOTION_DATA_SOURCE_ID},
                    "properties": build_deadline_properties(item, now, include_status=True),
                },
            )
            created += 1

    for cid, page_id in existing.items():
        if cid not in target_ids:
            notion_request("PATCH", f"/pages/{page_id}", json={"archived": True})
            archived += 1

    return created, updated, archived


# --------------------------------------------------------- Announcements ---

def chunk_text(text, limit=1900):
    """Split into pieces that each fit within Notion's 2000-char rich text
    limit, breaking on paragraph boundaries where possible."""
    if not text:
        return []
    paras = text.split("\n\n")
    blocks = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 2 <= limit:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                blocks.append(buf)
            while len(p) > limit:
                blocks.append(p[:limit])
                p = p[limit:]
            buf = p
    if buf:
        blocks.append(buf)
    return blocks


def title_rich_text(text, struck):
    """A title rich-text run with strikethrough on/off. Notion renders a
    struck-through title inline in every view (table, board, etc.) with no
    per-view configuration needed."""
    return [{
        "type": "text",
        "text": {"content": text},
        "annotations": {
            "bold": False, "italic": False, "underline": False, "code": False,
            "strikethrough": struck, "color": "default",
        },
    }]


def build_announcement_properties(item, struck):
    return {
        "Name": {"title": title_rich_text(item["title"], struck)},
        "Course": {"select": {"name": item["course"]}},
        "Posted": {"date": {"start": item["date"]}},
        "Canvas ID": {"number": item["canvas_id"]},
    }


def fetch_existing_announcement_rows():
    """Returns {canvas_id: {"page_id": ..., "read": bool}}."""
    rows = {}
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = notion_request("POST", f"/data_sources/{NOTION_ANNOUNCEMENTS_DATA_SOURCE_ID}/query", json=body)
        for page in data["results"]:
            props = page["properties"]
            cid_prop = props.get("Canvas ID", {})
            cid = cid_prop.get("number")
            if cid is not None:
                rows[int(cid)] = {
                    "page_id": page["id"],
                    "read": bool(props.get("Read", {}).get("checkbox")),
                }
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]
    return rows


def sync_announcements(announcements):
    existing = fetch_existing_announcement_rows()

    created = updated = 0

    for item in announcements:
        cid = item["canvas_id"]
        if cid in existing:
            row = existing[cid]
            notion_request(
                "PATCH", f"/pages/{row['page_id']}",
                json={"properties": build_announcement_properties(item, struck=row["read"])},
            )
            updated += 1
        else:
            children = [
                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}}
                for chunk in chunk_text(item["text"])
            ]
            notion_request(
                "POST", "/pages",
                json={
                    "parent": {"type": "data_source_id", "data_source_id": NOTION_ANNOUNCEMENTS_DATA_SOURCE_ID},
                    "properties": {**build_announcement_properties(item, struck=False), "Read": {"checkbox": False}},
                    "children": children,
                },
            )
            created += 1

    return created, updated


# ----------------------------------------------------------- Status head ---

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
    target_type = None
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
        # Block exists but isn't a heading_3 - block type can't be changed
        # via PATCH, so replace it: delete then insert fresh at the top.
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
        d_created, d_updated, d_archived = sync_deadlines(deadlines, now)

        announcements = fetch_announcements()
        print(f"{len(announcements)} announcements found", file=sys.stderr)
        a_created, a_updated = sync_announcements(announcements)

        soon = [d for d in deadlines if urgency_label(d["date"], now) != "Upcoming"]
        print(
            f"Deadlines: {d_created} new, {d_updated} updated, {d_archived} archived (done/overdue). "
            f"{len(deadlines)} outstanding total, {len(soon)} due within 3 days.\n"
            f"Announcements: {a_created} new, {a_updated} updated. {len(announcements)} total."
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
