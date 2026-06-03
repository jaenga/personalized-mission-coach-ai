import { useMemo, useState } from "react";
import tomatoHealth from "../assets/tomato/health/health.png";
import badge from "../assets/tomato/health/badge.png";
import iconHealth from "../assets/tomato/health/icon_health.png";
import spoon from "../assets/tomato/health/spoon.png";

const ALLERGEN_OPTIONS = [
  "우유", "계란", "메밀", "땅콩", "대두", "밀",
  "고등어", "게", "새우", "돼지고기", "복숭아", "토마토",
  "호두", "닭고기", "쇠고기", "오징어", "조개류", "잣",
  "키위", "견과류", "망고", "딸기", "바나나", "갑각류", "아황산류",
];

const CAUTION_FOOD_OPTIONS = [
  "사탕/젤리", "초콜릿", "탄산음료", "아이스크림", "햄버거", "감자튀김",
  "컵라면", "라면", "떡볶이", "피자", "치킨", "과자",
  "달콤한 음료", "핫도그", "도넛", "케이크", "시리얼", "가공육",
  "매운 음식", "튀김", "젤리", "마시멜로", "에너지드링크", "쿠키",
];

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
  primaryLightTint: "#FFF1EC",
  mainTitle: "#2C2623",
  sectionTitle: "#3A312D",
  bodyText: "#4F4742",
  descriptionText: "#7B7068",
  weakDescription: "#AAA099",
  placeholder: "#B2A59E",
  iconGray: "#A89C95",
  allergyBg: "#FFE7E1",
  allergyIcon: "#E35D49",
  reduceFoodBg: "#FFF0E5",
  reduceFoodIcon: "#F07A4A",
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

const ACCENT = {
  bgSelected: COLORS.selectedChipBg,
  textSelected: COLORS.selectedChipText,
  borderSelected: COLORS.selectedChipBorder,
  chipText: COLORS.selectedChipText,
};

function PickerCard({ icon, iconSize = 20, iconBg = COLORS.allergyBg, accentBorder = COLORS.inputCardBorder, accentPlusBg = COLORS.primaryLightTint, accentStroke = COLORS.primary, sectionTitle, subtitle, addLabel, placeholder, options, selected, onToggle, onAddCustom }) {
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState("");
  const [customMode, setCustomMode] = useState(false);
  const [customText, setCustomText] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim();
    if (!q) return options.slice(0, 12);
    return options.filter((o) => o.includes(q)).slice(0, 12);
  }, [options, query]);

  function commitCustom() {
    const t = customText.trim();
    if (!t) {
      setCustomMode(false);
      return;
    }
    onAddCustom(t);
    setCustomText("");
    setCustomMode(false);
  }

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
          style={{ width: 40, height: 40, borderRadius: "50%", background: iconBg }}
        >
          {typeof icon === "string" ? (
            <img src={icon} alt="" className="object-contain" style={{ width: iconSize, height: iconSize }} />
          ) : (
            icon
          )}
        </span>
        <div className="flex-1 min-w-0" style={{ paddingTop: 2 }}>
          <h3
            className="font-sejong"
            style={{
              fontSize: 16,
              fontWeight: 500,
              letterSpacing: "-0.43px",
              color: COLORS.sectionTitle,
            }}
          >
            {sectionTitle}
          </h3>
          {subtitle && (
            <p
              className="font-sejong"
              style={{
                fontSize: 12,
                fontWeight: 400,
                letterSpacing: "-0.3px",
                lineHeight: "17px",
                color: COLORS.descriptionText,
                marginTop: 1,
              }}
            >
              {subtitle}
            </p>
          )}
        </div>
      </div>

      {!expanded ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="w-full flex items-center justify-between transition active:scale-[0.995]"
          style={{
            background: COLORS.innerActionCardBg,
            padding: "14px 16px",
            borderRadius: 18,
            border: `1.5px solid ${accentBorder}`,
          }}
        >
          <span className="flex items-center gap-2">
            <span
              className="inline-flex items-center justify-center rounded-full"
              style={{ width: 24, height: 24, background: accentPlusBg }}
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke={accentStroke} strokeWidth="2" strokeLinecap="round">
                <path d="M6 2 L6 10 M2 6 L10 6" />
              </svg>
            </span>
            <span className="font-sejong" style={{ fontSize: 14, fontWeight: 500, letterSpacing: "-0.43px", color: COLORS.bodyText }}>
              {addLabel}
            </span>
          </span>
          <span className="flex items-center gap-2">
            {selected.length > 0 && (
              <span
                className="font-sejong"
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  padding: "2px 8px",
                  borderRadius: 999,
                  background: ACCENT.bgSelected,
                  color: ACCENT.chipText,
                }}
              >
                {selected.length}
              </span>
            )}
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke={COLORS.iconGray} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 3 L9 7 L5 11" />
            </svg>
          </span>
        </button>
      ) : (
        <div
          className="w-full"
          style={{
            background: COLORS.innerActionCardBg,
            padding: "14px 16px",
            borderRadius: 18,
            border: `1.5px solid ${accentBorder}`,
            minHeight: 200,
          }}
        >
          <div className="flex items-center justify-between mb-3">
            <span className="flex items-center gap-2">
              <span
                className="inline-flex items-center justify-center rounded-full"
                style={{ width: 24, height: 24, background: accentPlusBg }}
              >
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke={accentStroke} strokeWidth="2" strokeLinecap="round">
                  <path d="M6 2 L6 10 M2 6 L10 6" />
                </svg>
              </span>
              <span className="font-sejong" style={{ fontSize: 14, fontWeight: 500, letterSpacing: "-0.43px", color: COLORS.bodyText }}>
                {addLabel}
              </span>
            </span>
            <button
              type="button"
              onClick={() => setExpanded(false)}
              className="transition"
              aria-label="닫기"
              style={{ color: COLORS.iconGray }}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M4 6 L8 10 L12 6" />
              </svg>
            </button>
          </div>

          <div className="relative mb-2">
            <span className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: COLORS.iconGray }} aria-hidden="true">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.5" />
                <path d="M9.5 9.5L12.5 12.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </span>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={placeholder}
              className="health-note-input w-full font-sejong outline-none"
              style={{
                height: 36,
                borderRadius: 999,
                paddingLeft: 32,
                paddingRight: 14,
                background: COLORS.searchInputBg,
                border: `1.5px solid ${COLORS.inputCardBorder}`,
                fontSize: 13,
                letterSpacing: "-0.43px",
                color: COLORS.bodyText,
              }}
            />
          </div>

          <div className="flex items-center justify-end gap-2 mb-3">
            <span className="font-sejong" style={{ fontSize: 11, color: COLORS.descriptionText }}>
              찾는 항목이 없나요?
            </span>
            {!customMode ? (
              <button
                type="button"
                onClick={() => setCustomMode(true)}
                className="font-sejong transition active:scale-[0.97]"
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  padding: "4px 12px",
                  borderRadius: 999,
                  border: `1.5px solid ${COLORS.primary}`,
                  color: COLORS.primary,
                  background: "transparent",
                }}
              >
                직접 입력
              </button>
            ) : (
              <span className="flex items-center gap-1">
                <input
                  autoFocus
                  value={customText}
                  onChange={(e) => setCustomText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      commitCustom();
                    }
                    if (e.key === "Escape") {
                      setCustomMode(false);
                      setCustomText("");
                    }
                  }}
                  placeholder="직접 입력"
                  className="health-note-input font-sejong outline-none"
                  style={{
                    fontSize: 11,
                    padding: "4px 10px",
                    borderRadius: 999,
                    border: `1.5px solid ${COLORS.primary}`,
                    width: 100,
                    color: COLORS.bodyText,
                  }}
                />
                <button
                  type="button"
                  onClick={commitCustom}
                  className="font-sejong"
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    padding: "4px 10px",
                    borderRadius: 999,
                    background: COLORS.primary,
                    color: COLORS.buttonText,
                  }}
                >
                  추가
                </button>
              </span>
            )}
          </div>

          <p className="font-sejong mb-2" style={{ fontSize: 12, fontWeight: 500, color: COLORS.sectionTitle }}>
            추천 {sectionTitle.includes("알레르기") ? "알레르기" : "음식"}
          </p>
          <div className="flex flex-wrap gap-1.5 mb-3">
            {filtered.map((opt) => {
              const isSelected = selected.includes(opt);
              return (
                <button
                  key={opt}
                  type="button"
                  onClick={() => onToggle(opt)}
                  className="font-sejong transition active:scale-[0.97]"
                  style={{
                    fontSize: 12,
                    padding: "5px 12px",
                    borderRadius: 999,
                    background: isSelected ? ACCENT.bgSelected : COLORS.defaultChipBg,
                    color: isSelected ? ACCENT.textSelected : COLORS.defaultChipText,
                    border: `1px solid ${isSelected ? ACCENT.borderSelected : COLORS.defaultChipBorder}`,
                    fontWeight: isSelected ? 600 : 400,
                  }}
                >
                  {opt}
                </button>
              );
            })}
            {filtered.length === 0 && (
              <span className="font-sejong" style={{ fontSize: 12, color: COLORS.weakDescription }}>
                검색 결과 없음
              </span>
            )}
          </div>

          {selected.length > 0 && (
            <>
              <p className="font-sejong mb-2" style={{ fontSize: 12, fontWeight: 500, color: COLORS.sectionTitle }}>
                선택한 {sectionTitle.includes("알레르기") ? "알레르기" : "음식"}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {selected.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => onToggle(s)}
                    className="font-sejong inline-flex items-center gap-1 transition"
                    style={{
                      fontSize: 12,
                      padding: "5px 8px 5px 12px",
                      borderRadius: 999,
                      background: COLORS.selectedChipBg,
                      color: ACCENT.chipText,
                      border: `1px solid ${ACCENT.borderSelected}`,
                      fontWeight: 600,
                    }}
                  >
                    {s}
                    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
                      <path d="M2 2 L8 8 M8 2 L2 8" stroke={ACCENT.chipText} strokeWidth="1.6" strokeLinecap="round" />
                    </svg>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {!expanded && selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          {selected.map((s) => (
            <span
              key={s}
              className="font-sejong inline-flex items-center"
              style={{
                fontSize: 11,
                padding: "3px 10px",
                borderRadius: 999,
                background: COLORS.selectedChipBg,
                color: ACCENT.chipText,
                border: `1px solid ${ACCENT.borderSelected}`,
                fontWeight: 500,
              }}
            >
              {s}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function HealthNote({
  onSubmit,
  onSkip,
  onBack,
  loading,
  initialAllergens = [],
  initialCautionFoods = [],
}) {
  const [allergens, setAllergens] = useState(initialAllergens);
  const [cautionFoods, setCautionFoods] = useState(initialCautionFoods);

  const toggle = (list, setList) => (item) => {
    setList((prev) => (prev.includes(item) ? prev.filter((x) => x !== item) : [...prev, item]));
  };
  const addCustom = (list, setList) => (item) => {
    setList((prev) => (prev.includes(item) ? prev : [...prev, item]));
  };

  function handleSave(e) {
    e?.preventDefault?.();
    onSubmit?.({ allergens, cautionFoods });
  }

  return (
    <div className="mobile-frame flex flex-col" style={{ background: COLORS.appBg }}>
      <style>
        {`
          .health-note-input::placeholder {
            color: ${COLORS.placeholder};
            opacity: 1;
          }
        `}
      </style>
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
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={COLORS.mainTitle} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 6l-6 6 6 6" />
          </svg>
        </button>
        <span
          className="font-sejong"
          style={{ fontSize: 16, fontWeight: 700, color: COLORS.mainTitle, letterSpacing: "-0.43px" }}
        >
          건강 노트
        </span>
      </header>

      <div className="flex-1 overflow-y-auto pb-24 pt-5 space-y-4" style={{ paddingLeft: 19, paddingRight: 19 }}>
        <section
          className="relative"
          style={{
            background: COLORS.heroCardBg,
            height: 137,
            borderRadius: 32,
            padding: "18px 20px",
            border: `1.5px solid ${COLORS.strongBorder}`,
            boxShadow: `0 8px 18px ${COLORS.cardShadow}`,
          }}
        >
          <div className="flex items-center justify-between h-full gap-3">
            <div className="flex-1 min-w-0 self-center">
              <h2
                className="font-sejong"
                style={{
                  fontSize: 18,
                  fontWeight: 700,
                  color: COLORS.mainTitle,
                  letterSpacing: "-0.43px",
                  lineHeight: "21px",
                  marginBottom: 7,
                  wordBreak: "keep-all",
                }}
              >
                알레르기와 줄이고 싶은 <br />음식을 알려줘!
              </h2>
              <p
                className="font-sejong"
                style={{ fontSize: 11, fontWeight: 400, lineHeight: "16px", letterSpacing: "-0.43px", color: COLORS.descriptionText }}
              >
                더 건강하고 안전하게<br />
                미션을 할 수 있도록 도와줄게
              </p>
            </div>
            <div className="relative flex-shrink-0" style={{ width: 98, height: 104, marginBottom: -4 }}>
              <img
                src={badge}
                alt=""
                aria-hidden="true"
                className="absolute z-10"
                style={{ top: -2, left: -8, width: 44, height: 44 }}
              />
              <img
                src={tomatoHealth}
                alt=""
                draggable="false"
                className="absolute inset-0 select-none pointer-events-none"
                style={{ width: "100%", height: "120%", objectFit: "contain", zIndex: 2 }}
              />
              <div
                aria-hidden="true"
                className="absolute left-1/2 -translate-x-1/2 rounded-full blur-[3px]"
                style={{ bottom: 6, width: 60, height: 6, zIndex: 1, background: COLORS.characterShadow }}
              />
            </div>
          </div>
        </section>

        <PickerCard
          icon={iconHealth}
          iconSize={36}
          iconBg={COLORS.allergyBg}
          accentPlusBg={COLORS.allergyBg}
          accentStroke={COLORS.allergyIcon}
          sectionTitle="알레르기 설정"
          subtitle="먹으면 몸이 불편해지는 음식이 있다면 알려줘"
          addLabel="알레르기 항목 추가"
          placeholder="알레르기 검색"
          options={ALLERGEN_OPTIONS}
          selected={allergens}
          onToggle={toggle(allergens, setAllergens)}
          onAddCustom={addCustom(allergens, setAllergens)}
        />

        <PickerCard
          icon={spoon}
          iconSize={36}
          iconBg={COLORS.reduceFoodBg}
          accentPlusBg={COLORS.reduceFoodBg}
          accentStroke={COLORS.reduceFoodIcon}
          sectionTitle="줄이고 싶은 음식"
          subtitle="건강한 습관을 위해 줄이고 싶은 음식을 골라줘"
          addLabel="줄이고 싶은 음식 추가"
          placeholder="줄이고 싶은 음식 검색"
          options={CAUTION_FOOD_OPTIONS}
          selected={cautionFoods}
          onToggle={toggle(cautionFoods, setCautionFoods)}
          onAddCustom={addCustom(cautionFoods, setCautionFoods)}
        />

        <button
          type="button"
          onClick={onSkip}
          className="block mx-auto font-sejong transition pt-1"
          style={{ fontSize: 12, fontWeight: 300, letterSpacing: "-0.43px", color: COLORS.descriptionText }}
        >
          건너뛰고 나중에 설정할래요
        </button>
      </div>

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
          onClick={handleSave}
          disabled={loading}
          className="w-full font-sejong flex items-center justify-center gap-2 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.98]"
          style={{
            height: 48,
            borderRadius: 999,
            fontSize: 18,
            fontWeight: 400,
            letterSpacing: "-0.43px",
            background: `linear-gradient(180deg, ${COLORS.primaryStrong} 0%, ${COLORS.primary} 100%)`,
            boxShadow: `0 8px 18px ${COLORS.buttonShadow}`,
            color: COLORS.buttonText,
          }}
        >
          {loading && (
            <span
              aria-hidden="true"
              className="inline-block w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin"
            />
          )}
          {loading ? "저장 중..." : "저장하기"}
        </button>
      </div>
    </div>
  );
}
