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


SLIDE_TYPES = ["cover", "photo", "menu", "info", "outro"]
PHOTO_DIR = os.path.join("video", "public", "photos")
MAX_SLIDES = 10
HASHTAG_COUNT = 5


SYSTEM_PROMPT = """너는 맛집 기록 인스타그램 계정 '얌얌고니'의 편집자다.
블로그 주인 고니가 직접 다녀와서 쓴 방문 후기를 사진 캐러셀(7~10장)로 옮긴다.
목표: 피드에서 표지 사진에 멈추고, 넘기면서 가게에 가고 싶어지고, 마지막에 "저장"하고 댓글을 달게 만든다.

절대 규칙:
- 본문에 없는 사실·가격·메뉴·맛 평가·영업 정보를 지어내지 않는다. 숫자와 가격은 본문 그대로.
- 사진은 본문에 있는 [사진N]의 N만 쓴다. 장마다 그 장의 글과 가장 가까이 붙어 있는 사진을 고른다
  (그 사진 바로 앞뒤 문장이 그 장의 내용이어야 한다). 같은 사진을 두 번 쓰지 않는다.
- 고니 말투(친근한 존댓말·짧은 감탄)를 살리되 과장 광고 문구("인생 맛집", "미쳤다")는 쓰지 않는다.

장 구성 (순서 유지):
1. cover (1장): photo = 가장 먹음직스럽게 메인 메뉴가 크게 보이는 사진.
   title = 2줄 "지역 + 대표 메뉴\\n가게 이름" (줄당 9자 이내, 예: "명동 족발\\n미쓰족발").
   label = 이 집을 한마디로 (10자 이내, 본문 사실, 예: "오픈런 첫 족발").
2. photo (4~6장): 가게 → 메뉴/음식 → 먹는 장면 → 마무리 흐름대로.
   title = 그 사진에 붙은 핵심 한 줄 (16자 이내), 꼭 강조할 단어 하나를 **이렇게** 감싼다.
   body = 보충 한 줄 (22자 이내, 없어도 됨).
3. menu (본문에 가격이 있을 때만, 1장): title = "메뉴판", items = "메뉴 이름|가격" 최대 6개(본문 순서).
   고니가 시킨 메뉴는 이름 앞에 "★". photo = 메뉴판·대표 음식 사진.
4. info (본문에 주소·영업시간 등이 있을 때만, 1장): title = "저장해두고 가기",
   items = "항목|내용" 최대 5개. 항목은 위치·영업·주차·문의·팁 중에서 (내용 24자 이내, 본문 그대로 줄여서).
   photo = 가게 외관이나 매장 사진.
5. outro (마지막 1장): photo = 마무리 장면 사진. title = 댓글을 부르는 질문 2줄 (줄당 12자 이내, 이 글과 관련,
   예: "족발은 쌈 vs 그냥\\n여러분은?"). body = "전체 후기는 블로그에서".

caption (인스타 본문, 링크·해시태그 제외):
- 첫 줄: 사진을 넘기게 만드는 한 줄 훅 (본문 사실).
- 2~3줄: 고니 말투로 무엇을 먹었고 어땠는지.
- 빈 줄 뒤에 정보 줄 (본문에 있는 것만): "✅ 가게 이름", "📍 위치(역 기준)", "🕐 영업시간", "💰 대표 메뉴 가격".
- 마지막 줄: 댓글을 부르는 짧은 질문.
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

        if photo in used:
            # 같은 사진이 두 번 나오면 뒤의 장은 버린다 (표지·마지막 장은 지키기 위해 photo 장만).
            if slide["type"] == "photo":
                continue

        used.add(photo)
        slides.append(slide)

    if not slides or slides[0]["type"] != "cover":
        raise ValueError("첫 장이 표지(cover)가 아닙니다.")

    if slides[-1]["type"] != "outro":
        raise ValueError("마지막 장이 outro가 아닙니다.")

    if not 4 <= len(slides) <= MAX_SLIDES:
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


def build_props(content, log_no, handle, masthead):
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

    return {"masthead": masthead, "handle": handle, "slides": slides}


def build_caption(content, post):
    hashtags = " ".join(f"#{tag}" for tag in content["hashtags"])
    caption = re.sub(r"\n{3,}", "\n\n", content["caption"].strip())

    return (
        f"{caption}\n\n"
        "💾 저장해두고 갈 때 꺼내 보세요\n"
        f"📖 전체 후기: {post['link']}\n\n"
        f"{hashtags}"
    )[:2200]
