"""블로그 글 안의 동영상 → 얌얌고니 릴스 (또는 짧으면 캐러셀에 넣을 세로 영상).

흐름 (릴스):
1. 네이버 동영상 원본(mp4)을 받는다 → 30fps 고정 무음 영상 + 매장 소리 wav로 나눈다
   (원본은 프레임 속도가 일정하지 않아 Remotion이 프레임을 못 찾는 일이 있었다)
2. 1초(긴 영상은 몇 초)마다 한 장씩, 시각이 적힌 장면 시트 이미지를 만든다
3. Claude가 장면 시트와 블로그 본문을 보고 대사 6~8줄과 줄마다 원본 구간을 고른다
   (대사는 본문 사실만, 구간은 그 대사의 내용이 실제로 보이는 곳만 — 술 광고·딴 화면 금지)
4. 대사마다 Gemini TTS(속삭이는 말투) → 앞뒤 빈 소리 자르고 1.12배
5. 대사 길이에 맞춰 컷 배치 (원본이 짧으면 최대 0.7배 느리게) → Remotion FoodReelEdit → 소리 크기 -14 LUFS

기준: ~/.claude/youtube/reels.md, 레퍼런스(부산맛집여기·_mukpunzel, 2026-11-21 직접 확인) —
내레이션 + 말에 맞춘 작은 자막, 첫 장면만 큰 제목, 멈춘 장면은 2~4초, 20~30초.
"""

import glob
import json
import math
import os
import shutil
import subprocess
import urllib.request
import wave

import naver_blog
import tts
from common import BROWSER_HEADERS, claude_json, save_json


VIDEO_PROJECT_DIR = "video"
PUBLIC_DIR = os.path.join(VIDEO_PROJECT_DIR, "public", "videos")

# 원본 영상이 이보다 짧으면 릴스 대신 캐러셀에 영상 한 장으로 넣는다
MIN_REEL_SECONDS = float(os.environ.get("MIN_REEL_SECONDS") or 15)
# 캐러셀 영상은 60초까지
MAX_CAROUSEL_VIDEO_SECONDS = 60

VOICE_GAP = 0.12        # 대사 사이 쉼
VOICE_TEMPO = 1.12      # 속삭임이 늘어지지 않게
LAST_HOLD = 0.9         # 마지막 질문을 읽을 시간
MIN_RATE = 0.7          # 원본이 짧을 때 느리게 재생하는 한계


# ---------------------------------------------------------------------------
# ffmpeg
# ---------------------------------------------------------------------------

def ffmpeg_exe():
    found = shutil.which("ffmpeg")

    if found:
        return found

    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args):
    result = subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", *args], capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패: {result.stderr.strip()[-800:]}")


def wav_seconds(path):
    with wave.open(path) as file:
        return file.getnframes() / file.getframerate()


# ---------------------------------------------------------------------------
# 1. 원본 받기
# ---------------------------------------------------------------------------

def download_video(link, log_no):
    """글의 첫 동영상을 받아 video/public/videos/<글번호>/에 둔다. 없으면 None.

    돌려주는 값: {"dir", "raw", "cfr", "ambient", "duration", "width", "height"} (경로는 public 기준 상대 경로도 함께)
    """
    videos = naver_blog.fetch_post_videos(link)

    if not videos:
        return None

    source = naver_blog.video_source(*videos[0])
    folder = os.path.join(PUBLIC_DIR, log_no)
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder, exist_ok=True)

    raw = os.path.join(folder, "source.mp4")
    request = urllib.request.Request(source["url"], headers={**BROWSER_HEADERS, "Referer": "https://m.blog.naver.com/"})

    with urllib.request.urlopen(request, timeout=300) as response, open(raw, "wb") as file:
        shutil.copyfileobj(response, file)

    return {
        "dir": folder,
        "raw": raw,
        "duration": float(source["duration"]),
        "width": int(source["width"]),
        "height": int(source["height"]),
        "public": f"videos/{log_no}",
    }


def prepare_reel_media(video):
    """30fps 고정 무음 영상과 매장 소리 wav."""
    cfr = os.path.join(video["dir"], "cfr.mp4")
    ambient = os.path.join(video["dir"], "ambient.wav")
    run_ffmpeg(["-i", video["raw"], "-vf", "fps=30", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-g", "30", "-pix_fmt", "yuv420p", "-an", cfr])

    try:
        run_ffmpeg(["-i", video["raw"], "-vn", "-ac", "2", "-ar", "48000", ambient])
    except RuntimeError:
        # 소리가 없는 영상: 무음 트랙
        run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(video["duration"]), ambient])

    video["cfr"] = cfr
    video["ambient"] = ambient
    return video


def carousel_video(video, out_path):
    """짧은 영상을 캐러셀용 1080x1350 세로 mp4로 (가운데 영상, 위아래는 같은 영상을 흐리게)."""
    seconds = min(video["duration"], MAX_CAROUSEL_VIDEO_SECONDS)
    graph = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1350:force_original_aspect_ratio=increase,crop=1080:1350,boxblur=30:2,eq=brightness=-0.25[bgb];"
        "[fg]scale=1080:1350:force_original_aspect_ratio=decrease[fgs];"
        "[bgb][fgs]overlay=(W-w)/2:(H-h)/2,fps=30,format=yuv420p[v]"
    )
    args = ["-i", video["raw"], "-t", f"{seconds:.2f}", "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "fast", "-crf", "21", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
            "-movflags", "+faststart", out_path]
    run_ffmpeg(args)
    return out_path


# ---------------------------------------------------------------------------
# 2. 장면 시트
# ---------------------------------------------------------------------------

def scene_sheets(video, out_dir, columns=8, rows=5):
    """시각이 적힌 장면 시트 이미지들. 돌려주는 값: (시트 경로 목록, 몇 초마다 한 장인지)."""
    from PIL import Image, ImageDraw

    step = max(1, math.ceil(video["duration"] / 80))
    frames_dir = os.path.join(out_dir, "frames")
    shutil.rmtree(frames_dir, ignore_errors=True)
    os.makedirs(frames_dir, exist_ok=True)
    run_ffmpeg(["-i", video["raw"], "-vf", f"fps=1/{step},scale=240:-2", os.path.join(frames_dir, "%03d.jpg")])

    frames = sorted(glob.glob(os.path.join(frames_dir, "*.jpg")))
    per_sheet = columns * rows
    sheets = []

    for sheet_index in range(0, len(frames), per_sheet):
        chunk = frames[sheet_index:sheet_index + per_sheet]
        first = Image.open(chunk[0])
        width, height = first.size
        label = 26
        sheet = Image.new("RGB", (columns * width, rows * (height + label)), "white")
        draw = ImageDraw.Draw(sheet)

        for offset, path in enumerate(chunk):
            # n번째 칸 ≈ n*step초 장면
            seconds = (sheet_index + offset) * step
            x = (offset % columns) * width
            y = (offset // columns) * (height + label)
            draw.rectangle([x, y, x + width, y + label], fill="black")
            draw.text((x + 6, y + 6), f"{seconds}s", fill="yellow")
            sheet.paste(Image.open(path), (x, y + label))

        path = os.path.join(out_dir, f"scenes_{len(sheets) + 1}.jpg")
        sheet.save(path, quality=85)
        sheets.append(path)

    shutil.rmtree(frames_dir, ignore_errors=True)
    return sheets, step


# ---------------------------------------------------------------------------
# 3. 대사·구간 고르기 (Claude)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """너는 맛집 기록 인스타그램 계정 '얌얌고니'의 릴스 편집자다.
블로그 주인 고니가 직접 다녀와서 찍은 영상 하나와 그 후기 글로, 속삭이는 내레이션이 깔리는 20~30초 릴스를 짠다.

레퍼런스(큰 맛집 계정 릴스): 내레이션 + 말에 맞춰 바뀌는 작은 자막, 첫 장면만 큰 제목, 멈춘 장면은 2~4초씩.

절대 규칙:
- 대사는 블로그 본문에 있는 사실만. 가격·시간·메뉴·맛 표현을 지어내지 않는다. "김이 솔솔"처럼 본문에 없는 묘사도 쓰지 않는다.
- 장면 시트 이미지를 반드시 Read로 직접 열어 본다. 줄마다 고르는 원본 구간에는 그 줄이 말하는 것이 실제로 보여야 한다.
  광고 화면(술·음료 광고, 태블릿의 다른 탭), 흔들리거나 아무것도 안 보이는 구간, 다른 가게는 쓰지 않는다.
  확실하지 않으면 그 줄을 빼거나, 대사를 화면에 보이는 것에 맞게 바꾼다.
- 시트의 시각(초)은 그 칸이 시작하는 시각이다. 구간 시각은 원본 영상 길이 안에서.

구성 (대사 6~8줄, 말로 합쳐 20~26초. 속삭이는 목소리는 1초에 6음절 정도):
1. 첫 줄 = 훅. 가장 먹음직스럽고 움직임이 있는 장면(젓가락으로 들기 등) + 이 집을 한마디로 (12음절 이내).
2. 가게 이름·위치·시간 → 대표 메뉴·가격 → 음식 모습 → 곁들이·무료 → 맛 표현 순서로 이야기가 되게.
3. 마지막 줄 = 댓글을 부르는 질문 하나 (예: "여러분은 쌈파예요, 소스파예요?"). 구독·좋아요 부탁 금지.
- text: 화면 자막. 대사와 같은 문장, 강조할 단어 하나를 **이렇게**. 숫자는 숫자로(58,000원).
- speech: 읽을 문장. 숫자는 한글로(오만 팔천 원), 기호 없이.
- ranges: 그 줄 동안 보여줄 원본 구간 1~2개 [시작초, 끝초]. 한 줄의 구간 합은 대략 그 줄을 읽는 시간(음절 수 ÷ 6초).
  다른 줄과 구간이 겹치지 않게. 첫 줄 구간은 움직임이 있는 곳.
- seen: 고른 구간에 실제로 보이는 것 한 줄 (확인용).
hook: 첫 줄 동안 위에 크게 뜰 2줄 제목 (줄당 7자 이내, 줄바꿈으로 나눔, 강조 단어 **).
cta_text: 마지막 화면 큰 글씨 2줄 (질문을 짧게, 강조 **). cta_sub: 작은 안내 (예: "댓글로 한 단어만")."""


SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "speech": {"type": "string"},
                    "ranges": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
                    "seen": {"type": "string"},
                },
                "required": ["text", "speech", "ranges", "seen"],
                "additionalProperties": False,
            },
        },
        "hook": {"type": "string"},
        "cta_text": {"type": "string"},
        "cta_sub": {"type": "string"},
    },
    "required": ["lines", "hook", "cta_text", "cta_sub"],
    "additionalProperties": False,
}


def plan(post, text, sheets, step, duration):
    prompt = "\n".join(
        [
            "아래 블로그 후기와 영상 장면 시트로 릴스를 짜줘.",
            "",
            f"영상 길이: {duration:.1f}초. 장면 시트는 {step}초마다 한 칸이고 칸 위에 시작 시각이 적혀 있다.",
            "장면 시트 (Read로 열어 볼 것):",
            *[f"- {os.path.abspath(path)}" for path in sheets],
            "",
            f"제목: {post['title']}",
            "본문 ([사진N]·[장소]는 무시해도 된다. 여기에 없는 내용은 쓰지 않는다):",
            "<<<본문",
            text,
            "본문>>>",
        ]
    )
    content = claude_json(SYSTEM_PROMPT, prompt, SCHEMA, read_dirs=[os.path.dirname(sheets[0])])
    return validate_plan(content, duration)


def validate_plan(content, duration):
    lines = []

    for line in content.get("lines") or []:
        ranges = []

        for pair in line.get("ranges") or []:
            if len(pair) != 2:
                continue

            start, end = max(0.0, float(pair[0])), min(duration, float(pair[1]))

            if end - start >= 0.8:
                ranges.append([round(start, 2), round(end, 2)])

        text = (line.get("text") or "").replace("\\n", "\n").strip()
        speech = (line.get("speech") or "").strip()

        if ranges and text and speech:
            lines.append({"text": text, "speech": speech, "ranges": ranges, "seen": line.get("seen", "")})

    if not 4 <= len(lines) <= 9:
        raise ValueError(f"릴스 대사 줄 수가 이상합니다: {len(lines)}")

    content["lines"] = lines
    content["hook"] = (content.get("hook") or "").replace("\\n", "\n").strip()
    content["cta_text"] = (content.get("cta_text") or "").replace("\\n", "\n").strip()
    content["cta_sub"] = (content.get("cta_sub") or "댓글로 한 단어만").strip()
    return content


# ---------------------------------------------------------------------------
# 4. 내레이션
# ---------------------------------------------------------------------------

def narrate(content, voice_dir):
    """대사마다 속삭이는 음성 → 앞뒤 빈 소리 자르고 1.12배. 돌려주는 값: 줄마다 (파일, 초)."""
    os.makedirs(voice_dir, exist_ok=True)
    results = []

    for index, line in enumerate(content["lines"], start=1):
        raw = os.path.join(voice_dir, f"raw_{index:02d}.wav")
        path = os.path.join(voice_dir, f"{index:02d}.wav")
        tts.synthesize(line["speech"], raw)
        run_ffmpeg([
            "-i", raw,
            "-af",
            "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
            f"silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse,atempo={VOICE_TEMPO}",
            path,
        ])
        os.remove(raw)
        results.append((path, wav_seconds(path)))
        # 무료 한도(분당 요청 수)
        import time
        time.sleep(6)

    return results


# ---------------------------------------------------------------------------
# 5. 타임라인 → 렌더
# ---------------------------------------------------------------------------

def timeline(content, voices, video, footer, handle):
    """대사 길이에 맞춘 컷·자막 배치 → FoodReelEdit props."""
    lines, cuts, t = [], [], 0.0
    public = video["public"]

    for index, (line, (voice_path, seconds)) in enumerate(zip(content["lines"], voices)):
        last = index == len(voices) - 1
        length = round(seconds + VOICE_GAP + (LAST_HOLD if last else 0), 2)
        lines.append({
            "from": round(t, 2),
            "duration": length,
            "text": line["text"],
            "voice": f"{public}/voice/{os.path.basename(voice_path)}",
        })

        ranges = [list(pair) for pair in line["ranges"]]
        total = sum(end - start for start, end in ranges)

        # 원본이 너무 짧으면(0.7배로도 모자라면) 구간을 뒤로(안 되면 앞으로) 늘린다
        need = length * MIN_RATE
        if total < need:
            start, end = ranges[-1]
            grow = need - total
            end2 = min(video["duration"], end + grow)
            start2 = max(0.0, start - (grow - (end2 - end)))
            ranges[-1] = [start2, end2]
            total = sum(e - s for s, e in ranges)

        cursor = t
        for start, end in ranges:
            part = round(length * (end - start) / total, 2)
            cuts.append({"start": round(start, 2), "end": round(end, 2), "from": round(cursor, 2), "duration": part})
            cursor += part

        t += length

    return {
        "video": f"{public}/cfr.mp4",
        "ambient": f"{public}/ambient.wav",
        "width": video["width"],
        "height": video["height"],
        "cuts": cuts,
        "lines": lines,
        "hook": content["hook"],
        "cta": {"from": lines[-1]["from"], "text": content["cta_text"], "sub": content["cta_sub"]},
        "footer": footer,
        "handle": handle,
    }


def render(props, work_dir):
    """FoodReelEdit → reel.mp4 (소리 크기 -14 LUFS). 돌려주는 값: 경로."""
    npx = shutil.which("npx")

    if not npx:
        raise RuntimeError("Node.js(npx)가 없습니다.")

    props_path = os.path.abspath(os.path.join(work_dir, "reel_props.json"))
    raw = os.path.abspath(os.path.join(work_dir, "reel_raw.mp4"))
    out = os.path.abspath(os.path.join(work_dir, "reel.mp4"))
    save_json(props_path, props)
    command = [npx, "remotion", "render", "src/index.ts", "FoodReelEdit", raw, f"--props={props_path}",
               "--log=error", "--timeout=120000", "--crf=23"]

    for attempt in range(2):
        result = subprocess.run(command, cwd=VIDEO_PROJECT_DIR, capture_output=True, text=True,
                                encoding="utf-8", errors="ignore", timeout=1800)
        if result.returncode == 0:
            break

    if result.returncode != 0:
        raise RuntimeError(f"릴스 렌더링 실패: {(result.stderr or result.stdout).strip()[-1500:]}")

    run_ffmpeg(["-i", raw, "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
                "-ar", "48000", "-movflags", "+faststart", out])
    os.remove(raw)
    return out


def make_reel(post, text, video, work_dir, footer, handle):
    """원본 영상(download_video 결과)으로 릴스를 만든다. 돌려주는 값: (reel.mp4 경로, 계획)."""
    prepare_reel_media(video)
    sheets, step = scene_sheets(video, work_dir)
    content = plan(post, text, sheets, step, video["duration"])
    save_json(os.path.join(work_dir, "reel_plan.json"), content)
    print(f"릴스 대사 {len(content['lines'])}줄")

    voices = narrate(content, os.path.join(video["dir"], "voice"))
    props = timeline(content, voices, video, footer, handle)
    path = render(props, work_dir)
    print(f"릴스 렌더링 완료: {path} ({props['lines'][-1]['from'] + props['lines'][-1]['duration']:.1f}초)")
    return path, content
