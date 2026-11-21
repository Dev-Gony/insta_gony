"""네이버 블로그 새 글 → 여러 채널에 자동 게시.

흐름: 블로그 RSS에서 아직 안 올린 새 글 1개 → 본문 가져오기 → Claude로 카드 문구·캡션
→ Remotion으로 카드 JPEG → 켜 둔 채널(CHANNELS)마다 게시 → config/history.json

채널
- instagram: 카드뉴스 캐러셀 (지금 동작)
- threads, clip: 자리만 잡아 둠 (README의 "다음 할 일")

설정 (GitHub Variables / Secrets): README.md 참고
"""

import argparse
import os
from datetime import datetime

import cards
import food_cards
import instagram
import naver_blog
from common import KST, load_json, notify_slack, save_json


HISTORY_FILE = "config/history.json"
OUTPUT_DIR = "runtime/posts"

# 본문이 이보다 짧으면(사진만 있는 글 등) 카드로 만들 재료가 부족하다.
MIN_TEXT_LENGTH = 300

# 사진 카드에 쓸 사진이 이보다 적으면 건너뛴다.
MIN_PHOTOS = 5

# 방문 후기만 올린다: 정보 글 카테고리는 건너뛴다 (Variable SKIP_CATEGORIES, 쉼표로).
DEFAULT_SKIP_CATEGORIES = "먹거리 정보,방송 맛집,제철·레시피"


def skip_categories():
    value = os.environ.get("SKIP_CATEGORIES")
    value = DEFAULT_SKIP_CATEGORIES if value is None or not value.strip() else value
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
    value = os.environ.get("CHANNELS") or "instagram"
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
    media = instagram.publish_images(urls, work["caption"])

    return {"media_id": media["id"], "permalink": media.get("permalink")}


PUBLISHERS = {
    "instagram": publish_instagram,
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

    blog_name, posts = naver_blog.fetch_posts(naver_blog.blog_id())
    max_age = int(os.environ.get("MAX_AGE_DAYS") or 3)
    skipped = skip_categories()
    posts = [post for post in posts if post["category"] not in skipped]

    return blog_name, naver_blog.pick_post(posts, done_links(history, channels), max_age_days=max_age)


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
    masthead = (os.environ.get("INSTA_MASTHEAD") or blog_name or "얌얌고니").strip()[:16]
    props = food_cards.build_props(content, log_no, handle, masthead)
    images = cards.render(props, work_dir, composition="FoodCards")
    caption = food_cards.build_caption(content, post)

    with open(os.path.join(work_dir, "caption.txt"), "w", encoding="utf-8") as file:
        file.write(caption)

    print(f"카드 렌더링 완료: {work_dir} ({len(images)}장)")

    if not upload:
        return

    work = {"log_no": log_no, "images": images, "caption": caption, "content": content}
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
