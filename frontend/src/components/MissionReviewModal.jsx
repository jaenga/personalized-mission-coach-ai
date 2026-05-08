import { useState } from "react";

export default function MissionReviewModal({ open, resultType, onSave, onSkip, loading, error }) {
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");

  if (!open) return null;

  function handleSave(e) {
    e.preventDefault();
    onSave?.({ rating, comment: comment.trim() });
  }

  return (
    <div className="modal-backdrop">
      <form className="review-card" onSubmit={handleSave}>
        <div className="review-tomato">🍅</div>
        <p className="review-kicker">{resultType === "fail" ? "실패도 소중한 기록이에요" : "미션 제출 완료"}</p>
        <h2>오늘의 미션은 어땠나요?</h2>

        <div className="star-row" role="radiogroup" aria-label="미션 별점">
          {[1, 2, 3, 4, 5].map((value) => (
            <button
              key={value}
              type="button"
              className={`star-btn ${value <= rating ? "selected" : ""}`}
              onClick={() => setRating(value)}
              aria-label={`${value}점`}
            >
              ★
            </button>
          ))}
        </div>

        <label className="review-label" htmlFor="mission-review-comment">
          미션에 대하여 자유롭게 평가해주세요!
        </label>
        <textarea
          id="mission-review-comment"
          className="review-textarea"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="어려웠던 점이나 좋았던 점을 적어주세요."
          rows={4}
        />

        {error && <p className="form-error">{error}</p>}

        <div className="modal-actions">
          <button type="button" className="secondary-action" onClick={onSkip} disabled={loading}>
            건너뛰기
          </button>
          <button type="submit" className="primary-action" disabled={loading}>
            {loading ? "저장 중..." : "저장하기"}
          </button>
        </div>
      </form>
    </div>
  );
}
