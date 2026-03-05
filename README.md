# 건국대학교 공지 모니터링 에이전트

건국대학교 공지사항 RSS 피드를 자동으로 수집하고, Gemini AI로 관련도를 분석해 텔레그램으로 전달하는 에이전트입니다.

이 버전은 **다중 사용자(소규모) 배포**를 지원합니다.

## 주요 기능

- **자동 수집**: 학사/장학/취창업/국제교류/학생생활/일반 공지 RSS 피드 수집
- **AI 분석**: 사용자 프로필 기반 관련도 1-5점 평가
- **사용자별 필터**: `/filter 없음|상|중|하`
- **개인정보 미등록 정책**: 프로필 미등록 사용자는 신규 공지 전체 전달
- **허용목록 운영**: 관리자 `/allow`, `/block`으로 사용자 제어
- **일 1회 배치**: 명령 처리와 공지 발송을 하루 1회 실행

## GitHub Secrets 설정

`Settings > Secrets and variables > Actions`에 아래 값을 등록합니다.

| Secret 이름 | 설명 | 필수 여부 |
|------------|------|---------|
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 | 필수 |
| `GEMINI_API_KEY` | Google AI Studio API 키 | 권장 |
| `KEYWORDS_JSON` | 키워드 폴백용 JSON | 선택 |
| `PROFILE_JSON` | 레거시 1인 운영 마이그레이션용 JSON | 선택 |
| `TELEGRAM_CHAT_ID` | 레거시 1인 운영 마이그레이션용 chat_id | 선택 |
| `ADMIN_CHAT_ID` | 관리자 chat_id (`config.yaml` 값보다 우선) | 권장 |

### KEYWORDS_JSON 예시
```json
{
  "high": ["장학", "등록금", "수강신청"],
  "medium": ["취업", "인턴", "공모전", "해외"]
}
```

## 사용자 명령어

- `/start` 알림 활성화
- `/help` 도움말
- `/profile <자연어>` 개인정보 등록
- `/filter 없음|상|중|하` 필터 설정
- `/status` 내 설정 확인
- `/stop` 알림 비활성화
- `/delete_me` 내 개인정보/레코드 삭제

### `/profile` 입력 예시

```text
/profile 컴퓨터공학부 / 2학년 / 서울캠퍼스 / 재학
```

파싱 항목: `major`, `year`, `campus`, `status`

## 관리자 명령어

- `/allow <chat_id>` 사용자 허용
- `/block <chat_id>` 사용자 차단

허용되지 않은 사용자는 봇 사용이 제한됩니다.

## 필터 레벨 기준

- `없음`: 전체 신규 공지 전달
- `하`: 관련도 2점 이상
- `중`: 관련도 3점 이상
- `상`: 관련도 4점 이상

## 설정 파일 (`config.yaml`)

```yaml
settings:
  state_file: "state.json"
  users_file: "users.json"
  admin_chat_id: ""
  max_users: 30
  ssl_verify: false
```

```yaml
gemini:
  model: "gemini-3.1-flash-lite-preview"
  relevance_threshold: 3
  min_call_interval_sec: 4.2
  max_calls_per_run: 120
  disable_after_fallback: true
```

- `users_file`: 사용자/명령 처리 상태 저장 파일
- `admin_chat_id`: 관리자 chat_id
- `max_users`: 허용 가능한 최대 사용자 수
- `min_call_interval_sec`: Gemini 호출 간 최소 대기 시간(RPM 보호)
- `max_calls_per_run`: 일일 실행 1회당 Gemini 호출 상한(RPD 보호)
- `disable_after_fallback`: 제한/오류 발생 후 남은 그룹을 키워드 방식으로 자동 전환

## 로컬 실행

```bash
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="your-bot-token"
export GEMINI_API_KEY="your-api-key"
export ADMIN_CHAT_ID="your-admin-chat-id"
export KEYWORDS_JSON='{"high":["장학","등록금"],"medium":["취업","인턴"]}'

python main.py
```

## 데이터 파일

- `state.json`: 이미 처리한 공지 ID
- `users.json`: 사용자 상태/프로필/필터/텔레그램 update offset

`users.json` 예시:
```json
{
  "meta": { "last_update_id": 0, "version": 1 },
  "users": {}
}
```

## GitHub Actions 동작

- 스케줄: 매일 오전 10시(KST)
- 처리 순서:
1. 텔레그램 명령 수집 및 응답
2. 신규 공지 수집/분석
3. 사용자별 알림 발송
4. `state.json`, `users.json` 커밋

## 트러블슈팅

### 명령어 응답/알림이 오지 않아요
- `TELEGRAM_BOT_TOKEN`이 올바른지 확인하세요.
- 사용자가 봇과 먼저 대화를 시작했는지 확인하세요.
- 사용자가 관리자에게 `/allow`로 승인되었는지 확인하세요.

### 관리자 명령이 동작하지 않아요
- `ADMIN_CHAT_ID` 또는 `config.yaml > settings.admin_chat_id`가 본인 chat_id인지 확인하세요.

### Gemini 없이 키워드만 동작해요
- `GEMINI_API_KEY` 설정을 확인하세요.

### 개인정보 삭제가 필요해요
- 사용자가 `/delete_me`를 실행하면 해당 사용자 레코드가 `users.json`에서 삭제됩니다.
