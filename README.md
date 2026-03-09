# 건국대학교 공지 모니터링 봇

건국대학교 공지사항 RSS 피드를 매일 자동으로 수집하고, Gemini AI로 각 사용자의 프로필에 맞는 관련 공지를 분석해 텔레그램으로 전달하는 다중 사용자 알림 봇입니다.

GitHub Actions로 무료로 운영할 수 있으며, 별도 서버가 필요 없습니다.

---

## 목차

- [동작 방식](#동작-방식)
- [수집 피드](#수집-피드)
- [빠른 시작](#빠른-시작)
- [GitHub Secrets 설정](#github-secrets-설정)
- [config.yaml 설정](#configyaml-설정)
- [외부 사용자 등록 절차](#외부-사용자-등록-절차)
- [사용자 명령어](#사용자-명령어)
- [관리자 명령어](#관리자-명령어)
- [필터 레벨](#필터-레벨)
- [레거시 단일 사용자 마이그레이션](#레거시-단일-사용자-마이그레이션)
- [로컬 실행](#로컬-실행)
- [트러블슈팅](#트러블슈팅)

---

## 동작 방식

두 가지 GitHub Actions 워크플로우가 독립적으로 실행됩니다.

### 명령 처리 워크플로우 (15분마다)

```
텔레그램 업데이트 수집 → 명령어 처리 및 응답 → users.json 커밋
```

`/start`, `/profile`, `/filter` 등 봇 명령어는 최대 15분 이내에 처리됩니다.

### 공지 모니터링 워크플로우 (매일 오전 10시 KST)

```
1. 텔레그램 명령 수집 → 명령어 처리 및 응답 (15분 주기 처리 보완용)
2. RSS 피드 수집 → 신규 공지 필터링
3. 신규 공지 본문 크롤링 (AI 분석 정확도 향상)
4. 사용자별 Gemini AI 관련도 분석 (1~5점)
   └─ API 키 없거나 쿼터 초과 시 → 키워드 매칭으로 자동 폴백
5. 필터 기준 이상의 공지만 텔레그램으로 알림 발송
6. state.json, users.json 커밋 (처리 이력 보존)
```

**프로필 미등록 사용자**는 필터링 없이 전체 신규 공지를 수신합니다.

동일 프로필 + 필터 조합은 캐시되어, 동일 그룹 내 Gemini 호출이 중복되지 않습니다.

---

## 수집 피드

`config.yaml`의 `feeds` 섹션에서 활성화 여부를 제어할 수 있습니다.

| 피드 이름 | board_id | 기본값 |
|---------|---------|-------|
| 학사공지 | 234 | 활성 |
| 장학공지 | 235 | 활성 |
| 취창업공지 | 236 | 활성 |
| 국제교류 | 237 | 활성 |
| 학생생활 | 238 | 활성 |
| 일반공지 | 240 | 활성 |
| 채용공지 | 243 | 활성 |
| 학사서식공지 | 247 | 활성 |
| 대학일자리플러스 | 4083 | 활성 |
| 입찰공고공지 | 239 | **비활성** |

---

## 빠른 시작

### 1. 이 레포지토리를 Fork합니다

### 2. 텔레그램 봇을 생성합니다

[@BotFather](https://t.me/BotFather)에서 `/newbot` 명령으로 봇을 만들고 토큰을 받습니다.

### 3. 본인 chat_id를 확인합니다

텔레그램에서 [@getidsbot](https://t.me/getidsbot)에 `/start`를 보내면 바로 확인할 수 있습니다.

또는 봇에게 아무 메시지를 보낸 뒤, 아래 URL로 확인할 수도 있습니다.

```
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates
```

응답 JSON의 `result[0].message.chat.id` 값이 본인의 chat_id입니다.

### 4. GitHub Secrets를 설정합니다

아래 [GitHub Secrets 설정](#github-secrets-설정) 섹션을 참고합니다.

### 5. Actions를 활성화합니다

Fork한 레포지토리의 `Actions` 탭에서 워크플로우를 활성화합니다.

이후 아래 두 워크플로우가 자동 실행됩니다.

- **명령 처리**: 15분마다 실행 (텔레그램 명령 처리)
- **공지 모니터링**: 매일 오전 10시(KST) 실행 (공지 수집 및 알림)

각 워크플로우는 `workflow_dispatch`로 수동 실행도 가능합니다.

---

## GitHub Secrets 설정

`Settings > Secrets and variables > Actions`에 등록합니다.

| Secret 이름 | 설명 | 필수 여부 |
|------------|------|---------|
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 | **필수** |
| `ADMIN_CHAT_ID` | 관리자 chat_id (관리자 명령어 사용 가능) | **권장** |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) API 키 | 권장 |
| `KEYWORDS_JSON` | Gemini 대신 또는 폴백으로 사용할 키워드 JSON | 선택 |
| `TELEGRAM_CHAT_ID` | 레거시 단일 사용자 마이그레이션용 chat_id | 선택 |
| `PROFILE_JSON` | 레거시 단일 사용자 마이그레이션용 프로필 JSON | 선택 |

### GEMINI_API_KEY

무료 티어([Google AI Studio](https://aistudio.google.com/apikey))로 충분합니다.
설정하지 않으면 `KEYWORDS_JSON` 키워드 매칭으로 대체됩니다.

### KEYWORDS_JSON 예시

```json
{
  "high": ["장학", "등록금", "수강신청"],
  "medium": ["취업", "인턴", "공모전", "해외"]
}
```

- `high` 키워드 매칭 → 관련도 4점으로 처리
- `medium` 키워드 매칭 → 관련도 3점으로 처리

---

## config.yaml 설정

레포지토리 루트의 `config.yaml`에서 세부 동작을 제어합니다.

### settings

```yaml
settings:
  state_file: "state.json"       # 처리한 공지 ID 저장 파일
  users_file: "users.json"       # 사용자 상태/프로필 저장 파일
  admin_chat_id: ""              # 관리자 chat_id (ADMIN_CHAT_ID Secret으로도 설정 가능)
  max_users: 30                  # 최대 허용 사용자 수 (0 이하 = 무제한)
  ssl_verify: false              # SSL 인증서 검증 여부
                                 # 건국대 서버 인증서 문제로 기본값은 false
```

> `admin_chat_id`는 `ADMIN_CHAT_ID` Secret이 우선 적용됩니다. Secret 설정을 권장합니다.

### gemini

```yaml
gemini:
  model: "gemini-3.1-flash-lite-preview"
  relevance_threshold: 3         # 이 점수 이상인 공지만 알림 (1~5)
  min_call_interval_sec: 4.2     # Gemini 호출 간 최소 대기 시간 (RPM 보호)
  max_calls_per_run: 120         # 하루 1회 실행당 최대 Gemini 호출 수 (RPD 보호)
  disable_after_fallback: true   # 쿼터/오류 발생 후 남은 그룹을 키워드 방식으로 전환
```

> 무료 티어 기준: RPM 15, RPD 1,500. 기본값은 무료 티어 안에서 안정적으로 동작하도록 설정되어 있습니다.

### feeds

각 피드의 `enabled: false`로 수집을 비활성화할 수 있습니다.

```yaml
feeds:
  학사공지:
    id: 234
    enabled: true
  입찰공고공지:
    id: 239
    enabled: false   # 비활성화 예시
```

---

## 외부 사용자 등록 절차

봇을 운영자(관리자)가 아닌 외부인에게 공유할 경우의 등록 흐름입니다.

### 외부 사용자 입장

1. 봇 username으로 텔레그램 검색 후 대화 시작
2. `/start` 전송
3. "관리자 승인 후 이용 가능" 안내와 함께 본인 Chat ID 확인
4. 관리자에게 Chat ID 전달하거나, 자동 승인 요청 알림이 전송됩니다
5. 관리자 승인 후 최대 15분 내에 시작 안내 메시지 수신
6. `/start` 입력해 알림 활성화
7. (선택) `/profile`, `/filter`로 맞춤 설정

### 관리자 입장

1. 외부 사용자가 `/start`를 보내면 승인 요청 알림 자동 수신
   ```
   새 사용자 승인 요청이 왔습니다.
   Chat ID: 123456789

   승인하려면: /allow 123456789
   차단하려면: /block 123456789
   ```
2. 봇에게 `/allow <chat_id>` 전송
3. 최대 15분 내에 해당 사용자에게 시작 가이드 자동 전송

> **최대 허용 인원**: `config.yaml`의 `settings.max_users` (기본값 30명)로 제한됩니다.
> 초과 시 승인이 거부됩니다.

---

## 사용자 명령어

봇에게 직접 텔레그램 메시지로 명령을 보냅니다.
명령은 **최대 15분 이내**에 처리됩니다 (15분 주기 명령 처리 워크플로우).

| 명령어 | 설명 |
|--------|------|
| `/start` | 알림 활성화 |
| `/stop` | 알림 일시 중지 |
| `/help` | 명령어 목록 |
| `/profile <내용>` | 개인 프로필 등록 (AI 맞춤 분석에 사용) |
| `/filter 없음\|상\|중\|하` | 알림 필터 강도 설정 |
| `/status` | 현재 설정 확인 |
| `/delete_me` | 내 정보 전체 삭제 |

### `/profile` 입력 예시

구분자(`/`, `,`, `;`, `|`)로 항목을 분리합니다.

```
/profile 컴퓨터공학부 / 2학년 / 서울캠퍼스 / 재학
/profile 경영학과, 4학년, 서울, 졸업예정
```

파싱되는 항목: `학과(major)`, `학년(year)`, `캠퍼스(campus)`, `재학상태(status)`

> 프로필을 등록하지 않으면 필터 설정에 관계없이 전체 신규 공지를 수신합니다.

---

## 관리자 명령어

`ADMIN_CHAT_ID`로 지정된 관리자만 사용할 수 있습니다.

| 명령어 | 설명 |
|--------|------|
| `/allow <chat_id>` | 사용자 봇 이용 허용 |
| `/block <chat_id>` | 사용자 봇 이용 차단 |

허용(`/allow`)되지 않은 사용자는 모든 기능이 제한되며, 본인의 chat_id가 안내됩니다.

**신규 사용자 승인 흐름:**
1. 신규 사용자가 봇에 `/start` 전송
2. 관리자에게 승인 요청 알림 자동 발송 (`/allow <chat_id>` 안내 포함)
3. 관리자가 봇에 `/allow <chat_id>` 입력
4. 최대 15분 내에 신규 사용자에게 시작 가이드 자동 전송
5. 신규 사용자가 `/start`를 입력해 알림 활성화

---

## 필터 레벨

`/filter` 명령으로 설정하며, Gemini 또는 키워드 분석 결과에 적용됩니다.

| 레벨 | 명령어 | 전달 기준 |
|------|--------|---------|
| 없음 | `/filter 없음` | 전체 신규 공지 |
| 하 | `/filter 하` | 관련도 2점 이상 |
| 중 | `/filter 중` | 관련도 3점 이상 (기본값) |
| 상 | `/filter 상` | 관련도 4점 이상 |

**Gemini 관련도 점수 기준**

| 점수 | 기준 |
|------|------|
| 5점 | 수강신청, 등록금 등 필수 학사 사항 |
| 4점 | 본인 학과/관심 분야 직접 관련 |
| 3점 | 일반 학생에게 유용한 정보 |
| 2점 | 특정 대상만 해당하는 공지 |
| 1점 | 관련 없음 |

---

## 레거시 단일 사용자 마이그레이션

기존에 `TELEGRAM_CHAT_ID` + `PROFILE_JSON`으로 1인 운영하던 경우,
Secrets를 그대로 유지하면 최초 실행 시 자동으로 다중 사용자 구조로 마이그레이션됩니다.

마이그레이션 후에는 해당 사용자가 허용 + 활성 상태로 자동 등록되며,
이후부터는 텔레그램 명령어로 프로필과 필터를 관리합니다.

---

## 로컬 실행

```bash
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="your-bot-token"
export GEMINI_API_KEY="your-api-key"
export ADMIN_CHAT_ID="your-chat-id"
export KEYWORDS_JSON='{"high":["장학","등록금"],"medium":["취업","인턴"]}'

python main.py
```

실행 후 `state.json`과 `users.json`이 업데이트됩니다.

---

## 트러블슈팅

### 명령어를 보냈는데 응답이 없어요

명령어는 15분 주기 워크플로우에서 처리되므로 최대 15분 정도 기다려 주세요.
즉시 처리하려면 Actions 탭에서 `텔레그램 명령 처리` 워크플로우를 수동 실행하세요.

### 봇에 메시지를 보냈는데 승인 대기 안내가 왔어요

`/start`를 보내면 관리자에게 승인 요청이 자동으로 전송됩니다.
관리자가 `/allow <chat_id>`로 승인하면, 최대 15분 내에 시작 안내 메시지가 자동으로 옵니다.
이후 `/start`를 다시 입력해 알림을 활성화하세요.

### 관리자 명령어가 동작하지 않아요

`ADMIN_CHAT_ID` Secret 또는 `config.yaml`의 `settings.admin_chat_id`가 본인 chat_id와 일치하는지 확인하세요.

### Gemini 분석 없이 키워드 매칭만 동작해요

- `GEMINI_API_KEY` Secret이 올바르게 설정되어 있는지 확인하세요.
- Actions 로그에서 쿼터 초과 여부를 확인하세요.
- 당일 `max_calls_per_run` 상한(기본 120회)에 도달하면 나머지 그룹은 키워드 매칭으로 처리됩니다.

### 공지 알림이 오지 않아요

1. `TELEGRAM_BOT_TOKEN`이 올바른지 확인하세요.
2. 봇과 먼저 대화를 시작(`/start`)했는지 확인하세요.
3. 관리자에게 `/allow` 승인을 받았는지 확인하세요.
4. `/status` 명령으로 `알림: 켜짐` 상태인지 확인하세요.

### 개인정보를 삭제하고 싶어요

봇에 `/delete_me`를 보내면 다음 실행 시 `users.json`에서 해당 사용자 레코드가 완전히 삭제됩니다.
