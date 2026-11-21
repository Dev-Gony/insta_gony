"""네이버 블로그 새 글 → 여러 채널에 자동 게시.

흐름: 블로그 RSS에서 아직 안 올린 새 글 1개 → 본문 가져오기 → Claude로 카드 문구·캡션
→ Remotion으로 카드 JPEG → 켜 둔 채널(CHANNELS)마다 게시 → config/history.json

채널
- instagram: 사진 카드 캐러셀. 글의 영상이 짧으면(MIN_REEL_SECONDS 미만) 표지 다음 장에 그 영상을 넣는다
- reels: 글의 영상이 충분히 길면 속삭이는 내레이션 릴스 (reels.py). 영상이 없으면 건너뜀
- threads, clip: 자리만 잡아 둠 (README의 "다음 할 일")

설정 (GitHub Variables / Secrets): README.md 참고
"""

import argparse
import os
from datetime import datetime

import shutil
import urllib.request

import cards
import food_cards
import instagram
import naver_blog
import reels
from common import KST, load_json, notify_slack, save_json


HISTORY_FILE = "config/history.json"
OUTPUT_DIR = "runtime/posts"

# 본문이 이보다 짧으면(사진만 있는 글 등) 카드로 만들 재료가 부족하다.
MIN_TEXT_LENGTH = 300

# 사진 카드는 사진이 최소 1장은 있어야 만든다 (적으면 장 수를 줄여서 만든다).
MIN_PHOTOS = 1

# 방문 후기만 올린다: 이 카테고리(번호)와 그 아래 글만. 기본은 "맛집 · 그만 먹어.."(11).
# 블로그 카테고리 번호는 m.blog.naver.com/api/blogs/<ID>/category-list 에서 확인 (Variable POST_CATEGORIES, 쉼표로).
DEFAULT_POST_CATEGORIES = "11"


def post_categories():
    value = (os.environ.get("POST_CATEGORIES") or DEFAULT_POST_CATEGORIES).strip()
    return {name.strip() for name in value.split(",") if name.strip()}


def posted_today(history, now=None):
    """오늘(KST) 실제로 올린 글 수 (건너뛴 것 제외, 글 단위)."""
    today = (now or datetime.now(KST)).date()
    links = {
        entry["link"]
        for entry in history
        if not entry.get("skipped")
        and entry.get("at")
        and datetime.fromisoformat(entry["at"]).astimezone(KST).date() == today
    }
    return len(links)


def enabled_channels():
    value = os.environ.get("CHANNELS") or "instagram,reels"
    return [name.strip() for name in value.split(",") if name.strip()]


def done_links(history, channels):
    """켜 둔 채널 모두에서 끝난(올렸거나 건너뛴) 글."""
    finished = {}

    for entry in history:
        finished.setdefault(entry["link"], set()).add(entry.get("channel") or "instagram")

    return {link for link, names in finished.items() if set(channels) <= names or "all" in names}


def channel_done(history, link, channel):
    return any(entry["link"] == link and entry.get("channel") in (channel, "all") for entry in history)


# ---------------------------------------------------------------------------
# 채널별 게시
# ---------------------------------------------------------------------------

def publish_instagram(post, work):
    folder = f"{datetime.now(KST):%Y-%m-%d}_{work['log_no']}"
    urls = instagram.host_images(work["images"], folder)

    if work.get("carousel_video"):
        # 짧은 영상은 표지 다음 장에 (캐러셀은 10장까지 → 넘치면 마지막 장 앞의 사진을 하나 뺀다)
        items = [("image", urls[0]), ("video", work["carousel_video"])] + [("image", url) for url in urls[1:]]

        while len(items) > instagram.MAX_CAROUSEL:
            items.pop(-2)

        media = instagram.publish_carousel(items, work["caption"], folder)
    else:
        media = instagram.publish_images(urls, work["caption"])

    return {"media_id": media["id"], "permalink": media.get("permalink")}


def publish_reels(post, work):
    if not work.get("reel"):
        return {"skipped": work.get("reel_skip") or "no_video"}

    folder = f"{datetime.now(KST):%Y-%m-%d}_{work['log_no']}"
    media = instagram.publish_reel(work["reel"], work["caption"], folder)

    return {"media_id": media["id"], "permalink": media.get("permalink")}


PUBLISHERS = {
    "instagram": publish_instagram,
    "reels": publish_reels,
}


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="네이버 블로그 새 글을 인스타그램 등에 올리기")
    parser.add_argument("--link", help="이 글로 만들기 (기본: RSS에서 아직 안 올린 새 글 자동 선택)")
    parser.add_argument("--no-upload", action="store_true", help="카드만 만들고 올리지 않기")
    parser.add_argument("--check", action="store_true", help="올릴 새 글이 있는지만 확인 (GitHub Actions 출력 has_post)")
    parser.add_argument("--check-account", action="store_true", help="인스타 토큰이 작동하는지만 확인 (읽기만, 게시 안 함)")
    parser.add_argument("--reel-file", help="릴스를 새로 만들지 않고 이 mp4(경로나 URL)를 올리기")

    return parser.parse_args()


def write_output(name, value):
    output = os.environ.get("GITHUB_OUTPUT")

    if output:
        with open(output, "a", encoding="utf-8") as file:
            file.write(f"{name}={value}\n")


def record(history, entry):
    history.append({**entry, "at": datetime.now(KST).isoformat(timespec="seconds")})
    save_json(HISTORY_FILE, history)


def find_post(args, history, channels):
    """돌려주는 값: (블로그 이름, 글 또는 None)."""
    if args.link:
        link = naver_blog.canonical_link(args.link)
        owner, _ = naver_blog.parse_post_link(link)
        blog_name, posts = naver_blog.fetch_posts(owner)
        post = next((post for post in posts if post["link"] == link), None)

        return blog_name, post or {"title": "", "link": link, "published": None, "category": "", "summary": ""}

    owner = naver_blog.blog_id()
    blog_name, posts = naver_blog.fetch_posts(owner)
    max_age = int(os.environ.get("MAX_AGE_DAYS") or 3)
    allowed = post_categories()
    tree = None

    def accept(post):
        # RSS의 카테고리 이름만으로는 맛집/서울과 여행/서울을 구분할 수 없어서 글 페이지의 카테고리 번호를 본다.
        nonlocal tree
        tree = tree if tree is not None else naver_blog.category_tree(owner)
        number = naver_blog.fetch_post_category_no(post["link"])
        ok = naver_blog.in_categories(number, tree, allowed)

        if not ok:
            print(f"방문 후기 카테고리가 아니라 건너뜀: [{tree.get(number, ('?', ''))[0]}] {post['title']}")

        return ok

    return blog_name, naver_blog.pick_post(posts, done_links(history, channels), max_age_days=max_age, accept=accept)


def check_account():
    """토큰으로 계정 정보와 게시 한도만 읽어 본다. 아무것도 올리지 않는다."""
    info = instagram.account()
    print(f"인스타 계정: @{info.get('username')} (ID {info['id']}, API {info['host']})")

    limit = instagram.publishing_limit()

    if limit:
        total = (limit.get("config") or {}).get("quota_total")
        print(f"최근 24시간 게시: {limit.get('quota_usage')} / {total}")
    else:
        print("게시 한도는 읽지 못했습니다 (게시 권한은 실제 게시 때 확인됩니다).")

    handle = (os.environ.get("INSTA_HANDLE") or "").strip().lstrip("@")

    if handle and info.get("username") and handle != info["username"]:
        raise SystemExit(f"INSTA_HANDLE(@{handle})과 토큰의 계정(@{info['username']})이 다릅니다.")


def prepare_video(args, post, text, work, work_dir, channels, history, footer, handle):
    """글의 영상: 짧으면 캐러셀에 넣을 세로 영상, 길면 릴스. 영상 쪽이 실패해도 카드 게시는 막지 않는다."""
    need_reel = "reels" in channels and not channel_done(history, post["link"], "reels")
    need_carousel = "instagram" in channels and not channel_done(history, post["link"], "instagram")

    if args.reel_file:
        path = os.path.join(work_dir, "reel.mp4")

        if args.reel_file.startswith("http"):
            with urllib.request.urlopen(args.reel_file, timeout=300) as response, open(path, "wb") as file:
                shutil.copyfileobj(response, file)
        elif os.path.abspath(args.reel_file) != os.path.abspath(path):
            shutil.copyfile(args.reel_file, path)

        work["reel"] = path
        print(f"릴스 파일 사용: {args.reel_file}")
        return

    if not (need_reel or need_carousel):
        return

    try:
        video = reels.download_video(post["link"], work["log_no"])
    except Exception as error:
        print(f"영상 받기 실패 (카드만 올림): {error}")
        work["reel_skip"] = "video_error"
        return

    if not video:
        print("글에 영상이 없어 카드만 올립니다.")
        return

    print(f"글의 영상: {video['duration']:.1f}초 {video['width']}x{video['height']}")

    if video["duration"] < reels.MIN_REEL_SECONDS:
        work["reel_skip"] = "short_video"

        if need_carousel:
            work["carousel_video"] = reels.carousel_video(video, os.path.join(work_dir, "carousel_video.mp4"))
            print("영상이 짧아 캐러셀 2번째 장에 넣습니다.")
        return

    if not need_reel:
        return

    try:
        work["reel"], _ = reels.make_reel(post, text, video, work_dir, footer, handle)
    except Exception as error:
        print(f"릴스 만들기 실패 (카드만 올림): {error}")
        notify_slack(f":warning: 릴스 만들기 실패: {post['title']}\n{error}")
        work["reel_skip"] = "reel_error"


def main():
    args = parse_args()

    if args.check_account:
        check_account()
        return

    history = load_json(HISTORY_FILE, [])
    channels = enabled_channels()

    unknown = [name for name in channels if name not in PUBLISHERS]

    if unknown:
        raise SystemExit(f"아직 없는 채널: {', '.join(unknown)} (지금 되는 것: {', '.join(PUBLISHERS)})")

    # 아직 연결 전(NAVER_BLOG_ID 없음)이면 예약 실행이 실패로 쌓이지 않게 조용히 끝낸다.
    if args.check and not args.link and not (os.environ.get("NAVER_BLOG_ID") or "").strip():
        print("NAVER_BLOG_ID가 없어 건너뜁니다.")
        write_output("has_post", "false")
        return

    # 하루에 올리는 글 수 제한 (Variable DAILY_LIMIT, 기본 1). 글을 지정한 수동 실행은 제외.
    daily_limit = int(os.environ.get("DAILY_LIMIT") or 1)

    if not args.link and posted_today(history) >= daily_limit:
        print(f"오늘은 이미 {daily_limit}개를 올려서 건너뜁니다.")
        write_output("has_post", "false")
        return

    blog_name, post = find_post(args, history, channels)

    if args.check:
        write_output("has_post", "true" if post else "false")
        print(f"새 글: {post['title'] if post else '없음'}")
        return

    if not post:
        print("올릴 새 블로그 글이 없습니다.")
        return

    print(f"선택한 글: {post['title'] or post['link']}")
    text, photos = naver_blog.fetch_post_content(post["link"])

    if not post["title"]:
        post["title"] = text.split("\n", 1)[0][:80]

    if len(text) < MIN_TEXT_LENGTH:
        print(f"본문이 너무 짧아 건너뜁니다 ({len(text)}자).")
        record(history, {"link": post["link"], "title": post["title"], "channel": "all", "skipped": "short"})
        return

    if len(photos) < MIN_PHOTOS:
        print(f"사진이 적어 건너뜁니다 ({len(photos)}장).")
        record(history, {"link": post["link"], "title": post["title"], "channel": "all", "skipped": "photos"})
        return

    upload = not args.no_upload
    handle = (os.environ.get("INSTA_HANDLE") or "").strip()

    if upload and not handle and "instagram" in channels:
        username = instagram.account().get("username")
        handle = f"@{username}" if username else ""

    _, log_no = naver_blog.parse_post_link(post["link"])
    work_dir = os.path.join(OUTPUT_DIR, log_no)
    os.makedirs(work_dir, exist_ok=True)

    content = food_cards.generate(post, text, photos)
    save_json(os.path.join(work_dir, "content.json"), content)
    print(f"카드 문구 생성 완료: {len(content['slides'])}장")

    food_cards.download_photos(content, photos, log_no)
    # 표지 아래 작은 글씨: 지금 피드처럼 블로그 이름 (Variable INSTA_FOOTER로 바꿀 수 있음)
    footer = (os.environ.get("INSTA_FOOTER") or blog_name or "").strip()[:30]
    props = food_cards.build_props(content, log_no, handle, footer)
    images = cards.render(props, work_dir, composition="FoodCards")
    caption = food_cards.build_caption(content, post)

    with open(os.path.join(work_dir, "caption.txt"), "w", encoding="utf-8") as file:
        file.write(caption)

    print(f"카드 렌더링 완료: {work_dir} ({len(images)}장)")

    work = {"log_no": log_no, "images": images, "caption": caption, "content": content}
    # 릴스 아래쪽 안내 한 줄 (Variable REEL_FOOTER)
    reel_footer = (os.environ.get("REEL_FOOTER") or "전체 후기는 블로그에").strip()
    prepare_video(args, post, text, work, work_dir, channels, history, reel_footer, handle)

    if not upload:
        return

    failed = []

    for channel in channels:
        if channel_done(history, post["link"], channel):
            continue

        try:
            result = PUBLISHERS[channel](post, work)
        except Exception as error:
            hint = ""

            if isinstance(error, instagram.InstagramError) and error.token_expired:
                hint = " 토큰이 만료됐어요. 새 토큰을 받아 INSTAGRAM_ACCESS_TOKEN을 바꿔 주세요."

            print(f"{channel} 게시 실패: {error}")
            notify_slack(f":x: {channel} 게시 실패: {post['title']}\n{error}{hint}")
            failed.append(channel)
            continue

        record(history, {"link": post["link"], "title": post["title"], "channel": channel, **result})
        where = result.get("permalink") or result.get("media_id")
        print(f"{channel} 게시 완료: {where}")
        notify_slack(f":camera_with_flash: {channel} 게시: {post['title']}\n{where}")

    if failed:
        raise SystemExit(f"게시 실패: {', '.join(failed)}")


if __name__ == "__main__":
    main()
