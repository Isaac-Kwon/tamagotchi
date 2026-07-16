// main.js — boots Phaser, wires SSE (with polling fallback) into the room
// scene and the DOM panels, and drives the stale indicator.
//
// This is the only file that touches window/document boot wiring; scene
// rendering lives in room_scene.js, panel DOM lives in panels.js, and the
// action/interest/decision -> UI rules live in mapping.js.

import { api, subscribeState } from "./api.js";
import { RoomScene } from "./room_scene.js";
import { initPanels } from "./panels.js";
import { ROOM_WIDTH, ROOM_HEIGHT } from "./mapping.js";

const DEFAULT_HEARTBEAT_MS = 30 * 60 * 1000; // matches config.example.json agent.heartbeat_minutes default
const STALE_MULTIPLIER = 2;

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

function setConnStatus(text) {
  const el = document.getElementById("conn-status");
  if (el) el.textContent = text;
}

function setStatusBar(state, isStale) {
  const el = document.getElementById("status-bar");
  if (!el) return;
  if (!state) {
    el.textContent = "상태를 아직 불러오지 못했습니다.";
    return;
  }
  const statusKo = {
    awake: "활동 중",
    idle: "대기 중",
    chatting: "대화 중",
    error: "오류",
  };
  const parts = [];
  parts.push(isStale ? "연결 지연됨" : statusKo[state.status] || state.status || "알 수 없음");
  if (state.current_thread && state.current_thread.topic) {
    parts.push("스레드: " + state.current_thread.topic);
  }
  if (state.next_wake_at) {
    const d = new Date(state.next_wake_at);
    if (!isNaN(d.getTime())) parts.push("다음 활동: " + d.toLocaleTimeString("ko-KR"));
  }
  el.textContent = parts.join(" · ");
}

function boot() {
  const config = {
    type: Phaser.AUTO,
    parent: "game-container",
    width: ROOM_WIDTH,
    height: ROOM_HEIGHT,
    backgroundColor: "#f1e6d2",
    scene: [RoomScene],
    render: { pixelArt: true, antialias: false },
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
      setStatusBar(latestState, stale);
    }

    const unsubscribe = subscribeState(
      (state, transport) => {
        latestState = state;
        setConnStatus(transport === "sse" ? "실시간 연결" : "폴링 모드 (5초)");
        render();
        panels.refreshRevealed();
        panels.refreshStats();
        panels.setOutboxBadge(state && state.open_requests ? state.open_requests : 0);
      },
      { pollMs: 5000 }
    );

    // SSE only fires on state.json changes: a dead agent loop stops producing
    // events, so staleness must be re-judged on a timer to ever flip the UI.
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
      setStatusBar(null, false);
    }
  }

  game.events.once("room-ready", onReady);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
