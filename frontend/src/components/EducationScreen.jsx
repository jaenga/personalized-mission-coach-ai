import { useEffect, useRef, useState } from "react";
import chatTomato from "../assets/tomato/chat/chat.png";

const lessonImages = import.meta.glob("../assets/tomato/lessons/**/*.png", { eager: true });

function ImageModal({ src, onClose }) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.82)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 999,
        padding: 24,
      }}
    >
      <img
        src={src}
        alt=""
        draggable="false"
        onClick={onClose}
        style={{
          maxWidth: "100%",
          maxHeight: "80vh",
          borderRadius: 16,
          boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
        }}
      />
    </div>
  );
}

const COACH_MESSAGE_INITIAL_DELAY = 1200;
const COACH_MESSAGE_INTERVAL = 2500;

/* ─────────────────────────────────────────────────────────
   교육 챗 화면 — 코치 버블 + 하단 "이해했어요" 버튼
   ───────────────────────────────────────────────────────── */
// 한 문단을 문장 단위로 자르고 2문장씩 묶기
function chunkParagraph(paragraph, sentencesPerBubble = 2) {
  // bullet (-) 이나 번호 매김 리스트(1. 2. ...)면 그 블록은 통째로 유지
  if (/^\s*-\s/m.test(paragraph)) return [paragraph];
  if (/^\s*\d+\.\s/m.test(paragraph)) return [paragraph];

  // 문장 분리: ., !, ? 뒤 공백/줄바꿈 기준
  const sentences =
    paragraph.match(/[^.!?\n]+[.!?]+["')\]]*|[^.!?\n]+$/g)?.map((s) => s.trim()).filter(Boolean) || [paragraph];

  const chunks = [];
  for (let i = 0; i < sentences.length; i += sentencesPerBubble) {
    chunks.push(sentences.slice(i, i + sentencesPerBubble).join(" "));
  }
  return chunks;
}

// step을 말풍선 메시지 배열로 분할
function expandStep(step) {
  if (step.type === "summary") {
    return [{ role: "coach", kind: "summary", step }];
  }

  const messages = [];

  if (step.image) {
    messages.push({ role: "coach", kind: "image", src: step.image });
  }

  // \n\n 으로 문단 분리 후, 각 문단을 문장 단위로 추가 분할
  const paragraphs = (step.body || "")
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);

  const chunks = paragraphs.flatMap((p) => chunkParagraph(p));

  chunks.forEach((c, i) => {
    messages.push({
      role: "coach",
      kind: "para",
      text: c,
      heading: i === 0 ? step.heading : undefined,
      highlights: step.highlights,
    });
  });

  return messages;
}

export default function EducationScreen({ lesson, onBack, onFinish }) {
  // messages: [{ role: "coach", kind, ...} | { role: "user", text }]
  const [messages, setMessages] = useState([]);
  const [modalSrc, setModalSrc] = useState(null);
  const [stepIdx, setStepIdx] = useState(0);
  const [isTyping, setIsTyping] = useState(true); // 처음엔 코치가 등장 중
  const scrollRef = useRef(null);
  const startedRef = useRef(false);
  const timersRef = useRef([]);

  function clearMessageTimers() {
    timersRef.current.forEach((timer) => clearTimeout(timer));
    timersRef.current = [];
  }

  function revealCoachMessages(nextMessages, initialDelay = COACH_MESSAGE_INITIAL_DELAY) {
    clearMessageTimers();
    setIsTyping(true);
    nextMessages.forEach((msg, i) => {
      const timer = setTimeout(() => {
        setMessages((prev) => [...prev, msg]);
        if (i === nextMessages.length - 1) setIsTyping(false);
      }, initialDelay + i * COACH_MESSAGE_INTERVAL);
      timersRef.current.push(timer);
    });
  }

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [messages, isTyping]);

  // 첫 진입 시 첫 step의 메시지를 시간차로 등장
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    const firstMessages = expandStep(lesson.education[0]);
    revealCoachMessages(firstMessages);
    return () => {
      clearMessageTimers();
      startedRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currentStep = lesson.education[stepIdx];
  const isLast = stepIdx >= lesson.education.length - 1;
  const ctaLabel = currentStep?.type === "summary" ? "퀴즈 풀러 가기" : "이해했어요!";

  function handleNext() {
    if (isTyping) return; // 안전장치
    // 1) 내가 친 채팅(이해했어요/퀴즈 풀러 가기)을 먼저 추가
    setMessages((prev) => [...prev, { role: "user", text: ctaLabel }]);

    if (isLast) {
      // 마지막이면 짧은 딜레이 후 퀴즈로 이동
      setTimeout(() => onFinish?.(), 300);
      return;
    }

    // 2) 다음 step의 문단들을 시간차로 추가 (타이핑 도착 느낌)
    const nextIdx = stepIdx + 1;
    const nextStep = lesson.education[nextIdx];
    const nextMessages = expandStep(nextStep);
    setStepIdx(nextIdx);
    revealCoachMessages(nextMessages, 750);
  }

  return (
    <div
      className="mobile-frame flex flex-col"
      style={{ background: "#FFF3E7" }}
    >
      {/* 헤더 — 뒤로가기 + 우측 배움 배지 */}
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
        <span
          className="font-sejong"
          style={{
            fontSize: 16,
            fontWeight: 700,
            color: "#000",
            letterSpacing: "-0.43px",
          }}
        >
          토미와 배움
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

      {/* 스크롤 본문 */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto"
        style={{ padding: "16px 16px 120px" }}
      >
        {messages.map((m, i) => {
          const isLast = i === messages.length - 1;
          if (m.role === "user") {
            return <UserBubble key={i} text={m.text} animate={isLast} />;
          }
          return <CoachBubble key={i} message={m} animate={isLast} onImageClick={setModalSrc} />;
        })}
        {isTyping && <TypingBubble />}
      </div>
      {modalSrc && <ImageModal src={modalSrc} onClose={() => setModalSrc(null)} />}

      {/* 하단 CTA */}
      <div
        className="flex-shrink-0"
        style={{
          padding: "10px 16px calc(18px + env(safe-area-inset-bottom))",
          background: "linear-gradient(180deg, rgba(255, 243, 231, 0) 0%, #FFF3E7 30%)",
          position: "absolute",
          bottom: 0,
          left: 0,
          right: 0,
        }}
      >
        <button
          type="button"
          onClick={handleNext}
          disabled={isTyping}
          className="signup-submit w-full font-sejong text-white shadow-md transition-all flex items-center justify-center"
          style={{
            height: 50,
            borderRadius: 999,
            background: isTyping ? "#E5C0B8" : "#E35D49",
            fontSize: 17,
            fontWeight: 500,
            letterSpacing: "-0.43px",
            border: "none",
            padding: 0,
            cursor: isTyping ? "not-allowed" : "pointer",
            opacity: isTyping ? 0.85 : 1,
          }}
        >
          {isTyping ? "토미가 말하는 중..." : ctaLabel}
        </button>
      </div>
    </div>
  );
}

function TypingDots() {
  return (
    <span
      aria-label="토미가 말하는 중"
      className="inline-flex items-center"
      style={{ gap: 3, height: 20 }}
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            width: 5,
            height: 5,
            borderRadius: "50%",
            background: "#E35D49",
            display: "inline-block",
            animation: "typingDot 1s infinite ease-in-out",
            animationDelay: `${i * 0.16}s`,
          }}
        />
      ))}
    </span>
  );
}

function TypingBubble() {
  return (
    <div
      className="flex items-start"
      style={{
        gap: 8,
        marginBottom: 10,
        animation: "fadeIn 0.25s forwards",
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
          minWidth: 48,
          boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
        }}
      >
        <TypingDots />
      </div>
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes typingDot {
          0%, 80%, 100% { transform: translateY(0); opacity: 0.45; }
          40% { transform: translateY(-4px); opacity: 1; }
        }
      `}</style>
    </div>
  );
}

function renderHighlighted(text, keywords) {
  if (!keywords?.length) return text;
  // 문자열이면 기본 스타일로 정규화
  const normalized = keywords.map((k) =>
    typeof k === "string" ? { text: k, color: "#E35D49", bold: true } : k
  );
  const sorted = [...normalized].sort((a, b) => b.text.length - a.text.length);
  const regex = new RegExp(
    `(${sorted.map((k) => k.text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`,
    "g"
  );
  const parts = text.split(regex);
  return parts.map((part, i) => {
    const match = normalized.find((k) => k.text === part);
    if (!match) return part;
    return (
      <span
        key={i}
        style={{
          color: match.color || undefined,
          fontWeight: match.bold !== false ? 700 : undefined,
          ...(match.bg && {
            background: match.bg,
            borderRadius: 4,
            padding: "1px 5px",
          }),
        }}
      >
        {part}
      </span>
    );
  });
}

function CoachBubble({ message, animate, onImageClick }) {
  const isSummary = message.kind === "summary";
  const isImage = message.kind === "image";
  const step = message.step;
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
      {isImage ? (
        <img
          src={lessonImages[message.src.replace("/src/", "../")]?.default ?? message.src}
          alt=""
          draggable="false"
          onClick={() => onImageClick(lessonImages[message.src.replace("/src/", "../")]?.default ?? message.src)}
          style={{
            width: 270,
            maxWidth: "100%",
            borderRadius: "18px 18px 18px 4px",
            boxShadow: "0 2px 8px rgba(0,0,0,0.10)",
            display: "block",
            cursor: "pointer",
          }}
        />
      ) : (
      <div
        className="font-sejong"
        style={{
          background: "#FFFFFF",
          border: "1px solid rgba(227, 93, 73, 0.18)",
          borderRadius: "18px 18px 18px 4px",
          padding: "11px 14px",
          maxWidth: 270,
          fontSize: 13.5,
          lineHeight: "20px",
          color: "#1f1f1f",
          letterSpacing: "-0.3px",
          whiteSpace: "pre-line",
        }}
      >
        {message.heading && (
          <div
            style={{
              fontSize: 13.5,
              fontWeight: 700,
              color: "#E35D49",
              marginBottom: 6,
              letterSpacing: "-0.43px",
            }}
          >
            {message.heading}
          </div>
        )}
        {isSummary ? (
          <>
            {step.heading && (
              <div
                style={{
                  fontSize: 13.5,
                  fontWeight: 700,
                  color: "#E35D49",
                  marginBottom: 6,
                  letterSpacing: "-0.43px",
                }}
              >
                {step.heading}
              </div>
            )}
            <ul style={{ paddingLeft: 0, listStyle: "none" }}>
              {step.items?.map((it, i) => (
                <li key={i} style={{ marginTop: i === 0 ? 0 : 6, fontSize: 13, lineHeight: "19px" }}>
                  {it}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <div>{renderHighlighted(message.text, message.highlights)}</div>
        )}
      </div>
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

function UserBubble({ text, animate }) {
  return (
    <div
      className="flex justify-end"
      style={{
        marginBottom: 14,
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
          fontSize: 14,
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
