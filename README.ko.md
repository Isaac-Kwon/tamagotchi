[English](README.md) | [한국어](README.ko.md)

# Soul Tamagotchi

## 프로젝트 소개

스스로 관심사를 찾고, 꽂히면 파고들고, 지루하면 버리는 선택을 스텝마다 반복하는
자율 에이전트다. 그 선택의 누적이 자기만의 결("영혼")이 되고, 이를 다마고치처럼
관찰하고 교감할 수 있다.

이 시스템은 자기주도적 흥미를 시뮬레이션할 뿐, 문자 그대로 영혼이 깃든 존재가
아니다. 매 스텝 흥미도를 스스로 평가하고 `deepen`/`shelve`/`abandon`/`new` 중
하나를 결정해 저널에 쌓는 것이 전부이며, 각 결정은 외부 LLM API 호출의 결과다.
웹 UI 상단에도 같은 문구가 고정 배너로 표시된다.

## 요구사항

- Windows 11 + WSL(Ubuntu) 조합에서 검증됨. 실제 Python 실행은 WSL 안의
  `.venv-wsl` 가상환경에서 이루어진다. 샌드박스 격리 사다리
  (`soul/agent/sandbox.py`)는 Linux 네이티브 `bwrap`/`unshare`가 있을 때만
  진짜 네임스페이스 격리를 제공하므로, `code_experiment`와 자작 스킬 실행을
  의미 있게 격리하려면 WSL Ubuntu에서 실행해야 한다.
- Windows 쪽 venv(`.venv`)는 선택 사항. Windows 네이티브 Python으로도 테스트를
  포함해 전부 동작하지만, 이 경우 `sandbox.backend` 사다리는 bwrap/unshare를
  건너뛰고 Docker가 있으면 Docker로, 없으면 격리되지 않은 plain subprocess로
  폴백한다. 아래 "보안 관련 주의사항" 참고.
- Python 3.11 이상. `zoneinfo` 표준 라이브러리를 사용하며 `report.timezone`
  기본값은 `Asia/Seoul`.
- 외부 LLM API 키(OpenAI 호환 엔드포인트). 없어도 `--mock` 모드로 전체
  파이프라인을 돌려볼 수 있다.

## 셋업

WSL(Ubuntu) 셸에서:

```bash
cd /mnt/c/Users/<you>/Documents/tamagotchi

python3 -m venv .venv-wsl
source .venv-wsl/bin/activate
pip install -r requirements.txt
pip install pytest   # 테스트용 (requirements.txt에는 런타임 의존성만 있음)

cp config.example.json config.json
```

`config.json`에서 최소한 다음을 채운다. 로드와 검증은 `soul/config.py`가 담당한다.

- `llm.base_url` — OpenAI 호환 chat completions 엔드포인트. 기본값은
  `https://api.openai.com/v1`이며, 로컬 Ollama 등 어떤 OpenAI 호환 서버로도
  바꿀 수 있다. 특정 벤더에 락인되지 않는다.
- `llm.model` — 사용할 모델 이름.
- `llm.api_key` 또는 `llm.api_key_env` — 키 해석 순서는 ① `llm.api_key` 직접
  기입 → ② `llm.api_key_env`로 지정한 환경변수 → ③ 없으면 키 없이 동작
  (`soul/config.py:resolve_api_key`). 키가 없으면 Authorization 헤더 없이
  요청하므로 로컬 Ollama 같은 키 불필요 엔드포인트에 그대로 쓸 수 있다.
  기본 `api_key_env`는 `OPENAI_API_KEY`.
- `llm.mock` — `true`면 실제 API 키 없이 `FakeLLM`으로 전체 파이프라인을
  구동한다. UI 개발·테스트용이며 API 비용이 들지 않는다.

mock 모드: `config.json`을 건드리지 않고 커맨드에 `--mock`을 붙이면 그 실행만
FakeLLM으로 돈다(`run_agent.py --mock`, `run_web.py --mock`). API 키가 없어도
스텝 생성 → 저널 → state.json → 트랜스크립트로 이어지는 전체 흐름을 확인할 수 있다.

## 실행

에이전트 루프와 API 서버는 완전히 분리된 두 프로세스이며 `data/` 디렉토리만
공유한다. 한쪽이 죽어도 다른 쪽은 영향을 받지 않는다.

### 에이전트 루프

```bash
python run_agent.py                # 장기 실행 스케줄러 (heartbeat 또는 continuous)
python run_agent.py --once         # 스텝 1회만 실행하고 종료
python run_agent.py --once --mock  # FakeLLM으로 1스텝 (API 키 불필요)
python run_agent.py --mock         # FakeLLM으로 장기 실행
```

기본 동작은 `config.json`의 `agent.mode`(`heartbeat` 또는 `continuous`)를 따르는
장기 실행 스케줄러다. 프로세스 생존 기간 내내 `agent.lock`을 들고 있으므로
두 번째 인스턴스를 동시에 띄우면 거부된다.

### 웹 API 서버

```bash
python run_web.py            # http://127.0.0.1:8000 (config.json web.host/port)
python run_web.py --mock     # 대화 응답도 FakeLLM으로
```

### 재시작 래퍼 스크립트

`scripts/start_agent.ps1`, `scripts/start_web.ps1`은 크래시 시 지수 백오프로
자동 재시작하는 PowerShell 래퍼다. `wsl`과 `.venv-wsl`이 있으면 기본적으로
WSL의 `.venv-wsl` Python으로 실행하고, `-NoWsl` 스위치를 주면 Windows 쪽
venv(`.\.venv\Scripts\python.exe`)로 폴백한다. WSL 셸 안에서 직접 돌린다면
스크립트 없이 `run_agent.py`/`run_web.py`를 실행해도 된다. 동일한 재시작
패턴이 필요하면 bash `while` 루프로 구성한다.

## 관찰하기

웹 서버 실행 중에 `http://127.0.0.1:8000`에 접속하면:

- 방/캐릭터 — Phaser 3 기반의 작은 방에서 캐릭터가 현재 행동(`action`)에 따라
  책상/책장/창가/컴퓨터/작업대/우편함/침대 등의 위치로 이동하고 애니메이션이
  바뀐다. 흥미도(1~10)는 표정 강도로, 최근 결정(`deepen`/`new`/`shelve`/
  `abandon`)은 1회성 이펙트로 드러난다. 매핑 규칙은
  `soul/web/static/js/mapping.js`.
- 영혼 성장(soul) 패널 — 현재 SOUL.md 전문, git 히스토리 타임라인, 커밋별 diff.
  SOUL.md는 에이전트 프로세스만 고쳐 쓰고 모든 변경이 데이터 git 저장소에
  커밋되므로, 영혼의 성장사를 diff로 볼 수 있다.
- 사고 과정(step 상세) 탭 — 스텝별 ACT/REFLECT와 도구 라운드의 LLM 왕복 전문을
  그대로 열람한다(`GET /api/step/{id}/transcript`).
- 위키 — 에이전트가 스스로 쓴 `wiki_write` 노트를 검색(FTS5)·백링크·그래프로
  탐색한다.
- 일일 리포트 — 매일 지정 시각(`report.time`, 기본 22:00 `Asia/Seoul`)에
  생성되는 한국어 1인칭 회고를 날짜별로 열람한다.
- 대화 — 에이전트와 채팅한다. 진행 중이던 백그라운드 작업은 LLM 호출 경계에서
  멈췄다가 대화가 끝나면 그 지점부터 이어진다(선점). `record`가 꺼져 있으면
  (기본값) 대화는 어디에도 저장되지 않고 다음 wake에도 전달되지 않으며, UI에도
  "기억되지 않음"이라고 표시된다. `record=true`로 켜야 `chat/recorded.jsonl`에
  남고, 관찰자 inbox를 통해 다음 wake의 컨텍스트에 들어간다.
- 선물/메시지(inbox) — 관찰자가 텍스트나 URL을 남기면 다음 wake 스텝의
  컨텍스트에 "관찰자가 남긴 것"으로 중립적으로 전달된다. 반응 여부는 에이전트
  자유다.
- 요청(outbox) — inbox의 거울상. 에이전트는 ACT 중 `observer_request` 도구로
  관찰자에게 자유 형식 요청을 남길 수 있다("패키지 X가 필요하다", "이 논문에
  접근할 수 없다" 등 — 무엇을 요청할지는 전혀 유도하지 않는다). 요청은 이 탭에
  관리자 투두리스트로 쌓이고, 탭에 열린 요청 수가 배지로 표시된다. 아래 "요청에
  응답하기" 참고.
- 말과 행동(stated vs revealed) — 자기 보고 흥미도(stated)와, 저널에서 순수하게
  파생 계산한 행동 신호(revealed — 스레드 지속 길이, shelve 후 복귀 여부, 주제
  재등장 빈도)를 나란히 보여준다. 둘의 괴리는 숨기지 않고 그대로 노출한다.

## 요청에 응답하기 (관리자 가이드)

**요청** 탭을 열거나 `GET /api/outbox?status=open`을 본다. 열린 요청마다 완료
(resolved)·거절(declined)·무시(ignored) 버튼, 선택적 메모, 파일 첨부(완료/거절
시 포함)가 제공된다. 에이전트 입장에서는:

- 완료/거절은 다음 wake의 컨텍스트에 중립적 문장("An observer responded to a
  request you left")과 메모로 전달된다. 첨부 파일은 데이터 디렉토리의
  `home/attachments/<req-id>/<이름>`으로 복사된다 — `home/`은 모든 샌드박스
  백엔드에서 code_experiment의 작업 디렉토리이므로 에이전트가 직접 열 수 있는
  경로다.
- 무시는 조용하다: 목록에서만 사라지고 에이전트에게는 아무것도 전달되지 않는다
  (도구 설명 자체가 "a response may arrive later, or not"이라고만 약속한다).
  되돌릴 수 있다 — 필터를 무시로 바꾸고 다시 열기를 누르면 목록에 복원된다.

자주 나올 요청 유형별 이행 방법:

| 요청 유형 | 이행 방법 |
|---|---|
| 파이썬 패키지 | 샌드박스가 보는 위치에 설치(아래 표)하고 메모와 함께 완료. |
| 논문 / 막힌 URL | 직접 받아서 완료 시 파일 첨부 — 또는 inbox 선물로 URL/본문을 보내고 메모에 알림. |
| 데이터셋 / 샘플 파일 | 완료 시 첨부. |
| 샌드박스 한도(타임아웃·메모리), wake 주기 | `config.json` 수정 후 루프 재시작, 메모와 함께 완료. |
| 사람의 답·의견·대화 | 메모로 답하거나 채팅 세션을 시작. |
| 이행 불가 | 솔직한 메모와 함께 거절. |
| 지금은 다루고 싶지 않음 | 무시(무시 필터에서 되돌릴 수 있음). |

**패키지가 어느 파이썬에 설치되어야 하는지는 샌드박스 백엔드에 따라 다르다**
(`soul/agent/sandbox.py`; 저널의 `sandbox_backend` 필드로 확인):

| 백엔드 | 실험을 실행하는 인터프리터 | 설치 위치 |
|---|---|---|
| `subprocess` (Windows 폴백) | `sys.executable` — 에이전트를 돌리는 venv | `.venv`(또는 `.venv-wsl`)에 `pip install` |
| `bwrap` / `unshare` (WSL 기본) | 샌드박스 안의 `python3` — bwrap은 `/usr`만 ro-bind하고 venv는 바인드하지 않음 | WSL **시스템** python3에 설치 |
| `docker` | 컨테이너의 `python:3-slim` | 호스트 설치는 보이지 않음 — 커스텀 이미지 필요 |

## MCP 등록

읽기 전용 MCP 서버(`run_mcp.py`)를 Claude Code 등 외부 AI에 등록하면, 그 AI가
`wiki_search`/`wiki_read`/`wiki_list`/`read_soul`/`query_journal`/`read_report`/
`read_transcript` 도구로 이 에이전트의 데이터 디렉토리를 구조적으로 진단할 수 있다.

```bash
claude mcp add soul-wiki -- python run_mcp.py --data-dir ./data
```

이 서버는 SOUL.md/저널/리포트/트랜스크립트를 파일로 직접 읽고, 위키 인덱스는
`mode=ro` SQLite 연결로만 연다. 데이터 디렉토리에는 절대 쓰지 않는다. 쓰기
주체는 에이전트 프로세스 하나뿐이라는 원칙을 지키기 위해서다. 위키 인덱스가
아직 없으면 기본적으로 직접 재빌드하지 않고 에이전트를 한 번 실행하라는 안내
메시지를 돌려주며, `--allow-index-rebuild`를 명시적으로 줄 때만 예외적으로
파생 인덱스만 재빌드한다. md 원본은 건드리지 않는다.

## 테스트

WSL(`.venv-wsl`)에서:

```bash
pytest
```

242개 테스트가 전부 green이어야 한다. `tests/conftest.py`의 `data_paths`/`config`
픽스처가 `tmp_path`에 초기화된 데이터 디렉토리와 mock 모드 설정을 제공하므로,
테스트는 실제 네트워크나 실제 `./data`를 건드리지 않는다.

## 보안 관련 주의사항

- 샌드박스 격리 수준은 플랫폼에 따라 실제로 다르다. `soul/agent/sandbox.py`의
  격리 사다리는 (1) Linux 네이티브 `bwrap`(없으면 `unshare`) → (2) Docker(데몬
  실행 중일 때) → (3) plain subprocess 순으로 선택된다. WSL Ubuntu에서 실행하면
  보통 1번이 선택되어 네트워크·PID·마운트 네임스페이스가 격리되지만, Windows
  네이티브 폴백은 격리가 아닌 plain subprocess다. 코드가 이를 `isolated=False`로
  표시하고, 실제 선택된 백엔드는 저널의 `sandbox_backend` 필드와 기동 로그에
  그대로 기록된다. 강한 격리가 필요하면 WSL을 쓰거나 Windows에 Docker를 띄운다.
- 같은 규칙이 자작 스킬 실행(`skill_runner.py`)에도 적용된다. 스킬은 에이전트
  프로세스에 import되지 않고 항상 별도 subprocess로, 위와 같은 샌드박스
  사다리를 그대로 통과한다.
- DuckDuckGo 검색 결과에는 광고/스폰서 링크가 섞여 있을 수 있다. `web_search`는
  `html.duckduckgo.com/html`의 결과 HTML을 그대로 파싱하고 도메인 차단 목록을
  두지 않는다. 어떤 검색어와 URL을 고를지는 전적으로 에이전트 자유라는 중립성
  원칙 때문이다. 안전장치는 크기 상한(`max_page_kb`, 기본 500KB)과 시간
  상한(`http_timeout_seconds`, 기본 20초)뿐이다.
- 에이전트가 방문한 URL은 전부 저널의 `web_visits` 필드에 남는다.
- 응답 첨부 파일은 그대로 저장된다. `POST /api/outbox/{id}/resolve`로 올린
  파일은 가공 없이 `outbox/attachments/`에 저장되고 다음 wake에 `home/`으로
  복사되어 에이전트의 샌드박스 코드가 읽을 수 있다. 안전장치는 파일명
  정제(basename만 사용)와 `max_attachment_mb` 크기 상한뿐이다 — 이
  엔드포인트는 운영자를 신뢰하며, 그래서 서버 기본 바인드가 `127.0.0.1`이다
  (외부에 열 때는 `web.allowed_networks`를 함께 설정).
