import { useMemo, useState } from "react";
import ticket from "../assets/tomato/_shared/ticket.png";
import yaho from "../assets/tomato/draw/yaho.png";

/* ─────────────────────────────────────────────────────────
   퀴즈 모달
   - 5문제 큐로 관리: 오답이면 큐 끝으로 push, 모두 정답이면 완료
   - type: "multiple"(보기 4개) | "ox"(O/X)
   ───────────────────────────────────────────────────────── */
export default function QuizModal({ lesson, onClose, onComplete }) {
  // 문제 인덱스 큐 (원래 순서대로 시작)
  const initial = useMemo(() => lesson.quiz.map((_, i) => i), [lesson]);
  const [queue, setQueue] = useState(initial);
  const [picked, setPicked] = useState(null);   // 사용자 선택값
  const [revealed, setRevealed] = useState(false); // 정답 공개 상태
  const [solvedCount, setSolvedCount] = useState(0); // 누적 정답 개수 (진행도용)
  const [done, setDone] = useState(false);

  const totalQuestions = lesson.quiz.length;
  const currentIdx = queue[0];
  const q = currentIdx != null ? lesson.quiz[currentIdx] : null;

  const isCorrect = (() => {
    if (!q || picked == null) return false;
    if (q.type === "ox") return picked === q.answer;
    return picked === q.answer;
  })();

  function handlePick(value) {
    if (revealed) return;
    setPicked(value);
    setRevealed(true);
  }

  function handleNext() {
    if (!q) return;
    const correct = isCorrect;
    let nextQueue;
    if (correct) {
      nextQueue = queue.slice(1);
      setSolvedCount((c) => c + 1);
    } else {
      // 오답이면 끝으로 보내기
      nextQueue = [...queue.slice(1), currentIdx];
    }
    setQueue(nextQueue);
    setPicked(null);
    setRevealed(false);
    if (nextQueue.length === 0) {
      setDone(true);
      onComplete?.({ rewards: { tickets: 1 } });
    }
  }

  // 완료 화면
  if (done || !q) {
    return (
      <ModalShell onClose={onClose}>
        <div className="flex flex-col items-center" style={{ padding: "32px 22px" }}>
          <img
            src={yaho}
            alt=""
            draggable="false"
            className="select-none pointer-events-none"
            style={{ width: 130, height: 130, objectFit: "contain" }}
          />
          <div
            className="font-jeju"
            style={{ fontSize: 30, color: "#E35D49", letterSpacing: "-0.43px", marginTop: 8 }}
          >
            퀴즈 완료!
          </div>
          <div
            className="font-sejong"
            style={{ fontSize: 14, color: "#1f1f1f", letterSpacing: "-0.43px", marginTop: 6, textAlign: "center" }}
          >
            모든 문제를 다 맞혔어요!<br />보상으로 뽑기권 1개를 받았어요 🎁
          </div>
          <div
            className="flex items-center font-sejong"
            style={{
              marginTop: 18,
              background: "rgba(255, 218, 137, 0.4)",
              borderRadius: 999,
              paddingInline: 16,
              height: 38,
              gap: 8,
              border: "1px solid rgba(232, 181, 61, 0.45)",
              fontSize: 16,
              fontWeight: 700,
              color: "#E35D49",
              letterSpacing: "-0.43px",
            }}
          >
            <img src={ticket} alt="" style={{ width: 22, height: 22 }} />
            +1
          </div>
          <button
            type="button"
            onClick={onClose}
            className="signup-submit font-sejong text-white shadow-md transition-all flex items-center justify-center"
            style={{
              marginTop: 22,
              width: "100%",
              height: 48,
              borderRadius: 999,
              background: "#E35D49",
              fontSize: 16,
              fontWeight: 500,
              border: "none",
              padding: 0,
              letterSpacing: "-0.43px",
            }}
          >
            완료
          </button>
        </div>
      </ModalShell>
    );
  }

  return (
    <ModalShell onClose={onClose}>
      {/* 진행도 */}
      <div
        className="flex items-center justify-between font-sejong"
        style={{ padding: "16px 22px 8px", color: "#75726e", fontSize: 12, letterSpacing: "-0.43px" }}
      >
        <span>맞힌 문제 {solvedCount} / {totalQuestions}</span>
        <span>남은 문제 {queue.length}</span>
      </div>
      <div style={{ paddingInline: 22 }}>
        <div className="rounded-full overflow-hidden" style={{ height: 6, background: "#FCE0DA" }}>
          <div
            className="h-full rounded-full"
            style={{
              width: `${(solvedCount / totalQuestions) * 100}%`,
              background: "#E35D49",
              transition: "width 0.4s ease",
            }}
          />
        </div>
      </div>

      {/* 문제 */}
      <div style={{ padding: "16px 22px 0" }}>
        <div
          className="font-sejong"
          style={{
            background: "#FFF3E7",
            border: "1px solid rgba(227, 93, 73, 0.18)",
            borderRadius: 16,
            padding: "14px 16px",
            fontSize: 14,
            lineHeight: "21px",
            color: "#1f1f1f",
            letterSpacing: "-0.3px",
            whiteSpace: "pre-line",
          }}
        >
          <span style={{ color: "#E35D49", fontWeight: 700, marginRight: 6 }}>Q.</span>
          {q.question}
        </div>
      </div>

      {/* 선택지 */}
      <div className="flex flex-col" style={{ padding: "14px 22px 0", gap: 8 }}>
        {q.type === "multiple" &&
          q.options.map((opt, i) => (
            <OptionRow
              key={i}
              label={String.fromCharCode(65 + i)} // A, B, C, D
              text={opt}
              picked={picked === i}
              correct={revealed && i === q.answer}
              wrong={revealed && picked === i && i !== q.answer}
              disabled={revealed}
              onClick={() => handlePick(i)}
            />
          ))}
        {q.type === "ox" && (
          <div className="flex" style={{ gap: 10 }}>
            <OXButton
              value="O"
              picked={picked === "O"}
              correct={revealed && q.answer === "O"}
              wrong={revealed && picked === "O" && q.answer !== "O"}
              disabled={revealed}
              onClick={() => handlePick("O")}
            />
            <OXButton
              value="X"
              picked={picked === "X"}
              correct={revealed && q.answer === "X"}
              wrong={revealed && picked === "X" && q.answer !== "X"}
              disabled={revealed}
              onClick={() => handlePick("X")}
            />
          </div>
        )}
      </div>

      {/* 정답/해설 */}
      {revealed && (
        <div style={{ padding: "12px 22px 0" }}>
          <div
            className="font-sejong"
            style={{
              background: isCorrect ? "rgba(167, 218, 167, 0.18)" : "rgba(227, 93, 73, 0.10)",
              border: `1px solid ${isCorrect ? "rgba(123, 164, 92, 0.4)" : "rgba(227, 93, 73, 0.4)"}`,
              borderRadius: 14,
              padding: "12px 14px",
              fontSize: 13,
              lineHeight: "19px",
              color: "#1f1f1f",
              letterSpacing: "-0.3px",
            }}
          >
            <div
              style={{
                fontWeight: 700,
                color: isCorrect ? "#7BA45C" : "#E35D49",
                marginBottom: 4,
                letterSpacing: "-0.43px",
              }}
            >
              {isCorrect ? "🎉 정답이에요!" : "😢 아쉬워요. 다시 도전!"}
            </div>
            <div>{q.explanation}</div>
          </div>
        </div>
      )}

      {/* 다음 버튼 */}
      <div style={{ padding: "16px 22px 22px" }}>
        <button
          type="button"
          onClick={handleNext}
          disabled={!revealed}
          className="signup-submit w-full font-sejong text-white shadow-md transition-all flex items-center justify-center"
          style={{
            height: 48,
            borderRadius: 999,
            background: revealed ? "#E35D49" : "#E5C0B8",
            fontSize: 16,
            fontWeight: 500,
            border: "none",
            padding: 0,
            letterSpacing: "-0.43px",
            cursor: revealed ? "pointer" : "not-allowed",
          }}
        >
          {revealed ? (queue.length > 1 || !isCorrect ? "다음 문제" : "퀴즈 완료") : "정답을 골라주세요"}
        </button>
      </div>
    </ModalShell>
  );
}

/* ─────────────────────────────────────────────────────────
   모달 셸 (배경 딤 + 카드)
   ───────────────────────────────────────────────────────── */
function ModalShell({ children, onClose }) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 flex items-center justify-center"
      style={{
        background: "rgba(0, 0, 0, 0.45)",
        zIndex: 100,
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%",
          maxWidth: 360,
          maxHeight: "90vh",
          overflowY: "auto",
          background: "#FFFFFF",
          borderRadius: 24,
          boxShadow: "0 12px 32px rgba(0, 0, 0, 0.18)",
        }}
      >
        {children}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   선택지 행 (4지선다)
   ───────────────────────────────────────────────────────── */
function OptionRow({ label, text, picked, correct, wrong, disabled, onClick }) {
  let bg = "#FFFFFF";
  let border = "rgba(227, 93, 73, 0.20)";
  let labelBg = "#FFE5DD";
  let labelColor = "#E35D49";
  if (correct) {
    bg = "rgba(167, 218, 167, 0.18)";
    border = "rgba(123, 164, 92, 0.55)";
    labelBg = "#7BA45C";
    labelColor = "#FFFFFF";
  } else if (wrong) {
    bg = "rgba(227, 93, 73, 0.10)";
    border = "rgba(227, 93, 73, 0.55)";
    labelBg = "#E35D49";
    labelColor = "#FFFFFF";
  } else if (picked) {
    border = "rgba(227, 93, 73, 0.55)";
  }
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="w-full flex items-center font-sejong transition-all active:scale-[0.99]"
      style={{
        padding: "10px 12px",
        borderRadius: 14,
        background: bg,
        border: `1.5px solid ${border}`,
        gap: 10,
        textAlign: "left",
        cursor: disabled ? "default" : "pointer",
      }}
    >
      <span
        className="inline-flex items-center justify-center flex-shrink-0 font-noto"
        style={{
          width: 26, height: 26, borderRadius: 8,
          background: labelBg, color: labelColor,
          fontSize: 12, fontWeight: 700, letterSpacing: "-0.43px",
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: 13.5, lineHeight: "19px", color: "#1f1f1f", letterSpacing: "-0.3px" }}>
        {text}
      </span>
    </button>
  );
}

/* ─────────────────────────────────────────────────────────
   O / X 버튼
   ───────────────────────────────────────────────────────── */
function OXButton({ value, picked, correct, wrong, disabled, onClick }) {
  let bg = "#FFFFFF";
  let border = "rgba(227, 93, 73, 0.25)";
  let color = "#E35D49";
  if (correct) {
    bg = "rgba(167, 218, 167, 0.20)";
    border = "rgba(123, 164, 92, 0.55)";
    color = "#7BA45C";
  } else if (wrong) {
    bg = "rgba(227, 93, 73, 0.10)";
    border = "rgba(227, 93, 73, 0.55)";
    color = "#E35D49";
  } else if (picked) {
    border = "rgba(227, 93, 73, 0.55)";
  }
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex-1 flex items-center justify-center font-jeju transition-all active:scale-[0.98]"
      style={{
        height: 80,
        borderRadius: 16,
        background: bg,
        border: `2px solid ${border}`,
        color,
        fontSize: 44,
        fontWeight: 400,
        letterSpacing: "-0.43px",
        cursor: disabled ? "default" : "pointer",
      }}
    >
      {value}
    </button>
  );
}
