import { z } from "zod";

// food_cards.py가 만드는 props.json과 같은 구조. 프레임 하나가 카드 한 장이다.

export const foodSlideSchema = z.object({
  // cover: 표지 / photo: 사진+한 줄 / menu: 메뉴판 / info: 저장해두고 가기 / outro: 질문
  type: z.enum(["cover", "photo", "menu", "info", "outro"]),
  // video/public 아래 경로 (photos/<글번호>/NN.jpg)
  photo: z.string(),
  label: z.string(),
  title: z.string(),
  body: z.string(),
  // menu: "이름|가격" (시킨 메뉴는 "★" 시작), info: "항목|내용"
  items: z.array(z.string()),
});

export const foodCardsSchema = z.object({
  masthead: z.string(),
  handle: z.string(),
  slides: z.array(foodSlideSchema),
});

export type FoodSlide = z.infer<typeof foodSlideSchema>;
export type FoodCardsProps = z.infer<typeof foodCardsSchema>;
