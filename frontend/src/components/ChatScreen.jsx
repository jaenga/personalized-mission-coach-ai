import { useEffect, useRef, useState } from "react";
import tomatoChat from "../assets/tomato/chat/chat.png";

/* ─────────────────────────────────────────────────────────
   FAQ — + 버튼 누르면 떠오르는 자주 묻는 질문 시트
   ───────────────────────────────────────────────────────── */
const FAQ_ITEMS = [
  { id: "who",     label: "토미가 누구야?" },
  { id: "rules",   label: "게임 규칙이 뭐야?" },
  { id: "quiz",    label: "퀴즈는 어떻게 풀어?" },
  { id: "rewards", label: "보상은 어떻게 얻어?" },
];

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
function AssistantMessage({ text }) {
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
        {text}
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
   ChatScreen
   ───────────────────────────────────────────────────────── */
const INITIAL_MESSAGES = [
  { id: 1, role: "assistant", text: "민준아! 오늘 물 5잔 마셨니? 👍" },
  { id: 2, role: "user", text: "응! 3잔 마셨어!" },
  { id: 3, role: "assistant", text: "잘했어! 🎉\n3잔만 더 마시면 미션 완료!" },
];

export default function ChatScreen({
  onBack,
  initialMessages = INITIAL_MESSAGES,
}) {
  const [messages, setMessages] = useState(initialMessages);
  const [input, setInput] = useState("");
  const [faqOpen, setFaqOpen] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  function handleSend(textOverride) {
    const text = (textOverride ?? input).trim();
    if (!text) return;
    setMessages((prev) => [...prev, { id: Date.now(), role: "user", text }]);
    setInput("");
  }

  function handleFaqPick(item) {
    setFaqOpen(false);
    handleSend(item.label);
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

      {/* 메시지 스크롤 영역 */}
      <div
        ref={scrollRef}
        className="absolute left-0 right-0 overflow-y-auto"
        style={{
          top: 56,
          bottom: 76,
          padding: "16px 16px 8px",
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        {messages.map((m) =>
          m.role === "assistant" ? (
            <AssistantMessage key={m.id} text={m.text} />
          ) : (
            <UserMessage key={m.id} text={m.text} />
          )
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
            disabled={!input.trim()}
            aria-label="보내기"
            className="flex items-center justify-center transition-transform active:scale-95 disabled:opacity-50"
            style={{
              width: 38, height: 38,
              borderRadius: 999,
              background: "#E35D49",
              border: "none", padding: 0,
              cursor: input.trim() ? "pointer" : "not-allowed",
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
