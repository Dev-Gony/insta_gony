import { Composition } from "remotion";
import { Cards, calculateCardsMetadata } from "./cards/Cards";
import { cardsSchema } from "./cards/schema";

// 실제 렌더링은 cards.py가 --props로 내용을 넘겨준다. defaultProps는 Studio 미리보기용 샘플.
export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* 인스타그램 카드뉴스 (1080x1350, 프레임 하나 = 카드 한 장) */}
      <Composition
        id="Cards"
        component={Cards}
        schema={cardsSchema}
        calculateMetadata={calculateCardsMetadata}
        durationInFrames={4}
        fps={1}
        width={1080}
        height={1350}
        defaultProps={{
          masthead: "GONY BLOG",
          date: "2026.11.19",
          section: "여행",
          handle: "@gony",
          source: "blog.naver.com/gony",
          slides: [
            {
              type: "cover",
              label: "여행 · 제주",
              title: "제주 **3일**\n이렇게 돌았다",
              body: "동선 짜는 법부터\n꼭 가볼 곳까지",
            },
            {
              type: "story",
              label: "핵심만",
              title: "하루에 한 지역만\n천천히",
              items: ["첫날은 공항 근처 동쪽", "둘째 날은 서쪽 해안 도로", "마지막 날은 시내에서 쉬기"],
            },
            {
              type: "flow",
              label: "동선",
              title: "3일 코스",
              items: ["동쪽 해변", "서쪽 해안 도로", "시내 맛집"],
            },
            {
              type: "outro",
              label: "여러분 생각은?",
              title: "여러분의 제주\n최애 장소는\n어디인가요?",
              body: "전체 글은 블로그에서",
            },
          ],
        }}
      />
    </>
  );
};
