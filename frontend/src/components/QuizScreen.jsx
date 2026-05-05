import { useEffect, useMemo, useRef, useState } from "react";
import chatTomato from "../assets/tomato/chat/chat.png";
import ticketImg from "../assets/tomato/_shared/ticket.png";
import yahoImg from "../assets/tomato/draw/yaho.png";

/* ─────────────────────────────────────────────────────────
   퀴즈 채팅 화면
   - 코치(토미) 채팅으로 문제 출제 → 사용자가 보기 클릭 → 채팅에 답 보내짐
   - 정답이면 다음 문제 / 오답이면 큐 끝으로 보내고 다음 문제
   - 모두 정답 맞히면 보상 메시지 + 뽑기권 +1
   - 교육과는 별도 채팅으로 진행!
   ───────────────────────────────────────────────────────── */
export default function QuizScreen({ lesson, onBack, onComplete, alreadyCompleted = false }) {
  const initial = useMemo(() => lesson.quiz.map((_, i) => i), [lesson]);
  const [queue, setQueue] = useState(initial);
  const [messages, setMessages] = useState([]);
  const [waiting, setWaiting] = useState(false); // 코치가 다음 메시지 준비 중
  const [solvedCount, setSolvedCount] = useState(0);
  const [done, setDone] = useState(false);
  const scrollRef = useRef(null);
  const startedRef = useRef(false);

  const totalQuestions = lesson.quiz.length;

  // 첫 진입 시 인사 + 첫 문제 출제
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    pushCoach({ kind: "text", text: "🧠 도전! 영양 박사 퀴즈 시간이야. 5문제를 다 맞히면 뽑기권을 받을 수 있어!" });
    setTimeout(() => askQuestion(initial), 700);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 메시지 추가될 때마다 자동 스크롤
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [messages]);

  function pushCoach(msg) {
    setMessages((prev) => [...prev, { role: "coach", ...msg }]);
  }
  function pushUser(text) {
    setMessages((prev) => [...prev, { role: "user", text }]);
  }

  function askQuestion(currentQueue) {
    if (currentQueue.length === 0) {
      finishQuiz();
      return;
    }
    const idx = currentQueue[0];
    const q = lesson.quiz[idx];
    pushCoach({
      kind: "question",
      questionIdx: idx,
      questionNumber: solvedCount + 1,
      total: totalQuestions,
      text: q.question,
      type: q.type,
      options: q.options || null,
    });
    setWaiting(false);
  }

  // 현재 활성 질문 — 마지막 메시지가 coach question이면 활성
  const lastMsg = messages[messages.length - 1];
  const activeQuestion =
    lastMsg && lastMsg.role === "coach" && lastMsg.kind === "question" ? lastMsg : null;
  const activeQ = activeQuestion ? lesson.quiz[activeQuestion.questionIdx] : null;

  function handlePick(questionIdx, value) {
    if (waiting) return;
    const q = lesson.quiz[questionIdx];
    const isCorrect = value === q.answer;

    // 1) 해당 question 메시지를 answered 처리 (옵션 비활성화)
    setMessages((prev) =>
      prev.map((m) =>
        m.role === "coach" && m.kind === "question" && m.questionIdx === questionIdx && !m.answered
          ? { ...m, answered: true, picked: value }
          : m
      )
    );

    // 2) 사용자 채팅 (선택한 답)
    const userText = q.type === "ox" ? value : `${String.fromCharCode(65 + value)}. ${q.options[value]}`;
    pushUser(userText);

    setWaiting(true);

    // 3) 정/오답 피드백
    setTimeout(() => {
      pushCoach({
        kind: "feedback",
        correct: isCorrect,
        explanation: q.explanation,
      });
    }, 500);

    // 4) 큐 업데이트 + 다음 문제
    setTimeout(() => {
      let nextQueue;
      if (isCorrect) {
        nextQueue = queue.slice(1);
        setSolvedCount((c) => c + 1);
      } else {
        nextQueue = [...queue.slice(1), questionIdx];
      }
      setQueue(nextQueue);
      askQuestion(nextQueue);
    }, 1500);
  }

  function finishQuiz() {
    setDone(true);
    pushCoach({
      kind: "complete",
    });
    onComplete?.({ rewards: { tickets: 1 } });
  }

  return (
    <div
      className="relative overflow-hidden mx-auto flex flex-col"
      style={{
        width: "min(402px, 100vw)",
        height: "min(874px, 100dvh)",
        background: "#FFF3E7",
      }}
    >
      {/* 헤더 — 뒤로가기 + 우측 퀴즈 배지 */}
      <header
        className="flex-shrink-0 flex items-center justify-between"
        style={{
          height: 56,
          paddingInline: 16,
          background: "rgba(255, 248, 240, 0.92)",
          backdropFilter: "blur(8px)",
          borderBottom: "1px solid rgba(227, 93, 73, 0.12)",
        }}
      >
        <button
          type="button"
          onClick={onBack}
          aria-label="뒤로가기"
          className="flex items-center justify-center"
          style={{
            width: 36, height: 36, padding: 0, border: "none",
            background: "transparent", cursor: "pointer",
          }}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#000" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 6l-6 6 6 6" />
          </svg>
        </button>
        <span className="flex items-center" style={{ gap: 8 }}>
          <span
            className="font-sejong"
            style={{
              fontSize: 16,
              fontWeight: 700,
              color: "#000",
              letterSpacing: "-0.43px",
            }}
          >
            토미와 퀴즈
          </span>
          <span
            className="font-sejong inline-flex items-center"
            style={{
              background: "#E35D49",
              color: "#FFFFFF",
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "-0.3px",
              paddingInline: 8,
              height: 20,
              borderRadius: 999,
            }}
          >
            {solvedCount}/{totalQuestions}
          </span>
        </span>
      </header>

      {/* 레슨 정보 팝업 카드 */}
      <div
        className="flex-shrink-0"
        style={{ paddingInline: 16, paddingTop: 12 }}
      >
        <div
          className="flex items-center"
          style={{
            background: "#FFFFFF",
            border: "1px solid rgba(227, 93, 73, 0.25)",
            borderRadius: 16,
            padding: "10px 14px",
            gap: 10,
            boxShadow: "0 4px 12px rgba(0, 0, 0, 0.04)",
          }}
        >
          <span style={{ fontSize: 22 }}>{lesson.icon}</span>
          <div className="flex-1 min-w-0">
            <div
              className="font-sejong"
              style={{ fontSize: 11, color: "#75726e", letterSpacing: "-0.43px" }}
            >
              {lesson.category}
            </div>
            <div
              className="font-sejong truncate"
              style={{ fontSize: 14, fontWeight: 700, color: "#1a1a1a", letterSpacing: "-0.43px", marginTop: 1 }}
            >
              {lesson.title}
            </div>
          </div>
        </div>
      </div>

      {/* 채팅 본문 */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto"
        style={{ padding: "16px 16px 12px" }}
      >
        {messages.map((m, i) => {
          const isLastMsg = i === messages.length - 1;
          if (m.role === "user") {
            return <UserBubble key={i} text={m.text} animate={isLastMsg} />;
          }
          if (m.kind === "question") {
            return <QuestionBubble key={i} message={m} animate={isLastMsg} />;
          }
          if (m.kind === "feedback") {
            return <FeedbackBubble key={i} message={m} animate={isLastMsg} />;
          }
          if (m.kind === "complete") {
            return <CompleteBubble key={i} animate={isLastMsg} onClose={onBack} alreadyCompleted={alreadyCompleted} />;
          }
          return <TextBubble key={i} text={m.text} animate={isLastMsg} />;
        })}
      </div>

      {/* 하단 빠른답장 / 비활성 입력창 */}
      {activeQ ? (
        <QuickReplyBar
          question={activeQ}
          onPick={(value) => handlePick(activeQuestion.questionIdx, value)}
        />
      ) : (
        <DisabledChatInput />
      )}

      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   버블 컴포넌트
   ───────────────────────────────────────────────────────── */
function CoachBubbleShell({ children, animate, wide = false }) {
  return (
    <div
      className="flex items-start"
      style={{
        gap: 8,
        marginBottom: 10,
        opacity: animate ? 0 : 1,
        animation: animate ? "fadeIn 0.35s forwards" : "none",
      }}
    >
      <img
        src={chatTomato}
        alt=""
        draggable="false"
        className="select-none pointer-events-none flex-shrink-0"
        style={{ width: 32, height: 32, objectFit: "contain", marginTop: 4 }}
      />
      <div
        className="font-sejong"
        style={{
          background: "#FFFFFF",
          border: "1px solid rgba(227, 93, 73, 0.18)",
          borderRadius: "18px 18px 18px 4px",
          padding: "11px 14px",
          maxWidth: wide ? 296 : 270,
          fontSize: 13.5,
          lineHeight: "20px",
          color: "#1f1f1f",
          letterSpacing: "-0.3px",
        }}
      >
        {children}
      </div>
    </div>
  );
}

function TextBubble({ text, animate }) {
  return (
    <CoachBubbleShell animate={animate}>
      <div style={{ whiteSpace: "pre-line" }}>{text}</div>
    </CoachBubbleShell>
  );
}

function QuestionBubble({ message, animate }) {
  const { questionNumber, total, text, type, options } = message;
  return (
    <CoachBubbleShell animate={animate} wide>
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: "#E35D49",
          letterSpacing: "-0.43px",
          marginBottom: 4,
        }}
      >
        Q{questionNumber}/{total}
      </div>
      <div style={{ fontWeight: 600 }}>{text}</div>
      {type === "multiple" && Array.isArray(options) && (
        <ol
          className="font-sejong"
          style={{
            listStyle: "none",
            display: "flex",
            flexDirection: "column",
            gap: 6,
            marginTop: 10,
          }}
        >
          {options.map((option, i) => (
            <li
              key={i}
              style={{
                display: "grid",
                gridTemplateColumns: "22px 1fr",
                gap: 6,
                alignItems: "start",
                fontSize: 12.5,
                lineHeight: "18px",
                color: "#333",
              }}
            >
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: 22,
                  height: 22,
                  borderRadius: 999,
                  background: "rgba(227, 93, 73, 0.1)",
                  color: "#E35D49",
                  fontWeight: 800,
                }}
              >
                {String.fromCharCode(65 + i)}
              </span>
              <span>{option}</span>
            </li>
          ))}
        </ol>
      )}
    </CoachBubbleShell>
  );
}

function QuickReplyBar({ question, onPick }) {
  return (
    <div
      className="flex-shrink-0"
      style={{
        padding: "10px 16px max(16px, env(safe-area-inset-bottom))",
        background: "linear-gradient(180deg, rgba(255, 243, 231, 0) 0%, #FFF3E7 30%)",
      }}
    >
      <div
        className="font-sejong"
        style={{ fontSize: 11, color: "#75726e", letterSpacing: "-0.43px", marginBottom: 6, paddingLeft: 4 }}
      >
        답을 골라줘!
      </div>
      {question.type === "multiple" && (
        <div className="flex flex-wrap" style={{ gap: 8, marginBottom: 10 }}>
          {question.options.map((_, i) => (
            <ReplyChip
              key={i}
              label={String.fromCharCode(65 + i)}
              onClick={() => onPick(i)}
            />
          ))}
        </div>
      )}
      {question.type === "ox" && (
        <div className="flex" style={{ gap: 8, marginBottom: 10 }}>
          <ReplyChip label="O" onClick={() => onPick("O")} />
          <ReplyChip label="X" onClick={() => onPick("X")} />
        </div>
      )}
      <DisabledChatInput compact />
    </div>
  );
}

function DisabledChatInput({ compact = false }) {
  return (
    <div
      className="flex-shrink-0 flex items-center"
      style={{
        padding: compact ? 0 : "10px 16px 16px",
        gap: 8,
      }}
    >
      <button
        type="button"
        disabled
        aria-label="추가 메뉴 (비활성)"
        className="flex items-center justify-center flex-shrink-0"
        style={{
          width: 42,
          height: 42,
          borderRadius: 999,
          background: "#FFFFFF",
          border: "1.5px solid rgba(227, 93, 73, 0.32)",
          padding: 0,
          cursor: "not-allowed",
        }}
      >
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#E35D49" strokeWidth="2.4" strokeLinecap="round">
          <path d="M12 5v14M5 12h14" />
        </svg>
      </button>
      <div
        className="flex-1 flex items-center font-sejong"
        style={{
          minWidth: 0,
          background: "#FFFFFF",
          border: "1.5px solid rgba(227, 93, 73, 0.24)",
          borderRadius: 999,
          height: 42,
          paddingInline: 16,
          color: "#A6A29D",
          fontSize: 14,
          fontWeight: 700,
          letterSpacing: "-0.43px",
        }}
      >
        지금은 퀴즈 시간이에요!
      </div>
      <button
        type="button"
        disabled
        aria-label="보내기 (비활성)"
        className="flex items-center justify-center flex-shrink-0"
        style={{
          width: 42,
          height: 42,
          borderRadius: 999,
          background: "#F3A398",
          border: "none",
          padding: 0,
          cursor: "not-allowed",
        }}
      >
        <svg width="17" height="17" viewBox="0 0 24 24" fill="#FFFFFF">
          <path d="M3 3l18 9-18 9 4-9-4-9z" />
        </svg>
      </button>
    </div>
  );
}

function ReplyChip({ label, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="font-noto inline-flex items-center justify-center transition-all active:scale-[0.95]"
      style={{
        background: "#FFFFFF",
        border: "1.5px solid #E35D49",
        borderRadius: 999,
        minWidth: 48,
        height: 32,
        paddingInline: 14,
        cursor: "pointer",
        fontSize: 14,
        color: "#E35D49",
        fontWeight: 700,
        letterSpacing: "0.3px",
      }}
    >
      {label}
    </button>
  );
}

function FeedbackBubble({ message, animate }) {
  const { correct, explanation } = message;
  const color = correct ? "#7BA45C" : "#E35D49";
  const bg = correct ? "rgba(167, 218, 167, 0.18)" : "rgba(227, 93, 73, 0.10)";
  const border = correct ? "rgba(123, 164, 92, 0.4)" : "rgba(227, 93, 73, 0.4)";
  return (
    <div
      className="flex items-start"
      style={{
        gap: 8,
        marginBottom: 10,
        opacity: animate ? 0 : 1,
        animation: animate ? "fadeIn 0.35s forwards" : "none",
      }}
    >
      <img
        src={chatTomato}
        alt=""
        draggable="false"
        className="select-none pointer-events-none flex-shrink-0"
        style={{ width: 32, height: 32, objectFit: "contain", marginTop: 4 }}
      />
      <div
        className="font-sejong"
        style={{
          background: bg,
          border: `1px solid ${border}`,
          borderRadius: "18px 18px 18px 4px",
          padding: "11px 14px",
          maxWidth: 270,
          fontSize: 13.5,
          lineHeight: "20px",
          color: "#1f1f1f",
          letterSpacing: "-0.3px",
        }}
      >
        <div style={{ fontWeight: 700, color, marginBottom: 4 }}>
          {correct ? "🎉 정답이에요!" : "😢 아쉬워요"}
        </div>
        <div>{explanation}</div>
      </div>
    </div>
  );
}

function CompleteBubble({ animate, onClose, alreadyCompleted }) {
  return (
    <CoachBubbleShell animate={animate} wide>
      <div className="flex flex-col items-center" style={{ paddingTop: 4, paddingBottom: 4 }}>
        <img
          src={yahoImg}
          alt=""
          draggable="false"
          className="select-none pointer-events-none"
          style={{ width: 96, height: 96, objectFit: "contain" }}
        />
        <div
          className="font-jeju"
          style={{ fontSize: 24, color: "#E35D49", letterSpacing: "-0.43px", marginTop: 6 }}
        >
          퀴즈 완료!
        </div>
        <div
          className="font-sejong"
          style={{ fontSize: 13, color: "#1f1f1f", letterSpacing: "-0.3px", marginTop: 4, textAlign: "center" }}
        >
          {alreadyCompleted
            ? <>모든 문제를 다 맞혔어요!<br />이미 보상을 받은 퀴즈예요</>
            : <>모든 문제를 다 맞혔어요!<br />보상으로 뽑기권 1개를 받았어요</>}
        </div>
        {!alreadyCompleted && (
          <span
            className="flex items-center font-sejong"
            style={{
              marginTop: 12,
              background: "rgba(255, 218, 137, 0.4)",
              borderRadius: 999,
              paddingInline: 14,
              height: 32,
              gap: 8,
              border: "1px solid rgba(232, 181, 61, 0.45)",
              fontSize: 14,
              fontWeight: 700,
              color: "#E35D49",
              letterSpacing: "-0.43px",
            }}
          >
            <img src={ticketImg} alt="" style={{ width: 18, height: 18 }} />
            +1
          </span>
        )}
        <button
          type="button"
          onClick={onClose}
          className="signup-submit font-sejong text-white shadow-md transition-all flex items-center justify-center"
          style={{
            marginTop: 16,
            width: "100%",
            height: 40,
            borderRadius: 999,
            background: "#E35D49",
            fontSize: 14,
            fontWeight: 500,
            border: "none",
            padding: 0,
            letterSpacing: "-0.43px",
          }}
        >
          돌아가기
        </button>
      </div>
    </CoachBubbleShell>
  );
}

function UserBubble({ text, animate }) {
  return (
    <div
      className="flex justify-end"
      style={{
        marginBottom: 10,
        opacity: animate ? 0 : 1,
        animation: animate ? "fadeIn 0.3s forwards" : "none",
      }}
    >
      <div
        className="font-sejong"
        style={{
          background: "#E35D49",
          color: "#FFFFFF",
          borderRadius: "18px 18px 4px 18px",
          padding: "10px 14px",
          maxWidth: 260,
          fontSize: 13.5,
          lineHeight: "20px",
          letterSpacing: "-0.3px",
          boxShadow: "0 1px 2px rgba(227, 93, 73, 0.18)",
        }}
      >
        {text}
      </div>
    </div>
  );
}
