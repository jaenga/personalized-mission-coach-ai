import { useState } from "react";
import tomatoHi from "../assets/tomato/_shared/hi.png";
import tomatoInd from "../assets/tomato/onboarding/ind.svg";

export default function MissionReviewModal({ open, resultType, missionTitle, onSave, onSkip, loading, error }) {
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");

  if (!open) return null;

  function handleSave(e) {
    e.preventDefault();
    onSave?.({ rating, comment: comment.trim() });
  }

  const isFail = resultType === "fail";

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "center",
        zIndex: 2000,
        padding: "0 0 0 0",
      }}
    >
      <form
        onSubmit={handleSave}
        style={{
          width: "100%",
          background: "#FFF8F4",
          borderRadius: "28px 28px 0 0",
          padding: "0 24px 32px",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
        }}
      >
        {/* 드래그 핸들 */}
        <div style={{ width: 40, height: 4, borderRadius: 2, background: "rgba(0,0,0,0.12)", margin: "12px auto 0" }} />

        {/* 토미 이미지 */}
        <img
          src={tomatoHi}
          alt="토미"
          draggable="false"
          style={{ width: 80, height: 80, objectFit: "contain", marginTop: 12, marginBottom: 4 }}
        />

        {/* 서브타이틀 */}
        <p
          className="font-sejong"
          style={{ fontSize: 12, color: "#E35D49", fontWeight: 700, letterSpacing: "-0.3px", marginBottom: 4 }}
        >
          {isFail ? "실패도 소중한 기록이에요" : (missionTitle || "미션 제출 완료")}
        </p>

        {/* 제목 */}
        <h2
          className="font-sejong"
          style={{ fontSize: 20, fontWeight: 700, color: "#1a1a1a", letterSpacing: "-0.43px", marginBottom: 20, textAlign: "center" }}
        >
          오늘의 미션은 어땠나요?
        </h2>

        {/* 별점 */}
        <div
          role="radiogroup"
          aria-label="미션 별점"
          style={{ display: "flex", gap: 8, marginBottom: 20 }}
        >
          {[1, 2, 3, 4, 5].map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setRating(v)}
              aria-label={`${v}점`}
              style={{
                width: 44,
                height: 44,
                borderRadius: "50%",
                border: "none",
                background: v <= rating ? "#FFF0EC" : "#F0EDE9",
                cursor: "pointer",
                transition: "all 0.15s ease",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                padding: 6,
              }}
            >
              <img
                src={tomatoInd}
                alt={`${v}점`}
                draggable="false"
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "contain",
                  opacity: v <= rating ? 1 : 0.25,
                  transition: "opacity 0.15s ease",
                }}
              />
            </button>
          ))}
        </div>

        {/* 텍스트 입력 */}
        <div style={{ width: "100%", marginBottom: 8 }}>
          <label
            htmlFor="mission-review-comment"
            className="font-sejong"
            style={{ fontSize: 13, fontWeight: 700, color: "#4a4642", letterSpacing: "-0.3px", display: "block", marginBottom: 8 }}
          >
            미션에 대해 자유롭게 적어주세요
          </label>
          <textarea
            id="mission-review-comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="어려웠던 점이나 좋았던 점을 적어주세요."
            rows={3}
            className="font-sejong"
            style={{
              width: "100%",
              borderRadius: 16,
              border: "1.5px solid rgba(227, 93, 73, 0.2)",
              background: "#FFFFFF",
              padding: "12px 14px",
              fontSize: 13,
              color: "#1a1a1a",
              letterSpacing: "-0.3px",
              lineHeight: "19px",
              resize: "none",
              outline: "none",
              boxSizing: "border-box",
              fontFamily: "SejongGeulggot, sans-serif",
            }}
          />
        </div>

        {error && (
          <p className="font-sejong" style={{ fontSize: 12, color: "#E35D49", marginBottom: 8, alignSelf: "flex-start" }}>
            {error}
          </p>
        )}

        {/* 버튼 */}
        <div style={{ display: "flex", gap: 10, width: "100%", marginTop: 8 }}>
          <button
            type="button"
            onClick={onSkip}
            disabled={loading}
            className="font-sejong"
            style={{
              flex: "1 1 0",
              height: 48,
              borderRadius: 999,
              border: "none",
              background: "#ECEAE7",
              color: "#5a5754",
              fontSize: 15,
              fontWeight: 400,
              letterSpacing: "-0.43px",
              cursor: "pointer",
            }}
          >
            건너뛰기
          </button>
          <button
            type="submit"
            disabled={loading}
            className="font-sejong"
            style={{
              flex: "1 1 0",
              height: 48,
              borderRadius: 999,
              border: "none",
              background: "#E35D49",
              color: "#FFFFFF",
              fontSize: 16,
              fontWeight: 400,
              letterSpacing: "-0.43px",
              cursor: "pointer",
              boxShadow: "0 4px 14px rgba(227,93,73,0.3)",
              opacity: loading ? 0.6 : 1,
            }}
          >
            {loading ? "저장 중..." : "저장하기"}
          </button>
        </div>
      </form>
    </div>
  );
}
