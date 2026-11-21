import { loadFont as loadDisplay } from "@remotion/google-fonts/BlackHanSans";
import type { CalculateMetadataFunction } from "remotion";
import { AbsoluteFill, Img, staticFile, useCurrentFrame } from "remotion";
import { fontFamily as sans } from "../theme";
import type { FoodCardsProps, FoodSlide } from "./schema";

// 얌얌고니 맛집 카드. 사진이 주인공이고 글씨는 사진 위에 얹는다.
// 지금 피드(사진 + 흰 굵은 2줄 제목)를 그대로 잇고, 분홍(돼지 캐릭터)·노랑 강조로 고니 색을 낸다.
// 프레임 하나 = 카드 한 장 (fps 1, 길이 = 장 수).

const { fontFamily: display } = loadDisplay("normal", { weights: ["400"], subsets: ["korean", "latin"] });

const color = {
  pink: "#FF6FA3",
  pinkSoft: "#FFE3EE",
  yellow: "#FFE14D",
  ink: "#17120F",
  white: "#FFFFFF",
  muted: "#6B625D",
};

const W = 1080;
const H = 1350;
const SIDE = 72;

export const calculateFoodCardsMetadata: CalculateMetadataFunction<FoodCardsProps> = ({ props }) => {
  return { durationInFrames: Math.max(props.slides.length, 1) };
};

// 흰 글씨 + 검은 테두리 (지금 피드 표지와 같은 느낌)
const outlined = (size: number): React.CSSProperties => ({
  fontFamily: display,
  fontSize: size,
  lineHeight: 1.18,
  color: color.white,
  WebkitTextStroke: `${Math.round(size / 9)}px ${color.ink}`,
  paintOrder: "stroke fill",
  textShadow: "0 6px 24px rgba(0,0,0,0.35)",
  wordBreak: "keep-all",
  whiteSpace: "pre-line",
  letterSpacing: -1,
});

// **강조** 부분만 노란색
const Marked: React.FC<{ text: string; mark?: string }> = ({ text, mark = color.yellow }) => (
  <>
    {text.split("**").map((part, index) =>
      index % 2 === 1 ? (
        <span key={index} style={{ color: mark }}>
          {part}
        </span>
      ) : (
        part
      ),
    )}
  </>
);

const Photo: React.FC<{ src: string; blur?: number; dim?: number }> = ({ src, blur = 0, dim = 0 }) => (
  <AbsoluteFill>
    <Img
      src={staticFile(src)}
      style={{
        width: "100%",
        height: "100%",
        objectFit: "cover",
        filter: blur ? `blur(${blur}px)` : undefined,
        transform: blur ? "scale(1.12)" : undefined,
      }}
    />
    {dim ? <AbsoluteFill style={{ backgroundColor: `rgba(0,0,0,${dim})` }} /> : null}
  </AbsoluteFill>
);

const Shade: React.FC<{ from?: number; strength?: number }> = ({ from = 45, strength = 0.78 }) => (
  <AbsoluteFill
    style={{
      background: `linear-gradient(180deg, rgba(0,0,0,0.28) 0%, rgba(0,0,0,0) 16%, rgba(0,0,0,0) ${from}%, rgba(0,0,0,${strength}) 100%)`,
    }}
  />
);

// 위쪽 줄: 왼쪽 분홍 이름표, 오른쪽 쪽수
const TopBar: React.FC<{ masthead: string; index: number; total: number }> = ({ masthead, index, total }) => (
  <div
    style={{
      position: "absolute",
      top: 56,
      left: SIDE,
      right: SIDE,
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
    }}
  >
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "12px 26px 12px 18px",
        borderRadius: 999,
        backgroundColor: color.pink,
        color: color.white,
        fontFamily: display,
        fontSize: 34,
        boxShadow: "0 6px 18px rgba(0,0,0,0.25)",
      }}
    >
      <Snout />
      {masthead}
    </div>
    <div
      style={{
        padding: "10px 22px",
        borderRadius: 999,
        backgroundColor: "rgba(0,0,0,0.45)",
        color: color.white,
        fontFamily: sans,
        fontWeight: 700,
        fontSize: 28,
        letterSpacing: 1,
      }}
    >
      {index + 1} / {total}
    </div>
  </div>
);

// 돼지 코 (캐릭터 표시)
const Snout: React.FC<{ size?: number }> = ({ size = 34 }) => (
  <div
    style={{
      width: size,
      height: size * 0.78,
      borderRadius: "50%",
      backgroundColor: color.pinkSoft,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      gap: size * 0.16,
    }}
  >
    <div style={{ width: size * 0.16, height: size * 0.26, borderRadius: "50%", backgroundColor: color.pink }} />
    <div style={{ width: size * 0.16, height: size * 0.26, borderRadius: "50%", backgroundColor: color.pink }} />
  </div>
);

const Pill: React.FC<{ text: string; bg?: string; fg?: string; size?: number }> = ({
  text,
  bg = color.yellow,
  fg = color.ink,
  size = 40,
}) => (
  <div
    style={{
      display: "inline-block",
      padding: `${size * 0.28}px ${size * 0.7}px`,
      borderRadius: 999,
      backgroundColor: bg,
      color: fg,
      fontFamily: display,
      fontSize: size,
      boxShadow: "0 8px 22px rgba(0,0,0,0.25)",
    }}
  >
    {text}
  </div>
);

const Cover: React.FC<{ slide: FoodSlide; handle: string }> = ({ slide, handle }) => (
  <>
    <Photo src={slide.photo} />
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at center, rgba(0,0,0,0.30) 0%, rgba(0,0,0,0.05) 70%)" }} />
    <Shade from={70} strength={0.6} />
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", padding: `0 ${SIDE}px` }}>
      {slide.label ? (
        <div style={{ marginBottom: 34, transform: "rotate(-3deg)" }}>
          <Pill text={slide.label} size={46} />
        </div>
      ) : null}
      <div style={{ ...outlined(132), textAlign: "center" }}>
        <Marked text={slide.title} />
      </div>
    </AbsoluteFill>
    <div
      style={{
        position: "absolute",
        bottom: 64,
        left: SIDE,
        right: SIDE,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        color: color.white,
        fontFamily: sans,
        fontWeight: 700,
        fontSize: 30,
        textShadow: "0 2px 10px rgba(0,0,0,0.6)",
      }}
    >
      <div>{handle}</div>
      <div>넘겨서 보기 →</div>
    </div>
  </>
);

const PhotoSlide: React.FC<{ slide: FoodSlide }> = ({ slide }) => (
  <>
    <Photo src={slide.photo} />
    <Shade from={50} strength={0.82} />
    <div style={{ position: "absolute", left: SIDE, right: SIDE, bottom: 92 }}>
      <div style={{ width: 70, height: 10, borderRadius: 5, backgroundColor: color.pink, marginBottom: 30 }} />
      <div style={{ ...outlined(84), WebkitTextStroke: `6px ${color.ink}` }}>
        <Marked text={slide.title} />
      </div>
      {slide.body ? (
        <div
          style={{
            marginTop: 24,
            fontFamily: sans,
            fontWeight: 700,
            fontSize: 40,
            lineHeight: 1.45,
            color: "rgba(255,255,255,0.94)",
            textShadow: "0 2px 12px rgba(0,0,0,0.7)",
            wordBreak: "keep-all",
          }}
        >
          {slide.body}
        </div>
      ) : null}
    </div>
  </>
);

const split = (item: string) => {
  const [left, ...rest] = item.split("|");
  return [left.trim(), rest.join("|").trim()];
};

const MenuSlide: React.FC<{ slide: FoodSlide }> = ({ slide }) => (
  <>
    <Photo src={slide.photo} blur={26} dim={0.45} />
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", padding: `150px ${SIDE}px 90px` }}>
      <div
        style={{
          width: "100%",
          borderRadius: 44,
          backgroundColor: color.white,
          padding: "60px 60px 52px",
          boxShadow: "0 24px 60px rgba(0,0,0,0.35)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18, marginBottom: 34 }}>
          <Snout size={54} />
          <div style={{ fontFamily: display, fontSize: 72, color: color.ink }}>{slide.title || "메뉴판"}</div>
        </div>
        {slide.items.map((item, index) => {
          const [rawName, price] = split(item);
          const picked = rawName.startsWith("★");
          const name = rawName.replace(/^★\s*/, "");

          return (
            <div
              key={index}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 18,
                padding: "20px 22px",
                marginTop: 8,
                borderRadius: 20,
                backgroundColor: picked ? color.yellow : "transparent",
                fontFamily: sans,
                fontSize: 40,
                color: color.ink,
              }}
            >
              <div style={{ fontWeight: picked ? 900 : 700, whiteSpace: "nowrap" }}>
                {picked ? "★ " : ""}
                {name}
              </div>
              <div style={{ flex: 1, borderBottom: `3px dotted rgba(23,18,15,0.28)`, transform: "translateY(6px)" }} />
              <div style={{ fontWeight: 900, whiteSpace: "nowrap" }}>{price}</div>
            </div>
          );
        })}
        {slide.items.some((item) => item.startsWith("★")) ? (
          <div style={{ marginTop: 26, fontFamily: sans, fontWeight: 700, fontSize: 28, color: color.muted }}>
            ★ 고니가 먹은 메뉴
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  </>
);

const InfoSlide: React.FC<{ slide: FoodSlide }> = ({ slide }) => (
  <>
    <div style={{ position: "absolute", top: 0, left: 0, width: W, height: H * 0.46, overflow: "hidden" }}>
      <Photo src={slide.photo} />
      <Shade from={60} strength={0.35} />
    </div>
    <div
      style={{
        position: "absolute",
        top: H * 0.42,
        left: 0,
        width: W,
        height: H * 0.58,
        backgroundColor: color.white,
        borderRadius: "48px 48px 0 0",
        padding: `66px ${SIDE}px 0`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 20, marginBottom: 38 }}>
        <Bookmark />
        <div style={{ fontFamily: display, fontSize: 70, color: color.ink }}>{slide.title || "저장해두고 가기"}</div>
      </div>
      {slide.items.map((item, index) => {
        const [label, value] = split(item);

        return (
          <div key={index} style={{ display: "flex", alignItems: "flex-start", gap: 26, marginTop: 22 }}>
            <div
              style={{
                flexShrink: 0,
                minWidth: 120,
                textAlign: "center",
                padding: "8px 18px",
                borderRadius: 14,
                backgroundColor: color.pinkSoft,
                color: color.pink,
                fontFamily: display,
                fontSize: 34,
              }}
            >
              {label}
            </div>
            <div
              style={{
                fontFamily: sans,
                fontWeight: 700,
                fontSize: 38,
                lineHeight: 1.4,
                color: color.ink,
                wordBreak: "keep-all",
                paddingTop: 4,
              }}
            >
              {value}
            </div>
          </div>
        );
      })}
    </div>
  </>
);

const Bookmark: React.FC = () => (
  <div style={{ position: "relative", width: 44, height: 58, backgroundColor: color.pink, borderRadius: "8px 8px 0 0" }}>
    <div
      style={{
        position: "absolute",
        bottom: -1,
        left: 0,
        width: 0,
        height: 0,
        borderLeft: "22px solid transparent",
        borderRight: "22px solid transparent",
        borderBottom: `18px solid ${color.white}`,
      }}
    />
  </div>
);

const Outro: React.FC<{ slide: FoodSlide; handle: string }> = ({ slide, handle }) => (
  <>
    <Photo src={slide.photo} dim={0.5} />
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", padding: `0 ${SIDE}px` }}>
      <Pill text="댓글로 알려주세요" bg={color.pink} fg={color.white} size={40} />
      <div style={{ ...outlined(100), textAlign: "center", marginTop: 40 }}>
        <Marked text={slide.title} />
      </div>
      {slide.body ? (
        <div
          style={{
            marginTop: 40,
            fontFamily: sans,
            fontWeight: 700,
            fontSize: 38,
            color: color.white,
            textShadow: "0 2px 12px rgba(0,0,0,0.7)",
          }}
        >
          {slide.body}
        </div>
      ) : null}
    </AbsoluteFill>
    <div
      style={{
        position: "absolute",
        bottom: 70,
        left: SIDE,
        right: SIDE,
        display: "flex",
        justifyContent: "center",
        gap: 18,
      }}
    >
      {["저장", "공유", `팔로우 ${handle}`].map((text) => (
        <div
          key={text}
          style={{
            padding: "14px 28px",
            borderRadius: 999,
            border: `3px solid ${color.white}`,
            color: color.white,
            fontFamily: sans,
            fontWeight: 900,
            fontSize: 30,
          }}
        >
          {text}
        </div>
      ))}
    </div>
  </>
);

export const FoodCards: React.FC<FoodCardsProps> = (props) => {
  const frame = useCurrentFrame();
  const index = Math.min(frame, props.slides.length - 1);
  const slide = props.slides[index];

  return (
    <AbsoluteFill style={{ backgroundColor: color.ink }}>
      {slide.type === "cover" ? <Cover slide={slide} handle={props.handle} /> : null}
      {slide.type === "photo" ? <PhotoSlide slide={slide} /> : null}
      {slide.type === "menu" ? <MenuSlide slide={slide} /> : null}
      {slide.type === "info" ? <InfoSlide slide={slide} /> : null}
      {slide.type === "outro" ? <Outro slide={slide} handle={props.handle} /> : null}
      {slide.type !== "cover" ? <TopBar masthead={props.masthead} index={index} total={props.slides.length} /> : null}
    </AbsoluteFill>
  );
};
