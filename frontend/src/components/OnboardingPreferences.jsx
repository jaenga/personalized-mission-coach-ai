import { useState } from "react";

const ACTIVITY_OPTIONS = [
  "걷기", "물 마시기", "줄넘기", "스쿼트", "스트레칭",
  "채소 먹기", "과일 먹기", "간식 줄이기", "스마트폰 절제",
  "게임 시간 줄이기", "취침 시간 지키기", "손 씻기", "양치하기",
];

function toggleValue(list, value) {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

function ChipGrid({ selected, onToggle, excluding = [] }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {ACTIVITY_OPTIONS.filter((o) => !excluding.includes(o)).map((opt) => {
        const active = selected.includes(opt);
        return (
          <button
            key={opt}
            type="button"
            onClick={() => onToggle(opt)}
            className="font-sejong transition active:scale-[0.97]"
            style={{
              fontSize: 13,
              fontWeight: active ? 700 : 500,
              padding: "7px 16px",
              borderRadius: 999,
              background: active ? "#FFE5DD" : "#FFF8F4",
              color: active ? "#E35D49" : "#6b6864",
              border: `1.5px solid ${active ? "#F2C5BA" : "rgba(227,93,73,0.12)"}`,
              cursor: "pointer",
              letterSpacing: "-0.3px",
            }}
          >
            {opt}
          </button>
        );
      })}
    </div>
  );
}

function SectionCard({ iconBg, icon, title, description, children }) {
  return (
    <div
      style={{
        background: "#FFFFFF",
        borderRadius: 24,
        padding: "16px 18px 18px",
        border: "1px solid rgba(227, 93, 73, 0.10)",
        boxShadow: "0 2px 8px rgba(0,0,0,0.03)",
      }}
    >
      <div className="flex items-center gap-3" style={{ marginBottom: 14 }}>
        <span
          className="inline-flex items-center justify-center flex-shrink-0"
          style={{ width: 38, height: 38, borderRadius: "50%", background: iconBg, fontSize: 18 }}
        >
          {icon}
        </span>
        <div>
          <p className="font-sejong" style={{ fontSize: 15, fontWeight: 700, color: "#1a1a1a", letterSpacing: "-0.43px" }}>
            {title}
          </p>
          <p className="font-sejong" style={{ fontSize: 11, color: "#9a9690", letterSpacing: "-0.3px", marginTop: 1 }}>
            {description}
          </p>
        </div>
      </div>
      {children}
    </div>
  );
}

export default function OnboardingPreferences({ onSubmit, onSkip, onBack, loading, error, embedded = false }) {
  const [preferred, setPreferred] = useState([]);
  const [disliked, setDisliked] = useState([]);

  function handleSubmit() {
    onSubmit?.({ preferred_activity_keys: preferred, disliked_activity_keys: disliked, restrictions: [] });
  }

  const content = (
    <div className="mobile-frame flex flex-col" style={{ background: "#FFF3E7" }}>
      {/* 헤더 */}
      <header
        className="flex items-center justify-between flex-shrink-0"
        style={{
          height: 56,
          paddingInline: 16,
          background: "rgba(255, 248, 240, 0.92)",
          backdropFilter: "blur(8px)",
          borderBottom: "1px solid rgba(227, 93, 73, 0.12)",
        }}
      >
        {onBack ? (
          <button
            type="button"
            onClick={onBack}
            aria-label="뒤로가기"
            className="flex items-center justify-center"
            style={{ width: 36, height: 36, padding: 0, border: "none", background: "transparent", cursor: "pointer" }}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#1a1a1a" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M15 6l-6 6 6 6" />
            </svg>
          </button>
        ) : (
          <div style={{ width: 36 }} />
        )}
        <span className="font-sejong" style={{ fontSize: 16, fontWeight: 700, color: "#1a1a1a", letterSpacing: "-0.43px" }}>
          미션 취향
        </span>
        <div style={{ width: 36 }} />
      </header>

      {/* 본문 */}
      <div
        className="flex-1 overflow-y-auto"
        style={{ paddingInline: 19, paddingTop: 20, paddingBottom: "calc(88px + env(safe-area-inset-bottom))" }}
      >
        {/* 히어로 카드 */}
        <div
          style={{
            background: "#FFFFFF",
            borderRadius: 28,
            padding: "18px 20px",
            border: "1.5px solid #F2C5BA",
            marginBottom: 14,
          }}
        >
          <p className="font-sejong" style={{ fontSize: 18, fontWeight: 700, color: "#1a1a1a", letterSpacing: "-0.43px", lineHeight: "24px" }}>
            좋아하는 미션을 알려줘!
          </p>
          <p className="font-sejong" style={{ fontSize: 12, color: "#9a9690", marginTop: 6, letterSpacing: "-0.3px", lineHeight: "17px" }}>
            취향을 기억해서 딱 맞는 미션을 골라줄게
          </p>
        </div>

        {/* 좋아하는 활동 */}
        <div style={{ marginBottom: 12 }}>
          <SectionCard
            iconBg="#FFE5DD"
            icon="❤️"
            title="좋아하는 활동"
            description="자주 해도 괜찮은 활동을 골라줘"
          >
            <ChipGrid
              selected={preferred}
              onToggle={(k) => setPreferred((p) => toggleValue(p, k))}
              excluding={disliked}
            />
          </SectionCard>
        </div>

        {/* 피하고 싶은 활동 */}
        <div style={{ marginBottom: 16 }}>
          <SectionCard
            iconBg="#F0F4FF"
            icon="🙅"
            title="피하고 싶은 활동"
            description="가능하면 빼줬으면 하는 활동을 골라줘"
          >
            <ChipGrid
              selected={disliked}
              onToggle={(k) => setDisliked((p) => toggleValue(p, k))}
              excluding={preferred}
            />
          </SectionCard>
        </div>

        {/* 건너뛰기 */}
        <button
          type="button"
          onClick={onSkip}
          className="block mx-auto font-sejong"
          style={{ fontSize: 12, color: "#b0aca8", letterSpacing: "-0.3px", background: "none", border: "none", cursor: "pointer" }}
        >
          건너뛰고 나중에 설정할래요
        </button>

        {error && (
          <p className="font-sejong text-center" style={{ fontSize: 12, color: "#E35D49", marginTop: 8 }}>
            {error}
          </p>
        )}
      </div>

      {/* 하단 저장 버튼 */}
      <div
        className="absolute left-0 right-0 px-4 pt-3"
        style={{
          bottom: 0,
          paddingBottom: "calc(16px + env(safe-area-inset-bottom))",
          background: "linear-gradient(to top, #FFF8F0 60%, rgba(255,248,240,0))",
        }}
      >
        <button
          type="button"
          onClick={handleSubmit}
          disabled={loading}
          className="font-sejong w-full flex items-center justify-center gap-2 transition-all duration-200 disabled:opacity-50"
          style={{
            height: 48,
            borderRadius: 999,
            fontSize: 17,
            fontWeight: 400,
            letterSpacing: "-0.43px",
            background: "#E35D49",
            color: "#FFFFFF",
            border: "none",
            cursor: "pointer",
            boxShadow: "0 4px 14px rgba(227,93,73,0.3)",
          }}
        >
          {loading && (
            <span className="inline-block w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />
          )}
          {loading ? "저장 중..." : "저장하기"}
        </button>
      </div>
    </div>
  );

  if (embedded) return content;

  return (
    <div className="modal-backdrop soft">
      {content}
    </div>
  );
}
