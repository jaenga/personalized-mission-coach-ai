import { useState } from "react";

const REASONING_FIELDS = [
  { key: "input_signal",    label: "🔎 감지된 신호",        desc: "입력에서 발견한 핵심 키워드/상황" },
  { key: "applied_rule",    label: "📌 적용된 규칙",        desc: "어떤 규칙을 사용했는지" },
  { key: "avoided",         label: "🚫 의도적으로 피한 것", desc: "억제한 표현/행동" },
  { key: "response_choice", label: "✏️ 응답 선택 이유",     desc: "이 메시지를 고른 근거" },
];

function ViolationBanner({ violations }) {
  if (!violations || violations.length === 0) {
    return (
      <div className="violation-ok">
        ✅ 규칙 위반 없음
      </div>
    );
  }
  return (
    <div className="violation-warn">
      <div className="violation-warn-title">⚠️ 규칙 위반 감지 ({violations.length}건)</div>
      {violations.map((v, i) => (
        <div key={i} className="violation-item">{v}</div>
      ))}
    </div>
  );
}

function SentenceAnalysis({ sentences }) {
  if (!sentences || sentences.length === 0) return null;
  return (
    <div className="sentence-analysis">
      {sentences.map((item, i) => (
        <div key={i} className="sentence-row">
          <div className="sentence-text">"{item.sentence}"</div>
          <div className="sentence-purpose">→ {item.purpose}</div>
        </div>
      ))}
    </div>
  );
}

function ReasoningBlock({ reasoning }) {
  if (!reasoning) {
    return <div className="debug-reasoning-empty">LLM이 근거를 제공하지 않았어요.</div>;
  }

  if (typeof reasoning === "object") {
    return (
      <div className="debug-reasoning-structured">
        {REASONING_FIELDS.map(({ key, label, desc }) => (
          <div key={key} className="reasoning-field">
            <div className="reasoning-field-label" title={desc}>{label}</div>
            <div className="reasoning-field-value">
              {reasoning[key] || <span className="reasoning-empty">—</span>}
            </div>
          </div>
        ))}

        {reasoning.sentence_analysis?.length > 0 && (
          <div className="reasoning-field">
            <div className="reasoning-field-label">🔬 문장별 분석</div>
            <SentenceAnalysis sentences={reasoning.sentence_analysis} />
          </div>
        )}
      </div>
    );
  }

  return <div className="debug-reasoning">{reasoning}</div>;
}

export default function DebugPanel({ debugInfo, selected, previewText }) {
  const [showPrompt, setShowPrompt] = useState(false);

  return (
    <div className="debug-panel">
      <div className="debug-header">
        🔍 디버그 패널
        {previewText && (
          <div className="debug-header-preview">"{previewText}"</div>
        )}
      </div>

      {!selected ? (
        <div className="debug-empty">
          코치 응답을 클릭하면<br />분석 결과가 표시돼요.
        </div>
      ) : !debugInfo ? (
        <div className="debug-empty">
          이 메시지의 분석 데이터가 없어요.<br />
          <span className="debug-empty-sub">현재 세션에서 새로 받은 응답만<br />분석 데이터가 기록돼요.</span>
        </div>
      ) : (
        <>
          {/* 규칙 위반 배너 — 서버 사이드 감지 기준 */}
          <section className="debug-section">
            <ViolationBanner violations={debugInfo.violations} />
          </section>

          <section className="debug-section">
            <div className="debug-label">
              💬 응답 근거
              {debugInfo.analysing && (
                <span className="analysing-badge">분석 중…</span>
              )}
            </div>
            {debugInfo.analysing && !debugInfo.reasoning
              ? <div className="debug-reasoning-empty">분석 결과를 가져오는 중이에요.</div>
              : <ReasoningBlock reasoning={debugInfo.reasoning} />
            }
          </section>

          <section className="debug-section">
            <div className="debug-label">📊 상태 정보</div>
            <div className="debug-meta">
              <div className="debug-meta-row">
                <span className="meta-key">모델</span>
                <span className="meta-val">{debugInfo.model}</span>
              </div>
              <div className="debug-meta-row">
                <span className="meta-key">전달된 대화 턴</span>
                <span className="meta-val">{debugInfo.history_turns}회</span>
              </div>
            </div>
          </section>

          {debugInfo.timing && (
            <section className="debug-section">
              <div className="debug-label">⏱️ 응답 소요 시간</div>
              <div className="debug-meta">
                <div className="debug-meta-row">
                  <span className="meta-key">1차 (응답 생성)</span>
                  <span className="meta-val">
                    {debugInfo.timing.call1_ms != null
                      ? `${debugInfo.timing.call1_ms.toLocaleString()}ms`
                      : "—"}
                  </span>
                </div>
                <div className="debug-meta-row">
                  <span className="meta-key">2차 (분석)</span>
                  <span className="meta-val">
                    {debugInfo.timing.call2_ms != null
                      ? `${debugInfo.timing.call2_ms.toLocaleString()}ms`
                      : <span className="analysing-badge">대기 중…</span>}
                  </span>
                </div>
                {debugInfo.timing.total_ms != null && (
                  <div className="debug-meta-row">
                    <span className="meta-key">총 소요</span>
                    <span className={`meta-val ${debugInfo.timing.total_ms > 5000 ? "timing-slow" : debugInfo.timing.total_ms > 2000 ? "timing-mid" : "timing-fast"}`}>
                      {(debugInfo.timing.total_ms / 1000).toFixed(1)}s
                    </span>
                  </div>
                )}
              </div>
            </section>
          )}

          <section className="debug-section">
            <button
              className="debug-toggle"
              onClick={() => setShowPrompt((v) => !v)}
            >
              📋 시스템 프롬프트 {showPrompt ? "▲" : "▼"}
            </button>
            {showPrompt && (
              <pre className="debug-prompt">{debugInfo.system_prompt}</pre>
            )}
          </section>
        </>
      )}
    </div>
  );
}
