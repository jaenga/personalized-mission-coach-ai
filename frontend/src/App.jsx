import { useEffect, useState } from "react";
import { fetchMission, submitFeedback, fetchLogs } from "./api.js";
import MissionCard from "./components/MissionCard.jsx";
import FeedbackForm from "./components/FeedbackForm.jsx";
import CoachResponse from "./components/CoachResponse.jsx";
import HistoryList from "./components/HistoryList.jsx";

export default function App() {
  const [mission, setMission] = useState(null);
  const [loading, setLoading] = useState(false);
  const [aiResponse, setAiResponse] = useState(null);
  const [error, setError] = useState(null);
  const [logs, setLogs] = useState([]);
  const [showHistory, setShowHistory] = useState(false);

  // 미션 로드
  useEffect(() => {
    fetchMission().then(setMission).catch(() => setError("미션을 불러올 수 없어요."));
  }, []);

  async function handleFeedback({ result, reason }) {
    if (!mission) return;
    setLoading(true);
    setAiResponse(null);
    setError(null);

    try {
      const data = await submitFeedback({ mission: mission.title, result, reason });
      setAiResponse(data.ai_response);
      // 기록 패널이 열려있으면 자동 새로고침
      if (showHistory) loadLogs();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadLogs() {
    try {
      const data = await fetchLogs();
      setLogs(data);
    } catch {
      /* 조용히 무시 */
    }
  }

  function toggleHistory() {
    if (!showHistory) loadLogs();
    setShowHistory((v) => !v);
  }

  return (
    <div>
      {/* 헤더 */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1>🌟 AI 생활습관 코치</h1>
        <button
          type="button"
          onClick={toggleHistory}
          style={{
            background: showHistory ? "#e0f2fe" : "#f1f5f9",
            color: "#0369a1",
            fontSize: "0.82rem",
            padding: "6px 12px",
          }}
        >
          {showHistory ? "기록 닫기" : "기록 보기 📋"}
        </button>
      </div>

      {/* 오늘의 미션 */}
      {mission ? (
        <MissionCard mission={mission} />
      ) : (
        !error && <p style={{ color: "#94a3b8" }}>미션 불러오는 중...</p>
      )}

      {/* 피드백 폼 */}
      {mission && <FeedbackForm onSubmit={handleFeedback} loading={loading} />}

      {/* 코치 응답 */}
      <CoachResponse response={aiResponse} error={error} />

      {/* 기록 목록 */}
      {showHistory && (
        <HistoryList logs={logs} onRefresh={loadLogs} />
      )}
    </div>
  );
}
