import { useEffect, useMemo, useState } from "react";
// import main2 from "../assets/tomato/home/main2.png";
import home1 from "../assets/tomato/home/home1.svg";
import gachaTomi from "../assets/tomato/home/gacha_tomi.svg";
import homeTomiRun from "../assets/tomato/home/home_tomirun.svg";
import face from "../assets/tomato/home/face.png";
import danger from "../assets/tomato/home/danger.png";
import heart from "../assets/tomato/_shared/heart.png";
import ticket from "../assets/tomato/_shared/ticket.png";
import check from "../assets/tomato/home/check.png";
import flag from "../assets/tomato/home/flag.png";

/* ─────────────────────────────────────────────────────────
   호격 조사 (받침 있으면 "아", 없으면 "야")
   ───────────────────────────────────────────────────────── */
function vocativeParticle(name) {
  if (!name) return "야";
  const last = name.charCodeAt(name.length - 1);
  if (last < 0xac00 || last > 0xd7a3) return "야";
  const jong = (last - 0xac00) % 28;
  return jong === 0 ? "야" : "아";
}

function getGreetingName(name) {
  const trimmed = String(name || "").trim();
  if (!trimmed) return "";
  const parts = trimmed.split(/\s+/);
  if (parts.length > 1) return parts[parts.length - 1];
  return trimmed.length >= 3 ? trimmed.slice(1) : trimmed;
}

function formatTodayKor(date) {
  return `${date.getMonth() + 1}월 ${date.getDate()}일`;
}

function parseMissionGuideSections(text) {
  const normalized = String(text || "")
    .replace(/\\n|\/n/g, "\n")
    .replace(/\s*(\[[^\]]+\])/g, "\n$1")
    .trim();

  if (!normalized) return [];

  const parts = normalized
    .split(/(\[[^\]]+\])/g)
    .map((part) => part.trim())
    .filter(Boolean);
  const sections = [];
  let current = null;

  parts.forEach((part) => {
    if (/^\[[^\]]+\]$/.test(part)) {
      if (current) sections.push(current);
      current = { label: part, body: "" };
      return;
    }

    if (!current) {
      current = { label: "", body: part };
      return;
    }

    current.body = [current.body, part].filter(Boolean).join("\n");
  });

  if (current) sections.push(current);
  return sections;
}

/* ─────────────────────────────────────────────────────────
   LevelRing — 레벨과 경험치 표시
   ───────────────────────────────────────────────────────── */
export function LevelRing({ level = 3, currentXp = 60, maxXp = 100, size = 56 }) {
  const stroke = 4;
  const r = size / 2 - stroke / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(1, currentXp / maxXp));
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="#FFFFFF" stroke="#FCE0DA" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="#E35D49"
          strokeWidth={stroke}
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct)}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dashoffset 0.6s ease" }}
        />
      </svg>
      <span
        className="absolute inset-0 flex items-center justify-center font-noto"
        style={{ color: "#E35D49", fontSize: 11, fontWeight: 700, letterSpacing: "-0.43px" }}
      >
        Lv.{level}
      </span>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   소형 스파클 
   ───────────────────────────────────────────────────────── */
const SPARKLE_DOTS = [
  { x: 12,  y: 30,  size: 10, delay: 0,    color: "#A7DAA7" },
  { x: 305, y: 30,  size: 8,  delay: 0.4,  color: "#F2A8A0" },
  { x: 6,   y: 130, size: 8,  delay: 0.8,  color: "#FFD56B" },
  { x: 320, y: 100, size: 9,  delay: 0.2,  color: "#9DC9E8" },
  { x: 26,  y: 220, size: 7,  delay: 1.0,  color: "#FFAE6B" },
  { x: 310, y: 240, size: 9,  delay: 0.6,  color: "#A7DAA7" },
];

function SparkleField() {
  return (
    <>
      {SPARKLE_DOTS.map((s, i) => (
        <svg
          key={i}
          className="sparkle absolute pointer-events-none"
          style={{
            left: s.x,
            top: s.y,
            width: s.size,
            height: s.size,
            animationDelay: `${s.delay}s`,
          }}
          viewBox={`0 0 ${s.size} ${s.size}`}
          aria-hidden="true"
        >
          <path
            d={`M${s.size / 2} 0 L${s.size * 0.6} ${s.size * 0.4} L${s.size} ${s.size / 2} L${s.size * 0.6} ${s.size * 0.6} L${s.size / 2} ${s.size} L${s.size * 0.4} ${s.size * 0.6} L0 ${s.size / 2} L${s.size * 0.4} ${s.size * 0.4} Z`}
            fill={s.color}
          />
        </svg>
      ))}
    </>
  );
}

/* ─────────────────────────────────────────────────────────
   Calendar — 주간/월간 토글, 성공 날짜에 face.png 표시
   ───────────────────────────────────────────────────────── */

function ymd(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function buildMonthMatrix(year, month /* 0-indexed */) {
  const first = new Date(year, month, 1);
  // 월요일 시작: 일요일=0 → 6, 월=1 → 0, 화=2 → 1 ...
  const startOffset = (first.getDay() + 6) % 7;
  const lastDay = new Date(year, month + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < startOffset; i++) cells.push(null);
  for (let d = 1; d <= lastDay; d++) cells.push(new Date(year, month, d));
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

function buildWeek(today) {
  const start = new Date(today);
  // 월요일 시작 (월=1, 일=0 → 일요일이면 -6, 그 외엔 -(day-1))
  const offset = (today.getDay() + 6) % 7;
  start.setDate(today.getDate() - offset);
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return d;
  });
}

const WEEK_LABELS_MON = ["월", "화", "수", "목", "금", "토", "일"];

function MonthCalendar({ year, month, successSet, today, onPrev, onNext }) {
  const cells = useMemo(() => buildMonthMatrix(year, month), [year, month]);
  const todayKey = ymd(today);
  return (
    <div className="font-sejong" style={{ letterSpacing: "-0.43px" }}>
      <div className="flex items-center justify-between mb-2 px-1">
        <button
          type="button"
          onClick={onPrev}
          aria-label="이전 달"
          className="flex items-center justify-center"
          style={{
            width: 24, height: 24, padding: 0, border: "none",
            background: "transparent", color: "#75726e", fontSize: 16, cursor: "pointer",
          }}
        >
          ‹
        </button>
        <span style={{ fontSize: 13, fontWeight: 700 }}>{`${year}년 ${month + 1}월`}</span>
        <button
          type="button"
          onClick={onNext}
          aria-label="다음 달"
          className="flex items-center justify-center"
          style={{
            width: 24, height: 24, padding: 0, border: "none",
            background: "transparent", color: "#75726e", fontSize: 16, cursor: "pointer",
          }}
        >
          ›
        </button>
      </div>
      <div className="grid grid-cols-7 gap-y-1 text-center">
        {WEEK_LABELS_MON.map((d, i) => (
          <div key={d} style={{ fontSize: 11, color: i === 6 ? "#E35D49" : "#75726e" }}>
            {d}
          </div>
        ))}
        {cells.map((date, idx) => {
          if (!date) return <div key={`e${idx}`} />;
          const key = ymd(date);
          const isToday = key === todayKey;
          const success = successSet.has(key);
          return (
            <div
              key={key}
              className="flex flex-col items-center justify-center"
              style={{ height: 36 }}
            >
              <div
                className="flex items-center justify-center"
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: "50%",
                  background: isToday ? "#FFE9D2" : "transparent",
                  color: isToday ? "#E35D49" : "#000",
                  fontSize: 12,
                  position: "relative",
                  boxShadow: "none",
                }}
              >
                {success ? (
                  <img
                    src={face}
                    alt=""
                    className="select-none pointer-events-none"
                    style={{ width: 22, height: 22, objectFit: "contain" }}
                  />
                ) : (
                  <span>{date.getDate()}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function WeekStrip({ today, successSet }) {
  const week = useMemo(() => buildWeek(today), [today]);
  const todayKey = ymd(today);
  return (
    <div className="flex justify-between" style={{ paddingInline: 4 }}>
      {week.map((d) => {
        const key = ymd(d);
        const success = successSet.has(key);
        const isToday = key === todayKey;
        return (
          <div key={key} className="flex flex-col items-center" style={{ width: 36, minHeight: 66 }}>
            <span
              className="font-sejong"
              style={{ fontSize: 12, fontWeight: 700, color: "#000", letterSpacing: "-0.43px" }}
            >
              {WEEK_LABELS_MON[(d.getDay() + 6) % 7]}
            </span>
            <div
              className="flex items-center justify-center mt-1"
              style={{
                width: 32,
                height: 32,
                borderRadius: "50%",
                background: isToday ? "#FFE9D2" : "transparent",
                boxShadow: "none",
              }}
            >
              {success ? (
                <img src={face} alt="" style={{ width: 25, height: 25, objectFit: "contain" }} />
              ) : (
                <span
                  style={{
                    width: 31,
                    height: 31,
                    borderRadius: "50%",
                    background: isToday ? "#FFE9D2" : "rgba(255, 233, 210, 0.78)",
                    display: "inline-block",
                  }}
                />
              )}
            </div>
            {isToday && (
              <span
                className="font-sejong mt-1"
                style={{ fontSize: 10, fontWeight: 700, color: "#E35D49", letterSpacing: "-0.43px" }}
              >
                오늘
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   BottomNav — 5개 메뉴 (홈, 코치, 배움, 랭킹, 설정)
   ───────────────────────────────────────────────────────── */
function HomeIcon({ active }) {
  const stroke = active ? "#E35D49" : "#A6A29D";
  const fill = active ? "#E35D49" : "none";
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill={fill} stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 11l9-8 9 8" fill="none" />
      <path d="M5 10v10h14V10" />
    </svg>
  );
}
function ChatIcon({ active }) {
  const stroke = active ? "#E35D49" : "#A6A29D";
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12a8 8 0 1 1-3.5-6.6L21 4l-1 4.5A8 8 0 0 1 21 12z" />
      <circle cx="9" cy="12" r="1" fill={stroke} stroke="none" />
      <circle cx="13" cy="12" r="1" fill={stroke} stroke="none" />
      <circle cx="17" cy="12" r="1" fill={stroke} stroke="none" />
    </svg>
  );
}
function BookIcon({ active }) {
  const stroke = active ? "#E35D49" : "#A6A29D";
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 4h7a3 3 0 0 1 3 3v13a2 2 0 0 0-2-2H4z" />
      <path d="M20 4h-3a3 3 0 0 0-3 3v13a2 2 0 0 1 2-2h4z" />
    </svg>
  );
}
function TrophyIcon({ active }) {
  const stroke = active ? "#E35D49" : "#A6A29D";
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 4h8v5a4 4 0 0 1-8 0z" />
      <path d="M5 5h3v3a3 3 0 0 1-3-3z" />
      <path d="M19 5h-3v3a3 3 0 0 0 3-3z" />
      <path d="M10 14h4l-1 4h-2z" />
      <path d="M8 20h8" />
    </svg>
  );
}
function GearIcon({ active }) {
  const stroke = active ? "#E35D49" : "#A6A29D";
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </svg>
  );
}

const NAV_ITEMS = [
  { key: "home",     label: "홈",   Icon: HomeIcon },
  { key: "coach",    label: "코치", Icon: ChatIcon },
  { key: "learn",    label: "배움", Icon: BookIcon },
  { key: "rank",     label: "랭킹", Icon: TrophyIcon },
  { key: "settings", label: "설정", Icon: GearIcon },
];

export function BottomNav({ active = "home", onChange }) {
  return (
    <nav
      className="absolute left-0 right-0 flex items-center justify-around"
      style={{
        bottom: 0,
        zIndex: 40,
        height: "calc(72px + env(safe-area-inset-bottom))",
        paddingBottom: "env(safe-area-inset-bottom)",
        background: "rgba(255, 255, 255, 0.95)",
        borderTop: "1px solid rgba(227, 93, 73, 0.15)",
        backdropFilter: "blur(8px)",
      }}
    >
      {NAV_ITEMS.map(({ key, label, Icon }) => {
        const isActive = active === key;
        return (
          <button
            key={key}
            type="button"
            onClick={() => onChange?.(key)}
            className="flex flex-col items-center justify-center transition-transform active:scale-95"
            style={{
              width: 60,
              height: 72,
              padding: 0,
              border: "none",
              background: "transparent",
            }}
          >
            <Icon active={isActive} />
            <span
              className="font-sejong mt-1"
              style={{
                fontSize: 11,
                color: isActive ? "#E35D49" : "#A6A29D",
                fontWeight: isActive ? 700 : 400,
                letterSpacing: "-0.43px",
              }}
            >
              {label}
            </span>
          </button>
        );
      })}
    </nav>
  );
}

/* ─────────────────────────────────────────────────────────
   Home — 메인 페이지
   ───────────────────────────────────────────────────────── */
export default function Home({
  studentName = "민준",
  level = 3,
  currentXp = 12,
  maxXp = 20,
  streakDays = 0,
  ticketCount = 2,
  heartCount = 4,
  todayMission = { title: "15분 책 읽기", description: "", done: false },
  successDates = [],
  onNavigate,
}) {
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("home");
  const [expOpen, setExpOpen] = useState(false);
  const [missionFlipped, setMissionFlipped] = useState(false);
  const today = useMemo(() => new Date(), []);
  const [viewYM, setViewYM] = useState(() => ({ year: today.getFullYear(), month: today.getMonth() }));
  const greetingName = getGreetingName(studentName);
  const particle = vocativeParticle(greetingName);

  const monthSuccessCount = useMemo(() => {
    const prefix = `${viewYM.year}-${String(viewYM.month + 1).padStart(2, "0")}-`;
    return successDates.filter((d) => d.startsWith(prefix)).length;
  }, [successDates, viewYM]);

  const weekRange = useMemo(() => {
    const offset = (today.getDay() + 6) % 7; // 월요일 시작
    const mon = new Date(today);
    mon.setDate(today.getDate() - offset);
    const sun = new Date(mon);
    sun.setDate(mon.getDate() + 6);
    return `${mon.getMonth() + 1}월 ${mon.getDate()}일~${sun.getMonth() + 1}월 ${sun.getDate()}일`;
  }, [today]);
  const successSet = useMemo(() => new Set(successDates), [successDates]);

  const missionPct = todayMission.done ? 1 : 0;
  const missionGuide =
    todayMission.description?.trim() ||
    "미션 설명을 아직 불러오지 못했어. 잠시 후 다시 확인해줘!";
  const missionGuideSections = useMemo(
    () => parseMissionGuideSections(missionGuide),
    [missionGuide],
  );

  useEffect(() => {
    setMissionFlipped(false);
  }, [todayMission.title, todayMission.description]);

  function handleNav(key) {
    setActiveTab(key);
    onNavigate?.(key);
  }

  return (
    <div
      className="mobile-frame"
      style={{ background: "#fdefea" }}
    >
      <div
        className="absolute inset-0 overflow-y-auto"
        style={{ paddingBottom: "calc(88px + env(safe-area-inset-bottom))" }}
      >
        {/* 상단: 레벨 링(좌) + 뱃지(우) — 다이나믹 아일랜드와 겹치지 않게 좌우 분리 */}
        <div
          className="relative mt-4 flex items-start justify-between"
          style={{ paddingInline: 19 }}
        >
          <button
            type="button"
            onClick={() => setExpOpen((v) => !v)}
            aria-expanded={expOpen}
            aria-label={`레벨 ${level} EXP ${currentXp}/${maxXp}`}
            className="transition-transform active:scale-95"
            style={{ background: "transparent", border: "none", padding: 0, cursor: "pointer" }}
          >
            <LevelRing level={level} currentXp={currentXp} maxXp={maxXp} size={38} />
          </button>
          <div className="flex gap-1.5">
            <button
              type="button"
              onClick={() => onNavigate?.("draw")}
              aria-label={`뽑기권 ${ticketCount}개 — 뽑기 화면으로`}
              className="flex items-center gap-1 font-sejong transition-transform active:scale-95"
              style={{
                background: "rgba(255, 218, 137, 0.5)",
                borderRadius: 50,
                paddingInline: 8,
                height: 24,
                fontSize: 12,
                border: "none",
                cursor: "pointer",
              }}
            >
              <img src={ticket} alt="" style={{ width: 12, height: 12 }} />
              {ticketCount}
            </button>
            <button
              type="button"
              onClick={() => { window.location.hash = "#game"; }}
              aria-label={`하트 ${heartCount}개 — 토미랑 달리기 게임으로`}
              className="flex items-center gap-1 font-sejong"
              style={{
                background: "rgba(252, 228, 225, 0.7)",
                borderRadius: 50,
                paddingInline: 8,
                height: 24,
                fontSize: 12,
                border: "none",
                cursor: "pointer",
              }}
            >
              <img src={heart} alt="" style={{ width: 12, height: 12 }} />
              {heartCount}
            </button>
          </div>

          {/* 레벨 링 누르면 펼쳐지는 EXP 상세 팝오버 */}
          <div
            className="absolute"
            style={{
              left: 19,
              top: 52,
              width: 220,
              padding: "10px 14px",
              borderRadius: 18,
              background: "rgba(255, 255, 255, 0.95)",
              border: "1px solid rgba(227, 93, 73, 0.4)",
              boxShadow: "0 4px 12px rgba(0,0,0,0.06)",
              opacity: expOpen ? 1 : 0,
              transform: expOpen ? "translateY(0)" : "translateY(-6px)",
              pointerEvents: expOpen ? "auto" : "none",
              transition: "opacity 0.2s ease, transform 0.2s ease",
              zIndex: 10,
            }}
          >
            <div className="flex flex-col gap-1">
              <div className="flex items-baseline justify-between font-sejong">
                <span style={{ fontSize: 12, color: "#75726e", letterSpacing: "-0.43px" }}>
                  Lv.{level} EXP
                </span>
                <span style={{ fontSize: 12, color: "#000", letterSpacing: "-0.43px" }}>
                  {currentXp}/{maxXp}
                </span>
              </div>
              <div className="rounded-full overflow-hidden" style={{ height: 8, background: "#FCE0DA" }}>
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.min(1, currentXp / maxXp) * 100}%`,
                    background: "#E35D49",
                    transition: "width 0.6s ease",
                  }}
                />
              </div>
            </div>
          </div>
        </div>

        {/* 인사말 + 연속일 */}
        <div className="mt-5 flex items-start justify-between" style={{ paddingInline: 24 }}>
          <div>
            <h1
              className="font-jeju"
              style={{
                fontSize: 26,
                color: "#E35D49",
                letterSpacing: "-0.43px",
                lineHeight: "32px",
              }}
            >
              안녕, {greetingName}{particle}!
            </h1>
            <p
              className="font-sejong mt-1"
              style={{
                fontSize: 15,
                color: "#000",
                letterSpacing: "-0.43px",
                lineHeight: "22px",
              }}
            >
              오늘도 힘내보자~
            </p>
          </div>
          <div
            className="flex flex-col items-center justify-center"
            style={{
              display: streakDays > 0 ? "flex" : "none",
              width: 76,
              height: 65,
              borderRadius: 25,
              background: "rgba(255, 255, 255, 0.7)",
              border: "1px solid rgba(227, 93, 73, 0.4)",
            }}
          >
            <div className="flex items-center gap-1">
              <img src={danger} alt="" style={{ width: 18, height: 18 }} />
              <span
                className="font-sejong"
                style={{ fontSize: 18, fontWeight: 700, color: "#000" }}
              >
                {streakDays}
              </span>
            </div>
            <span
              className="font-sejong"
              style={{ fontSize: 11, color: "#000", letterSpacing: "-0.43px" }}
            >
              일 연속!
            </span>
          </div>
        </div>

        {/* 메인 캐릭터 + 스파클 */}
        <div className="relative mx-auto mt-4" style={{ width: 340, height: 290 }}>
          <SparkleField />
          {/*
          <img
            src={main2}
            alt="토미"
            draggable="false"
            className="absolute select-none pointer-events-none"
            style={{
              left: 21,
              top: 0,
              width: 298,
              height: 280,
              objectFit: "contain",
            }}
          />
          */}
          <img
            src={home1}
            alt="토미"
            draggable="false"
            className="absolute select-none pointer-events-none"
            style={{
              left: 20,
              top: 10,
              width: 280,
              height: 260,
              objectFit: "contain",
            }}
          />
          <div
            aria-hidden="true"
            className="absolute"
            style={{
              left: "50%",
              top: 240,
              transform: "translateX(-50%)",
              width: 170,
              height: 24,
              background:
                "radial-gradient(ellipse at center, rgba(0,0,0,0.22) 0%, rgba(0,0,0,0.12) 40%, rgba(0,0,0,0) 75%)",
              filter: "blur(5px)",
              pointerEvents: "none",
            }}
          />
        </div>

        {/* 오늘의 미션 카드 */}
        <button
          type="button"
          className="mx-auto mt-5 block text-left transition-transform active:scale-[0.99]"
          onClick={() => setMissionFlipped((v) => !v)}
          aria-pressed={missionFlipped}
          aria-label={missionFlipped ? "오늘의 미션 보기" : "오늘의 미션 수행 방법 보기"}
          style={{
            width: 315,
            height: 135,
            border: "none",
            padding: 0,
            background: "transparent",
            perspective: 1000,
            cursor: "pointer",
          }}
        >
          <div
            className="relative h-full w-full"
            style={{
              transformStyle: "preserve-3d",
              transition: "transform 0.55s cubic-bezier(0.2, 0.8, 0.2, 1)",
              transform: missionFlipped ? "rotateY(180deg)" : "rotateY(0deg)",
            }}
          >
            <div
              className="absolute inset-0"
              style={{
                borderRadius: 20,
                background: "rgba(255, 255, 255, 0.5)",
                border: "1px solid rgba(227, 93, 73, 0.22)",
                padding: "17px 20px 18px",
                backfaceVisibility: "hidden",
                WebkitBackfaceVisibility: "hidden",
                boxShadow: "0 6px 14px rgba(80, 60, 40, 0.04)",
              }}
            >
              <div className="flex items-baseline justify-between">
                <span
                  className="font-sejong"
                  style={{ fontSize: 14, color: "#E35D49", letterSpacing: "-0.43px" }}
                >
                  오늘의 미션
                </span>
                <span
                  className="font-sejong"
                  style={{ fontSize: 12, color: "#75726e", letterSpacing: "-0.43px" }}
                >
                  {formatTodayKor(today)}
                </span>
              </div>
              <div
                className="mt-3 flex items-start"
                style={{ gap: 10 }}
              >
                <img
                  src={flag}
                  alt=""
                  style={{ width: 25, height: 25, objectFit: "contain", flexShrink: 0, marginTop: 2 }}
                />
                <span
                  style={{
                    fontFamily: '"IM_Hyemin", "SejongGeulggot", sans-serif',
                    flex: 1,
                    minWidth: 0,
                    fontSize: 19,
                    fontWeight: 700,
                    letterSpacing: "-0.43px",
                    lineHeight: "27px",
                    wordBreak: "keep-all",
                    overflowWrap: "normal",
                  }}
                >
                  {todayMission.title}
                </span>
              </div>
              <div
                className="mt-3 rounded-full overflow-hidden"
                style={{ height: 8, background: "#FCE0DA" }}
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${missionPct * 100}%`,
                    background: "#E35D49",
                    transition: "width 0.6s ease",
                  }}
                />
              </div>
            </div>

            <div
              className="absolute inset-0"
              style={{
                borderRadius: 20,
                background: "rgba(255, 255, 255, 0.5)",
                border: "1px solid rgba(227, 93, 73, 0.22)",
                padding: "16px 18px",
                backfaceVisibility: "hidden",
                WebkitBackfaceVisibility: "hidden",
                transform: "rotateY(180deg)",
                boxShadow: "0 6px 14px rgba(80, 60, 40, 0.04)",
              }}
            >
              <div className="flex items-center justify-between">
                <span
                  className="font-sejong"
                  style={{ fontSize: 14, fontWeight: 700, color: "#E35D49", letterSpacing: "-0.43px" }}
                >
                  수행 방법
                </span>
                <span
                  className="font-sejong"
                  style={{ fontSize: 12, color: "#75726e", letterSpacing: "-0.43px" }}
                >
                  {formatTodayKor(today)}
                </span>
              </div>
              <div
                className="font-sejong mt-3"
                style={{
                  maxHeight: 80,
                  overflowY: "auto",
                  fontSize: 14,
                  lineHeight: "21px",
                  color: "#2f2c28",
                  letterSpacing: "-0.43px",
                  wordBreak: "keep-all",
                  overflowWrap: "break-word",
                }}
              >
                {missionGuideSections.map((section, index) => (
                  <div
                    key={`${section.label}-${index}`}
                    style={{ marginBottom: index === missionGuideSections.length - 1 ? 0 : 10 }}
                  >
                    {section.label && (
                      <strong
                        style={{
                          display: "block",
                          marginBottom: 3,
                          fontWeight: 800,
                          color: "#2f2c28",
                        }}
                      >
                        {section.label}
                      </strong>
                    )}
                    {section.body && (
                      <span style={{ display: "block", whiteSpace: "pre-line" }}>
                        {section.body}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </button>

        {/* 이번 주 기록 카드 */}
        <div
          className="mx-auto mt-3"
          style={{
            width: 315,
            borderRadius: 18,
            background: "rgba(255, 255, 255, 0.5)",
            border: "1px solid rgba(227, 93, 73, 0.22)",
            padding: "13px 18px 8px",
            boxShadow: "0 6px 14px rgba(80, 60, 40, 0.04)",
          }}
        >
          <div className="flex items-baseline justify-between">
            <span
              className="font-sejong"
              style={{ fontSize: 13, fontWeight: 700, color: "#E35D49", letterSpacing: "-0.43px" }}
            >
              이번 주 기록
            </span>
            <span
              className="font-sejong"
              style={{ fontSize: 11, color: "#75726e", letterSpacing: "-0.43px" }}
            >
              {weekRange}
            </span>
          </div>

          <div className="mt-3">
            <WeekStrip today={today} successSet={successSet} />
          </div>

          <button
            type="button"
            onClick={() => setCalendarOpen((v) => !v)}
            aria-label={calendarOpen ? "캘린더 접기" : "캘린더 전체 보기"}
            className="mt-1 mx-auto flex items-center justify-center transition-transform active:scale-95"
            style={{
              width: 20,
              height: 18,
              borderRadius: 999,
              background: "transparent",
              border: "none",
              color: "#e79777",
              padding: 0,
              cursor: "pointer",
            }}
          >
            <span
              aria-hidden="true"
              style={{
                display: "inline-block",
                width: 10,
                height: 10,
                borderRight: "2px solid currentColor",
                borderBottom: "2px solid currentColor",
                transform: calendarOpen ? "rotate(225deg) translate(-2px, -2px)" : "rotate(45deg) translate(-2px, -2px)",
                transition: "transform 0.3s ease",
              }}
            />
          </button>

          {/* 펼쳐지는 월간 캘린더 */}
          <div
            style={{
              maxHeight: calendarOpen ? 400 : 0,
              overflow: "hidden",
              transition: "max-height 0.4s ease, opacity 0.3s ease",
              opacity: calendarOpen ? 1 : 0,
              marginTop: calendarOpen ? 12 : 0,
            }}
          >
            <MonthCalendar
              year={viewYM.year}
              month={viewYM.month}
              successSet={successSet}
              today={today}
              onPrev={() =>
                setViewYM(({ year, month }) =>
                  month === 0 ? { year: year - 1, month: 11 } : { year, month: month - 1 }
                )
              }
              onNext={() =>
                setViewYM(({ year, month }) =>
                  month === 11 ? { year: year + 1, month: 0 } : { year, month: month + 1 }
                )
              }
            />

            {/* 캘린더 아래 통계 카드 */}
            <div className="mt-4 flex gap-2">
              <div
                className="flex-1 flex flex-col items-start font-sejong"
                style={{
                  padding: "10px 14px",
                  borderRadius: 18,
                  background: "rgba(255, 255, 255, 0.7)",
                  border: "1px solid rgba(227, 93, 73, 0.3)",
                  letterSpacing: "-0.43px",
                }}
              >
                <span style={{ fontSize: 12, color: "#75726e" }}>연속 기록</span>
                <span className="mt-1 flex items-center gap-1" style={{ fontSize: 18, fontWeight: 700 }}>
                  {streakDays}일
                  <img src={danger} alt="" style={{ width: 18, height: 18 }} />
                </span>
              </div>
              <div
                className="flex-1 flex flex-col items-start font-sejong"
                style={{
                  padding: "10px 14px",
                  borderRadius: 18,
                  background: "rgba(255, 255, 255, 0.7)",
                  border: "1px solid rgba(227, 93, 73, 0.3)",
                  letterSpacing: "-0.43px",
                }}
              >
                <span style={{ fontSize: 12, color: "#75726e" }}>완료 미션</span>
                <span className="mt-1 flex items-center gap-1" style={{ fontSize: 18, fontWeight: 700 }}>
                  {monthSuccessCount}개
                  <img src={check} alt="" style={{ width: 18, height: 18 }} />
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* 뽑기 바로가기 배너 */}
        <button
          type="button"
          onClick={() => onNavigate?.("draw")}
          aria-label="뽑기 화면으로 이동"
          className="mx-auto mt-3 block text-left transition-transform active:scale-[0.99]"
          style={{
            position: "relative",
            width: 315,
            minHeight: 126,
            overflow: "hidden",
            borderRadius: 22,
            border: "1px solid rgba(227, 93, 73, 0.22)",
            background: "rgba(255, 255, 255, 0.5)",
            boxShadow: "0 6px 14px rgba(80, 60, 40, 0.04)",
            padding: "16px 17px 14px",
            cursor: "pointer",
          }}
        >
          <div className="relative" style={{ minHeight: 96 }}>
            <div style={{ width: 170, position: "relative", zIndex: 2 }}>
              <h2
                style={{
                  fontFamily: '"IM_Hyemin", "SejongGeulggot", sans-serif',
                  fontSize: 20,
                  fontWeight: 700,
                  lineHeight: "27px",
                  color: "#1f1f1f",
                  letterSpacing: "-0.43px",
                  wordBreak: "keep-all",
                }}
              >
                토미와 함께
                <br />
                오늘의 뽑기!
              </h2>
              <p
                className="font-sejong mt-1"
                style={{
                  color: "#75726e",
                  fontSize: 12,
                  fontWeight: 700,
                  lineHeight: "17px",
                  letterSpacing: "-0.43px",
                  wordBreak: "keep-all",
                }}
              >
                작은 습관을 모아
                <br />
                선물을 뽑아보세요!
              </p>
            </div>
            <img
              src={gachaTomi}
              alt=""
              draggable="false"
              className="absolute select-none pointer-events-none"
              style={{
                right: -11,
                bottom: -7,
                width: 118,
                height: 96,
                objectFit: "contain",
              }}
            />
          </div>

        </button>

        {/* 게임 바로가기 배너 */}
        <button
          type="button"
          onClick={() => onNavigate?.("game")}
          aria-label="토미랑 달리기 게임으로 이동"
          className="mx-auto mt-3 block text-left transition-transform active:scale-[0.99]"
          style={{
            position: "relative",
            width: 315,
            height: 126,
            overflow: "hidden",
            borderRadius: 20,
            border: "1px solid rgba(227, 93, 73, 0.22)",
            background: "rgba(255, 255, 255, 0.5)",
            boxShadow: "0 6px 14px rgba(80, 60, 40, 0.04)",
            padding: 0,
            cursor: "pointer",
          }}
        >
          <img
            src={homeTomiRun}
            alt=""
            draggable="false"
            className="absolute inset-0 h-full w-full select-none pointer-events-none"
            style={{
              objectFit: "cover",
              objectPosition: "62% center",
            }}
          />
          <div
            className="relative"
            style={{
              zIndex: 2,
              padding: "30px 18px",
              width: 166,
            }}
          >
            <h2
              style={{
                fontFamily: '"IM_Hyemin", "SejongGeulggot", sans-serif',
                fontSize: 21,
                fontWeight: 700,
                lineHeight: "26px",
                color: "#1f1f1f",
                letterSpacing: "-0.43px",
                wordBreak: "keep-all",
                whiteSpace: "nowrap",
              }}
            >
              토미랑 달리기
            </h2>
            <p
              className="font-sejong mt-2"
              style={{
                color: "#5f5a55",
                fontSize: 12,
                fontWeight: 700,
                lineHeight: "17px",
                letterSpacing: "-0.43px",
                wordBreak: "keep-all",
              }}
            >
              돌을 피해 더 멀리 달려보세요!
            </p>
          </div>
        </button>
      </div>

      <BottomNav active={activeTab} onChange={handleNav} />
    </div>
  );
}
