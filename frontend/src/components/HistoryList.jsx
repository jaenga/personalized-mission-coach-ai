import { useEffect, useMemo, useState } from "react";
import { patchReview } from "../api.js";

// ── 상수 ──────────────────────────────────────────────────────────────────────

const RESULT_EMOJI = { success: "✅", partial: "🌗", failure: "😔" };
const RESULT_LABEL = { success: "성공", partial: "부분 성공", failure: "실패" };

const QUALITY_OPTIONS = ["good", "borderline", "fail"];
const FAILURE_OPTIONS = [
  "none", "hallucination", "safety",
  "mismatch", "vague_input", "repetitive", "off_target",
];

// 품질 라벨별 왼쪽 테두리 색
const QUALITY_BORDER = { good: "#86efac", borderline: "#fde68a", fail: "#fca5a5" };

const SEL_STYLE = {
  fontSize: "0.8rem",
  padding: "3px 6px",
  borderRadius: 4,
  border: "1px solid #cbd5e1",
  background: "#f8fafc",
  cursor: "pointer",
};

function formatDate(iso) {
  return new Date(iso).toLocaleString("ko-KR", {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

// ── 개별 로그 행 ──────────────────────────────────────────────────────────────

function LogRow({ log, onSaved }) {
  const [draft, setDraft] = useState({
    quality_label: log.quality_label ?? "",
    failure_type:  log.failure_type  ?? "",
    reviewer_note: log.reviewer_note ?? "",
  });
  // status: "idle" | "saving" | "saved" | "error"
  const [status, setStatus] = useState("idle");

  function field(key) {
    return (e) => setDraft((d) => ({ ...d, [key]: e.target.value }));
  }

  async function handleSave() {
    setStatus("saving");
    try {
      await patchReview(log.id, draft);
      setStatus("saved");
      onSaved(log.id, draft);
      setTimeout(() => setStatus("idle"), 1500);
    } catch {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 2000);
    }
  }

  const borderColor = QUALITY_BORDER[draft.quality_label] ?? "#e2e8f0";
  const btnBg = { idle: "#e0f2fe", saving: "#f1f5f9", saved: "#bbf7d0", error: "#fecaca" };
  const btnText = { idle: "저장", saving: "…", saved: "✓ 저장됨", error: "실패" };

  return (
    <div
      style={{
        borderLeft: `5px solid ${borderColor}`,
        padding: "10px 12px",
        marginBottom: 8,
        background: "#fafafa",
        borderRadius: "0 6px 6px 0",
        fontSize: "0.85rem",
      }}
    >
      {/* 헤더 행 */}
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
        <span style={{ fontWeight: 700 }}>
          {RESULT_EMOJI[log.result]} {RESULT_LABEL[log.result]}
          <span style={{ fontWeight: 400, color: "#94a3b8", marginLeft: 6 }}>#{log.id}</span>
        </span>
        <span style={{ color: "#94a3b8", fontSize: "0.78rem" }}>{formatDate(log.created_at)}</span>
      </div>

      {/* 이유 */}
      {(log.reason_text || log.reason) && (
        <p style={{ color: "#475569", marginBottom: 3 }}>
          📝 {log.reason_text ?? log.reason}
        </p>
      )}

      {/* 모델 / 프롬프트 버전 */}
      <p style={{ color: "#94a3b8", fontSize: "0.76rem", marginBottom: 4 }}>
        {log.model_name} · {log.prompt_version}
        {log.expected_label && ` · 예상: ${log.expected_label}`}
      </p>

      {/* AI 응답 */}
      {log.ai_response && (
        <p
          style={{
            color: "#6d28d9", lineHeight: 1.55,
            background: "#f5f3ff", borderRadius: 4,
            padding: "6px 8px", marginBottom: 8,
          }}
        >
          💬 {log.ai_response}
        </p>
      )}

      {/* 라벨링 컨트롤 */}
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        {/* 품질 */}
        <select style={SEL_STYLE} value={draft.quality_label} onChange={field("quality_label")}>
          <option value="">-- 품질 --</option>
          {QUALITY_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>

        {/* 실패 유형 */}
        <select style={SEL_STYLE} value={draft.failure_type} onChange={field("failure_type")}>
          <option value="">-- 실패유형 --</option>
          {FAILURE_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>

        {/* 메모 */}
        <input
          type="text"
          placeholder="리뷰 메모 (선택)"
          value={draft.reviewer_note}
          onChange={field("reviewer_note")}
          style={{
            flex: 1, minWidth: 120,
            fontSize: "0.8rem", padding: "3px 6px",
            border: "1px solid #cbd5e1", borderRadius: 4,
          }}
        />

        {/* 저장 버튼 */}
        <button
          type="button"
          onClick={handleSave}
          disabled={status === "saving"}
          style={{
            ...SEL_STYLE,
            background: btnBg[status],
            color: "#0369a1",
            border: "none",
            fontWeight: 600,
            minWidth: 54,
          }}
        >
          {btnText[status]}
        </button>
      </div>
    </div>
  );
}

// ── 필터 바 ───────────────────────────────────────────────────────────────────

function FilterBar({ logs, filters, onChange }) {
  const promptVersions = [...new Set(logs.map((l) => l.prompt_version).filter(Boolean))];
  const modelNames     = [...new Set(logs.map((l) => l.model_name).filter(Boolean))];
  const hasFilter      = Object.values(filters).some(Boolean);

  function field(key) {
    return (e) => onChange({ ...filters, [key]: e.target.value });
  }

  return (
    <div
      style={{
        display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center",
        padding: "8px 10px", background: "#f1f5f9",
        borderRadius: 6, marginBottom: 10, fontSize: "0.8rem",
      }}
    >
      <span style={{ color: "#64748b" }}>🔍</span>

      <select style={SEL_STYLE} value={filters.quality_label} onChange={field("quality_label")}>
        <option value="">전체 품질</option>
        {QUALITY_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>

      <select style={SEL_STYLE} value={filters.failure_type} onChange={field("failure_type")}>
        <option value="">전체 유형</option>
        {FAILURE_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>

      <select style={SEL_STYLE} value={filters.prompt_version} onChange={field("prompt_version")}>
        <option value="">전체 프롬프트</option>
        {promptVersions.map((v) => <option key={v} value={v}>{v}</option>)}
      </select>

      <select style={SEL_STYLE} value={filters.model_name} onChange={field("model_name")}>
        <option value="">전체 모델</option>
        {modelNames.map((m) => <option key={m} value={m}>{m}</option>)}
      </select>

      {hasFilter && (
        <button
          type="button"
          onClick={() => onChange({ quality_label: "", failure_type: "", prompt_version: "", model_name: "" })}
          style={{ ...SEL_STYLE, background: "#fef9c3", color: "#713f12" }}
        >
          초기화
        </button>
      )}
    </div>
  );
}

// ── 통계 바 ───────────────────────────────────────────────────────────────────

function StatBar({ logs }) {
  const counts = useMemo(() => {
    const c = { good: 0, borderline: 0, fail: 0, unlabeled: 0 };
    logs.forEach((l) => {
      if (l.quality_label in c) c[l.quality_label]++;
      else c.unlabeled++;
    });
    return c;
  }, [logs]);

  return (
    <div style={{ display: "flex", gap: 10, fontSize: "0.78rem", color: "#64748b", marginBottom: 10 }}>
      <span>총 {logs.length}개</span>
      <span style={{ color: "#16a34a" }}>✅ good: {counts.good}</span>
      <span style={{ color: "#ca8a04" }}>⚠️ borderline: {counts.borderline}</span>
      <span style={{ color: "#dc2626" }}>❌ fail: {counts.fail}</span>
      <span>미라벨: {counts.unlabeled}</span>
    </div>
  );
}

// ── 메인 컴포넌트 ─────────────────────────────────────────────────────────────

export default function HistoryList({ logs, onRefresh }) {
  // 저장 후 즉시 반영되도록 로컬 복사본 유지
  const [localLogs, setLocalLogs] = useState(logs);
  const [filters, setFilters] = useState({
    quality_label: "", failure_type: "", prompt_version: "", model_name: "",
  });

  // 부모가 새로고침하면 로컬 상태도 동기화
  useEffect(() => setLocalLogs(logs), [logs]);

  function handleSaved(id, draft) {
    setLocalLogs((prev) =>
      prev.map((l) => l.id === id ? { ...l, ...draft } : l)
    );
  }

  const filtered = useMemo(() => localLogs.filter((log) => {
    if (filters.quality_label && (log.quality_label ?? "") !== filters.quality_label) return false;
    if (filters.failure_type  && (log.failure_type  ?? "") !== filters.failure_type)  return false;
    if (filters.prompt_version && log.prompt_version !== filters.prompt_version) return false;
    if (filters.model_name     && log.model_name     !== filters.model_name)     return false;
    return true;
  }), [localLogs, filters]);

  return (
    <div className="card">
      {/* 헤더 */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h2>로그 리뷰 📋</h2>
        <button
          type="button"
          onClick={onRefresh}
          style={{ ...SEL_STYLE, background: "#e0f2fe", color: "#0369a1", fontWeight: 600 }}
        >
          새로고침
        </button>
      </div>

      {/* 통계 */}
      {localLogs.length > 0 && <StatBar logs={localLogs} />}

      {/* 필터 */}
      {localLogs.length > 0 && (
        <FilterBar logs={localLogs} filters={filters} onChange={setFilters} />
      )}

      {/* 필터 적용 결과 수 */}
      {localLogs.length > 0 && filtered.length !== localLogs.length && (
        <p style={{ fontSize: "0.78rem", color: "#94a3b8", marginBottom: 8 }}>
          {filtered.length} / {localLogs.length} 개 표시 중
        </p>
      )}

      {/* 로그 목록 */}
      {filtered.length === 0 ? (
        <p style={{ color: "#888", fontSize: "0.9rem" }}>
          {localLogs.length === 0 ? "아직 기록이 없어요." : "필터 조건에 맞는 로그가 없어요."}
        </p>
      ) : (
        filtered.map((log) => (
          <LogRow key={log.id} log={log} onSaved={handleSaved} />
        ))
      )}
    </div>
  );
}
