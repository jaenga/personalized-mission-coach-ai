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
 * 백그라운드 분석 결과 폴링.
 * @returns {object|null} 준비됐으면 결과 객체, 아직이면 null
 */
export async function fetchAnalysis(analysisId) {
  const res = await fetch(`/analysis/${analysisId}`);
  if (res.status === 202) return null;
  if (!res.ok) throw new Error("분석 조회 실패");
  return res.json();
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
