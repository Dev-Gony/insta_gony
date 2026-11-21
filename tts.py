"""릴스 내레이션: Gemini TTS로 대사 한 줄마다 wav 파일을 만든다 (기본: 속삭이는 말투, 여성 목소리 Leda).

    python tts.py --lines lines.txt --out runtime/voice          # 한 줄에 대사 하나 → 01.wav, 02.wav ...
    python tts.py --text "한 줄" --out runtime/voice

컷마다 따로 만드는 이유: 컷이 시작할 때 그 컷의 대사가 시작되게 맞추려고 (한 번에 만들면 시점을 알 수 없다).

필요한 값: GEMINI_API_KEY (Google AI Studio 무료 한도, 결제 수단 연결 안 함 → 한도 초과는 실패)
"""

import argparse
import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import wave


MODEL = os.environ.get("GEMINI_TTS_MODEL") or "gemini-3.1-flash-tts-preview"
VOICE = os.environ.get("GEMINI_TTS_VOICE") or "Leda"

# 말투 지시. 대사 앞에 붙여 보낸다.
WHISPER_STYLE = (
    "다음 한국어 문장을 마이크 바로 앞에서 속삭이듯 읽어 주세요. "
    "숨이 살짝 섞인 작고 부드러운 목소리로, 친구에게 비밀 맛집을 알려 주듯 다정하게, "
    "너무 느리지 않게 자연스러운 속도로. 문장만 읽고 다른 말은 하지 마세요: "
)


def _key():
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()

    if not key:
        raise RuntimeError("GEMINI_API_KEY가 없습니다.")

    return key


def synthesize(text, path, voice=VOICE, style=WHISPER_STYLE, attempts=4):
    """text를 읽은 16bit mono wav를 path에 쓴다. 돌려주는 값: 길이(초)."""
    body = {
        "contents": [{"parts": [{"text": style + text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
        f"?key={urllib.parse.quote(_key())}"
    )

    for attempt in range(attempts):
        request = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST"
        )

        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as error:
            # 429(한도)·503(혼잡)은 기다렸다 다시. 다른 오류는 바로 실패.
            if error.code not in (429, 500, 503) or attempt == attempts - 1:
                raise RuntimeError(f"Gemini TTS 실패 {error.code}: {error.read().decode('utf-8', 'ignore')[:300]}") from None

            time.sleep(30 * (attempt + 1))

    inline = data["candidates"][0]["content"]["parts"][0]["inlineData"]
    rate = int((re.search(r"rate=(\d+)", inline["mimeType"]) or [None, 24000])[1])
    pcm = base64.b64decode(inline["data"])

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with wave.open(path, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(pcm)

    return len(pcm) / 2 / rate


def main():
    parser = argparse.ArgumentParser(description="Gemini TTS로 릴스 내레이션 만들기")
    parser.add_argument("--lines", help="한 줄에 대사 하나인 텍스트 파일")
    parser.add_argument("--text", help="대사 한 줄")
    parser.add_argument("--out", default="runtime/voice")
    parser.add_argument("--voice", default=VOICE)
    parser.add_argument("--plain", action="store_true", help="속삭임 지시 없이 보통 말투")
    args = parser.parse_args()

    lines = [args.text] if args.text else [
        line.strip() for line in open(args.lines, encoding="utf-8").read().splitlines() if line.strip()
    ]
    style = "다음 한국어 문장을 자연스럽게 읽어 주세요. 문장만 읽고 다른 말은 하지 마세요: " if args.plain else WHISPER_STYLE
    report = []

    for index, line in enumerate(lines, start=1):
        path = os.path.join(args.out, f"{index:02d}.wav")
        seconds = synthesize(line, path, voice=args.voice, style=style)
        report.append({"file": os.path.basename(path), "seconds": round(seconds, 2), "text": line})
        print(f"{index:02d}  {seconds:5.2f}s  {line}")
        # 무료 한도(분당 요청 수)를 넘지 않게 조금씩 쉰다
        time.sleep(6)

    with open(os.path.join(args.out, "voice.json"), "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
