# Plan Instruction — "Soul Tamagotchi" (자율 에이전트 키우기)

> 이 문서 전체를 Claude Code의 plan 모드 프롬프트로 사용한다.
> 지금 단계의 산출물은 **구현 계획(plan)** 이다. 코드를 먼저 쓰지 말 것.

## 1. 프로젝트 목표

스스로 관심사를 찾고, 꽂히면 파고들고, 지루하면 버리며, 그 선택의 누적으로
자기만의 결("영혼")을 만들어가는 **자율적 에이전트**를 만든다.
사람이 방향을 미리 심어주지 않는다. 성격은 완전 백지에서 시작하고,
에이전트가 살아가며 스스로 되어간다.

그리고 이 존재를 사람이 **다마고치를 키우듯 관찰·교감할 수 있는 웹 서비스**를 만든다.

## 2. 하드 제약 (계획이 반드시 지켜야 함)

1. SOUL.md / MCP 등을 활용할 수 있다.
2. **행동은 외부 LLM API 호출로 한다.** OpenAI-호환 엔드포인트(chat completions)를
   사용하며, 기본 타깃은 로컬 Ollama(`base_url` 설정 가능)다. 특정 벤더에 락인하지
   말고 `base_url` / `model` / `api_key`를 설정으로 분리한다.
3. **에이전트 루프는 로컬 파이썬 스크립트다.** 데몬/스케줄러 포함 전부 로컬에서 돈다.
   외부 에이전트 프레임워크(LangChain 류의 무거운 스캐폴딩) 없이, 표준 라이브러리 +
   최소한의 의존성으로 직접 구현한다.
4. **웹 기반 조회 서비스를 제공한다.** 에이전트의 현재 상태·활동·역사를 브라우저로
   볼 수 있어야 한다.
   - **API 서버 + 웹 프론트 분리 구조**로 만든다. 웹 UI는 API의 클라이언트 중 하나일
     뿐이며, 나중에 이 프로그램을 서버로 두고 모바일 앱이 같은 API로 접속하는 시나리오를
     처음부터 고려한다 (UI 전용 로직을 API에 섞지 말 것).
5. **웹 UI는 대시보드일 뿐만 아니라 "키우기" 인터페이스다.** 다마고치/Gather Town처럼,
   에이전트가 캐릭터로 존재하는 작은 공간(방/마을)에서 지금 무엇을 하는지 보이고,
   기분·흥미 상태가 표정/행동으로 드러나는 형태. 표·로그 나열이 기본 화면이 되면 안 된다
   (raw 로그는 보조 화면으로만).

## 3. 영혼 철학 (설계 원칙)

- **백지 시작**: SOUL.md(또는 동등한 정체성 파일)는 거의 비어 있는 상태로 시작한다.
  취향·성격·관심사를 시드로 넣지 않는다.
- **흥미는 진짜 신호**: 매 스텝마다 에이전트가 스스로 흥미도(1~10)를 평가하고,
  deepen / shelve / abandon / new 중 하나를 결정한다. 이 결정의 누적이 성격이 된다.
- **자기 서술의 소유권**: SOUL.md는 에이전트 자신만이 고쳐 쓴다. 변경은 git으로
  버전 관리하여 "영혼의 성장사"를 diff로 볼 수 있게 한다.
- **정직한 프레이밍**: 이것은 자기주도적 흥미를 *시뮬레이션*하는 시스템이지,
  문자 그대로의 영혼 주입이 아니다. UI 문구도 과장하지 않는다.
- **관찰자 개입 최소화**: 웹 UI에서 사람이 할 수 있는 상호작용(말 걸기, 선물처럼
  "읽을거리 던져주기" 등)을 넣더라도, 에이전트가 무시할 자유를 보장한다.

## 4. 시스템 구성요소 (계획에서 구체화할 것)

### A. 에이전트 코어 (Python)
- **wake 루프**: 회상(SOUL.md + 최근 기록 로드) → 행동 1개 실행 → 흥미 자기평가 →
  결정(deepen/shelve/abandon/new) → 기록 저장 → durable하면 SOUL.md 갱신 + git 커밋.
- **스케줄링**: heartbeat 주기 실행 + 매일 지정된 시간에 지정된 언어로 1인칭 회고 리포트 생성.
  파이썬 내 스케줄러로 할지 시스템 cron으로 할지, 겹침 방지(lock)를 어떻게 할지 계획에 명시.
  - **연속 모드(무한루프)도 지원**: "30분마다 한 번" 같은 주기 실행 외에, 진행 중인
    스텝이 끝나는 즉시 다음 스텝을 시작하는 모드. 주기 모드 ↔ 연속 모드는 설정으로 전환.
- **대화 선점(preemption)**: 에이전트가 백그라운드 작업 중일 때 유저가 대화를 요청하면,
  진행 중인 LLM 작업을 현재 지점까지만 마치고 중단한 뒤 유저 대화를 먼저 처리한다.
  유저가 대화 종료를 알리거나 타임아웃이 지나면 자동으로 원래 작업으로 복귀.
  중단 지점의 상태 보존·복원 방식을 계획에 명시할 것.
- **행동(action) 공간**: 백지 존재가 실제로 "할 수 있는 일"의 목록(예: 웹 검색/읽기,
  글쓰기, 메모 정리, 코드 실험 등)을 무엇으로 시작할지, 어떻게 안전하게 샌드박싱할지 제안.
  행동 공간 자체가 성격을 유도하지 않도록 중립적으로 설계할 것.
  - **웹 검색**: DuckDuckGo 기반으로 단순하게 직접 구현한다 (별도 API 키 불필요).
  - **논문 검색**: arXiv API로 논문 검색·초록 읽기 기능을 넣는다.
- **스킬 시스템 (자기 기능강화)**: 에이전트가 스스로 스킬(행동 확장 모듈)을 작성·등록해
  자기 행동 공간을 넓힐 수 있게 한다. 단, **기본(내장) 스킬은 변경 불가**(읽기 전용)이고,
  자작 스킬은 별도 디렉토리에 저장해 git으로 버전 관리한다. 자작 스킬의 로딩·실행
  샌드박싱과 실패 격리(스킬이 죽어도 루프는 살게) 방식을 계획에 포함할 것.
- **LLM 클라이언트**: OpenAI-호환. 재시도, 타임아웃, 컨텍스트 예산 관리 포함.

### B. 상태·기억 저장
- 활동 기록(스텝별 로그), 흥미 추세, 리포트를 저장할 스토리지 선택(SQLite vs JSONL 등)과
  스키마를 계획에 포함.
- SOUL.md + git 히스토리 = 정체성. 저장소 = 사건 기록. 이 둘의 역할 분리를 유지.
- 상태 기록과 SOUL.md 등 대상 에이전트의 저장을 한개의 디렉토리에서 하여, 다른 AI (like claude code) 에 통째로 import 하여 문제가 발생할 시 빠르게 진단할 수 있도록 한다.

### C. 웹 서비스
- **백엔드**: 에이전트 상태를 읽는 API(FastAPI 등 경량 제안). 실시간 갱신 방식
  (SSE vs WebSocket vs polling) 비교 후 선택.
  - API는 웹 UI와 독립적으로 설계한다(모바일 앱 등 다른 클라이언트 대비).
    대화 요청·대화 종료·상태 구독 등 "키우기" 상호작용도 전부 API로 노출할 것.
- **프론트엔드**: 캐릭터가 있는 작은 공간. 최소 요구:
  - 현재 활동이 캐릭터의 행동/위치/말풍선으로 표현됨 (예: 책상에 앉아 있으면 "읽는 중")
  - 흥미도·기분이 시각적으로 드러남 (표정, 이펙트 등)
  - "영혼 성장" 뷰: SOUL.md 현재본 + git diff 타임라인
  - 일일 회고 리포트 열람 (한국어 1인칭)
  - 에이전트와 대화할 수도 있도록 하기 (다만, 이것이 기록될지 아닐지는 유저의 자유로 두기)
  - (선택) 가벼운 상호작용: 말 걸기 / 읽을거리 주기 — 에이전트의 다음 wake에
    "관찰자가 남긴 것"으로 전달되고, 반응 여부는 에이전트 자유
  - 기술 선택(순수 HTML/JS vs 경량 프레임워크 vs Phaser 같은 2D 엔진)을 트레이드오프와 함께 제안. 과한 게임 엔진 도입보다 빨리 돌아가는 단순한 것 우선.

## 5. 계획 단계에서 반드시 답해야 할 질문

계획서에 아래 각 항목에 대한 결정과 근거를 포함할 것:

1. 프로젝트 디렉터리 구조와 모듈 분리 (agent / storage / web / config)
2. wake 한 스텝의 프롬프트 구조 초안 — 백지 철학을 깨지 않으면서 자기평가·결정을
   구조화 출력(JSON)으로 받는 방법
3. 흥미/결정 데이터의 스키마와, 웹 UI가 이를 캐릭터 상태로 매핑하는 규칙
4. 에이전트 루프와 웹 서버의 프로세스 구성 (단일 프로세스 vs 분리 + 공유 스토리지)
5. 장애 시나리오: LLM 다운, 루프 크래시, 스텝 겹침, git 커밋 경합 — 각각의 대응
6. 설정 파일 항목 — **형식은 JSON으로 확정**. 항목(base_url, model, api_key,
   heartbeat 주기 vs 연속 모드, 대화 타임아웃, 타임존, 리포트 시각 등)을 계획에 명시
7. 대화 선점의 구현 — 루프 중단 신호 전달, 중단 지점 상태 보존, 타임아웃 후 복귀 방식
8. 자작 스킬의 인터페이스 규격, 저장 위치, 로딩 방식, 샌드박싱과 실패 격리
9. 구현 순서(마일스톤): 최소 루프 → 저장 → 리포트 → API → UI 순의 단계별 완료 기준
10. 테스트 전략: LLM 목킹으로 루프 로직 검증하는 방법

## 6. 비목표 (지금은 안 함)

- 멀티 에이전트, 에이전트 간 대화
- 클라우드 배포, 인증/멀티유저
- 음성, 3D
- Hermes와의 호환성

## 7. 산출물 형식

- 위 5절의 질문에 전부 답한 **구현 계획서** (마일스톤별로 파일 단위 작업 목록 포함)
- 불확실하거나 사용자 결정이 필요한 지점은 "질문" 섹션으로 분리해서 제시
- 계획 승인 전에는 코드를 작성하지 않는다

---

# 구현 계획서 (Part 2 — 위 스펙에 대한 답)

> 위 §5의 질문 10개에 대한 결정과 근거. 답 위치: 1→P1, 2→P2, 3→P4, 4→P5, 5→P5,
> 6→P6, 7→P7, 8→P8, 9→P9, 10→P10.

## P0. 확정 사항 및 핵심 결정

**사용자 확정 사항:**
- LLM: 외부 OpenAI-호환 API 기본 타깃 (base_url/model/api_key 설정 분리, Ollama 전환 가능)
- 프론트: **Phaser 3** (CDN + 순수 JS, 빌드 도구 없음)
- 행동 공간: 오프라인 행동 + **웹 검색(DuckDuckGo 직접 구현) + arXiv 논문 검색** (스펙 개정으로 v1 포함)
- 아트: CC0 픽셀 에셋 팩 (Kenney.nl 등)
- heartbeat 기본 30분 (+ 연속 모드 설정 전환)
- 프롬프트는 **영어**, 일일 리포트는 한국어 1인칭
- code_experiment/스킬 실행: 격리 가능하면 격리 — Linux는 bwrap/unshare 네이티브, Windows는 Docker, 최후 폴백 subprocess
- **흥미 철학 보완(검토 반영)**: stated/revealed 흥미 분리 측정, 상대 앵커, 환경 우연성, reason→decision 필드 순서
- **지식 위키 + MCP**: 검색 가능한 위키(md 원본 + SQLite FTS 인덱스) + 외부 AI용 읽기 전용 MCP 서버
- **사고 과정 관찰**: 스텝별 LLM 왕복 전문 트랜스크립트 보존, UI/API/MCP 열람

| 항목 | 결정 | 근거 |
|---|---|---|
| 스토리지 | JSONL + Markdown + state.json (SQLite는 위키 파생 인덱스만) | "한 디렉토리 통째 import 진단" → 사람/AI가 그대로 읽는 텍스트. 데이터량 극소 |
| 스케줄링 | Python 내부 루프(장기 실행) + 락파일, 주기/연속 모드 겸용 | Windows에 cron 없음. 프로세스 상주가 연속 모드·선점에도 필수 |
| 프로세스 | 에이전트 루프 / API 서버 **2개 프로세스 분리**, 데이터 디렉토리 공유 | 장애 격리(루프 죽어도 UI 생존), sync 루프 + async 웹 동시성 단순화 |
| API 우선 | 모든 상호작용(대화 시작/종료, 구독, 선물)을 REST/SSE로 노출, 웹 UI는 클라이언트 중 하나 | 모바일 앱 등 다른 클라이언트 대비 (스펙 §2.4) |
| 실시간 갱신 | SSE (EventSource) | 저빈도·단방향 이벤트에 부합. WebSocket 양방향 불필요, 폴링 낭비 |
| 대화 | API 서버가 즉시 LLM 직접 호출 + **선점 프로토콜**(P7) + 기록 여부 유저 토글 | 즉시 응답 + "에이전트가 하던 일을 멈추고 응대"의 양립 |
| 설정 | **JSON** (`config.json`, stdlib `json`) | 스펙 §5.6 확정 |
| 의존성 | `fastapi`, `uvicorn`, `httpx`, `mcp` 4개 | 에이전트 코어는 httpx 외 표준 라이브러리. sqlite3/xml/html 파서는 stdlib |

## P1. 디렉터리 구조와 모듈 분리

### 소스 저장소 (`tamagotchi/`)

```
tamagotchi/
├── config.example.json        # 커밋 / config.json은 .gitignore
├── requirements.txt           # fastapi, uvicorn, httpx, mcp (dev: pytest)
├── run_agent.py               # 진입점: 에이전트 루프 (--once, --mock 플래그)
├── run_web.py                 # 진입점: API 서버
├── run_mcp.py                 # 진입점: 지식 MCP 서버 (stdio, 읽기 전용)
├── scripts/start_agent.ps1    # 크래시 자동 재시작 while 래퍼
├── scripts/start_web.ps1
├── soul/                      # Python 패키지
│   ├── config.py              # config.json 로드+검증 (dataclass)
│   ├── paths.py               # 데이터 디렉토리 경로/초기화
│   ├── agent/
│   │   ├── loop.py            # wake 스텝 오케스트레이션 (심장) + 선점 체크포인트
│   │   ├── scheduler.py       # 주기/연속 모드 루프 + 리포트 시각 트리거
│   │   ├── llm.py             # OpenAI-호환 클라이언트 (재시도/타임아웃/tool 루프/트랜스크립트)
│   │   ├── prompts.py         # 영어 프롬프트 템플릿 (백지 철학의 핵심)
│   │   ├── actions.py         # 내장 행동 정의 + 부수효과 (읽기 전용 = 소스 repo 소속)
│   │   ├── webtools.py        # web_search(DuckDuckGo)/web_read/arxiv_search 도구
│   │   ├── skills.py          # 자작 스킬 로딩/등록/실패 격리 (P8)
│   │   ├── skill_runner.py    # 스킬 실행 러너 (subprocess 경유, 샌드박스 사다리)
│   │   ├── preempt.py         # 대화 선점: control 파일 감시, 스냅샷 저장/복원 (P7)
│   │   ├── context.py         # 컨텍스트 조립 (SOUL.md+최근스텝+스레드+inbox+세렌디피티)
│   │   ├── soul.py            # SOUL.md 읽기/쓰기 + git 커밋
│   │   ├── report.py          # 일일 한국어 1인칭 회고
│   │   ├── sandbox.py         # 격리 백엔드 사다리 (code_experiment/스킬 공용)
│   │   └── lock.py            # agent.lock (pid+timestamp, stale 탈취)
│   ├── storage/
│   │   ├── journal.py         # steps JSONL append/tail + revealed_interest 파생 지표
│   │   ├── state.py           # state.json 원자적 쓰기 (tmp+os.replace)
│   │   ├── inbox.py           # pending→delivered 큐
│   │   ├── control.py         # data/control/ 신호 파일 (chat.json, paused_step.json)
│   │   └── chatlog.py
│   ├── knowledge/
│   │   ├── wiki.py            # 위키: md 원본 CRUD + [[링크]] 파싱 + SQLite FTS5 인덱스 + rebuild
│   │   ├── tools.py           # LLM function calling 도구 스키마+디스패처 (wiki+web+skill)
│   │   └── mcp_server.py      # 읽기 전용 MCP 서버 (외부 AI 진단용)
│   └── web/
│       ├── server.py          # FastAPI 앱 + StaticFiles (UI는 정적 파일일 뿐, API에 UI 로직 없음)
│       ├── api.py             # REST 라우트
│       ├── events.py          # SSE (state.json mtime 감시)
│       ├── chat.py            # 대화 세션 + 선점 신호 발행 + 기록 토글
│       ├── gitview.py         # SOUL.md git log/diff (read-only)
│       └── static/            # 웹 클라이언트 (API의 클라이언트 중 하나)
│           ├── index.html     # Phaser 3 CDN <script>
│           ├── js/{main,api,room_scene,mapping,panels}.js
│           └── assets/        # CC0 픽셀 스프라이트/타일
└── tests/                     # conftest, fake_llm + 모듈별 테스트
```

### 데이터 디렉토리 (에이전트의 "몸", 기본 `./data/`, gitignore)

**자체 git 저장소** — 소스와 분리, `data/`만 다른 AI에 통째 import하면 진단 가능.

```
data/
├── .git/                      # 영혼 성장사 전용 git
├── SOUL.md                    # 정체성 (에이전트만 수정, 거의 빈 상태로 시드)
├── state.json                 # UI용 현재 스냅샷 (커밋 안 함)
├── journal/steps-YYYY-MM.jsonl  # 월별 로테이션, 스텝당 1줄
├── notes/                     # 활동 산출물 .md
├── wiki/                      # 지식 베이스: 페이지당 md 1개, [[링크]] 네트 (git 커밋)
├── index/wiki.sqlite3         # FTS5+링크 그래프 파생 인덱스 (커밋 안 함, 재빌드 가능)
├── skills/<name>/             # 자작 스킬: manifest.json + skill.py (git 커밋) — P8
├── sandbox/                   # code_experiment 작업 디렉토리
├── reports/YYYY-MM-DD.md      # 일일 한국어 회고
├── inbox/{pending,delivered}.jsonl  # 관찰자 메시지/선물 큐
├── chat/recorded.jsonl        # 기록 동의된 대화만
├── transcripts/step-*.jsonl   # 스텝별 LLM 왕복 전문 (chain of thought — P2.5)
├── control/                   # 프로세스 간 신호: chat.json, paused_step.json (커밋 안 함)
├── logs/agent.log             # 운영 로그
└── agent.lock
```

역할 분리: SOUL.md + git = 정체성 / journal = 사건 기록. `soul.py`만 SOUL.md에 쓴다.
커밋 대상: SOUL.md, notes/, wiki/, skills/, reports/ (+리포트 시 하루 1회 저널 동반 커밋).

## P2. wake 스텝 프롬프트 구조

```
회상(context.py) → [호출1 ACT] 행동 선택+수행 (도구 tool-use 루프, 최대 5라운드)
                → 산출물 notes/ 저장
                → [호출2 REFLECT] 흥미 자기평가+결정 JSON (도구 없음)
                → 저널 append → state.json 갱신 → (soul_update 시) SOUL.md 갱신+커밋
```

행동/평가 분리 이유: 자유 서술과 구조화 JSON 혼합 시 파싱 취약, 완성된 산출물을 보고 평가하는 게 더 정직함.

### 백지 철학 프롬프트 원칙 (영어 프롬프트)
- 시스템 프롬프트는 상황·메커니즘만 서술. 성격 형용사("curious" 등)·예시 주제 금지
- 행동 목록은 매 스텝 **순서 무작위 셔플** (위치 편향 방지)
- 4가지 decision을 대칭적 한 줄 중립 정의로만 제시
- 흥미 척도는 양 끝점만 앵커 (1 = not drawn at all, 10 = strongly drawn) + **상대 앵커 병행**: "직전 평가 대비 더/덜/비슷하게 끌리는가"(`interest_delta`)를 함께 물어 LLM 자기평가의 중앙 쏠림(6~8 뭉침)을 완화하고 시계열에 실제 등락을 만든다
- **reason을 decision보다 먼저** 쓰게 배치 (이유→결정 순서로 사후 합리화 완화)
- soul_update는 "durable한 것이 생겼을 때만 true, 불확실하면 false가 기본"

### ACT 응답 JSON
```json
{"action": "<목록 중 하나>", "topic": "<한 줄>", "content": "<수행 결과 전문 markdown>"}
```

### REFLECT 응답 JSON (필드 순서 의도적: reason이 decision보다 앞)
```json
{"interest": 1-10, "interest_delta": "more|less|same|first",
 "mood": "neutral|curious|excited|calm|bored|frustrated|tired|proud",
 "reason": "...", "decision": "deepen|shelve|abandon|new", "summary": "<한 줄>",
 "soul_update": {"update": false, "content": "<true일 때 SOUL.md 새 전문>", "reason": "..."}}
```
REFLECT user 메시지에 "이 스레드의 직전 흥미 평가"를 제시해 interest_delta의 비교 기준을 준다. delta와 절대값이 모순되면 둘 다 원문 보존 — 모순 자체도 관찰 데이터.

### P2.5 사고 과정(chain of thought) 관찰 가능성

- **트랜스크립트 보존**: `llm.py`가 스텝의 모든 LLM 왕복(messages 전문, 도구 라운드별 tool_calls·결과, 원시 응답)을 `data/transcripts/step-XXXXXX.jsonl`(호출 1건=1줄)로 저장. 저널에 `transcript_path` 연결. 회상에 무엇이 들어갔고 무엇이 나왔는지 재구성 가능
- **reasoning 토큰 캡처**: 응답에 `reasoning_content`/`reasoning` 필드가 있으면 그대로 보존. 없으면 프롬프트로 유도하지 않음(강제 "생각 서술" 필드는 성능·중립성 훼손 — reason 필드가 최소한의 명시적 근거)
- **열람 경로 3곳**: ① UI 스텝 상세 "사고 과정" 탭 ② `GET /api/step/{id}/transcript` ③ MCP `read_transcript(step_id)`
- git 커밋 안 함(용량·잡음), 월별 하위 폴더. chat도 record=true면 동일 보존

### stated vs revealed 흥미 분리 (철학 보완의 핵심)

자기 보고 interest는 **자기 보고(stated)**로 취급하고, **진짜 신호는 행동의 누적(revealed)**에서 별도 산출 — LLM 자기평가의 긍정 편향·confabulation 대응.

- revealed 지표(저널에서 순수 함수로 파생, LLM 무관): 스레드 지속 길이 / shelve 후 실제 복귀 여부·횟수 / 같은 주제 재등장 빈도
- 계산 위치: `journal.py`의 `revealed_interest(steps)` — 저장하지 않고 조회 시 계산
- stated vs revealed **괴리는 1급 관찰 데이터**: API·UI에 나란히 노출, 일일 리포트 컨텍스트에도 포함해 에이전트가 자기 말과 행동의 괴리를 스스로 보게 한다

### 환경 우연성 (모델 prior 수렴 완화)

같은 모델·같은 백지는 모델 기본 페르소나로 수렴할 위험 → 주제를 심지 않는 무작위성을 환경에서 공급 (개체성 = prior + 경로의 우연):
- 행동 목록 셔플
- **과거 노트 무작위 재부상**: 회상 조립 시 낮은 확률(`serendipity_rate` 0.3)로 과거 노트 1개를 "a note you wrote before"로 포함
- 관찰자 inbox는 설계상 이미 외부 우연
- 전부 주제 중립적(내용으로 고르지 않고 무작위 추첨) — 백지 철학과 충돌 없음

### JSON 견고성 3단계 폴백
`response_format: json_object` → 실패 시 최외곽 `{…}` 정규식 추출 → 교정 재호출 1회 → error 스텝 기록 후 스킵. interest는 clamp(1,10), enum 밖 값은 neutral 정규화 + `raw` 보존.

## P3. 행동 공간 v1 (중립 동사)

내장 행동: `free_write / revisit_notes / organize_notes / thought_experiment / code_experiment / web_explore / read_inbox(inbox 있을 때만) / rest` + 자작 스킬 `skill:<name>` (enabled인 것만, 중립 나열)

### 웹 도구 (web_explore 중 tool-use 루프에서 사용 가능)
- `web_search(query)`: DuckDuckGo HTML 엔드포인트(html.duckduckgo.com/html) 직접 파싱, API 키 불필요. 상위 N개 제목/URL/스니펫 반환
- `web_read(url)`: httpx fetch + stdlib html.parser 기반 본문 텍스트 추출, `max_page_kb`(기본 500KB) 상한, 타임아웃 20초
- `arxiv_search(query)`: arXiv Atom API(export.arxiv.org/api/query) + `xml.etree` 파싱 — 제목/저자/초록 반환
- 안전: 도메인 차단 목록 없음(중립성) 대신 크기·시간 상한, 방문 URL 저널 기록. 검색어·URL은 전적으로 에이전트 선택

### code_experiment / 스킬 실행 격리 — 백엔드 사다리 (`sandbox.py`, `backend:"auto"`)
1. **Linux 네이티브 (최우선, Docker 불필요)**: `bwrap`(bubblewrap) — `--unshare-all --die-with-parent --bind data/sandbox /work ...`, 비루트 네임스페이스 격리(네트워크·PID·마운트 차단), 데몬 없음, 오버헤드 ~ms. bwrap 없으면 `unshare --user --net --pid --map-root-user` 폴백. unprivileged userns 차단 배포판이면 다음 단계
2. **Docker** (`docker info` 성공 시): `--network none`, 볼륨 마운트, `--memory`/`--pids-limit` — Windows에선 유일한 강격리
3. **plain subprocess 폴백**: cwd 한정, 환경변수 최소화, 타임아웃 — 격리 아님을 명시

공통: 타임아웃(기본 10초), stdout/stderr 캡처. 선택된 백엔드를 기동 로그와 저널 `sandbox_backend`에 기록.

## P3.5 지식 저장소 — 위키 (검색 가능한 네트)

markdown 노트만으로는 검색이 안 되는 문제의 대응.

### 저장 구조 (원본 md + 파생 SQLite — 진단성·검색성 양립)
- **원본**: `data/wiki/<slug>.md` — frontmatter + 본문, `[[다른-페이지]]` 링크로 llm-wiki 스타일 네트. git 커밋(지식 성장도 diff로 관찰)
- **파생 인덱스**: `data/index/wiki.sqlite3` — `pages`, `links(src,dst)`(백링크 그래프), FTS5 `pages_fts`. **항상 md에서 전체 재빌드 가능**(`rebuild_index()`, 기동 시 mtime 불일치 감지 자동 재빌드). 커밋 안 함
- sqlite3·FTS5는 stdlib — 의존성 0

### 에이전트 접근: function calling 도구 루프
ACT 호출을 표준 chat completions `tools` 기반 **소형 tool-use 루프**로 (프레임워크 불필요):
- wiki 도구 4종: `wiki_search`(FTS) / `wiki_read`(본문+백링크) / `wiki_write`(생성/갱신, [[링크]] 자동 인덱싱) / `wiki_backlinks`
- 루프: tool_calls → 디스패치 → 결과 append → 재호출, 최대 `max_tool_rounds`(기본 5) 후 최종 ACT JSON 강제
- 도구 설명 중립("store something you want to find again"), 쓰기/안 쓰기는 에이전트 자유
- REFLECT는 도구 없음(평가 오염 방지). 저널에 `wiki_ops` 기록

### 외부 접근: 읽기 전용 MCP 서버 (`run_mcp.py`)
Claude Code 등 외부 AI의 구조적 진단용. 공식 `mcp` Python SDK.
- 도구: `wiki_search`, `wiki_read`, `wiki_list`, `read_soul`, `query_journal(limit, since)`, `read_report(date)`, `read_transcript(step_id)`
- **읽기 전용** — 쓰기 주체는 에이전트 프로세스 하나 원칙 유지. SQLite도 read-only 연결
- 등록: `claude mcp add soul-wiki -- python run_mcp.py --data-dir ./data`

## P4. 저널 스키마 & UI 매핑

### 스텝 레코드 (JSONL 1줄)
```json
{"id":"step-000123","ts":"...","kind":"wake_step|report|error","action":"...","topic":"...",
 "thread_id":"th-0007","content_path":"notes/....md","interest":7,"interest_delta":"more",
 "mood":"curious","reason":"...","decision":"deepen","summary":"...",
 "soul_updated":true,"soul_commit":"abc1234","serendipity_note":"notes/....md",
 "transcript_path":"transcripts/step-000123.jsonl",
 "wiki_ops":[{"tool":"wiki_write","slug":"..."}],"web_visits":["https://..."],
 "skill_used":null,"sandbox_backend":null,"preempted":false,
 "inbox_delivered":["in-0004"],"llm":{"model":"...","tokens_in":0,"tokens_out":0,"latency_ms":0},"error":null}
```

스레드 규칙: deepen→같은 thread_id 유지, shelve→state.json shelved 목록 보관, abandon/new→다음 스텝 새 thread_id.

### state.json (단일 스냅샷, 원자적 교체)
`status(awake|idle|chatting|error), last_step 요약, current_thread{topic,steps,interest_series}, shelved_threads, revealed{top_threads,stated_vs_revealed_note}, next_wake_at, today_report, updated_at`

### 매핑 규칙 (`mapping.js` 단일 소스)
- **행동→위치/애니메이션**: free_write=책상·쓰기 / revisit_notes=책장·읽기 / organize_notes=책장·정리 / thought_experiment=창가 러그·생각구름 / code_experiment=컴퓨터·타이핑 / web_explore=창가 노트북·스크롤 / skill:*=작업대·공구질 / read_inbox=우편함·열기 / rest=침대·Zzz / chatting=문 앞·대화 모션 / idle=배회 / stale·error=중앙 정지+"…"
- **interest→표정 강도**: 1–3 처짐·저채도 / 4–6 중립 / 7–8 미소·반짝 / 9–10 큰 반짝+파티클
- **decision→1회 이펙트**: deepen=전구+불꽃 / new="!"+자리이동 / shelve=노트 꽂기 / abandon=종이 구겨 버리기
- **말풍선**: last_step.summary 30초 표시, 클릭 시 산출물 전문 패널. wiki 쓰기 있던 스텝은 책상 위 "위키 노트" 소품 반짝임

## P5. 프로세스 구성 & 장애 대응

**2 프로세스**: `run_agent.py`(동기 루프) + `run_web.py`(uvicorn, API 서버). API 서버는 데이터 디렉토리 read-only, 예외적으로 inbox append + chat append + **control/chat.json**(선점 신호)만 씀. inbox는 `inbox.lock` 소형 락 + "웹은 append만, 에이전트는 스텝 시작 시 pending→delivered 원자적 이동" 프로토콜.

| 장애 | 대응 |
|---|---|
| LLM 다운/타임아웃 | 지수 백오프 3회(1s/4s/16s, 타임아웃 120s) → error 스텝 기록+스킵. 연속 5회 실패 시 서킷브레이커(간격 4배, 성공 시 복원). 연속 모드에서도 동일 적용 |
| 루프 크래시 | 스텝 단위 try/except 격리 + `start_agent.ps1` while 재시작(백오프). UI는 updated_at이 기준 간격 2배 초과 시 stale 표시 |
| 스텝 겹침/장기 스텝 | 단일 프로세스라 내부 겹침 불가. 이중 기동은 agent.lock(pid 생존 검사, stale 탈취)으로 거부. 주기 초과 스텝은 죽이지 않고 완주시키되 step_timeout_minutes(하드 데드라인)는 별도 적용, 종료 후 min_step_gap_seconds 경과 시 자동으로 다음 스텝 시작(아래 스케줄러 규칙) |
| git 경합 | 데이터 git 쓰기 주체는 에이전트 프로세스 하나뿐(웹·MCP는 읽기만). 커밋 실패 시 1회 재시도, 실패해도 파일은 갱신됨 → 다음 커밋에 포함 |
| state.json 파손 읽기 | tmp+os.replace 원자 교체, 웹은 파싱 실패 시 직전 캐시 유지 |
| 리포트 실패 | 날짜 파일 부재로 판정, 매 스텝 사이 재시도 (멱등) |
| 스킬 크래시 | P8 참조 — subprocess 격리 + 연속 실패 자동 비활성 |

**스케줄러** (`scheduler.py`): `while True: check_preempt(); check_report(); run_step(); wait()`.

**장기 실행 스텝 처리 원칙 — 주기 초과는 허용, 단 스텝 타임아웃은 별도로 존재.**

- **주기 초과 허용**: 스텝이 heartbeat 주기보다 오래 걸리는 것은 정상 동작이며 주기를 이유로 죽이거나 스킵하지 않는다. 대신 **최소 격리 간격**(`min_step_gap_seconds`, 기본 60초)을 보장한다:
  - 다음 스텝 시작 시각 = `max(이전 스텝 시작 + heartbeat 주기, 이전 스텝 종료 + min_step_gap_seconds)`
  - 예: 주기 10분인데 스텝이 12분 걸림 → 스킵하지 않고, 종료 후 60초 쉬고 자동으로 다음 스텝 시작
  - 예: 주기 10분에 스텝이 1분 걸림 → 정상적으로 시작 기준 10분 주기 유지
  - `mode:"continuous"`: 주기 항 없이 `이전 스텝 종료 + min_step_gap_seconds`만 적용 (두 모드가 같은 격리 파라미터 공유)
- **스텝 타임아웃** (`step_timeout_minutes`, 주기와 독립 — 예: 주기 10분/타임아웃 15분, 주기보다 크게 설정 권장): 스텝 시작부터의 하드 데드라인. 초과 시 스텝을 중단하고 그때까지의 부분 산출물·트랜스크립트를 보존한 채 `kind:"error"`, `error:"step_timeout"`으로 저널 기록 후 다음 스텝으로 진행. 폭주(무한 도구 루프, 스킬 행 등)의 최종 방어선이며, 개별 LLM 호출·도구 타임아웃보다 상위의 안전망
  - 집행 방식: 동기 루프이므로 각 LLM 호출/도구 실행 **경계마다 데드라인 검사** — 개별 호출 자체에 타임아웃(LLM 120초, 도구 10~20초)이 있으므로 경계 검사만으로 데드라인 초과가 한 호출 길이 이상 밀리지 않음
  - 서킷브레이커에는 집계하지 않음 (API 장애가 아니라 "작업이 길었음"이므로)
- 리포트 시각 체크는 두 모드 공통, `Asia/Seoul` `zoneinfo` 기준. state.json의 `next_wake_at`은 위 규칙으로 계산된 실제 예정 시각을 기록(UI가 정확한 카운트다운 표시)

## P6. 설정 — config.json (스펙 확정: JSON)

`config.example.json` 커밋 / `config.json` gitignore. JSON은 주석 불가 → 각 키 설명은 example 옆 README 표에 기재.

```json
{
  "llm": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini",
          "api_key_env": "OPENAI_API_KEY", "api_key": null,
          "timeout_seconds": 120, "max_retries": 3,
          "temperature": 1.0, "max_output_tokens": 2000, "mock": false},
  "agent": {"data_dir": "./data", "mode": "heartbeat", "heartbeat_minutes": 30,
            "min_step_gap_seconds": 60, "step_timeout_minutes": 45,
            "context_recent_steps": 10,
            "serendipity_rate": 0.3, "soul_max_chars": 8000,
            "consecutive_error_backoff": 5},
  "chat": {"record_default": false, "idle_end_seconds": 180,
           "preempt_max_wait_minutes": 30, "preempt_poll_seconds": 2},
  "sandbox": {"enabled": true, "timeout_seconds": 10, "backend": "auto"},
  "skills": {"enabled": true, "timeout_seconds": 20, "auto_disable_after_failures": 3},
  "web_actions": {"enabled": true, "http_timeout_seconds": 20, "max_page_kb": 500},
  "knowledge": {"max_tool_rounds": 5, "fts_snippet_len": 200},
  "report": {"time": "22:00", "timezone": "Asia/Seoul", "language": "ko"},
  "web": {"host": "127.0.0.1", "port": 8000, "sse_check_ms": 1000}
}
```

api_key 해석: `api_key` 직접 기입 → `api_key_env` 환경변수 → 없으면 기동 시 명확한 에러.

## P7. 대화 선점 (preemption)

**신호 전달 = control 파일** (프로세스 분리 구조에서 IPC 최소화, state.json 버스 패턴과 동일):

1. **대화 시작**: `POST /api/chat` 첫 메시지 수신 시 API 서버가 `data/control/chat.json` `{active:true, session_id, started_at, last_message_at}` 원자적 기록. 대화 응답 자체는 API 서버가 즉시 LLM 직접 호출(현재 SOUL.md + 최근 스텝 + 세션 턴) — 유저는 기다리지 않음
2. **루프 중단 (현재 지점까지만)**: 에이전트 루프는 **LLM 호출 경계마다**(ACT 시작 전 / 각 tool 라운드 사이 / REFLECT 전) `chat.json`을 확인. active면 진행 중이던 호출은 완료하고, 그 지점에서 멈춤
3. **상태 보존**: 중단 시 `data/control/paused_step.json`에 스냅샷 저장 — `{step_id, phase:"act|tools|reflect", messages_so_far, tool_rounds_done, act_result(있으면), started_at}`. state.status="chatting" 갱신(캐릭터가 문 앞으로 옴)
4. **복귀**: 유저가 `POST /api/chat/end`를 호출하거나, `last_message_at`이 `idle_end_seconds`(기본 180초) 초과하면 API 서버가 chat.json을 inactive로 갱신. 루프는 `preempt_poll_seconds`(2초) 간격으로 폴링하다가 스냅샷을 복원해 **중단 지점부터 이어서** 실행. `preempt_max_wait_minutes`(30분) 초과 시 대화 중이라도 스냅샷 복원 후 재개(다음 경계에서 다시 양보)
5. **크래시 안전**: 루프 재시작 시 paused_step.json이 있으면 phase에 따라 복원 시도, 복원 불가(메시지 불일치 등)면 해당 스텝을 error로 기록하고 새 스텝 시작. 저널에 `preempted:true` 표시
6. **기록 토글**: record=false(기본)는 서버 메모리 세션만(재시작 소멸, UI 명시), record=true는 `chat/recorded.jsonl` + inbox 경유로 다음 wake에 편입 ("기억"으로 남는 것은 record=true뿐임을 UI에 정직하게 표기)

## P8. 자작 스킬 시스템

**내장 스킬 = 소스 repo의 `actions.py`/`webtools.py`** — 에이전트는 데이터 디렉토리에만 쓸 수 있으므로 구조적으로 변경 불가(읽기 전용 요구 충족).

- **저장 위치**: `data/skills/<name>/` — `manifest.json` + `skill.py`. 데이터 git으로 버전 관리(스킬의 탄생·수정도 성장사)
- **인터페이스 규격**:
  - `manifest.json`: `{"name", "description", "entry": "skill.py", "version": 1, "enabled": true, "failures": 0, "created_at"}`
  - `skill.py`: `def run(params: dict) -> dict` — 반환 `{"output": "<markdown>"}`. 표준 라이브러리만 import 가능(러너가 검사)
- **등록**: ACT 도구 루프에 `skill_write(name, description, code)` 도구 제공(중립 문구: "define a new activity you can do later"). 성공 시 다음 스텝부터 행동 목록에 `skill:<name>`으로 노출 — 만들지/쓸지/버릴지 전적으로 에이전트 자유
- **로딩·실행**: import하지 않는다. `skill_runner.py`가 **별도 subprocess**로 실행(P3의 샌드박스 사다리 그대로 통과) — params를 stdin JSON으로, 결과를 stdout JSON으로. 에이전트 프로세스와 메모리 완전 분리
- **실패 격리**: 타임아웃(`skills.timeout_seconds` 20초)/예외/비-JSON 출력 → 해당 스텝은 error 아닌 "스킬 실패 결과"로 정상 진행(루프는 절대 안 죽음), manifest `failures`++. `auto_disable_after_failures`(3회) 도달 시 `enabled:false` — 비활성 사실을 다음 컨텍스트에 알림(고치거나 버리는 것도 에이전트 자유)
- **보안 한계 명시**: subprocess 폴백 모드에서는 강격리가 아님을 README와 기동 로그에 정직하게 표기

## P9. 마일스톤 (완료 기준 포함)

**M0 — 스캐폴딩**: requirements.txt, .gitignore, config.example.json, `config.py`, `paths.py`, tests/conftest.py. `init_data_dir()`: data/ 트리 + 거의 빈 SOUL.md 시드 + git init/최초 커밋.
✓ data/ 생성, config 로드 테스트 green.

**M1 — 최소 wake 루프 (mock)**: llm.py, prompts.py, context.py, loop.py, actions.py(free_write/rest), soul.py, lock.py, journal.py, state.py, fake_llm.py, run_agent.py(`--once --mock`).
✓ 1스텝 → JSONL 1줄 + notes 산출물 + transcripts 왕복 전문 + state.json 갱신 + soul_update 시 git 커밋. JSON 폴백 3단계 테스트 포함 pytest green.

**M2 — 오프라인 행동 전체 + 스레드 + 실 API**: actions.py 확장, sandbox.py(백엔드 사다리), 스레드/shelved 관리, inbox.py.
✓ 실제 API 연속 5스텝(간격 단축), deepen 시 thread_id 유지, sandbox 타임아웃 테스트, pending→delivered 검증.

**M3 — 지식 위키 + tool-use 루프**: wiki.py(md CRUD, [[링크]], FTS5, rebuild), tools.py, llm.py tools 루프, loop.py 통합.
✓ wiki_write→md+인덱스 반영, FTS 히트, 백링크, md 수동 수정 후 rebuild 정합성, FakeLLM tool_calls 시나리오(최대 라운드 강제 포함) green.

**M4 — 웹 행동**: webtools.py — web_search(DuckDuckGo)/web_read/arxiv_search, web_explore 행동 등록.
✓ httpx MockTransport로 DDG/arXiv 응답 파싱 테스트 green, 실 네트워크 1회 수동 확인, 크기/타임아웃 상한 동작.

**M5 — 스케줄러(주기/연속) + 일일 리포트**: scheduler.py, report.py, run_agent.py 장기 실행, start_agent.ps1.
✓ heartbeat 모드 구동, `mode:"continuous"` 전환 시 min_step_gap 간격 연쇄 실행, **장기 스텝 테스트**(주기보다 오래 걸리는 FakeLLM 스텝 → 스킵/강제종료 없이 완주 후 min_step_gap 뒤 자동 재개, next_wake_at 정확성), **스텝 타임아웃 테스트**(step_timeout 초과 시 경계에서 중단 → 부분 산출물 보존 + error:"step_timeout" 기록 → 다음 스텝 정상 진행, 서킷브레이커 미집계 확인), 리포트 시각에 한국어 1인칭 리포트 생성·커밋, 이중 기동 락 거부, 서킷브레이커 테스트.

**M6 — API 서버 + SSE + 대화 선점**: server.py, api.py, events.py, chat.py, control.py, preempt.py, gitview.py, chatlog.py, run_web.py.
✓ TestClient 전 엔드포인트 green, 스텝 발생 → SSE 1초 내 수신, **선점 E2E**: 스텝 진행 중 chat 시작 → 루프가 호출 경계에서 멈추고 status="chatting" → chat/end 또는 타임아웃 → 스냅샷 복원 재개(FakeLLM으로 자동 테스트), record=true 시 recorded.jsonl + inbox 반영.

**M7 — Phaser UI**: index.html(Phaser 3 CDN), room_scene.js, mapping.js, panels.js, CC0 에셋.
✓ 스텝 발생 → 캐릭터 이동·애니메이션·말풍선 자동 반영, chatting 시 문 앞 이동, SOUL.md diff 타임라인, 사고 과정 탭, 위키 검색/그래프 뷰, 대화/선물 왕복.

**M8 — 스킬 시스템**: skills.py, skill_runner.py, skill_write 도구, manifest 수명주기.
✓ FakeLLM 시나리오로 스킬 작성→등록→다음 스텝 목록 노출→실행 성공/타임아웃/크래시/3연속 실패 자동 비활성 전부 테스트 green. 루프 생존 확인.

**M9 — MCP 서버**: mcp_server.py, run_mcp.py.
✓ `claude mcp add` 등록 후 외부에서 wiki_search/query_journal/read_soul/read_transcript 왕복. 읽기 전용 확인.

**M10 — 운영 마감**: README.md(Windows 기준 셋업→실행→관찰→MCP 등록 재현 절차), 스크립트 다듬기.
✓ 새 환경에서 README만으로 재현.

## P10. 테스트 전략

- **FakeLLM**(tests/fake_llm.py): `chat(messages, tools=None)->response` 동일 인터페이스, 응답 큐 시나리오 — ①흥미상승·deepen 연속→thread 유지+soul_update ②하락→abandon→새 thread ③깨진 JSON→추출 폴백 ④비-JSON 2연속→error 스텝 ⑤soul_update→커밋 해시 저널 기록 ⑥tool_calls 반환→도구 디스패치·max_tool_rounds 강제 종료 ⑦선점: 스텝 중 chat 플래그→스냅샷 저장·복원
- **llm.py**: `httpx.MockTransport`로 429/500/타임아웃 → 백오프 검증 (실 네트워크 없음)
- **웹 도구**: MockTransport로 DDG HTML/arXiv Atom 고정 응답 파싱 검증
- **스킬**: 정상/타임아웃/크래시/비JSON 출력 스킬 픽스처로 러너·자동 비활성 검증
- **위키**: tmp data dir에서 CRUD·FTS·백링크·rebuild 검증. revealed_interest는 저널 픽스처로 순수 함수 테스트
- **저장/git**: tmp_path에 실제 git init 후 커밋 로직 검증
- **웹 API**: FastAPI TestClient + 가짜 data dir, SSE는 이벤트 1개 수신까지
- **E2E 개발 모드**: `llm.mock=true`면 전체 파이프라인이 FakeLLM으로 구동 — UI 개발 시 API 비용 0

## P11. 검증 방법

1. `pytest` 전체 green (mock 기반 루프/선점/스킬/저장/API 로직)
2. `python run_agent.py --once --mock` → data/ 산출물·저널·state·트랜스크립트 수동 확인
3. 실 API 키로 `--once` 1회 → 실제 LLM 왕복 확인
4. 두 프로세스 기동 후 브라우저 `localhost:8000` → 캐릭터 반응, SOUL diff, 사고 과정, 위키, 대화(선점 포함), 선물 E2E 수동 확인
5. 에이전트 프로세스 강제 종료 → UI stale 표시 확인 (장애 격리 검증)
6. `claude mcp add`로 MCP 등록 → 외부에서 wiki 검색/저널/트랜스크립트 조회 확인

## 정직한 프레이밍 반영

UI 상단 고정 문구: "이 존재는 자기주도적 흥미를 시뮬레이션합니다" 수준의 담백한 표기. 기록 안 된 대화는 "기억되지 않음" 명시. stated/revealed 괴리도 숨기지 않고 노출.
