// api.js — thin client for the Soul Tamagotchi web API.
//
// Contract (same-origin, base path ""):
//   GET  /api/state
//   GET  /api/steps?limit=N
//   GET  /api/step/{id}
//   GET  /api/step/{id}/transcript
//   GET  /api/soul
//   GET  /api/soul/history
//   GET  /api/soul/diff/{commit}
//   GET  /api/reports
//   GET  /api/report/{date}
//   GET  /api/revealed
//   GET  /api/stats?timeline=N
//   GET  /api/skills
//   GET  /api/config
//   GET  /api/wiki/pages
//   GET  /api/wiki/search?q=
//   GET  /api/wiki/page/{slug}
//   GET  /api/wiki/graph
//   SSE  /api/events               (event name "state", data = state JSON)
//   POST /api/chat                 {message, session_id|null, record}
//   POST /api/chat/end             {session_id}
//   GET  /api/chat/{session_id}
//   POST /api/inbox                {kind:"message"|"gift", content, url?}
//   GET  /api/outbox?status=       {requests:[...]}
//   POST /api/outbox/{id}/resolve  multipart form (status, note?, file?)
//
// Mock mode: append ?mock=1 to the page URL to serve canned in-JS fixtures
// instead of hitting the network. Useful for UI development without a
// running API server, and for offline verification. Keep this in the code;
// it is genuinely useful after M7 too.

const MOCK = new URLSearchParams(location.search).get("mock") === "1";

// ---------------------------------------------------------------------------
// Mock fixtures
// ---------------------------------------------------------------------------

const MOCK_ACTIONS = [
  "free_write",
  "revisit_notes",
  "organize_notes",
  "thought_experiment",
  "code_experiment",
  "web_explore",
  "read_inbox",
  "rest",
  "skill:doodle",
  "idle",
];
const MOCK_DECISIONS = ["deepen", "new", "shelve", "abandon"];
const MOCK_MOODS = ["neutral", "curious", "excited", "calm", "bored", "frustrated", "tired", "proud"];

let mockStepCounter = 0;
let mockCurrentAction = MOCK_ACTIONS[0];

function mockLastStep() {
  const n = mockStepCounter;
  return {
    id: `step-${String(n).padStart(6, "0")}`,
    ts: new Date().toISOString(),
    kind: "wake_step",
    action: mockCurrentAction,
    topic: "목업 주제 " + n,
    thread_id: "th-mock",
    interest: 1 + ((n * 3) % 10),
    interest_delta: ["more", "less", "same", "first"][n % 4],
    mood: MOCK_MOODS[n % MOCK_MOODS.length],
    reason: "목업 이유 텍스트입니다.",
    decision: MOCK_DECISIONS[n % MOCK_DECISIONS.length],
    summary: `[목업] ${mockCurrentAction} 을(를) 하는 중 (스텝 ${n})`,
    wiki_ops: n % 3 === 0 ? [{ tool: "wiki_write", slug: "mock-page" }] : [],
  };
}

function mockState() {
  return {
    status: "awake",
    stale: false,
    last_step: mockLastStep(),
    current_thread: { topic: "목업 스레드", steps: 3, interest_series: [4, 5, 7] },
    shelved_threads: [{ thread_id: "th-old", topic: "예전 관심사" }],
    revealed: {
      top_threads: [{ topic: "예전 관심사", revisits: 2, persistence_steps: 5 }],
      stated_vs_revealed_note: "stated 흥미는 대체로 revealed보다 높게 나타납니다 (목업 데이터).",
    },
    next_wake_at: new Date(Date.now() + 5 * 60000).toISOString(),
    today_report: null,
    open_requests: 1,
    updated_at: new Date().toISOString(),
  };
}

const MOCK_SOUL_MD = `# SOUL\n\n(목업 모드) 아직 거의 비어 있습니다.\n`;

const MOCK_WIKI_PAGES = [
  { slug: "mock-page", title: "목업 페이지", updated: new Date().toISOString() },
  { slug: "another-page", title: "다른 페이지", updated: new Date().toISOString() },
];

const MOCK_OUTBOX = [
  {
    id: "req-0002",
    ts: new Date(Date.now() - 3600000).toISOString(),
    step_id: "step-000012",
    text: "numpy 패키지를 설치해줄 수 있을까요? code_experiment에서 필요합니다.",
    status: "open",
    resolved_ts: null,
    observer_note: null,
    attachment: null,
  },
  {
    id: "req-0001",
    ts: new Date(Date.now() - 86400000).toISOString(),
    step_id: "step-000004",
    text: "이 논문을 읽고 싶은데 접근이 막혀 있습니다. 받아볼 수 있을까요?",
    status: "resolved",
    resolved_ts: new Date(Date.now() - 82800000).toISOString(),
    observer_note: "첨부해두었습니다. 도움이 되길 바랍니다.",
    attachment: "req-0001/paper.pdf",
  },
];

function mockStats() {
  const moods = MOCK_MOODS;
  const timeline = [];
  for (let i = 1; i <= 60; i++) {
    timeline.push({
      id: `step-${String(i).padStart(6, "0")}`,
      ts: new Date(Date.now() - (60 - i) * 120000).toISOString(),
      interest: 1 + ((i * 3) % 10),
      mood: moods[i % moods.length],
      decision: MOCK_DECISIONS[i % MOCK_DECISIONS.length],
      action: MOCK_ACTIONS[i % MOCK_ACTIONS.length],
    });
  }
  return {
    total_steps: 60,
    decisions: { deepen: 41, shelve: 8, abandon: 2, new: 9 },
    decision_total: 60,
    actions: { free_write: 12, thought_experiment: 18, code_experiment: 20, organize_notes: 8, web_explore: 2 },
    moods: { curious: 25, proud: 18, excited: 6, neutral: 5, frustrated: 6 },
    interest_hist: { "4": 1, "6": 6, "7": 14, "8": 24, "9": 14, "10": 1 },
    timeline,
    threads: [
      { thread_id: "th-0001", topic: "목업 스레드 A", steps: 5, start_ts: timeline[0].ts, end_ts: timeline[4].ts, avg_interest: 7.4 },
      { thread_id: "th-0006", topic: "목업 스레드 B (조금 더 긴 제목)", steps: 12, start_ts: timeline[5].ts, end_ts: timeline[16].ts, avg_interest: 8.2 },
      { thread_id: "th-0018", topic: "목업 스레드 C", steps: 2, start_ts: timeline[17].ts, end_ts: timeline[18].ts, avg_interest: 6.5 },
    ],
    errors: {
      count: 2,
      recent: [
        { id: "step-000031", ts: new Date(Date.now() - 3600000).toISOString(), phase: "act", message: "LLM request failed after 3 attempts: timed out" },
        { id: "step-000044", ts: new Date(Date.now() - 1800000).toISOString(), phase: "act", message: "act_json_unparseable" },
      ],
    },
  };
}

const MOCK_SKILLS = [
  {
    name: "doodle",
    description: "간단한 ASCII 그림을 그립니다.",
    version: 3,
    enabled: true,
    failures: 2,
    created_at: new Date(Date.now() - 86400000).toISOString(),
    updated_at: new Date(Date.now() - 3600000).toISOString(),
  },
  {
    name: "old-tool",
    description: "실패가 누적되어 자동 비활성화된 스킬.",
    version: 1,
    enabled: false,
    failures: 3,
    created_at: new Date(Date.now() - 172800000).toISOString(),
    updated_at: new Date(Date.now() - 86400000).toISOString(),
  },
];

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function mockFetch(path, opts) {
  await delay(60 + Math.random() * 80);
  const url = new URL(path, location.origin);
  const p = url.pathname;
  const method = (opts && opts.method) || "GET";

  if (p === "/api/state") return mockState();
  if (p === "/api/steps") {
    const limit = Number(url.searchParams.get("limit")) || 20;
    const steps = [];
    for (let i = 0; i < Math.min(limit, 10); i++) {
      mockStepCounter++;
      mockCurrentAction = MOCK_ACTIONS[mockStepCounter % MOCK_ACTIONS.length];
      steps.push(mockLastStep());
    }
    return { steps: steps.reverse() };
  }
  if (p.startsWith("/api/step/") && p.endsWith("/transcript")) {
    return {
      entries: [
        { role: "system", content: "(mock) system prompt excerpt" },
        { role: "assistant", content: "(mock) reasoning/tool call excerpt" },
      ],
    };
  }
  if (p.startsWith("/api/step/")) {
    return { record: mockLastStep(), content: "# 목업 산출물\n\n본문 텍스트입니다." };
  }
  if (p === "/api/soul") return { content: MOCK_SOUL_MD, updated_at: new Date().toISOString() };
  if (p === "/api/soul/history") {
    return {
      commits: [
        { commit: "abc1234", ts: new Date().toISOString(), message: "soul: 목업 변경 1" },
        { commit: "def5678", ts: new Date(Date.now() - 86400000).toISOString(), message: "soul: 목업 변경 0" },
      ],
    };
  }
  if (p.startsWith("/api/soul/diff/")) {
    return { diff: "--- a/SOUL.md\n+++ b/SOUL.md\n@@ -1 +1,2 @@\n (목업 diff)\n+새 줄\n" };
  }
  if (p === "/api/reports") {
    const today = new Date().toISOString().slice(0, 10);
    return { dates: [today] };
  }
  if (p.startsWith("/api/report/")) {
    return { date: p.split("/").pop(), content: "오늘의 회고 (목업).\n\n특별한 일은 없었다." };
  }
  if (p === "/api/revealed") {
    return (await mockState()).revealed;
  }
  if (p === "/api/stats") return mockStats();
  if (p === "/api/skills") return { skills: MOCK_SKILLS, auto_disable_after_failures: 3 };
  if (p === "/api/config") {
    return { heartbeat_minutes: 30, mode: "heartbeat", model: "gpt-4o-mini", sse_check_ms: 1000, skill_auto_disable_failures: 3 };
  }
  if (p === "/api/wiki/pages") return { pages: MOCK_WIKI_PAGES };
  if (p === "/api/wiki/search") {
    const q = url.searchParams.get("q") || "";
    return { results: MOCK_WIKI_PAGES.filter((pg) => pg.title.includes(q) || !q).map((pg) => ({ ...pg, snippet: "…검색 스니펫…" })) };
  }
  if (p.startsWith("/api/wiki/page/")) {
    const slug = p.split("/").pop();
    return { slug, content: `# ${slug}\n\n목업 위키 본문. [[another-page]] 링크 포함.`, backlinks: ["another-page"] };
  }
  if (p === "/api/wiki/graph") {
    return {
      nodes: MOCK_WIKI_PAGES.map((pg) => ({ id: pg.slug, title: pg.title })),
      links: [{ src: "mock-page", dst: "another-page" }],
    };
  }
  if (p === "/api/chat" && method === "POST") {
    return { session_id: "mock-session", reply: "(목업) 안녕하세요, 대화는 기록되지 않는 모드입니다." };
  }
  if (p === "/api/chat/end" && method === "POST") return { ok: true };
  if (p.startsWith("/api/chat/")) return { session_id: p.split("/").pop(), turns: [] };
  if (p === "/api/inbox" && method === "POST") return { ok: true };
  if (p === "/api/outbox" && method === "GET") {
    const status = url.searchParams.get("status");
    const requests = status ? MOCK_OUTBOX.filter((r) => r.status === status) : MOCK_OUTBOX;
    return { requests };
  }
  if (p.startsWith("/api/outbox/") && p.endsWith("/resolve") && method === "POST") {
    const id = p.split("/")[3];
    const body = opts && opts.body;
    const status = body && typeof body.get === "function" ? body.get("status") : "resolved";
    return { id, status };
  }

  return { error: "mock: unknown path " + p };
}

// ---------------------------------------------------------------------------
// Real fetch helpers
// ---------------------------------------------------------------------------

async function request(path, opts) {
  if (MOCK) return mockFetch(path, opts);
  // FormData bodies must keep the browser-generated multipart Content-Type
  // (with boundary) — never force application/json on them.
  const isForm = typeof FormData !== "undefined" && opts && opts.body instanceof FormData;
  const baseHeaders = isForm ? {} : { "Content-Type": "application/json" };
  const res = await fetch(path, {
    headers: { ...baseHeaders, ...(opts && opts.headers) },
    ...opts,
  });
  if (!res.ok) {
    let bodyText = "";
    try {
      bodyText = await res.text();
    } catch (_e) {
      /* ignore */
    }
    throw new Error(`API ${path} -> ${res.status} ${res.statusText} ${bodyText}`.trim());
  }
  // Some endpoints (e.g. chat/end) may return empty body.
  const text = await res.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch (_e) {
    throw new Error(`API ${path} -> invalid JSON response`);
  }
}

function get(path) {
  return request(path, { method: "GET" });
}

function post(path, body) {
  return request(path, { method: "POST", body: JSON.stringify(body || {}) });
}

// Multipart/form-data POST: pass the FormData through untouched and do NOT set
// a JSON Content-Type — the browser must set multipart boundary itself.
function postForm(path, formData) {
  if (MOCK) return mockFetch(path, { method: "POST", body: formData });
  return request(path, { method: "POST", body: formData, headers: {} });
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export const api = {
  isMock: MOCK,

  getState: () => get("/api/state"),
  getSteps: (limit = 20) => get(`/api/steps?limit=${encodeURIComponent(limit)}`),
  getStep: (id) => get(`/api/step/${encodeURIComponent(id)}`),
  getStepTranscript: (id) => get(`/api/step/${encodeURIComponent(id)}/transcript`),

  getSoul: () => get("/api/soul"),
  getSoulHistory: () => get("/api/soul/history"),
  getSoulDiff: (commit) => get(`/api/soul/diff/${encodeURIComponent(commit)}`),

  getReports: () => get("/api/reports"),
  getReport: (date) => get(`/api/report/${encodeURIComponent(date)}`),

  getRevealed: () => get("/api/revealed"),
  getStats: (timeline = 250) => get(`/api/stats?timeline=${encodeURIComponent(timeline)}`),
  getSkills: () => get("/api/skills"),
  getConfig: () => get("/api/config"),

  getWikiPages: () => get("/api/wiki/pages"),
  searchWiki: (q) => get(`/api/wiki/search?q=${encodeURIComponent(q || "")}`),
  getWikiPage: (slug) => get(`/api/wiki/page/${encodeURIComponent(slug)}`),
  getWikiGraph: () => get("/api/wiki/graph"),

  sendChat: (message, sessionId, record) =>
    post("/api/chat", { message, session_id: sessionId || null, record: !!record }),
  endChat: (sessionId) => post("/api/chat/end", { session_id: sessionId }),
  getChatSession: (sessionId) => get(`/api/chat/${encodeURIComponent(sessionId)}`),

  postInbox: (kind, content, url) => post("/api/inbox", { kind, content, url }),

  getOutbox: (status) => get(`/api/outbox${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  resolveOutbox: (id, formData) => postForm(`/api/outbox/${encodeURIComponent(id)}/resolve`, formData),
};

// ---------------------------------------------------------------------------
// Live updates: SSE with reconnect backoff, falling back to polling.
// onState(stateObj) is called on every update, from either transport.
// Returns a function to stop the subscription.
// ---------------------------------------------------------------------------

export function subscribeState(onState, opts = {}) {
  const pollMs = opts.pollMs || 5000;
  let stopped = false;
  let es = null;
  let pollTimer = null;
  let backoffMs = 1000;
  const maxBackoffMs = 30000;

  function startPolling() {
    if (pollTimer || stopped) return;
    const tick = async () => {
      if (stopped) return;
      try {
        const state = await api.getState();
        onState(state, "poll");
      } catch (_e) {
        // swallow; UI treats missing/stale updates via updated_at staleness check
      }
      if (!stopped) pollTimer = setTimeout(tick, pollMs);
    };
    tick();
  }

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function startSSE() {
    if (MOCK) {
      // No real SSE in mock mode; mock transport is polling-only, which
      // exercises the same onState/staleness code paths in the UI.
      startPolling();
      return;
    }
    if (typeof EventSource === "undefined") {
      startPolling();
      return;
    }
    try {
      es = new EventSource("/api/events");
    } catch (_e) {
      startPolling();
      return;
    }

    es.addEventListener("state", (ev) => {
      backoffMs = 1000; // reset backoff on any successful message
      try {
        const state = JSON.parse(ev.data);
        onState(state, "sse");
      } catch (_e) {
        // ignore malformed event
      }
    });

    es.onerror = () => {
      if (stopped) return;
      if (es) {
        es.close();
        es = null;
      }
      // Fall back to polling immediately, and try to reconnect SSE with backoff.
      startPolling();
      setTimeout(() => {
        if (stopped) return;
        stopPolling();
        backoffMs = Math.min(backoffMs * 2, maxBackoffMs);
        startSSE();
      }, backoffMs);
    };

    es.onopen = () => {
      backoffMs = 1000;
      stopPolling();
    };
  }

  startSSE();

  return function unsubscribe() {
    stopped = true;
    stopPolling();
    if (es) {
      es.close();
      es = null;
    }
  };
}
