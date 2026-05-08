import { useEffect, useState } from "react";
import { verifyStudent, registerDemoStudent, saveProfile, fetchMissionByStudent, fetchStudentStats, fetchAppState, adjustHeart, claimAttendance, claimDrawReward, recordGameRun, sendMessage, sendMessageStream, fetchChatHistory, clearChatHistory, fetchHealthNote, saveHealthNoteDb, deleteHealthNote } from "./api.js";
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
import AppLoadingScreen from "./components/AppLoadingScreen.jsx";

// ── 화면 상수 ──────────────────────────────────────────────────────────────
const SCREENS = {
  LOGIN: "login",
  SIGNUP: "signup",
  SIGNUP_CONFIRM: "signup_confirm",
  SIGNUP_FAREWELL: "signup_farewell",
  ONBOARD_INFO: "onboard_info",
  ONBOARD_HEALTH: "onboard_health",
  ONBOARD_WELCOME: "onboard_welcome",
  HOME: "home",
  CHAT: "chat",
  DRAW: "draw",
  SETTINGS: "settings",
  SETTINGS_HEALTH_EDIT: "settings_health_edit",
  RANKING: "ranking",
  LEARN: "learn",
  GAME: "game",
};

// 컴포넌트 onNavigate(key) → SCREENS 매핑
const NAV_KEY_TO_SCREEN = {
  home: SCREENS.HOME,
  coach: SCREENS.CHAT,
  learn: SCREENS.LEARN,
  draw: SCREENS.DRAW,
  game: SCREENS.GAME,
  settings: SCREENS.SETTINGS,
  rank: SCREENS.RANKING,
};

// ── 세션/프로필 헬퍼 ───────────────────────────────────────────────────────
function createSessionId() {
  const id = createClientId("session");
  localStorage.setItem("chat_session_id", id);
  return id;
}

function createClientId(prefix = "id") {
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
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

// ── 레벨/스탯 상수 ─────────────────────────────────────────────────────────
// 누적 XP 임계값: key = 그 레벨에 도달하기 위해 필요한 누적 XP. 백엔드 _LEVEL_THRESHOLDS와 일치해야 함.
// 프론트에선 maxXp(progress 바 표시) 계산용으로만 사용 — XP/level 자체는 백엔드 응답을 그대로 반영.
const LEVEL_THRESHOLDS = { 2: 5, 3: 17, 4: 37, 5: 70, 6: 150 };
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

function normalizeHealthNote(note) {
  if (!note) return null;
  return {
    allergens: Array.isArray(note.allergens) ? note.allergens : [],
    cautionFoods: Array.isArray(note.cautionFoods)
      ? note.cautionFoods
      : Array.isArray(note.caution_foods)
        ? note.caution_foods
        : [],
  };
}

// 신규 가입자 기본값 — Lv1, 0 EXP, 뽑기권 0, 하트 1
const FRESH_STATS = { level: 1, currentXp: 0, ticketCount: 0, heartCount: 1 };

export default function App() {
  // ── 화면 상태 ────────────────────────────────────────────────────────────
  const [screen, setScreen] = useState(() =>
    getStoredProfile() ? SCREENS.HOME : SCREENS.LOGIN
  );
  const [screenHistory, setScreenHistory] = useState([]);

  // 화면 이동 헬퍼
  function goTo(next) {
    if (next === screen) return;
    setScreenHistory((h) => [...h, screen]);
    setScreen(next);
  }
  function goBack(fallback = SCREENS.HOME) {
    setScreenHistory((h) => {
      if (h.length === 0) {
        setScreen(fallback);
        return [];
      }
      setScreen(h[h.length - 1]);
      return h.slice(0, -1);
    });
  }
  function resetTo(next) {
    setScreen(next);
    setScreenHistory([]);
  }
  function navHandler(currentScreen) {
    return (key) => {
      const target = NAV_KEY_TO_SCREEN[key];
      if (target) {
        if (target === currentScreen) return;
        goTo(target);
      }
    };
  }

  // ── 인터럽트/오버레이 상태 (어느 화면에서든 뜸) ─────────────────────────
  const [leveledUpTo, setLeveledUpTo] = useState(null);
  const [pendingSignup, setPendingSignup] = useState(null);
  const [signupFarewell, setSignupFarewell] = useState(false);

  // ── 핵심 데이터 상태 ─────────────────────────────────────────────────────
  const [routeHash, setRouteHash] = useState(() =>
    typeof window !== "undefined" ? window.location.hash : ""
  );
  const [profile, setProfile] = useState(getStoredProfile);
  const [mission, setMission] = useState(null);
  const [stats, setStats] = useState({ streak_days: 0, success_dates: [] });
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [pipeline, setPipeline] = useState([]); // 실시간 파이프라인 단계
  const [debugMap, setDebugMap] = useState({});
  const [selectedDebugId, setSelectedDebugId] = useState(null);
  const [sessionId, setSessionId] = useState(getOrCreateSessionId);

  // 로그인/온보딩 폼 상태
  const [loginError, setLoginError] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);
  const [extraInfo, setExtraInfo] = useState(null);
  const [healthNote, setHealthNote] = useState(() => getStoredHealthNote());

  // 레벨/리워드
  const [level, setLevel] = useState(FRESH_STATS.level);
  const [currentXp, setCurrentXp] = useState(FRESH_STATS.currentXp);
  const [maxXp, setMaxXp] = useState(LEVEL_THRESHOLDS[FRESH_STATS.level + 1] ?? 100);
  const [ticketCount, setTicketCount] = useState(FRESH_STATS.ticketCount);
  const [heartCount, setHeartCount] = useState(FRESH_STATS.heartCount);
  const [appStateLoaded, setAppStateLoaded] = useState(false);
  const [missionLoaded, setMissionLoaded] = useState(false);

  useEffect(() => {
    function handleHashChange() {
      setRouteHash(window.location.hash);
    }
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  // ── 스탯 변경 헬퍼 ───────────────────────────────────────────────────────
  // 미션 성공/가챠 보상에 따른 XP/하트 증가는 백엔드가 단독으로 결정함.
  // 프론트는 응답으로 받은 app_state를 setApp State에 반영만 함.

  function applyAppStateFromBackend(s, leveledUp = false) {
    if (!s) return;
    setLevel(s.level);
    setCurrentXp(s.current_xp);
    setMaxXp(LEVEL_THRESHOLDS[s.level + 1] ?? 100);
    setTicketCount(s.ticket_count);
    setHeartCount(s.heart_count);
    if (leveledUp) setLeveledUpTo(s.level);
  }

  async function spendHeart(amount = 1) {
    if (!profile?.student_id || heartCount < amount) return false;
    const result = await adjustHeart(profile.student_id, -amount);
    applyAppStateFromBackend(result.app_state);
    return true;
  }

  async function refundHeart(amount = 1) {
    if (!profile?.student_id) return;
    const result = await adjustHeart(profile.student_id, amount);
    applyAppStateFromBackend(result.app_state);
  }

  // 가챠 한 판 — 백엔드가 보상 결정 + 상태 갱신, 응답을 그대로 반영하고 결과 반환.
  async function handleDraw() {
    if (!profile?.student_id) throw new Error("로그인 필요");
    const result = await claimDrawReward(profile.student_id);
    applyAppStateFromBackend(result.app_state, result.leveled_up);
    return result;
  }

  function refreshMissionData() {
    if (!profile?.student_id) return;
    fetchMissionByStudent(profile.student_id)
      .then(setMission)
      .catch(() => {});
    fetchStudentStats(profile.student_id)
      .then(setStats)
      .catch(() => {});
  }

  // 미션/통계 로드 (프로필 확정 후)
  useEffect(() => {
    if (!profile) {
      setAppStateLoaded(false);
      setMissionLoaded(false);
      return;
    }
    setAppStateLoaded(false);
    setMissionLoaded(false);
    fetchMissionByStudent(profile.student_id)
      .then(setMission)
      .catch(() => setMission({ mission_id: 1, mission_name: "오늘의 미션" }))
      .finally(() => setMissionLoaded(true));
    fetchStudentStats(profile.student_id)
      .then(setStats)
      .catch(() => setStats({ streak_days: 0, success_dates: [] }));
    fetchHealthNote(profile.student_id)
      .then((note) => {
        const normalized = normalizeHealthNote(note);
        setHealthNote(normalized);
        saveHealthNote(normalized);
      })
      .catch(() => {});
    // 출석 체크 — 응답으로 받는 app_state가 (오늘 첫 진입이면 ticket+1 반영된) 최신값.
    // 실패 시 fetchAppState로 fallback.
    claimAttendance(profile.student_id)
      .then((res) => {
        const s = res.app_state;
        setLevel(s.level);
        setCurrentXp(s.current_xp);
        setMaxXp(LEVEL_THRESHOLDS[s.level + 1] ?? 100);
        setTicketCount(s.ticket_count);
        setHeartCount(s.heart_count);
        setAppStateLoaded(true);
      })
      .catch(() => {
        fetchAppState(profile.student_id)
          .then((state) => {
            setLevel(state.level ?? FRESH_STATS.level);
            setCurrentXp(state.current_xp ?? FRESH_STATS.currentXp);
            setMaxXp(LEVEL_THRESHOLDS[state.level + 1] ?? 100);
            setTicketCount(state.ticket_count ?? FRESH_STATS.ticketCount);
            setHeartCount(state.heart_count ?? FRESH_STATS.heartCount);
            setAppStateLoaded(true);
          })
          .catch(() => setAppStateLoaded(true));
      });
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
    setMaxXp(LEVEL_THRESHOLDS[FRESH_STATS.level + 1]);
    setTicketCount(FRESH_STATS.ticketCount);
    setHeartCount(FRESH_STATS.heartCount);
  }

  // ── 인증/온보딩 핸들러 ───────────────────────────────────────────────────
  async function handleSignup({ name, phone4 }) {
    setLoginError("");
    setLoginLoading(true);
    try {
      const student = await verifyStudent(name, phone4);
      const profileResult = await saveProfile(sessionId, student.student_id, student.student_name);
      const assignedMission = profileResult.mission ?? null;
      const saved = { student_id: student.student_id, student_name: student.student_name };
      localStorage.setItem("user_profile", JSON.stringify(saved));
      setProfile(saved);
      if (assignedMission) setMission(assignedMission);
      // 출석 체크는 profile useEffect에서 claimAttendance로 자동 호출됨.
      resetTo(SCREENS.HOME);
    } catch (err) {
      if (err.status === 404) {
        setPendingSignup({ name, phone4 });
        setLoginError("");
        goTo(SCREENS.SIGNUP_CONFIRM);
        return;
      }
      setLoginError(err.message);
    } finally {
      setLoginLoading(false);
    }
  }

  async function handleConfirmSignup() {
    if (!pendingSignup) return;
    setLoginError("");
    setLoginLoading(true);
    try {
      const demo = await registerDemoStudent(pendingSignup.name, pendingSignup.phone4);
      const student = demo.student;
      const profileResult = await saveProfile(sessionId, student.student_id, student.student_name);
      const assignedMission = profileResult.mission ?? demo.mission ?? null;
      const saved = { student_id: student.student_id, student_name: student.student_name };
      localStorage.setItem("user_profile", JSON.stringify(saved));
      setProfile(saved);
      if (assignedMission) setMission(assignedMission);
      resetUserStats();
      setPendingSignup(null);
      resetTo(SCREENS.ONBOARD_INFO);
    } catch (err) {
      setLoginError(err.message);
    } finally {
      setLoginLoading(false);
    }
  }

  function handleCancelSignup() {
    setPendingSignup(null);
    setSignupFarewell(true);
    setLoginError("");
    goTo(SCREENS.SIGNUP_FAREWELL);
    setTimeout(() => {
      setSignupFarewell(false);
      resetTo(SCREENS.LOGIN);
    }, 1200);
  }

  function handleInfoSubmit(info) {
    setExtraInfo(info);
    goTo(SCREENS.ONBOARD_HEALTH);
  }

  async function persistHealthNote(note) {
    const normalized = normalizeHealthNote(note);
    setHealthNote(normalized);
    saveHealthNote(normalized);
    if (profile?.student_id) {
      await saveHealthNoteDb({
        studentId: profile.student_id,
        allergens: normalized.allergens,
        cautionFoods: normalized.cautionFoods,
      });
    }
  }

  async function clearHealthNote() {
    setHealthNote(null);
    saveHealthNote(null);
    if (profile?.student_id) {
      await deleteHealthNote(profile.student_id);
    }
  }

  async function handleHealthSubmit(note) {
    setHealthNote(note);
    saveHealthNote(note);
    try {
      await persistHealthNote(note);
    } catch {}
    goTo(SCREENS.ONBOARD_WELCOME);
  }

  async function handleHealthSkip() {
    try {
      await clearHealthNote();
    } catch {
      setHealthNote(null);
      saveHealthNote(null);
    }
    goTo(SCREENS.ONBOARD_WELCOME);
  }

  function handleWelcomeContinue() {
    // 출석 체크는 profile useEffect에서 claimAttendance로 자동 호출됨 (가입 시 이미 발동).
    resetTo(SCREENS.HOME);
  }

  function handleHealthBack() {
    goBack(SCREENS.ONBOARD_INFO);
  }

  async function handleReset() {
    // 채팅 스트리밍 중이어도 로그아웃은 항상 통과시킴 — 진행 중인 요청은 그냥 버려짐.
    setLoading(false);
    try {
      await clearChatHistory(sessionId);
    } catch {
      // 삭제 실패해도 초기화 진행
    }
    localStorage.removeItem("user_profile");
    // 클라 잔여 캐시(예: 옛 빌드 흔적) 정리만.
    localStorage.removeItem("tommy_lesson_progress");
    localStorage.removeItem("tommy_run_records");
    localStorage.removeItem(HEALTH_NOTE_KEY);
    setSessionId(createSessionId());
    setProfile(null);
    setMission(null);
    setStats({ streak_days: 0, success_dates: [] });
    setMessages([]);
    setDebugMap({});
    setSelectedDebugId(null);
    setLoginError("");
    setPendingSignup(null);
    setSignupFarewell(false);
    setExtraInfo(null);
    setHealthNote(null);
    setLevel(FRESH_STATS.level);
    setCurrentXp(FRESH_STATS.currentXp);
    setMaxXp(LEVEL_THRESHOLDS[FRESH_STATS.level + 1]);
    setTicketCount(FRESH_STATS.ticketCount);
    setHeartCount(FRESH_STATS.heartCount);
    setAppStateLoaded(false);
    setMissionLoaded(false);
    resetTo(SCREENS.LOGIN);
  }

  // ── 채팅 핸들러 ──────────────────────────────────────────────────────────
  async function requestGreeting(missionTitle) {
    setLoading(true);
    try {
      const res = await sendMessage("__GREET__", sessionId, missionTitle);
      const debugId = createClientId("debug");
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
    setPipeline([]);
    const debugId = createClientId("debug");
    let shouldRefreshMissionAfterDone = false;

    setMessages((prev) => [...prev, { role: "assistant", content: "", debugId, streaming: true }]);

    try {
      await sendMessageStream(
        text,
        sessionId,
        mission?.mission_name,
        {
          onPipeline: (stage) => {
            setPipeline((prev) => [...prev, stage]);
            if (stage.stage === "intent") {
              setDebugMap((prev) => ({
                ...prev,
                [debugId]: { ...prev[debugId], intent: stage.value },
              }));
              setSelectedDebugId(debugId);
            }
            if (stage.stage === "qwen") {
              const calls = Array.isArray(stage.calls)
                ? stage.calls
                : stage.fn
                  ? [[stage.fn, stage.args || {}]]
                  : [];
              const [detectedFn, detectedArgs = {}] = calls[0] || [];
              if (
                calls.some(([fn]) =>
                  fn === "request_mission_adjustment" || fn === "cancel_mission_action"
                )
              ) {
                shouldRefreshMissionAfterDone = true;
              }
              setDebugMap((prev) => ({
                ...prev,
                [debugId]: {
                  ...prev[debugId],
                  detected_function: detectedFn,
                  fn_args: detectedArgs,
                  fn_calls: calls,
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
              // 백엔드가 미션 성공 시 XP/티켓 지급 후 새 app_state를 응답에 포함시킴.
              // 프론트는 그 값을 그대로 반영만 함 — 자체 계산 X.
              if (debug.app_state) {
                const s = debug.app_state;
                setLevel(s.level);
                setCurrentXp(s.current_xp);
                setMaxXp(LEVEL_THRESHOLDS[s.level + 1] ?? 100);
                setTicketCount(s.ticket_count);
                setHeartCount(s.heart_count);
                if (debug.reward?.leveled_up) {
                  setLeveledUpTo(s.level);
                }
              }
              if (debug.submit_result?.status === "saved" && profile?.student_id) {
                refreshMissionData();
              }
              setDebugMap((prev) => ({
                ...prev,
                [debugId]: { ...prev[debugId], ...debug },
              }));
              if (
                shouldRefreshMissionAfterDone ||
                debug.fn_args?.adjustment_type ||
                debug.detected_function === "request_mission_adjustment"
              ) {
                refreshMissionData();
              }
            }
          },
        }
      );
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

  // ── 해시 라우트 (디버그 프리뷰 전용 — 화면 상태와 독립) ───────────────────
  const hash = routeHash;
  if (hash.startsWith("#levelup")) {
    const m = hash.match(/=(\d)/);
    const lv = m ? parseInt(m[1], 10) : 2;
    return <LevelUp level={lv} onContinue={() => { window.location.hash = ""; }} />;
  }
  if (hash.startsWith("#ranking")) {
    return <Ranking studentId={profile?.student_id} onNavigate={() => { window.location.hash = ""; }} />;
  }
  if (hash.startsWith("#learn")) {
    return (
      <LearnScreen
        studentId={profile?.student_id}
        todayMission={{ title: mission?.mission_name || "오늘의 미션" }}
        level={level}
        currentXp={currentXp}
        maxXp={maxXp}
        ticketCount={ticketCount}
        heartCount={heartCount}
        onAppStateUpdate={(s) => applyAppStateFromBackend(s)}
        onNavigate={() => { window.location.hash = ""; }}
      />
    );
  }
  if (hash.startsWith("#game")) {
    return (
      <GameScreen
        studentId={profile?.student_id}
        level={level}
        heartCount={heartCount}
        onSpendHeart={() => spendHeart(1)}
        onRefundHeart={() => refundHeart(1)}
        onRecordRun={({ score, durationSec }) =>
          profile?.student_id
            ? recordGameRun({ studentId: profile.student_id, gameType: "run", score, durationSec }).catch(() => null)
            : null
        }
        onNavigate={() => { window.location.hash = ""; }}
      />
    );
  }

  // ── 레벨업 오버레이 (다른 화면보다 우선) ─────────────────────────────────
  if (leveledUpTo) {
    return (
      <LevelUp
        level={leveledUpTo}
        onContinue={() => {
          setLeveledUpTo(null);
          resetTo(SCREENS.HOME);
        }}
      />
    );
  }

  // ── 화면별 렌더 ──────────────────────────────────────────────────────────
  switch (screen) {
    case SCREENS.LOGIN:
      return <Login onStart={() => goTo(SCREENS.SIGNUP)} />;

    case SCREENS.SIGNUP:
    case SCREENS.SIGNUP_CONFIRM:
    case SCREENS.SIGNUP_FAREWELL:
      return (
        <Signup
          onSubmit={handleSignup}
          loading={loginLoading}
          error={loginError}
          pendingSignup={pendingSignup}
          farewell={signupFarewell}
          onConfirmSignup={handleConfirmSignup}
          onCancelSignup={handleCancelSignup}
        />
      );

    case SCREENS.ONBOARD_INFO:
      return <InfoInput onSubmit={handleInfoSubmit} loading={false} error="" />;

    case SCREENS.ONBOARD_HEALTH:
      return (
        <HealthNote
          onSubmit={handleHealthSubmit}
          onSkip={handleHealthSkip}
          onBack={handleHealthBack}
          loading={false}
        />
      );

    case SCREENS.ONBOARD_WELCOME:
      return <Welcome onContinue={handleWelcomeContinue} />;

    case SCREENS.HOME:
      if (profile && (!appStateLoaded || !missionLoaded)) {
        return <AppLoadingScreen active="home" onNavigate={navHandler(SCREENS.HOME)} />;
      }
      return (
        <Home
          studentName={profile?.student_name || "민준"}
          level={level}
          currentXp={currentXp}
          maxXp={maxXp}
          streakDays={stats.streak_days || 0}
          successDates={stats.success_dates || []}
          ticketCount={ticketCount}
          heartCount={heartCount}
          todayMission={{
            title: mission?.mission_name || "오늘의 미션",
            description: mission?.mission_description || mission?.mission_rule || "",
            done: mission?.status === "completed" || mission?.status === "success",
          }}
          onNavigate={navHandler(SCREENS.HOME)}
        />
      );

    case SCREENS.CHAT:
      return (
        <ChatScreen
          onBack={() => goBack(SCREENS.HOME)}
          messages={messages}
          loading={loading}
          onSend={handleSend}
          todayMission={{
            title: mission?.mission_name || "오늘의 미션",
            done: mission?.status === "completed" || mission?.status === "success",
          }}
        />
      );

    case SCREENS.DRAW:
      return (
        <DrawScreen
          level={level}
          currentXp={currentXp}
          maxXp={maxXp}
          ticketCount={ticketCount}
          heartCount={heartCount}
          onDraw={handleDraw}
          onBack={() => goBack(SCREENS.HOME)}
          onNavigate={navHandler(SCREENS.DRAW)}
        />
      );

    case SCREENS.SETTINGS:
      return (
        <Settings
          studentName={profile?.student_name || "민준"}
          level={level}
          heartCount={heartCount}
          streakDays={stats.streak_days || 0}
          onBack={() => goBack(SCREENS.HOME)}
          onOpenHealthNote={() => goTo(SCREENS.SETTINGS_HEALTH_EDIT)}
          onLogout={handleReset}
          onWithdraw={handleReset}
          onNavigate={navHandler(SCREENS.SETTINGS)}
        />
      );

    case SCREENS.SETTINGS_HEALTH_EDIT:
      return (
        <HealthNote
          initialAllergens={healthNote?.allergens || []}
          initialCautionFoods={healthNote?.cautionFoods || []}
          onSubmit={async (note) => {
            try {
              await persistHealthNote(note);
            } catch {
              setHealthNote(note);
              saveHealthNote(note);
            }
            goBack(SCREENS.SETTINGS);
          }}
          onSkip={() => goBack(SCREENS.SETTINGS)}
          onBack={() => goBack(SCREENS.SETTINGS)}
          loading={false}
        />
      );

    case SCREENS.RANKING:
      return (
        <Ranking
          studentId={profile?.student_id}
          onNavigate={navHandler(SCREENS.RANKING)}
        />
      );

    case SCREENS.LEARN:
      return (
        <LearnScreen
          studentId={profile?.student_id}
          todayMission={{ title: mission?.mission_name || "오늘의 미션" }}
          level={level}
          currentXp={currentXp}
          maxXp={maxXp}
          ticketCount={ticketCount}
          heartCount={heartCount}
          onAppStateUpdate={(s) => applyAppStateFromBackend(s)}
          onNavigate={navHandler(SCREENS.LEARN)}
        />
      );

    case SCREENS.GAME:
      return (
        <GameScreen
          studentId={profile?.student_id}
          level={level}
          heartCount={heartCount}
          onSpendHeart={() => spendHeart(1)}
          onRefundHeart={() => refundHeart(1)}
          onRecordRun={({ score, durationSec }) =>
            recordGameRun({ studentId: profile.student_id, gameType: "run", score, durationSec })
              .catch(() => null)
          }
          onNavigate={navHandler(SCREENS.GAME)}
        />
      );

    default:
      return <div style={{ padding: 24 }}>알 수 없는 화면: {screen}</div>;
  }
}
