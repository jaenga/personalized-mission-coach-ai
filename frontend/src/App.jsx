import { useEffect, useRef, useState } from "react";
import { verifyStudent, saveProfile, registerDemoStudent, fetchMissionByStudent, sendMessage, sendMessageStream, fetchChatHistory, clearChatHistory, resolveMissionUiAction, fetchActiveUiAction, saveMissionReview, saveOnboardingPreferences } from "./api.js";
import ChatWindow from "./components/ChatWindow.jsx";
import DebugPanel from "./components/DebugPanel.jsx";
import MissionReviewModal from "./components/MissionReviewModal.jsx";
import OnboardingPreferences from "./components/OnboardingPreferences.jsx";

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
  const [pipeline, setPipeline] = useState([]); // 실시간 파이프라인 단계
  const [debugMap, setDebugMap] = useState({});
  const [selectedDebugId, setSelectedDebugId] = useState(null);
  const [sessionId, setSessionId] = useState(getOrCreateSessionId);
  const [profile, setProfile] = useState(getStoredProfile);
  const [profileSynced, setProfileSynced] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const greetingRequestedRef = useRef(false);
  const syncedProfileKeyRef = useRef(null);
  const loadedHistoryKeyRef = useRef(null);
  const [showOnboardingPreferences, setShowOnboardingPreferences] = useState(false);
  const [onboardingSaving, setOnboardingSaving] = useState(false);
  const [onboardingError, setOnboardingError] = useState("");
  const [reviewModal, setReviewModal] = useState(null);
  const [reviewSaving, setReviewSaving] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [toastMessage, setToastMessage] = useState("");

  // 로그인 화면용 상태
  const [loginForm, setLoginForm] = useState({ name: "", phone4: "" });
  const [loginError, setLoginError] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);
  const [signupPopupOpen, setSignupPopupOpen] = useState(false);
  const [farewellMessage, setFarewellMessage] = useState("");

  useEffect(() => {
    if (!profile?.student_id) {
      setShowOnboardingPreferences(false);
      return;
    }
    const key = `onboarding_preferences_done:${profile.student_id}`;
    setShowOnboardingPreferences(profileSynced && localStorage.getItem(key) !== "true");
    setOnboardingError("");
  }, [profile?.student_id, profileSynced]);

  useEffect(() => {
    if (!toastMessage) return;
    const timer = setTimeout(() => setToastMessage(""), 1800);
    return () => clearTimeout(timer);
  }, [toastMessage]);

  // 로컬 프로필을 백엔드 세션 매핑과 동기화
  useEffect(() => {
    if (!profile?.student_id) {
      setProfileSynced(false);
      return;
    }

    const profileKey = `${sessionId}:${profile.student_id}:${profile.student_name}`;
    if (syncedProfileKeyRef.current === profileKey) {
      setProfileSynced(true);
      return;
    }

    let cancelled = false;
    setProfileSynced(false);
    setHistoryLoaded(false);

    saveProfile(sessionId, profile.student_id, profile.student_name)
      .then((result) => {
        if (cancelled) return;
        syncedProfileKeyRef.current = profileKey;
        if (result.mission) {
          setMission(result.mission);
        }
        setProfileSynced(true);
      })
      .catch(() => {
        if (cancelled) return;
        setProfileSynced(true);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId, profile?.student_id, profile?.student_name]);

  // 미션 로드 (프로필 확정 후)
  useEffect(() => {
    if (!profile || !profileSynced) return;
    fetchMissionByStudent(profile.student_id)
      .then(setMission)
      .catch(() => setMission({ mission_id: 1, mission_name: "오늘의 미션" }));
  }, [profile, profileSynced]);

  // 채팅 히스토리 로드
  useEffect(() => {
    if (!profile?.student_id) {
      setHistoryLoaded(false);
      return;
    }
    if (!profileSynced) {
      setHistoryLoaded(false);
      return;
    }

    const historyKey = `${sessionId}:${profile.student_id}`;
    if (loadedHistoryKeyRef.current === historyKey) return;
    loadedHistoryKeyRef.current = historyKey;
    setHistoryLoaded(false);

    let cancelled = false;
    fetchChatHistory(sessionId)
      .then(async (history) => {
        if (cancelled) return;
        if (history.length === 0) {
          setMessages([]);
          greetingRequestedRef.current = false;
        } else {
          greetingRequestedRef.current = true;
          const mapped = history.map((msg, i) =>
            msg.role === "assistant" ? { ...msg, debugId: `hist-${i}` } : msg
          );
          // 새로고침 후 버튼 복구: active ui_action이 있으면 마지막 assistant 메시지에 붙인다
          try {
            const activeUiAction = await fetchActiveUiAction(sessionId);
            if (activeUiAction) {
              const lastAssistantIdx = [...mapped].map((m, i) => ({ m, i })).filter(({ m }) => m.role === "assistant").at(-1)?.i;
              if (lastAssistantIdx !== undefined) {
                mapped[lastAssistantIdx] = { ...mapped[lastAssistantIdx], ui_action: activeUiAction };
              }
            }
          } catch {}
          setMessages(mapped);
        }
        setHistoryLoaded(true);
      })
      .catch(() => {
        if (cancelled) return;
        setMessages([{ role: "assistant", content: "코치에 연결할 수 없어요. 잠시 후 다시 시도해 봐!" }]);
        setHistoryLoaded(true);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId, profile?.student_id, profileSynced]);

  useEffect(() => {
    if (!profile || !mission) return;
    if (!historyLoaded) return;
    if (messages.length > 0) return;
    if (greetingRequestedRef.current) return;

    greetingRequestedRef.current = true;
    requestGreeting(mission);
  }, [profile?.student_id, mission?.mission_id, historyLoaded, messages.length]);

  async function handleLogin(e) {
    e.preventDefault();
    setLoginError("");
    setFarewellMessage("");
    setLoginLoading(true);
    try {
      const student = await verifyStudent(loginForm.name.trim(), loginForm.phone4.trim());
      const saved = { student_id: student.student_id, student_name: student.student_name };
      localStorage.setItem("user_profile", JSON.stringify(saved));
      syncedProfileKeyRef.current = null;
      loadedHistoryKeyRef.current = null;
      setProfileSynced(false);
      setHistoryLoaded(false);
      setProfile(saved);
    } catch (err) {
      if (err.status === 404 || err.message.includes("일치하는 학생")) {
        setSignupPopupOpen(true);
      } else {
        setLoginError(err.message);
      }
    } finally {
      setLoginLoading(false);
    }
  }

  async function handleSignupAgree() {
    setLoginError("");
    setFarewellMessage("");
    setLoginLoading(true);

    try {
      const result = await registerDemoStudent(loginForm.name.trim(), loginForm.phone4.trim());
      const student = result.student;

      const saved = { student_id: student.student_id, student_name: student.student_name };
      localStorage.setItem("user_profile", JSON.stringify(saved));
      setSignupPopupOpen(false);
      syncedProfileKeyRef.current = null;
      loadedHistoryKeyRef.current = null;
      setProfileSynced(false);
      setHistoryLoaded(false);
      setProfile(saved);

      if (result.mission) {
        setMission(result.mission);
      }
    } catch (err) {
      setLoginError(err.message);
      setSignupPopupOpen(false);
    } finally {
      setLoginLoading(false);
    }
  }

  function handleSignupCancel() {
    setSignupPopupOpen(false);
    setFarewellMessage("다음에 만나요!");

    setTimeout(() => {
      setFarewellMessage("");
      setLoginForm({ name: "", phone4: "" });
      setLoginError("");
    }, 1200);
  }

  async function handleReset() {
    if (loading) return;
    try {
      await clearChatHistory(sessionId);
    } catch {
      // 삭제 실패해도 초기화
    }
    greetingRequestedRef.current = false;
    syncedProfileKeyRef.current = null;
    setHistoryLoaded(false);
    setProfileSynced(false);
    localStorage.removeItem("user_profile");
    setSessionId(createSessionId());
    loadedHistoryKeyRef.current = null;
    setProfile(null);
    setMission(null);
    setMessages([]);
    setDebugMap({});
    setSelectedDebugId(null);
    setLoginForm({ name: "", phone4: "" });
    setLoginError("");
    setSignupPopupOpen(false);
    setFarewellMessage("");
    setShowOnboardingPreferences(false);
    setReviewModal(null);
    setToastMessage("");
  }

  async function handleSaveOnboardingPreferences(values) {
    if (!profile?.student_id) return;
    if (!profileSynced) {
      setOnboardingError("프로필을 준비하는 중이에요. 잠시 후 다시 눌러주세요.");
      return;
    }
    setOnboardingSaving(true);
    setOnboardingError("");
    try {
      await saveOnboardingPreferences({
        session_id: sessionId,
        preferred_activity_keys: values.preferred_activity_keys,
        disliked_activity_keys: values.disliked_activity_keys,
        restrictions: values.restrictions,
      });
      localStorage.setItem(`onboarding_preferences_done:${profile.student_id}`, "true");
      setShowOnboardingPreferences(false);
      setToastMessage("선호 정보가 저장됐어요!");
    } catch (err) {
      setOnboardingError(err.message);
    } finally {
      setOnboardingSaving(false);
    }
  }

  function handleSkipOnboardingPreferences() {
    if (profile?.student_id) {
      localStorage.setItem(`onboarding_preferences_done:${profile.student_id}`, "true");
    }
    setShowOnboardingPreferences(false);
    setOnboardingError("");
  }

  async function handleSaveMissionReview({ rating, comment }) {
    const missionId = reviewModal?.missionId ?? mission?.mission_id;
    if (!missionId) {
      setReviewError("미션 정보를 찾지 못했어요. 잠시 후 다시 시도해주세요.");
      return;
    }
    setReviewSaving(true);
    setReviewError("");
    try {
      await saveMissionReview({
        session_id: sessionId,
        mission_id: missionId,
        rating,
        comment,
      });
      setReviewModal(null);
      setToastMessage("평가가 저장됐어요!");
    } catch (err) {
      setReviewError(err.message);
    } finally {
      setReviewSaving(false);
    }
  }

  function handleSkipMissionReview() {
    setReviewModal(null);
    setReviewError("");
  }

  async function requestGreeting(currentMission) {
    if (currentMission?.mission_message) {
      setMessages([{ role: "assistant", content: currentMission.mission_message }]);
      return;
    }

    setLoading(true);
    try {
      const res = await sendMessage("__GREET__", sessionId, currentMission?.mission_name);
      const debugId = crypto.randomUUID();
      setMessages([{ role: "assistant", content: res.response, debugId }]);
      setDebugMap({ [debugId]: { ...res.debug } });
      setSelectedDebugId(debugId);

      // 미션 재조회
      if (profile?.student_id) {
        fetchMissionByStudent(profile.student_id)
          .then(setMission)
          .catch(() => {});
      }
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
              const firstCall = stage.calls?.[0];
              setDebugMap((prev) => ({
                ...prev,
                [debugId]: {
                  ...prev[debugId],
                  detected_function: firstCall?.[0] ?? null,
                  fn_args: firstCall?.[1] ?? {},
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
          onDone: (debug, uiAction, doneInfo) => {
            if (debug) {
              setDebugMap((prev) => ({
                ...prev,
                [debugId]: { ...prev[debugId], ...debug },
              }));
            }
            if (uiAction) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.debugId === debugId ? { ...m, ui_action: uiAction } : m
                )
              );
            }
            if (doneInfo?.mission_result_submitted === true) {
              const reviewMissionId = doneInfo.mission_id ?? mission?.mission_id;
              if (reviewMissionId) {
                setReviewModal({
                  missionId: reviewMissionId,
                  resultType: doneInfo.mission_result_type,
                });
                setReviewError("");
              }
            }
            if (profile?.student_id) {
              fetchMissionByStudent(profile.student_id)
                .then(setMission)
                .catch(() => {});
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

  // 버튼 대기 중이면 입력창 잠금
  const lockChat = messages.some(
    (m) => m.ui_action?.lock_chat && m.ui_action?.buttons?.length > 0
  );

  async function handleMissionUiAction(actionId, value) {
    // 버튼 즉시 비활성화 (해당 메시지의 ui_action을 resolving 상태로 표시)
    setMessages((prev) =>
      prev.map((m) =>
        m.ui_action?.action_id === actionId ? { ...m, ui_action: { ...m.ui_action, resolving: true } } : m
      )
    );
    setLoading(true);

    try {
      const res = await resolveMissionUiAction(actionId, sessionId, value);
      // 버튼 제거
      setMessages((prev) =>
        prev.map((m) =>
          m.ui_action?.action_id === actionId ? { ...m, ui_action: null } : m
        )
      );
      // 새 응답 메시지 추가
      const newDebugId = crypto.randomUUID();
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: res.response, debugId: newDebugId, ui_action: res.ui_action ?? null },
      ]);
      setDebugMap((prev) => ({ ...prev, [newDebugId]: res.debug ?? {} }));
      setSelectedDebugId(newDebugId);

      if (profile?.student_id) {
        fetchMissionByStudent(profile.student_id).then(setMission).catch(() => {});
      }
    } catch (err) {
      // 만료(410) → 버튼 제거 + 안내
      setMessages((prev) =>
        prev.map((m) =>
          m.ui_action?.action_id === actionId ? { ...m, ui_action: null } : m
        )
      );
      if (err.status === 410) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "선택지가 만료됐어. 다시 말해줄래?", ui_action: null },
        ]);
      }
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
          {farewellMessage && (
            <p className="farewell-message">{farewellMessage}</p>
          )}

          {signupPopupOpen && (
            <div className="signup-modal-backdrop">
              <div className="signup-modal">
                <h3>회원가입 하기</h3>
                <p>
                  아직 등록된 친구가 아니야.<br />
                  지금 바로 회원가입하고 오늘의 미션을 받아볼래?
                </p>

                <div className="signup-modal-actions">
                  <button
                    type="button"
                    className="signup-yes-btn"
                    onClick={handleSignupAgree}
                    disabled={loginLoading}
                  >
                    좋아요
                  </button>

                  <button
                    type="button"
                    className="signup-no-btn"
                    onClick={handleSignupCancel}
                    disabled={loginLoading}
                  >
                    안할래요
                  </button>
                </div>
              </div>
            </div>
          )}
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
          <div>
            🎯 오늘 미션: <strong>{mission.mission_name}</strong>
          </div>
          {mission.mission_message && (
            <p className="mission-banner-message">{mission.mission_message}</p>
          )}
        </div>
      )}

      <div className="main-area">
        <div className="chat-area">
          <ChatWindow
            messages={messages}
            onSend={handleSend}
            loading={loading}
            lockChat={lockChat}
            onMissionUiAction={handleMissionUiAction}
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
                      ⚡ Qwen → <strong>{s.calls?.[0]?.[0] ?? "없음"}</strong> <em>({s.ms}ms)</em>
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

      {toastMessage && <div className="toast-message">{toastMessage}</div>}

      {showOnboardingPreferences && (
        <OnboardingPreferences
          onSubmit={handleSaveOnboardingPreferences}
          onSkip={handleSkipOnboardingPreferences}
          loading={onboardingSaving}
          error={onboardingError}
        />
      )}

      <MissionReviewModal
        open={!!reviewModal}
        resultType={reviewModal?.resultType}
        onSave={handleSaveMissionReview}
        onSkip={handleSkipMissionReview}
        loading={reviewSaving}
        error={reviewError}
      />
    </div>
  );
}
