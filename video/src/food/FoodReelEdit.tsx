import { loadFont as loadDisplay } from "@remotion/google-fonts/BlackHanSans";
import type { CalculateMetadataFunction } from "remotion";
import { AbsoluteFill, Audio, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { z } from "zod";
import { fontFamily as sans } from "../theme";

// 얌얌고니 릴스 (편집본).
// 레퍼런스(부산맛집여기 35.3만, _mukpunzel 155.5만 — 2026-11-21 직접 확인): 내레이션 + 말에 맞춰 바뀌는 작은 자막,
// 첫 장면만 큰 제목, 멈춘 장면은 3~4.5초씩. 원본 매장 소리는 컷과 상관없이 한 줄로 이어 깔고 내레이션 아래로 낮춘다.
// 영상 컷(cuts)과 대사(lines)는 따로 간다: 대사가 시작할 때 그 대사의 장면이 나오도록 cuts를 맞춰 둔다.

const { fontFamily: display } = loadDisplay("normal", { weights: ["400"], subsets: ["korean", "latin"] });

const seconds = z.number();

export const foodReelEditSchema = z.object({
  // 30fps 고정으로 다시 인코딩한 무음 영상, 원본에서 뗀 매장 소리
  video: z.string(),
  ambient: z.string(),
  width: z.number(),
  height: z.number(),
  // 영상 컷: 원본 [start, end]를 출력 [from, from+duration]에 (느리면 playbackRate < 1)
  cuts: z.array(z.object({ start: seconds, end: seconds, from: seconds, duration: seconds })),
  // 대사: 출력 from부터 duration 동안 자막, voice가 있으면 그 음성
  lines: z.array(z.object({ from: seconds, duration: seconds, text: z.string(), voice: z.string() })),
  // 첫 대사 동안 위쪽에 크게
  hook: z.string(),
  // 마지막 장면(댓글 키워드 CTA): from부터 끝까지 어둡게 깔고 가운데 큰 글씨
  cta: z.object({ from: seconds, text: z.string(), sub: z.string() }),
  footer: z.string(),
  handle: z.string(),
});

export type FoodReelEditProps = z.infer<typeof foodReelEditSchema>;

const FPS = 30;
const W = 1080;
const H = 1920;
const SIDE = 64;
const ink = "#141210";
const yellow = "#FFE14D";

const frames = (value: number) => Math.round(value * FPS);

export const calculateFoodReelEditMetadata: CalculateMetadataFunction<FoodReelEditProps> = ({ props }) => {
  const end = Math.max(
    ...props.cuts.map((cut) => cut.from + cut.duration),
    ...props.lines.map((line) => line.from + line.duration),
    1,
  );
  return { durationInFrames: frames(end), fps: FPS };
};

const Marked: React.FC<{ text: string }> = ({ text }) => (
  <>
    {text.split("**").map((part, index) =>
      index % 2 === 1 ? (
        <span key={index} style={{ color: yellow }}>
          {part}
        </span>
      ) : (
        part
      ),
    )}
  </>
);

const outlined = (size: number): React.CSSProperties => ({
  fontFamily: display,
  fontSize: size,
  lineHeight: 1.2,
  color: "#FFFFFF",
  WebkitTextStroke: `${Math.max(6, Math.round(size / 10))}px ${ink}`,
  paintOrder: "stroke fill",
  textShadow: "0 6px 26px rgba(0,0,0,0.5)",
  whiteSpace: "pre-line",
  textAlign: "center",
  letterSpacing: -1,
});

const fitSize = (text: string, max: number, width = W - SIDE * 2) => {
  const plain = text.replace(/\*\*/g, "");
  const units = (line: string) => [...line].reduce((sum, char) => sum + (char === " " ? 0.45 : 1), 0);
  const longest = Math.max(...plain.split("\n").map(units), 1);
  return Math.min(max, Math.floor(width / (longest * 0.98)));
};

// 한 컷: 흐린 배경 + 가운데 영상, 컷마다 번갈아 천천히 줌인/줌아웃
const Cut: React.FC<{
  src: string;
  start: number;
  end: number;
  duration: number;
  index: number;
  box: { top: number; height: number };
}> = ({ src, start, end, duration, index, box }) => {
  const frame = useCurrentFrame();
  const length = frames(duration);
  const zoomIn = index % 2 === 0;
  const scale = interpolate(frame, [0, length], zoomIn ? [1.0, 1.06] : [1.06, 1.0], { extrapolateRight: "clamp" });
  const rate = Math.max(0.5, Math.min(1, (end - start) / duration));

  return (
    <>
      <AbsoluteFill style={{ overflow: "hidden" }}>
        <OffthreadVideo
          src={src}
          startFrom={frames(start)}
          playbackRate={rate}
          muted
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            filter: "blur(40px) brightness(0.42)",
            transform: "scale(1.2)",
          }}
        />
      </AbsoluteFill>
      <div style={{ position: "absolute", top: box.top, left: 0, width: W, height: box.height, overflow: "hidden" }}>
        <OffthreadVideo
          src={src}
          startFrom={frames(start)}
          playbackRate={rate}
          muted
          style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${scale})` }}
        />
      </div>
    </>
  );
};

// 말에 맞춰 바뀌는 작은 자막 (강조 단어만 노랑)
const Subtitle: React.FC<{ text: string; top: number }> = ({ text, top }) => {
  const frame = useCurrentFrame();
  const appear = interpolate(frame, [0, 5], [0, 1], { extrapolateRight: "clamp" });

  return (
    <div
      style={{ position: "absolute", top, left: SIDE, right: SIDE, display: "flex", justifyContent: "center", opacity: appear }}
    >
      <div
        style={{
          fontFamily: sans,
          fontWeight: 900,
          fontSize: 58,
          lineHeight: 1.35,
          color: "#FFFFFF",
          WebkitTextStroke: `8px ${ink}`,
          paintOrder: "stroke fill",
          textShadow: "0 3px 14px rgba(0,0,0,0.55)",
          textAlign: "center",
          whiteSpace: "pre-line",
          letterSpacing: -0.5,
        }}
      >
        <Marked text={text} />
      </div>
    </div>
  );
};

const Hook: React.FC<{ text: string; height: number }> = ({ text, height }) => {
  const frame = useCurrentFrame();
  const pop = interpolate(frame, [0, 6], [0.88, 1], { extrapolateRight: "clamp" });

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: SIDE,
        right: SIDE,
        height,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div style={{ ...outlined(fitSize(text, 132)), transform: `scale(${pop})` }}>
        <Marked text={text} />
      </div>
    </div>
  );
};

export const FoodReelEdit: React.FC<FoodReelEditProps> = (props) => {
  const src = staticFile(props.video);
  const { durationInFrames: total } = useVideoConfig();
  const boxHeight = Math.min(1240, Math.round((W * props.height) / props.width));
  const box = { top: Math.round((H - boxHeight) / 2) - 10, height: boxHeight };
  const subtitleTop = box.top + Math.round(boxHeight * 0.7);
  const hasVoice = props.lines.some((line) => line.voice);
  const ambientLevel = hasVoice ? 0.18 : 0.85;
  const ctaFrom = frames(props.cta.from);

  return (
    <AbsoluteFill style={{ backgroundColor: ink }}>
      {/* 매장 소리: 한 줄로 이어서, 내레이션이 있으면 낮게 */}
      <Audio
        src={staticFile(props.ambient)}
        loop
        volume={(f) =>
          interpolate(f, [0, 9, total - 24, total], [0, ambientLevel, ambientLevel, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          })
        }
      />

      {props.cuts.map((cut, index) => (
        <Sequence key={`cut-${index}`} from={frames(cut.from)} durationInFrames={frames(cut.duration)}>
          <Cut src={src} start={cut.start} end={cut.end} duration={cut.duration} index={index} box={box} />
        </Sequence>
      ))}

      {/* 아래 안내 (CTA 전까지) */}
      <Sequence from={0} durationInFrames={Math.max(1, ctaFrom)}>
        <div
          style={{
            position: "absolute",
            top: box.top + box.height + 34,
            left: SIDE,
            right: SIDE,
            textAlign: "center",
            fontFamily: sans,
            fontWeight: 700,
            fontSize: 40,
            color: "#FFFFFF",
            textShadow: "0 2px 10px rgba(0,0,0,0.7)",
          }}
        >
          {props.footer}
          <div style={{ fontSize: 30, opacity: 0.8, marginTop: 10 }}>{props.handle}</div>
        </div>
      </Sequence>

      {props.lines.map((line, index) => (
        <Sequence key={`line-${index}`} from={frames(line.from)} durationInFrames={frames(line.duration)}>
          {line.voice ? <Audio src={staticFile(line.voice)} volume={1} /> : null}
          {index === 0 && props.hook ? <Hook text={props.hook} height={box.top} /> : null}
          {frames(line.from) < ctaFrom ? <Subtitle text={line.text} top={subtitleTop} /> : null}
        </Sequence>
      ))}

      {/* 마지막: 어둡게 깔고 댓글 키워드 CTA */}
      <Sequence from={ctaFrom} durationInFrames={Math.max(1, total - ctaFrom)}>
        <AbsoluteFill style={{ backgroundColor: "rgba(0,0,0,0.55)" }} />
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", padding: `0 ${SIDE}px` }}>
          <div style={outlined(fitSize(props.cta.text, 120))}>
            <Marked text={props.cta.text} />
          </div>
          <div
            style={{
              marginTop: 40,
              padding: "16px 34px",
              borderRadius: 999,
              backgroundColor: yellow,
              color: ink,
              fontFamily: display,
              fontSize: 46,
            }}
          >
            {props.cta.sub}
          </div>
        </AbsoluteFill>
      </Sequence>
    </AbsoluteFill>
  );
};
