import { loadFont as loadDisplay } from "@remotion/google-fonts/BlackHanSans";
import type { CalculateMetadataFunction } from "remotion";
import { AbsoluteFill, Img, staticFile, useCurrentFrame } from "remotion";
import { fontFamily as sans } from "../theme";
import type { FoodCardsProps, FoodSlide } from "./schema";

// 얌얌고니 맛집 캐러셀.
// 레퍼런스(서울더핫플, _mukpunzel, 김밥대장 — 2026-11-21 직접 넘겨 봄)처럼
// 표지만 사진 + 흰 굵은 2줄 제목, 중간 장은 글씨 없는 사진, 마지막 장은 어둡게 깐 사진 + 질문 한 줄.
// 표지 제목 위치·글꼴은 지금 얌얌고니 피드(가운데, 흰 글씨 검은 테두리, 아래 작게 블로그 이름)를 잇는다.
// 프레임 하나 = 카드 한 장 (fps 1, 길이 = 장 수).

const { fontFamily: display } = loadDisplay("normal", { weights: ["400"], subsets: ["korean", "latin"] });

const W = 1080;
const SIDE = 72;
const ink = "#141210";

export const calculateFoodCardsMetadata: CalculateMetadataFunction<FoodCardsProps> = ({ props }) => {
  return { durationInFrames: Math.max(props.slides.length, 1) };
};

// 흰 글씨 + 검은 테두리
const outlined = (size: number): React.CSSProperties => ({
  fontFamily: display,
  fontSize: size,
  lineHeight: 1.22,
  color: "#FFFFFF",
  WebkitTextStroke: `${Math.max(6, Math.round(size / 10))}px ${ink}`,
  paintOrder: "stroke fill",
  textShadow: "0 6px 26px rgba(0,0,0,0.45)",
  wordBreak: "keep-all",
  whiteSpace: "pre-line",
  textAlign: "center",
  letterSpacing: -1,
});

// 가장 긴 줄이 카드 폭에 들어가게 글씨 크기를 정한다 (한글 한 글자 ≈ 글씨 크기).
const fitSize = (text: string, max: number, width = W - SIDE * 2) => {
  // 띄어쓰기는 반 글자로 센다
  const units = (line: string) => [...line].reduce((sum, char) => sum + (char === " " ? 0.45 : 1), 0);
  const longest = Math.max(...text.split("\n").map(units), 1);
  return Math.min(max, Math.floor(width / (longest * 0.98)));
};

const Photo: React.FC<{ src: string; dim?: number }> = ({ src, dim = 0 }) => (
  <AbsoluteFill>
    <Img src={staticFile(src)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
    {dim ? <AbsoluteFill style={{ backgroundColor: `rgba(0,0,0,${dim})` }} /> : null}
  </AbsoluteFill>
);

const Small: React.FC<{ text: string; bottom: number }> = ({ text, bottom }) => (
  <div
    style={{
      position: "absolute",
      bottom,
      left: SIDE,
      right: SIDE,
      textAlign: "center",
      fontFamily: sans,
      fontWeight: 700,
      fontSize: 30,
      color: "rgba(255,255,255,0.92)",
      textShadow: "0 2px 10px rgba(0,0,0,0.75)",
    }}
  >
    {text}
  </div>
);

const Cover: React.FC<{ slide: FoodSlide; footer: string }> = ({ slide, footer }) => (
  <>
    <Photo src={slide.photo} />
    {/* 제목 뒤만 살짝 어둡게 (사진은 최대한 그대로) */}
    <AbsoluteFill style={{ background: "radial-gradient(ellipse 70% 30% at 50% 50%, rgba(0,0,0,0.32), rgba(0,0,0,0))" }} />
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", padding: `0 ${SIDE}px` }}>
      <div style={outlined(fitSize(slide.title, 150))}>{slide.title}</div>
    </AbsoluteFill>
    {footer ? <Small text={footer} bottom={58} /> : null}
  </>
);

const Outro: React.FC<{ slide: FoodSlide; handle: string }> = ({ slide, handle }) => (
  <>
    <Photo src={slide.photo} dim={0.62} />
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", padding: `0 ${SIDE}px` }}>
      <div style={outlined(fitSize(slide.title, 120))}>{slide.title}</div>
      <div
        style={{
          marginTop: 46,
          textAlign: "center",
          fontFamily: sans,
          fontWeight: 700,
          fontSize: 34,
          lineHeight: 1.5,
          color: "#FFFFFF",
          textShadow: "0 2px 12px rgba(0,0,0,0.7)",
        }}
      >
        {handle} 팔로우하고
        <br />
        다음 맛집도 같이 가요
      </div>
    </AbsoluteFill>
  </>
);

export const FoodCards: React.FC<FoodCardsProps> = (props) => {
  const frame = useCurrentFrame();
  const slide = props.slides[Math.min(frame, props.slides.length - 1)];

  return (
    <AbsoluteFill style={{ backgroundColor: ink }}>
      {slide.type === "cover" ? <Cover slide={slide} footer={props.footer} /> : null}
      {slide.type === "photo" ? <Photo src={slide.photo} /> : null}
      {slide.type === "outro" ? <Outro slide={slide} handle={props.handle} /> : null}
    </AbsoluteFill>
  );
};
