export default function CoachResponse({ response, error }) {
  if (error) {
    return (
      <div className="card" style={{ borderLeft: "4px solid #ef4444" }}>
        <p style={{ color: "#ef4444" }}>⚠️ {error}</p>
      </div>
    );
  }

  if (!response) return null;

  return (
    <div className="card" style={{ borderLeft: "4px solid #a78bfa", background: "#faf5ff" }}>
      <h2>코치 선생님의 한마디 💬</h2>
      <p style={{ marginTop: 10, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>
        {response}
      </p>
    </div>
  );
}
