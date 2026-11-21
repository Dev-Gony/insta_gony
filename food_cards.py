"""맛집 방문 후기 → 얌얌고니 사진 카드 (Remotion FoodCards).

블로그 본문은 naver_blog.post_content로 [사진N] 표시가 들어간 글을 받는다.
Claude가 글 흐름대로 장을 나누고 장마다 어울리는 사진 번호를 고른다.
사진은 video/public/photos/<글번호>/에 받아 두고 Remotion이 staticFile로 읽는다.
"""

import os
import re
import shutil
import urllib.request

from common import BROWSER_HEADERS, claude_json


SLIDE_TYPES = ["cover", "photo", "outro"]
PHOTO_DIR = os.path.join("video", "public", "photos")
MAX_SLIDES = 10
HASHTAG_COUNT = 5


# 레퍼런스(2026-11-21 인스타에서 직접 넘겨 봄): 서울더핫플 방어 맛집(10장), _mukpunzel 산동교자(좋아요 2만),
# 김밥대장 오믈렛김밥(좋아요 1,364). 한 가게 후기 캐러셀은 모두
# 표지만 사진+굵은 2줄 제목, 중간은 글씨 없는 사진(외관→메뉴→음식→먹는 장면), 마지막은 사진(+질문 한 줄).
# 정보(위치·영업시간)는 카드가 아니라 캡션 2~4줄. 해시태그 5개 안팎.
SYSTEM_PROMPT = """너는 맛집 기록 인스타그램 계정 '얌얌고니'의 편집자다.
블로그 주인 고니가 직접 다녀와서 쓴 방문 후기를 사진 캐러셀로 옮긴다.
큰 맛집 계정들처럼: 표지에만 굵은 제목, 중간 장은 글씨 없이 사진만, 마지막 장에 질문 한 줄.

절대 규칙:
- 본문에 없는 사실·가격·메뉴·맛 평가·영업 정보를 지어내지 않는다. 숫자와 가격은 본문 그대로.
- 사진은 본문에 있는 [사진N]의 N만 쓴다. 같은 사진을 두 번 쓰지 않는다.
- 과장 광고 문구("인생 맛집", "미쳤다", "역대급")는 쓰지 않는다.

장 구성 (사진이 충분하면 8~10장, 적으면 있는 만큼):
1. cover (1장): photo = 메인 메뉴가 가장 크고 먹음직스럽게 보이는 사진.
   title = 2줄 (줄당 11자 이내). 1줄은 이 집을 넘겨 보고 싶게 만드는 본문 사실(예: "오픈런하면 갓 삶은 첫 족발",
   "족발 시키면 칼국수가 공짜"), 2줄은 "지역 + 가게 이름"(예: "명동 미쓰족발"). 두 줄은 줄바꿈으로 나눈다.
2. photo (사진 수에 맞춰 최대 8장): 글씨 없이 사진만. 본문 순서대로 고르되 이야기가 되게:
   가게 외관 → 메뉴판·매장 → 음식이 나온 모습 → 가까이 → 먹는 장면 → 곁들이·마무리.
   비슷한 사진이 연달아 있으면 더 잘 보이는 하나만. 흔들리거나 의미 없는 사진(영수증, 빈 테이블 등)은 뺀다.
   title·body는 비운다.
3. outro (마지막 1장): photo = 가게 외관이나 마무리 장면 (표지와 다른 사진).
   title = 댓글을 부르는 질문 한 줄 (16자 이내, 이 글과 관련, 예: "족발은 쌈파? 소스파?").

caption (인스타 본문, 링크·해시태그 제외). 큰 계정들처럼 담백하게:
- 첫 줄: 훅 한 줄 (본문 사실).
- 빈 줄 뒤 3~5문장: 고니 말투(친근한 존댓말, 짧은 감탄)로 무엇을 먹었고 어땠는지, 본문에서만.
- 빈 줄 뒤 정보 2~3줄 (본문에 있는 것만): "📍 가게 이름 (위치·역)", "✔ 영업시간·휴무".
- 빈 줄 뒤 마지막 줄: 댓글을 부르는 짧은 질문.
- 이모지는 위 정보 줄 머리표(📍 ✔)만. 문장 안·끝에는 넣지 않는다.
hashtags: # 없이 정확히 5개. 지역+메뉴 맛집, 가게 이름, 메뉴 이름처럼 실제로 검색할 것."""


SCHEMA = {
    "type": "object",
    "properties": {
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": SLIDE_TYPES},
                    "photo": {"type": "integer"},
                    "label": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "items": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["type", "photo"],
                "additionalProperties": False,
            },
        },
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["slides", "caption", "hashtags"],
    "additionalProperties": False,
}


def build_prompt(post, text):
    return "\n".join(
        [
            "아래 방문 후기로 얌얌고니 캐러셀을 만들어줘.",
            "",
            f"제목: {post['title']}",
            "",
            "본문 ([사진N]은 그 자리에 있는 사진, ## 는 소제목. 여기에 없는 내용은 쓰지 않는다):",
            "<<<본문",
            text,
            "본문>>>",
        ]
    )


def validate(content, photo_count):
    slides = []
    used = set()

    for slide in content.get("slides") or []:
        for key in ("title", "body", "label"):
            if slide.get(key):
                slide[key] = slide[key].replace("\\n", "\n").strip()

        slide["items"] = [item.strip() for item in slide.get("items") or [] if item.strip()]
        photo = slide.get("photo")

        if not isinstance(photo, int) or not 1 <= photo <= photo_count:
            raise ValueError(f"없는 사진 번호: {photo} (사진 {photo_count}장)")

        if slide["type"] == "photo":
            slide["title"] = ""
            slide["body"] = ""

        # 중간 사진 장에 같은 사진이 또 나오면 버린다 (사진이 적은 글은 outro가 표지 사진을 다시 쓸 수 있다).
        if slide["type"] == "photo" and photo in used:
            continue

        used.add(photo)
        slides.append(slide)

    if not slides or slides[0]["type"] != "cover":
        raise ValueError("첫 장이 표지(cover)가 아닙니다.")

    if slides[-1]["type"] != "outro":
        raise ValueError("마지막 장이 outro가 아닙니다.")

    if not 2 <= len(slides) <= MAX_SLIDES:
        raise ValueError(f"카드 장 수가 이상합니다: {len(slides)}")

    content["slides"] = slides
    content["hashtags"] = [
        tag.strip().lstrip("#").replace(" ", "")
        for tag in content.get("hashtags") or []
        if tag.strip()
    ][:HASHTAG_COUNT]

    return content


def generate(post, text, photos):
    return validate(claude_json(SYSTEM_PROMPT, build_prompt(post, text), SCHEMA), len(photos))


def download_photos(content, photos, log_no):
    """쓰는 사진만 video/public/photos/<글번호>/NN.jpg로 받는다. 돌려주는 값: 폴더 경로."""
    folder = os.path.join(PHOTO_DIR, log_no)
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder, exist_ok=True)

    for slide in content["slides"]:
        number = slide["photo"]
        path = os.path.join(folder, f"{number:02d}.jpg")

        if os.path.exists(path):
            continue

        request = urllib.request.Request(
            photos[number - 1], headers={**BROWSER_HEADERS, "Referer": "https://m.blog.naver.com/"}
        )

        with urllib.request.urlopen(request, timeout=60) as response, open(path, "wb") as file:
            file.write(response.read())

    return folder


def build_props(content, log_no, handle, footer):
    slides = []

    for slide in content["slides"]:
        slides.append(
            {
                "type": slide["type"],
                "photo": f"photos/{log_no}/{slide['photo']:02d}.jpg",
                "label": slide.get("label") or "",
                "title": slide.get("title") or "",
                "body": slide.get("body") or "",
                "items": slide.get("items") or [],
            }
        )

    return {"footer": footer, "handle": handle, "slides": slides}


def build_caption(content, post):
    hashtags = " ".join(f"#{tag}" for tag in content["hashtags"])
    caption = re.sub(r"\n{3,}", "\n\n", content["caption"].strip())

    return (
        f"{caption}\n\n"
        f"전체 후기는 블로그에: {post['link']}\n\n"
        f"{hashtags}"
    )[:2200]
