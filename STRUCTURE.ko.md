[English](STRUCTURE.md) | [한국어](STRUCTURE.ko.md)

# STRUCTURE — 디렉토리·모듈 지도

"무엇이 있는가"의 정본 문서다. 설계 이유는 DESIGN.md, 셋업·실행 방법은
README.md 참고. 표와 필드는 실제 코드를 읽고 작성했다. PLAN.md와 다른
지점은 코드를 기준으로 기술한다.

## 소스 트리 (`soul/`)

### 진입점 (repo root)

| 파일 | 역할 |
|---|---|
| `run_agent.py` | 에이전트 루프 진입점. 기본은 장기 실행 스케줄러. `--once`는 스텝 1회, `--mock`은 FakeLLM. `agent.lock`을 프로세스 생존 기간 내내 보유. |
| `run_web.py` | API 서버 진입점(uvicorn). `--mock`이면 대화 응답도 FakeLLM 사용. |
| `run_mcp.py` | 읽기 전용 지식 MCP 서버 진입점(stdio). `--data-dir`, `--allow-index-rebuild`(옵트인, 파생 인덱스만 재빌드). |
| `config.example.json` | 커밋되는 설정 템플릿. `config.json`은 `.gitignore` 대상. |
| `requirements.txt` | `httpx`, `fastapi`, `uvicorn`, `mcp`, `tzdata`(Windows에서 `zoneinfo` 보완). |
| `scripts/start_agent.ps1` / `start_web.ps1` | 크래시 시 지수 백오프로 자동 재시작하는 PowerShell 래퍼. Windows 네이티브 venv 전제. |

### `soul/config.py`, `soul/paths.py`

| 모듈 | 역할 | 핵심 함수/클래스 |
|---|---|---|
| `config.py` | `config.json` 로드+검증(dataclass). API 키 해석 순서 적용. | `load_config`, `config_from_dict`, `resolve_api_key`, `Config` 및 하위 9개 섹션 dataclass |
| `paths.py` | 데이터 디렉토리 경로 헬퍼 + 최초 초기화(트리 생성, SOUL.md 시드, git init). | `DataPaths`, `init_data_dir`, `DATA_SUBDIRS`, `DATA_GITIGNORE`, `SOUL_SEED` |

### `soul/agent/` — 에이전트 코어

| 모듈 | 역할 | 핵심 함수/클래스 |
|---|---|---|
| `loop.py` | wake 스텝 오케스트레이션의 중심: 회상 → ACT(도구 루프) → 저장 → REFLECT → 저널/state 갱신 → soul_update 시 커밋. JSON 파싱 3단계 폴백. | `run_step`, `_run_step_body`, `_parse_with_fallback`, `_record_error` |
| `scheduler.py` | heartbeat/continuous 모드 장기 루프 + 서킷브레이커 + `next_wake_at` 계산 + 주기적 autosave. | `run_scheduler`, `compute_wait`, `CircuitBreaker`, `is_llm_failure` |
| `autosave.py` | 누적 히스토리(journal/notes/home/inbox/outbox/chat)를 `agent.autosave_every_steps` 스텝마다 data repo에 커밋 — 일일 리포트 사이의 안전망. | `maybe_autosave`, `is_due`, `AUTOSAVE_PATHS` |
| `preempt.py` | 대화 선점: LLM 호출 경계마다 `control/chat.json` 확인, 스텝 타임아웃 데드라인 검사, 스냅샷 저장/복원, 크래시 복구. | `StepController`, `StepTimeout`, `recover_paused_step` |
| `llm.py` | OpenAI 호환 chat-completions 클라이언트(재시도/백오프/타임아웃) + 트랜스크립트 기록 + 도구 사용 루프. | `LLMClient`, `LLMResponse`, `TranscriptRecorder`, `run_tool_loop` |
| `fake_llm.py` | 테스트/`--mock`용 `LLMClient` 대체. 큐에 넣은 응답을 순서대로 반환(dict/str/`LLMResponse`/예외). | `FakeLLM` |
| `prompts.py` | 영어 프롬프트 템플릿(백지 원칙의 핵심). ACT/REFLECT 메시지 조립, JSON 필드 정규화. | `ACT_SYSTEM_PROMPT`, `REFLECT_SYSTEM_PROMPT`, `build_act_messages`, `build_reflect_messages`, `clamp_interest`, `normalize_mood`, `normalize_decision`, `normalize_interest_delta` |
| `actions.py` | 내장 행동 정의(중립 동사) + 셔플 + `skill:<name>` 합성. | `BUILTIN_ACTIONS`, `available_actions`, `shuffled_actions`, `is_known_action` |
| `webtools.py` | `web_search`(DuckDuckGo HTML 파싱), `web_read`(본문 추출, 크기/시간 상한), `arxiv_search`(Atom API). | `web_search`, `web_read`, `arxiv_search` |
| `skills.py` | 자작 스킬 등록/수명주기: 이름·코드 정적 검증(표준 라이브러리만 허용), manifest 관리, 실패 카운트/자동 비활성화, 데이터 git 커밋. | `create_skill`, `check_imports`, `has_run`, `record_success`, `record_failure`, `drain_notices` |
| `skill_runner.py` | 스킬을 별도 subprocess로 실행하는 러너(샌드박스 사다리 경유). 스킬 코드는 절대 import되지 않음. | `run_skill`, `SkillRunResult` |
| `sandbox.py` | 격리 백엔드 사다리: bwrap → unshare → Docker → plain subprocess. `code_experiment`와 스킬 실행이 공용. | `select_backend`, `run_python`, `backend_is_isolated`, `describe_backend` |
| `context.py` | 회상 컨텍스트 조립: SOUL.md + 최근 N스텝 + 현재 스레드 + 세렌디피티 노트 + inbox + 응답된 관찰자 요청 + 스킬 알림. | `assemble_context`, `RecallContext`, `ThreadInfo`, `_pick_serendipity_note` |
| `soul.py` | SOUL.md 읽기/쓰기 + 데이터 git 커밋. SOUL.md를 쓰는 유일한 모듈. | `read_soul`, `write_soul`, `SoulWriteError` |
| `report.py` | 매일 정해진 시각·타임존에 1인칭 회고를 한국어(설정 가능)로 생성. 날짜 파일 존재 여부로 판정하는 멱등 동작. | `generate_report`, `check_report`, `is_due`, `build_report_messages` |
| `lock.py` | `agent.lock` — pid+timestamp 락. 죽은 프로세스의 stale 락은 탈취(POSIX `os.kill`/Windows `OpenProcess`). | `AgentLock`, `LockError` |

### `soul/storage/` — 상태·이력 저장

| 모듈 | 역할 | 핵심 함수/클래스 |
|---|---|---|
| `journal.py` | 스텝 기록 JSONL append/tail(월별 로테이션) + 순수 파생 함수 `revealed_interest`·`stats`. | `new_step_record`, `append_step`, `read_all`, `tail`, `revealed_interest`, `stats` |
| `state.py` | `state.json` 원자적 읽기/쓰기(tmp + `os.replace`) + 스텝 id 카운터. | `read_state`, `write_state`, `next_step_id`, `default_state` |
| `inbox.py` | 관찰자 메시지 pending→delivered 큐. 웹은 append만 하고, 에이전트가 스텝 시작 시 원자적으로 drain. | `append_pending`, `drain`, `has_pending`, `peek_pending` |
| `outbox.py` | 에이전트→관찰자 요청 채널. 에이전트가 요청을 append(`observer_request` 도구), 웹이 응답을 append. 상태는 두 append 전용 로그를 조인해 파생하고, 에이전트는 스텝 시작 시 커서(`seen.json`)로 새 응답을 drain하며 첨부를 `home/`으로 복사. | `append_request`, `list_requests`, `open_requests`, `append_resolution`, `drain_new_resolutions`, `OutboxStateError` |
| `locks.py` | inbox와 outbox가 공유하는 `O_CREAT\|O_EXCL` 어드바이저리 파일 락(타임아웃 5초, 30초 지난 락은 탈취). | `AdvisoryFileLock` |
| `control.py` | 프로세스 간 신호 파일: `control/chat.json`(선점 버스), `control/paused_step.json`(스냅샷). | `read_chat`, `set_chat_active`, `set_chat_inactive`, `chat_is_active`, `write_paused_step`, `read_paused_step`, `clear_paused_step` |

### `soul/knowledge/` — 지식 위키 + MCP

| 모듈 | 역할 | 핵심 함수/클래스 |
|---|---|---|
| `wiki.py` | 위키 원본(md) CRUD + `[[링크]]` 파싱 + SQLite FTS5 인덱스(파생, 항상 재빌드 가능) + git 커밋. | `write_page`, `read_page`, `search`, `graph`, `backlinks`, `rebuild_index`, `ensure_index` |
| `tools.py` | ACT 도구 루프용 function-calling 스키마 + 디스패처(위키/웹/스킬/관찰자 요청 도구 통합). | `act_tools`, `dispatch`, `WIKI_TOOLS`, `WEB_TOOLS`, `SKILL_TOOLS`, `OUTBOX_TOOLS` |
| `mcp_server.py` | 읽기 전용 MCP 서버(`mcp` SDK, stdio). SQLite도 `mode=ro`로만 연결. | `build_server`, `serve_stdio`, `wiki_search`, `wiki_read`, `wiki_list`, `read_soul`, `query_journal`, `read_report`, `read_transcript` |

### `soul/web/` — API 서버 + 정적 클라이언트

| 모듈 | 역할 | 핵심 함수/클래스 |
|---|---|---|
| `server.py` | FastAPI 앱 팩토리 + 정적 파일 마운트. UI 로직 없음. 라우트는 전부 `api.py`에 있음. | `create_app` |
| `api.py` | REST + SSE 라우트 전체(아래 표). 데이터 디렉토리에 대해 원칙적으로 read-only. | `build_router`, `state_snapshot` |
| `events.py` | `state.json` mtime을 감시해 SSE로 상태 push. | `state_event_stream` |
| `chat.py` | 대화 세션(인메모리) + LLM 직접 호출 + 선점 신호 발행 + 기록 토글. API 서버에 허용된 네 가지 쓰기 중 하나. | `ChatManager`, `ChatSession`, `build_chat_messages` |
| `chatlog.py` | `record=true`인 대화만 `chat/recorded.jsonl`에 append. | `append_turn`, `read_all` |
| `gitview.py` | SOUL.md의 git 로그/커밋별 diff를 읽기 전용으로 노출. 영혼의 성장 이력. | `soul_history`, `soul_diff`, `soul_updated_at` |
| `static/` | Phaser 3(CDN) 기반 웹 클라이언트. API의 여러 클라이언트 중 하나. 모바일 앱 등 다른 클라이언트도 같은 API 사용 가능. | `index.html`, `js/{main,api,room_scene,mapping,panels}.js` |

`static/js/mapping.js`가 action→위치/애니메이션, interest→표정 강도,
decision→1회성 이펙트, 말풍선 규칙의 단일 소스다. `static/assets/`는
의도적으로 비어 있다(`assets/README.md`). 방과 캐릭터 텍스처는 전부
`room_scene.js`가 Phaser `Graphics.generateTexture()`로 절차 생성한다.
DESIGN.md의 "계획과 실제 구현이 갈라진 지점" 참고.

### `tests/` (이름/범위만)

`conftest.py`가 `data_paths`(임시 초기화된 데이터 디렉토리)와 `config`(mock
모드 설정) 픽스처를 제공한다. 242개 테스트가 다음을 모듈별로 검증한다: 설정
로딩(`test_config.py`), 경로/데이터 디렉토리 초기화(`test_paths.py`), 저장
계층(`test_storage.py`, `test_inbox.py`, `test_outbox.py`),
락(`test_lock.py`), LLM 클라이언트
(`test_llm.py`), wake 루프(`test_loop.py`, `test_loop_m2m3.py`,
`test_loop_outbox.py`), 프롬프트
정규화(`test_prompts.py`), 웹 도구(`test_webtools.py`), 오프라인 행동 확장
(`test_actions_m2.py`), 세렌디피티(`test_context_serendipity.py`), revealed
interest(`test_revealed.py`), 샌드박스(`test_sandbox.py`), 도구 사용 루프
(`test_tools_loop.py`), 관찰자 요청 도구(`test_outbox_tool.py`),
autosave(`test_autosave.py`), 위키(`test_wiki.py`), 선점(`test_preempt.py`),
리포트(`test_report.py`), 스케줄러(`test_scheduler.py`), 웹
API(`test_web_api.py`), MCP 서버(`test_mcp_server.py`),
스킬(`test_skills_m8.py`).

## 데이터 디렉토리 (`data/`, 기본 `./data`, 소스 저장소와 별도 git repo)

```
data/
├── .git/                      # 영혼 성장 이력 전용 git 저장소
├── .gitignore                 # 아래 "커밋 안 함" 목록
├── SOUL.md                    # 정체성 — soul.py만 씀. 커밋됨.
├── state.json                 # UI 스냅샷. 커밋 안 함(휘발성).
├── agent.lock                 # pid+timestamp 락. 커밋 안 함.
├── journal/steps-YYYY-MM.jsonl  # 스텝 기록, 월별 로테이션. 커밋됨(리포트와 함께).
├── notes/step-XXXXXX.md       # ACT 산출물. 커밋됨(리포트와 함께).
├── wiki/<slug>.md             # 위키 원본(frontmatter+본문+[[링크]]). 커밋됨(wiki.py).
├── index/wiki.sqlite3         # 위키 FTS5+링크 그래프 파생 인덱스. 커밋 안 함(재빌드 가능).
├── skills/<name>/manifest.json, skill.py  # 자작 스킬. 커밋됨(skills.py).
├── sandbox/                   # 스킬 실행용 일회성 스크래치. 커밋 안 함.
├── home/                      # code_experiment의 영속 작업 디렉토리(cwd). 상대경로로 쓴 파일이 스텝 간 유지되고, 응답된 outbox 첨부가 home/attachments/<req-id>/로 복사됨. 주기 커밋됨(autosave.py).
├── reports/YYYY-MM-DD.md      # 일일 회고. 커밋됨(report.py).
├── inbox/{pending,delivered}.jsonl, inbox.lock  # 관찰자 메시지 큐. 주기 커밋됨(autosave.py).
├── outbox/requests.jsonl      # 에이전트→관찰자 요청(에이전트가 observer_request 도구로 append). 주기 커밋됨(autosave.py).
├── outbox/resolutions.jsonl   # 관찰자 응답(웹이 append; resolved/declined/ignored/reopened). 같은 autosave 대상.
├── outbox/attachments/<req-id>/<file>  # 관찰자가 응답 시 첨부한 파일(웹, 생성만).
├── outbox/seen.json, outbox.lock  # 에이전트 쪽 응답 커서 + 어드바이저리 락.
├── chat/recorded.jsonl        # record=true인 대화만. 주기 커밋됨(autosave.py).
├── transcripts/<step_id>.jsonl  # 스텝별 LLM 왕복 전문. 커밋 안 함(용량/잡음).
├── control/chat.json, paused_step.json  # 프로세스 간 신호. 커밋 안 함.
└── logs/agent.log             # 운영 로그. 커밋 안 함.
```

커밋 대상 정리. `paths.py:DATA_GITIGNORE`가 명시적으로 배제하는 목록은
`state.json`, `index/`, `control/`, `logs/`, `agent.lock`, `sandbox/`,
`transcripts/`다. 나머지는 전부 커밋되지만, 커밋을 실행하는 코드는 각자 정해진
대상만 add한다. `soul.py`는 SOUL.md만, `wiki.py`는 해당 페이지 md만,
`skills.py`는 해당 스킬 디렉토리만 커밋하고, `report.py`는 하루 1회
`reports/ journal/ notes/`를 함께 커밋하며, 나머지 누적 히스토리
(`journal/ notes/ home/ inbox/ outbox/ chat/`)는 `autosave.py`가
`agent.autosave_every_steps` 스텝마다 쓸어 담는다.

## API 엔드포인트 (`soul/web/api.py:build_router`)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/state` | 현재 `state.json` 스냅샷 + `stale` 플래그(`next_wake_at`+`step_timeout_minutes`까지 무소식이면 true, 진행 중인 스텝은 stale 아님) + `stale_at`(그 기준 시각). |
| GET | `/api/events` | SSE. `state.json` 변경마다 `event: state`로 동일 스냅샷 push. |
| GET | `/api/steps?limit=50` | 저널 스텝 목록(최신순). |
| GET | `/api/step/{step_id}` | 스텝 레코드 + `content_path`의 본문. |
| GET | `/api/step/{step_id}/transcript` | 해당 스텝의 LLM 왕복 전문(사고 과정). |
| GET | `/api/soul` | 현재 SOUL.md 전문 + 마지막 갱신 시각. |
| GET | `/api/soul/history` | SOUL.md를 변경한 커밋 목록(최신순). |
| GET | `/api/soul/diff/{commit}` | 특정 커밋이 SOUL.md에 도입한 unified diff. |
| GET | `/api/reports` | 리포트가 존재하는 날짜 목록(최신순). |
| GET | `/api/report/{date}` | 해당 날짜 리포트 본문. |
| GET | `/api/revealed` | stated vs revealed 흥미 파생 지표 전체. |
| GET | `/api/stats?timeline=N` | 통계 패널용 저널 전체 집계: 결정/행동/기분 분포, 흥미 히스토그램, 스텝 타임라인(최근 N개), 시간순 스레드 구간, 에러 수 + 최근 에러. |
| GET | `/api/skills` | 에이전트가 만든 스킬 manifest(name/version/enabled/failures) + `auto_disable_after_failures` 임계값. |
| GET | `/api/wiki/pages` | 전체 위키 페이지 목록(slug/title/updated). |
| GET | `/api/wiki/search?q=` | FTS5 검색 결과(slug/title/snippet). |
| GET | `/api/wiki/page/{slug}` | 페이지 본문 + 백링크. |
| GET | `/api/wiki/graph` | 위키 링크 그래프(nodes/links). |
| POST | `/api/chat` | 대화 메시지 전송. 세션 없으면 새로 생성. 선점 신호 발행 + 즉시 LLM 응답. |
| POST | `/api/chat/end` | 대화 세션 종료. 선점 신호 해제. |
| GET | `/api/chat/{session_id}` | 세션의 턴 목록 + record 플래그. |
| POST | `/api/inbox` (202) | 관찰자 메시지/선물을 pending 큐에 추가. |
| GET | `/api/outbox?status=` | 에이전트가 관찰자에게 남긴 요청 목록(최신순, 파생 status: `open`\|`resolved`\|`declined`\|`ignored`, 필터 선택). |
| POST | `/api/outbox/{id}/resolve` | multipart form(`status`, 선택 `note`, 선택 `file` — 파일은 resolved/declined일 때만). 응답 레코드 append. 404 미존재, 409 잘못된 전이, 413 파일 초과, 422 잘못된 status. API 서버의 네 번째 허용 쓰기. |

## 저널 스텝 레코드 필드 (`soul/storage/journal.py:new_step_record`)

| 필드 | 타입(기본) | 의미 |
|---|---|---|
| `id` | str | `step-NNNNNN` 형식 스텝 id. |
| `ts` | str | ISO-8601 UTC 타임스탬프. |
| `kind` | str | `wake_step` \| `report` \| `error`. |
| `action` | str\|null | 선택된 행동 이름(`free_write` 등, `skill:<name>` 포함). |
| `topic` | str\|null | ACT가 정한 한 줄 주제. |
| `thread_id` | str\|null | `th-NNNN`. `deepen`이면 이전 스텝과 동일 유지 (decision 기준 — topic 문구가 스텝 사이에 달라져도 스레드는 끊기지 않는다). |
| `content_path` | str\|null | 산출물 경로(`notes/<id>.md` 등). |
| `interest` | int\|null | 1~10, clamp 적용. |
| `interest_delta` | str\|null | `more`\|`less`\|`same`\|`first`. |
| `mood` | str\|null | 8종 enum. 원본 값이 enum 밖이면 `mood_raw`에 원문 보존. |
| `reason` | str\|null | 이유. decision보다 먼저 기록됨. |
| `decision` | str\|null | `deepen`\|`shelve`\|`abandon`\|`new`. |
| `summary` | str\|null | 한 줄 요약. 말풍선에 사용. |
| `soul_updated` | bool | 이 스텝에서 SOUL.md가 갱신됐는지. |
| `soul_commit` | str\|null | 갱신됐다면 그 커밋 해시. |
| `serendipity_note` | str\|null | 이번 스텝에 우연히 재부상한 과거 노트의 경로. |
| `transcript_path` | str\|null | `transcripts/<id>.jsonl`. |
| `wiki_ops` | list | `[{"tool":"wiki_write","slug":...}, ...]`. |
| `web_visits` | list[str] | `web_read`로 실제 방문한 URL. |
| `skill_used` | str\|null | 실행된 자작 스킬 이름. |
| `sandbox_backend` | str\|null | `bwrap`\|`unshare`\|`docker`\|`subprocess`\|null. |
| `preempted` | bool | 이 스텝이 대화 선점으로 중단됐는지. |
| `inbox_delivered` | list[str] | 이 스텝에서 전달된 inbox 메시지 id 목록. |
| `observer_requests` | list[str] | 이 스텝에서 에이전트가 남긴 요청 id 목록(`observer_request` 도구). |
| `observer_resolved` | list[str] | 이 스텝 컨텍스트에 응답이 전달된 요청 id 목록. |
| `llm` | dict | `{model, tokens_in, tokens_out, latency_ms}`. ACT+REFLECT 합산. |
| `error` | dict\|null | `{"phase", "message", "llm_failure"}` — `kind:"error"`일 때. |

## `config.json` 키 표 (`soul/config.py`)

### `llm`

| 키 | 기본값 | 의미 |
|---|---|---|
| `base_url` | `https://api.openai.com/v1` | OpenAI 호환 chat completions 엔드포인트. |
| `model` | `gpt-4o-mini` | 모델 이름. |
| `api_key_env` | `OPENAI_API_KEY` | `api_key`가 없을 때 참조할 환경변수. |
| `api_key` | `null` | 직접 기입한 키. 있으면 최우선. |
| `timeout_seconds` | `120` | 요청 타임아웃. |
| `max_retries` | `3` | 재시도 횟수(백오프 1s/4s/16s). |
| `temperature` | `1.0` | 샘플링 온도. |
| `max_output_tokens` | `2000` | 응답 최대 토큰. |
| `mock` | `false` | true면 FakeLLM 사용. API 키 불필요. |

### `agent`

| 키 | 기본값 | 의미 |
|---|---|---|
| `data_dir` | `./data` | 데이터 디렉토리 경로. |
| `mode` | `heartbeat` | `heartbeat` \| `continuous`. |
| `heartbeat_minutes` | `30` | heartbeat 모드 주기. |
| `min_step_gap_seconds` | `60` | 두 모드 공통 최소 스텝 간격. |
| `step_timeout_minutes` | `45` | 스텝 하드 데드라인. 주기와 독립. |
| `context_recent_steps` | `10` | 회상에 포함할 최근 스텝 수. |
| `serendipity_rate` | `0.3` | 과거 노트 무작위 재부상 확률. |
| `soul_max_chars` | `8000` | SOUL.md 쓰기 허용 최대 글자 수. |
| `consecutive_error_backoff` | `5` | 이 횟수 연속 LLM 실패 시 서킷브레이커 발동. |
| `autosave_every_steps` | `20` | N스텝마다 journal/notes/home/inbox/outbox/chat을 data repo에 커밋(`autosave @ <step_id>`) — 일일 리포트가 아직 없어도 히스토리를 보존한다. `0`이면 비활성. |

### `chat`

| 키 | 기본값 | 의미 |
|---|---|---|
| `record_default` | `false` | 새 대화 세션의 기본 기록 여부. |
| `idle_end_seconds` | `180` | 마지막 메시지 후 이 시간이 지나면 세션 종료로 취급. |
| `preempt_max_wait_minutes` | `30` | 대화가 이어져도 루프가 재개를 강제 시도하기까지의 최대 대기. |
| `preempt_poll_seconds` | `2` | 루프가 선점 해제를 폴링하는 간격. |

### `sandbox`

| 키 | 기본값 | 의미 |
|---|---|---|
| `enabled` | `true` | `code_experiment` 실행 여부. |
| `timeout_seconds` | `10` | 샌드박스 실행 타임아웃. |
| `backend` | `auto` | `auto`\|`bwrap`\|`unshare`\|`docker`\|`subprocess` 강제 지정 가능. |

### `skills`

| 키 | 기본값 | 의미 |
|---|---|---|
| `enabled` | `true` | 자작 스킬 시스템 전체 on/off. |
| `timeout_seconds` | `20` | 스킬 실행 타임아웃. |
| `auto_disable_after_failures` | `3` | 이 횟수 연속 실패 시 자동 비활성화. |

### `web_actions`

| 키 | 기본값 | 의미 |
|---|---|---|
| `enabled` | `true` | `web_explore`/웹 도구 노출 여부. |
| `http_timeout_seconds` | `20` | 웹 요청 타임아웃. |
| `max_page_kb` | `500` | `web_read` 최대 수신 바이트(KB). |

### `observer_requests`

| 키 | 기본값 | 의미 |
|---|---|---|
| `enabled` | `true` | ACT에 `observer_request` 도구를 노출할지. 꺼도 이미 남은 요청의 응답은 에이전트에게 전달된다. |
| `max_open` | `5` | 동시에 열려 있을 수 있는 요청 수. 상한에 도달하면 도구가 중립적 에러 문자열을 반환한다. 거절/무시된 요청은 슬롯을 비운다. |
| `max_attachment_mb` | `20` | resolve 첨부 파일 크기 상한(초과 시 413). |

### `knowledge`

| 키 | 기본값 | 의미 |
|---|---|---|
| `max_tool_rounds` | `5` | ACT 도구 루프 최대 라운드. 초과 시 도구 없는 최종 호출 강제. |
| `fts_snippet_len` | `200` | 위키 검색 스니펫 길이. |

### `report`

| 키 | 기본값 | 의미 |
|---|---|---|
| `time` | `22:00` | 일일 리포트 트리거 시각(로컬). |
| `timezone` | `Asia/Seoul` | `zoneinfo` 타임존 이름. |
| `language` | `ko` | 리포트 언어. `ko`\|`en`\|`ja` 지원, 그 외 코드는 그대로 프롬프트에 전달. |

### `web`

| 키 | 기본값 | 의미 |
|---|---|---|
| `host` | `127.0.0.1` | API 서버 바인드 주소. |
| `port` | `8000` | API 서버 포트. |
| `sse_check_ms` | `1000` | SSE가 `state.json` mtime을 폴링하는 간격(ms). |
| `allowed_networks` | `[]` | 접속 허용 CIDR 목록(예: `["192.168.0.0/24", "::1/128"]`). 비어 있으면 필터링 없음. 기본 `127.0.0.1` 바인드는 이미 로컬 전용이므로 host를 `0.0.0.0` 등으로 열 때 함께 설정. 목록이 비어 있지 않으면 목록 밖 IP와 판별 불가 주소는 모두 403(fail-closed). |
