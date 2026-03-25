import { useEffect, useState } from "react";
import { fetchMission, sendMessage, fetchChatHistory } from "./api.js";
import ChatWindow from "./components/ChatWindow.jsx";

function getSessionId() {
  let id = localStorage.getItem("chat_session_id");
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem("chat_session_id", id);
  }
  return id;
}

export default function App() {
  const [mission, setMission] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const sessionId = getSessionId();

  useEffect(() => {
    Promise.all([fetchMission(), fetchChatHistory(sessionId)])
      .then(([m, history]) => {
        setMission(m);
        if (history.length === 0) {
          // 처음 방문: AI 인사 요청
          requestGreeting(m.title);
        } else {
          setMessages(history);
        }
      })
      .catch(() => {
        setMessages([{ role: "assistant", content: "코치에 연결할 수 없어요. 잠시 후 다시 시도해 봐!" }]);
      });
  }, []);

  async function requestGreeting(missionTitle) {
    setLoading(true);
    try {
      const res = await sendMessage("__GREET__", sessionId, missionTitle);
      setMessages([{ role: "assistant", content: res.response }]);
    } catch {
      setMessages([{ role: "assistant", content: "안녕! 오늘도 함께 해보자 🌟" }]);
    } finally {
      setLoading(false);
    }
  }

  async function handleSend(text) {
    // 낙관적 업데이트: 유저 메시지 먼저 표시
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);

    try {
      const res = await sendMessage(text, sessionId, mission?.title);
      setMessages((prev) => [...prev, { role: "assistant", content: res.response }]);
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
      </header>

      {mission && (
        <div className="mission-banner">
          🎯 오늘 미션: <strong>{mission.title}</strong>
        </div>
      )}

      <ChatWindow messages={messages} onSend={handleSend} loading={loading} />
    </div>
  );
}
