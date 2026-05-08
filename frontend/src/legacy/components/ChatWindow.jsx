import { useEffect, useRef, useState } from "react";

export default function ChatWindow({ messages, onSend, loading, lockChat, onMissionUiAction, selectedDebugId, onSelectMessage }) {
  const [input, setInput] = useState("");
  const bottomRef = useRef(null);
  const textareaRef = useRef(null);

  // 새 메시지 올 때마다 맨 아래로 스크롤
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // textarea 높이 자동 조절
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }, [input]);

  function handleSend() {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    onSend(text);
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="chat-container">
      <div className="messages-area">
        {messages.map((msg, i) => {
          const isClickable = msg.role === "assistant" && !!msg.debugId;
          const isSelected = msg.debugId && msg.debugId === selectedDebugId;
          const uiAction = msg.ui_action;
          const hasButtons = uiAction?.buttons?.length > 0;
          const isResolving = uiAction?.resolving;
          return (
            <div key={i} className={`message-row ${msg.role}`}>
              {msg.role === "assistant" && <div className="avatar">🌟</div>}
              <div className="message-col">
                <div
                  className={`bubble ${msg.role}${isClickable ? " has-debug" : ""}${isSelected ? " debug-selected" : ""}`}
                  onClick={isClickable ? () => onSelectMessage(msg.debugId) : undefined}
                >
                  {msg.content}
                </div>
                {hasButtons && (
                  <div className="ui-action-buttons">
                    {uiAction.buttons.map((btn) => (
                      <button
                        key={btn.value}
                        className="ui-action-btn"
                        disabled={isResolving || loading}
                        onClick={() => onMissionUiAction?.(uiAction.action_id, btn.value)}
                      >
                        {btn.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {loading && (
          <div className="message-row assistant">
            <div className="avatar">🌟</div>
            <div className="bubble assistant typing">
              <span className="dot" />
              <span className="dot" />
              <span className="dot" />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <div className="chat-input-bar">
        <textarea
          ref={textareaRef}
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={lockChat ? "위 선택지 중 하나를 골라줘!" : "메시지를 입력하세요..."}
          rows={1}
          disabled={loading || lockChat}
        />
        <button
          className="send-btn"
          onClick={handleSend}
          disabled={!input.trim() || loading || lockChat}
          aria-label="전송"
        >
          ▶
        </button>
      </div>
    </div>
  );
}
