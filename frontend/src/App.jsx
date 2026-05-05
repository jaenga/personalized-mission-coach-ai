import { useEffect, useState } from "react";
import { verifyStudent, saveProfile, fetchMissionByStudent, sendMessage, sendMessageStream, fetchChatHistory, clearChatHistory } from "./api.js";
import ChatWindow from "./components/ChatWindow.jsx";
import DebugPanel from "./components/DebugPanel.jsx";
import Login from "./components/Login.jsx";
import Signup from "./components/Signup.jsx";
import InfoInput from "./components/InfoInput.jsx";
import HealthNote from "./components/HealthNote.jsx";
import Welcome from "./components/Welcome.jsx";
import Home from "./components/Home.jsx";
import ChatScreen from "./components/ChatScreen.jsx";
import DrawScreen from "./components/DrawScreen.jsx";
import Settings from "./components/Settings.jsx";
import LevelUp from "./components/LevelUp.jsx";
import Ranking from "./components/Ranking.jsx";
import LearnScreen from "./components/LearnScreen.jsx";
import GameScreen from "./components/GameScreen.jsx";
import GameRanking from "./components/GameRanking.jsx";

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

const LEVEL_THRESHOLDS = { 1: 5, 2: 12, 3: 20, 4: 33, 5: 50 };
const MAX_HEARTS = 5;
const MISSION_EXP_BY_DIFFICULTY = { easy: 5, medium: 10, hard: 12 };
const ATTENDANCE_KEY = "daily_attendance_ticket_date";
const USER_STATS_KEY = "user_stats";
const HEALTH_NOTE_KEY = "health_note";

function getStoredHealthNote() {
  try {
    return JSON.parse(localStorage.getItem(HEALTH_NOTE_KEY) || "null");
  } catch {
    return null;
  }
}

function saveHealthNote(note) {
  if (note == null) localStorage.removeItem(HEALTH_NOTE_KEY);
  else localStorage.setItem(HEALTH_NOTE_KEY, JSON.stringify(note));
}

// 신규 가입자 기본값 — Lv1, 0 EXP, 뽑기권 0, 하트 1
const FRESH_STATS = { level: 1, currentXp: 0, ticketCount: 0, heartCount: 1 };

function getStoredStats() {
  try {
    const saved = JSON.parse(localStorage.getItem(USER_STATS_KEY) || "null");
    if (saved && typeof saved.level === "number") return saved;
  } catch {
    // ignore
  }
  return FRESH_STATS;
}

function applyExp(level, currentXp, gain) {
  let lv = level;
  let xp = currentXp + gain;
  while (LEVEL_THRESHOLDS[lv] && xp >= LEVEL_THRESHOLDS[lv]) {
    xp -= LEVEL_THRESHOLDS[lv];
    lv += 1;
  }
  return { level: lv, xp, maxXp: LEVEL_THRESHOLDS[lv] || 100 };
}

// 레벨 + 레벨 내 XP → 누적 XP (랭킹의 levelFromXp 5/17/37/70 기준에 맞춤)
function cumulativeXp(level, currentXp) {
  let total = 0;
  for (let i = 1; i < level; i++) total += LEVEL_THRESHOLDS[i] || 0;
  return total + currentXp;
}

function todayKey() {
  return new Date().toISOString().slice(0, 10);
}

export default function App() {
  const [routeHash, setRouteHash] = useState(() =>
    typeof window !== "undefined" ? window.location.hash : ""
  );
  const [mission, setMission] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [pipeline, setPipeline] = useState([]); // 실시간 파이프라인 단계
  const [debugMap, setDebugMap] = useState({});
  const [selectedDebugId, setSelectedDebugId] = useState(null);
  const [sessionId, setSessionId] = useState(getOrCreateSessionId);
  const [profile, setProfile] = useState(getStoredProfile);

  // 로그인 화면용 상태
  const [showWelcome, setShowWelcome] = useState(true);
  const [loginError, setLoginError] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);
  const [needsInfoInput, setNeedsInfoInput] = useState(false);
  const [needsHealthNote, setNeedsHealthNote] = useState(false);
  const [needsWelcomeCelebrate, setNeedsWelcomeCelebrate] = useState(false);
  const [showHome, setShowHome] = useState(false);
  const [showNewChat, setShowNewChat] = useState(false);
  const [showDraw, setShowDraw] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showRanking, setShowRanking] = useState(false);
  const [showLearn, setShowLearn] = useState(false);
  const [editHealthNote, setEditHealthNote] = useState(false);
  const [extraInfo, setExtraInfo] = useState(null);
  const [healthNote, setHealthNote] = useState(() => getStoredHealthNote());
  const [level, setLevel] = useState(() => getStoredStats().level);
  const [currentXp, setCurrentXp] = useState(() => getStoredStats().currentXp);
  const [maxXp, setMaxXp] = useState(() => LEVEL_THRESHOLDS[getStoredStats().level] || 100);
  const [ticketCount, setTicketCount] = useState(() => getStoredStats().ticketCount);
  const [heartCount, setHeartCount] = useState(() => getStoredStats().heartCount);
  const [leveledUpTo, setLeveledUpTo] = useState(null); // 레벨업 시 표시할 새 레벨

  // 통계 변경 시 localStorage에 저장
  useEffect(() => {
    localStorage.setItem(
      USER_STATS_KEY,
      JSON.stringify({ level, currentXp, ticketCount, heartCount })
    );
  }, [level, currentXp, ticketCount, heartCount]);
  const [firstDrawOfDay, setFirstDrawOfDay] = useState(true);

  useEffect(() => {
    function handleHashChange() {
      setRouteHash(window.location.hash);
    }
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  function addExp(gain) {
    if (!gain) return;
    const next = applyExp(level, currentXp, gain);
    setLevel(next.level);
    setCurrentXp(next.xp);
    setMaxXp(next.maxXp);
    if (next.level > level) {
      setLeveledUpTo(next.level); // 레벨업 → 축하 화면 표시
    }
  }

  function addTickets(amount) {
    setTicketCount((count) => Math.max(0, count + amount));
  }

  function addHearts(amount) {
    setHeartCount((count) => Math.max(0, Math.min(MAX_HEARTS, count + amount)));
  }

  function spendHeart(amount = 1) {
    if (heartCount < amount) return false;
    setHeartCount((count) => Math.max(0, count - amount));
    return true;
  }

  function refundHeart(amount = 1) {
    setHeartCount((count) => Math.min(MAX_HEARTS, count + amount));
  }

  function awardAttendanceIfNeeded() {
    const today = todayKey();
    if (localStorage.getItem(ATTENDANCE_KEY) === today) return;
    localStorage.setItem(ATTENDANCE_KEY, today);
    addTickets(1);
  }

  function awardMissionSuccess(difficulty) {
    const key = (difficulty || mission?.difficulty || "easy").toLowerCase();
    const gain = MISSION_EXP_BY_DIFFICULTY[key] ?? MISSION_EXP_BY_DIFFICULTY.easy;
    addExp(gain);
    addTickets(1);
  }

  // 미션 로드 (프로필 확정 후)
  useEffect(() => {
    if (!profile) return;
    awardAttendanceIfNeeded();
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

  function resetUserStats() {
    setLevel(FRESH_STATS.level);
    setCurrentXp(FRESH_STATS.currentXp);
    setMaxXp(LEVEL_THRESHOLDS[FRESH_STATS.level]);
    setTicketCount(FRESH_STATS.ticketCount);
    setHeartCount(FRESH_STATS.heartCount);
  }

  async function handleSignup({ name, phone4 }) {
    setLoginError("");
    setLoginLoading(true);
    // 디자인 미리보기용: 백엔드 없이 바로 다음 단계로 진행
    const MOCK_MODE = true;
    if (MOCK_MODE) {
      await new Promise((r) => setTimeout(r, 400));
      const saved = { student_id: 0, student_name: name };
      setProfile(saved);
      resetUserStats();
      setNeedsInfoInput(true);
      setLoginLoading(false);
      return;
    }
    try {
      const student = await verifyStudent(name, phone4);
      await saveProfile(sessionId, student.student_id, student.student_name);
      const saved = { student_id: student.student_id, student_name: student.student_name };
      localStorage.setItem("user_profile", JSON.stringify(saved));
      setProfile(saved);
      resetUserStats();
      setNeedsInfoInput(true);
    } catch (err) {
      setLoginError(err.message);
    } finally {
      setLoginLoading(false);
    }
  }

  function handleInfoSubmit(info) {
    setExtraInfo(info);
    setNeedsInfoInput(false);
    setNeedsHealthNote(true);
  }

  function handleHealthSubmit(note) {
    setHealthNote(note);
    saveHealthNote(note);
    setNeedsHealthNote(false);
    setNeedsWelcomeCelebrate(true);
  }

  function handleHealthSkip() {
    setHealthNote(null);
    saveHealthNote(null);
    setNeedsHealthNote(false);
    setNeedsWelcomeCelebrate(true);
  }

  function handleWelcomeContinue() {
    awardAttendanceIfNeeded();
    setNeedsWelcomeCelebrate(false);
    setShowHome(true);
  }

  function handleHealthBack() {
    setNeedsHealthNote(false);
    setNeedsInfoInput(true);
  }

  async function handleReset() {
    if (loading) return;
    try {
      await clearChatHistory(sessionId);
    } catch {
      // 삭제 실패해도 초기화
    }
    localStorage.removeItem("user_profile");
    localStorage.removeItem(USER_STATS_KEY);
    localStorage.removeItem("tommy_lesson_progress");
    localStorage.removeItem("tommy_run_records");
    localStorage.removeItem(HEALTH_NOTE_KEY);
    setSessionId(createSessionId());
    setProfile(null);
    setMission(null);
    setMessages([]);
    setDebugMap({});
    setSelectedDebugId(null);
    setLoginError("");
    setShowWelcome(true);
    setNeedsInfoInput(false);
    setExtraInfo(null);
    setNeedsHealthNote(false);
    setHealthNote(null);
    setNeedsWelcomeCelebrate(false);
    setShowHome(false);
    setShowNewChat(false);
    setShowDraw(false);
    setShowSettings(false);
    setShowRanking(false);
    setShowLearn(false);
    setLevel(FRESH_STATS.level);
    setCurrentXp(FRESH_STATS.currentXp);
    setMaxXp(LEVEL_THRESHOLDS[FRESH_STATS.level]);
    setTicketCount(FRESH_STATS.ticketCount);
    setHeartCount(FRESH_STATS.heartCount);
    setFirstDrawOfDay(true);
  }

  async function requestGreeting(missionTitle) {
    setLoading(true);
    try {
      const res = await sendMessage("__GREET__", sessionId, missionTitle);
      const debugId = crypto.randomUUID();
      setMessages([{ role: "assistant", content: res.response, debugId }]);
      setDebugMap({ [debugId]: { ...res.debug } });
      setSelectedDebugId(debugId);
    } catch {
      setMessages([{ role: "assistant", content: "안녕! 오늘도 함께 해보자 🌟" }]);
    } finally {
      setLoading(false);
    }
  }

  async function handleSend(text) {
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);
    setPipeline([]); // 파이프라인 초기화
    const debugId = crypto.randomUUID();

    // 빈 어시스턴트 버블 먼저 추가
    setMessages((prev) => [...prev, { role: "assistant", content: "", debugId, streaming: true }]);

    try {
      await sendMessageStream(
        text,
        sessionId,
        mission?.mission_name,
        {
          onPipeline: (stage) => {
            setPipeline((prev) => [...prev, stage]);
            // 디버그맵에도 최신 파이프라인 정보 반영
            if (stage.stage === "intent") {
              setDebugMap((prev) => ({
                ...prev,
                [debugId]: { ...prev[debugId], intent: stage.value },
              }));
              setSelectedDebugId(debugId);
            }
            if (stage.stage === "qwen") {
              setDebugMap((prev) => ({
                ...prev,
                [debugId]: {
                  ...prev[debugId],
                  detected_function: stage.fn,
                  fn_args: stage.args,
                },
              }));
            }
          },
          onToken: (token) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.debugId === debugId ? { ...m, content: m.content + token } : m
              )
            );
          },
          onDone: (debug) => {
            if (debug) {
              if (
                debug.submit_result?.status === "saved" &&
                debug.submit_result?.db_changed &&
                debug.submit_result?.result_type === "success"
              ) {
                awardMissionSuccess();
              }
              setDebugMap((prev) => ({
                ...prev,
                [debugId]: { ...prev[debugId], ...debug },
              }));
              // adjustment 후 미션 제목 갱신
              if (debug.fn_args?.adjustment_type || debug.detected_function === "request_mission_adjustment") {
                fetchMissionByStudent(profile.student_id)
                  .then(setMission)
                  .catch(() => {});
              }
            }
          },
        }
      );
      // 스트리밍 완료 — 파이프라인 로그 숨김
      setMessages((prev) =>
        prev.map((m) => (m.debugId === debugId ? { ...m, streaming: false } : m))
      );
      setPipeline([]);
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.debugId === debugId
            ? { ...m, content: "앗, 연결이 끊겼어. 다시 말해줄래?", streaming: false }
            : m
        )
      );
      setPipeline([]);
    } finally {
      setLoading(false);
    }
  }

  // ── 레벨업 미리보기 (URL #levelup 또는 #levelup=3) ──────────────────────────
  const hash = routeHash;
  if (hash.startsWith("#levelup")) {
    const m = hash.match(/=(\d)/);
    const lv = m ? parseInt(m[1], 10) : 2;
    return <LevelUp level={lv} onContinue={() => { window.location.hash = ""; }} />;
  }
  if (hash.startsWith("#ranking")) {
    return <Ranking studentName={profile?.student_name || "민준"} currentXp={cumulativeXp(level, currentXp)} onNavigate={() => { window.location.hash = ""; }} />;
  }
  if (hash.startsWith("#game-ranking")) {
    return <GameRanking studentName={profile?.student_name || "민준"} currentLevel={level} onNavigate={() => { window.location.hash = ""; }} />;
  }
  if (hash.startsWith("#learn")) {
    return (
      <LearnScreen
        level={level}
        currentXp={currentXp}
        maxXp={maxXp}
        ticketCount={ticketCount}
        heartCount={heartCount}
        onQuizReward={(reward) => {
          addTickets(reward.tickets || 0);
        }}
        onNavigate={() => { window.location.hash = ""; }}
      />
    );
  }
  if (hash.startsWith("#game")) {
    return (
      <GameScreen
        level={level}
        heartCount={heartCount}
        onSpendHeart={() => spendHeart(1)}
        onRefundHeart={() => refundHeart(1)}
        onNavigate={() => { window.location.hash = ""; }}
      />
    );
  }

  // ── 레벨업 축하 화면 (다른 화면보다 우선) ──────────────────────────────────
  if (leveledUpTo) {
    return (
      <LevelUp
        level={leveledUpTo}
        onContinue={() => {
          setLeveledUpTo(null);
          // 홈으로 이동 (다른 화면 닫기)
          setShowNewChat(false);
          setShowDraw(false);
          setShowSettings(false);
          setShowRanking(false);
          setShowLearn(false);
          setShowHome(true);
        }}
      />
    );
  }

  // ── 시작 화면 (Figma 로그인 화면) ────────────────────────────────────────────
  if (!profile && showWelcome) {
    return (
      <Login onStart={() => setShowWelcome(false)} />
    );
  }

  // ── 회원가입 화면 (Figma 1. 로그인 화면/회원가입) ─────────────────────────────
  if (!profile) {
    return (
      <Signup onSubmit={handleSignup} loading={loginLoading} error={loginError} />
    );
  }

  // ── 정보입력 화면 (Figma 1. 로그인 화면/정보입력) ─────────────────────────────
  if (needsInfoInput) {
    return (
      <InfoInput onSubmit={handleInfoSubmit} loading={false} error="" />
    );
  }

  // ── 건강노트 화면 (Figma 1. 로그인 화면/건강노트) ─────────────────────────────
  if (needsHealthNote) {
    return (
      <HealthNote
        onSubmit={handleHealthSubmit}
        onSkip={handleHealthSkip}
        onBack={handleHealthBack}
        loading={false}
      />
    );
  }

  // ── 가입축하 화면 (Figma 1. 로그인 화면/가입축하) ─────────────────────────────
  if (needsWelcomeCelebrate) {
    return <Welcome onContinue={handleWelcomeContinue} />;
  }

  // ── 홈 화면 (Figma 2. 홈 화면) ───────────────────────────────────────────────
  if (showHome && !showNewChat && !showDraw && !showSettings && !showRanking && !showLearn) {
    return (
      <Home
        studentName={profile?.student_name || "민준"}
        level={level}
        currentXp={currentXp}
        maxXp={maxXp}
        ticketCount={ticketCount}
        heartCount={heartCount}
        onNavigate={(key) => {
          if (key === "coach") setShowNewChat(true);
          if (key === "learn") setShowLearn(true);
          if (key === "draw") setShowDraw(true);
          if (key === "settings") setShowSettings(true);
          if (key === "rank") setShowRanking(true);
        }}
      />
    );
  }

  // ── 배움 길 화면 ────────────────────────────────────────────────────────────
  if (showLearn) {
    return (
      <LearnScreen
        level={level}
        currentXp={currentXp}
        maxXp={maxXp}
        ticketCount={ticketCount}
        heartCount={heartCount}
        onQuizReward={(reward) => {
          addTickets(reward.tickets || 0);
        }}
        onNavigate={(key) => {
          if (key === "home") setShowLearn(false);
          if (key === "coach") { setShowLearn(false); setShowNewChat(true); }
          if (key === "rank") { setShowLearn(false); setShowRanking(true); }
          if (key === "settings") { setShowLearn(false); setShowSettings(true); }
          if (key === "draw") { setShowLearn(false); setShowDraw(true); }
        }}
      />
    );
  }

  // ── 랭킹 화면 ───────────────────────────────────────────────────────────────
  if (showRanking) {
    return (
      <Ranking
        studentName={profile?.student_name || "민준"}
        currentXp={cumulativeXp(level, currentXp)}
        onNavigate={(key) => {
          if (key === "home") setShowRanking(false);
          if (key === "coach") { setShowRanking(false); setShowNewChat(true); }
          if (key === "learn") { setShowRanking(false); setShowLearn(true); }
          if (key === "settings") { setShowRanking(false); setShowSettings(true); }
        }}
      />
    );
  }

  // ── 설정 → 건강 노트 수정 모드 ────────────────────────────────────────────────
  if (showSettings && editHealthNote) {
    return (
      <HealthNote
        initialAllergens={healthNote?.allergens || []}
        initialCautionFoods={healthNote?.cautionFoods || []}
        onSubmit={(note) => {
          setHealthNote(note);
          saveHealthNote(note);
          setEditHealthNote(false);
        }}
        onSkip={() => setEditHealthNote(false)}
        onBack={() => setEditHealthNote(false)}
        loading={false}
      />
    );
  }

  // ── 설정 화면 ───────────────────────────────────────────────────────────────
  if (showSettings) {
    return (
      <Settings
        studentName={profile?.student_name || "민준"}
        level={level}
        heartCount={heartCount}
        onBack={() => setShowSettings(false)}
        onOpenHealthNote={() => setEditHealthNote(true)}
        onLogout={handleReset}
        onWithdraw={handleReset}
        onNavigate={(key) => {
          setShowSettings(false);
          if (key === "coach") setShowNewChat(true);
          if (key === "learn") setShowLearn(true);
          if (key === "rank") setShowRanking(true);
        }}
      />
    );
  }

  // ── 뽑기 화면 (Figma 3. 뽑기) ────────────────────────────────────────────────
  if (showDraw) {
    return (
      <DrawScreen
        level={level}
        currentXp={currentXp}
        maxXp={maxXp}
        ticketCount={ticketCount}
        heartCount={heartCount}
        firstOfDay={firstDrawOfDay}
        onSpendTicket={() => addTickets(-1)}
        onReward={(reward) => {
          addHearts(reward.heart || 0);
          addExp(reward.exp || 0);
          setFirstDrawOfDay(false);
        }}
        onBack={() => setShowDraw(false)}
        onNavigate={(key) => {
          if (key === "home") setShowDraw(false);
          if (key === "coach") {
            setShowDraw(false);
            setShowNewChat(true);
          }
          if (key === "settings") {
            setShowDraw(false);
            setShowSettings(true);
          }
          if (key === "rank") {
            setShowDraw(false);
            setShowRanking(true);
          }
          if (key === "learn") {
            setShowDraw(false);
            setShowLearn(true);
          }
        }}
      />
    );
  }

  // ── 새 채팅 화면 (Figma 3. 채팅 화면) ─────────────────────────────────────────
  if (showNewChat) {
    return (
      <ChatScreen onBack={() => setShowNewChat(false)} />
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
        <div className="chat-area">
          <ChatWindow
            messages={messages}
            onSend={handleSend}
            loading={loading}
            selectedDebugId={selectedDebugId}
            onSelectMessage={setSelectedDebugId}
          />
          {pipeline.length > 0 && (
            <div className="pipeline-log">
              {pipeline.map((s, i) => {
                if (s.stage === "intent") {
                  const colors = { A: "#6c757d", B: "#0d6efd", C: "#198754", D: "#dc3545" };
                  return (
                    <span key={i} className="pipeline-chip" style={{ borderColor: colors[s.value] ?? "#aaa" }}>
                      🔍 인텐트 <strong>{s.value}</strong> — {s.label} <em>({s.ms}ms)</em>
                    </span>
                  );
                }
                if (s.stage === "qwen") {
                  return (
                    <span key={i} className="pipeline-chip" style={{ borderColor: "#fd7e14" }}>
                      ⚡ Qwen → <strong>{s.fn ?? "없음"}</strong> <em>({s.ms}ms)</em>
                    </span>
                  );
                }
                if (s.stage === "rag") {
                  return (
                    <span key={i} className="pipeline-chip" style={{ borderColor: "#198754" }}>
                      📚 RAG <strong>{s.hits}개</strong> 결과
                    </span>
                  );
                }
                if (s.stage === "generating") {
                  return (
                    <span key={i} className="pipeline-chip generating" style={{ borderColor: "#6f42c1" }}>
                      ✨ Gemma4 응답 생성 중...
                    </span>
                  );
                }
                return null;
              })}
            </div>
          )}
        </div>
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
