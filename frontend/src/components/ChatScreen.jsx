import { useEffect, useRef, useState } from "react";
import tomatoChat from "../assets/tomato/chat/chat.png";
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

function FaqSheet({ open, onClose, onPick }) {
  return (
    <>
      <div
        onClick={onClose}
        className="absolute inset-0"
        style={{
          background: "rgba(0,0,0,0.18)",
          opacity: open ? 1 : 0,
          pointerEvents: open ? "auto" : "none",
          transition: "opacity 0.2s ease",
          zIndex: 20,
        }}
      />
      <div
        className="absolute left-0 right-0"
        style={{
          bottom: 0,
          padding: 16,
          borderTopLeftRadius: 24,
          borderTopRightRadius: 24,
          background: "#FFFFFF",
          boxShadow: "0 -4px 16px rgba(0,0,0,0.08)",
          transform: open ? "translateY(-66px)" : "translateY(100%)",
          transition: "transform 0.28s ease",
          zIndex: 21,
        }}
      >
        <div className="flex items-center justify-between mb-3">
          <span
            className="font-sejong"
            style={{ fontSize: 14, fontWeight: 700, color: "#000", letterSpacing: "-0.43px" }}
          >
            자주 묻는 질문
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            style={{
              width: 24, height: 24, padding: 0, border: "none",
              background: "transparent", color: "#75726e", fontSize: 16,
            }}
          >
            ✕
          </button>
        </div>
        <div className="flex flex-col gap-2">
          {FAQ_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onPick(item)}
              className="font-sejong text-left transition-all active:scale-[0.99]"
              style={{
                width: "100%",
                padding: "12px 14px",
                borderRadius: 14,
                border: "1px solid rgba(227, 93, 73, 0.3)",
                background: "rgba(255, 243, 231, 0.6)",
                fontSize: 14,
                color: "#000",
                letterSpacing: "-0.43px",
                cursor: "pointer",
              }}
            >
              {item.label}
            </button>
          ))}
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

function AssistantMessage({ text, streaming = false }) {
  const showTyping = streaming && !String(text || "").trim();
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
        {showTyping ? <TypingDots /> : text}
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
            width: 34,
            height: 34,
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
  }, [messages, loading, missionOpen]);

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
      className="relative w-[402px] h-[874px] overflow-hidden mx-auto"
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
          top: missionOpen ? 124 : 56,
          bottom: 76,
          padding: "16px 16px 8px",
          display: "flex",
          flexDirection: "column",
          gap: 10,
          transition: "top 0.24s ease",
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
          style={{ padding: "10px 16px 16px", background: "transparent" }}
        >
          <button
            type="button"
            onClick={() => setFaqOpen(true)}
            aria-label="자주 묻는 질문"
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
