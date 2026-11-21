import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cards  # noqa: E402
import instagram  # noqa: E402
import main  # noqa: E402
import naver_blog  # noqa: E402
from common import KST, normalize_oauth_token  # noqa: E402


RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title><![CDATA[곤이 블로그]]></title>
<item>
  <category><![CDATA[여행]]></category>
  <title><![CDATA[제주 3일 코스]]></title>
  <link><![CDATA[https://blog.naver.com/gony/224000000002?fromRss=true&trackingCode=rss]]></link>
  <guid>https://blog.naver.com/gony/224000000002</guid>
  <description><![CDATA[요약]]></description>
  <pubDate>Tue, 17 Nov 2026 09:00:00 +0900</pubDate>
</item>
<item>
  <title><![CDATA[옛 글]]></title>
  <guid>https://blog.naver.com/gony/224000000001</guid>
  <pubDate>Sun, 01 Nov 2026 09:00:00 +0900</pubDate>
</item>
</channel></rss>"""


class NaverBlogTest(unittest.TestCase):
    def test_parse_post_link_accepts_common_forms(self):
        for link in (
            "https://blog.naver.com/gony/224000000002",
            "https://m.blog.naver.com/gony/224000000002?referrerCode=0",
            "https://blog.naver.com/PostView.naver?blogId=gony&logNo=224000000002",
        ):
            self.assertEqual(naver_blog.parse_post_link(link), ("gony", "224000000002"))

        with self.assertRaises(ValueError):
            naver_blog.parse_post_link("https://blog.naver.com/gony")

    def test_parse_rss(self):
        name, posts = naver_blog.parse_rss(RSS)

        self.assertEqual(name, "곤이 블로그")
        self.assertEqual(posts[0]["link"], "https://blog.naver.com/gony/224000000002")
        self.assertEqual(posts[0]["category"], "여행")
        self.assertEqual(posts[0]["published"].hour, 9)

    def test_pick_post_skips_done_and_old_posts(self):
        _, posts = naver_blog.parse_rss(RSS)
        now = datetime(2026, 11, 17, 12, tzinfo=KST)

        self.assertEqual(naver_blog.pick_post(posts, set(), now=now)["title"], "제주 3일 코스")
        self.assertIsNone(naver_blog.pick_post(posts, {posts[0]["link"]}, now=now))
        # 기간 안이면 오래된 것부터
        self.assertEqual(naver_blog.pick_post(posts, set(), now=now, max_age_days=30)["title"], "옛 글")

    def test_post_text_reads_smart_editor_body(self):
        html = """<html><body><div class="se-main-container">
          <p class="se-text-paragraph">첫 문단​</p>
          <p class="se-text-paragraph"> </p>
          <p class="se-text-paragraph">둘째 문단</p>
        </div><div class="comment">댓글</div></body></html>"""

        self.assertEqual(naver_blog.post_text(html), "첫 문단\n둘째 문단")
        self.assertEqual(naver_blog.post_text("<html><body>없음</body></html>"), "")


class CategoryTest(unittest.TestCase):
    TREE = {"11": ("맛집", ""), "18": ("서울", "11"), "13": ("여행", ""), "21": ("서울", "13"), "60": ("방송 맛집", "")}

    def test_only_food_subcategories_pass(self):
        self.assertTrue(naver_blog.in_categories("18", self.TREE, {"11"}))
        self.assertTrue(naver_blog.in_categories("11", self.TREE, {"11"}))
        # 이름이 같은 여행/서울, 맛집 밖의 방송 맛집은 통과하지 않는다
        self.assertFalse(naver_blog.in_categories("21", self.TREE, {"11"}))
        self.assertFalse(naver_blog.in_categories("60", self.TREE, {"11"}))
        self.assertFalse(naver_blog.in_categories(None, self.TREE, {"11"}))

    def test_post_category_no_from_page(self):
        self.assertEqual(naver_blog.post_category_no('<a data-categoryNo="18">'), "18")
        self.assertEqual(naver_blog.post_category_no('{"categoryNo\\":18,'), "18")
        self.assertIsNone(naver_blog.post_category_no("<html></html>"))


class CardsTest(unittest.TestCase):
    def test_validate_cleans_text_and_drops_empty_slides(self):
        content = cards.validate(
            {
                "section": "여행",
                "slides": [
                    {"type": "cover", "title": "첫 줄\\n둘째 줄", "body": " 설명 "},
                    {"type": "story", "title": "핵심", "items": ["하나", " ", "둘"]},
                    {"type": "number"},
                    {"type": "outro", "title": "질문?"},
                ],
                "caption": "훅",
                "hashtags": ["#제주 여행", " "],
            }
        )

        self.assertEqual([slide["type"] for slide in content["slides"]], ["cover", "story", "outro"])
        self.assertEqual(content["slides"][0]["title"], "첫 줄\n둘째 줄")
        self.assertEqual(content["slides"][1]["items"], ["하나", "둘"])
        self.assertEqual(content["hashtags"], ["제주여행"])

    def test_validate_requires_cover_first_and_outro_last(self):
        with self.assertRaises(ValueError):
            cards.validate({"slides": [{"type": "story", "title": "a"}, {"type": "outro", "title": "b"}]})

    def test_build_caption_adds_blog_link_and_hashtags(self):
        caption = cards.build_caption(
            {"caption": "훅 한 줄", "hashtags": ["제주여행", "제주코스"]}, {"link": "https://blog.naver.com/gony/1"}
        )

        self.assertTrue(caption.startswith("훅 한 줄"))
        self.assertIn("https://blog.naver.com/gony/1", caption)
        self.assertTrue(caption.endswith("#제주여행 #제주코스"))


class MainTest(unittest.TestCase):
    def test_done_links_needs_every_enabled_channel(self):
        history = [
            {"link": "a", "channel": "instagram"},
            {"link": "b", "channel": "instagram"},
            {"link": "b", "channel": "threads"},
            {"link": "c", "channel": "all", "skipped": "short"},
        ]

        self.assertEqual(main.done_links(history, ["instagram"]), {"a", "b", "c"})
        self.assertEqual(main.done_links(history, ["instagram", "threads"]), {"b", "c"})
        self.assertTrue(main.channel_done(history, "a", "instagram"))
        self.assertFalse(main.channel_done(history, "a", "threads"))


class InstagramTest(unittest.TestCase):
    def setUp(self):
        instagram._account = None

    def tearDown(self):
        instagram._account = None

    def test_account_falls_back_to_facebook_host(self):
        hosts = []

        def fake_call(host, method, path, params=None):
            hosts.append(host)

            if host == "graph.instagram.com":
                raise instagram.InstagramError("400 Invalid OAuth access token", code=190)
            return {"username": "yamyam_gony"}

        env = {"INSTAGRAM_USER_ID": "17", "INSTAGRAM_GRAPH_HOST": ""}

        with mock.patch.object(instagram, "_call", side_effect=fake_call), mock.patch.dict("os.environ", env):
            info = instagram.account()
            instagram.account()

        self.assertEqual(info, {"id": "17", "username": "yamyam_gony", "host": "graph.facebook.com"})
        self.assertEqual(hosts, ["graph.instagram.com", "graph.facebook.com"])

    def test_account_reports_both_hosts_when_token_is_bad(self):
        def fake_call(host, method, path, params=None):
            raise instagram.InstagramError(f"{host} bad", code=190)

        env = {"INSTAGRAM_USER_ID": "17", "INSTAGRAM_GRAPH_HOST": ""}

        with mock.patch.object(instagram, "_call", side_effect=fake_call), mock.patch.dict("os.environ", env):
            with self.assertRaises(instagram.InstagramError) as caught:
                instagram.account()

        self.assertTrue(caught.exception.token_expired)
        self.assertIn("graph.facebook.com", str(caught.exception))

    def test_publish_carousel_flow(self):
        calls = []

        def fake_api(method, path, params=None):
            calls.append((method, path, params))

            if path == "17/media":
                return {"id": f"c{len(calls)}"}
            if path == "17/media_publish":
                return {"id": "m1"}
            if params and params.get("fields") == "status_code":
                return {"status_code": "FINISHED"}
            if params and params.get("fields") == "permalink":
                return {"permalink": "https://www.instagram.com/p/x/"}
            raise AssertionError(path)

        instagram._account = {"id": "17", "username": "gony", "host": "graph.instagram.com"}

        with mock.patch.object(instagram, "_api", side_effect=fake_api):
            media = instagram.publish_images(["https://a/1.jpg", "https://a/2.jpg"], "캡션")

        self.assertEqual(media, {"id": "m1", "permalink": "https://www.instagram.com/p/x/"})
        carousel = [params for _, _, params in calls if params and params.get("media_type") == "CAROUSEL"]
        self.assertEqual(len(carousel), 1)
        self.assertEqual(carousel[0]["caption"], "캡션")
        self.assertEqual(len(carousel[0]["children"].split(",")), 2)

    def test_publish_rejects_too_many_images(self):
        with self.assertRaises(ValueError):
            instagram.publish_images([f"https://a/{i}.jpg" for i in range(11)], "캡션")


class CommonTest(unittest.TestCase):
    def test_normalize_oauth_token_joins_wrapped_lines(self):
        self.assertEqual(normalize_oauth_token("토큰:\n sk-ant-oat01-abc\ndef\n\n끝."), "sk-ant-oat01-abcdef")


if __name__ == "__main__":
    unittest.main()
