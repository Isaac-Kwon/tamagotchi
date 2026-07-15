# DESIGN — 설계 결정과 근거

이 문서는 "왜 이렇게 만들었는가"를 다룹니다. "무엇이 있는가"는 `STRUCTURE.md`,
"어떻게 재현하는가"는 `README.md`를 보세요. 각 절은 `PLAN.md`의 해당 섹션(P0~P11)을
가리키며, 실제 코드가 계획과 달라진 지점은 숨기지 않고 그대로 적었습니다.

## 1. 백지(blank-slate) 철학과 프롬프트 원칙 (PLAN §3, P2)

핵심 제약: SOUL.md는 거의 빈 채로 시작하고(`soul/paths.py:SOUL_SEED` — "This file
is owned and edited only by the agent itself." 한 줄뿐), 취향·성격·관심사를 어디에도
시드로 심지 않습니다. 이 원칙이 프롬프트 설계 전체를 규정합니다
(`soul/agent/prompts.py`):

- **성격 형용사·예시 주제 금지**: `ACT_SYSTEM_PROMPT`/`REFLECT_SYSTEM_PROMPT`는
  상황과 메커니즘만 서술합니다 ("Time passes in discrete steps. On each step you
  choose exactly one action..."). "curious한 에이전트" 같은 형용사도, "예를 들어
  코딩을 좋아한다면" 같은 예시 주제도 없습니다.
- **행동 목록 셔플**: `soul/agent/actions.py:shuffled_actions()`가 매 스텝
  `random.shuffle`로 순서를 섞습니다. 위치 편향(첫 항목을 고르는 경향)을 막기
  위함이며, `prompts.render_action_list`는 주어진 순서를 그대로 렌더링할 뿐 절대
  하드코딩된 순서를 쓰지 않습니다.
- **대칭적 결정 정의**: `deepen`/`shelve`/`abandon`/`new` 네 가지가
  `DECISION_DEFINITIONS`에 각각 한 줄 중립 정의로만 존재합니다. 어느 쪽도
  "더 나은 선택"으로 읽히지 않도록 구조를 맞췄습니다.
- **reason이 decision보다 먼저**: REFLECT 응답 JSON의 필드 순서 자체가
  `{"interest", "interest_delta", "mood", "reason", "decision", "summary",
  "soul_update"}`로 고정되어 있고, 시스템 프롬프트도 "Write your reason BEFORE
  stating the decision"이라고 명시합니다. 결정부터 뱉고 이유를 사후 합리화하는
  패턴을 줄이기 위한 장치입니다.
- **interest_delta 상대 앵커**: 절대 척도(1~10, 양 끝점만 앵커)만으로는 LLM
  자기평가가 6~8 사이에 뭉치는 경향(central tendency)이 있어, "직전 이 주제를
  평가했을 때보다 더/덜/비슷하게 끌리는가"(`interest_delta`: more/less/same/first)를
  함께 물어봅니다. `soul/agent/context.py:_derive_thread`가 같은 스레드의 직전
  `interest`를 찾아 REFLECT 프롬프트(`build_reflect_messages`)에 명시적 비교
  기준으로 제공합니다.
- **soul_update는 기본 false**: "durable한 것이 생겼을 때만 true"라고 프롬프트에
  못박혀 있고, `loop.py`도 `soul_update.update is True`이고 내용이 비어있지 않을
  때만 실제로 SOUL.md를 덮어씁니다.

## 2. stated vs revealed 흥미 분리 (PLAN §P0/P2)

자기 보고(stated) interest는 LLM의 긍정 편향·confabulation에 취약할 수 있다는
전제 위에서, **행동으로 드러난(revealed) 신호는 LLM과 무관하게 저널에서 순수
함수로 파생**합니다 (`soul/storage/journal.py:revealed_interest`):

- 스레드 지속 길이(같은 thread_id로 몇 스텝이 이어졌는가)
- shelve 후 실제로 그 주제로 복귀했는지·몇 번(returns)
- 같은 topic이 재등장하는 빈도(topic recurrence)

이 값은 **저장되지 않고 조회 시점에 계산**됩니다(state.json 갱신 시
`_update_revealed`가 캐시로 채워 넣긴 하지만, 원천은 항상 저널 재계산입니다).
stated와 revealed의 괴리는 숨기지 않고 API(`/api/revealed`)·UI("말과 행동" 탭)·
일일 리포트 컨텍스트(`report.py:build_report_messages`)에 함께 노출해, 에이전트
스스로 자기 말과 행동의 괴리를 보게 합니다.

## 3. 환경 우연성 (PLAN §P2 "환경 우연성")

같은 모델·같은 백지 프롬프트는 모델의 기본 페르소나로 수렴할 위험이 있습니다.
개체성을 "prior + 경로의 우연"으로 보고, **내용이 아니라 무작위 추첨으로** 우연을
공급합니다:

- **행동 목록 셔플** (위 1번)
- **과거 노트 무작위 재부상**: `context.py:_pick_serendipity_note`가
  `serendipity_rate`(기본 0.3) 확률로 `notes/*.md` 중 하나를 균등 추첨해 "a note
  you wrote before"로 컨텍스트에 끼워 넣습니다. 내용으로 고르지 않고 파일 목록에서
  균등 추첨하므로 특정 주제를 편애하지 않습니다.
- **관찰자 inbox**: 설계상 이미 외부에서 오는 우연(사람이 무엇을 남길지 예측 불가).

## 4. ACT/REFLECT 2-호출 분리 (PLAN §P2)

한 스텝은 두 번의 별도 LLM 호출로 이루어집니다: **① ACT** — 행동 선택 + 수행 →
`{"action","topic","content"}`, **② REFLECT** — 완성된 산출물을 보고 자기평가 +
결정 → 구조화 JSON(도구 없음). 자유 서술과 구조화 JSON을 한 호출에 섞으면 파싱이
취약해지고, 무엇보다 **아직 하지도 않은 행동을 미리 평가하는 것보다, 완성된
산출물을 보고 평가하는 편이 더 정직**하기 때문입니다(`loop.py` 주석 및 PLAN P2).
REFLECT에는 도구를 주지 않습니다 — 평가 단계에서 위키/웹 도구를 또 호출할 수
있게 하면 평가 자체가 오염될 수 있기 때문입니다(`knowledge/tools.py`,
"REFLECT는 도구 없음").

## 5. 사고 과정(chain of thought) 트랜스크립트 보존 (PLAN §P2.5)

`soul/agent/llm.py:TranscriptRecorder`가 매 LLM 왕복(요청 messages 전문, 도구
라운드별 tool_calls·결과, 원시 응답, `reasoning_content`/`reasoning` 필드가 있으면
그대로)을 `data/transcripts/<step_id>.jsonl`에 한 줄씩 append합니다. `LLMClient`와
`FakeLLM`이 동일한 recorder 인터페이스를 쓰므로 mock 모드에서도 같은 방식으로
트랜스크립트가 쌓입니다. 왜 강제로 "생각을 서술하라"는 필드를 추가하지 않았는가:
그런 필드는 프롬프트 오염이자 성능·중립성을 해칠 수 있다고 보고, `reason` 필드가
이미 "최소한의 명시적 근거"를 담당하게 했습니다. 열람 경로는 셋: ① UI 스텝 상세
"사고 과정" 탭, ② `GET /api/step/{id}/transcript`, ③ MCP `read_transcript(step_id)`.
트랜스크립트는 용량·잡음을 이유로 데이터 git에는 커밋하지 않습니다
(`paths.py:DATA_GITIGNORE`의 `transcripts/`).

## 6. 대화 선점(preemption) 프로토콜 (PLAN §P7)

에이전트 루프(동기)와 API 서버(비동기)는 별도 프로세스이므로, IPC를 최소화하려고
**control 파일을 신호 버스로 재사용**합니다 — `state.json`과 같은 패턴입니다.

- **시작**: `POST /api/chat` 첫 메시지에서 `soul/web/chat.py:ChatManager.send`가
  `control/chat.json`을 `{active:true, session_id, started_at, last_message_at}`로
  원자적으로 씁니다(`storage/control.py`, tmp+`os.replace`). 대화 응답 자체는 API
  서버가 SOUL.md + 최근 스텝 + 세션 턴으로 **즉시 LLM을 직접 호출**해 만듭니다 —
  유저는 루프를 기다리지 않습니다.
- **루프 중단**: `soul/agent/preempt.py:StepController.boundary`가 ACT 호출 전,
  각 도구 라운드 사이, REFLECT 호출 전 — 즉 **모든 LLM 호출 경계**에서
  `control/chat.json`을 확인합니다. active면 그 지점에서 멈춥니다(진행 중이던 호출
  자체는 끝까지 완료한 뒤 멈춤).
- **상태 보존**: 멈추는 순간 `control/paused_step.json`에
  `{step_id, phase, messages_so_far, tool_rounds_done, act_result, started_at}`를
  스냅샷으로 저장하고 `state.status="chatting"`으로 갱신합니다. 루프가 파이썬
  스택 안에서 그대로 블로킹하기 때문에(`_check_preempt`가 `sleep`로 폴링),
  "복귀"는 사실 "unblock하고 이어서 실행"일 뿐입니다 — 인메모리 상태가 한 번도
  파괴되지 않습니다. `paused_step.json`은 오직 **프로세스 재시작을 가로지르는
  크래시 복구용**입니다.
- **복귀**: `POST /api/chat/end` 또는 `last_message_at`이
  `chat.idle_end_seconds`(기본 180초)를 넘기면 비활성으로 전환됩니다. 루프는
  `chat.preempt_poll_seconds`(기본 2초) 간격으로 폴링하다가 재개합니다.
  `chat.preempt_max_wait_minutes`(기본 30분)를 넘기면 대화 중이라도 일단
  재개하고, 다음 경계에서 다시 양보합니다(무한 대기 방지).
- **크래시 안전**: 재시작 시 `scheduler.run_scheduler`가
  `preempt.recover_paused_step`을 먼저 호출합니다. 프로세스 재시작을 가로지른
  LLM 대화는 신뢰성 있게 재구성할 수 없으므로, 남은 스냅샷은 `kind:"error"`,
  `preempted:true`로 저널에 기록하고 새 스텝으로 넘어갑니다.
- **기록 토글**: `record=false`(기본)는 세션이 API 서버 메모리에만 존재하다가
  재시작하면 사라집니다 — "기억되지 않음"을 UI에 정직하게 표기합니다.
  `record=true`일 때만 `chat/recorded.jsonl`에 남고, 유저 메시지가 inbox를 거쳐
  다음 wake의 컨텍스트에 들어갑니다.

## 7. 스케줄러 정책 (PLAN §P5)

`soul/agent/scheduler.py:run_scheduler`는
`check_preempt() → check_report() → run_step() → wait()`를 반복합니다.

- **주기(heartbeat) vs 연속(continuous)**: `compute_wait()`가 다음 스텝 시작
  시각을 계산합니다. heartbeat 모드는
  `max(이전 스텝 시작 + heartbeat, 이전 스텝 종료 + min_step_gap)` — 즉 **스텝이
  주기보다 오래 걸려도 스킵하거나 죽이지 않고**, 대신 최소 격리 간격
  (`min_step_gap_seconds`, 기본 60초)만 보장합니다. continuous 모드는
  `이전 스텝 종료 + min_step_gap`만 적용해 끝나는 즉시 다음 스텝을 잇습니다. 두
  모드가 같은 `min_step_gap_seconds` 파라미터를 공유합니다.
- **스텝 타임아웃은 별도 안전망**: heartbeat/continuous의 "느긋한" 정책과 별개로,
  `StepController`가 `step_timeout_minutes`(기본 45분) 하드 데드라인을 스텝 내부의
  LLM 호출 경계마다 검사합니다(`_check_deadline`, 개별 LLM 호출 자체도 120초
  타임아웃이 있으므로 데드라인 초과가 한 호출 길이 이상 밀리지 않습니다). 초과 시
  `StepTimeout`을 던지고, `loop.run_step`이 그때까지의 부분 산출물·트랜스크립트를
  보존한 채 `kind:"error"`, `error:"step_timeout"`으로 기록한 뒤 다음 스텝으로
  넘어갑니다. 폭주(무한 도구 루프 등)의 최종 방어선이며, LLM 장애가 아니라 "작업이
  길었을 뿐"이므로 서킷브레이커에는 집계하지 않습니다(`scheduler.is_llm_failure`가
  `error.llm_failure` 플래그로 구분).
- **서킷브레이커**: `CircuitBreaker`가 **연속 LLM 실패**(`llm_failure: true`인
  에러 스텝)만 셉니다. `consecutive_error_backoff`(기본 5)회 연속 실패 시 다음
  대기 시간에 4배(`CIRCUIT_MULTIPLIER`)를 곱하고, 성공하면 즉시 원상 복귀합니다.
  파싱 실패나 스텝 타임아웃은 "API 장애"가 아니므로 카운트에서 제외됩니다.
- 리포트 시각 체크(`report.is_due`)는 두 모드 공통으로 스텝 사이마다 이루어지고,
  `Asia/Seoul` 등 `zoneinfo` 기준입니다. `state.json`의 `next_wake_at`은 항상
  `compute_wait()`가 계산한 실제 다음 시작 시각을 반영해 UI 카운트다운이 정확하게
  맞습니다.

## 8. 샌드박스 사다리 (PLAN §P3)

`soul/agent/sandbox.py:select_backend`가 최선의 격리부터 순서대로 시도합니다:

1. **Linux 네이티브** — `bwrap`(`--unshare-all --die-with-parent`, 없으면
   `unshare --user --net --pid --map-root-user`). 데몬 불필요, 오버헤드 최소.
2. **Docker** — `docker info`가 성공할 때만. `--network none`,
   `--memory 256m`, `--pids-limit 128` — **Windows에서 유일한 강격리**.
3. **plain subprocess** — 마지막 폴백. cwd를 `data/sandbox`에 고정하고 환경변수를
   최소화하지만, **격리가 아닙니다**.

정직성이 이 설계의 핵심입니다: `SandboxResult.isolated`가 subprocess 폴백에서는
반드시 `False`이고, 이 값이 저널의 `sandbox_backend` 필드와 기동 로그에 그대로
남습니다. 어떤 백엔드가 선택됐는지 숨기지 않습니다. 이 사다리는 `code_experiment`
행동과 자작 스킬 실행(P8) 양쪽에서 공용으로 재사용됩니다.

## 9. 자작 스킬 수명주기 (PLAN §P8)

내장 스킬(`actions.py`/`webtools.py`)은 소스 저장소 소속이라 에이전트가 구조적으로
바꿀 수 없습니다(데이터 디렉토리에만 쓸 수 있으므로). 자작 스킬은:

- **등록**: ACT 도구 루프에서 `skill_write(name, description, code)`를 호출하면
  `soul/agent/skills.py:create_skill`이 이름을 slug로 검증하고,
  `soul/agent/skills.py:check_imports`로 **표준 라이브러리 이외의 import를 정적으로
  거부**하며(AST 파싱), `run(params: dict) -> dict` 함수 존재를 확인한 뒤
  `manifest.json` + `skill.py`를 쓰고 데이터 git에 커밋합니다. 성공하면 다음
  스텝부터 `skill:<name>`이 행동 목록에 중립적으로 나타납니다.
- **실행**: `skill_runner.py`가 스킬 코드를 **에이전트 프로세스에 import하지
  않고**, 위 8번의 샌드박스 사다리를 통해 별도 subprocess로 돌립니다. params는
  stdin JSON, 결과는 stdout JSON(`{"output": "<markdown>"}`). 실행 직전에도
  import 검사를 다시 돌려, 등록 후 디스크에서 파일이 바뀌었어도 안전합니다.
- **실패 격리**: 타임아웃(`skills.timeout_seconds`, 기본 20초)/예외/비-JSON
  출력은 전부 "스킬 실패" 마크다운 결과로 변환되어 **스텝은 정상 진행되고 루프는
  절대 죽지 않습니다**(`skill_runner.run_skill`이 예외를 던지지 않음). 실패마다
  `manifest.failures`가 증가하고, `skills.auto_disable_after_failures`(기본 3)에
  도달하면 자동으로 `enabled:false`가 되며 커밋됩니다. 다음 컨텍스트에 "이 스킬이
  꺼졌다"는 1회성 알림이 `skills.drain_notices`를 통해 전달되어, 고치거나 버리는
  것도 에이전트 자유로 남습니다.

## 10. 스토리지 선택 근거 (PLAN §P0/P1)

JSONL(저널) + Markdown(노트/위키/리포트) + `state.json`(단일 스냅샷)을 1차
저장소로, SQLite는 **위키 검색을 위한 파생 인덱스(`index/wiki.sqlite3`)로만**
사용합니다. 근거: PLAN의 "한 디렉토리 통째로 다른 AI에 import해 진단"
요구사항(P1) — 텍스트 파일은 사람도 AI도 그대로 읽습니다. 데이터량도 애초에
작습니다(스텝당 몇 KB). SQLite 인덱스는 **항상 md 원본에서 전체 재빌드
가능**(`wiki.rebuild_index`)하고, 기동 시 mtime 불일치를 감지하면 자동
재빌드(`wiki.ensure_index`)하므로, 인덱스 자체는 데이터 git에 커밋하지 않습니다
(파생물이지 원본이 아니므로). sqlite3 + FTS5는 표준 라이브러리라 추가 의존성이
없습니다.

**데이터 디렉토리 자체가 별도 git 저장소**(`soul/paths.py:init_data_dir`)인
이유도 같은 진단성 요구에서 나옵니다 — 소스 저장소와 완전히 분리되어 있어야
`data/`만 통째로 다른 AI 컨텍스트에 넘길 수 있고, SOUL.md의 git 히스토리 자체가
"영혼의 성장사"로서 diff 타임라인이 됩니다(P1/§3). 커밋 대상은 SOUL.md, notes/,
wiki/, skills/, reports/이고(+ 리포트 생성 시 하루 1회 저널을 동반 커밋), `state.json`/
`index/`/`control/`/`logs/`/`sandbox/`/`transcripts/`/`agent.lock`은
`data/.gitignore`(`DATA_GITIGNORE`)로 명시적으로 제외됩니다 — 파생물이거나,
휘발성이거나, 머신 로컬이기 때문입니다.

## 11. 프로세스 분리와 "쓰기 주체" 원칙 (PLAN §P5)

에이전트 루프(`run_agent.py`, 동기)와 API 서버(`run_web.py`, uvicorn 비동기)는
**2개의 별도 프로세스**로, `data/` 디렉토리만 공유합니다. 근거는 장애
격리(루프가 죽어도 UI는 살아있음)와, 동기 루프 + 비동기 웹 동시성을 억지로
한 프로세스에 섞지 않는 단순함입니다.

**쓰기 주체는 정확히 하나로 고정됩니다**: 데이터 디렉토리의 실질적인 쓰기는
에이전트 루프 프로세스만 합니다(SOUL.md, 저널, 위키, 스킬, 리포트, state.json).
API 서버는 원칙적으로 읽기 전용이고, 예외적으로 딱 세 가지만 씁니다 — inbox
`pending.jsonl` append(`storage/inbox.append_pending`), 기록 동의된 대화
`chat/recorded.jsonl` append(`web/chatlog.py`), 그리고 선점 신호
`control/chat.json`(`storage/control.py`). MCP 서버(`run_mcp.py`)는 이 셋조차
쓰지 않는 **완전 읽기 전용**이며, 위키 인덱스도 `mode=ro` SQLite 연결로만 엽니다.
inbox는 "웹은 append만, 에이전트는 스텝 시작 시 pending→delivered를 원자적으로
이동"하는 프로토콜(`storage/inbox.py`, `O_CREAT|O_EXCL` 어드바이저리 락)로
경합을 피합니다. git 커밋 경합도 같은 원칙으로 해소됩니다 — 데이터 git에 쓰는
프로세스가 하나뿐이므로 애초에 다중 writer 문제가 생기지 않습니다(커밋 실패 시
1회 재시도, 그래도 실패하면 파일은 갱신된 채로 다음 커밋에 포함).

## 12. 정직한 프레이밍 원칙 (PLAN §3/P11)

이 프로젝트 전체를 관통하는 규칙: **과장하지 않는다.** 구체적으로:

- UI 상단 고정 배너: "이 존재는 자기주도적 흥미를 시뮬레이션합니다"
  (`soul/web/static/index.html`).
- `record=false` 대화는 UI에 "기억되지 않음"이라고 명시(6번).
- 샌드박스가 격리되지 않은 경우(plain subprocess) `isolated:false`를 저널·로그에
  그대로 남김(8번, 9번).
- stated vs revealed 흥미의 괴리를 숨기지 않고 UI/API/리포트에 나란히 노출(2번).
- 웹 검색에 도메인 차단 목록을 두지 않는 대신, 그 한계(광고 혼입 가능성 등)를
  README에 정직하게 적음.

## 참고: 계획과 실제 구현이 갈라진 지점

- **프론트엔드 아트 소스**: PLAN §P0은 "CC0 픽셀 에셋 팩(Kenney.nl 등)"을
  선택으로 명시했지만, 실제 M7 구현은 `soul/web/static/js/room_scene.js`가
  Phaser의 `Graphics.generateTexture()`로 **모든 텍스처를 부팅 시 절차적으로
  생성**합니다. `soul/web/static/assets/`는 의도적으로 빈 디렉토리이며, 그 안의
  `README.md`가 "richer art가 필요하면 여기 CC0 팩을 넣고 `room_scene.js`의
  `preload()`를 바꿔 끼우라"고 안내합니다 — 즉 CC0 에셋 팩 통합은 계획에서
  언급됐지만 구현되지 않았고, 대신 의존성 0인 절차적 생성으로 대체되었습니다.
- **런타임 의존성 개수**: PLAN §P0은 "`fastapi`, `uvicorn`, `httpx`, `mcp` 4개"라고
  적었지만, 실제 `requirements.txt`에는 `tzdata`가 하나 더 있습니다. Windows의
  `zoneinfo`가 IANA 타임존 DB를 내장하지 않아 `Asia/Seoul` 리포트 스케줄링(P5)이
  깨지는 것을 막기 위한 추가로, 계획과 모순되기보다는 계획 이후 드러난 실무적
  보완입니다.
