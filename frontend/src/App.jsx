import { useEffect, useState } from "react";
import { fetchMission, sendMessage, fetchChatHistory, fetchAnalysis, clearChatHistory } from "./api.js";
import ChatWindow from "./components/ChatWindow.jsx";
import DebugPanel from "./components/DebugPanel.jsx";

function createSessionId() {
  const id = crypto.randomUUID();
  localStorage.setItem("chat_session_id", id);
  return id;
}

function getOrCreateSessionId() {
  return localStorage.getItem("chat_session_id") || createSessionId();
}

export default function App() {
  const [mission, setMission] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [debugMap, setDebugMap] = useState({});
  const [selectedDebugId, setSelectedDebugId] = useState(null);
  const [sessionId, setSessionId] = useState(getOrCreateSessionId);

  // 미션은 최초 1회만 fetch
  useEffect(() => {
    fetchMission().then(setMission).catch(() => {});
  }, []);

  // 세션 변경(초기 로드 or 리셋)마다 히스토리 로드
  useEffect(() => {
    if (!mission) return;
    fetchChatHistory(sessionId)
      .then((history) => {
        if (history.length === 0) {
          requestGreeting(mission.title);
        } else {
          setMessages(
            history.map((msg, i) =>
              msg.role === "assistant" ? { ...msg, debugId: `hist-${i}` } : msg
            )
          );
        }
      })
      .catch(() => {
        setMessages([{ role: "assistant", content: "코치에 연결할 수 없어요. 잠시 후 다시 시도해 봐!" }]);
      });
  }, [sessionId, mission]);

  async function handleReset() {
    if (loading) return;
    try {
      await clearChatHistory(sessionId);
    } catch {
      // 삭제 실패해도 프론트 상태는 초기화
    }
    setSessionId(createSessionId());
    setMessages([]);
    setDebugMap({});
    setSelectedDebugId(null);
  }

  /** 분석 결과를 백그라운드에서 폴링해서 debugMap[debugId]에 병합 */
  async function pollAnalysis(analysisId, debugId) {
    const MAX = 40; // 최대 40회 × 800ms = 32초
    for (let i = 0; i < MAX; i++) {
      await new Promise((r) => setTimeout(r, 800));
      try {
        const result = await fetchAnalysis(analysisId);
        if (result) {
          setDebugMap((prev) => ({
            ...prev,
            [debugId]: {
              ...prev[debugId],
              reasoning: result.reasoning,
              timing: { ...prev[debugId]?.timing, ...result.timing },
              analysing: false,
            },
          }));
          return;
        }
      } catch {
        // 일시적 오류는 무시하고 재시도
      }
    }
    // 타임아웃: analysing 해제
    setDebugMap((prev) =>
      prev[debugId] ? { ...prev, [debugId]: { ...prev[debugId], analysing: false } } : prev
    );
  }

  async function requestGreeting(missionTitle) {
    setLoading(true);
    try {
      const res = await sendMessage("__GREET__", sessionId, missionTitle);
      const debugId = crypto.randomUUID();
      setMessages([{ role: "assistant", content: res.response, debugId }]);
      setDebugMap({ [debugId]: { ...res.debug, analysing: !!res.analysis_id } });
      setSelectedDebugId(debugId);
      if (res.analysis_id) pollAnalysis(res.analysis_id, debugId);
    } catch {
      setMessages([{ role: "assistant", content: "안녕! 오늘도 함께 해보자 🌟" }]);
    } finally {
      setLoading(false);
    }
  }

  async function handleSend(text) {
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);

    try {
      const res = await sendMessage(text, sessionId, mission?.title);
      const debugId = crypto.randomUUID();
      setMessages((prev) => [...prev, { role: "assistant", content: res.response, debugId }]);
      setDebugMap((prev) => ({ ...prev, [debugId]: { ...res.debug, analysing: !!res.analysis_id } }));
      setSelectedDebugId(debugId);
      if (res.analysis_id) pollAnalysis(res.analysis_id, debugId);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "앗, 연결이 끊겼어. 다시 말해줄래?" },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app-layout">
      <header className="app-header">
        <span>🌟 AI 생활습관 코치</span>
        <button
          className="reset-btn"
          onClick={handleReset}
          disabled={loading}
          title="대화 초기화"
        >
          새 대화
        </button>
      </header>

      {mission && (
        <div className="mission-banner">
          🎯 오늘 미션: <strong>{mission.title}</strong>
        </div>
      )}

      <div className="main-area">
        <ChatWindow
          messages={messages}
          onSend={handleSend}
          loading={loading}
          selectedDebugId={selectedDebugId}
          onSelectMessage={setSelectedDebugId}
        />
        <DebugPanel
          debugInfo={debugMap[selectedDebugId] ?? null}
          selected={selectedDebugId !== null}
          previewText={
            messages.find((m) => m.debugId === selectedDebugId)?.content?.slice(0, 30) ?? null
          }
        />
      </div>
    </div>
  );
}
