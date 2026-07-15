// mapping.js — single source of truth for action→position/animation,
// interest→expression, decision→one-shot effect, and related UI mapping.
// PLAN.md §P4 "매핑 규칙 (mapping.js 단일 소스)" is the spec this file implements.
//
// Plain ES module, no build step, no external deps.

// ---------------------------------------------------------------------------
// Room stations. Each station has a name, a pixel position (room-local
// coordinates, room is designed at ROOM_WIDTH x ROOM_HEIGHT), and a facing
// direction hint used by room_scene.js when placing/orienting the character.
// ---------------------------------------------------------------------------

export const ROOM_WIDTH = 960;
export const ROOM_HEIGHT = 600;

export const STATIONS = {
  bed: { x: 120, y: 140, facing: "down" },
  desk: { x: 260, y: 420, facing: "up" }, // writing desk (free_write)
  bookshelf: { x: 620, y: 130, facing: "down" }, // revisit_notes / organize_notes
  window_rug: { x: 480, y: 300, facing: "down" }, // thought_experiment
  computer: { x: 780, y: 420, facing: "up" }, // code_experiment
  window_laptop: { x: 480, y: 150, facing: "down" }, // web_explore
  workbench: { x: 820, y: 200, facing: "left" }, // skill:*
  mailbox: { x: 80, y: 480, facing: "right" }, // read_inbox
  door: { x: 470, y: 570, facing: "up" }, // chatting
  center: { x: 470, y: 320, facing: "down" }, // idle / stale / error
};

// ---------------------------------------------------------------------------
// action -> {station, animation, label}
// "label" is a short Korean phrase used for tooltips/fallback bubble text.
// ---------------------------------------------------------------------------

const ACTION_MAP = {
  free_write: { station: "desk", animation: "writing", label: "글 쓰는 중" },
  revisit_notes: { station: "bookshelf", animation: "reading", label: "메모 다시 보는 중" },
  organize_notes: { station: "bookshelf", animation: "tidying", label: "메모 정리 중" },
  thought_experiment: { station: "window_rug", animation: "thought-cloud", label: "생각 중" },
  code_experiment: { station: "computer", animation: "typing", label: "코드 실험 중" },
  web_explore: { station: "window_laptop", animation: "scrolling", label: "웹 탐색 중" },
  read_inbox: { station: "mailbox", animation: "opening", label: "우편함 확인 중" },
  rest: { station: "bed", animation: "zzz", label: "쉬는 중" },
  chatting: { station: "door", animation: "talk", label: "대화 중" },
  idle: { station: "center", animation: "wander", label: "어슬렁거리는 중" },
};

// skill:<name> actions all resolve to the workbench with a "tinkering" anim.
const SKILL_ACTION_PREFIX = "skill:";
const SKILL_DEFAULT = { station: "workbench", animation: "tinkering", label: "작업대에서 뭔가 하는 중" };

// stale / error: center, stopped, "…" bubble.
const STALE_MAPPING = { station: "center", animation: "stopped", label: "…" };
const ERROR_MAPPING = { station: "center", animation: "stopped", label: "…" };

/**
 * Resolve an action string (from last_step.action) to {station, animation, label}.
 * Defensive: unknown/missing actions fall back to idle/wander at center.
 */
export function mapAction(action) {
  if (!action || typeof action !== "string") {
    return { ...ACTION_MAP.idle };
  }
  if (action.startsWith(SKILL_ACTION_PREFIX)) {
    return { ...SKILL_DEFAULT };
  }
  const found = ACTION_MAP[action];
  if (found) return { ...found };
  return { ...ACTION_MAP.idle };
}

/**
 * Resolve overall UI status (from state.status / stale flag) to a station
 * override. Returns null when the action-based mapping should apply as-is.
 */
export function mapStatusOverride(status, stale) {
  if (stale) return { ...STALE_MAPPING };
  if (status === "error") return { ...ERROR_MAPPING };
  if (status === "chatting") return { ...ACTION_MAP.chatting };
  return null;
}

// ---------------------------------------------------------------------------
// interest (1-10) -> expression tier
// ---------------------------------------------------------------------------

/**
 * Returns one of: "droop" (1-3), "neutral" (4-6), "smile" (7-8), "sparkle" (9-10).
 * Defensive: missing/out-of-range interest -> "neutral".
 */
export function mapInterestTier(interest) {
  const n = Number(interest);
  if (!Number.isFinite(n)) return "neutral";
  if (n <= 3) return "droop";
  if (n <= 6) return "neutral";
  if (n <= 8) return "smile";
  return "sparkle";
}

export const INTEREST_TIER_STYLE = {
  droop: { desaturate: true, particles: false, sparkle: false, mouth: "frown" },
  neutral: { desaturate: false, particles: false, sparkle: false, mouth: "flat" },
  smile: { desaturate: false, particles: false, sparkle: true, mouth: "smile" },
  sparkle: { desaturate: false, particles: true, sparkle: true, mouth: "bigsmile" },
};

// ---------------------------------------------------------------------------
// mood -> tint/eye hint (secondary, softer signal than interest)
// ---------------------------------------------------------------------------

export const MOOD_LABEL_KO = {
  neutral: "평온",
  curious: "호기심",
  excited: "신남",
  calm: "차분",
  bored: "지루함",
  frustrated: "답답함",
  tired: "피곤함",
  proud: "뿌듯함",
};

// ---------------------------------------------------------------------------
// decision -> one-shot effect (played once when a new step arrives)
// ---------------------------------------------------------------------------

const DECISION_EFFECTS = {
  deepen: { kind: "bulb-spark", label: "몰입" },
  new: { kind: "bang-relocate", label: "새로운 시도" },
  shelve: { kind: "note-slot", label: "보류" },
  abandon: { kind: "crumple-paper", label: "그만둠" },
};

/**
 * Resolve decision -> one-shot effect descriptor, or null if unknown/missing.
 */
export function mapDecisionEffect(decision) {
  if (!decision) return null;
  return DECISION_EFFECTS[decision] || null;
}

// ---------------------------------------------------------------------------
// Speech bubble timing
// ---------------------------------------------------------------------------

export const SPEECH_BUBBLE_MS = 30000;

/**
 * Build bubble text from a last_step summary object. Defensive against
 * missing fields; falls back to the action's Korean label, then "…".
 */
export function bubbleTextFor(lastStep) {
  if (!lastStep || typeof lastStep !== "object") return null;
  if (lastStep.summary && typeof lastStep.summary === "string" && lastStep.summary.trim()) {
    return lastStep.summary.trim();
  }
  const m = mapAction(lastStep.action);
  return m.label || "…";
}

// ---------------------------------------------------------------------------
// Wiki-write "desk prop shimmer" hint (P4: wiki 쓰기 있던 스텝은 책상 위
// "위키 노트" 소품 반짝임)
// ---------------------------------------------------------------------------

export function hadWikiWrite(step) {
  if (!step || !Array.isArray(step.wiki_ops)) return false;
  return step.wiki_ops.some((op) => op && op.tool === "wiki_write");
}
