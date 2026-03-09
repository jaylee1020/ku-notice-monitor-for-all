# 셋업 가이드

건국대 공지 텔레그램 봇을 내 계정으로 직접 운영하는 방법입니다.
서버 없이 GitHub Actions만으로 무료로 돌릴 수 있습니다.

---

## 준비물

- GitHub 계정
- 텔레그램 계정
- (선택) Google 계정 — AI 필터링 사용 시

---

## Step 1. 레포지토리 Fork

1. 이 레포지토리 상단의 **Fork** 버튼 클릭
2. 내 GitHub 계정으로 Fork 완료

---

## Step 2. 텔레그램 봇 만들기

1. 텔레그램에서 [@BotFather](https://t.me/BotFather) 검색 후 대화 시작
2. `/newbot` 입력
3. 봇 이름 입력 (예: `건국대 공지봇`)
4. 봇 username 입력 (영어, `_bot`으로 끝나야 함, 예: `konkuk_notice_bot`)
5. 발급된 **토큰** 복사해 저장

   ```
   예시: 1234567890:ABCDefghIJKlmNOPqrSTUvwxYZ
   ```

---

## Step 3. 내 chat_id 확인

1. 텔레그램에서 [@getidsbot](https://t.me/getidsbot) 검색 후 `/start` 전송
2. 응답에서 **Your ID** 숫자 값 복사해 저장

   ```
   예시: 987654321
   ```

---

## Step 4. Gemini API 키 발급 (선택, 권장)

> 없으면 키워드 매칭 방식으로 동작합니다. AI 맞춤 필터링을 원하면 설정하세요.

1. [Google AI Studio](https://aistudio.google.com/apikey) 접속
2. **Create API key** 클릭
3. 발급된 키 복사해 저장

---

## Step 5. GitHub Secrets 등록

Fork한 내 레포지토리에서 설정합니다.

`Settings` → `Secrets and variables` → `Actions` → **New repository secret**

아래 항목을 하나씩 추가합니다.

| Name | Value | 필수 |
|------|-------|------|
| `TELEGRAM_BOT_TOKEN` | Step 2에서 받은 봇 토큰 | **필수** |
| `ADMIN_CHAT_ID` | Step 3에서 확인한 내 chat_id | **권장** |
| `GEMINI_API_KEY` | Step 4에서 발급한 API 키 | 선택 |

> `ADMIN_CHAT_ID`를 설정해야 신규 사용자 승인, 차단 등 관리자 기능을 쓸 수 있습니다.

---

## Step 6. Actions 활성화

1. Fork한 레포지토리의 **Actions** 탭 클릭
2. "I understand my workflows..." 버튼 클릭해 활성화

이제 아래 두 워크플로우가 자동으로 실행됩니다.

- **텔레그램 명령 처리**: 15분마다 (명령어 처리)
- **건국대 공지 모니터링**: 매일 오전 10시 KST (공지 수집 및 알림)

---

## Step 7. 봇 사용 시작

1. Step 2에서 만든 내 봇(@봇username)에게 텔레그램으로 `/start` 전송
2. `ADMIN_CHAT_ID`를 설정했다면 관리자(본인)에게 승인 요청 알림이 옵니다
3. 봇에게 `/allow <본인 chat_id>` 입력해 스스로 승인
4. 최대 15분 내에 시작 안내 메시지가 자동으로 옵니다

> 명령어는 **최대 15분 이내**에 처리됩니다 (15분 주기 명령 처리 워크플로우).
> 즉시 확인하려면 Actions 탭 → `텔레그램 명령 처리` → `Run workflow`로 수동 실행하세요.

---

## 봇 명령어

봇에게 직접 메시지로 보내세요.

| 명령어 | 설명 |
|--------|------|
| `/start` | 알림 켜기 |
| `/stop` | 알림 끄기 |
| `/profile 컴퓨터공학부 / 2학년 / 서울 / 재학` | AI 맞춤 분석용 프로필 등록 |
| `/filter 없음\|하\|중\|상` | 알림 필터 강도 설정 |
| `/status` | 현재 설정 확인 |
| `/help` | 명령어 목록 |
| `/delete_me` | 내 정보 삭제 |

### 프로필 입력 예시

```
/profile 컴퓨터공학부 / 2학년 / 서울 / 재학
/profile 경영학과, 4학년, 서울캠퍼스, 졸업예정
```

프로필을 등록하면 AI가 내 전공/학년에 맞는 공지만 골라서 알려줍니다.

### 필터 레벨

| 레벨 | 의미 |
|------|------|
| `없음` | 전체 신규 공지 수신 |
| `하` | 나와 약간이라도 관련된 것 |
| `중` | 일반적으로 유용한 것 (기본값) |
| `상` | 내 학과/관심사에 직접 관련된 것만 |

---

## 자주 묻는 것

**명령어를 보냈는데 응답이 없어요**
최대 15분 이내에 처리됩니다. 즉시 확인하려면 Actions 탭에서 `텔레그램 명령 처리` 워크플로우를 수동 실행하세요.

**승인 대기 중이라고 나와요**
관리자(본인)가 봇에게 `/allow <chat_id>` 를 보내면 됩니다.

**AI 분석 없이 키워드 매칭만 돼요**
`GEMINI_API_KEY` Secret이 올바르게 등록됐는지 확인하세요.

**알림이 아예 안 와요**
1. `TELEGRAM_BOT_TOKEN` 값이 맞는지 확인
2. 봇에 `/start`를 보냈는지 확인
3. 관리자 승인(`/allow`)을 받았는지 확인
4. `/status`로 `알림: 켜짐` 상태인지 확인
