// main.js — boots Phaser, wires SSE (with polling fallback) into the room
// scene and the DOM panels, and drives the topbar, status card, and stale
// indicator.
//
// This is the only file that touches window/document boot wiring; scene
// rendering lives in room_scene.js, panel DOM lives in panels.js, and the
// action/interest/decision -> UI rules live in mapping.js.

import { api, subscribeState } from "./api.js";
import { RoomScene } from "./room_scene.js";
import { initPanels } from "./panels.js";
import { ROOM_WIDTH, ROOM_HEIGHT, mapAction, MOOD_LABEL_KO } from "./mapping.js";

const DEFAULT_HEARTBEAT_MS = 30 * 60 * 1000; // matches config.example.json agent.heartbeat_minutes default
const STALE_MULTIPLIER = 2;
const THEME_KEY = "soul-theme";

const STATUS_KO = {
  awake: "활동 중",
  idle: "대기 중",
  chatting: "대화 중",
  error: "오류",
};

// Decision label + token per the shared design contract (labels are bilingual;
// chips use --d-<token>-soft bg with --d-<token> text). Presentation only.
const DECISION_META = {
  deepen: { label: "몰입 deepen", token: "deepen" },
  new: { label: "새 시도 new", token: "new" },
  shelve: { label: "보류 shelve", token: "shelve" },
  abandon: { label: "그만둠 abandon", token: "abandon" },
};

function computeStale(state) {
  if (!state) return true;
  if (state.stale === true) return true;
  // Preferred: the server says when this snapshot becomes stale (stale_at
  // accounts for the running step's hard timeout — a silent multi-minute step
  // is normal, especially in continuous mode). Judged on the client clock so
  // the flag can flip even when no new SSE event ever arrives.
  if (state.stale_at) {
    const staleMs = new Date(state.stale_at).getTime();
    if (!isNaN(staleMs)) return Date.now() > staleMs;
  }
  // Fallback for payloads without stale_at (e.g. the mock transport).
  if (!state.updated_at) return false; // no timestamp to judge by; don't assume stale
  const updatedMs = new Date(state.updated_at).getTime();
  if (isNaN(updatedMs)) return false;

  let heartbeatMs = DEFAULT_HEARTBEAT_MS;
  if (state.next_wake_at) {
    const nextMs = new Date(state.next_wake_at).getTime();
    if (!isNaN(nextMs) && nextMs > updatedMs) {
      heartbeatMs = nextMs - updatedMs;
    }
  }
  return Date.now() - updatedMs > heartbeatMs * STALE_MULTIPLIER;
}

// --------------------------------------------------------------------------- #
// small helpers
// --------------------------------------------------------------------------- #
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// "N분" / "N시간 M분" — used for the stale "…동안 응답이 없습니다" gap.
function humanizeAgo(ms) {
  const totalMin = Math.max(0, Math.floor(ms / 60000));
  if (totalMin < 60) return `${totalMin}분`;
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return m ? `${h}시간 ${m}분` : `${h}시간`;
}

// "방금 전" / "N분 전" / "N시간 M분 전" — status card relative timestamp.
function humanizeRelative(tsMs) {
  const diff = Date.now() - tsMs;
  if (diff < 60000) return "방금 전";
  const totalMin = Math.floor(diff / 60000);
  if (totalMin < 60) return `${totalMin}분 전`;
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return m ? `${h}시간 ${m}분 전` : `${h}시간 전`;
}

// --------------------------------------------------------------------------- #
// theme (persisted; default light)
// --------------------------------------------------------------------------- #
function applyTheme(theme) {
  const root = document.getElementById("soul-app");
  if (root) root.setAttribute("data-theme", theme);
  const btn = document.getElementById("btn-theme");
  if (btn) btn.textContent = theme === "light" ? "☾" : "☀";
}

function initTheme() {
  let theme = "light";
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "dark" || stored === "light") theme = stored;
  } catch (_e) {
    /* localStorage unavailable — stay on default */
  }
  applyTheme(theme);
  const btn = document.getElementById("btn-theme");
  if (btn) {
    btn.addEventListener("click", () => {
      const root = document.getElementById("soul-app");
      const next = root && root.getAttribute("data-theme") === "light" ? "dark" : "light";
      applyTheme(next);
      try {
        localStorage.setItem(THEME_KEY, next);
      } catch (_e) {
        /* ignore persistence failure */
      }
    });
  }
}

// --------------------------------------------------------------------------- #
// popovers (config / honesty) — mutually exclusive
// --------------------------------------------------------------------------- #
function initPopovers() {
  const cfg = document.getElementById("popover-config");
  const hon = document.getElementById("popover-honesty");
  const show = (el, on) => { if (el) el.style.display = on ? "block" : "none"; };
  const toggleConfig = () => { const open = cfg && cfg.style.display !== "block"; show(cfg, open); show(hon, false); };
  const toggleHonesty = () => { const open = hon && hon.style.display !== "block"; show(hon, open); show(cfg, false); };
  document.getElementById("btn-config")?.addEventListener("click", toggleConfig);
  document.getElementById("btn-honesty")?.addEventListener("click", toggleHonesty);
  document.getElementById("config-close")?.addEventListener("click", () => show(cfg, false));
  document.getElementById("honesty-close")?.addEventListener("click", () => show(hon, false));
}

// Fill the read-only settings popover from /api/config; never crash on failure.
async function loadConfig() {
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  // 전송/기록 정책은 config가 정하는 값이 아니라 정책 문구 — 실패해도 그대로 표시.
  set("cfg-transport", "SSE · 폴백 5초");
  set("cfg-record", "대화 토글 따름");
  try {
    const c = await api.getConfig();
    set("cfg-heartbeat", `${c.heartbeat_minutes}분`);
    set("cfg-model", c.model || "—");
    set("cfg-skill", `연속 실패 ${c.skill_auto_disable_failures}회`);
  } catch (_e) {
    set("cfg-heartbeat", "—");
    set("cfg-model", "—");
    set("cfg-skill", "—");
  }
}

// --------------------------------------------------------------------------- #
// topbar + status card renderers (fed from state + client-side stale judgment)
// --------------------------------------------------------------------------- #
function renderTopbar(state, isStale, transport) {
  const chip = document.getElementById("status-chip");
  const dot = document.getElementById("status-dot");
  const label = document.getElementById("status-label");
  let text, color, bg, anim;
  if (isStale) {
    text = "연결 지연됨";
    color = "var(--warn)";
    bg = "var(--warn-soft)";
    anim = "soulBlink 2.4s infinite";
  } else {
    text = (state && STATUS_KO[state.status]) || "대기 중";
    color = "var(--accent-ink)";
    bg = "var(--accent-soft)";
    anim = "soulPulse 2.2s infinite";
  }
  if (label) label.textContent = text;
  if (chip) { chip.style.background = bg; chip.style.color = color; }
  if (dot) dot.style.animation = anim;

  const thread = document.getElementById("topbar-thread");
  if (thread) {
    const t = state && state.current_thread;
    if (t && t.topic) {
      let steps = t.steps;
      if (steps == null && Array.isArray(t.interest_series)) steps = t.interest_series.length;
      const stepsPart = steps != null ? ` · ${esc(steps)}스텝` : "";
      thread.innerHTML = `스레드: <strong style="color:var(--ink)">${esc(t.topic)}</strong>${stepsPart}`;
    } else {
      thread.textContent = "";
    }
  }

  const nw = document.getElementById("next-wake");
  if (nw) {
    if (isStale) {
      nw.textContent = "다음 활동: 알 수 없음";
    } else if (state && state.next_wake_at) {
      const d = new Date(state.next_wake_at);
      if (!isNaN(d.getTime())) {
        const hhmm = d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false });
        const mins = Math.max(1, Math.round((d.getTime() - Date.now()) / 60000));
        nw.textContent = `다음 활동 ${hhmm} · ${mins}분 후`;
      } else {
        nw.textContent = "";
      }
    } else {
      nw.textContent = "";
    }
  }

  const cd = document.getElementById("conn-dot");
  const cl = document.getElementById("conn-label");
  if (cd && cl && transport) {
    if (transport === "sse") {
      cd.style.background = "oklch(0.65 0.15 145)";
      cl.textContent = "실시간 연결";
    } else {
      cd.style.background = "oklch(0.6 0.18 25)";
      cl.textContent = "폴링 모드 (5초)";
    }
  }
}

function renderStatusCard(state, isStale) {
  const card = document.getElementById("status-card");
  if (!card) return;

  if (isStale) {
    let ago = "";
    if (state && state.updated_at) {
      const ms = Date.now() - new Date(state.updated_at).getTime();
      if (!isNaN(ms)) ago = humanizeAgo(ms);
    }
    card.innerHTML =
      `<div style="display:flex;gap:10px;align-items:flex-start;font-size:var(--fs-sm);color:var(--ink-soft)">` +
        `<span style="width:8px;height:8px;border-radius:50%;background:var(--warn);margin-top:6px;flex-shrink:0;animation:soulBlink 2.4s infinite"></span>` +
        `<div><strong style="color:var(--ink)">연결이 지연되고 있어요.</strong> 에이전트 프로세스에서 ${esc(ago)} 동안 응답이 없습니다. 마지막으로 기록된 상태를 보여드리고 있어요 — 프로세스가 돌아오면 자동으로 이어집니다.</div>` +
      `</div>`;
    return;
  }

  const ls = state && state.last_step;
  if (!ls) {
    card.innerHTML = `<div style="font-size:var(--fs-sm);color:var(--ink-faint)">아직 기록된 스텝이 없습니다.</div>`;
    return;
  }

  let rel = "";
  if (ls.ts) {
    const ms = new Date(ls.ts).getTime();
    if (!isNaN(ms)) rel = humanizeRelative(ms);
  }

  // Action label from mapping.js; strip the trailing "중" so it reads as a
  // completed action ("코드 실험을 마쳤습니다").
  const actionLabel = mapAction(ls.action).label || "";
  const stem = actionLabel.replace(/\s*중$/, "").trim() || actionLabel;

  let decisionChip = "";
  const dm = DECISION_META[ls.decision];
  if (dm) {
    decisionChip = `<span style="padding:1px 8px;border-radius:999px;font-size:var(--fs-xs);background:var(--d-${dm.token}-soft);color:var(--d-${dm.token})">${esc(dm.label)}</span>`;
  }

  let imChip = "";
  const moodKo = ls.mood ? (MOOD_LABEL_KO[ls.mood] || ls.mood) : null;
  const parts = [];
  if (ls.interest != null) parts.push(`흥미 ${esc(ls.interest)}/10`);
  if (moodKo) parts.push(esc(moodKo));
  if (parts.length) {
    imChip = `<span style="padding:1px 8px;border-radius:999px;font-size:var(--fs-xs);background:var(--panel-2);color:var(--ink-soft);border:1px solid var(--line-soft)">${parts.join(" · ")}</span>`;
  }

  // state.last_step (loop.py) has no `reason` field — only {id, action, topic,
  // summary, mood, interest, decision, ts}. Fall back to summary; keep reason
  // first for forward-compat if the shape ever grows one.
  const quote = ls.reason || ls.summary;
  const reason = quote ? `<div style="color:var(--ink-soft)">"${esc(quote)}"</div>` : "";

  card.innerHTML =
    `<div style="display:flex;flex-direction:column;gap:6px;font-size:var(--fs-sm)">` +
      `<div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap">` +
        (rel ? `<span style="color:var(--ink-faint);font-family:var(--mono);font-size:var(--fs-xs)">${esc(rel)}</span>` : "") +
        (stem ? `<span><strong>${esc(stem)}</strong>을 마쳤습니다.</span>` : "") +
        decisionChip +
        imChip +
      `</div>` +
      reason +
    `</div>`;
}

function boot() {
  initTheme();
  initPopovers();
  loadConfig();

  const config = {
    type: Phaser.AUTO,
    parent: "game-container",
    width: ROOM_WIDTH,
    height: ROOM_HEIGHT,
    backgroundColor: "#f1e6d2",
    scene: [RoomScene],
    render: { pixelArt: true, antialias: false },
    // FIT the 960x600 scene into the responsive aspect-ratio room box.
    scale: {
      mode: Phaser.Scale.FIT,
      autoCenter: Phaser.Scale.CENTER_BOTH,
      width: ROOM_WIDTH,
      height: ROOM_HEIGHT,
    },
  };

  const game = new Phaser.Game(config);

  const panelsRoot = document.getElementById("panels-root");
  let chattingOverride = false;
  // Reading game.scene.keys.room synchronously right after `new
  // Phaser.Game()` is unreliable (the scene manager boots asynchronously on
  // the next game step). room_scene.js instead emits "room-ready" with
  // itself once its create() has fully run; we hold the reference here.
  let scene = null;

  const panels = initPanels({
    root: panelsRoot,
    api,
    onChatStateChange: (isChatting) => {
      chattingOverride = isChatting;
      // Immediate local feedback: move the character to the door without
      // waiting for the next SSE/poll tick.
      if (isChatting && scene) {
        scene.applyState({ status: "chatting", stale: false, last_step: null, updated_at: new Date().toISOString() });
      }
    },
  });

  function onReady(roomScene) {
    scene = roomScene;
    scene.events.on("bubbleClick", (stepId) => {
      if (stepId) panels.openStep(stepId);
    });

    let latestState = null;
    let lastTransport = null;

    function render() {
      const stale = computeStale(latestState);
      let effective = latestState;
      if (latestState) {
        // The scene reads state.stale — feed it the client-side judgment so
        // the room and the status bar can never disagree.
        effective = { ...latestState, stale };
        if (chattingOverride) effective.status = "chatting";
      }
      scene.applyState(effective);
      renderTopbar(effective, stale, lastTransport);
      renderStatusCard(effective, stale);
      const inner = document.getElementById("room-inner");
      if (inner) inner.style.filter = stale ? "grayscale(0.65) contrast(0.92)" : "none";
    }

    const unsubscribe = subscribeState(
      (state, transport) => {
        latestState = state;
        lastTransport = transport;
        render();
        panels.refreshRevealed();
        panels.refreshStats();
        panels.setOutboxBadge(state && state.open_requests ? state.open_requests : 0);
      },
      { pollMs: 5000 }
    );

    // SSE only fires on state.json changes: a dead agent loop stops producing
    // events, so staleness must be re-judged on a timer to ever flip the UI.
    // The 10s tick also refreshes the next-wake countdown.
    const staleTimer = setInterval(() => {
      if (latestState) render();
    }, 10000);

    window.addEventListener("beforeunload", () => {
      clearInterval(staleTimer);
      unsubscribe();
    });

    // Initial empty-state render in case no update arrives immediately
    // (fresh install / server not reachable yet) — show an idle room, not
    // a blank/broken page.
    if (!latestState) {
      scene.applyState(null);
    }
  }

  game.events.once("room-ready", onReady);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
