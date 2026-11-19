import { loadFont } from "@remotion/google-fonts/NotoSansKR";

// 본문 글꼴. 제목 명조(NotoSerifKR)는 cards/Cards.tsx에서 불러온다.
export const { fontFamily } = loadFont("normal", {
  weights: ["500", "700", "900"],
  subsets: ["korean", "latin"],
});
