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
LIBRARY = Path("/Users/richrusso/Desktop/Hulk-30-Day-Content-Library-Aug02-Aug31/manifest.json")
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
    if not direct or not direct.get("verified") or not re.fullmatch(r"https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}", direct.get("url", "")):
        log(f"BLOCKED {post['id']} missing verified direct YouTube URL")
        raise SystemExit(f"Missing verified direct YouTube URL for {post['id']}")
    rows = load_site_data()
    item = {key: value for key, value in post.items() if key not in {"imageFile", "imageSelectionRule"}}
    source_image = Path(post["imageFile"])
    image_name = source_image.name
    shutil.copy2(source_image, REPO / image_name)
    item["image"] = image_name
    item["videos"] = [{"title": direct["videoTitle"], "url": direct["url"], "provider": "YouTube"}]
    rows = [row for row in rows if row.get("id") != item["id"]]
    rows.append(item)
    save_site_data(rows)
    stamp = now.strftime("%Y%m%d%H%M%S")
    html = HTML.read_text(encoding="utf-8")
    html = re.sub(r'video-links-data\.js\?v=[^"\']+', f"video-links-data.js?v={stamp}", html)
    HTML.write_text(html, encoding="utf-8")
    log(f"PREPARED {item['id']} image={image_name} youtube={direct['url']}")
    if args.deploy:
        subprocess.run(["git", "add", "video-links-data.js", "video-links.html", image_name, "hulk-direct-video-links.json", "scripts/sync_due_hulk_post.py"], cwd=REPO, check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO).returncode != 0:
            subprocess.run(["git", "commit", "-m", f"Publish Hulk website entry {item['id']}"], cwd=REPO, check=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=REPO, check=True)
        log(f"DEPLOYED {item['id']} youtube={direct['url']}")
    print(json.dumps({"id": item["id"], "image": image_name, "youtube": direct["url"], "deployed": args.deploy}))


if __name__ == "__main__":
    main()
