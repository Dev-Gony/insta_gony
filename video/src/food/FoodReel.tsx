import { loadFont as loadDisplay } from "@remotion/google-fonts/BlackHanSans";
import type { CalculateMetadataFunction } from "remotion";
import { AbsoluteFill, OffthreadVideo, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { z } from "zod";
import { fontFamily as sans } from "../theme";

// 얌얌고니 릴스: 블로그에 올린 실제 촬영 영상(대개 정사각형)을 1080x1920 세로로.
// 가운데 영상, 위에 표지와 같은 흰 굵은 2줄 제목, 아래에 블로그 안내. 빈 곳은 같은 영상을 흐리게 깐다.

const { fontFamily: display } = loadDisplay("normal", { weights: ["400"], subsets: ["korean", "latin"] });

export const foodReelSchema = z.object({
  // video/public 아래 경로 (videos/<글번호>/01.mp4)
  video: z.string(),
  // 영상 길이(초). 릴스는 90초까지만 쓴다.
  duration: z.number(),
  width: z.number(),
  height: z.number(),
  title: z.string(),
  footer: z.string(),
  handle: z.string(),
});

export type FoodReelProps = z.infer<typeof foodReelSchema>;

const FPS = 30;
const W = 1080;
const H = 1920;
const SIDE = 64;
const ink = "#141210";

export const calculateFoodReelMetadata: CalculateMetadataFunction<FoodReelProps> = ({ props }) => {
  return { durationInFrames: Math.max(1, Math.floor(Math.min(props.duration, 90) * FPS)), fps: FPS };
};

const fitSize = (text: string, max: number, width = W - SIDE * 2) => {
  const units = (line: string) => [...line].reduce((sum, char) => sum + (char === " " ? 0.45 : 1), 0);
  const longest = Math.max(...text.split("\n").map(units), 1);
  return Math.min(max, Math.floor(width / (longest * 0.98)));
};

export const FoodReel: React.FC<FoodReelProps> = (props) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const src = staticFile(props.video);

  // 영상 비율대로 가운데 상자 크기 (가로는 꽉, 세로는 최대 1300)
  const boxHeight = Math.min(1300, Math.round((W * props.height) / props.width));
  const boxTop = Math.round((H - boxHeight) / 2) + 40;
  const size = fitSize(props.title, 150);

  // 처음 0.4초 동안 제목이 살짝 올라오며 나타남
  const appear = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  // 마지막 0.5초 페이드아웃
  const fadeOut = interpolate(frame, [durationInFrames - 15, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
  });

  return (
    <AbsoluteFill style={{ backgroundColor: ink, opacity: fadeOut }}>
      {/* 흐린 배경 */}
      <AbsoluteFill style={{ overflow: "hidden" }}>
        <OffthreadVideo
          src={src}
          muted
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            filter: "blur(40px) brightness(0.45)",
            transform: "scale(1.2)",
          }}
        />
      </AbsoluteFill>

      {/* 가운데 영상 (소리는 이 영상 것만) */}
      <div style={{ position: "absolute", top: boxTop, left: 0, width: W, height: boxHeight, overflow: "hidden" }}>
        <OffthreadVideo src={src} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>

      {/* 위: 제목 */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: SIDE,
          right: SIDE,
          height: boxTop,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          opacity: appear,
          transform: `translateY(${(1 - appear) * 24}px)`,
        }}
      >
        <div
          style={{
            fontFamily: display,
            fontSize: size,
            lineHeight: 1.2,
            color: "#FFFFFF",
            WebkitTextStroke: `${Math.max(6, Math.round(size / 10))}px ${ink}`,
            paintOrder: "stroke fill",
            textShadow: "0 6px 26px rgba(0,0,0,0.45)",
            whiteSpace: "pre-line",
            textAlign: "center",
            letterSpacing: -1,
          }}
        >
          {props.title}
        </div>
      </div>

      {/* 아래: 안내 */}
      <div
        style={{
          position: "absolute",
          // 릴스 화면 아래쪽은 캡션·버튼에 가려지므로 영상 바로 아래에 둔다
          top: boxTop + boxHeight + 36,
          left: SIDE,
          right: SIDE,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 14,
          fontFamily: sans,
          fontWeight: 700,
          color: "#FFFFFF",
          textShadow: "0 2px 10px rgba(0,0,0,0.7)",
          textAlign: "center",
        }}
      >
        <div style={{ fontSize: 44 }}>{props.footer}</div>
        <div style={{ fontSize: 34, opacity: 0.85 }}>{props.handle}</div>
      </div>
    </AbsoluteFill>
  );
};
