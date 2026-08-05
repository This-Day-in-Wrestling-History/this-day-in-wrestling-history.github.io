#!/usr/bin/env python3
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


def load_site_data():
    text = DATA.read_text(encoding="utf-8")
    return json.loads(text[text.index("["):text.rindex("]") + 1])


def save_site_data(rows):
    rows.sort(key=lambda row: row["publishAt"])
    DATA.write_text("window.TDWH_VIDEO_POSTS = " + json.dumps(rows, indent=2, ensure_ascii=False) + ";\n", encoding="utf-8")


def log(message):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(ZONE).isoformat()} {message}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--post-id")
    parser.add_argument("--deploy", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(LIBRARY.read_text(encoding="utf-8"))
    links = json.loads(LINKS.read_text(encoding="utf-8"))
    now = datetime.now(ZONE)
    eligible = [post for post in manifest["feedPosts"] if datetime.fromisoformat(post["publishAt"]) <= now]
    if args.post_id:
        eligible = [post for post in manifest["feedPosts"] if post["id"] == args.post_id]
    if not eligible:
        raise SystemExit("No due Hulk feed post found")
    post = max(eligible, key=lambda row: row["publishAt"])
    direct = links.get(post["id"])
    direct_videos = direct.get("videos", []) if direct else []
    if direct and not direct_videos and direct.get("url"):
        direct_videos = [direct]
    valid_videos = [
        video for video in direct_videos
        if video.get("verified")
        and video.get("videoTitle")
        and re.fullmatch(r"https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}", video.get("url", ""))
    ]
    unavailable = post.get("videoStatus") == "unavailable_after_verification"
    if (not direct or not direct.get("verified") or not valid_videos) and not unavailable:
        log(f"BLOCKED {post['id']} missing verified direct YouTube URL or audited unavailable status")
        raise SystemExit(f"Missing verified direct YouTube URL or audited unavailable status for {post['id']}")
    rows = load_site_data()
    item = {key: value for key, value in post.items() if key not in {"imageFile", "imageSelectionRule"}}
    source_image = Path(post["imageFile"])
    image_name = source_image.name
    shutil.copy2(source_image, REPO / image_name)
    item["image"] = image_name
    item["videos"] = [
        {"title": video["videoTitle"], "url": video["url"], "provider": "YouTube"}
        for video in valid_videos[:2]
    ]
    if unavailable and not valid_videos:
        item["videoStatus"] = "unavailable_after_verification"
    rows = [row for row in rows if row.get("id") != item["id"]]
    rows.append(item)
    save_site_data(rows)
    stamp = now.strftime("%Y%m%d%H%M%S")
    html = HTML.read_text(encoding="utf-8")
    html = re.sub(r'video-links-data\.js\?v=[^"\']+', f"video-links-data.js?v={stamp}", html)
    HTML.write_text(html, encoding="utf-8")
    urls = ",".join(video["url"] for video in valid_videos[:2])
    video_note = urls or "unavailable_after_verification"
    log(f"PREPARED {item['id']} image={image_name} youtube={video_note}")
    if args.deploy:
        subprocess.run(["git", "add", "video-links-data.js", "video-links.html", image_name, "hulk-direct-video-links.json", "scripts/sync_due_hulk_post.py"], cwd=REPO, check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO).returncode != 0:
            subprocess.run(["git", "commit", "-m", f"Publish Hulk website entry {item['id']}"], cwd=REPO, check=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=REPO, check=True)
        log(f"DEPLOYED {item['id']} youtube={video_note}")
    print(json.dumps({"id": item["id"], "image": image_name, "youtube": [video["url"] for video in valid_videos[:2]], "videoStatus": item.get("videoStatus", "verified"), "deployed": args.deploy}))


if __name__ == "__main__":
    main()
