/**
 * 백엔드 API 호출 모듈
 * Vite proxy 덕분에 상대경로 그대로 사용 가능
 */

export async function fetchMission() {
  const res = await fetch("/mission");
  if (!res.ok) throw new Error("미션 불러오기 실패");
  return res.json();
}

/**
 * 채팅 메시지 전송.
 * @param {string} message  사용자 메시지 (또는 "__GREET__")
 * @param {string} sessionId  세션 UUID
 * @param {string|null} [mission]  오늘의 미션 제목
 * @returns {{ response: string, analysis_id: string, debug: object }}
 */
export async function sendMessage(message, sessionId, mission = null) {
  const res = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId, mission }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "메시지 전송 실패");
  }
  return res.json();
}

/**
 * 채팅 스트리밍 전송.
 * onToken(token): 토큰 수신 시 호출
 * onPipeline(stage): 파이프라인 단계 이벤트 수신 시 호출
 */
export async function sendMessageStream(message, sessionId, mission = null, { onToken, onPipeline, onDone } = {}) {
  const res = await fetch("/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId, mission }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "메시지 전송 실패");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        const data = JSON.parse(line.slice(6));
        if (data.type === "pipeline") {
          onPipeline?.(data);
        } else if (data.type === "token") {
          onToken?.(data.content);
        } else if (data.type === "done") {
          onDone?.(data.debug, data.ui_action ?? null, {
            mission_result_submitted: data.mission_result_submitted === true,
            mission_result_type: data.mission_result_type ?? null,
            mission_id: data.mission_id ?? null,
          });
        }
      } catch {}
    }
  }
}

/** 세션의 대화 히스토리 조회. */
export async function fetchChatHistory(sessionId) {
  const res = await fetch(`/chat/${sessionId}`);
  if (!res.ok) throw new Error("대화 기록 불러오기 실패");
  return res.json();
}

/** 세션의 대화 히스토리 삭제. */
export async function clearChatHistory(sessionId) {
  const res = await fetch(`/chat/${sessionId}`, { method: "DELETE" });
  if (!res.ok) throw new Error("대화 초기화 실패");
  return res.json();
}

/** 탈퇴: 학생 본인과 학생을 참조하는 모든 데이터 삭제. */
export async function deleteStudentAccount(studentId) {
  const res = await fetch(`/students/${studentId}`, { method: "DELETE" });
  if (!res.ok) throw new Error("탈퇴 처리 실패");
  return res.json();
}

/** 이름 + 전화번호 뒷 4자리로 학생 본인 확인. */
export async function verifyStudent(studentName, phoneLast4) {
  const res = await fetch("/verify-student", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ student_name: studentName, phone_last4: phoneLast4 }),
  });
  if (res.status === 404) {
    const err = new Error("일치하는 학생을 찾을 수 없어요.");
    err.status = 404;
    throw err;
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "확인 중 오류가 발생했어요.");
  }
  return res.json();
}

export async function fetchStudentStats(studentId) {
  const res = await fetch(`/stats/${studentId}`);
  if (!res.ok) throw new Error("통계 불러오기 실패");
  return res.json();
}

export async function fetchWeeklySharePrompt(studentId) {
  const res = await fetch(`/weekly-share/${studentId}`);
  if (!res.ok) throw new Error("주간 공유 팝업을 불러오지 못했어요.");
  return res.json();
}

export async function markWeeklySharePrompt({ studentId, weekStart, action }) {
  const res = await fetch("/weekly-share/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      student_id: studentId,
      week_start: weekStart,
      action,
    }),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail ?? "주간 공유 상태를 저장하지 못했어요.");
  }
  return res.json();
}

export async function fetchAppState(studentId) {
  const res = await fetch(`/app-state/${studentId}`);
  if (!res.ok) throw new Error("상태 불러오기 실패");
  return res.json();
}

export async function adjustHeart(studentId, delta) {
  const res = await fetch(`/app-state/${studentId}/heart`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ delta }),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail ?? "하트 변경 실패");
  }
  return res.json();
}

/**
 * 가챠 한 판. 백엔드가 보상 굴림 + 상태 갱신 + history 기록.
 * Returns { reward, app_state, leveled_up, level_after, xp_gain, heart_gain, ticket_gain, first_of_day }
 */
export async function claimDrawReward(studentId) {
  const res = await fetch(`/draw/reward/${studentId}`, { method: "POST" });
  if (res.status === 409) {
    const err = new Error("뽑기권이 부족해요.");
    err.status = 409;
    throw err;
  }
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail ?? "뽑기 실패");
  }
  return res.json();
}

/**
 * 출석 체크인. 오늘 첫 진입이면 ticket +1, 두 번째 이후는 no-op.
 * Returns { first_check_in, ticket_awarded, app_state }
 */
export async function claimAttendance(studentId) {
  const res = await fetch(`/attendance/check-in/${studentId}`, { method: "POST" });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail ?? "출석 체크 실패");
  }
  return res.json();
}

/**
 * 경험치 랭킹. xp_history 기간 합계 기준.
 * @param {"week"|"month"} period
 * Returns [{rank, student_id, student_name, level, period_xp}, ...]
 */
export async function fetchXpRanking(period = "week") {
  const res = await fetch(`/ranking/xp?period=${encodeURIComponent(period)}`);
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail ?? "랭킹 불러오기 실패");
  }
  return res.json();
}

/** 게임 한 판 기록. Returns inserted run row. */
export async function recordGameRun({ studentId, gameType, score, durationSec = 0 }) {
  const res = await fetch("/game/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      student_id: studentId,
      game_type: gameType,
      score,
      duration_sec: durationSec,
    }),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail ?? "게임 기록 저장 실패");
  }
  return res.json();
}

/**
 * 게임 랭킹. game_runs 기간 MAX(score) 기준.
 * @param {"week"|"month"|"all"} period
 * @param {string} [gameType]  특정 게임만 필터 (생략 시 전체)
 * Returns [{rank, student_id, student_name, level, best_score, plays}, ...]
 */
export async function fetchGameRanking(period = "week", gameType) {
  const params = new URLSearchParams({ period });
  if (gameType) params.set("game_type", gameType);
  const res = await fetch(`/ranking/game?${params}`);
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail ?? "게임 랭킹 불러오기 실패");
  }
  return res.json();
}

/** 학생의 모든 lesson 진행도 조회. Returns [{lesson_id, current_step, edu_done, quiz_done, ...}, ...] */
export async function fetchLessonProgress(studentId) {
  const res = await fetch(`/lessons/progress/${studentId}`);
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail ?? "학습 진행도 불러오기 실패");
  }
  return res.json();
}

/**
 * lesson 진행도 부분 업데이트 (current_step / edu_done / quiz_done).
 * 생략한 필드는 기존 값 유지.
 */
export async function updateLessonProgress({ studentId, lessonId, currentStep, eduDone, quizDone }) {
  const body = { student_id: studentId, lesson_id: lessonId };
  if (currentStep !== undefined) body.current_step = currentStep;
  if (eduDone !== undefined) body.edu_done = eduDone;
  if (quizDone !== undefined) body.quiz_done = quizDone;
  const res = await fetch("/lessons/progress", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail ?? "학습 진행도 저장 실패");
  }
  return res.json();
}

/**
 * 퀴즈 완료. 첫 완료면 ticket +1 지급.
 * Returns { progress, app_state, first_completion, ticket_awarded }
 */
export async function completeLessonQuiz({ studentId, lessonId, quizScore }) {
  const body = { student_id: studentId, lesson_id: lessonId };
  if (quizScore !== undefined) body.quiz_score = quizScore;
  const res = await fetch("/lessons/quiz-complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail ?? "퀴즈 완료 처리 실패");
  }
  return res.json();
}

/** 유저 프로필(student_id, student_name) 저장. */
export async function fetchHealthNote(studentId) {
  const res = await fetch(`/health-note/${studentId}`);
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail ?? "건강노트 불러오기 실패");
  }
  return res.json();
}

export async function saveHealthNoteDb({ studentId, allergens = [], cautionFoods = [] }) {
  const res = await fetch("/health-note", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      student_id: studentId,
      allergens,
      caution_foods: cautionFoods,
    }),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail ?? "건강노트 저장 실패");
  }
  return res.json();
}

export async function deleteHealthNote(studentId) {
  const res = await fetch(`/health-note/${studentId}`, { method: "DELETE" });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.detail ?? "건강노트 삭제 실패");
  }
  return res.json();
}

export async function registerDemoStudent(studentName, phoneLast4) {
  const res = await fetch("/demo-register-student", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ student_name: studentName, phone_last4: phoneLast4 }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "회원가입에 실패했어요.");
  }
  return res.json();
}

export async function saveProfile(sessionId, studentId, studentName) {
  const res = await fetch("/profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, student_id: studentId, student_name: studentName }),
  });
  if (!res.ok) throw new Error("프로필 저장 실패");
  return res.json();
}

/** 현재 세션의 active UI action 조회 (새로고침 후 버튼 복구용). */
export async function fetchActiveUiAction(sessionId) {
  const res = await fetch(`/mission-ui-actions/active?session_id=${sessionId}`);
  if (!res.ok) return null;
  const data = await res.json();
  return data.ui_action ?? null;
}

/** 미션 UI 액션 버튼 resolve. */
export async function resolveMissionUiAction(actionId, sessionId, value) {
  const res = await fetch(`/mission-ui-actions/${actionId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, value }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const error = new Error(err.detail?.reason ?? "버튼 처리 실패");
    error.status = res.status;
    throw error;
  }
  return res.json();
}

/** 학생 미션 조회. */
export async function saveMissionReview({ session_id, mission_id, rating, comment }) {
  const res = await fetch("/mission-review", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id, mission_id, rating, comment }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "미션 평가 저장에 실패했어요");
  }
  return res.json();
}

export async function saveOnboardingPreferences({
  session_id,
  preferred_activity_keys,
  disliked_activity_keys,
  restrictions,
}) {
  const res = await fetch("/onboarding-preferences", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id,
      preferred_activity_keys,
      disliked_activity_keys,
      restrictions,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "선호 정보 저장에 실패했어요");
  }
  return res.json();
}

export async function fetchMissionByStudent(studentId) {
  const res = await fetch(`/mission?student_id=${studentId}`);
  if (!res.ok) throw new Error("미션 불러오기 실패");
  return res.json();
}
