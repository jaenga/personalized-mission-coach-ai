import { useEffect, useState } from "react";
import missionPreferenceTomato from "../assets/tomato/onboarding/mis.svg";

const ACTIVITY_OPTIONS = [
  "걷기", "물 마시기", "줄넘기", "스쿼트", "스트레칭",
  "채소 먹기", "과일 먹기", "간식 줄이기", "스마트폰 절제",
  "게임 시간 줄이기", "취침 시간 지키기", "손 씻기", "양치하기",
];

const EMPTY_ACTIVITY_SELECTION = [];

const COLORS = {
  appBg: "#FFF3E7",
  heroCardBg: "#FFFCFA",
  sectionCardBg: "#FFFDFC",
  innerActionCardBg: "#FFFFFF",
  searchInputBg: "#FFF8F4",
  strongBorder: "#F2C5BA",
  softBorder: "#F7DDD5",
  inputCardBorder: "#F1D5CC",
  divider: "rgba(227, 93, 73, 0.08)",
  primary: "#E35D49",
  primaryStrong: "#EA6A55",
  mainTitle: "#2C2623",
  sectionTitle: "#3A312D",
  bodyText: "#4F4742",
  descriptionText: "#7B7068",
  weakDescription: "#AAA099",
  iconGray: "#A89C95",
  likeActivityBg: "#FFF1EE",
  likeActivityIcon: "#E35D49",
  dislikeActivityBg: "#F3F0FF",
  dislikeActivityIcon: "#8C78D8",
  defaultChipBg: "#FFF4EE",
  defaultChipBorder: "#F3D9D0",
  defaultChipText: "#7B655D",
  selectedChipBg: "#FFE1D8",
  selectedChipBorder: "#E35D49",
  selectedChipText: "#D95A47",
  buttonText: "#FFFFFF",
  buttonShadow: "rgba(227, 93, 73, 0.18)",
  cardShadow: "rgba(240, 190, 170, 0.08)",
  characterShadow: "rgba(44, 38, 35, 0.18)",
};

function LikeActivityIcon() {
  return (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 20.2s-7.1-4.4-9.2-8.7C1.1 7.9 3.1 4.7 6.5 4.7c2 0 3.6 1.1 4.4 2.7.2.4.8.4 1 0 .8-1.6 2.4-2.7 4.4-2.7 3.4 0 5.4 3.2 3.7 6.8-2 4.3-9 8.7-9 8.7Z"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function DislikeActivityIcon() {
  return (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 3a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17Z"
        stroke="currentColor"
        strokeWidth="2"
      />
      <path d="M7 17 17 7" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}

function ChipGrid({ selected, onToggle }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
      {ACTIVITY_OPTIONS.map((opt) => {
        const active = selected.includes(opt);
        return (
          <button
            key={opt}
            type="button"
            onClick={() => onToggle(opt)}
            className="font-sejong transition active:scale-[0.97]"
            style={{
              fontSize: 12,
              fontWeight: active ? 600 : 400,
              padding: "5px 12px",
              borderRadius: 999,
              background: active ? COLORS.selectedChipBg : COLORS.defaultChipBg,
              color: active ? COLORS.selectedChipText : COLORS.defaultChipText,
              border: `1px solid ${active ? COLORS.selectedChipBorder : COLORS.defaultChipBorder}`,
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

function SelectedKeywordList({ selected, onToggle }) {
  if (selected.length === 0) return null;

  return (
    <>
      <p className="font-sejong mb-2" style={{ fontSize: 12, fontWeight: 500, color: COLORS.sectionTitle, marginTop: 12 }}>
        고른 키워드
      </p>
      <div className="flex flex-wrap gap-1.5">
        {selected.map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => onToggle(item)}
            className="font-sejong inline-flex items-center gap-1 transition active:scale-[0.97]"
            style={{
              fontSize: 12,
              padding: "5px 8px 5px 12px",
              borderRadius: 999,
              background: COLORS.selectedChipBg,
              color: COLORS.selectedChipText,
              border: `1px solid ${COLORS.selectedChipBorder}`,
              fontWeight: 600,
            }}
          >
            {item}
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
              <path d="M2 2 L8 8 M8 2 L2 8" stroke={COLORS.selectedChipText} strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        ))}
      </div>
    </>
  );
}

function SectionCard({ iconBg, icon, title, description, children }) {
  return (
    <div
      style={{
        background: COLORS.sectionCardBg,
        borderRadius: 24,
        padding: "14px 16px 16px",
        border: `1px solid ${COLORS.softBorder}`,
        boxShadow: `0 8px 18px ${COLORS.cardShadow}`,
      }}
    >
      <div className="flex items-start gap-3" style={{ marginBottom: 10 }}>
        <span
          className="inline-flex items-center justify-center flex-shrink-0"
          style={{ width: 40, height: 40, borderRadius: "50%", background: iconBg, color: icon?.props?.color || "currentColor" }}
        >
          {icon}
        </span>
        <div className="flex-1 min-w-0" style={{ paddingTop: 2 }}>
          <p className="font-sejong" style={{ fontSize: 16, fontWeight: 500, color: COLORS.sectionTitle, letterSpacing: "-0.43px" }}>
            {title}
          </p>
          <p className="font-sejong" style={{ fontSize: 12, fontWeight: 400, color: COLORS.descriptionText, letterSpacing: "-0.3px", lineHeight: "17px", marginTop: 1 }}>
            {description}
          </p>
        </div>
      </div>
      {children}
    </div>
  );
}

export default function OnboardingPreferences({
  initialPreferred = EMPTY_ACTIVITY_SELECTION,
  initialDisliked = EMPTY_ACTIVITY_SELECTION,
  onSubmit,
  onSkip,
  onBack,
  loading,
  error,
  embedded = false,
  submitLabel = "저장하기",
  skipLabel = "건너뛰고 나중에 설정할래요",
}) {
  const [preferred, setPreferred] = useState(initialPreferred);
  const [disliked, setDisliked] = useState(initialDisliked);
  const [overlapWarning, setOverlapWarning] = useState(false);

  useEffect(() => {
    setPreferred(initialPreferred);
    setDisliked(initialDisliked);
    setOverlapWarning(false);
  }, [initialPreferred, initialDisliked]);

  function handleSubmit() {
    onSubmit?.({ preferred_activity_keys: preferred, disliked_activity_keys: disliked, restrictions: [] });
  }

  function handlePreferredToggle(keyword) {
    setPreferred((current) => {
      if (current.includes(keyword)) {
        setOverlapWarning(false);
        return current.filter((item) => item !== keyword);
      }
      if (disliked.includes(keyword)) {
        setOverlapWarning(true);
        return current;
      }
      setOverlapWarning(false);
      return [...current, keyword];
    });
  }

  function handleDislikedToggle(keyword) {
    setDisliked((current) => {
      if (current.includes(keyword)) {
        setOverlapWarning(false);
        return current.filter((item) => item !== keyword);
      }
      if (preferred.includes(keyword)) {
        setOverlapWarning(true);
        return current;
      }
      setOverlapWarning(false);
      return [...current, keyword];
    });
  }

  const content = (
    <div className="mobile-frame flex flex-col" style={{ background: COLORS.appBg }}>
      {/* 헤더 */}
      <header
        className="flex items-center justify-between flex-shrink-0"
        style={{
          height: 56,
          paddingInline: 16,
          background: COLORS.heroCardBg,
          backdropFilter: "blur(8px)",
          borderBottom: `1px solid ${COLORS.divider}`,
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
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={COLORS.mainTitle} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M15 6l-6 6 6 6" />
            </svg>
          </button>
        ) : (
          <div style={{ width: 36 }} />
        )}
        <span className="font-sejong" style={{ fontSize: 16, fontWeight: 700, color: COLORS.mainTitle, letterSpacing: "-0.43px" }}>
          미션 취향
        </span>
      </header>

      {/* 본문 */}
      <div
        className="flex-1 overflow-y-auto"
        style={{ paddingInline: 19, paddingTop: 20, paddingBottom: "calc(88px + env(safe-area-inset-bottom))" }}
      >
        {/* 히어로 카드 */}
        <div
          className="relative overflow-hidden"
          style={{
            background: COLORS.heroCardBg,
            borderRadius: 32,
            padding: "18px 20px",
            border: `1.5px solid ${COLORS.strongBorder}`,
            boxShadow: `0 8px 18px ${COLORS.cardShadow}`,
            marginBottom: 14,
            minHeight: 137,
          }}
        >
          <div className="flex items-center justify-between h-full gap-3">
            <div className="flex-1 min-w-0 self-center">
              <h2 className="font-sejong" style={{ fontSize: 18, fontWeight: 700, color: COLORS.mainTitle, letterSpacing: "-0.43px", lineHeight: "21px", marginBottom: 7, wordBreak: "keep-all" }}>
                좋아하는 미션을 알려줘!
              </h2>
              <p className="font-sejong" style={{ fontSize: 12, color: COLORS.descriptionText, fontWeight: 400, letterSpacing: "-0.43px", lineHeight: "20px" }}>
                취향을 기억해서<br />
                딱 맞는 미션을 골라줄게
              </p>
            </div>
            <div className="relative flex-shrink-0" style={{ width: 98, height: 104, marginBottom: -4 }}>
              <img
                src={missionPreferenceTomato}
                alt=""
                draggable="false"
                className="absolute inset-0 select-none pointer-events-none"
                style={{ width: "95%", height: "120%", top: "50%", transform: "translateY(-50%)", objectFit: "contain", zIndex: 2 }}
              />
              <div
                aria-hidden="true"
                className="absolute left-1/2 -translate-x-1/2 rounded-full blur-[3px]"
                style={{ bottom: 8, width: 60, height: 6, zIndex: 1, background: COLORS.characterShadow }}
              />
            </div>
          </div>
        </div>

        {/* 좋아하는 활동 */}
        <div style={{ marginBottom: 12 }}>
          <SectionCard
            iconBg={COLORS.likeActivityBg}
            icon={<span style={{ color: COLORS.likeActivityIcon }}><LikeActivityIcon /></span>}
            title="좋아하는 활동"
            description="자주 해도 괜찮은 활동을 골라줘"
          >
            <ChipGrid
              selected={preferred}
              onToggle={handlePreferredToggle}
            />
            <SelectedKeywordList
              selected={preferred}
              onToggle={handlePreferredToggle}
            />
          </SectionCard>
        </div>

        {/* 피하고 싶은 활동 */}
        <div style={{ marginBottom: 16 }}>
          <SectionCard
            iconBg={COLORS.dislikeActivityBg}
            icon={<span style={{ color: COLORS.dislikeActivityIcon }}><DislikeActivityIcon /></span>}
            title="피하고 싶은 활동"
            description="가능하면 빼줬으면 하는 활동을 골라줘"
          >
            <ChipGrid
              selected={disliked}
              onToggle={handleDislikedToggle}
            />
            <SelectedKeywordList
              selected={disliked}
              onToggle={handleDislikedToggle}
            />
          </SectionCard>
        </div>

        {overlapWarning && (
          <p
            className="font-sejong text-center"
            style={{ fontSize: 12, color: COLORS.primary, letterSpacing: "-0.3px", margin: "-4px 0 14px" }}
          >
            키워드가 겹쳐! 다시 확인해줄래?
          </p>
        )}

        {/* 건너뛰기 */}
        <button
          type="button"
          onClick={onSkip}
          className="block mx-auto font-sejong"
          style={{ fontSize: 12, color: COLORS.descriptionText, letterSpacing: "-0.3px", background: "none", border: "none", cursor: "pointer" }}
        >
          {skipLabel}
        </button>

        {error && (
          <p className="font-sejong text-center" style={{ fontSize: 12, color: COLORS.primary, marginTop: 8 }}>
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
          background: COLORS.appBg,
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
            background: `linear-gradient(180deg, ${COLORS.primaryStrong} 0%, ${COLORS.primary} 100%)`,
            color: COLORS.buttonText,
            border: "none",
            cursor: "pointer",
            boxShadow: `0 8px 18px ${COLORS.buttonShadow}`,
          }}
        >
          {loading && (
            <span className="inline-block w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />
          )}
          {loading ? "저장 중..." : submitLabel}
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
