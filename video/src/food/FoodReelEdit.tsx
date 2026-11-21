import { loadFont as loadDisplay } from "@remotion/google-fonts/BlackHanSans";
import type { CalculateMetadataFunction } from "remotion";
import { AbsoluteFill, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";
import { z } from "zod";
import { fontFamily as sans } from "../theme";

// 얌얌고니 릴스 (편집본): 블로그 원본 영상을 1.5~2초 컷으로 잘라 순서를 바꾸고,
// 컷마다 큰 자막(강조 단어 노랑) + 줌인/줌아웃, 마지막 3초는 댓글 키워드 CTA.
// 기준: ~/.claude/youtube/reels.md (첫 1.5초는 움직이는 음식 컷, 1.5~2초마다 변화, CTA 하나).

const { fontFamily: display } = loadDisplay("normal", { weights: ["400"], subsets: ["korean", "latin"] });

export const reelSegmentSchema = z.object({
  // 원본 영상에서 쓸 구간(초)
  start: z.number(),
  end: z.number(),
  // 자막. **강조** 부분은 노랑. 줄바꿈 가능
  text: z.string(),
});

export const foodReelEditSchema = z.object({
  video: z.string(),
  width: z.number(),
  height: z.number(),
  segments: z.array(reelSegmentSchema),
  // 마지막 CTA 장면
  cta: z.object({ start: z.number(), seconds: z.number(), text: z.string(), sub: z.string() }),
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

const frames = (seconds: number) => Math.round(seconds * FPS);

export const calculateFoodReelEditMetadata: CalculateMetadataFunction<FoodReelEditProps> = ({ props }) => {
  const total = props.segments.reduce((sum, s) => sum + frames(s.end - s.start), 0) + frames(props.cta.seconds);
  return { durationInFrames: Math.max(1, total), fps: FPS };
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

// 한 컷: 원본 구간 + 줌(짝수 컷 줌인, 홀수 컷 줌아웃) + 소리 앞뒤 살짝 페이드
const Clip: React.FC<{ src: string; start: number; length: number; zoomIn: boolean; dim?: number }> = ({
  src,
  start,
  length,
  zoomIn,
  dim = 0,
}) => {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, length], zoomIn ? [1.0, 1.14] : [1.14, 1.0], { extrapolateRight: "clamp" });
  const volume = (f: number) => interpolate(f, [0, 3, length - 3, length], [0, 0.9, 0.9, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <OffthreadVideo
        src={src}
        startFrom={frames(start)}
        volume={volume}
        style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${scale})` }}
      />
      {dim ? <AbsoluteFill style={{ backgroundColor: `rgba(0,0,0,${dim})` }} /> : null}
    </AbsoluteFill>
  );
};

const Backdrop: React.FC<{ src: string; start: number }> = ({ src, start }) => (
  <AbsoluteFill style={{ overflow: "hidden" }}>
    <OffthreadVideo
      src={src}
      startFrom={frames(start)}
      muted
      style={{ width: "100%", height: "100%", objectFit: "cover", filter: "blur(40px) brightness(0.42)", transform: "scale(1.2)" }}
    />
  </AbsoluteFill>
);

const Caption: React.FC<{ text: string; top: number; height: number }> = ({ text, top, height }) => {
  const frame = useCurrentFrame();
  // 컷이 바뀔 때 자막이 톡 튀어나옴 (0.2초)
  const pop = interpolate(frame, [0, 6], [0.86, 1], { extrapolateRight: "clamp" });

  return (
    <div
      style={{
        position: "absolute",
        top,
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
  const boxHeight = Math.min(1240, Math.round((W * props.height) / props.width));
  const boxTop = Math.round((H - boxHeight) / 2) - 10;
  let cursor = 0;

  return (
    <AbsoluteFill style={{ backgroundColor: ink }}>
      {props.segments.map((segment, index) => {
        const length = frames(segment.end - segment.start);
        const from = cursor;
        cursor += length;

        return (
          <Sequence key={index} from={from} durationInFrames={length}>
            <Backdrop src={src} start={segment.start} />
            <div style={{ position: "absolute", top: boxTop, left: 0, width: W, height: boxHeight, overflow: "hidden" }}>
              <Clip src={src} start={segment.start} length={length} zoomIn={index % 2 === 0} />
            </div>
            <Caption text={segment.text} top={0} height={boxTop} />
            <div
              style={{
                position: "absolute",
                top: boxTop + boxHeight + 34,
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
        );
      })}

      {/* 마지막: 댓글 키워드 CTA (화면 전체를 어둡게 깔고 가운데 큰 글씨) */}
      <Sequence from={cursor} durationInFrames={frames(props.cta.seconds)}>
        <Backdrop src={src} start={props.cta.start} />
        <div style={{ position: "absolute", top: boxTop, left: 0, width: W, height: boxHeight, overflow: "hidden" }}>
          <Clip src={src} start={props.cta.start} length={frames(props.cta.seconds)} zoomIn dim={0.55} />
        </div>
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
