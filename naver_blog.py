"""네이버 블로그: RSS로 새 글 목록, 모바일 페이지에서 본문 글자 가져오기."""

import email.utils
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from common import KST, download_page


MAX_SOURCE_LENGTH = 12000


def blog_id():
    value = (os.environ.get("NAVER_BLOG_ID") or "").strip()

    if not value:
        raise RuntimeError("NAVER_BLOG_ID가 없습니다 (blog.naver.com/<블로그ID>).")

    return value


def parse_post_link(link):
    """블로그 글 주소에서 (블로그ID, 글번호)를 뽑는다. 여러 주소 형식을 받는다."""
    parts = urllib.parse.urlsplit(link)
    query = urllib.parse.parse_qs(parts.query)

    if query.get("blogId") and query.get("logNo"):
        return query["blogId"][0], query["logNo"][0]

    match = re.search(r"/([A-Za-z0-9_\-]+)/(\d+)", parts.path)

    if not match:
        raise ValueError(f"네이버 블로그 글 주소가 아닙니다: {link}")

    return match.group(1), match.group(2)


def canonical_link(link):
    owner, log_no = parse_post_link(link)
    return f"https://blog.naver.com/{owner}/{log_no}"


def parse_rss(xml_text):
    """RSS → (블로그 이름, [글...]). 글: title, link, published(KST datetime), category, summary."""
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    posts = []

    for item in channel.findall("item"):
        link = (item.findtext("guid") or item.findtext("link") or "").strip()

        try:
            link = canonical_link(link)
        except ValueError:
            continue

        published = None
        date_text = item.findtext("pubDate")

        if date_text:
            published = email.utils.parsedate_to_datetime(date_text).astimezone(KST)

        posts.append(
            {
                "title": (item.findtext("title") or "").strip(),
                "link": link,
                "published": published,
                "category": (item.findtext("category") or "").strip(),
                "summary": (item.findtext("description") or "").strip(),
            }
        )

    return (channel.findtext("title") or "").strip(), posts


def fetch_posts(owner):
    return parse_rss(download_page(f"https://rss.blog.naver.com/{owner}.xml"))


def post_text(html):
    """모바일 블로그 페이지에서 본문 글만 뽑는다 (스마트에디터 ONE, 옛 에디터 모두)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".se-main-container") or soup.select_one("#postViewArea") or soup.select_one("#viewTypeSelector")

    if not root:
        return ""

    blocks = root.select(".se-text-paragraph, .se-code-source, .se-quote, .se-table") or root.find_all(["p", "div"])
    lines = []

    for block in blocks:
        text = block.get_text(" ", strip=True).replace("​", "").strip()

        if text and (not lines or lines[-1] != text):
            lines.append(text)

    return "\n".join(lines)[:MAX_SOURCE_LENGTH]


def fetch_post_text(link):
    owner, log_no = parse_post_link(link)
    return post_text(download_page(f"https://m.blog.naver.com/{owner}/{log_no}"))


def pick_post(posts, done_links, now=None, max_age_days=3):
    """아직 안 올린 글 중 가장 오래된 것 1개 (너무 오래된 글은 제외, 처음 연결할 때 옛 글이 쏟아지지 않게)."""
    now = now or datetime.now(KST)
    candidates = [
        post
        for post in posts
        if post["link"] not in done_links
        and post["published"]
        and now - post["published"] <= timedelta(days=max_age_days)
    ]

    return min(candidates, key=lambda post: post["published"]) if candidates else None
