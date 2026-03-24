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
 * @param {string} params.mission
 * @param {string} params.result           "success" | "partial" | "failure"
 * @param {string|null} [params.reason]
 * @param {string} [params.prompt_version] 기본값 "v1"
 * @param {string|null} [params.expected_label]
 * @param {string|null} [params.memo]
 */
export async function submitFeedback({
  mission,
  result,
  reason,
  prompt_version,
  expected_label,
  memo,
}) {
  const res = await fetch("/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mission,
      result,
      reason: reason ?? null,
      prompt_version: prompt_version ?? "v1",
      expected_label: expected_label ?? null,
      memo: memo ?? null,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "피드백 제출 실패");
  }
  return res.json(); // { id, ai_response }
}

export async function fetchLogs(limit = 50) {
  const res = await fetch(`/logs?limit=${limit}`);
  if (!res.ok) throw new Error("기록 불러오기 실패");
  return res.json();
}

/**
 * 특정 로그에 리뷰 라벨을 저장한다.
 * @param {number} id
 * @param {{ quality_label?: string, failure_type?: string, reviewer_note?: string }} body
 */
export async function patchReview(id, { quality_label, failure_type, reviewer_note }) {
  const res = await fetch(`/logs/${id}/review`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      quality_label: quality_label || null,
      failure_type:  failure_type  || null,
      reviewer_note: reviewer_note || null,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "리뷰 저장 실패");
  }
  return res.json(); // { ok: true, id }
}
