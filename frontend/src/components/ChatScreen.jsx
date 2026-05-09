import { useEffect, useRef, useState } from "react";
import tomatoChat from "../assets/tomato/chat/chat.png";
import submitMissionIcon from "../assets/tomato/chat/submit_mission_result.svg";
import adjustMissionIcon from "../assets/tomato/chat/request_mission_adjustment.svg";
import equivalencyIcon from "../assets/tomato/chat/check_mission_equivalency.svg";
import missionInfoIcon from "../assets/tomato/chat/get_mission_info.svg";
import historyIcon from "../assets/tomato/chat/get_user_history.svg";
import cancelActionIcon from "../assets/tomato/chat/cancel_mission_action.svg";
import flagImg from "../assets/tomato/home/flag.png";

/* ─────────────────────────────────────────────────────────
   FAQ — + 버튼 누르면 떠오르는 자주 묻는 질문 시트(수정가능)
   ───────────────────────────────────────────────────────── */
const FAQ_ITEMS = [
  { id: "who",     label: "토미가 누구야?" },
  { id: "rules",   label: "게임 규칙이 뭐야?" },
  { id: "quiz",    label: "퀴즈는 어떻게 풀어?" },
  { id: "rewards", label: "보상은 어떻게 얻어?" },
];

const TOMI_FEATURES = [
  {
    id: "submit",
    title: "미션 제출하기",
    description: "오늘 미션을 했는지\n결과를 제출해요",
    example: "미션 성공!",
    icon: submitMissionIcon,
    detailTitle: "이렇게 말해보세요",
    questions: ["오늘 미션 성공했어", "미션 완료했어", "오늘 미션 실패했어"],
  },
  {
    id: "adjust",
    title: "미션 바꾸기",
    description: "미션을 변경하거나\n난이도를 조정해요",
    example: "다른 미션으로 바꿔줘",
    icon: adjustMissionIcon,
    detailTitle: "바꾸고 싶을 때",
    questions: ["더 쉬운 미션으로 바꿔줘", "다른 미션 하고 싶어", "미션 너무 어려워"],
  },
  {
    id: "equivalency",
    title: "인정 여부 확인",
    description: "다른 방법으로 해도\n인정되는지 물어봐요",
    example: "자전거로 해도 돼?",
    icon: equivalencyIcon,
    detailTitle: "비슷한 행동을 물어볼 때",
    questions: ["산책 대신 자전거 타도 돼?", "저녁에 해도 인정돼?", "집에서 해도 괜찮아?"],
  },
  {
    id: "info",
    title: "미션/규칙 확인",
    description: "오늘 미션이나 규칙,\n마감 시간을 확인해요",
    example: "오늘 미션 뭐야?",
    icon: missionInfoIcon,
    detailTitle: "미션 정보가 궁금할 때",
    questions: ["오늘 미션 뭐야?", "미션 규칙 알려줘", "언제까지 하면 돼?"],
  },
  {
    id: "history",
    title: "기록 조회하기",
    description: "내 미션 수행 기록을\n확인할 수 있어요",
    example: "이번 주 기록 보여줘",
    icon: historyIcon,
    detailTitle: "기록을 보고 싶을 때",
    questions: ["이번 주 기록 보여줘", "어제 미션 성공했어?", "이번 달 미션 결과 요약 알려줘"],
  },
  {
    id: "cancel",
    title: "최근 행동 취소",
    description: "가장 최근의 제출/변경을\n취소할 수 있어요",
    example: "방금 제출 취소해줘",
    icon: cancelActionIcon,
    detailTitle: "실수했을 때",
    questions: ["방금 제출 취소해줘", "미션 변경 취소해줘", "최근 행동 되돌려줘"],
  },
];

const MISSION_HEADER_STORAGE_KEY = "tommyChatMissionHeaderOpen";

function readMissionHeaderOpen() {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem(MISSION_HEADER_STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

function saveMissionHeaderOpen(open) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(MISSION_HEADER_STORAGE_KEY, open ? "true" : "false");
  } catch {
  }
}

function FeatureCard({ item, flipped, onFlip }) {
  return (
    <button
      type="button"
      onClick={onFlip}
      aria-pressed={flipped}
      className="text-left"
      style={{
        minHeight: 170,
        padding: 0,
        border: "none",
        background: "transparent",
        perspective: 900,
      }}
    >
      <div
        className="relative h-full w-full"
        style={{
          minHeight: 170,
          transformStyle: "preserve-3d",
          transform: flipped ? "rotateY(180deg)" : "rotateY(0deg)",
          transition: "transform 0.42s cubic-bezier(0.2, 0.8, 0.2, 1)",
        }}
      >
        <div
          className="absolute inset-0"
          style={{
            borderRadius: 18,
            padding: "12px 13px",
            background: "rgba(255, 255, 255, 0.78)",
            border: "1px solid rgba(227, 93, 73, 0.18)",
            boxShadow: "0 7px 18px rgba(80, 60, 40, 0.05)",
            backfaceVisibility: "hidden",
            WebkitBackfaceVisibility: "hidden",
          }}
        >
          <img src={item.icon} alt="" draggable="false" style={{ width: 38, height: 38, objectFit: "contain" }} />
          <div className="font-sejong" style={{ marginTop: 8, fontSize: 16, fontWeight: 800, color: "#111", lineHeight: "19px" }}>
            {item.title}
          </div>
          <div
            className="font-sejong"
            style={{
              marginTop: 5,
              whiteSpace: "pre-line",
              fontSize: 12,
              fontWeight: 600,
              color: "#2f2c28",
              lineHeight: "17px",
              letterSpacing: "-0.2px",
            }}
          >
            {item.description}
          </div>
          <span
            className="font-sejong"
            style={{
              display: "inline-flex",
              marginTop: 7,
              maxWidth: "100%",
              borderRadius: 999,
              padding: "5px 8px",
              background: "rgba(237, 224, 214, 0.65)",
              color: "#7b7069",
              fontSize: 11,
              fontWeight: 700,
              lineHeight: "16px",
              whiteSpace: "normal",
            }}
          >
            “{item.example}”
          </span>
        </div>

        <div
          className="absolute inset-0"
          style={{
            borderRadius: 18,
            padding: "12px 12px",
            background: "rgba(255, 250, 245, 0.94)",
            border: "1px solid rgba(227, 93, 73, 0.22)",
            boxShadow: "0 7px 18px rgba(80, 60, 40, 0.05)",
            transform: "rotateY(180deg)",
            backfaceVisibility: "hidden",
            WebkitBackfaceVisibility: "hidden",
          }}
        >
          <div className="font-sejong" style={{ fontSize: 13, fontWeight: 800, color: "#E35D49", lineHeight: "17px" }}>
            {item.detailTitle}
          </div>
          <div className="mt-2 flex flex-col" style={{ gap: 6 }}>
            {item.questions.map((question) => (
              <div
                key={question}
                className="font-sejong"
                style={{
                  borderRadius: 12,
                  padding: "6px 7px",
                  background: "#FFFFFF",
                  border: "1px solid rgba(227, 93, 73, 0.14)",
                  color: "#2f2c28",
                  fontSize: 11,
                  fontWeight: 700,
                  lineHeight: "15px",
                  wordBreak: "keep-all",
                }}
              >
                {question}
              </div>
            ))}
          </div>
        </div>
      </div>
    </button>
  );
}

function FaqSheet({ open, onClose, onPick }) {
  const [expanded, setExpanded] = useState(false);
  const [dragOffset, setDragOffset] = useState(0);
  const [flippedCardId, setFlippedCardId] = useState(null);
  const [closing, setClosing] = useState(false);
  const dragStateRef = useRef(null);
  const closeTimerRef = useRef(null);

  useEffect(() => {
    if (open) {
      if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
      setClosing(false);
      return;
    }
    if (!open) {
      setExpanded(false);
      setDragOffset(0);
      setFlippedCardId(null);
      setClosing(false);
    }
  }, [open]);

  useEffect(() => {
    return () => {
      if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
    };
  }, []);

  function closeWithSlideDown() {
    if (closing) return;
    if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
    dragStateRef.current = null;
    setDragOffset(0);
    setClosing(true);
    closeTimerRef.current = setTimeout(() => {
      onClose();
      closeTimerRef.current = null;
    }, 280);
  }

  function handleHandlePointerDown(e) {
    dragStateRef.current = { startY: e.clientY };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  }

  function handleHandlePointerMove(e) {
    if (!dragStateRef.current) return;
    const dy = e.clientY - dragStateRef.current.startY;
    setDragOffset(Math.max(-22, Math.min(180, dy)));
  }

  function handleHandlePointerUp(e) {
    if (!dragStateRef.current) return;
    const dy = e.clientY - dragStateRef.current.startY;
    dragStateRef.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    setDragOffset(0);
    if (dy > 70) {
      closeWithSlideDown();
      return;
    }
    if (dy < -36) setExpanded(true);
  }

  function toggleCard(id) {
    setFlippedCardId((prev) => (prev === id ? null : id));
  }

  return (
    <>
      <div
        onClick={closeWithSlideDown}
        className="absolute inset-0"
        style={{
          background: "rgba(0,0,0,0.18)",
          opacity: open && !closing ? 1 : 0,
          pointerEvents: open && !closing ? "auto" : "none",
          transition: "opacity 0.2s ease",
          zIndex: 30,
        }}
      />
      <div
        className="absolute left-0 right-0"
        style={{
          bottom: 0,
          height: expanded ? "88%" : "72%",
          borderTopLeftRadius: 28,
          borderTopRightRadius: 28,
          background: "rgba(255, 252, 248, 0.98)",
          boxShadow: "0 -10px 28px rgba(94, 55, 40, 0.13)",
          transform: closing
            ? "translateY(calc(100% + 24px))"
            : open
              ? `translateY(${Math.max(0, dragOffset)}px)`
              : "translateY(calc(100% + 24px))",
          transition: dragStateRef.current ? "none" : "height 0.24s ease, transform 0.28s ease",
          zIndex: 31,
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          pointerEvents: open && !closing ? "auto" : "none",
        }}
      >
        <div
          onPointerDown={handleHandlePointerDown}
          onPointerMove={handleHandlePointerMove}
          onPointerUp={handleHandlePointerUp}
          onPointerCancel={() => {
            dragStateRef.current = null;
            setDragOffset(0);
          }}
          style={{
            padding: "12px 0 8px",
            cursor: "grab",
            touchAction: "none",
            flexShrink: 0,
          }}
        >
          <div
            aria-hidden="true"
            style={{
              width: 58,
              height: 5,
              borderRadius: 999,
              margin: "0 auto",
              background: "#cfc2b9",
            }}
          />
        </div>

        <div
          className="overflow-y-auto"
          style={{
            padding: "24px 18px calc(28px + env(safe-area-inset-bottom))",
            flex: 1,
            WebkitOverflowScrolling: "touch",
          }}
        >
          <div className="flex items-center" style={{ gap: 13 }}>
            <img src={tomatoChat} alt="" draggable="false" style={{ width: 58, height: 58, objectFit: "contain", flexShrink: 0 }} />
            <div>
              <div className="font-sejong" style={{ fontSize: 20, fontWeight: 800, color: "#111", lineHeight: "27px" }}>
                토미와 할 수 있는 것
              </div>
              <div className="font-sejong" style={{ marginTop: 5, fontSize: 14, fontWeight: 700, color: "#5d514a", lineHeight: "20px" }}>
                토미와 말하는 방법을 알려드릴게요!
              </div>
            </div>
          </div>

          <div
            className="mt-7 grid"
            style={{
              gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
              gap: 12,
            }}
          >
            {TOMI_FEATURES.map((item) => (
              <FeatureCard
                key={item.id}
                item={item}
                flipped={flippedCardId === item.id}
                onFlip={() => toggleCard(item.id)}
              />
            ))}
          </div>

          <div style={{ height: 1, background: "rgba(227, 93, 73, 0.14)", margin: "24px 0 22px" }} />

          <div className="flex items-center" style={{ gap: 8 }}>
            <span
              aria-hidden="true"
              className="flex items-center justify-center"
              style={{
                width: 25,
                height: 22,
                borderRadius: "12px 12px 12px 5px",
                background: "#B897E8",
                color: "#FFFFFF",
                fontSize: 14,
                fontWeight: 800,
              }}
            >
              ?
            </span>
            <span className="font-sejong" style={{ fontSize: 16, fontWeight: 800, color: "#111", lineHeight: "22px" }}>
              자주 묻는 질문
            </span>
          </div>

          <div className="mt-4 flex flex-col" style={{ gap: 9 }}>
            {FAQ_ITEMS.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => onPick(item)}
                className="font-sejong text-left transition-transform active:scale-[0.99]"
                style={{
                  width: "100%",
                  minHeight: 49,
                  padding: "0 16px",
                  borderRadius: 14,
                  border: "1px solid rgba(227, 93, 73, 0.18)",
                  background: "rgba(255, 255, 255, 0.82)",
                  color: "#111",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  fontSize: 14,
                  fontWeight: 800,
                  lineHeight: "20px",
                  letterSpacing: "-0.25px",
                }}
              >
                <span>{item.label}</span>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#9b8d85" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 6l6 6-6 6" />
                </svg>
              </button>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────
   메시지 버블
   ───────────────────────────────────────────────────────── */
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

function stripMarkdown(text) {
  return String(text || "")
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/\*\*(.+?)\*\*/gs, "$1")
    .replace(/\*(.+?)\*/gs, "$1")
    .replace(/__(.+?)__/gs, "$1")
    .replace(/_(.+?)_/gs, "$1")
    .replace(/```[\s\S]*?```/g, "")
    .replace(/`(.+?)`/g, "$1")
    .replace(/^\s*[-*+]\s/gm, "")
    .replace(/^\s*\d+\.\s/gm, "")
    .trim();
}

function AssistantMessage({ text, streaming = false }) {
  const showTyping = streaming && !String(text || "").trim();
  const displayText = stripMarkdown(text);
  return (
    <div className="flex items-end gap-2" style={{ maxWidth: "82%" }}>
      <img
        src={tomatoChat}
        alt=""
        draggable="false"
        className="select-none pointer-events-none"
        style={{ width: 36, height: 36, objectFit: "contain", flexShrink: 0 }}
      />
      <div
        className="font-sejong"
        style={{
          background: "#FFFFFF",
          borderRadius: "18px 18px 18px 4px",
          padding: "10px 14px",
          fontSize: 14,
          lineHeight: "20px",
          color: "#000",
          letterSpacing: "-0.43px",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {showTyping ? <TypingDots /> : displayText}
      </div>
    </div>
  );
}

function UserMessage({ text }) {
  return (
    <div className="self-end" style={{ maxWidth: "78%" }}>
      <div
        className="font-sejong"
        style={{
          background: "#E35D49",
          color: "#FFFFFF",
          borderRadius: "18px 18px 4px 18px",
          padding: "10px 14px",
          fontSize: 14,
          lineHeight: "20px",
          letterSpacing: "-0.43px",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {text}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   ChatScreen(백엔드랑 연동 시 삭제)
   ───────────────────────────────────────────────────────── */
const INITIAL_MESSAGES = [
  { id: 1, role: "assistant", text: "민준아! 오늘 물 5잔 마셨니? 👍" },
  { id: 2, role: "user", text: "응! 3잔 마셨어!" },
  { id: 3, role: "assistant", text: "잘했어! 🎉\n3잔만 더 마시면 미션 완료!" },
];

function MissionHeaderCard({ mission, open, onClose }) {
  const title = mission?.title || "오늘의 미션";
  const done = !!mission?.done;
  return (
    <div
      className="absolute left-0 right-0"
      style={{
        top: 64,
        paddingInline: 16,
        zIndex: 9,
        opacity: open ? 1 : 0,
        transform: open ? "translateY(0)" : "translateY(-12px)",
        transition: "opacity 0.22s ease, transform 0.28s cubic-bezier(0.2, 0.8, 0.25, 1)",
        pointerEvents: open ? "auto" : "none",
      }}
    >
      <div
        className="flex items-center"
        style={{
          minHeight: 58,
          borderRadius: 18,
          background: "#FFFFFF",
          border: "1px solid rgba(227, 93, 73, 0.18)",
          boxShadow: "0 8px 20px rgba(184, 72, 56, 0.12), 0 2px 6px rgba(0,0,0,0.05)",
          padding: "10px 12px",
          gap: 10,
        }}
      >
        <span
          className="flex items-center justify-center flex-shrink-0"
          style={{
            width: 36,
            height: 36,
            borderRadius: 12,
            background: done ? "rgba(123, 164, 92, 0.14)" : "rgba(227, 93, 73, 0.10)",
          }}
        >
          <img
            src={flagImg}
            alt=""
            draggable="false"
            className="select-none pointer-events-none"
            style={{
              width: 16,
              height: 16,
              objectFit: "contain",
              filter: done ? "grayscale(0.2) brightness(0.95)" : "none",
            }}
          />
        </span>
        <div className="flex-1 min-w-0">
          <div
            className="font-sejong"
            style={{ fontSize: 11, fontWeight: 700, color: done ? "#7BA45C" : "#E35D49", letterSpacing: "-0.3px" }}
          >
            {done ? "완료한 미션" : "오늘의 미션"}
          </div>
          <div
            className="font-sejong"
            style={{
              marginTop: 2,
              fontSize: 14,
              fontWeight: 700,
              color: "#1a1a1a",
              lineHeight: "18px",
              letterSpacing: "-0.3px",
              overflow: "hidden",
              display: "-webkit-box",
              WebkitLineClamp: 2,
              WebkitBoxOrient: "vertical",
            }}
          >
            {title}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="오늘의 미션 접어두기"
          className="flex items-center justify-center flex-shrink-0 transition-opacity active:opacity-60"
          style={{
            width: 24,
            height: 24,
            padding: 0,
            border: "none",
            background: "transparent",
            color: "#75726e",
            cursor: "pointer",
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
      </div>
    </div>
  );
}

export default function ChatScreen({
  onBack,
  messages: backendMessages,
  loading = false,
  onSend,
  todayMission,
  initialMessages = INITIAL_MESSAGES,
}) {
  const [localMessages, setLocalMessages] = useState(initialMessages);
  const [input, setInput] = useState("");
  const [faqOpen, setFaqOpen] = useState(false);
  const [missionOpen, setMissionOpen] = useState(readMissionHeaderOpen);
  const scrollRef = useRef(null);
  const messages = backendMessages
    ? backendMessages.map((m, index) => ({
        id: m.debugId || `${m.role}-${index}`,
        role: m.role,
        text: m.content ?? m.text ?? "",
        streaming: !!m.streaming,
      }))
    : localMessages;

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, loading]);

  useEffect(() => {
    saveMissionHeaderOpen(missionOpen);
  }, [missionOpen]);

  function handleSend(textOverride) {
    const text = (textOverride ?? input).trim();
    if (!text || loading) return;
    setInput("");
    if (onSend) {
      onSend(text);
      return;
    }
    setLocalMessages((prev) => [...prev, { id: Date.now(), role: "user", text }]);
  }

  function handleFaqPick(item) {
    setFaqOpen(false);
    handleSend(item.label);
  }

  function setMissionHeaderOpen(nextOpen) {
    setMissionOpen(nextOpen);
  }

  return (
    <div
      className="mobile-frame"
      style={{ background: "#FFF3E7" }}
    >
      {/* 상단 헤더: 뒤로가기 + 하트 카운트 */}
      <header
        className="absolute left-0 right-0 flex items-center justify-between"
        style={{
          top: 0,
          height: 56,
          paddingInline: 16,
          background: "rgba(255, 248, 240, 0.92)",
          backdropFilter: "blur(8px)",
          borderBottom: "1px solid rgba(227, 93, 73, 0.12)",
          zIndex: 10,
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
            fontSize: 16, fontWeight: 700, color: "#000", letterSpacing: "-0.43px",
          }}
        >
          토미와의 대화
        </span>
      </header>

      {/* 떠 있는 미션 토글 버튼 (FAB) — 접힌 상태에서만 표시 */}
      <button
        type="button"
        onClick={() => setMissionHeaderOpen(true)}
        aria-label="오늘의 미션 보기"
        aria-hidden={missionOpen}
        className="absolute flex items-center justify-center transition-transform active:scale-95"
        style={{
          top: 64,
          right: 20,
          width: 36,
          height: 36,
          padding: 0,
          border: "none",
          borderRadius: "50%",
          background: "#FFFFFF",
          boxShadow: "0 4px 12px rgba(0,0,0,0.10)",
          cursor: "pointer",
          zIndex: 11,
          opacity: missionOpen ? 0 : 1,
          pointerEvents: missionOpen ? "none" : "auto",
          transform: missionOpen ? "scale(0.85)" : "scale(1)",
          transition: "opacity 0.2s ease, transform 0.2s ease",
        }}
      >
        <img
          src={flagImg}
          alt=""
          draggable="false"
          className="select-none pointer-events-none"
          style={{ width: 16, height: 16, objectFit: "contain" }}
        />
      </button>

      {/* 메시지 스크롤 영역 */}
      <MissionHeaderCard
        mission={todayMission}
        open={missionOpen}
        onClose={() => setMissionHeaderOpen(false)}
      />

      <div
        ref={scrollRef}
        className="absolute left-0 right-0 overflow-y-auto"
        style={{
          top: 56,
          bottom: "calc(76px + env(safe-area-inset-bottom))",
          padding: "16px 16px 8px",
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        {messages.map((m) =>
          m.role === "assistant" ? (
            <AssistantMessage key={m.id} text={m.text} streaming={m.streaming} />
          ) : (
            <UserMessage key={m.id} text={m.text} />
          )
        )}
        {loading && messages[messages.length - 1]?.role !== "assistant" && (
          <AssistantMessage text="" streaming />
        )}
      </div>

      {/* 하단 입력바 */}
      <div className="absolute left-0 right-0" style={{ bottom: 0 }}>
        <div
          className="flex items-center gap-2"
          style={{
            padding: "10px 16px calc(16px + env(safe-area-inset-bottom))",
            background: "transparent",
          }}
        >
          <button
            type="button"
            data-tutorial-target="chat-plus-btn"
            onClick={() => setFaqOpen(true)}
            aria-label="토미 기능 안내"
            className="flex items-center justify-center transition-transform active:scale-95"
            style={{
              width: 38, height: 38,
              borderRadius: 999,
              background: "#FFFFFF",
              border: "1px solid rgba(227, 93, 73, 0.4)",
              padding: 0, cursor: "pointer",
              flexShrink: 0,
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#E35D49" strokeWidth="2.4" strokeLinecap="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
          <div
            className="flex items-center"
            style={{
              flex: 1,
              minWidth: 0,
              height: 42,
              borderRadius: 999,
              background: "#FFFFFF",
              border: "1px solid rgba(227, 93, 73, 0.3)",
              paddingInline: 16,
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={loading}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="메시지 입력..."
              className="font-sejong flex-1"
              style={{
                border: "none",
                outline: "none",
                background: "transparent",
                fontSize: 14,
                letterSpacing: "-0.43px",
                color: "#000",
                width: 0,
                minWidth: 0,
              }}
            />
          </div>
          <button
            type="button"
            onClick={() => handleSend()}
            disabled={!input.trim() || loading}
            aria-label="보내기"
            className="flex items-center justify-center transition-transform active:scale-95 disabled:opacity-50"
            style={{
              width: 38, height: 38,
              borderRadius: 999,
              background: "#E35D49",
              border: "none", padding: 0,
              cursor: input.trim() && !loading ? "pointer" : "not-allowed",
              flexShrink: 0,
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="#FFFFFF">
              <path d="M3 3l18 9-18 9 4-9-4-9z" />
            </svg>
          </button>
        </div>
      </div>

      <FaqSheet open={faqOpen} onClose={() => setFaqOpen(false)} onPick={handleFaqPick} />
    </div>
  );
}
