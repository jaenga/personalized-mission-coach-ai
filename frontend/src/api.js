/**
 * 백엔드 API 호출 모듈.
 * Vite proxy 덕분에 상대경로 그대로 사용 가능.
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
          onDone?.(data.debug);
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

/** 이름 + 전화번호 뒷 4자리로 학생 본인 확인. */
export async function verifyStudent(studentName, phoneLast4) {
  const res = await fetch("/verify-student", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ student_name: studentName, phone_last4: phoneLast4 }),
  });
  if (res.status === 404) throw new Error("일치하는 학생을 찾을 수 없어요.");
  if (!res.ok) throw new Error("확인 중 오류가 발생했어요.");
  return res.json();
}

/** 유저 프로필(student_id, student_name) 저장. */
export async function saveProfile(sessionId, studentId, studentName) {
  const res = await fetch("/profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, student_id: studentId, student_name: studentName }),
  });
  if (!res.ok) throw new Error("프로필 저장 실패");
  return res.json();
}

/** 학생 미션 조회. */
export async function fetchMissionByStudent(studentId) {
  const res = await fetch(`/mission?student_id=${studentId}`);
  if (!res.ok) throw new Error("미션 불러오기 실패");
  return res.json();
}
