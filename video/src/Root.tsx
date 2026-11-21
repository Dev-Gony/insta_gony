import { Composition } from "remotion";
import { Cards, calculateCardsMetadata } from "./cards/Cards";
import { cardsSchema } from "./cards/schema";
import { FoodCards, calculateFoodCardsMetadata } from "./food/FoodCards";
import { foodCardsSchema } from "./food/schema";
import { FoodReel, calculateFoodReelMetadata, foodReelSchema } from "./food/FoodReel";

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
      {/* 얌얌고니 맛집 사진 카드 (1080x1350). 사진은 food_cards.py가 public/photos/에 받아 둔다. */}
      <Composition
        id="FoodCards"
        component={FoodCards}
        schema={foodCardsSchema}
        calculateMetadata={calculateFoodCardsMetadata}
        durationInFrames={1}
        fps={1}
        width={1080}
        height={1350}
        defaultProps={{
          footer: "돌아다니면서 얼마나 먹는 고니?",
          handle: "@yamyam_gony",
          slides: [
            { type: "cover", photo: "photos/sample/01.jpg", label: "오픈런 첫 족발", title: "명동 족발\n미쓰족발", body: "", items: [] },
          ],
        }}
      />
      {/* 얌얌고니 릴스 (1080x1920). 영상은 reels.py가 public/videos/에 받아 둔다. */}
      <Composition
        id="FoodReel"
        component={FoodReel}
        schema={foodReelSchema}
        calculateMetadata={calculateFoodReelMetadata}
        durationInFrames={300}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          video: "videos/224485765186/01.mp4",
          duration: 37.6,
          width: 720,
          height: 720,
          title: "오픈런 첫 족발\n명동 미쓰족발",
          footer: "전체 후기는 프로필 링크 블로그에",
          handle: "@yamyam_gony",
        }}
      />
    </>
  );
};
