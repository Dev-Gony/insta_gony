import { z } from "zod";

// food_cards.py가 만드는 props.json과 같은 구조. 프레임 하나가 카드 한 장이다.

export const foodSlideSchema = z.object({
  // cover: 표지(제목) / photo: 사진만 / outro: 마지막 장(질문)
  type: z.enum(["cover", "photo", "outro"]),
  // video/public 아래 경로 (photos/<글번호>/NN.jpg)
  photo: z.string(),
  label: z.string(),
  title: z.string(),
  body: z.string(),
  items: z.array(z.string()),
});

export const foodCardsSchema = z.object({
  // 표지 아래 작은 글씨 (블로그 이름)
  footer: z.string(),
  handle: z.string(),
  slides: z.array(foodSlideSchema),
});

export type FoodSlide = z.infer<typeof foodSlideSchema>;
export type FoodCardsProps = z.infer<typeof foodCardsSchema>;
