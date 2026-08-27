#!/usr/bin/env python3
"""Daily Canvas -> Notion deadline sync.

Pulls outstanding (not submitted/graded, not yet due) assignments from a
fixed list of Canvas courses and replaces the content of one Notion page
with a color-coded table of them.

Required environment variables:
    CANVAS_URL      e.g. https://canvas.nus.edu.sg
    CANVAS_TOKEN    Canvas API access token (Account > Settings > New Access Token)
    NOTION_TOKEN    Notion internal integration token (notion.so/my-integrations)
    NOTION_PAGE_ID  The "NUS Deadlines" page ID (shared with the integration)
"""
import os
import re
import sys
import html
import time
import datetime
import requests

CANVAS_URL = os.environ["CANVAS_URL"].rstrip("/")
CANVAS_TOKEN = os.environ["CANVAS_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_PAGE_ID = os.environ["NOTION_PAGE_ID"]

NOTION_VERSION = "2022-06-28"

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

# Course code -> notion background color for the Course cell. Extend as needed;
# pick from the unused set (gray_background, orange_background, yellow_background)
# for any new course code.
COURSE_COLOR = {
    "CS2030S": "blue_background",
    "CS2100": "purple_background",
    "MA1301": "brown_background",
    "GEA1000": "pink_background",
}
FALLBACK_COURSE_COLORS = ["gray_background", "orange_background", "yellow_background"]


def canvas_get(path, params=None):
    """GET a Canvas API endpoint, following pagination via the Link header."""
    url = f"{CANVAS_URL}{path}"
    headers = {"Authorization": f"Bearer {CANVAS_TOKEN}"}
    out = []
    while url:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        out.extend(resp.json())
        params = None  # only needed on first request; next url already has query
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
    # Canvas can mark a submission "graded" (e.g. an instructor-entered 0)
    # without the student ever actually submitting - submitted_at stays at
    # the zero-value placeholder in that case. That must NOT count as done.
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
                "course": code,
                "title": a.get("name") or "Untitled",
                "date": due,
                "points": a.get("points_possible"),
            })
    deadlines.sort(key=lambda x: x["date"])
    return deadlines


def urgency_color(due_iso, now):
    due = datetime.datetime.fromisoformat(due_iso.replace("Z", "+00:00"))
    diff_days = (due - now).total_seconds() / 86400
    if diff_days <= 1:
        return "red_background"
    elif diff_days <= 3:
        return "yellow_background"
    return "green_background"


def course_color(code):
    if code not in COURSE_COLOR:
        # deterministically assign a fallback color so it stays stable run to run
        idx = sum(ord(c) for c in code) % len(FALLBACK_COURSE_COLORS)
        return FALLBACK_COURSE_COLORS[idx]
    return COURSE_COLOR[code]


SGT = datetime.timezone(datetime.timedelta(hours=8))


def rich_text(content, color=None, bold=False):
    ann = {}
    if color:
        ann["color"] = color
    if bold:
        ann["bold"] = True
    obj = {"type": "text", "text": {"content": content}}
    if ann:
        obj["annotations"] = ann
    return obj


def build_table_row(cells_with_colors):
    return {
        "object": "block",
        "type": "table_row",
        "table_row": {
            "cells": [[rich_text(text, color=color)] for text, color in cells_with_colors]
        },
    }


def build_blocks(deadlines, now):
    today_str = now.strftime("%-d %b %Y")
    intro = {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [rich_text(
                "Outstanding deadlines across all your Canvas courses, synced automatically. "
                f"Already-submitted, graded, and past-due items are left out. Generated {today_str}."
            )]
        },
    }
    legend = {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "\U0001F3A8"},
            "rich_text": [rich_text(
                "Course column colors are fixed per course. "
                "Row highlight = urgency: red = due within 1 day, "
                "yellow = within 3 days, green = more than 3 days out."
            )],
        },
    }

    header_row = build_table_row([
        ("Course", None), ("Title", None), ("Due Date", None),
        ("Time", None), ("Points", None),
    ])
    rows = [header_row]
    for d in deadlines:
        due_dt = datetime.datetime.fromisoformat(d["date"].replace("Z", "+00:00")).astimezone(SGT)
        day_str = due_dt.strftime("%a, %-d %b")
        time_str = due_dt.strftime("%-I:%M %p")
        pts = d["points"]
        pts_str = "" if pts is None else (f"{pts} pt" if pts == 1 else f"{pts} pts")
        u = urgency_color(d["date"], now)
        c = course_color(d["course"])
        rows.append(build_table_row([
            (d["course"], c),
            (d["title"], u),
            (day_str, u),
            (time_str, u),
            (pts_str, u),
        ]))

    table = {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": 5,
            "has_column_header": True,
            "has_row_header": False,
            "children": rows,
        },
    }
    return [intro, legend, table]


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
    return resp.json()


def clear_page(page_id):
    cursor = None
    block_ids = []
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        data = notion_request("GET", f"/blocks/{page_id}/children", params=params)
        block_ids.extend(b["id"] for b in data["results"])
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]
    for bid in block_ids:
        notion_request("DELETE", f"/blocks/{bid}")


def append_blocks(page_id, blocks):
    notion_request("PATCH", f"/blocks/{page_id}/children", json={"children": blocks})


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    deadlines = fetch_deadlines(now)
    print(f"{len(deadlines)} outstanding deadlines found", file=sys.stderr)

    blocks = build_blocks(deadlines, now)
    clear_page(NOTION_PAGE_ID)
    append_blocks(NOTION_PAGE_ID, blocks)

    soon = [d for d in deadlines if urgency_color(d["date"], now) != "green_background"]
    print(f"Synced {len(deadlines)} deadlines to Notion. {len(soon)} due within 3 days.")


if __name__ == "__main__":
    main()
