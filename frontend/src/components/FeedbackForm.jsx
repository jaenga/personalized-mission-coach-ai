import { useState } from "react";

const RESULT_OPTIONS = [
  { value: "success", label: "✅ 성공", color: "#22c55e" },
  { value: "partial", label: "🌗 부분 성공", color: "#f59e0b" },
  { value: "failure", label: "😔 실패", color: "#ef4444" },
];

export default function FeedbackForm({ onSubmit, loading }) {
  const [result, setResult] = useState(null);
  const [reason, setReason] = useState("");

  const needsReason = result === "partial" || result === "failure";
  const canSubmit = result && (!needsReason || reason.trim().length > 0);

  function handleSubmit(e) {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit({ result, reason: needsReason ? reason.trim() : null });
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>오늘 어땠어? 🤔</h2>

      {/* 결과 선택 버튼 */}
      <div style={{ display: "flex", gap: 8, margin: "12px 0" }}>
        {RESULT_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => { setResult(opt.value); setReason(""); }}
            style={{
              flex: 1,
              background: result === opt.value ? opt.color : "#f1f5f9",
              color: result === opt.value ? "#fff" : "#444",
              fontSize: "0.85rem",
              padding: "10px 6px",
            }}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* 이유 입력 */}
      {needsReason && (
        <div style={{ marginBottom: 12 }}>
          <label
            htmlFor="reason"
            style={{ display: "block", marginBottom: 6, color: "#555", fontSize: "0.9rem" }}
          >
            왜 그랬는지 말해줄래? (짧게도 괜찮아!)
          </label>
          <textarea
            id="reason"
            rows={2}
            placeholder="예: 까먹었어 / 너무 힘들었어 / 시간이 없었어"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            disabled={loading}
          />
        </div>
      )}

      <button
        type="submit"
        disabled={!canSubmit || loading}
        style={{
          width: "100%",
          background: canSubmit ? "#5b9cf6" : "#cbd5e1",
          color: "#fff",
          padding: "12px",
        }}
      >
        {loading ? "코치한테 물어보는 중... ⏳" : "코치한테 보내기 🚀"}
      </button>
    </form>
  );
}
