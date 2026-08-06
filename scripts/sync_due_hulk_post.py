#!/usr/bin/env python3
"""Safely sync one confirmed Hulk post to the public website."""

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
LIBRARY = Path("/Users/richrusso/Documents/Instagram/main-30-day-bank-aug05-sep03/main-30-day-manifest.json")
LINKS = REPO / "hulk-direct-video-links.json"
DATA = REPO / "video-links-data.js"
HTML = REPO / "video-links.html"
LOG = Path("/Users/richrusso/Documents/Instagram/hulk-website-sync-log.txt")
ZONE = ZoneInfo("America/Denver")


def log(message):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(ZONE).isoformat()} {message}\n")


def run_git(*args, capture_output=False):
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, text=True, capture_output=capture_output
    )


def ensure_clean_and_current_repo():
    status = run_git("status", "--porcelain", capture_output=True).stdout.strip()
    if status:
        raise RuntimeError("repository working tree is dirty; leaving manual work untouched")
    run_git("fetch", "origin", "main")
    local = run_git("rev-parse", "HEAD", capture_output=True).stdout.strip()
    remote = run_git("rev-parse", "origin/main", capture_output=True).stdout.strip()
    if local != remote:
        run_git("pull", "--ff-only", "origin", "main")
    status = run_git("status", "--porcelain", capture_output=True).stdout.strip()
    if status:
        raise RuntimeError("repository changed during preflight; leaving it untouched")


def load_site_data():
    text = DATA.read_text(encoding="utf-8")
    return json.loads(text[text.index("[") : text.rindex("]") + 1])


def save_site_data(rows):
    rows.sort(key=lambda row: row["publishAt"])
    DATA.write_text(
        "window.TDWH_VIDEO_POSTS = " + json.dumps(rows, indent=2, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )


def same_public_entry(existing, candidate):
    keys = ("id", "publishAt", "title", "caption", "image", "videos")
    return bool(existing) and all(existing.get(key) == candidate.get(key) for key in keys)


def stage_changed_paths(image_name):
    paths = ["video-links-data.js", "video-links.html", image_name]
    for optional in ("hulk-direct-video-links.json", "scripts/sync_due_hulk_post.py"):
        if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", optional], cwd=REPO).returncode:
            paths.append(optional)
    run_git("add", "--", *paths)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--post-id", required=True, help="a ledger-confirmed published Hulk post id")
    parser.add_argument("--deploy", action="store_true")
    args = parser.parse_args()

    try:
        if args.deploy:
            ensure_clean_and_current_repo()
        manifest = json.loads(LIBRARY.read_text(encoding="utf-8"))
        links = json.loads(LINKS.read_text(encoding="utf-8"))
        matching = [post for post in manifest["feedPosts"] if post["id"] == args.post_id]
        if len(matching) != 1:
            raise ValueError(f"unknown or ambiguous Hulk post id: {args.post_id}")
        post = matching[0]
        direct = links.get(post["id"])
        direct_videos = direct.get("videos", []) if direct else []
        if direct and not direct_videos and direct.get("url"):
            direct_videos = [direct]
        valid_videos = [
            video
            for video in direct_videos
            if video.get("verified")
            and video.get("videoTitle")
            and re.fullmatch(r"https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}", video.get("url", ""))
        ]
        if not direct or not direct.get("verified") or not valid_videos:
            reason = (direct or {}).get("reason") or "missing verified matching direct YouTube watch URL"
            raise ValueError(f"Skipped {post['id']}: {reason}")

        source_image = Path(post["imageFile"])
        if not source_image.is_file():
            raise ValueError(f"missing approved image: {source_image}")
        image_name = source_image.name
        item = {key: value for key, value in post.items() if key not in {"imageFile", "imageSelectionRule"}}
        item["image"] = image_name
        item["videos"] = [
            {"title": video["videoTitle"], "url": video["url"], "provider": "YouTube"}
            for video in valid_videos[:2]
        ]
        item.pop("videoStatus", None)

        rows = load_site_data()
        existing = next((row for row in rows if row.get("id") == item["id"]), None)
        if same_public_entry(existing, item) and (REPO / image_name).is_file():
            log(f"NOOP {item['id']} already_current")
            print(json.dumps({"id": item["id"], "status": "already_current", "deployed": False}))
            return

        shutil.copy2(source_image, REPO / image_name)
        rows = [row for row in rows if row.get("id") != item["id"]]
        rows.append(item)
        save_site_data(rows)
        stamp = datetime.now(ZONE).strftime("%Y%m%d%H%M%S")
        html = HTML.read_text(encoding="utf-8")
        html = re.sub(r'video-links-data\.js\?v=[^"\']+', f"video-links-data.js?v={stamp}", html)
        HTML.write_text(html, encoding="utf-8")
        urls = ",".join(video["url"] for video in valid_videos[:2])
        log(f"PREPARED {item['id']} image={image_name} youtube={urls}")

        if args.deploy:
            stage_changed_paths(image_name)
            if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO).returncode != 0:
                run_git("commit", "-m", f"Publish Hulk website entry {item['id']}")
                run_git("push", "origin", "main")
                log(f"DEPLOYED {item['id']} youtube={urls}")
        print(
            json.dumps(
                {
                    "id": item["id"],
                    "image": image_name,
                    "youtube": [video["url"] for video in valid_videos[:2]],
                    "status": "prepared",
                    "deployed": args.deploy,
                }
            )
        )
    except (OSError, ValueError, subprocess.CalledProcessError, RuntimeError) as exc:
        log(f"SKIPPED {args.post_id} reason={exc}")
        raise SystemExit(str(exc))


if __name__ == "__main__":
    main()
