# Soul Tamagotchi

## 프로젝트 한 줄 소개

스스로 관심사를 찾고, 꽂히면 파고들고, 지루하면 버리는 선택을 스텝마다 반복하며
그 누적으로 자기만의 결("영혼")을 만들어가는 자율 에이전트를, 다마고치처럼
관찰·교감할 수 있게 만든 개인 프로젝트입니다.

**정직하게 밝혀둡니다**: 이것은 자기주도적 흥미를 *시뮬레이션*하는 시스템이지,
문자 그대로 영혼이 깃든 존재가 아닙니다. 매 스텝 흥미도를 스스로 평가하고
(`deepen`/`shelve`/`abandon`/`new`) 그 결정을 저널에 쌓는 것이 전부이며,
그 결정 하나하나는 외부 LLM API 호출의 결과물입니다. 웹 UI 상단에도 같은
문구가 고정 배너로 떠 있습니다.

## 요구사항

- **Windows 11 + WSL(Ubuntu) 조합을 기준으로 검증되었습니다.** 실제 Python 실행은
  **WSL 안에서** 이루어집니다 (`.venv-wsl` 가상환경). 이 프로젝트의 샌드박스 격리
  사다리(`soul/agent/sandbox.py`)는 Linux 네이티브 `bwrap`/`unshare`가 있을 때만
  진짜 네임스페이스 격리를 제공하므로, WSL Ubuntu에서 실행해야 `code_experiment`나
  자작 스킬 실행이 의미 있게 격리됩니다.
- **Windows 쪽 venv(`.venv`)는 선택 사항**입니다. Windows 네이티브 Python으로도
  전부 동작은 하지만(테스트 포함), 그 경우 `sandbox.backend` 사다리는 bwrap/unshare를
  건너뛰고 Docker(있으면) 또는 격리되지 않은 plain subprocess로 폴백합니다 — 아래
  "보안 정직성 노트" 참고.
- Python 3.11+ (`zoneinfo` 표준 라이브러리 사용, `report.timezone` 기본값
  `Asia/Seoul`).
- 외부 LLM API 키 (OpenAI 호환 엔드포인트) — 없어도 `--mock` 모드로 전체 파이프라인을
  돌려볼 수 있습니다.

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

`config.json`에서 최소한 다음을 채웁니다 (`soul/config.py`가 로드·검증):

- `llm.base_url` — OpenAI 호환 chat completions 엔드포인트. 기본값은
  `https://api.openai.com/v1`이지만 로컬 Ollama 등 어떤 OpenAI 호환 서버로도
  바꿀 수 있습니다 (특정 벤더에 락인하지 않음).
- `llm.model` — 사용할 모델 이름.
- `llm.api_key` 또는 `llm.api_key_env` — 키 해석 순서는 **① `llm.api_key`에 직접
  기입 → ② `llm.api_key_env`로 지정한 환경변수 → ③ 없으면 키 없이 동작**
  (`soul/config.py:resolve_api_key`). 키가 없으면 Authorization 헤더 없이 요청하며,
  로컬 Ollama 같은 키 불필요 엔드포인트에 그대로 붙습니다. 기본 `api_key_env`는
  `OPENAI_API_KEY`.
- `llm.mock` — `true`면 실제 API 키 없이 `FakeLLM`으로 전체 파이프라인을 구동합니다
  (UI 개발·테스트용, API 비용 0).

**mock 모드**: `config.json`을 건드리지 않고도 커맨드에 `--mock`을 붙이면 그 실행만
FakeLLM으로 돕니다 (`run_agent.py --mock`, `run_web.py --mock`). API 키가 아예
없어도 이 방식으로 전체 흐름(스텝 생성 → 저널 → state.json → 트랜스크립트)을 확인할
수 있습니다.

## 실행

에이전트 루프와 API 서버는 **완전히 분리된 두 프로세스**이며, `data/` 디렉토리만
공유합니다 — 한쪽이 죽어도 다른 쪽은 영향을 받지 않습니다 (장애 격리).

### 에이전트 루프

```bash
python run_agent.py                # 장기 실행 스케줄러 (heartbeat 또는 continuous)
python run_agent.py --once         # 스텝 1회만 실행하고 종료
python run_agent.py --once --mock  # FakeLLM으로 1스텝 (API 키 불필요)
python run_agent.py --mock         # FakeLLM으로 장기 실행
```

기본은 `config.json`의 `agent.mode`(`heartbeat` 또는 `continuous`)를 따르는 장기
실행 스케줄러입니다. `agent.lock`을 프로세스 생존 기간 내내 들고 있으므로 동시에
두 번째 인스턴스를 띄우면 거부됩니다.

### 웹 API 서버

```bash
python run_web.py            # http://127.0.0.1:8000 (config.json web.host/port)
python run_web.py --mock     # 대화 응답도 FakeLLM으로
```

### 재시작 래퍼 스크립트

`scripts/start_agent.ps1`, `scripts/start_web.ps1`은 각각 크래시 시 지수 백오프로
자동 재시작하는 PowerShell 래퍼입니다. 기본적으로 **WSL의 `.venv-wsl` Python으로
실행**하며(`wsl`과 `.venv-wsl`이 있을 때), `-NoWsl` 스위치를 주면 Windows 쪽
venv(`.\.venv\Scripts\python.exe`)로 폴백합니다. WSL 셸 안에서 직접 돌린다면
스크립트 없이 `run_agent.py`/`run_web.py`를 실행해도 됩니다 (동일한 재시작
패턴이 필요하면 bash `while` 루프로 구성).

## 관찰하기

`http://127.0.0.1:8000`에 접속하면(웹 서버 실행 중이어야 함):

- **방/캐릭터**: Phaser 3 기반의 작은 방에서 캐릭터가 현재 행동(`action`)에 따라
  책상/책장/창가/컴퓨터/작업대/우편함/침대 등의 위치로 이동하고 애니메이션이
  바뀝니다. 흥미도(1~10)는 표정 강도로, 최근 결정(`deepen`/`new`/`shelve`/
  `abandon`)은 1회성 이펙트로 드러납니다 (매핑 규칙: `soul/web/static/js/mapping.js`).
- **영혼 성장(soul) 패널**: 현재 SOUL.md 전문 + git 히스토리 타임라인 + 커밋별 diff.
  SOUL.md는 에이전트 프로세스만 고쳐 쓰고, 모든 변경이 데이터 git 저장소에 커밋되므로
  "영혼의 성장사"를 diff로 볼 수 있습니다.
- **사고 과정(step 상세) 탭**: 스텝별 ACT/REFLECT(그리고 도구 라운드) LLM 왕복 전문을
  그대로 열람합니다 (`GET /api/step/{id}/transcript`).
- **위키**: 에이전트가 스스로 쓴 `wiki_write` 노트를 검색(FTS5)·백링크·그래프로
  탐색합니다.
- **일일 리포트**: 매일 지정 시각(`report.time`, 기본 22:00 `Asia/Seoul`)에 생성되는
  한국어 1인칭 회고를 날짜별로 열람합니다.
- **대화**: 에이전트와 채팅할 수 있습니다. 진행 중이던 백그라운드 작업은 LLM 호출
  경계에서 멈췄다가 대화가 끝나면 그 지점부터 이어집니다(선점).
  **`record`가 꺼져 있으면(기본값) 이 대화는 어디에도 저장되지 않고, 다음 wake에도
  전달되지 않습니다 — UI에도 "기억되지 않음"이라고 명시됩니다.** `record=true`로
  켜야만 `chat/recorded.jsonl`에 남고, 관찰자 inbox를 통해 다음 wake의 컨텍스트에
  들어갑니다.
- **선물/메시지(inbox)**: 관찰자가 텍스트나 URL을 남기면, 다음 wake 스텝의 컨텍스트에
  "관찰자가 남긴 것"으로 중립적으로 전달됩니다. 반응할지 말지는 에이전트 자유입니다.
- **말과 행동(stated vs revealed)**: 자기 보고 흥미도(stated)와, 저널에서 순수하게
  파생 계산한 행동 신호(revealed — 스레드 지속 길이, shelve 후 복귀 여부, 주제
  재등장 빈도)를 나란히 보여줍니다. 둘의 괴리는 숨기지 않고 그대로 노출합니다.

## MCP 등록

읽기 전용 MCP 서버(`run_mcp.py`)를 Claude Code 등 외부 AI에 등록하면, 그 AI가
`wiki_search`/`wiki_read`/`wiki_list`/`read_soul`/`query_journal`/`read_report`/
`read_transcript` 도구로 이 에이전트의 데이터 디렉토리를 구조적으로 진단할 수
있습니다.

```bash
claude mcp add soul-wiki -- python run_mcp.py --data-dir ./data
```

이 서버는 SOUL.md/저널/리포트/트랜스크립트를 파일로 직접 읽고, 위키 인덱스는
`mode=ro` SQLite 연결로만 엽니다 — 데이터 디렉토리를 절대 쓰지 않습니다(쓰기 주체는
에이전트 프로세스 하나뿐이라는 원칙 유지). 위키 인덱스가 아직 없으면 기본적으로는
직접 재빌드하지 않고 에이전트를 한 번 실행하라는 안내 메시지를 돌려주며,
`--allow-index-rebuild`를 명시적으로 줄 때만 예외적으로 (md 원본이 아닌) 파생
인덱스만 재빌드합니다.

## 테스트

WSL 기준(`.venv-wsl`)으로:

```bash
pytest
```

186개의 테스트가 전부 green이어야 합니다. `tests/conftest.py`의 `data_paths`/
`config` 픽스처가 `tmp_path`에 초기화된 데이터 디렉토리와 mock 모드 설정을
제공하므로, 테스트는 실제 네트워크나 실제 `./data`를 건드리지 않습니다.

## 보안 정직성 노트

- **샌드박스 격리는 플랫폼에 따라 실제로 다릅니다.** `soul/agent/sandbox.py`의
  격리 사다리는 (1) Linux 네이티브 `bwrap`(없으면 `unshare`) → (2) Docker(데몬이
  떠 있을 때) → (3) plain subprocess 순으로 선택됩니다. **WSL Ubuntu에서 실행하면
  보통 1번(bwrap/unshare, 네트워크·PID·마운트 네임스페이스 격리)이 선택**되지만,
  **Windows 네이티브 폴백은 격리가 아닌 plain subprocess**입니다 — 코드 자체가
  `isolated=False`로 정직하게 표시하고, 저널의 `sandbox_backend` 필드와 기동 로그에도
  실제 선택된 백엔드가 그대로 기록됩니다. 강한 격리가 필요하면 WSL을 쓰거나 Windows에
  Docker를 띄우세요.
- 이 규칙은 자작 스킬 실행(`skill_runner.py`)에도 동일하게 적용됩니다 — 스킬은
  에이전트 프로세스에 import되지 않고 항상 별도 subprocess로, 위와 같은 샌드박스
  사다리를 그대로 통과합니다.
- **DuckDuckGo 검색 결과에는 광고/스폰서 링크가 섞여 있을 수 있습니다.**
  `web_search`는 `html.duckduckgo.com/html`의 결과 HTML을 그대로 파싱하며, 도메인
  차단 목록을 두지 않습니다(중립성 원칙 — 어떤 검색어·URL을 고를지는 전적으로
  에이전트 자유). 크기(`max_page_kb`, 기본 500KB)와 시간(`http_timeout_seconds`,
  기본 20초) 상한만 안전장치로 존재합니다.
- 에이전트가 방문한 URL은 전부 저널의 `web_visits` 필드에 남습니다.
