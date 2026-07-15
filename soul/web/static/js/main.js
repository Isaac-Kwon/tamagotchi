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
  const scene = game.scene.keys.room;

  const panelsRoot = document.getElementById("panels-root");
  let chattingOverride = false;

  const panels = initPanels({
    root: panelsRoot,
    api,
    onChatStateChange: (isChatting) => {
      chattingOverride = isChatting;
      // Immediate local feedback: move the character to the door without
      // waiting for the next SSE/poll tick.
      if (isChatting) {
        scene.applyState({ status: "chatting", stale: false, last_step: null, updated_at: new Date().toISOString() });
      }
    },
  });

  function onReady() {
    scene.events.on("bubbleClick", (stepId) => {
      if (stepId) panels.openStep(stepId);
    });

    let latestState = null;

    const unsubscribe = subscribeState(
      (state, transport) => {
        latestState = state;
        setConnStatus(transport === "sse" ? "실시간 연결" : "폴링 모드 (5초)");
        const stale = computeStale(state);
        const effective = chattingOverride && state ? { ...state, status: "chatting" } : state;
        scene.applyState(effective);
        setStatusBar(state, stale);
        panels.refreshRevealed();
      },
      { pollMs: 5000 }
    );

    window.addEventListener("beforeunload", () => unsubscribe());

    // Initial empty-state render in case no update arrives immediately
    // (fresh install / server not reachable yet) — show an idle room, not
    // a blank/broken page.
    if (!latestState) {
      scene.applyState(null);
      setStatusBar(null, false);
    }
  }

  // Scene.create() runs asynchronously on the next game step, so this
  // listener reliably fires exactly once after the room is fully built.
  scene.events.once(Phaser.Scenes.Events.CREATE, onReady);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
