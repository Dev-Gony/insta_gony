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
MIN_RATE = 0.5          # 원본이 짧을 때 느리게 재생하는 한계 (멈춘 음식 장면이라 0.5배도 어색하지 않다)
# 속삭이는 목소리(1.12배 뒤)는 1초에 5.5음절쯤
SYLLABLES_PER_SECOND = 5.5


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

구성 (대사 수와 길이는 영상 길이에 맞춘다 — 아래 사용자 메시지의 '말 길이 목표'를 넘기지 않는다. 속삭이는 목소리는 1초에 5.5음절):
1. 첫 줄 = 훅. 가장 먹음직스럽고 움직임이 있는 장면(젓가락으로 들기 등) + 이 집을 한마디로 (12음절 이내).
2. 가게 이름·위치·시간 → 대표 메뉴·가격 → 음식 모습 → 곁들이·무료 → 맛 표현 순서로 이야기가 되게.
3. 마지막 줄 = 댓글을 부르는 질문 하나 (예: "여러분은 쌈파예요, 소스파예요?"). 구독·좋아요 부탁 금지.
- text: 화면 자막. 대사와 같은 문장, 강조할 단어 하나를 **이렇게**. 숫자는 숫자로(58,000원).
- speech: 읽을 문장. 숫자는 한글로(오만 팔천 원), 기호 없이.
- ranges: 그 줄 동안 보여줄 원본 구간 1~2개 [시작초, 끝초]. 한 줄의 구간 합은 그 줄을 읽는 시간(speech 음절 수 ÷ 5.5초)의 0.6배 이상.
  구간 안에 다른 장면(다음 메뉴, 다른 접시)이 섞이지 않게 장면이 바뀌는 시각 앞에서 끊는다.
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


def target_seconds(duration):
    """영상이 짧으면 말도 짧게: 원본 길이의 1.4배(0.7배 느린 재생까지)와 26초 중 작은 쪽, 최소 10초."""
    return max(10.0, min(26.0, duration * 1.4))


def target_lines(duration):
    seconds = target_seconds(duration)
    return "4~5" if seconds < 16 else "5~6" if seconds < 21 else "6~8"


def syllables(text):
    import re

    return max(1, len(re.findall(r"[가-힣0-9A-Za-z]", text)))


def plan(post, text, sheets, step, duration):
    prompt = "\n".join(
        [
            "아래 블로그 후기와 영상 장면 시트로 릴스를 짜줘.",
            "",
            f"영상 길이: {duration:.1f}초. 장면 시트는 {step}초마다 한 칸이고 칸 위에 시작 시각이 적혀 있다.",
            f"말 길이 목표: 대사 전체를 읽는 시간 {target_seconds(duration):.0f}초 이하 "
            f"(= 전체 음절 {int(target_seconds(duration) * SYLLABLES_PER_SECOND)}개 이하), 대사 {target_lines(duration)}줄.",
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

def _silences(path, noise="-38dB", minimum=0.3):
    """(시작, 끝) 무음 구간 목록."""
    import re

    result = subprocess.run(
        [ffmpeg_exe(), "-i", path, "-af", f"silencedetect=noise={noise}:d={minimum}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", result.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", result.stderr)]
    return list(zip(starts, ends))


def _split_points(path, weights):
    """한 번에 읽은 음성을 줄마다 나눌 자리(초).

    줄마다 음절 수로 '여기쯤 끝나야 한다'는 위치를 계산하고, 그 위치에 가장 가까운 쉼(앞에서부터 차례로)을 고른다.
    문장 안의 짧은 쉼을 줄 경계로 잘못 잡지 않게, 길이가 비슷한 쉼 중에서도 예상 위치에 가까운 것을 쓴다.
    """
    total = wav_seconds(path)
    count = len(weights)
    expected, acc = [], 0.0

    for weight in weights[:-1]:
        acc += weight
        expected.append(total * acc / sum(weights))

    for noise in ("-38dB", "-34dB", "-42dB", "-30dB"):
        gaps = [((start + end) / 2, end - start) for start, end in _silences(path, noise, 0.25) if 0.2 < start and end < total - 0.2]

        if len(gaps) < count - 1:
            continue

        points, last = [], 0.0

        for index, target in enumerate(expected):
            remaining = count - 1 - index
            options = [gap for gap in gaps if gap[0] > last + 0.4]

            if len(options) < remaining:
                break

            # 남은 줄 수만큼 쉼을 남겨 두고, 예상 위치에 가깝고 긴 쉼일수록 좋게
            usable = options[: len(options) - remaining + 1]
            best = min(usable, key=lambda gap: abs(gap[0] - target) - 0.6 * gap[1])
            points.append(best[0])
            last = best[0]
        else:
            return points

    raise RuntimeError(f"내레이션을 {count}줄로 나눌 쉼을 찾지 못했습니다.")


def _pieces_ok(pieces, weights, total):
    """나눈 조각 길이가 음절 수로 예상한 길이와 너무 다르면 잘못 나눈 것."""
    for (start, end), weight in zip(pieces, weights):
        expected = total * weight / sum(weights)
        ratio = (min(end, total) - start) / expected

        if not 0.5 <= ratio <= 1.8:
            return False

    return True


def narrate(content, voice_dir):
    """대사 전체를 TTS 한 번으로 읽고(무료 한도 아끼기) 줄 사이 쉼에서 잘라 나눈다.

    줄마다: 앞뒤 빈 소리 자르고 1.12배. 나누기가 안 되면 줄마다 따로 부른다.
    돌려주는 값: 줄마다 (파일, 초).
    """
    os.makedirs(voice_dir, exist_ok=True)
    lines = content["lines"]
    whole = os.path.join(voice_dir, "whole.wav")
    script = "\n".join(f"{line['speech'].rstrip('.')}." for line in lines)
    style = tts.WHISPER_STYLE.replace(
        "문장만 읽고 다른 말은 하지 마세요: ",
        "줄마다 한 문장이고, 줄과 줄 사이에는 1초쯤 쉬어 주세요. 문장만 읽고 다른 말은 하지 마세요:\n",
    )
    tts.synthesize(script, whole, style=style)

    weights = [syllables(line["speech"]) for line in lines]
    total = wav_seconds(whole)

    try:
        cuts = _split_points(whole, weights)
        pieces = list(zip([0.0] + cuts, cuts + [total + 1]))

        if not _pieces_ok(pieces, weights, total):
            raise RuntimeError("나눈 길이가 대사 길이와 맞지 않습니다")
    except RuntimeError as error:
        print(f"{error} → 줄마다 따로 만듭니다.")
        pieces = None

    results = []
    trim = (
        "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
        f"silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse,atempo={VOICE_TEMPO}"
    )

    for index, line in enumerate(lines, start=1):
        path = os.path.join(voice_dir, f"{index:02d}.wav")

        if pieces:
            start, end = pieces[index - 1]
            run_ffmpeg(["-i", whole, "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-af", trim, path])
        else:
            raw = os.path.join(voice_dir, f"raw_{index:02d}.wav")
            tts.synthesize(line["speech"], raw)
            run_ffmpeg(["-i", raw, "-af", trim, path])
            os.remove(raw)

        results.append((path, wav_seconds(path)))

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

        # 원본이 너무 짧으면 먼저 느리게(최대 0.5배), 그래도 모자랄 때만 구간을 뒤로(안 되면 앞으로) 늘린다
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


def smooth_slow_cuts(props, video):
    """느리게 재생할 컷은 ffmpeg 움직임 보간(minterpolate)으로 미리 30fps 영상을 만들어 1배속으로 쓴다.

    Remotion에서 playbackRate로 늦추면 원본 프레임이 반복돼서(0.7배면 3프레임마다 한 번 멈춤) 화면이 덜컥거린다.
    (양재옥 릴스 11/22: 거의 모든 컷이 0.7배라 처음부터 끝까지 끊겨 보였음)
    """
    folder = os.path.join(video["dir"], "cuts")
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder, exist_ok=True)

    for index, cut in enumerate(props["cuts"]):
        rate = (cut["end"] - cut["start"]) / cut["duration"]

        if rate >= 0.97:
            continue

        name = f"{index:02d}.mp4"
        run_ffmpeg([
            "-ss", f"{cut['start']:.3f}", "-to", f"{cut['end']:.3f}", "-i", video["cfr"],
            "-vf", f"setpts=PTS/{rate:.4f},minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1",
            "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-g", "30",
            os.path.join(folder, name),
        ])
        cut["src"] = f"{video['public']}/cuts/{name}"
        cut["start"], cut["end"] = 0.0, cut["duration"]

    return props


def repeated_frame_ratio(path, crop=None):
    """앞 프레임과 거의 같은 프레임의 비율 (덜컥거림 검사)."""
    import re

    scale = f"crop={crop}," if crop else ""
    result = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", path, "-an", "-vf",
         f"{scale}scale=120:120,format=gray,signalstats,metadata=print:key=lavfi.signalstats.YDIF", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    values = [float(x) for x in re.findall(r"YDIF=([0-9.]+)", result.stderr)][1:]
    return sum(1 for value in values if value < 0.3) / max(1, len(values))


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
    props = smooth_slow_cuts(timeline(content, voices, video, footer, handle), video)

    # 보간으로 만든 컷이 덜컥거리지 않는지 (반복 프레임 10% 넘으면 실패)
    for cut in props["cuts"]:
        if cut.get("src"):
            ratio = repeated_frame_ratio(os.path.join(VIDEO_PROJECT_DIR, "public", cut["src"]))
            if ratio > 0.10:
                raise RuntimeError(f"느린 컷이 덜컥거립니다: {cut['src']} 반복 프레임 {ratio:.0%}")

    path = render(props, work_dir)
    print(f"릴스 렌더링 완료: {path} ({props['lines'][-1]['from'] + props['lines'][-1]['duration']:.1f}초)")
    return path, content
