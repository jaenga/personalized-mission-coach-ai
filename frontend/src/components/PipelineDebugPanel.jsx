import { useState } from "react";

// ── 인텐트 색상 ──────────────────────────────────────────────
const INTENT_COLOR = {
  A: { bg: "#E8F5E9", text: "#388E3C", label: "A · 일반 대화" },
  B: { bg: "#E3F2FD", text: "#1565C0", label: "B · 앱 기능" },
  C: { bg: "#FFF3E0", text: "#E65100", label: "C · 건강 질문" },
  D: { bg: "#F5F5F5", text: "#757575", label: "D · 의도 불명확" },
};

function intentMeta(intent) {
  return INTENT_COLOR[intent] ?? { bg: "#F5F5F5", text: "#555", label: intent ?? "—" };
}

// ── 함수 이름 한글화 ─────────────────────────────────────────
const FN_LABEL = {
  submit_mission_result:      "미션 결과 제출",
  request_mission_adjustment: "미션 변경 요청",
  cancel_mission_action:      "미션 액션 취소",
  get_mission_info:           "미션 정보 조회",
  get_user_history:           "활동 기록 조회",
  check_mission_equivalency:  "미션 동등성 확인",
};
function fnLabel(name) {
  return FN_LABEL[name] ?? name;
}

// ── 제출 결과 한글화 ─────────────────────────────────────────
const SUBMIT_STATUS = {
  saved:            { text: "DB 저장 완료", color: "#388E3C" },
  already_submitted:{ text: "이미 제출됨",  color: "#E65100" },
  skipped:          { text: "건너뜀",       color: "#757575" },
};
const RESULT_TYPE = { success: "성공 ✅", partial: "부분 달성 🟡", failure: "실패 ❌", fail: "실패 ❌" };

// ── 타이밍 바 ────────────────────────────────────────────────
function TimingBar({ label, ms, maxMs, color = "#E35D49" }) {
  if (ms == null || ms <= 0) return null;
  const pct = Math.min(100, Math.round((ms / Math.max(maxMs, 1)) * 100));
  return (
    <div style={{ marginBottom: 6 }}>
      <div className="font-pretendard" style={{ display: "flex", justifyContent: "space-between", fontSize: 13, color: "#555", marginBottom: 3 }}>
        <span>{label}</span>
        <span style={{ fontWeight: 700, color }}>{ms.toLocaleString()}ms</span>
      </div>
      <div style={{ height: 6, borderRadius: 4, background: "#F0EDE8", overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, borderRadius: 4, background: color, transition: "width 0.4s ease" }} />
      </div>
    </div>
  );
}

// ── 섹션 카드 ─────────────────────────────────────────────────
function Card({ children, style }) {
  return (
    <div
      className="font-pretendard"
      style={{
        background: "#FFFFFF",
        borderRadius: 14,
        border: "1px solid rgba(227, 93, 73, 0.12)",
        padding: "12px 14px",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function SectionLabel({ children }) {
  return (
    <div style={{ fontSize: 12, fontWeight: 800, color: "#E35D49", letterSpacing: "0.5px", marginBottom: 8, textTransform: "uppercase" }}>
      {children}
    </div>
  );
}

// ── Step Row: 파이프라인 흐름 한 줄 ─────────────────────────
function StepRow({ icon, label, badge, badgeBg, badgeColor, detail, ms, active }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        opacity: active === false ? 0.35 : 1,
        transition: "opacity 0.3s",
      }}
    >
      <div style={{
        width: 28, height: 28, borderRadius: 8,
        background: active ? "rgba(227,93,73,0.10)" : "#F5F2EE",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 14, flexShrink: 0,
      }}>
        {icon}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: "#1a1a1a" }}>{label}</span>
          {badge && (
            <span style={{
              fontSize: 12, fontWeight: 800, padding: "2px 8px", borderRadius: 6,
              background: badgeBg ?? "rgba(227,93,73,0.10)", color: badgeColor ?? "#E35D49",
            }}>
              {badge}
            </span>
          )}
          {ms != null && ms > 0 && (
            <span style={{ fontSize: 12, color: "#aaa", marginLeft: "auto" }}>{ms.toLocaleString()}ms</span>
          )}
        </div>
        {detail && (
          <div style={{ fontSize: 13, color: "#7b7069", marginTop: 3, lineHeight: "17px", wordBreak: "break-word" }}>
            {detail}
          </div>
        )}
      </div>
    </div>
  );
}

// ── 라이브 점 애니메이션 ─────────────────────────────────────
function LiveDots() {
  return (
    <span style={{ display: "inline-flex", gap: 3, alignItems: "center", verticalAlign: "middle" }}>
      {[0, 1, 2].map((i) => (
        <span key={i} style={{
          width: 4, height: 4, borderRadius: "50%", background: "#E35D49",
          display: "inline-block",
          animation: "typingDot 1s infinite ease-in-out",
          animationDelay: `${i * 0.16}s`,
        }} />
      ))}
    </span>
  );
}

// ── 메인 컴포넌트 ────────────────────────────────────────────
export default function PipelineDebugPanel({ debug, liveStages = [], onClose }) {
  const [showPrompt, setShowPrompt] = useState(false);

  // 인텐트: done debug 우선, 없으면 liveStages에서
  const intentStage = liveStages.find((s) => s.stage === "intent");
  const qwenStage   = liveStages.find((s) => s.stage === "qwen");
  const ragStage    = liveStages.find((s) => s.stage === "rag");
  const isGenerating = liveStages.some((s) => s.stage === "generating");
  const isLive = !debug && liveStages.length > 0;

  const intent    = debug?.intent ?? intentStage?.value;
  const intentLbl = intentStage?.label ?? debug?.intent;
  const meta      = intentMeta(["A","B","C","D"].includes(intent) ? intent : null);

  const timing    = debug?.timing ?? {};
  const maxMs     = Math.max(timing.intent_ms ?? 0, timing.qwen_ms ?? 0, timing.rag_ms ?? 0, timing.gen_ms ?? 0, 1);

  // qwen calls: done debug의 fn_args 또는 liveStages qwen
  const fnCalls   = qwenStage?.calls ?? (debug?.fn_args ? [["(from args)", debug.fn_args]] : []);

  const violations = debug?.violations ?? [];
  const submitResult = debug?.submit_result;
  const ragHits = debug?.rag_hits;

  // 어느 단계까지 진행됐는지
  const hasIntent    = !!intent;
  const hasQwen      = fnCalls.length > 0 || !!qwenStage;
  const hasRag       = !!ragStage || (debug?.rag_hits?.chunks > 0 || debug?.rag_hits?.faqs > 0);
  const hasGenerate  = isGenerating || timing.gen_ms != null;
  const isDone       = !!debug;

  return (
    <div
      className="font-pretendard"
      style={{
        width: 360,
        height: "min(874px, 100dvh)",
        background: "#FFF8F0",
        borderRadius: 24,
        border: "1px solid rgba(227, 93, 73, 0.18)",
        boxShadow: "0 8px 32px rgba(184,72,56,0.12), 0 2px 8px rgba(0,0,0,0.06)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        flexShrink: 0,
      }}
    >
      {/* 헤더 */}
      <div style={{
        padding: "16px 18px 12px",
        borderBottom: "1px solid rgba(227,93,73,0.10)",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        background: "rgba(255,248,240,0.95)",
        flexShrink: 0,
      }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 800, color: "#1a1a1a", letterSpacing: "-0.3px" }}>
            AI 실행 흐름
            {isLive && <span style={{ marginLeft: 8, fontSize: 13, color: "#E35D49" }}><LiveDots /></span>}
          </div>
          <div style={{ fontSize: 12, color: "#aaa", marginTop: 1 }}>
            {debug?.model ?? "gemma4:e2b"}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            width: 28, height: 28, borderRadius: 8,
            background: "rgba(227,93,73,0.08)", border: "none",
            display: "flex", alignItems: "center", justifyContent: "center",
            cursor: "pointer", color: "#E35D49", fontSize: 14, fontWeight: 700,
          }}
        >✕</button>
      </div>

      {/* 스크롤 영역 */}
      <div style={{ flex: 1, overflowY: "auto", padding: "14px 14px 20px", display: "flex", flexDirection: "column", gap: 10 }}>

        {/* 1. 파이프라인 흐름 카드 */}
        <Card>
          <SectionLabel>실행 파이프라인</SectionLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>

            {/* Intent */}
            <StepRow
              icon="🔍"
              label="Intent 분류"
              badge={hasIntent ? (intentLbl ?? meta.label) : undefined}
              badgeBg={meta.bg}
              badgeColor={meta.text}
              ms={timing.intent_ms}
              active={hasIntent}
              detail={!hasIntent ? "대기 중" : undefined}
            />

            {/* 구분선 + 화살표 */}
            {hasIntent && (
              <div style={{ display: "flex", alignItems: "center", paddingLeft: 14 }}>
                <div style={{ width: 1, height: 12, background: "rgba(227,93,73,0.2)" }} />
              </div>
            )}

            {/* Qwen (B일 때) */}
            {(intent === "B" || hasQwen) && (
              <>
                <StepRow
                  icon="⚡"
                  label="Qwen Function Call"
                  ms={timing.qwen_ms ?? qwenStage?.ms}
                  active={hasQwen}
                  badge={hasQwen ? `${fnCalls.length}개 호출` : undefined}
                  detail={
                    hasQwen && fnCalls.length > 0
                      ? fnCalls.map(([fn]) => fnLabel(fn)).join(", ")
                      : (!hasQwen ? "대기 중" : undefined)
                  }
                />
                {hasQwen && (
                  <div style={{ display: "flex", alignItems: "center", paddingLeft: 14 }}>
                    <div style={{ width: 1, height: 12, background: "rgba(227,93,73,0.2)" }} />
                  </div>
                )}
              </>
            )}

            {/* RAG (C일 때) */}
            {(intent === "C" || hasRag) && (
              <>
                <StepRow
                  icon="📚"
                  label="RAG 검색"
                  ms={timing.rag_ms ?? ragStage?.ms}
                  active={hasRag}
                  badge={
                    hasRag
                      ? `${(ragHits?.chunks ?? ragStage?.hits ?? 0)}건 매칭`
                      : undefined
                  }
                  detail={
                    hasRag && ragHits
                      ? `문서 ${ragHits.chunks}건 · FAQ ${ragHits.faqs}건`
                      : (!hasRag ? "대기 중" : undefined)
                  }
                />
                {hasRag && (
                  <div style={{ display: "flex", alignItems: "center", paddingLeft: 14 }}>
                    <div style={{ width: 1, height: 12, background: "rgba(227,93,73,0.2)" }} />
                  </div>
                )}
              </>
            )}

            {/* Gemma4 생성 */}
            <StepRow
              icon="💬"
              label="Gemma4 응답 생성"
              ms={timing.gen_ms}
              active={hasGenerate}
              badge={
                isGenerating && !isDone ? "생성 중" :
                isDone ? "완료" : undefined
              }
              detail={!hasGenerate ? "대기 중" : undefined}
            />
          </div>
        </Card>

        {/* 2. Function Call 상세 */}
        {fnCalls.length > 0 && (
          <Card>
            <SectionLabel>Function Call 상세</SectionLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {fnCalls.map(([fn, args], i) => (
                <div key={i} style={{ background: "#FFF8F0", borderRadius: 10, padding: "8px 10px" }}>
                  <div style={{ fontSize: 14, fontWeight: 800, color: "#1565C0", marginBottom: 4 }}>
                    {fnLabel(fn)}
                  </div>
                  {args && Object.keys(args).length > 0 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                      {Object.entries(args).map(([k, v]) => (
                        <div key={k} style={{ display: "flex", gap: 6, fontSize: 13 }}>
                          <span style={{ color: "#aaa", flexShrink: 0 }}>{k}</span>
                          <span style={{ color: "#1a1a1a", fontWeight: 700, wordBreak: "break-all" }}>
                            {String(v)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* 3. DB 실행 결과 */}
        {submitResult && (
          <Card>
            <SectionLabel>DB 실행 결과</SectionLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 13, color: "#555" }}>상태</span>
                <span style={{
                  fontSize: 13, fontWeight: 800,
                  color: SUBMIT_STATUS[submitResult.status]?.color ?? "#555",
                }}>
                  {SUBMIT_STATUS[submitResult.status]?.text ?? submitResult.status}
                </span>
              </div>
              {submitResult.result_type && (
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 13, color: "#555" }}>결과 유형</span>
                  <span style={{ fontSize: 13, fontWeight: 800, color: "#1a1a1a" }}>
                    {RESULT_TYPE[submitResult.result_type] ?? submitResult.result_type}
                  </span>
                </div>
              )}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 13, color: "#555" }}>DB 변경</span>
                <span style={{ fontSize: 13, fontWeight: 800, color: submitResult.db_changed ? "#388E3C" : "#aaa" }}>
                  {submitResult.db_changed ? "변경됨" : "변경 없음"}
                </span>
              </div>
            </div>
          </Card>
        )}

        {/* 4. 타이밍 */}
        {isDone && timing.total_ms != null && (
          <Card>
            <SectionLabel>단계별 소요 시간</SectionLabel>
            <TimingBar label="🔍 Intent 분류" ms={timing.intent_ms} maxMs={maxMs} color="#1565C0" />
            <TimingBar label="⚡ Qwen FC"     ms={timing.qwen_ms}  maxMs={maxMs} color="#7B1FA2" />
            <TimingBar label="📚 RAG 검색"    ms={timing.rag_ms}   maxMs={maxMs} color="#E65100" />
            <TimingBar label="💬 Gemma4 생성" ms={timing.gen_ms}   maxMs={maxMs} color="#E35D49" />
            <div style={{
              marginTop: 10, paddingTop: 10,
              borderTop: "1px solid rgba(227,93,73,0.12)",
              display: "flex", justifyContent: "space-between", alignItems: "center",
            }}>
              <span style={{ fontSize: 14, fontWeight: 800, color: "#555" }}>총 소요</span>
              <span style={{
                fontSize: 16, fontWeight: 800,
                color: timing.total_ms > 5000 ? "#C62828" : timing.total_ms > 2000 ? "#E65100" : "#388E3C",
              }}>
                {(timing.total_ms / 1000).toFixed(1)}s
              </span>
            </div>
          </Card>
        )}

        {/* 5. 규칙 위반 */}
        {isDone && (
          <Card>
            <SectionLabel>규칙 검사</SectionLabel>
            {violations.length === 0 ? (
              <div style={{ fontSize: 14, color: "#388E3C", fontWeight: 700 }}>✅ 위반 없음</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {violations.map((v, i) => (
                  <div key={i} style={{
                    fontSize: 13, color: "#C62828", background: "#FFEBEE",
                    borderRadius: 6, padding: "4px 8px",
                  }}>{v}</div>
                ))}
              </div>
            )}
          </Card>
        )}

        {/* 6. 시스템 프롬프트 (고급 숨김) */}
        {isDone && debug?.system_prompt && (
          <Card>
            <button
              onClick={() => setShowPrompt((v) => !v)}
              style={{
                background: "none", border: "none", cursor: "pointer",
                fontSize: 13, fontWeight: 800, color: "#aaa", padding: 0,
                display: "flex", alignItems: "center", gap: 4,
              }}
            >
              <span>⚙️ 시스템 프롬프트</span>
              <span style={{ fontSize: 12 }}>{showPrompt ? "▲" : "▼"}</span>
            </button>
            {showPrompt && (
              <pre style={{
                marginTop: 8, fontSize: 10, color: "#7b7069",
                whiteSpace: "pre-wrap", wordBreak: "break-word",
                lineHeight: "15px", maxHeight: 200, overflowY: "auto",
                background: "#FFF3E0", borderRadius: 8, padding: "8px 10px",
              }}>
                {debug.system_prompt}
              </pre>
            )}
          </Card>
        )}

        {/* 히스토리 턴 수 */}
        {isDone && debug?.history_turns != null && (
          <div style={{ fontSize: 12, color: "#bbb", textAlign: "center", paddingTop: 4 }}>
            대화 컨텍스트 {debug.history_turns}턴 사용
          </div>
        )}
      </div>
    </div>
  );
}
