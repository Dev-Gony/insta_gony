"""블로그 글 → 카드뉴스: Claude로 카드 문구·캡션, Remotion으로 장별 이미지."""

import glob
import os
import re
import shutil
import subprocess
from datetime import datetime

from common import KST, claude_json, save_json
from naver_blog import parse_post_link


VIDEO_PROJECT_DIR = "video"
SLIDE_TYPES = ["cover", "story", "number", "flow", "checklist", "caution", "outro"]


SYSTEM_PROMPT = """너는 블로그 주인이 직접 쓴 글을 인스타그램 카드뉴스로 옮기는 편집자다.
목표: 피드를 넘기던 사람이 표지에서 멈추고, 끝까지 넘겨 "저장"하고, 블로그 전체 글이 궁금해지게 만든다.

원칙:
- 글쓴이의 관점과 말투를 살린다. 글에 없는 사실·숫자·가격·후기·효과를 지어내지 않는다.
- 문장은 짧고 쉽게. 한 문장 25자 안팎. 군더더기·과장·감탄사 금지.
- 카드에는 핵심만, 자세한 내용은 블로그에서 보도록 여지를 남긴다.

카드 구성 (5~8장, 순서 유지):
1. cover: 표지. label에 주제 2단어(예: "여행 · 제주"), title에 2줄 제목(줄 사이 \\n, 줄당 12자 이내),
   핵심 단어나 숫자 하나를 **이렇게** 감싸 강조. body에 이 글에서 얻을 것 2줄.
2. story: 글의 핵심 이야기. title 2줄, items에 핵심 3개(각 30자 이내).
3. number: 글에 인상적인 숫자(가격·기간·순위 등)가 있을 때만. value에 숫자+단위(8자 이내), title에 무엇의 숫자인지, body 한 줄.
4. flow: 순서·과정·방법이 있을 때만. title 한 줄, items에 2~4단계(각 16자 이내).
5. checklist: 글에 독자가 따라 할 팁·준비물·방법이 있을 때만. title 한 줄, items 2~3개 (글에 나온 것만).
6. caution: 글에 주의점이 있을 때만. title 한 줄, body 2문장 이내.
7. outro: 마지막 장. label "여러분 생각은?", title에 독자에게 던지는 질문 2~3줄, body에 "전체 글은 블로그에서" 같은 한 줄.
number, flow, checklist, caution은 재료가 없으면 뺀다. cover, story, outro는 꼭 넣는다.

section: 카드 위쪽에 들어갈 분류 2~6자 (예: "여행", "맛집", "IT 리뷰").
caption: 인스타그램 본문. 첫 줄은 표지보다 구체적인 훅 한 문장, 이어서 핵심 3줄 요약(각 줄 앞에 "▪").
블로그 링크와 해시태그는 넣지 않는다(자동으로 붙는다).
hashtags: # 없이 8~15개. 한국어 위주, 이 주제를 실제로 검색할 만한 것."""


SCHEMA = {
    "type": "object",
    "properties": {
        "section": {"type": "string"},
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": SLIDE_TYPES},
                    "label": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "value": {"type": "string"},
                    "items": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["type"],
                "additionalProperties": False,
            },
        },
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["section", "slides", "caption", "hashtags"],
    "additionalProperties": False,
}


def validate(content):
    slides = content.get("slides") or []

    for slide in slides:
        for key in ("title", "body"):
            if slide.get(key):
                # 모델이 줄바꿈을 글자 그대로 "\n"으로 쓰는 경우가 있다.
                slide[key] = slide[key].replace("\\n", "\n").strip()

        slide["items"] = [item.strip() for item in slide.get("items") or [] if item.strip()]

    # 재료가 없는 장은 뺀다.
    slides = [
        slide
        for slide in slides
        if slide.get("title") or slide.get("value") or slide.get("body") or slide.get("items")
    ]

    if not slides or slides[0]["type"] != "cover":
        raise ValueError("첫 장이 표지(cover)가 아닙니다.")

    if slides[-1]["type"] != "outro":
        raise ValueError("마지막 장이 outro가 아닙니다.")

    # 인스타 캐러셀은 최대 10장
    if not 3 <= len(slides) <= 10:
        raise ValueError(f"카드 장 수가 이상합니다: {len(slides)}")

    content["slides"] = slides
    content["hashtags"] = [
        tag.strip().lstrip("#").replace(" ", "")
        for tag in content.get("hashtags") or []
        if tag.strip()
    ]

    return content


def build_prompt(post, text):
    return "\n".join(
        [
            "아래 블로그 글로 인스타그램 카드뉴스를 만들어줘.",
            "",
            f"제목: {post['title']}",
            f"카테고리: {post.get('category') or ''}",
            "",
            "본문 (여기에 없는 내용은 쓰지 않는다):",
            "<<<본문",
            text,
            "본문>>>",
        ]
    )


def generate(post, text):
    return validate(claude_json(SYSTEM_PROMPT, build_prompt(post, text), SCHEMA))


def build_caption(content, post):
    hashtags = " ".join(f"#{tag}" for tag in content["hashtags"][:15])

    return (
        f"{content['caption'].strip()}\n\n"
        "💾 저장해두고 필요할 때 다시 보세요\n"
        f"📖 전체 글은 블로그에서: {post['link']}\n\n"
        f"{hashtags}"
    )[:2200]


def build_props(content, post, blog_name, handle):
    published = post.get("published") or datetime.now(KST)
    masthead = (os.environ.get("INSTA_MASTHEAD") or blog_name or "BLOG").strip()
    owner, _ = parse_post_link(post["link"])

    return {
        "masthead": masthead[:16],
        "date": published.strftime("%Y.%m.%d"),
        "section": content["section"],
        "handle": handle,
        "source": f"blog.naver.com/{owner}",
        "slides": content["slides"],
    }


def render(props, work_dir, image_format="jpeg", composition="Cards"):
    """Remotion Cards 컴포지션을 장별 이미지로 렌더링한다. 돌려주는 값: 이미지 경로 목록(순서대로).

    인스타그램 API는 JPEG만 받으므로 기본은 jpeg.
    """
    npx = shutil.which("npx")

    if not npx:
        raise RuntimeError("Node.js(npx)가 없습니다. video/ 폴더에서 npm ci를 먼저 실행하세요.")

    extension = "jpg" if image_format == "jpeg" else image_format
    props_path = os.path.abspath(os.path.join(work_dir, "props.json"))
    frames_dir = os.path.abspath(os.path.join(work_dir, "frames"))
    save_json(props_path, props)
    shutil.rmtree(frames_dir, ignore_errors=True)

    command = [
        npx, "remotion", "render", "src/index.ts", composition, frames_dir,
        "--sequence", f"--image-format={image_format}", f"--props={props_path}", "--log=error",
        # 처음 실행할 때 한글 글꼴을 받느라 오래 걸릴 수 있다.
        "--timeout=120000",
    ]

    if image_format == "jpeg":
        command.append("--jpeg-quality=92")

    # 글꼴 받기가 늦어 실패하는 일이 있어 한 번 더 시도한다.
    for _ in range(2):
        result = subprocess.run(
            command,
            cwd=VIDEO_PROJECT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=900,
        )

        if result.returncode == 0:
            break

    if result.returncode != 0:
        raise RuntimeError(f"카드 렌더링 실패: {(result.stderr or result.stdout).strip()[-2000:]}")

    frames = sorted(
        glob.glob(os.path.join(frames_dir, "*.*")),
        key=lambda path: int(re.findall(r"\d+", os.path.basename(path))[-1]),
    )
    paths = []

    for index, frame in enumerate(frames, start=1):
        path = os.path.join(work_dir, f"card-{index:02d}.{extension}")
        shutil.move(frame, path)
        paths.append(path)

    shutil.rmtree(frames_dir, ignore_errors=True)

    return paths
