import { useEffect, useState } from "react";
import { verifyStudent, saveProfile, fetchMissionByStudent, sendMessage, fetchChatHistory, fetchAnalysis, clearChatHistory } from "./api.js";
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

function getStoredProfile() {
  try {
    return JSON.parse(localStorage.getItem("user_profile") || "null");
  } catch {
    return null;
  }
}

export default function App() {
  const [mission, setMission] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [debugMap, setDebugMap] = useState({});
  const [selectedDebugId, setSelectedDebugId] = useState(null);
  const [sessionId, setSessionId] = useState(getOrCreateSessionId);
  const [profile, setProfile] = useState(getStoredProfile);

  // 로그인 화면용 상태
  const [loginForm, setLoginForm] = useState({ name: "", phone4: "" });
  const [loginError, setLoginError] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);

  // 미션 로드 (프로필 확정 후)
  useEffect(() => {
    if (!profile) return;
    fetchMissionByStudent(profile.student_id)
      .then(setMission)
      .catch(() => setMission({ mission_id: 1, mission_name: "오늘의 미션" }));
  }, [profile]);

  // 채팅 히스토리 로드
  useEffect(() => {
    if (!mission || !profile) return;
    fetchChatHistory(sessionId)
      .then((history) => {
        if (history.length === 0) {
          requestGreeting(mission.mission_name);
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

  async function handleLogin(e) {
    e.preventDefault();
    setLoginError("");
    setLoginLoading(true);
    try {
      const student = await verifyStudent(loginForm.name.trim(), loginForm.phone4.trim());
      await saveProfile(sessionId, student.student_id, student.student_name);
      const saved = { student_id: student.student_id, student_name: student.student_name };
      localStorage.setItem("user_profile", JSON.stringify(saved));
      setProfile(saved);
    } catch (err) {
      setLoginError(err.message);
    } finally {
      setLoginLoading(false);
    }
  }

  async function handleReset() {
    if (loading) return;
    try {
      await clearChatHistory(sessionId);
    } catch {
      // 삭제 실패해도 초기화
    }
    localStorage.removeItem("user_profile");
    setSessionId(createSessionId());
    setProfile(null);
    setMission(null);
    setMessages([]);
    setDebugMap({});
    setSelectedDebugId(null);
    setLoginForm({ name: "", phone4: "" });
    setLoginError("");
  }

  async function pollAnalysis(analysisId, debugId) {
    const MAX = 40;
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
        // 일시적 오류 무시
      }
    }
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
      const res = await sendMessage(text, sessionId, mission?.mission_name);
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

  // ── 로그인 화면 ──────────────────────────────────────────────────────────────
  if (!profile) {
    return (
      <div className="app-layout">
        <header className="app-header">
          <span>🌟 AI 생활습관 코치</span>
        </header>
        <div className="profile-setup">
          <h2>안녕! 나는 누구?</h2>
          <form onSubmit={handleLogin} className="profile-form">
            <div className="profile-field">
              <label>이름</label>
              <input
                type="text"
                placeholder="이름을 입력해 줘"
                value={loginForm.name}
                onChange={(e) => setLoginForm((f) => ({ ...f, name: e.target.value }))}
                required
              />
            </div>
            <div className="profile-field">
              <label>전화번호 뒷 4자리</label>
              <input
                type="text"
                inputMode="numeric"
                maxLength={4}
                placeholder="0000"
                value={loginForm.phone4}
                onChange={(e) => setLoginForm((f) => ({ ...f, phone4: e.target.value.replace(/\D/g, "") }))}
                required
              />
            </div>
            {loginError && <p className="login-error">{loginError}</p>}
            <button
              type="submit"
              className="profile-submit-btn"
              disabled={loginLoading || !loginForm.name.trim() || loginForm.phone4.length !== 4}
            >
              {loginLoading ? "확인 중..." : "시작하기"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  // ── 채팅 화면 ────────────────────────────────────────────────────────────────
  return (
    <div className="app-layout">
      <header className="app-header">
        <span>🌟 {profile.student_name}의 코치</span>
        <button className="reset-btn" onClick={handleReset} disabled={loading}>
          학생 변경
        </button>
      </header>

      {mission && (
        <div className="mission-banner">
          🎯 오늘 미션: <strong>{mission.mission_name}</strong>
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
