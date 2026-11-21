# insta_gony

네이버 블로그에 새 글을 쓰면, Claude가 카드뉴스로 만들어 인스타그램에 자동으로 올린다.

```
네이버 블로그 RSS ─▶ 본문 가져오기 ─▶ Claude 카드 문구·캡션 ─▶ Remotion 카드 JPEG ─▶ 채널마다 게시
                                                                                     ├ instagram (카드 캐러셀) ✅
                                                                                     ├ threads (다음)
                                                                                     └ clip / reels (영상, 그다음)
```

| 파일 | 하는 일 |
|---|---|
| `main.py` | 전체 흐름, 켜 둔 채널(`CHANNELS`)마다 게시 |
| `naver_blog.py` | RSS로 새 글 찾기, 모바일 페이지에서 본문 가져오기 |
| `cards.py` | Claude 카드 문구(글에 없는 사실은 안 씀), 캡션, 카드 렌더 |
| `instagram.py` | 이미지를 `insta-media` 브랜치에 올려 공개 URL 만들기, 캐러셀 게시 |
| `common.py` | Claude 호출(`claude -p`, 구독 토큰), Slack 알림, JSON 기록 |
| `video/` | Remotion 카드 화면 (1080x1350, 종이색·명조) |
| `config/history.json` | 채널별로 올린 글·건너뛴 글 (여기 있으면 다시 안 올림) |
| `.github/workflows/run.yml` | 08~22시 2시간마다 실행, 새 글 없으면 바로 끝 |

## 동작 규칙

- 아직 안 올린 글 중 **최근 3일 안에 쓴 글** 1개를 오래된 것부터 올린다. 처음 연결할 때 옛 글이 한꺼번에 올라가지 않게 하려는 것. 옛 글은 수동 실행에 `link`로 넣으면 된다.
- 본문이 300자 미만이면(사진만 있는 글 등) 건너뛴다.
- 한 채널이 실패해도 다른 채널은 올리고, 실패는 Slack으로 알린다. 실패한 채널은 다음 실행에서 다시 시도한다.

## 처음 한 번 연결하기

### 1. Claude 토큰

로컬에서 `claude setup-token`을 실행해 나온 토큰을 Secret `CLAUDE_CODE_OAUTH_TOKEN`에 넣는다 (technews와 같은 토큰을 써도 된다).

### 2. 인스타그램 토큰 (Instagram 로그인 방식, 페이스북 페이지 필요 없음)

1. 인스타 계정이 **프로페셔널(비즈니스·크리에이터)** 인지 확인
2. https://developers.facebook.com → 내 앱 → **앱 만들기**
   - 사용 사례: **"Instagram에서 메시지 및 콘텐츠 관리"**(Instagram API), 앱 유형: 비즈니스
3. 앱 대시보드 → Instagram → **"Instagram 로그인을 통한 API 설정"**
4. **"액세스 토큰 생성" → 계정 추가** → 올릴 인스타 계정으로 로그인해 권한 허용
   - 권한: `instagram_business_basic`, `instagram_business_content_publish`
   - 계정 추가가 막히면: 앱 역할에 그 인스타 계정을 **Instagram 테스터**로 추가하고,
     인스타 앱 → 설정 → 앱 및 웹사이트 → 테스터 초대에서 수락
5. 나온 **토큰**과 계정 옆 **ID 숫자**를 복사 (토큰은 60일짜리)

### 3. GitHub에 넣기 (Settings → Secrets and variables → Actions)

| 종류 | 이름 | 값 |
|---|---|---|
| Secret | `CLAUDE_CODE_OAUTH_TOKEN` | Claude 구독 토큰 |
| Secret | `INSTAGRAM_ACCESS_TOKEN` | 인스타 토큰 |
| Secret | `INSTAGRAM_USER_ID` | 인스타 계정 ID 숫자 (비워도 됨) |
| Secret | `SLACK_WEBHOOK_URL` | Slack 알림 (선택) |
| Variable | `NAVER_BLOG_ID` | `blog.naver.com/<여기>` |
| Variable | `INSTA_HANDLE` | 카드에 찍을 아이디, 예: `@gony` (비우면 계정 이름) |
| Variable | `INSTA_MASTHEAD` | 카드 맨 위 제목 (비우면 블로그 이름, 16자까지) |
| Variable | `MAX_AGE_DAYS` | 자동으로 올릴 글의 최대 나이 (기본 3) |
| Variable | `CHANNELS` | 올릴 채널, 쉼표로 (기본 `instagram`) |
| Variable | `CLAUDE_MODEL` | 카드 문구 모델 (기본 `sonnet`) |

API 주소는 자동으로 고른다: graph.instagram.com을 먼저 시험하고, 안 되면 graph.facebook.com(비즈니스 포트폴리오의 "통합 로그인" 시스템 사용자 토큰, "Facebook 로그인" 토큰)을 쓴다. graph.facebook.com 쪽 토큰이면 `INSTAGRAM_USER_ID`를 꼭 넣는다. 고정하려면 Variable `INSTAGRAM_GRAPH_HOST`.

토큰만 확인하려면: Actions → Blog to SNS → Run workflow에서 `check_account`를 켜고 실행 (계정 이름·게시 한도만 읽고 끝남).

### 4. 시험

1. Actions → **Blog to SNS** → Run workflow, `link`에 블로그 글 주소를 넣고 `upload`는 **끈 채로** 실행
2. 실행 결과의 아티팩트 `cards`에서 카드 JPEG·캡션 확인
3. 괜찮으면 `upload`를 켜고 한 번 더 실행해서 인스타에 올라갔는지 확인
4. 그 뒤로는 예약 실행이 알아서 올린다

## 로컬에서 돌려 보기

```bash
pip install -r requirements.txt
cd video && npm ci && cd ..
NAVER_BLOG_ID=<블로그ID> python main.py --no-upload        # 카드만 만들기 → runtime/posts/<글번호>/
python main.py --link https://blog.naver.com/<ID>/<글번호> --no-upload
cd video && npm run dev                                      # 카드 화면 미리보기 (Remotion Studio)
```

## 주의

- **인스타 토큰은 60일 뒤 만료**된다. 만료되면 게시가 실패하고 Slack에 알림이 온다 → 2-4를 다시 해서 Secret을 바꾼다.
- 인스타 API는 이미지를 공개 URL로만 받는다. 그래서 이 레포는 **공개**이고, 카드 이미지는 `insta-media` 브랜치에 쌓인다 (블로그에 공개한 내용이라 문제없음). 토큰은 Secrets에만 있다.

## 다음 할 일

- [ ] **threads**: Threads API(graph.threads.net)로 같은 카드 + 짧은 글. 인스타와 같은 Meta 앱에서 토큰 발급
- [ ] **영상**: 카드를 넘기는 15~30초 세로 영상(+배경음) → 인스타 릴스
- [ ] **clip**: 네이버 클립은 공개 업로드 API가 없어서 자동화 방법을 따로 조사해야 함. 우선은 영상 파일만 만들어 두고 직접 올리기

## 글의 영상 → 릴스 (reels.py)

| 글의 영상 | 하는 일 |
|---|---|
| 없음 | 사진 카드 캐러셀만 |
| `MIN_REEL_SECONDS`(기본 15초)보다 짧음 | 캐러셀 2번째 장에 그 영상을 1080x1350으로 넣음 |
| 그보다 김 | 캐러셀 + 릴스 (속삭이는 내레이션) |

릴스 만드는 순서: 네이버 동영상 원본 → 30fps 고정 무음 영상 + 매장 소리 → 장면 시트(시각 표시) →
Claude가 시트를 직접 보고 대사 6~8줄과 줄마다 원본 구간(본문 사실만, 광고·딴 화면 금지) →
Gemini TTS **한 번**으로 전체 대사를 속삭이듯 읽고 줄 사이 쉼에서 나눔(안 되면 줄마다) → 빈 소리 자르고 1.12배 →
대사 길이에 맞춰 컷 배치(최대 0.7배 느리게) → Remotion `FoodReelEdit` → -14 LUFS.

- 필요한 Secret: `GEMINI_API_KEY` (무료 한도. technews 쇼츠와 같은 키면 한도를 같이 씀, KST 17시 초기화)
- 릴스 만들기가 실패하면(TTS 한도 등) 기록하지 않고 다음 실행에서 다시 한다. 하루 1개 제한은 새 글을 고를 때만.
- 수동 실행 `reel_url`: 새로 만들지 않고 그 mp4를 올림
- 릴스는 파일을 직접 올리고(resumable upload), 안 되면 `insta-media` 브랜치 공개 주소로 다시 시도
- Variables: `MIN_REEL_SECONDS`, `REEL_FOOTER`(릴스 아래 안내, 기본 "전체 후기는 블로그에"), `CHANNELS`(기본 `instagram,reels`)
