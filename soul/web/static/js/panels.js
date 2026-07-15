// panels.js — DOM-based side/overlay panels (not Phaser).
//
// Tabs (per PLAN.md P4/C):
//   ① soul   — 영혼 성장: SOUL.md 현재본 + git 히스토리 타임라인 + diff
//   ② step   — 스텝 상세 + "사고 과정" (transcript) 탭
//   ③ wiki   — 검색 + 페이지 뷰 + 백링크 + 그래프(캔버스, 외부 라이브러리 없음)
//   ④ report — 일일 회고 리포트 목록/뷰어
//   ⑤ chat   — 대화 (기록 토글 기본 OFF, "기억되지 않음" 명시)
//   ⑥ inbox  — 선물/메시지 보내기 (POST /api/inbox)
//   ⑦ revealed — stated vs revealed 흥미 패널
//   journal (secondary/raw) — 스텝 원문 목록
//
// Plain DOM + the CSS classes defined in index.html's <style>. No frameworks.

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

function emptyNote(text) {
  return el("div", { class: "panel-empty", text });
}

const TABS = [
  { id: "soul", label: "영혼 성장" },
  { id: "step", label: "스텝 상세" },
  { id: "wiki", label: "위키" },
  { id: "report", label: "일일 리포트" },
  { id: "chat", label: "대화" },
  { id: "inbox", label: "선물/메시지" },
  { id: "revealed", label: "말과 행동" },
  { id: "journal", label: "저널(원문)" },
];

export function initPanels({ root, api, onChatStateChange }) {
  root.innerHTML = "";
  const tabBar = el("div", { class: "panel-tabs" });
  const contentHost = el("div", { class: "panel-content" });
  root.appendChild(tabBar);
  root.appendChild(contentHost);

  const sections = {};
  const buttons = {};
  let activeId = null;

  function activate(id) {
    if (activeId === id) return;
    activeId = id;
    Object.entries(sections).forEach(([k, node]) => node.classList.toggle("active", k === id));
    Object.entries(buttons).forEach(([k, btn]) => btn.classList.toggle("active", k === id));
    const loader = loaders[id];
    if (loader && !loader._loaded) {
      loader._loaded = true;
      loader.load();
    }
  }

  TABS.forEach((t) => {
    const btn = el("button", {
      class: "panel-tab",
      text: t.label,
      onclick: () => activate(t.id),
    });
    buttons[t.id] = btn;
    tabBar.appendChild(btn);
    const sec = el("div", { class: "panel-section" });
    sections[t.id] = sec;
    contentHost.appendChild(sec);
  });

  const loaders = {};

  // ---------------------------------------------------------------
  // ① 영혼 성장
  // ---------------------------------------------------------------
  {
    const sec = sections.soul;
    const soulBody = el("pre", { class: "soul-md" }, [""]);
    const historyList = el("div", { class: "soul-history" });
    const diffView = el("pre", { class: "soul-diff" }, [""]);
    sec.appendChild(el("h3", { text: "SOUL.md (현재)" }));
    sec.appendChild(soulBody);
    sec.appendChild(el("h3", { text: "성장사 (git 히스토리)" }));
    sec.appendChild(historyList);
    sec.appendChild(el("h3", { text: "선택한 커밋의 diff" }));
    sec.appendChild(diffView);

    loaders.soul = {
      async load() {
        try {
          const soul = await api.getSoul();
          soulBody.textContent = soul && soul.content ? soul.content : "(아직 SOUL.md 내용이 없습니다)";
          if (soul && soul.updated_at) {
            sec.querySelector("h3").after; // no-op, keep structure simple
          }
        } catch (e) {
          soulBody.textContent = "SOUL.md를 불러오지 못했습니다: " + e.message;
        }
        try {
          const hist = await api.getSoulHistory();
          historyList.innerHTML = "";
          const commits = (hist && hist.commits) || [];
          if (!commits.length) {
            historyList.appendChild(emptyNote("아직 커밋된 변경 이력이 없습니다."));
          }
          commits.forEach((c) => {
            const row = el("div", { class: "soul-commit" }, [
              el("span", { class: "soul-commit-msg", text: c.message || "(메시지 없음)" }),
              el("span", { class: "soul-commit-ts", text: fmtTime(c.ts) }),
            ]);
            row.addEventListener("click", async () => {
              diffView.textContent = "불러오는 중…";
              try {
                const d = await api.getSoulDiff(c.commit);
                diffView.textContent = (d && d.diff) || "(diff 없음)";
              } catch (e2) {
                diffView.textContent = "diff를 불러오지 못했습니다: " + e2.message;
              }
            });
            historyList.appendChild(row);
          });
        } catch (e) {
          historyList.innerHTML = "";
          historyList.appendChild(emptyNote("히스토리를 불러오지 못했습니다: " + e.message));
        }
      },
    };
  }

  // ---------------------------------------------------------------
  // ② 스텝 상세 + 사고 과정
  // ---------------------------------------------------------------
  let currentStepId = null;
  {
    const sec = sections.step;
    const header = el("div", { class: "step-header" }, [emptyNote("말풍선이나 저널 항목을 클릭하면 여기에 상세가 표시됩니다.")]);
    const subTabs = el("div", { class: "sub-tabs" }, [
      el("button", { class: "sub-tab active", text: "산출물", id: "step-tab-content" }),
      el("button", { class: "sub-tab", text: "사고 과정", id: "step-tab-transcript" }),
    ]);
    const contentBody = el("pre", { class: "step-body" }, [""]);
    const transcriptBody = el("div", { class: "transcript-body" });
    transcriptBody.style.display = "none";
    sec.appendChild(header);
    sec.appendChild(subTabs);
    sec.appendChild(contentBody);
    sec.appendChild(transcriptBody);

    subTabs.children[0].addEventListener("click", () => {
      subTabs.children[0].classList.add("active");
      subTabs.children[1].classList.remove("active");
      contentBody.style.display = "";
      transcriptBody.style.display = "none";
    });
    subTabs.children[1].addEventListener("click", async () => {
      subTabs.children[1].classList.add("active");
      subTabs.children[0].classList.remove("active");
      contentBody.style.display = "none";
      transcriptBody.style.display = "";
      if (!currentStepId) return;
      transcriptBody.innerHTML = "불러오는 중…";
      try {
        const t = await api.getStepTranscript(currentStepId);
        const entries = (t && t.entries) || [];
        transcriptBody.innerHTML = "";
        if (!entries.length) {
          transcriptBody.appendChild(emptyNote("이 스텝에는 보존된 사고 과정 트랜스크립트가 없습니다."));
        }
        entries.forEach((e) => {
          transcriptBody.appendChild(
            el("div", { class: "transcript-entry" }, [
              el("div", { class: "transcript-role", text: e.role || "?" }),
              el("pre", { class: "transcript-content", text: typeof e.content === "string" ? e.content : JSON.stringify(e, null, 2) }),
            ])
          );
        });
      } catch (e) {
        transcriptBody.innerHTML = "";
        transcriptBody.appendChild(emptyNote("사고 과정을 불러오지 못했습니다: " + e.message));
      }
    });

    loaders.step = { load() {} }; // populated on-demand via openStepDetail()

    var openStepDetail = async function (stepId) {
      currentStepId = stepId;
      activate("step");
      header.innerHTML = "";
      header.appendChild(el("div", { text: "스텝: " + stepId }));
      contentBody.textContent = "불러오는 중…";
      subTabs.children[0].click();
      try {
        const detail = await api.getStep(stepId);
        const rec = detail && detail.record;
        if (rec) {
          header.innerHTML = "";
          header.appendChild(
            el("div", { class: "step-meta" }, [
              el("span", { text: "행동: " + (rec.action || "-") }),
              el("span", { text: "흥미: " + (rec.interest != null ? rec.interest : "-") }),
              el("span", { text: "결정: " + (rec.decision || "-") }),
              el("span", { text: "기분: " + (rec.mood || "-") }),
              el("span", { text: fmtTime(rec.ts) }),
            ])
          );
        }
        contentBody.textContent = (detail && detail.content) || "(산출물 내용 없음)";
      } catch (e) {
        contentBody.textContent = "스텝 상세를 불러오지 못했습니다: " + e.message;
      }
    };
  }

  // ---------------------------------------------------------------
  // ③ 위키
  // ---------------------------------------------------------------
  {
    const sec = sections.wiki;
    const searchRow = el("div", { class: "wiki-search-row" });
    const searchInput = el("input", { type: "text", placeholder: "위키 검색…", class: "wiki-search-input" });
    const searchBtn = el("button", { text: "검색" });
    searchRow.appendChild(searchInput);
    searchRow.appendChild(searchBtn);
    const resultsList = el("div", { class: "wiki-results" });
    const pageView = el("div", { class: "wiki-page-view" });
    const graphToggle = el("button", { class: "wiki-graph-toggle", text: "그래프 보기" });
    const graphCanvas = el("canvas", { class: "wiki-graph-canvas", width: "560", height: "360" });
    graphCanvas.style.display = "none";

    sec.appendChild(el("h3", { text: "위키" }));
    sec.appendChild(searchRow);
    sec.appendChild(resultsList);
    sec.appendChild(graphToggle);
    sec.appendChild(graphCanvas);
    sec.appendChild(pageView);

    async function doSearch(q) {
      resultsList.innerHTML = "검색 중…";
      try {
        const res = q ? await api.searchWiki(q) : await api.getWikiPages();
        resultsList.innerHTML = "";
        const items = (res && (res.results || res.pages)) || [];
        if (!items.length) {
          resultsList.appendChild(emptyNote("결과가 없습니다."));
          return;
        }
        items.forEach((it) => {
          const row = el("div", { class: "wiki-result-row" }, [
            el("span", { class: "wiki-result-title", text: it.title || it.slug }),
            el("span", { class: "wiki-result-snippet", text: it.snippet || "" }),
          ]);
          row.addEventListener("click", () => openWikiPage(it.slug));
          resultsList.appendChild(row);
        });
      } catch (e) {
        resultsList.innerHTML = "";
        resultsList.appendChild(emptyNote("위키를 불러오지 못했습니다: " + e.message));
      }
    }

    async function openWikiPage(slug) {
      pageView.innerHTML = "불러오는 중…";
      try {
        const pg = await api.getWikiPage(slug);
        pageView.innerHTML = "";
        pageView.appendChild(el("h4", { text: pg.slug }));
        pageView.appendChild(el("pre", { class: "wiki-page-content", text: pg.content || "" }));
        const backlinks = pg.backlinks || [];
        pageView.appendChild(el("div", { class: "wiki-backlinks-label", text: "백링크 (" + backlinks.length + ")" }));
        const bl = el("div", { class: "wiki-backlinks" });
        backlinks.forEach((b) => {
          const link = el("span", { class: "wiki-backlink", text: b });
          link.addEventListener("click", () => openWikiPage(b));
          bl.appendChild(link);
        });
        pageView.appendChild(bl);
      } catch (e) {
        pageView.innerHTML = "";
        pageView.appendChild(emptyNote("페이지를 불러오지 못했습니다: " + e.message));
      }
    }

    searchBtn.addEventListener("click", () => doSearch(searchInput.value.trim()));
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
  // ④ 일일 리포트
  // ---------------------------------------------------------------
  {
    const sec = sections.report;
    const list = el("div", { class: "report-list" });
    const view = el("pre", { class: "report-view" }, [""]);
    sec.appendChild(el("h3", { text: "일일 회고" }));
    sec.appendChild(list);
    sec.appendChild(view);

    loaders.report = {
      async load() {
        try {
          const res = await api.getReports();
          const dates = (res && res.dates) || [];
          list.innerHTML = "";
          if (!dates.length) {
            list.appendChild(emptyNote("아직 작성된 일일 리포트가 없습니다."));
            return;
          }
          dates
            .slice()
            .reverse()
            .forEach((d) => {
              const row = el("div", { class: "report-row", text: d });
              row.addEventListener("click", async () => {
                view.textContent = "불러오는 중…";
                try {
                  const rep = await api.getReport(d);
                  view.textContent = (rep && rep.content) || "(내용 없음)";
                } catch (e) {
                  view.textContent = "리포트를 불러오지 못했습니다: " + e.message;
                }
              });
              list.appendChild(row);
            });
        } catch (e) {
          list.innerHTML = "";
          list.appendChild(emptyNote("리포트 목록을 불러오지 못했습니다: " + e.message));
        }
      },
    };
  }

  // ---------------------------------------------------------------
  // ⑤ 대화 (기록 토글 기본 OFF)
  // ---------------------------------------------------------------
  {
    const sec = sections.chat;
    let sessionId = null;
    let recordOn = false;

    sec.appendChild(el("h3", { text: "대화" }));
    sec.appendChild(
      el("p", { class: "panel-note", text: "대화 중에는 캐릭터가 문 앞으로 이동합니다. 진행 중이던 활동은 대화가 끝나면 이어서 재개됩니다." })
    );

    const recordLabel = el("label", { class: "chat-record-toggle" });
    const recordCheckbox = el("input", { type: "checkbox" });
    recordLabel.appendChild(recordCheckbox);
    recordLabel.appendChild(document.createTextNode(" 이 대화를 기록함"));
    const recordHint = el("div", {
      class: "chat-record-hint",
      text: "기록 안 함 (기본값) = 이 대화는 저장되지 않으며, 에이전트에게 \"기억되지 않음\" 상태로 남습니다.",
    });
    recordCheckbox.addEventListener("change", () => {
      recordOn = recordCheckbox.checked;
      recordHint.textContent = recordOn
        ? "기록함 = 이 대화는 저장되고, 다음 활동 시점에 에이전트에게 전달될 수 있습니다."
        : "기록 안 함 (기본값) = 이 대화는 저장되지 않으며, 에이전트에게 \"기억되지 않음\" 상태로 남습니다.";
    });

    const log = el("div", { class: "chat-log" });
    const inputRow = el("div", { class: "chat-input-row" });
    const input = el("input", { type: "text", placeholder: "메시지를 입력하세요…", class: "chat-input" });
    const sendBtn = el("button", { text: "보내기" });
    const endBtn = el("button", { text: "대화 종료", class: "chat-end-btn" });
    inputRow.appendChild(input);
    inputRow.appendChild(sendBtn);
    inputRow.appendChild(endBtn);

    sec.appendChild(recordLabel);
    sec.appendChild(recordHint);
    sec.appendChild(log);
    sec.appendChild(inputRow);

    function appendLine(who, text) {
      log.appendChild(el("div", { class: "chat-line chat-line-" + who }, [el("b", { text: who === "me" ? "나: " : "존재: " }), text]));
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
  // ⑥ 선물/메시지 보내기
  // ---------------------------------------------------------------
  {
    const sec = sections.inbox;
    sec.appendChild(el("h3", { text: "선물 / 메시지 보내기" }));
    sec.appendChild(
      el("p", {
        class: "panel-note",
        text: "다음 활동 시작 시 \"관찰자가 남긴 것\"으로 전달됩니다. 반응할지 말지는 전적으로 에이전트의 자유입니다.",
      })
    );
    const kindSel = el("select", {}, [
      el("option", { value: "message", text: "메시지" }),
      el("option", { value: "gift", text: "읽을거리 (URL)" }),
    ]);
    const contentInput = el("textarea", { class: "inbox-content", placeholder: "내용을 입력하세요…", rows: "3" });
    const urlInput = el("input", { type: "text", class: "inbox-url", placeholder: "URL (선물일 때만)" });
    urlInput.style.display = "none";
    kindSel.addEventListener("change", () => {
      urlInput.style.display = kindSel.value === "gift" ? "" : "none";
    });
    const sendBtn = el("button", { text: "보내기" });
    const statusMsg = el("div", { class: "panel-note" });

    sendBtn.addEventListener("click", async () => {
      const content = contentInput.value.trim();
      if (!content) {
        statusMsg.textContent = "내용을 입력해주세요.";
        return;
      }
      statusMsg.textContent = "보내는 중…";
      try {
        await api.postInbox(kindSel.value, content, kindSel.value === "gift" ? urlInput.value.trim() : undefined);
        statusMsg.textContent = "전달되었습니다. (다음 활동 시 참고될 수 있습니다)";
        contentInput.value = "";
        urlInput.value = "";
      } catch (e) {
        statusMsg.textContent = "전달 실패: " + e.message;
      }
    });

    sec.appendChild(kindSel);
    sec.appendChild(contentInput);
    sec.appendChild(urlInput);
    sec.appendChild(sendBtn);
    sec.appendChild(statusMsg);

    loaders.inbox = { load() {} };
  }

  // ---------------------------------------------------------------
  // ⑦ stated vs revealed
  // ---------------------------------------------------------------
  {
    const sec = sections.revealed;
    sec.appendChild(el("h3", { text: "말한 흥미 vs 드러난 흥미" }));
    sec.appendChild(
      el("p", {
        class: "panel-note",
        text: "stated = 매 스텝 스스로 보고한 흥미. revealed = 실제 행동(지속 시간, 재방문)에서 계산된 흥미. 둘의 괴리는 숨기지 않고 그대로 보여줍니다.",
      })
    );
    const body = el("div", { class: "revealed-body" });
    sec.appendChild(body);

    loaders.revealed = {
      async load() {
        body.innerHTML = "불러오는 중…";
        try {
          const rv = await api.getRevealed();
          body.innerHTML = "";
          if (rv && rv.stated_vs_revealed_note) {
            body.appendChild(el("div", { class: "revealed-note", text: rv.stated_vs_revealed_note }));
          }
          const threads = (rv && rv.top_threads) || [];
          if (!threads.length) {
            body.appendChild(emptyNote("아직 축적된 데이터가 없습니다."));
          }
          threads.forEach((t) => {
            body.appendChild(
              el("div", { class: "revealed-thread" }, [
                el("span", { class: "revealed-thread-topic", text: t.topic || "(주제 없음)" }),
                el("span", { text: "재방문 " + (t.revisits != null ? t.revisits : "-") + "회" }),
                el("span", { text: "지속 " + (t.persistence_steps != null ? t.persistence_steps : "-") + "스텝" }),
              ])
            );
          });
        } catch (e) {
          body.innerHTML = "";
          body.appendChild(emptyNote("불러오지 못했습니다: " + e.message));
        }
      },
    };
  }

  // ---------------------------------------------------------------
  // 저널 (원문, 보조 화면)
  // ---------------------------------------------------------------
  {
    const sec = sections.journal;
    sec.appendChild(el("h3", { text: "저널 (원문, 보조 화면)" }));
    const list = el("div", { class: "journal-list" });
    sec.appendChild(list);

    loaders.journal = {
      async load() {
        list.innerHTML = "불러오는 중…";
        try {
          const res = await api.getSteps(50);
          const steps = (res && res.steps) || [];
          list.innerHTML = "";
          if (!steps.length) {
            list.appendChild(emptyNote("아직 기록된 스텝이 없습니다."));
          }
          steps.forEach((s) => {
            const row = el("div", { class: "journal-row" }, [
              el("span", { class: "journal-id", text: s.id }),
              el("span", { text: s.action || "-" }),
              el("span", { text: "흥미 " + (s.interest != null ? s.interest : "-") }),
              el("span", { text: s.decision || "-" }),
              el("span", { class: "journal-ts", text: fmtTime(s.ts) }),
            ]);
            row.addEventListener("click", () => panels.openStep(s.id));
            list.appendChild(row);
          });
        } catch (e) {
          list.innerHTML = "";
          list.appendChild(emptyNote("저널을 불러오지 못했습니다: " + e.message));
        }
      },
    };
  }

  // default tab
  activate("soul");

  const panels = {
    openStep: (stepId) => openStepDetail(stepId),
    activate,
    refreshRevealed: () => {
      if (loaders.revealed) {
        loaders.revealed._loaded = false;
        if (activeId === "revealed") loaders.revealed.load();
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
