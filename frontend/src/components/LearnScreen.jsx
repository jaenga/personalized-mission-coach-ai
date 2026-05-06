import { useEffect, useMemo, useState } from "react";
import { BottomNav, LevelRing } from "./Home.jsx";
import { LESSONS } from "../data/lessons.js";
import { completeLessonQuiz, fetchLessonProgress, updateLessonProgress } from "../api.js";
import EducationScreen from "./EducationScreen.jsx";
import QuizScreen from "./QuizScreen.jsx";
import gachaImg from "../assets/tomato/draw/gacha.png";
import readingTomato from "../assets/read.png";
import bookIconImg from "../assets/book.png";
import starIconImg from "../assets/star.png";
import flagImg from "../assets/tomato/home/flag.png";
import ticketImg from "../assets/tomato/_shared/ticket.png";
import heartImg from "../assets/tomato/_shared/heart.png";

/* ─────────────────────────────────────────────────────────
   하루치 플랜 — day별 단원 2개 (다른 주제) → 4노드 (교육-퀴즈-교육-퀴즈)
   ───────────────────────────────────────────────────────── */
const DAILY_PLAN = [
  { day: 1, title: "건강한 하루의 시작",     lessonIds: ["sugar-snacks", "hand-washing"] },
  { day: 2, title: "잘 먹고 잘 닦기",        lessonIds: ["rainbow-vegetables", "tooth-care"] },
  { day: 3, title: "영양과 면역",            lessonIds: ["nutrition-label", "immunity-vaccine"] },
  { day: 4, title: "물과 잠의 비밀",         lessonIds: ["water-habit", "sleep-golden-time"] },
  { day: 5, title: "바른 자세, 신나는 운동", lessonIds: ["posture-spine", "exercise-muscle"] },
  { day: 6, title: "눈 보호와 안전",         lessonIds: ["eye-health", "outdoor-safety"] },
  { day: 7, title: "응급처치와 마음 건강",   lessonIds: ["first-aid", "emotion-stress"] },
];

const NODE_GAP = 100;
const PATH_WIDTH = 280;

export default function LearnScreen({
  onNavigate,
  studentId,
  todayMission = { title: "15분 책 읽기" },
  currentDay = 1,
  level = 3,
  currentXp = 12,
  maxXp = 20,
  ticketCount = 2,
  heartCount = 4,
  onAppStateUpdate,
}) {
  const [activeNav, setActiveNav] = useState("learn");
  // progress[lessonId] = { eduDone, quizDone }. 백엔드 lesson_progress에서 로드.
  const [progress, setProgress] = useState({});

  // 진입 시 백엔드에서 진행도 로드
  useEffect(() => {
    if (!studentId) return;
    let cancelled = false;
    fetchLessonProgress(studentId)
      .then((rows) => {
        if (cancelled) return;
        const map = {};
        for (const r of rows) {
          map[r.lesson_id] = { eduDone: r.edu_done, quizDone: r.quiz_done };
        }
        setProgress(map);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [studentId]);
  const [openLessonId, setOpenLessonId] = useState(null);
  const [openMode, setOpenMode] = useState(null);
  const [expOpen, setExpOpen] = useState(false);

  const todayPlan = DAILY_PLAN.find((d) => d.day === currentDay) ?? DAILY_PLAN[0];
  const todayLessons = todayPlan.lessonIds
    .map((id) => LESSONS.find((l) => l.id === id))
    .filter(Boolean);

  const todayNodes = useMemo(
    () =>
      todayLessons.flatMap((lesson, idx) => [
        { id: `${lesson.id}-edu`,  lessonId: lesson.id, kind: "education", lesson, setIdx: idx + 1 },
        { id: `${lesson.id}-quiz`, lessonId: lesson.id, kind: "quiz",      lesson, setIdx: idx + 1 },
      ]),
    [todayLessons]
  );

  // 잠긴 다음 날들도 같은 패스에 연결
  const lockedDayNodes = useMemo(
    () =>
      DAILY_PLAN.filter((d) => d.day > currentDay).map((d) => ({
        id: `day-${d.day}`,
        kind: "lockedDay",
        day: d.day,
        title: d.title,
      })),
    [currentDay]
  );

  const nodes = useMemo(() => [...todayNodes, ...lockedDayNodes], [todayNodes, lockedDayNodes]);

  function nodeState(node) {
    if (node.kind === "lockedDay") return "locked";
    const p = progress[node.lessonId] || {};
    if (node.kind === "education") return p.eduDone ? "done" : "active";
    if (!p.eduDone) return "locked";
    return p.quizDone ? "done" : "active";
  }

  const states = nodes.map(nodeState);
  const activeIdx = states.findIndex((s) => s === "active");

  function handleNav(key) {
    setActiveNav(key);
    onNavigate?.(key);
  }

  function handleNodeClick(node, state) {
    if (state === "locked") return;
    if (state === "active" && nodes.findIndex((n) => n.id === node.id) !== activeIdx) return;
    setOpenLessonId(node.lessonId);
    setOpenMode(node.kind);
  }

  function handleEduFinish(lessonId) {
    setProgress((prev) => ({
      ...prev,
      [lessonId]: { ...(prev[lessonId] || {}), eduDone: true },
    }));
    setOpenMode("quiz");
    if (studentId) {
      updateLessonProgress({ studentId, lessonId, eduDone: true }).catch(() => {});
    }
  }

  function handleQuizComplete(lessonId) {
    setProgress((prev) => ({
      ...prev,
      [lessonId]: { ...(prev[lessonId] || {}), quizDone: true },
    }));
    if (studentId) {
      completeLessonQuiz({ studentId, lessonId })
        .then((res) => {
          // 첫 완료라면 백엔드가 ticket +1 한 새 app_state를 반환 — 부모에 반영.
          if (res?.app_state) onAppStateUpdate?.(res.app_state);
        })
        .catch(() => {});
    }
  }

  function closeOverlay() {
    setOpenLessonId(null);
    setOpenMode(null);
  }

  if (openLessonId && openMode === "education") {
    const lesson = LESSONS.find((l) => l.id === openLessonId);
    return (
      <EducationScreen
        lesson={lesson}
        onBack={closeOverlay}
        onFinish={() => handleEduFinish(openLessonId)}
      />
    );
  }

  if (openLessonId && openMode === "quiz") {
    const lesson = LESSONS.find((l) => l.id === openLessonId);
    return (
      <QuizScreen
        lesson={lesson}
        onBack={closeOverlay}
        onComplete={() => handleQuizComplete(openLessonId)}
        alreadyCompleted={!!progress[openLessonId]?.quizDone}
      />
    );
  }

  return (
    <div
      className="relative w-[402px] h-[874px] overflow-hidden mx-auto flex flex-col"
      style={{ background: "#FFF3E7" }}
    >
      {/* 상단 바 (LevelRing + 뽑기권/하트 칩) */}
      <div
        className="relative flex-shrink-0 flex items-start justify-between"
        style={{ paddingInline: 19, paddingTop: 16 }}
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
            <img src={ticketImg} alt="" style={{ width: 12, height: 12 }} />
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
            <img src={heartImg} alt="" style={{ width: 12, height: 12 }} />
            {heartCount}
          </button>
        </div>

        {/* 레벨 링 */}
        <div
          className="absolute"
          style={{
            left: 19,
            top: 68,
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

      {/* 타이틀 */}
      <div className="flex-shrink-0" style={{ paddingInline: 19, paddingTop: 16, paddingBottom: 4 }}>
        <h1
          className="font-sejong"
          style={{ fontSize: 20, fontWeight: 700, color: "#1a1a1a", letterSpacing: "-0.43px" }}
        >
          오늘의 배움 길
        </h1>
      </div>

      {/* 본문 */}
      <div
        className="flex-1 overflow-y-auto relative"
        style={{ paddingInline: 19, paddingTop: 6, paddingBottom: 110 }}
      >
        {/* 배경 데코 (구름/풀) */}
        <BackgroundDecor />

        {/* 미션 배너 */}
        <MissionBanner mission={todayMission} day={currentDay} />

        {/* 패스 (오늘 + 잠긴 다음 날들 연결) */}
        <Path nodes={nodes} states={states} activeIdx={activeIdx} onClick={handleNodeClick} />
      </div>

      {/* 가챠 플로팅 버튼 */}
      <button
        type="button"
        onClick={() => onNavigate?.("draw")}
        aria-label="뽑기 화면으로 이동"
        className="absolute transition-transform active:scale-95"
        style={{
          right: 14, bottom: 84,
          width: 78, height: 78,
          borderRadius: "50%",
          background: "transparent",
          border: "none",
          padding: 0,
          cursor: "pointer",
          zIndex: 5,
        }}
      >
        <img
          src={gachaImg}
          alt=""
          draggable="false"
          className="select-none pointer-events-none"
          style={{ width: "100%", height: "100%", objectFit: "contain" }}
        />
      </button>

      <BottomNav active={activeNav} onChange={handleNav} />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   미션 배너 — 진행 바 + 토마토 캐릭터
   ───────────────────────────────────────────────────────── */
function MissionBanner({ mission }) {
  return (
    <div className="relative" style={{ minHeight: 96, zIndex: 1 }}>
      {/* 좌측 미션 카드 (말풍선 스타일, 폭 좁게) */}
      <div
        className="flex items-center"
        style={{
          position: "relative",
          zIndex: 1,
          background: "#DDEBC9",
          borderRadius: 22,
          padding: "12px 16px",
          gap: 12,
          maxWidth: 220,
          minHeight: 70,
          border: "1px solid rgba(123, 164, 92, 0.25)",
        }}
      >
        <span
          className="inline-flex items-center justify-center flex-shrink-0"
          style={{ width: 40, height: 40, borderRadius: 12, background: "#FFFFFF" }}
        >
          <img src={flagImg} alt="" style={{ width: 24, height: 24, objectFit: "contain" }} />
        </span>
        <div className="flex-1 min-w-0">
          <div
            className="font-sejong"
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: "#7BA45C",
              letterSpacing: "-0.43px",
            }}
          >
            오늘의 미션
          </div>
          <div
            className="font-sejong"
            style={{
              fontSize: 15,
              fontWeight: 700,
              color: "#1a1a1a",
              letterSpacing: "-0.43px",
              lineHeight: "19px",
              marginTop: 1,
            }}
          >
            {mission.title}
          </div>
        </div>
      </div>

      {/* 우측 토마토 (카드와 살짝 겹치게) */}
      <img
        src={readingTomato}
        alt=""
        draggable="false"
        className="absolute select-none pointer-events-none"
        style={{
          left: 188,
          top: -14,
          width: 116,
          height: 116,
          objectFit: "contain",
          zIndex: 2,
        }}
      />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   곡선 패스 + 노드
   ───────────────────────────────────────────────────────── */
function Path({ nodes, states, activeIdx, onClick }) {
  const positions = nodes.map((_, i) => ({
    x: PATH_WIDTH / 2 + (i % 2 === 0 ? -52 : 52),
    y: 82 + i * NODE_GAP,
  }));
  const lastPos = positions[positions.length - 1];
  const endPoint = {
    x: lastPos.x + (nodes.length % 2 === 0 ? -54 : 54),
    y: lastPos.y + 96,
  };
  const totalHeight = endPoint.y + 40;

  // SVG path: 미션 카드 바로 아래에서 시작
  const startX = positions[0].x;
  const startY = 0;
  const svgPath = positions.reduce((acc, p, i) => {
    if (i === 0) {
      return `M ${startX} ${startY} L ${p.x} ${p.y}`;
    }
    const prev = positions[i - 1];
    const midY = (prev.y + p.y) / 2;
    return `${acc} C ${prev.x} ${midY}, ${p.x} ${midY}, ${p.x} ${p.y}`;
  }, "");
  const tailMidY = (lastPos.y + endPoint.y) / 2;
  const continuedPath = `${svgPath} C ${lastPos.x} ${tailMidY}, ${endPoint.x} ${tailMidY}, ${endPoint.x} ${endPoint.y}`;

  return (
    <div
      className="relative mx-auto"
      style={{ width: PATH_WIDTH, height: totalHeight, marginTop: -26 }}
    >
      <svg
        aria-hidden="true"
        width={PATH_WIDTH}
        height={totalHeight}
        style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
      >
        <path
          d={continuedPath}
          stroke="rgba(227, 93, 73, 0.4)"
          strokeWidth="3.5"
          strokeDasharray="8 8"
          strokeLinecap="round"
          fill="none"
        />
      </svg>

      {nodes.map((node, i) => {
        const state = states[i];
        const isCurrent = i === activeIdx;
        const pos = positions[i];
        return (
          <PathNode
            key={node.id}
            node={node}
            state={state}
            isCurrent={isCurrent}
            x={pos.x}
            y={pos.y}
            onClick={() => onClick(node, state)}
          />
        );
      })}
    </div>
  );
}

function PathNode({ node, state, isCurrent, x, y, onClick }) {
  const isLockedDay = node.kind === "lockedDay";
  const isEdu = node.kind === "education";
  // 교육=메인 레드 / 퀴즈=노랑 / 잠금=쿨 그레이
  const baseColor = isEdu ? "#E35D49" : "#F4C842";
  const lockedColor = "#D9D5D0";
  const bg = state === "locked" ? lockedColor : baseColor;
  const ring = darken(bg);
  const size = isLockedDay ? 56 : isCurrent ? 80 : 68;
  const innerImg = isEdu ? bookIconImg : starIconImg;
  const innerSize = isCurrent ? 35 : 27;

  return (
    <div
      className="absolute flex flex-col items-center"
      style={{
        left: x - size / 2,
        top: y - size / 2,
        width: size,
      }}
    >
      <button
        type="button"
        onClick={onClick}
        disabled={state === "locked" || (!isCurrent && state === "active")}
        className="relative transition-transform active:scale-95"
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          background: bg,
          border: `4px solid #FFFFFF`,
          cursor: state === "locked" ? "default" : "pointer",
          boxShadow: state === "locked"
            ? "0 2px 0 rgba(0,0,0,0.05)"
            : `0 5px 0 ${ring}, 0 8px 16px rgba(0,0,0,0.06)`,
          padding: 0,
          opacity: state === "locked" ? 0.85 : 1,
        }}
      >
        {isCurrent && state === "active" && (
          <span
            aria-hidden="true"
            style={{
              position: "absolute",
              inset: -10,
              borderRadius: "50%",
              border: `3px solid ${baseColor}`,
              opacity: 0.35,
              animation: "pulseRing 1.6s ease-out infinite",
            }}
          />
        )}
        <span className="absolute inset-0 flex items-center justify-center">
          {isLockedDay ? (
            <span className="font-jeju" style={{ fontSize: 22, color: "#fff", letterSpacing: "-0.43px" }}>
              {node.day}
            </span>
          ) : (
            <img
              src={innerImg}
              alt=""
              draggable="false"
              className="select-none pointer-events-none"
              style={{
                width: innerSize,
                height: innerSize,
                objectFit: "contain",
                filter: state === "locked" ? "grayscale(0.6) opacity(0.7)" : "none",
              }}
            />
          )}
        </span>
        {state === "done" && <DoneBadge />}
        {state === "locked" && <LockBadge />}
      </button>

      <style>{`
        @keyframes pulseRing {
          0%   { transform: scale(0.95); opacity: 0.5; }
          70%  { transform: scale(1.18); opacity: 0; }
          100% { transform: scale(1.18); opacity: 0; }
        }
      `}</style>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   배경 데코 (구름 / 풀)
   ───────────────────────────────────────────────────────── */
function BackgroundDecor() {
  return (
    <div
      aria-hidden="true"
      className="absolute pointer-events-none"
      style={{ inset: 0, overflow: "hidden", zIndex: 0 }}
    >
      {/* 구름 */}
      <Cloud style={{ left: 16, top: 220, opacity: 0.55 }} />
      <Cloud style={{ right: 8,  top: 280, opacity: 0.45, transform: "scale(0.8)" }} />
      <Cloud style={{ left: 26, top: 480, opacity: 0.4, transform: "scale(0.7)" }} />
      <Cloud style={{ right: 18, top: 540, opacity: 0.5 }} />
    </div>
  );
}
function Cloud({ style }) {
  return (
    <svg
      width="60"
      height="32"
      viewBox="0 0 60 32"
      fill="none"
      style={{ position: "absolute", ...style }}
    >
      <ellipse cx="18" cy="20" rx="12" ry="10" fill="#FFFFFF" />
      <ellipse cx="32" cy="14" rx="14" ry="11" fill="#FFFFFF" />
      <ellipse cx="46" cy="20" rx="11" ry="9"  fill="#FFFFFF" />
    </svg>
  );
}


/* ─────────────────────────────────────────────────────────
   아이콘 / 배지
   ───────────────────────────────────────────────────────── */
function DoneBadge() {
  return (
    <span
      aria-hidden="true"
      style={{
        position: "absolute",
        top: -2, right: -2,
        width: 22, height: 22, borderRadius: "50%",
        background: "#7BA45C",
        border: "2px solid #FFF3E7",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <svg width="11" height="11" viewBox="0 0 14 14" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 7.5 L6 10.5 L11 4.5" />
      </svg>
    </span>
  );
}
function LockBadge() {
  return (
    <span
      aria-hidden="true"
      style={{
        position: "absolute",
        bottom: -4, right: -4,
        width: 24, height: 24, borderRadius: "50%",
        background: "#FFFFFF",
        border: "2px solid #D9D5D0",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <LockBadgeInline />
    </span>
  );
}
function LockBadgeInline() {
  return (
    <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="#A6A29D" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="6" width="8" height="6" rx="1.2" />
      <path d="M5 6 V4.5 a2 2 0 0 1 4 0 V6" />
    </svg>
  );
}

function darken(hex) {
  const map = {
    "#E35D49": "#B84838",
    "#F4C842": "#C49A1F",
    "#D9D5D0": "#B5B0AB",
  };
  return map[hex] || "#999";
}
