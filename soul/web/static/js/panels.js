// panels.js — DOM-based side/overlay panels (not Phaser).
//
// Tabs (per PLAN.md P4/C), grouped in the tab bar as 관찰 / 기록 / 소통:
//   관찰: step(스텝 상세) · soul(영혼 성장) · revealed(말과 행동) · stats(통계)
//   기록: wiki(위키) · report(일일 리포트) · skills(스킬) · journal(저널)
//   소통: chat(대화) · inbox(선물) · outbox(요청)
//
// 탭 id 는 그대로 유지된다 (#hash 딥링크 호환). 예: /#stats.
//
// 프레젠테이션은 index.html(Agent A)이 정의한 디자인 토큰(--bg/--ink/--accent/
// --d-*/--m-* …)을 인라인 스타일로 소비한다. 이 파일이 의존하는 CSS 클래스는
// .chip 과 아래에서 1회 주입하는 `p-` 접두 hover 스타일뿐이다.

import { MOOD_LABEL_KO } from "./mapping.js";
import { renderMarkdownWithToggle } from "./markdown.js";

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "html") node.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
  }
  (children || []).forEach((c) => {
    if (c == null) return;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  });
  return node;
}

function fmtTime(iso) {
  if (!iso) return "-";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleString("ko-KR");
  } catch (_e) {
    return String(iso);
  }
}

// 저널/스텝 상세용 짧은 형식: YYYY-MM-DD HH:MM.
function fmtShort(iso) {
  const d = new Date(iso);
  if (!iso || isNaN(d.getTime())) return String(iso || "-");
  const p = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// 커밋 히스토리용 MM-DD.
function fmtMonthDay(iso) {
  const d = new Date(iso);
  if (!iso || isNaN(d.getTime())) return "";
  const p = (x) => String(x).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// LLM 트랜스크립트 호출 시각용 HH:MM:SS.
function fmtHms(iso) {
  const d = new Date(iso);
  if (!iso || isNaN(d.getTime())) return "";
  const p = (x) => String(x).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

// 일일 리포트 날짜: "2026-07-15" → "7월 15일".
function fmtReportDate(dateStr) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(dateStr || "");
  if (!m) return dateStr || "-";
  return `${Number(m[2])}월 ${Number(m[3])}일`;
}

// 빈/에러 상태 안내: 톤은 그대로, 색만 --ink-faint 로.
function emptyNote(text) {
  return el("div", { style: "color:var(--ink-faint);font-size:var(--fs-sm);padding:8px 0", text });
}

// --------------------------------------------------------------------------
// 8개 기분 → 8개 기분 토큰 (동일 채도). 예전의 3-발란스 색 구성을 대체한다.
// 디자인 매핑: 평온=--m-calm, 차분=--m-serene 임에 주의 (라벨은 mapping.js).
// --------------------------------------------------------------------------
const MOOD_TOKEN = {
  neutral: "--m-calm",
  curious: "--m-curious",
  excited: "--m-excited",
  calm: "--m-serene",
  bored: "--m-bored",
  frustrated: "--m-frustrated",
  tired: "--m-tired",
  proud: "--m-proud",
};
const MOOD_KEYS = ["curious", "excited", "neutral", "calm", "bored", "frustrated", "tired", "proud"];

function moodToken(mood) {
  return MOOD_TOKEN[mood] || "--m-calm";
}
function moodLabelKo(mood) {
  return MOOD_LABEL_KO[mood] || mood || "-";
}

// 네 결정은 대칭이다 — 고정 순서, 동일 형태의 라벨/토큰.
const DECISION_ORDER = ["deepen", "new", "shelve", "abandon"];
const DECISION_TOKEN = { deepen: "--d-deepen", new: "--d-new", shelve: "--d-shelve", abandon: "--d-abandon" };
const DECISION_LABEL = { deepen: "몰입 deepen", new: "새 시도 new", shelve: "보류 shelve", abandon: "그만둠 abandon" };

function decisionChip(decision) {
  const tok = DECISION_TOKEN[decision];
  if (!tok) {
    return el("span", {
      style: "padding:2px 10px;border-radius:999px;font-size:var(--fs-xs);background:var(--panel-2);color:var(--ink-soft);border:1px solid var(--line-soft)",
      text: decision || "-",
    });
  }
  return el("span", {
    style: `padding:2px 10px;border-radius:999px;font-size:var(--fs-xs);background:var(${tok}-soft);color:var(${tok});font-weight:600`,
    text: DECISION_LABEL[decision],
  });
}

// 통계/행동 라벨: 원문 액션 키를 한국어로 (판독성). 미지 키는 그대로.
const ACTION_LABEL_KO = {
  free_write: "글쓰기",
  revisit_notes: "메모 다시보기",
  organize_notes: "메모 정리",
  thought_experiment: "사고실험",
  code_experiment: "코드 실험",
  web_explore: "웹 탐색",
  read_inbox: "우편함",
  rest: "쉬기",
  idle: "어슬렁",
  chatting: "대화",
};
function actionLabelKo(a) {
  if (!a) return "-";
  if (typeof a === "string" && a.startsWith("skill:")) return "스킬:" + a.slice(6);
  return ACTION_LABEL_KO[a] || a;
}

function pct(n, total) {
  if (!total) return "0%";
  return Math.round((n / total) * 100) + "%";
}

// 공통 인라인 스타일 상수 (디자인 프로토타입에서 그대로 옮김).
const INPUT_STYLE =
  "font-family:inherit;font-size:var(--fs-sm);padding:9px 12px;border-radius:var(--radius-sm);border:1px solid var(--line);background:var(--panel-2);color:var(--ink);box-sizing:border-box;width:100%";
const ACCENT_BTN =
  "padding:9px 20px;border-radius:var(--radius-sm);border:1px solid var(--accent);background:var(--accent);color:#fff;font-size:var(--fs-sm);font-weight:600";
const GHOST_BTN =
  "padding:7px 16px;border-radius:var(--radius-sm);border:1px solid var(--line);background:var(--panel);color:var(--ink);font-size:var(--fs-sm)";
const CARD_SOFT =
  "background:var(--panel-2);border:1px solid var(--line-soft);border-radius:var(--radius-sm);padding:12px 14px";
const STAT_H3 = "margin:0 0 10px;font-size:var(--fs-sm);color:var(--ink-faint);font-weight:600";
const CONTENT_PRE =
  "margin:0;background:var(--panel-2);border:1px solid var(--line-soft);border-radius:var(--radius-sm);padding:14px;font-family:var(--mono);font-size:12.5px;overflow-x:auto;color:var(--ink-soft);white-space:pre-wrap;word-break:break-word";
const DIFF_PRE =
  "margin:6px 0 0;background:var(--panel-2);border:1px solid var(--line-soft);border-radius:var(--radius-sm);padding:10px 12px;font-family:var(--mono);font-size:11.5px;overflow-x:auto;line-height:1.6;white-space:pre-wrap;word-break:break-word";
const BADGE_STYLE =
  "min-width:16px;height:16px;border-radius:999px;background:var(--warn);color:#fff;font-size:10px;display:inline-grid;place-items:center;padding:0 4px";
const NAV_STYLE =
  "display:flex;gap:var(--sp-4);padding:10px var(--sp-4);border-bottom:1px solid var(--line-soft);background:var(--panel-2);flex-wrap:wrap;align-items:center;flex-shrink:0";

// hover 상태만 담는 1회성 스타일시트 (인라인으로는 표현 불가). 모든 클래스 `p-`.
const PANEL_HOVER_CSS = `
.p-tab{transition:filter .12s}
.p-tab:hover{filter:brightness(0.96)}
.p-ghostbtn:hover{background:var(--panel-2) !important}
.p-solidbtn:hover{filter:brightness(1.06)}
.p-row{transition:border-color .12s,background .12s}
.p-row:hover{border-color:var(--line) !important;background:var(--panel-3) !important}
.p-listitem{transition:background .12s}
.p-listitem:hover{background:var(--panel-2) !important}
.p-bar{cursor:pointer;transition:filter .12s}
.p-bar:hover{filter:brightness(1.08)}
`;
function injectHoverStyle() {
  if (document.getElementById("p-hover-style")) return;
  const style = document.createElement("style");
  style.id = "p-hover-style";
  style.textContent = PANEL_HOVER_CSS;
  document.head.appendChild(style);
}

// 3그룹 · 11탭. 내부 id 는 기존 그대로 (딥링크 호환).
const GROUPS = [
  { label: "관찰", tabs: [["step", "스텝 상세"], ["soul", "영혼 성장"], ["revealed", "말과 행동"], ["stats", "통계"]] },
  { label: "기록", tabs: [["wiki", "위키"], ["report", "일일 리포트"], ["skills", "스킬"], ["journal", "저널"]] },
  { label: "소통", tabs: [["chat", "대화"], ["inbox", "선물"], ["outbox", "요청"]] },
];
const ALL_TAB_IDS = GROUPS.flatMap((g) => g.tabs.map((t) => t[0]));

function tabStyle(active) {
  const base = "display:inline-flex;align-items:center;gap:6px;padding:5px 11px;border-radius:999px;font-size:var(--fs-sm);";
  return active
    ? base + "background:var(--ink);color:var(--bg);border:1px solid var(--ink);font-weight:600"
    : base + "background:var(--panel);color:var(--ink-soft);border:1px solid var(--line-soft);font-weight:400";
}

export function initPanels({ root, api, onChatStateChange }) {
  injectHoverStyle();
  root.innerHTML = "";
  const tabBar = el("nav", { style: NAV_STYLE });
  const contentHost = el("div", { style: "flex:1;overflow-y:auto;padding:var(--sp-5);min-height:0;scrollbar-gutter:stable" });
  root.appendChild(tabBar);
  root.appendChild(contentHost);

  const sections = {};
  const buttons = {};
  const loaders = {};
  let activeId = null;
  let openStepDetail = null;
  // Hoisted so the 영혼 성장 tab's [[wiki]] links can jump into the 위키 tab
  // (assigned inside the wiki block, like openStepDetail from the step block).
  let openWikiPage = null;
  let outboxBadge = null;
  let lastOutboxCount = 0;

  // -- 탭 바 (그룹 라벨 + 알약 버튼) --
  GROUPS.forEach((g) => {
    const groupEl = el("div", { style: "display:flex;align-items:center;gap:6px;flex-wrap:wrap" });
    groupEl.appendChild(
      el("span", { style: "font-family:var(--mono);font-size:10px;letter-spacing:.14em;color:var(--ink-faint);margin-right:2px", text: g.label })
    );
    g.tabs.forEach(([id, label]) => {
      const btn = el("button", { class: "p-tab", style: tabStyle(false), onclick: () => activate(id) });
      btn.appendChild(document.createTextNode(label));
      if (id === "outbox") {
        outboxBadge = el("span", { style: BADGE_STYLE });
        outboxBadge.style.display = "none";
        btn.appendChild(outboxBadge);
      }
      buttons[id] = btn;
      groupEl.appendChild(btn);
      const sec = el("div", {});
      sec.style.display = "none";
      sections[id] = sec;
      contentHost.appendChild(sec);
    });
    tabBar.appendChild(groupEl);
  });
  tabBar.appendChild(el("div", { style: "flex:1" }));

  // -- ⟳ 새로고침: 활성 탭 로더 재실행 + 클릭마다 360° 회전 --
  let spinCount = 0;
  const refreshGlyph = el("span", { style: "display:inline-block;transition:transform .5s", text: "⟳" });
  const refreshBtn = el("button", {
    class: "p-ghostbtn",
    style: "display:inline-flex;align-items:center;gap:6px;padding:5px 12px;border-radius:999px;border:1px solid var(--line);background:var(--panel);color:var(--ink-soft);font-size:var(--fs-sm)",
    title: "이 탭 새로고침",
    onclick: () => refreshActive(),
  });
  refreshBtn.appendChild(refreshGlyph);
  refreshBtn.appendChild(document.createTextNode(" 새로고침"));
  tabBar.appendChild(refreshBtn);

  function refreshActive() {
    spinCount++;
    refreshGlyph.style.transform = `rotate(${spinCount * 360}deg)`;
    const loader = loaders[activeId];
    if (loader && loader.load) {
      loader._loaded = true;
      loader.load();
    }
  }

  function activate(id) {
    if (activeId === id) return;
    activeId = id;
    Object.entries(sections).forEach(([k, node]) => (node.style.display = k === id ? "" : "none"));
    Object.entries(buttons).forEach(([k, btn]) => (btn.style.cssText = tabStyle(k === id)));
    // Deep-linkable tabs: #wiki, #stats, ... survive a reload / can be shared.
    try {
      history.replaceState(null, "", "#" + id);
    } catch (_e) {
      /* ignore (e.g. sandboxed iframe) */
    }
    const loader = loaders[id];
    if (loader && !loader._loaded) {
      loader._loaded = true;
      loader.load();
    }
  }

  // ---------------------------------------------------------------
  // 스텝 상세 + LLM 트랜스크립트
  // ---------------------------------------------------------------
  let currentStepId = null;
  {
    const sec = sections.step;
    const wrap = el("div", { style: "display:flex;flex-direction:column;gap:var(--sp-4);max-width:720px" });

    const header = el("div", { style: "display:flex;align-items:baseline;gap:10px;flex-wrap:wrap" });
    const metrics = el("div", { style: "display:flex;gap:var(--sp-3);flex-wrap:wrap" });

    const subTabs = el("div", { style: "display:flex;gap:2px;border-bottom:1px solid var(--line-soft)" });
    const outBtn = el("button", { text: "산출물" });
    const trBtn = el("button", { text: "LLM 트랜스크립트" });
    function styleSub(btn, active) {
      btn.style.cssText =
        "padding:7px 14px;border:none;background:none;font-size:var(--fs-sm);font-weight:600;cursor:pointer;" +
        (active ? "color:var(--ink);border-bottom:2px solid var(--ink)" : "color:var(--ink-faint);border-bottom:2px solid transparent");
    }
    styleSub(outBtn, true);
    styleSub(trBtn, false);
    subTabs.appendChild(outBtn);
    subTabs.appendChild(trBtn);

    // 산출물 본문: 마크다운을 DOM으로 렌더한다 (로딩/에러 메시지는 textContent 로).
    const contentBody = el("div", {});
    const transcriptBody = el("div", { style: "display:flex;flex-direction:column;gap:12px" });
    transcriptBody.style.display = "none";

    const errorHost = el("div", {});
    header.appendChild(emptyNote("말풍선이나 저널 항목을 클릭하면 여기에 상세가 표시됩니다."));
    wrap.appendChild(header);
    wrap.appendChild(metrics);
    wrap.appendChild(errorHost);
    wrap.appendChild(subTabs);
    wrap.appendChild(contentBody);
    wrap.appendChild(transcriptBody);
    sec.appendChild(wrap);

    outBtn.addEventListener("click", () => {
      styleSub(outBtn, true);
      styleSub(trBtn, false);
      contentBody.style.display = "";
      transcriptBody.style.display = "none";
    });
    trBtn.addEventListener("click", async () => {
      styleSub(trBtn, true);
      styleSub(outBtn, false);
      contentBody.style.display = "none";
      transcriptBody.style.display = "";
      if (!currentStepId) return;
      transcriptBody.innerHTML = "";
      transcriptBody.appendChild(emptyNote("불러오는 중…"));
      try {
        const t = await api.getStepTranscript(currentStepId);
        const entries = (t && t.entries) || [];
        transcriptBody.innerHTML = "";
        if (!entries.length) {
          transcriptBody.appendChild(emptyNote("이 스텝에는 보존된 LLM 트랜스크립트가 없습니다."));
          return;
        }
        // 실제 API 는 LLM 왕복(round-trip)마다 항목 하나를 준다:
        // {ts, backend, messages:[{role,content}...], response, normalized, error}.
        // 항목별로 "LLM 호출 i/total" 헤더 아래에 요청 messages[] + 응답(assistant)
        // 을 그룹으로 렌더한다. 예전 목업의 평면 {role, content} 항목도 방어적으로 처리.
        const msgRow = (role, text) =>
          el("div", { style: "display:flex;gap:10px;align-items:flex-start" }, [
            el("span", {
              style: "font-family:var(--mono);font-size:10px;letter-spacing:.08em;color:var(--ink-faint);background:var(--panel-2);border:1px solid var(--line-soft);border-radius:4px;padding:2px 7px;flex-shrink:0;margin-top:2px;min-width:64px;text-align:center",
              text: role || "?",
            }),
            el("div", {
              style: "font-size:var(--fs-sm);color:var(--ink-soft);white-space:pre-wrap;word-break:break-word",
              text: typeof text === "string" ? text : JSON.stringify(text, null, 2),
            }),
          ]);
        const total = entries.length;
        entries.forEach((e, i) => {
          // 방어: 평면 {role, content} 항목은 단일 행으로.
          if (!Array.isArray(e.messages)) {
            transcriptBody.appendChild(msgRow(e.role, typeof e.content === "string" ? e.content : e));
            return;
          }
          const group = el("div", { style: "display:flex;flex-direction:column;gap:10px" });
          const hdr = el("div", { style: "display:flex;align-items:center;gap:10px" });
          hdr.appendChild(el("span", { style: "font-family:var(--mono);font-size:10px;letter-spacing:.12em;color:var(--ink-faint)", text: `LLM 호출 ${i + 1}/${total}` }));
          if (e.backend) hdr.appendChild(el("span", { style: "font-size:var(--fs-xs);color:var(--ink-faint)", text: e.backend }));
          hdr.appendChild(el("div", { style: "flex:1;height:1px;background:var(--line-soft)" }));
          const tm = fmtHms(e.ts);
          if (tm) hdr.appendChild(el("span", { style: "font-family:var(--mono);font-size:10px;color:var(--ink-faint)", text: tm }));
          group.appendChild(hdr);
          // 요청 messages[].
          const msgs = e.messages || [];
          msgs.forEach((m) => group.appendChild(msgRow(m.role, m.content)));
          // 모델의 응답: normalized.content (LLMResponse.as_dict). messages[] 가
          // 이미 assistant 로 끝나지 않을 때만 마지막 assistant 행으로 덧붙인다.
          const reply = e.normalized && typeof e.normalized.content === "string" ? e.normalized.content : "";
          const lastRole = msgs.length ? msgs[msgs.length - 1].role : null;
          if (reply && lastRole !== "assistant") group.appendChild(msgRow("assistant", reply));
          // 에러로 끝난 호출은 경고색 행으로.
          if (e.error) {
            group.appendChild(
              el("div", { style: "display:flex;gap:10px;align-items:flex-start" }, [
                el("span", { style: "font-size:10px;padding:2px 7px;border-radius:4px;background:var(--warn-soft);color:var(--warn);flex-shrink:0;margin-top:2px;min-width:64px;text-align:center", text: "error" }),
                el("div", { style: "font-size:var(--fs-sm);color:var(--warn);white-space:pre-wrap;word-break:break-word", text: String(e.error) }),
              ])
            );
          }
          transcriptBody.appendChild(group);
        });
      } catch (e) {
        transcriptBody.innerHTML = "";
        transcriptBody.appendChild(emptyNote("트랜스크립트를 불러오지 못했습니다: " + e.message));
      }
    });

    function renderInterestCard(n) {
      const dots = el("div", { style: "display:flex;gap:3px" });
      const v = Number(n);
      const filled = Number.isFinite(v) ? Math.max(0, Math.min(10, Math.round(v))) : 0;
      for (let i = 0; i < 10; i++) {
        dots.appendChild(el("span", { style: `width:9px;height:9px;border-radius:50%;background:var(${i < filled ? "--accent" : "--panel-3"})` }));
      }
      return el("div", { style: "background:var(--panel-2);border:1px solid var(--line-soft);border-radius:var(--radius-sm);padding:10px 14px;display:flex;flex-direction:column;gap:5px;min-width:150px" }, [
        el("span", { style: "font-size:var(--fs-xs);color:var(--ink-faint)", text: "흥미도" }),
        el("div", { style: "display:flex;align-items:center;gap:8px" }, [dots, el("strong", { text: `${n != null ? n : "-"}/10` })]),
      ]);
    }
    function renderMoodCard(mood) {
      return el("div", { style: "background:var(--panel-2);border:1px solid var(--line-soft);border-radius:var(--radius-sm);padding:10px 14px;display:flex;flex-direction:column;gap:5px" }, [
        el("span", { style: "font-size:var(--fs-xs);color:var(--ink-faint)", text: "기분" }),
        el("span", { style: "display:inline-flex;align-items:center;gap:6px" }, [
          el("span", { style: `width:9px;height:9px;border-radius:50%;background:var(${moodToken(mood)})` }),
          el("strong", { text: moodLabelKo(mood) }),
        ]),
      ]);
    }
    function renderDecisionCard(rec) {
      const reason = rec.reason || rec.summary || "";
      return el("div", { style: "background:var(--panel-2);border:1px solid var(--line-soft);border-radius:var(--radius-sm);padding:10px 14px;display:flex;flex-direction:column;gap:5px;flex:1;min-width:220px" }, [
        el("span", { style: "font-size:var(--fs-xs);color:var(--ink-faint)", text: "결정" }),
        el("div", { style: "display:flex;align-items:center;gap:8px;flex-wrap:wrap" }, [
          decisionChip(rec.decision),
          reason ? el("span", { style: "font-size:var(--fs-sm);color:var(--ink-soft)", text: `"${reason}"` }) : null,
        ]),
      ]);
    }

    openStepDetail = async function (stepId) {
      currentStepId = stepId;
      // _loaded 를 켜 둔 채로 전환 → activate 가 로더를 재호출해 재귀하지 않게.
      loaders.step._loaded = true;
      activate("step");
      header.innerHTML = "";
      header.appendChild(el("span", { style: "font-family:var(--mono);font-size:var(--fs-xs);color:var(--ink-faint)", text: stepId }));
      metrics.innerHTML = "";
      errorHost.innerHTML = "";
      styleSub(outBtn, true);
      styleSub(trBtn, false);
      contentBody.style.display = "";
      transcriptBody.style.display = "none";
      contentBody.textContent = "불러오는 중…";
      try {
        const detail = await api.getStep(stepId);
        const rec = (detail && detail.record) || {};
        header.innerHTML = "";
        header.appendChild(el("h2", { style: "margin:0;font-size:var(--fs-xl);letter-spacing:-.01em", text: actionLabelKo(rec.action) }));
        header.appendChild(el("span", { style: "font-family:var(--mono);font-size:var(--fs-xs);color:var(--ink-faint)", text: `${stepId} · ${fmtShort(rec.ts)}` }));
        metrics.innerHTML = "";
        metrics.appendChild(renderInterestCard(rec.interest));
        metrics.appendChild(renderMoodCard(rec.mood));
        metrics.appendChild(renderDecisionCard(rec));
        if (rec.error) {
          const err = rec.error;
          const msg = typeof err === "object" ? `${err.phase || "?"} — ${err.message || "?"}` : String(err);
          errorHost.appendChild(
            el("div", { style: "font-size:var(--fs-sm);color:var(--warn);background:var(--warn-soft);border-radius:var(--radius-sm);padding:8px 12px", text: "이 스텝은 에러로 끝났습니다: " + msg })
          );
        }
        contentBody.innerHTML = "";
        contentBody.appendChild(renderMarkdownWithToggle((detail && detail.content) || "(산출물 내용 없음)"));
      } catch (e) {
        contentBody.textContent = "스텝 상세를 불러오지 못했습니다: " + e.message;
      }
    };

    loaders.step = {
      _loaded: true,
      load() {
        if (currentStepId) openStepDetail(currentStepId);
      },
    };
  }

  // ---------------------------------------------------------------
  // 영혼 성장 — SOUL.md + 변경 히스토리 diff
  // ---------------------------------------------------------------
  {
    const sec = sections.soul;
    let openCommit = null;

    const leftArticle = el("article", { style: "display:flex;flex-direction:column;gap:12px" });
    leftArticle.appendChild(
      el("div", { style: "display:flex;align-items:baseline;gap:10px" }, [
        el("h2", { style: "margin:0;font-size:var(--fs-xl)", text: "SOUL.md" }),
        el("span", { style: "font-family:var(--mono);font-size:var(--fs-xs);color:var(--ink-faint)", text: "에이전트가 스스로 쓰는 자기 서사" }),
      ])
    );
    const soulBody = el("div", { style: "display:flex;flex-direction:column;gap:12px" });
    leftArticle.appendChild(soulBody);

    const aside = el("aside", { style: "display:flex;flex-direction:column;gap:8px" });
    aside.appendChild(el("h3", { style: "margin:0;font-size:var(--fs-sm);color:var(--ink-faint);font-weight:600", text: "변경 히스토리" }));
    const historyList = el("div", { style: "display:flex;flex-direction:column;gap:8px" });
    aside.appendChild(historyList);

    sec.appendChild(el("div", { style: "display:grid;grid-template-columns:minmax(0,1.5fr) minmax(240px,1fr);gap:var(--sp-5)" }, [leftArticle, aside]));

    function renderSoulProse(content) {
      soulBody.innerHTML = "";
      const text = (content || "").trim();
      if (!text) {
        soulBody.appendChild(emptyNote("(아직 SOUL.md 내용이 없습니다)"));
        return;
      }
      soulBody.appendChild(
        renderMarkdownWithToggle(content, {
          onWikiLink: (slug) => { activate("wiki"); openWikiPage(slug); },
        })
      );
    }

    function commitBtnStyle(open) {
      return `width:100%;text-align:left;background:${open ? "var(--accent-soft)" : "var(--panel-2)"};border:1px solid var(--line-soft);border-radius:var(--radius-sm);padding:9px 12px;font-size:var(--fs-sm);color:var(--ink);cursor:pointer`;
    }
    function renderDiff(pre, diffText) {
      pre.innerHTML = "";
      const lines = String(diffText || "").split("\n");
      lines.forEach((ln, i) => {
        let color = "var(--ink-soft)";
        if (ln.startsWith("@@")) color = "var(--ink-faint)";
        else if (ln.startsWith("+")) color = "var(--d-new)";
        else if (ln.startsWith("-")) color = "var(--d-abandon)";
        pre.appendChild(el("span", { style: `color:${color}`, text: ln }));
        if (i < lines.length - 1) pre.appendChild(document.createTextNode("\n"));
      });
    }
    function buildCommit(c) {
      const wrap = el("div", {});
      const hash = String(c.commit || "").slice(0, 7);
      const btn = el("button", { class: "p-listitem", style: commitBtnStyle(false) });
      btn.appendChild(el("span", { style: "font-family:var(--mono);font-size:10px;color:var(--ink-faint)", text: `${hash} · ${fmtMonthDay(c.ts)}` }));
      btn.appendChild(el("br"));
      btn.appendChild(document.createTextNode(c.message || "(메시지 없음)"));
      const diffPre = el("pre", { style: DIFF_PRE });
      diffPre.style.display = "none";
      let loaded = false;
      wrap._close = () => {
        diffPre.style.display = "none";
        btn.style.cssText = commitBtnStyle(false);
      };
      btn.addEventListener("click", async () => {
        const isOpen = diffPre.style.display !== "none";
        if (isOpen) {
          wrap._close();
          if (openCommit === wrap) openCommit = null;
          return;
        }
        if (openCommit && openCommit !== wrap) openCommit._close();
        openCommit = wrap;
        btn.style.cssText = commitBtnStyle(true);
        diffPre.style.display = "";
        if (!loaded) {
          diffPre.textContent = "불러오는 중…";
          try {
            const d = await api.getSoulDiff(c.commit);
            renderDiff(diffPre, (d && d.diff) || "(diff 없음)");
            loaded = true;
          } catch (e) {
            diffPre.textContent = "diff를 불러오지 못했습니다: " + e.message;
          }
        }
      });
      wrap.appendChild(btn);
      wrap.appendChild(diffPre);
      return wrap;
    }

    loaders.soul = {
      async load() {
        soulBody.innerHTML = "";
        soulBody.appendChild(emptyNote("불러오는 중…"));
        try {
          const soul = await api.getSoul();
          renderSoulProse(soul && soul.content);
        } catch (e) {
          soulBody.innerHTML = "";
          soulBody.appendChild(emptyNote("SOUL.md를 불러오지 못했습니다: " + e.message));
        }
        historyList.innerHTML = "";
        openCommit = null;
        try {
          const hist = await api.getSoulHistory();
          const commits = (hist && hist.commits) || [];
          if (!commits.length) {
            historyList.appendChild(emptyNote("아직 커밋된 변경 이력이 없습니다."));
          }
          commits.forEach((c) => historyList.appendChild(buildCommit(c)));
        } catch (e) {
          historyList.innerHTML = "";
          historyList.appendChild(emptyNote("히스토리를 불러오지 못했습니다: " + e.message));
        }
      },
    };
  }

  // ---------------------------------------------------------------
  // 말과 행동 (stated vs revealed)
  // ---------------------------------------------------------------
  {
    const sec = sections.revealed;
    const wrap = el("div", { style: "display:flex;flex-direction:column;gap:var(--sp-4);max-width:720px" });
    wrap.appendChild(
      el("div", {}, [
        el("h2", { style: "margin:0 0 4px;font-size:var(--fs-xl)", text: "말과 행동" }),
        el("p", { style: "margin:0;font-size:var(--fs-sm);color:var(--ink-soft)", text: "말로 밝힌 관심(stated)과 실제 행동에서 드러난 관심(revealed)의 비교입니다. 차이 자체가 관찰 대상이며, 좋고 나쁨은 없습니다." }),
      ])
    );
    const noteHost = el("div", {});
    const rowsHost = el("div", { style: "display:flex;flex-direction:column;gap:var(--sp-3)" });
    wrap.appendChild(noteHost);
    wrap.appendChild(rowsHost);
    sec.appendChild(wrap);

    // API(revealed_interest)는 said/did % 대신 top_threads(지속 steps/평균 흥미)를
    // 준다 → 같은 카드+바 언어로 표시하되 값은 실제 수치 그대로 (허위 퍼센트 없음).
    function miniBar(label, value, max, tokenVar, displayText) {
      const w = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
      return [
        el("span", { text: label }),
        el("div", { style: "height:8px;border-radius:4px;background:var(--panel-3);overflow:hidden" }, [
          el("div", { style: `height:100%;width:${w}%;background:var(${tokenVar})` }),
        ]),
        el("span", { style: "font-family:var(--mono)", text: displayText != null ? displayText : String(value != null ? value : "-") }),
      ];
    }

    loaders.revealed = {
      async load() {
        noteHost.innerHTML = "";
        rowsHost.innerHTML = "";
        rowsHost.appendChild(emptyNote("불러오는 중…"));
        try {
          const rv = await api.getRevealed();
          noteHost.innerHTML = "";
          rowsHost.innerHTML = "";
          if (rv && rv.stated_vs_revealed_note) {
            noteHost.appendChild(el("p", { style: "margin:0;font-size:var(--fs-sm);color:var(--ink-soft)", text: rv.stated_vs_revealed_note }));
          }
          const threads = (rv && rv.top_threads) || [];
          if (!threads.length) {
            rowsHost.appendChild(emptyNote("아직 축적된 데이터가 없습니다."));
            return;
          }
          // 재방문(셀브 후 복귀) 횟수는 top-level shelve_returns 에 topic 키로 들어있다
          // → 스레드의 topic 으로 직접 조회 (없으면 0, 데이터를 지어내지 않는다).
          const shelveReturns = (rv && rv.shelve_returns) || {};
          const maxSteps = Math.max(1, ...threads.map((t) => t.steps || 0));
          threads.forEach((t) => {
            const steps = t.steps || 0;
            const avg = t.avg_interest; // 0–10, revealed_interest 가 소수 2자리로 반올림
            const revisits = t.topic && shelveReturns[t.topic] != null ? shelveReturns[t.topic] : 0;
            rowsHost.appendChild(
              el("div", { style: "background:var(--panel-2);border:1px solid var(--line-soft);border-radius:var(--radius-sm);padding:12px 14px;display:flex;flex-direction:column;gap:8px" }, [
                el("div", { style: "display:flex;align-items:baseline;gap:8px;flex-wrap:wrap" }, [
                  el("strong", { style: "font-size:var(--fs-md)", text: t.topic || "(주제 없음)" }),
                  el("span", { style: "font-size:var(--fs-xs);color:var(--ink-faint)", text: `재방문 ${revisits}회 · 지속 ${steps}스텝` }),
                ]),
                el("div", { style: "display:grid;grid-template-columns:64px 1fr 56px;gap:6px;align-items:center;font-size:var(--fs-xs);color:var(--ink-faint)" }, [
                  ...miniBar("지속", steps, maxSteps, "--accent", `${steps}스텝`),
                  ...miniBar("평균 흥미", avg != null ? avg : 0, 10, "--m-curious", avg != null ? `${avg}/10` : "-/10"),
                ]),
              ])
            );
          });
        } catch (e) {
          noteHost.innerHTML = "";
          rowsHost.innerHTML = "";
          rowsHost.appendChild(emptyNote("불러오지 못했습니다: " + e.message));
        }
      },
    };
  }

  // ---------------------------------------------------------------
  // 통계 — 타일 · 타임라인 · 결정/행동/흥미 분포 · 주제 스레드 · 에러
  // ---------------------------------------------------------------
  {
    const sec = sections.stats;
    const body = el("div", { style: "display:flex;flex-direction:column;gap:var(--sp-5)" });
    sec.appendChild(body);

    function tile(label, value) {
      return el("div", { style: "background:var(--panel-2);border:1px solid var(--line-soft);border-radius:var(--radius-sm);padding:12px 14px" }, [
        el("div", { style: "font-size:var(--fs-xs);color:var(--ink-faint)", text: label }),
        el("div", { style: "font-size:24px;font-weight:700;letter-spacing:-.02em;font-family:var(--mono)", text: value }),
      ]);
    }

    async function render() {
      body.innerHTML = "";
      body.appendChild(emptyNote("불러오는 중…"));
      let s;
      try {
        s = await api.getStats();
      } catch (e) {
        body.innerHTML = "";
        body.appendChild(emptyNote("통계를 불러오지 못했습니다: " + e.message));
        return;
      }
      body.innerHTML = "";
      if (!s || !s.total_steps) {
        body.appendChild(emptyNote("아직 기록된 스텝이 없습니다."));
        return;
      }

      // -- 요약 타일 (모두 실제 데이터에서 파생) --
      const hist = s.interest_hist || {};
      let histSum = 0, histN = 0;
      Object.entries(hist).forEach(([k, v]) => { histSum += Number(k) * v; histN += v; });
      const avgInterest = histN ? (histSum / histN).toFixed(1) : "-";
      const timeline = s.timeline || [];
      const activeDays = new Set(timeline.map((t) => String(t.ts || "").slice(0, 10)).filter(Boolean)).size;
      const tiles = el("div", { style: "display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:var(--sp-3)" }, [
        tile("총 스텝", String(s.total_steps)),
        tile("활동 일수", `${activeDays}일`),
        tile("평균 흥미도", String(avgInterest)),
        tile("주제 스레드", String((s.threads || []).length)),
        tile("오류", String((s.errors && s.errors.count) || 0)),
        tile("열린 요청", String(lastOutboxCount)),
      ]);
      body.appendChild(tiles);

      // -- 스텝 타임라인: 높이=흥미, 색=기분 --
      const tlSection = el("section", {});
      tlSection.appendChild(el("h3", { style: STAT_H3, text: "스텝 타임라인 — 높이는 흥미도, 색은 기분" }));
      const strip = el("div", { style: "display:flex;align-items:flex-end;gap:2px;height:72px;background:var(--panel-2);border:1px solid var(--line-soft);border-radius:var(--radius-sm);padding:8px;overflow-x:auto" });
      timeline.forEach((t) => {
        const interest = t.interest;
        const bar = el("div", {
          class: "p-bar",
          style: `flex:1;height:${interest ? Math.max(6, interest * 10) : 4}%;background:var(${interest ? moodToken(t.mood) : "--panel-3"});border-radius:2px 2px 0 0;min-width:3px`,
          title: `${t.id} · 흥미 ${interest != null ? interest : "-"} · ${moodLabelKo(t.mood)}`,
        });
        if (t.id) bar.addEventListener("click", () => openStepDetail(t.id));
        strip.appendChild(bar);
      });
      tlSection.appendChild(strip);
      const legend = el("div", { style: "display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;font-size:var(--fs-xs);color:var(--ink-soft)" });
      MOOD_KEYS.forEach((m) => {
        legend.appendChild(
          el("span", { style: "display:inline-flex;align-items:center;gap:5px" }, [
            el("span", { style: `width:8px;height:8px;border-radius:2px;background:var(${moodToken(m)})` }),
            moodLabelKo(m),
          ])
        );
      });
      tlSection.appendChild(legend);
      body.appendChild(tlSection);
      strip.scrollLeft = strip.scrollWidth; // 최신 스텝이 보이게 오른쪽 끝

      const grid = el("div", { style: "display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:var(--sp-5)" });

      // -- 결정 분포 (고정 순서, 폭=최댓값 대비) --
      const dSection = el("section", {});
      dSection.appendChild(el("h3", { style: STAT_H3, text: `결정 분포 — ${s.decision_total || s.total_steps} 스텝` }));
      const dWrap = el("div", { style: "display:flex;flex-direction:column;gap:8px" });
      const dMax = Math.max(1, ...DECISION_ORDER.map((d) => (s.decisions && s.decisions[d]) || 0));
      DECISION_ORDER.forEach((d) => {
        const n = (s.decisions && s.decisions[d]) || 0;
        dWrap.appendChild(
          el("div", { style: "display:grid;grid-template-columns:110px 1fr 44px;gap:8px;align-items:center;font-size:var(--fs-sm)" }, [
            el("span", { text: DECISION_LABEL[d] }),
            el("div", { style: "height:14px;border-radius:4px;background:var(--panel-2);overflow:hidden" }, [
              el("div", { style: `height:100%;width:${Math.round((n / dMax) * 100)}%;background:var(${DECISION_TOKEN[d]})` }),
            ]),
            el("span", { style: "font-family:var(--mono);font-size:var(--fs-xs);color:var(--ink-soft);text-align:right", text: String(n) }),
          ])
        );
      });
      dSection.appendChild(dWrap);
      grid.appendChild(dSection);

      // -- 행동 분포 --
      const aSection = el("section", {});
      aSection.appendChild(el("h3", { style: STAT_H3, text: "행동 분포" }));
      const aWrap = el("div", { style: "display:flex;flex-direction:column;gap:8px" });
      const actions = Object.entries(s.actions || {}).sort((a, b) => b[1] - a[1]);
      const aMax = Math.max(1, ...actions.map(([, n]) => n));
      actions.forEach(([a, n]) => {
        aWrap.appendChild(
          el("div", { style: "display:grid;grid-template-columns:110px 1fr 44px;gap:8px;align-items:center;font-size:var(--fs-sm)" }, [
            el("span", { text: actionLabelKo(a) }),
            el("div", { style: "height:14px;border-radius:4px;background:var(--panel-2);overflow:hidden" }, [
              el("div", { style: `height:100%;width:${Math.round((n / aMax) * 100)}%;background:var(--accent);opacity:.75` }),
            ]),
            el("span", { style: "font-family:var(--mono);font-size:var(--fs-xs);color:var(--ink-soft);text-align:right", text: `${n} · ${pct(n, s.total_steps)}` }),
          ])
        );
      });
      if (!actions.length) aWrap.appendChild(emptyNote("행동 기록이 없습니다."));
      aSection.appendChild(aWrap);
      grid.appendChild(aSection);

      // -- 흥미도 히스토그램 (1–10) --
      const hSection = el("section", {});
      hSection.appendChild(el("h3", { style: STAT_H3, text: "흥미도 히스토그램 (1–10, 자기평가)" }));
      const histHost = el("div", { style: "display:flex;align-items:flex-end;gap:5px;height:110px" });
      const histMax = Math.max(1, ...Object.values(hist));
      for (let i = 1; i <= 10; i++) {
        const n = hist[String(i)] || 0;
        histHost.appendChild(
          el("div", { style: "flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;height:100%;justify-content:flex-end" }, [
            el("span", { style: "font-size:10px;font-family:var(--mono);color:var(--ink-faint)", text: n ? String(n) : "" }),
            el("div", { style: `width:100%;height:${n ? Math.max(3, Math.round((n / histMax) * 70)) : 0}px;background:var(--accent);opacity:.8;border-radius:3px 3px 0 0` }),
            el("span", { style: "font-size:10px;font-family:var(--mono);color:var(--ink-faint)", text: String(i) }),
          ])
        );
      }
      hSection.appendChild(histHost);
      grid.appendChild(hSection);

      // -- 주제 스레드 (최신 우선). API 가 상태를 주지 않으므로 상태 칩은 생략. --
      const tSection = el("section", {});
      tSection.appendChild(el("h3", { style: STAT_H3, text: "주제 스레드" }));
      const threads = (s.threads || []).slice(-30).reverse();
      const tWrap = el("div", { style: "display:flex;flex-direction:column;gap:6px" });
      threads.forEach((t) => {
        tWrap.appendChild(
          el("div", { style: "display:flex;align-items:baseline;gap:8px;font-size:var(--fs-sm);padding:7px 10px;background:var(--panel-2);border:1px solid var(--line-soft);border-radius:var(--radius-sm)" }, [
            el("strong", { style: "flex:1;min-width:0", text: t.topic || "(주제 없음)" }),
            el("span", { style: "font-family:var(--mono);font-size:var(--fs-xs);color:var(--ink-soft)", text: `${t.steps}스텝 · 평균 ${t.avg_interest != null ? t.avg_interest : "-"}` }),
          ])
        );
      });
      if (!threads.length) tWrap.appendChild(emptyNote("아직 스레드가 없습니다."));
      tSection.appendChild(tWrap);

      // -- 오류 블록 (최근, 클릭 → 스텝 상세) --
      const errs = ((s.errors && s.errors.recent) || []).slice().reverse();
      const errBlock = el("div", { style: "margin-top:14px;font-size:var(--fs-sm);color:var(--ink-soft)" });
      errBlock.appendChild(el("strong", { style: "color:var(--ink)", text: `오류 ${(s.errors && s.errors.count) || 0}건` }));
      if (!errs.length) {
        errBlock.appendChild(document.createTextNode(" — 기록된 에러가 없습니다."));
      } else {
        errBlock.appendChild(document.createTextNode(" — 최근:"));
        const errHost = el("div", { style: "font-family:var(--mono);font-size:var(--fs-xs);margin-top:6px;display:flex;flex-direction:column;gap:4px" });
        errs.forEach((e2) => {
          const attrs = { style: "cursor:" + (e2.id ? "pointer" : "default"), text: `${fmtShort(e2.ts)} · ${e2.phase || "-"}: ${e2.message || "(메시지 없음)"}` };
          if (e2.id) attrs.class = "p-listitem";
          const line = el("span", attrs);
          if (e2.id) line.addEventListener("click", () => openStepDetail(e2.id));
          errHost.appendChild(line);
        });
        errBlock.appendChild(errHost);
      }
      tSection.appendChild(errBlock);
      grid.appendChild(tSection);

      body.appendChild(grid);
    }

    loaders.stats = { load: render };
  }

  // ---------------------------------------------------------------
  // 위키 — 검색 + 페이지 목록 + 페이지 뷰 + 백링크 + 그래프
  // ---------------------------------------------------------------
  {
    const sec = sections.wiki;
    let currentSlug = null;
    const listItems = [];

    const searchInput = el("input", { type: "text", placeholder: "위키 검색…", style: "font-family:inherit;font-size:var(--fs-sm);padding:8px 12px;border-radius:var(--radius-sm);border:1px solid var(--line);background:var(--panel-2);color:var(--ink)" });
    const pageList = el("div", { style: "display:flex;flex-direction:column;gap:2px;font-size:var(--fs-sm)" });
    const graphToggle = el("button", { class: "p-ghostbtn", text: "◉ 링크 그래프 보기", style: "padding:7px 12px;border-radius:var(--radius-sm);border:1px dashed var(--line);background:none;color:var(--ink-soft);font-size:var(--fs-sm)" });
    const graphCanvas = el("canvas", { width: "560", height: "360", style: "border:1px solid var(--line-soft);border-radius:var(--radius-sm);background:var(--panel-2);max-width:100%" });
    graphCanvas.style.display = "none";

    const aside = el("aside", { style: "display:flex;flex-direction:column;gap:10px" }, [searchInput, pageList, graphToggle, graphCanvas]);
    const article = el("article", { style: "display:flex;flex-direction:column;gap:12px" });
    article.appendChild(emptyNote("왼쪽에서 페이지를 선택하세요."));

    sec.appendChild(el("div", { style: "display:grid;grid-template-columns:210px minmax(0,1fr);gap:var(--sp-5)" }, [aside, article]));

    function highlightActive() {
      listItems.forEach(({ slug, node }) => {
        const on = slug === currentSlug;
        node.style.background = on ? "var(--accent-soft)" : "transparent";
        node.style.color = on ? "var(--accent-ink)" : "var(--ink-soft)";
      });
    }

    async function doSearch(q) {
      pageList.innerHTML = "";
      listItems.length = 0;
      pageList.appendChild(emptyNote("검색 중…"));
      try {
        const res = q ? await api.searchWiki(q) : await api.getWikiPages();
        pageList.innerHTML = "";
        const items = (res && (res.results || res.pages)) || [];
        if (!items.length) {
          pageList.appendChild(emptyNote("결과가 없습니다."));
          return;
        }
        items.forEach((it) => {
          const slug = it.slug;
          const node = el("span", { class: "p-listitem", style: "padding:6px 10px;border-radius:var(--radius-sm);background:transparent;color:var(--ink-soft);cursor:pointer", text: it.title || it.slug });
          node.addEventListener("click", () => openWikiPage(slug));
          listItems.push({ slug, node });
          pageList.appendChild(node);
        });
        highlightActive();
      } catch (e) {
        pageList.innerHTML = "";
        pageList.appendChild(emptyNote("위키를 불러오지 못했습니다: " + e.message));
      }
    }

    openWikiPage = async function (slug) {
      currentSlug = slug;
      highlightActive();
      article.innerHTML = "";
      article.appendChild(emptyNote("불러오는 중…"));
      try {
        const pg = await api.getWikiPage(slug);
        article.innerHTML = "";
        article.appendChild(el("h2", { style: "margin:0;font-size:var(--fs-xl)", text: pg.title || pg.slug }));
        article.appendChild(renderMarkdownWithToggle(pg.content || "", { onWikiLink: openWikiPage }));
        const backlinks = pg.backlinks || [];
        if (backlinks.length) {
          const row = el("div", { style: "display:flex;gap:6px;flex-wrap:wrap;font-size:var(--fs-xs);align-items:center" });
          row.appendChild(el("span", { style: "color:var(--ink-faint)", text: "백링크:" }));
          backlinks.forEach((b) => {
            const chip = el("span", { class: "p-listitem", style: "padding:2px 9px;border-radius:999px;background:var(--panel-2);border:1px solid var(--line-soft);color:var(--ink-soft);cursor:pointer", text: b });
            chip.addEventListener("click", () => openWikiPage(b));
            row.appendChild(chip);
          });
          article.appendChild(row);
        }
      } catch (e) {
        article.innerHTML = "";
        article.appendChild(emptyNote("페이지를 불러오지 못했습니다: " + e.message));
      }
    };

    searchInput.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") doSearch(searchInput.value.trim());
    });
    graphToggle.addEventListener("click", async () => {
      const showing = graphCanvas.style.display !== "none";
      graphCanvas.style.display = showing ? "none" : "block";
      if (showing) return;
      try {
        const graph = await api.getWikiGraph();
        drawWikiGraph(graphCanvas, graph, openWikiPage);
      } catch (e) {
        const ctx = graphCanvas.getContext("2d");
        ctx.clearRect(0, 0, graphCanvas.width, graphCanvas.height);
        ctx.fillStyle = "#888";
        ctx.fillText("그래프를 불러오지 못했습니다: " + e.message, 10, 20);
      }
    });

    loaders.wiki = { load: () => doSearch("") };
  }

  // ---------------------------------------------------------------
  // 일일 리포트
  // ---------------------------------------------------------------
  {
    const sec = sections.report;
    const dateItems = [];
    let currentDate = null;

    const aside = el("aside", { style: "display:flex;flex-direction:column;gap:2px;font-size:var(--fs-sm)" });
    const article = el("article", { style: "display:flex;flex-direction:column;gap:10px;max-width:600px" });
    article.appendChild(emptyNote("왼쪽에서 날짜를 선택하세요."));
    sec.appendChild(el("div", { style: "display:grid;grid-template-columns:150px minmax(0,1fr);gap:var(--sp-5)" }, [aside, article]));

    function highlightDate() {
      dateItems.forEach(({ date, node }) => {
        const on = date === currentDate;
        node.style.background = on ? "var(--accent-soft)" : "transparent";
        node.style.color = on ? "var(--accent-ink)" : "var(--ink-soft)";
        node.style.fontWeight = on ? "600" : "400";
      });
    }
    async function openReport(date) {
      currentDate = date;
      highlightDate();
      article.innerHTML = "";
      article.appendChild(emptyNote("불러오는 중…"));
      try {
        const rep = await api.getReport(date);
        article.innerHTML = "";
        article.appendChild(el("h2", { style: "margin:0;font-size:var(--fs-xl)", text: fmtReportDate(date) + "의 기록" }));
        article.appendChild(renderMarkdownWithToggle((rep && rep.content) || "(내용 없음)"));
      } catch (e) {
        article.innerHTML = "";
        article.appendChild(emptyNote("리포트를 불러오지 못했습니다: " + e.message));
      }
    }

    loaders.report = {
      async load() {
        aside.innerHTML = "";
        dateItems.length = 0;
        aside.appendChild(emptyNote("불러오는 중…"));
        try {
          const res = await api.getReports();
          const dates = ((res && res.dates) || []).slice().reverse();
          aside.innerHTML = "";
          if (!dates.length) {
            aside.appendChild(emptyNote("아직 작성된 일일 리포트가 없습니다."));
            return;
          }
          dates.forEach((d) => {
            const node = el("span", { class: "p-listitem", style: "padding:6px 10px;border-radius:var(--radius-sm);background:transparent;color:var(--ink-soft);cursor:pointer", text: fmtReportDate(d) });
            node.addEventListener("click", () => openReport(d));
            dateItems.push({ date: d, node });
            aside.appendChild(node);
          });
        } catch (e) {
          aside.innerHTML = "";
          aside.appendChild(emptyNote("리포트 목록을 불러오지 못했습니다: " + e.message));
        }
      },
    };
  }

  // ---------------------------------------------------------------
  // 스킬
  // ---------------------------------------------------------------
  {
    const sec = sections.skills;
    const listHost = el("div", { style: "display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:var(--sp-3)" });
    sec.appendChild(listHost);

    async function render() {
      listHost.innerHTML = "";
      listHost.appendChild(emptyNote("불러오는 중…"));
      let res;
      try {
        res = await api.getSkills();
      } catch (e) {
        listHost.innerHTML = "";
        listHost.appendChild(emptyNote("스킬 목록을 불러오지 못했습니다: " + e.message));
        return;
      }
      listHost.innerHTML = "";
      const skills = (res && res.skills) || [];
      const threshold = (res && res.auto_disable_after_failures) || 3;
      if (!skills.length) {
        listHost.appendChild(emptyNote("아직 만든 스킬이 없습니다."));
        return;
      }
      skills.forEach((m) => {
        const fails = m.failures || 0;
        const autoDisabled = !m.enabled && fails >= threshold;
        const failNote = autoDisabled ? " — 임계치 도달로 자동 비활성" : "";
        listHost.appendChild(
          el("div", { style: `background:var(--panel-2);border:1px solid var(--line-soft);border-radius:var(--radius);padding:14px;display:flex;flex-direction:column;gap:6px;opacity:${m.enabled ? 1 : 0.65}` }, [
            el("div", { style: "display:flex;align-items:baseline;gap:8px" }, [
              el("strong", { style: "font-family:var(--mono);font-size:var(--fs-sm)", text: m.name }),
              el("span", { style: "font-family:var(--mono);font-size:10px;color:var(--ink-faint)", text: `v${m.version != null ? m.version : "?"}` }),
              el("div", { style: "flex:1" }),
              el("span", {
                style: `font-size:10px;padding:1px 7px;border-radius:999px;background:var(${m.enabled ? "--accent-soft" : "--panel-3"});color:var(${m.enabled ? "--accent-ink" : "--ink-soft"})`,
                text: m.enabled ? "활성" : "비활성",
              }),
            ]),
            el("span", { style: "font-size:var(--fs-sm);color:var(--ink-soft)", text: m.description || "(설명 없음)" }),
            el("span", { style: `font-size:var(--fs-xs);color:var(${fails > 0 ? "--warn" : "--ink-faint"})`, text: `연속 실패 ${fails}회${failNote}` }),
          ])
        );
      });
    }

    loaders.skills = { load: render };
  }

  // ---------------------------------------------------------------
  // 저널 (원문) — 클라이언트 페이지네이션 (10/페이지, getSteps(500) 1회 fetch)
  // ---------------------------------------------------------------
  {
    const sec = sections.journal;
    const PER_PAGE = 10;
    let journalSteps = [];
    let journalPage = 1;

    const wrap = el("div", { style: "display:flex;flex-direction:column;gap:6px;max-width:680px" });
    wrap.appendChild(el("p", { style: "margin:0 0 8px;font-size:var(--fs-sm);color:var(--ink-soft)", text: "원시 스텝 레코드입니다. 행을 클릭하면 스텝 상세로 이동합니다." }));
    const rowsHost = el("div", { style: "display:flex;flex-direction:column;gap:6px" });
    const pager = el("div", { style: "display:flex;align-items:center;gap:8px;margin-top:10px;font-size:var(--fs-sm)" });
    wrap.appendChild(rowsHost);
    wrap.appendChild(pager);
    sec.appendChild(wrap);

    function renderPage() {
      rowsHost.innerHTML = "";
      pager.innerHTML = "";
      const total = journalSteps.length;
      const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
      if (journalPage > totalPages) journalPage = totalPages;
      if (!total) {
        rowsHost.appendChild(emptyNote("아직 기록된 스텝이 없습니다."));
        return;
      }
      const start = (journalPage - 1) * PER_PAGE;
      journalSteps.slice(start, start + PER_PAGE).forEach((s) => {
        const isError = s.kind === "error" || !!s.error;
        const row = el("button", {
          class: "p-row",
          style: "display:grid;grid-template-columns:88px 150px 1fr auto;gap:12px;align-items:center;text-align:left;padding:8px 12px;border-radius:var(--radius-sm);border:1px solid var(--line-soft);background:var(--panel-2);color:var(--ink);font-family:var(--mono);font-size:12.5px;cursor:pointer",
        }, [
          el("span", { style: "color:var(--ink-faint)", text: s.id }),
          el("span", { text: fmtShort(s.ts) }),
          el("span", { text: actionLabelKo(s.action) }),
          isError ? el("span", { style: "font-size:10px;padding:1px 7px;border-radius:999px;background:var(--warn-soft);color:var(--warn)", text: "error" }) : el("span", {}),
        ]);
        row.addEventListener("click", () => openStepDetail(s.id));
        rowsHost.appendChild(row);
      });

      const prevBtn = el("button", { class: "p-ghostbtn", style: `padding:5px 12px;border-radius:var(--radius-sm);border:1px solid var(--line);background:var(--panel-2);color:var(${journalPage > 1 ? "--ink" : "--ink-faint"})`, text: "‹ 이전" });
      const nextBtn = el("button", { class: "p-ghostbtn", style: `padding:5px 12px;border-radius:var(--radius-sm);border:1px solid var(--line);background:var(--panel-2);color:var(${journalPage < totalPages ? "--ink" : "--ink-faint"})`, text: "다음 ›" });
      prevBtn.addEventListener("click", () => {
        if (journalPage > 1) { journalPage--; renderPage(); }
      });
      nextBtn.addEventListener("click", () => {
        if (journalPage < totalPages) { journalPage++; renderPage(); }
      });
      pager.appendChild(prevBtn);
      pager.appendChild(el("span", { style: "color:var(--ink-soft);font-family:var(--mono);font-size:var(--fs-xs)", text: `${journalPage} / ${totalPages}` }));
      pager.appendChild(nextBtn);
      pager.appendChild(el("span", { style: "color:var(--ink-faint);font-size:var(--fs-xs)", text: `총 ${total} 레코드 · 페이지당 ${PER_PAGE}` }));
    }

    loaders.journal = {
      async load() {
        rowsHost.innerHTML = "";
        pager.innerHTML = "";
        rowsHost.appendChild(emptyNote("불러오는 중…"));
        try {
          const res = await api.getSteps(500);
          journalSteps = (res && res.steps) || [];
        } catch (e) {
          journalSteps = [];
          rowsHost.innerHTML = "";
          rowsHost.appendChild(emptyNote("저널을 불러오지 못했습니다: " + e.message));
          return;
        }
        journalPage = 1; // 새로고침은 항상 1페이지로
        renderPage();
      },
    };
  }

  // ---------------------------------------------------------------
  // 대화 (기록 토글 기본 OFF — "기억되지 않음"이 기본)
  // ---------------------------------------------------------------
  {
    const sec = sections.chat;
    let sessionId = null;
    let recordOn = false;

    const wrap = el("div", { style: "display:flex;flex-direction:column;gap:var(--sp-4);max-width:640px" });
    const header = el("div", { style: "display:flex;align-items:center;gap:12px;flex-wrap:wrap" });
    const endBtn = el("button", { class: "p-ghostbtn", style: "padding:5px 12px;border-radius:999px;border:1px solid var(--line);background:var(--panel);color:var(--ink-soft);font-size:var(--fs-sm)", text: "대화 종료" });
    const toggleBtn = el("button", {});
    const track = el("span", { style: "width:28px;height:16px;border-radius:999px;position:relative;display:inline-block" });
    const knob = el("span", { style: "position:absolute;top:2px;width:12px;height:12px;border-radius:50%;background:#fff;transition:left .15s" });
    track.appendChild(knob);
    const toggleText = document.createTextNode(" 기록 비공개");
    toggleBtn.appendChild(track);
    toggleBtn.appendChild(toggleText);
    header.appendChild(el("h2", { style: "margin:0;font-size:var(--fs-xl)", text: "대화" }));
    header.appendChild(el("div", { style: "flex:1" }));
    header.appendChild(endBtn);
    header.appendChild(toggleBtn);

    const hint = el("p", { style: "margin:0;font-size:var(--fs-sm);color:var(--ink-soft)" });
    const log = el("div", { style: "display:flex;flex-direction:column;gap:10px;background:var(--panel-2);border:1px solid var(--line-soft);border-radius:var(--radius);padding:var(--sp-4);min-height:220px;max-height:calc(100vh - 340px);overflow-y:auto" });
    const inputRow = el("div", { style: "display:flex;gap:8px" });
    const input = el("input", { type: "text", style: "flex:1;font-family:inherit;font-size:var(--fs-sm);padding:10px 14px;border-radius:999px;border:1px solid var(--line);background:var(--panel-2);color:var(--ink)" });
    const sendBtn = el("button", { class: "p-solidbtn", style: "padding:10px 18px;border-radius:999px;border:1px solid var(--accent);background:var(--accent);color:#fff;font-size:var(--fs-sm);font-weight:600", text: "보내기" });
    inputRow.appendChild(input);
    inputRow.appendChild(sendBtn);

    wrap.appendChild(header);
    wrap.appendChild(hint);
    wrap.appendChild(log);
    wrap.appendChild(inputRow);
    sec.appendChild(wrap);

    function updateRecordVisuals() {
      toggleBtn.style.cssText = `display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);border-radius:999px;padding:5px 12px;font-size:var(--fs-sm);color:var(--ink);background:var(${recordOn ? "--panel-2" : "--warn-soft"})`;
      track.style.background = `var(${recordOn ? "--accent" : "--ink-faint"})`;
      knob.style.left = recordOn ? "14px" : "2px";
      toggleText.textContent = " 기록 " + (recordOn ? "허용" : "비공개");
      hint.textContent = recordOn
        ? "이 대화는 에이전트의 기억(SOUL.md·저널)에 남습니다."
        : "기록이 꺼져 있어요 — 이 대화는 에이전트의 기억에 남지 않습니다.";
      input.placeholder = recordOn ? "메시지 보내기…" : "비공개로 메시지 보내기…";
    }
    toggleBtn.addEventListener("click", () => {
      recordOn = !recordOn;
      updateRecordVisuals();
    });
    updateRecordVisuals();

    function appendLine(who, text) {
      const mine = who === "me";
      const bubble = el("div", {
        style:
          `align-self:${mine ? "flex-end" : "flex-start"};max-width:80%;font-size:var(--fs-sm);padding:8px 12px;white-space:pre-wrap;word-break:break-word;` +
          (mine
            ? "background:var(--accent-soft);border-radius:12px 12px 3px 12px"
            : "background:var(--panel);border:1px solid var(--line-soft);border-radius:12px 12px 12px 3px"),
        text,
      });
      log.appendChild(bubble);
      log.scrollTop = log.scrollHeight;
    }

    async function send() {
      const msg = input.value.trim();
      if (!msg) return;
      input.value = "";
      appendLine("me", msg);
      const wasActive = !!sessionId;
      try {
        const res = await api.sendChat(msg, sessionId, recordOn);
        sessionId = (res && res.session_id) || sessionId;
        appendLine("them", (res && res.reply) || "(응답 없음)");
        if (!wasActive && onChatStateChange) onChatStateChange(true);
      } catch (e) {
        appendLine("them", "(오류) 메시지를 보내지 못했습니다: " + e.message);
      }
    }

    async function end() {
      if (!sessionId) return;
      try {
        await api.endChat(sessionId);
      } catch (e) {
        appendLine("them", "(오류) 대화 종료 실패: " + e.message);
      }
      sessionId = null;
      if (onChatStateChange) onChatStateChange(false);
      appendLine("them", "(대화가 종료되었습니다)");
    }

    sendBtn.addEventListener("click", send);
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") send();
    });
    endBtn.addEventListener("click", end);

    loaders.chat = { load() {} };
  }

  // ---------------------------------------------------------------
  // 선물 / 메시지 (POST /api/inbox)
  // ---------------------------------------------------------------
  {
    const sec = sections.inbox;
    const wrap = el("div", { style: "display:flex;flex-direction:column;gap:var(--sp-4);max-width:560px" });
    wrap.appendChild(
      el("div", {}, [
        el("h2", { style: "margin:0 0 4px;font-size:var(--fs-xl)", text: "선물 · 메시지" }),
        el("p", { style: "margin:0;font-size:var(--fs-sm);color:var(--ink-soft)", html: '우편함에 넣어두면 에이전트가 <strong>다음에 우편함을 열 때</strong> 읽습니다. 즉시 반응하지 않아요 — 편지처럼요.' }),
      ])
    );
    const kindSel = el("select", { style: INPUT_STYLE }, [
      el("option", { value: "message", text: "메시지" }),
      el("option", { value: "gift", text: "읽을거리 (URL)" }),
    ]);
    const contentInput = el("textarea", { rows: "4", placeholder: "메시지 또는 URL을 남겨보세요", style: "resize:vertical;" + INPUT_STYLE });
    const urlInput = el("input", { type: "text", placeholder: "URL (선물일 때만)", style: INPUT_STYLE });
    urlInput.style.display = "none";
    kindSel.addEventListener("change", () => {
      urlInput.style.display = kindSel.value === "gift" ? "" : "none";
    });
    const sendBtn = el("button", { class: "p-solidbtn", style: "align-self:flex-end;" + ACCENT_BTN, text: "우편함에 넣기" });
    const statusMsg = el("div", { style: "font-size:var(--fs-sm);color:var(--ink-faint)" });

    sendBtn.addEventListener("click", async () => {
      const content = contentInput.value.trim();
      if (!content) {
        statusMsg.textContent = "내용을 입력해주세요.";
        return;
      }
      statusMsg.textContent = "보내는 중…";
      try {
        await api.postInbox(kindSel.value, content, kindSel.value === "gift" ? urlInput.value.trim() : undefined);
        statusMsg.textContent = "우편함에 넣었습니다. (다음에 우편함을 열 때 읽습니다)";
        contentInput.value = "";
        urlInput.value = "";
      } catch (e) {
        statusMsg.textContent = "전달 실패: " + e.message;
      }
    });

    wrap.appendChild(kindSel);
    wrap.appendChild(contentInput);
    wrap.appendChild(urlInput);
    wrap.appendChild(sendBtn);
    wrap.appendChild(statusMsg);
    sec.appendChild(wrap);

    loaders.inbox = { load() {} };
  }

  // ---------------------------------------------------------------
  // 요청함 (관찰자 아웃박스 — 돌봄 투두리스트)
  // ---------------------------------------------------------------
  {
    const sec = sections.outbox;
    const wrap = el("div", { style: "display:flex;flex-direction:column;gap:var(--sp-4);max-width:680px" });
    wrap.appendChild(
      el("div", {}, [
        el("h2", { style: "margin:0 0 4px;font-size:var(--fs-xl)", text: "요청함" }),
        el("p", { style: "margin:0;font-size:var(--fs-sm);color:var(--ink-soft)", text: "에이전트가 관찰자에게 보낸 요청입니다. 응답하면 다음 스텝에서 확인합니다." }),
      ])
    );

    const FILTERS = [
      { value: "all", label: "전체" },
      { value: "open", label: "열림" },
      { value: "resolved", label: "완료" },
      { value: "declined", label: "거절" },
      { value: "ignored", label: "무시" },
    ];
    const STATUS_LABEL = { open: "열림", resolved: "완료", declined: "거절", ignored: "무시" };

    const filterSel = el("select", { style: "font-family:inherit;font-size:var(--fs-sm);padding:6px 10px;border-radius:var(--radius-sm);border:1px solid var(--line);background:var(--panel-2);color:var(--ink)" }, FILTERS.map((f) => el("option", { value: f.value, text: f.label })));
    wrap.appendChild(el("div", { style: "display:flex;align-items:center;gap:8px" }, [el("span", { style: "font-size:var(--fs-xs);color:var(--ink-faint)", text: "상태" }), filterSel]));

    const listHost = el("div", { style: "display:flex;flex-direction:column;gap:var(--sp-4)" });
    wrap.appendChild(listHost);
    sec.appendChild(wrap);

    // "전체"는 능동적 돌봄 뷰: open + resolved + declined, ignored 는 "무시"에서만.
    function matchesFilter(status, filter) {
      if (filter === "all") return status !== "ignored";
      return status === filter;
    }

    function statusChip(status) {
      const open = status === "open";
      return el("span", {
        style: open
          ? "font-size:var(--fs-xs);padding:1px 8px;border-radius:999px;background:var(--accent-soft);color:var(--accent-ink);font-weight:600"
          : "font-size:var(--fs-xs);padding:1px 8px;border-radius:999px;background:var(--panel-3);color:var(--ink-soft)",
        text: STATUS_LABEL[status] || status,
      });
    }

    async function reload() {
      listHost.innerHTML = "";
      listHost.appendChild(emptyNote("불러오는 중…"));
      let requests;
      try {
        const res = await api.getOutbox();
        requests = (res && res.requests) || [];
      } catch (e) {
        listHost.innerHTML = "";
        listHost.appendChild(emptyNote("요청 목록을 불러오지 못했습니다: " + e.message));
        return;
      }
      const rows = requests.filter((r) => matchesFilter(r.status, filterSel.value));
      listHost.innerHTML = "";
      if (!rows.length) {
        listHost.appendChild(emptyNote("표시할 요청이 없습니다."));
        return;
      }
      rows.forEach((r) => listHost.appendChild(buildRow(r)));
    }

    function buildRow(r) {
      const open = r.status === "open";
      const card = el("div", {
        style: open
          ? "border:1px solid var(--line);border-radius:var(--radius);background:var(--panel-2);padding:var(--sp-4);display:flex;flex-direction:column;gap:12px"
          : "border:1px solid var(--line-soft);border-radius:var(--radius);background:var(--panel-2);padding:var(--sp-4);display:flex;flex-direction:column;gap:8px;opacity:.75",
      });
      card.appendChild(
        el("div", { style: "display:flex;align-items:baseline;gap:8px;flex-wrap:wrap" }, [
          statusChip(r.status),
          el("span", { style: "font-family:var(--mono);font-size:var(--fs-xs);color:var(--ink-faint)", text: r.id + (r.ts ? " · " + fmtTime(r.ts) : "") + (r.step_id ? " · " + r.step_id : "") }),
        ])
      );
      card.appendChild(el("p", { style: "margin:0", text: r.text || "(내용 없음)" }));

      if (open) {
        card.appendChild(buildResolveForm(r));
      } else {
        if (r.observer_note) {
          card.appendChild(el("p", { style: "margin:0;font-size:var(--fs-sm);color:var(--ink-soft)", text: "↳ 관찰자: " + r.observer_note }));
        }
        if (r.attachment) {
          card.appendChild(el("div", { style: "font-size:var(--fs-xs);color:var(--ink-faint)", text: "첨부: " + String(r.attachment).split("/").pop() }));
        }
        if (r.status === "ignored") {
          const statusMsg = el("div", { style: "font-size:var(--fs-sm);color:var(--ink-faint)" });
          statusMsg.style.display = "none";
          const reopenBtn = el("button", { class: "p-ghostbtn", style: "align-self:flex-start;" + GHOST_BTN, text: "다시 열기" });
          reopenBtn.addEventListener("click", async () => {
            reopenBtn.disabled = true;
            statusMsg.style.display = "none";
            try {
              const fd = new FormData();
              fd.append("status", "reopened");
              await api.resolveOutbox(r.id, fd);
              await reload();
            } catch (e) {
              reopenBtn.disabled = false;
              statusMsg.style.display = "";
              statusMsg.textContent = "다시 열기 실패: " + e.message;
            }
          });
          card.appendChild(reopenBtn);
          card.appendChild(statusMsg);
        }
      }
      return card;
    }

    function buildResolveForm(r) {
      const form = el("div", { style: "border-top:1px dashed var(--line);padding-top:12px;display:flex;flex-direction:column;gap:10px" });
      const noteInput = el("textarea", { rows: "2", placeholder: "에이전트에게 남길 노트 (선택)", style: "resize:vertical;" + INPUT_STYLE });
      const fileInput = el("input", { type: "file" });
      fileInput.style.display = "none";
      const statusMsg = el("div", { style: "font-size:var(--fs-sm);color:var(--ink-faint)" });
      statusMsg.style.display = "none";

      const attachBtn = el("button", { class: "p-ghostbtn", style: "padding:7px 14px;border-radius:var(--radius-sm);border:1px dashed var(--line);background:none;color:var(--ink-soft);font-size:var(--fs-sm)", text: "📎 파일 첨부" });
      const declineBtn = el("button", { class: "p-ghostbtn", style: GHOST_BTN, text: "거절" });
      const ignoreBtn = el("button", { class: "p-ghostbtn", style: GHOST_BTN, text: "무시" });
      const doneBtn = el("button", { class: "p-solidbtn", style: "padding:7px 16px;border-radius:var(--radius-sm);border:1px solid var(--accent);background:var(--accent);color:#fff;font-size:var(--fs-sm);font-weight:600", text: "완료로 응답" });

      attachBtn.addEventListener("click", () => {
        fileInput.style.display = fileInput.style.display === "none" ? "" : "none";
      });
      function setBusy(busy) {
        [doneBtn, declineBtn, ignoreBtn, attachBtn].forEach((b) => (b.disabled = busy));
      }
      // includeFile: 완료/거절은 첨부 가능; 무시는 노트/파일 없이 보낸다.
      async function submit(status, includeFile) {
        setBusy(true);
        statusMsg.style.display = "none";
        try {
          const fd = new FormData();
          fd.append("status", status);
          if (status !== "ignored") {
            const note = noteInput.value.trim();
            if (note) fd.append("note", note);
            if (includeFile && fileInput.files && fileInput.files.length) {
              fd.append("file", fileInput.files[0]);
            }
          }
          await api.resolveOutbox(r.id, fd);
          await reload();
        } catch (e) {
          setBusy(false);
          statusMsg.style.display = "";
          statusMsg.textContent = "처리 실패: " + e.message;
        }
      }
      doneBtn.addEventListener("click", () => submit("resolved", true));
      declineBtn.addEventListener("click", () => submit("declined", true));
      ignoreBtn.addEventListener("click", () => submit("ignored", false));

      form.appendChild(noteInput);
      form.appendChild(
        el("div", { style: "display:flex;gap:8px;align-items:center;flex-wrap:wrap" }, [
          attachBtn,
          el("div", { style: "flex:1" }),
          ignoreBtn,
          declineBtn,
          doneBtn,
        ])
      );
      form.appendChild(fileInput);
      form.appendChild(statusMsg);
      return form;
    }

    filterSel.addEventListener("change", reload);
    loaders.outbox = { load: reload };
  }

  // default tab: a valid #hash deep-link wins, else the step tab
  const hashTab = (location.hash || "").slice(1);
  activate(ALL_TAB_IDS.includes(hashTab) ? hashTab : "step");

  const panels = {
    openStep: (stepId) => openStepDetail(stepId),
    activate,
    setOutboxBadge: (count) => {
      lastOutboxCount = count > 0 ? count : 0;
      if (outboxBadge) {
        if (count > 0) {
          outboxBadge.textContent = String(count);
          outboxBadge.style.display = "";
        } else {
          outboxBadge.style.display = "none";
        }
      }
    },
    refreshRevealed: () => {
      if (loaders.revealed) {
        loaders.revealed._loaded = false;
        if (activeId === "revealed") {
          loaders.revealed._loaded = true;
          loaders.revealed.load();
        }
      }
    },
    refreshStats: () => {
      // 새 스텝이 기록될 때마다 통계를 신선하게: 활성 탭이면 즉시 다시 그리고,
      // 아니면 다음 활성화 때 다시 불러오게 표시만 해 둔다.
      if (loaders.stats) {
        loaders.stats._loaded = false;
        if (activeId === "stats") {
          loaders.stats._loaded = true;
          loaders.stats.load();
        }
      }
    },
  };

  return panels;
}

// ---------------------------------------------------------------------------
// Wiki graph: simple canvas-drawn node/link view (no external lib).
// Places nodes on a circle and draws straight-line links.
// ---------------------------------------------------------------------------

function drawWikiGraph(canvas, graph, onNodeClick) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const nodes = (graph && graph.nodes) || [];
  const links = (graph && graph.links) || [];
  if (!nodes.length) {
    ctx.fillStyle = "#888";
    ctx.font = "13px sans-serif";
    ctx.fillText("위키 페이지가 아직 없습니다.", 10, 20);
    return;
  }

  const cx = w / 2;
  const cy = h / 2;
  const r = Math.min(w, h) / 2 - 50;
  const positions = {};
  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length;
    positions[n.id] = { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle), node: n };
  });

  ctx.strokeStyle = "#b6b0a0";
  ctx.lineWidth = 1;
  links.forEach((l) => {
    const a = positions[l.src];
    const b = positions[l.dst];
    if (!a || !b) return;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  });

  ctx.font = "11px sans-serif";
  Object.values(positions).forEach((p) => {
    ctx.fillStyle = "#4a7dbf";
    ctx.beginPath();
    ctx.arc(p.x, p.y, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#333";
    ctx.fillText(p.node.title || p.node.id, p.x + 10, p.y + 4);
  });

  canvas.onclick = (ev) => {
    const rect = canvas.getBoundingClientRect();
    const mx = ev.clientX - rect.left;
    const my = ev.clientY - rect.top;
    for (const p of Object.values(positions)) {
      const dx = mx - p.x;
      const dy = my - p.y;
      if (dx * dx + dy * dy <= 10 * 10) {
        onNodeClick(p.node.id);
        return;
      }
    }
  };
}
