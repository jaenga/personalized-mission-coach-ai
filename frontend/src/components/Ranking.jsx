import { useMemo, useState } from "react";
import { BottomNav } from "./Home.jsx";
import lv1Face from "../assets/tomato/_shared/Level/Lv1_face.png";
import lv2Face from "../assets/tomato/_shared/Level/Lv2_face.png";
import lv3Face from "../assets/tomato/_shared/Level/Lv3_face.png";
import lv4Face from "../assets/tomato/_shared/Level/Lv4_face.png";
import lv5Face from "../assets/tomato/_shared/Level/Lv5_face.png";
import lv1Full from "../assets/tomato/_shared/Level/LV1.png";
import lv2Full from "../assets/tomato/_shared/Level/LV2.png";
import lv3Full from "../assets/tomato/_shared/Level/LV3.png";
import lv4Full from "../assets/tomato/_shared/Level/LV4.png";
import lv5Full from "../assets/tomato/_shared/Level/LV5.png";
import leaf from "../assets/tomato/_shared/leaf.png";

const LEVEL_FACES = { 1: lv1Face, 2: lv2Face, 3: lv3Face, 4: lv4Face, 5: lv5Face };
const LEVEL_FULLS = { 1: lv1Full, 2: lv2Full, 3: lv3Full, 4: lv4Full, 5: lv5Full };

// face PNG마다 캐릭터 크기/여백이 달라서 컨텍스트별로 개별 조정 가능하게
const LIST_FACE_SIZE = { 1: 28, 2: 32, 3: 35, 4: 32, 5: 32 };
const ME_FACE_SIZE   = { 1: 36, 2: 40, 3: 43, 4: 40, 5: 40 };

// 레벨 임계값 (누적 XP)
//  Lv1: 5 / Lv2: 17 (+12) / Lv3: 37 (+20) / Lv4: 70 (+33) / Lv5: 120 (+50)
function levelFromXp(xp) {
  if (xp >= 120) return 5;
  if (xp >= 70)  return 4;
  if (xp >= 37)  return 3;
  if (xp >= 17)  return 2;
  return 1;
}
function levelFace(lv) {
  return LEVEL_FACES[Math.min(5, Math.max(1, lv))];
}
function levelFull(lv) {
  return LEVEL_FULLS[Math.min(5, Math.max(1, lv))];
}

/* ─────────────────────────────────────────────────────────
   임시 데이터 ! 나중에 바꿔야함!
   ───────────────────────────────────────────────────────── */
const WEEK_USERS = [
  { id: "u1",  name: "하준", xp: 145, change: 0 },   // Lv5
  { id: "u2",  name: "서연", xp:  92, change: 0 },   // Lv4
  { id: "u3",  name: "지우", xp:  78, change: 0 },   // Lv4
  { id: "me",  name: "민준", xp:  55, change: 2 },   // Lv3
  { id: "u5",  name: "채원", xp:  48, change: -1 },  // Lv3
  { id: "u6",  name: "도윤", xp:  32, change: 0 },   // Lv2
  { id: "u7",  name: "윤아", xp:  25, change: 1 },   // Lv2
  { id: "u8",  name: "시우", xp:  18, change: -1 },  // Lv2
  { id: "u9",  name: "지민", xp:  12, change: 3 },   // Lv1
  { id: "u10", name: "수현", xp:   8, change: -2 },  // Lv1
];

const MONTH_USERS = [
  { id: "u1",  name: "하준", xp: 285, change: 0 },   // Lv5
  { id: "u2",  name: "서연", xp: 224, change: 1 },   // Lv5
  { id: "u3",  name: "지우", xp: 195, change: -1 },  // Lv5
  { id: "me",  name: "민준", xp: 158, change: 4 },   // Lv5
  { id: "u5",  name: "채원", xp: 142, change: -2 },  // Lv5
  { id: "u6",  name: "도윤", xp: 118, change: 0 },   // Lv4
  { id: "u7",  name: "윤아", xp:  95, change: 2 },   // Lv4
  { id: "u8",  name: "시우", xp:  78, change: -1 },  // Lv4
  { id: "u9",  name: "지민", xp:  64, change: 0 },   // Lv3
  { id: "u10", name: "수현", xp:  50, change: -3 },  // Lv3
];

/* ─────────────────────────────────────────────────────────
   상단 헤더
   ───────────────────────────────────────────────────────── */

// 이번 주 일요일 날짜 (예: "~5/10")
function getWeekEndLabel() {
  const d = new Date();
  const dow = d.getDay(); // 0=일
  const offset = dow === 0 ? 0 : 7 - dow;
  const sun = new Date(d);
  sun.setDate(d.getDate() + offset);
  return `~ ${sun.getMonth() + 1}월 ${sun.getDate()}일`;
}

function DateChip({ label }) {
  return (
    <span
      className="inline-flex items-center font-sejong"
      style={{
        background: "#FFFFFF",
        border: "1px solid rgba(227, 93, 73, 0.35)",
        borderRadius: 999,
        paddingInline: 12,
        height: 30,
        fontSize: 12,
        color: "#E35D49",
        letterSpacing: "-0.43px",
        gap: 6,
      }}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#E35D49" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="5" width="18" height="16" rx="2" />
        <path d="M3 9h18" />
        <path d="M8 3v4M16 3v4" />
      </svg>
      {label}
    </span>
  );
}

/* ─────────────────────────────────────────────────────────
   탭 (주간/월간)
   ───────────────────────────────────────────────────────── */
function Tabs({ value, onChange }) {
  const items = [
    { key: "week",  label: "주간" },
    { key: "month", label: "월간" },
  ];
  return (
    <div
      className="flex"
      style={{
        background: "rgba(255, 255, 255, 0.7)",
        borderRadius: 999,
        padding: 4,
        border: "1px solid rgba(227, 93, 73, 0.2)",
      }}
    >
      {items.map((it) => {
        const active = value === it.key;
        return (
          <button
            key={it.key}
            type="button"
            onClick={() => onChange(it.key)}
            className="flex-1 font-sejong transition-all"
            style={{
              height: 36,
              borderRadius: 999,
              background: active ? "#E35D49" : "transparent",
              color: active ? "#FFFFFF" : "#75726e",
              fontSize: 14,
              fontWeight: active ? 700 : 500,
              letterSpacing: "-0.43px",
              border: "none",
              cursor: "pointer",
            }}
          >
            {it.label}
          </button>
        );
      })}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   왕관 / 메달
   ───────────────────────────────────────────────────────── */
function Crown({ size = 22, color = "#E8B53D" }) {
  const w = size;
  const h = Math.round(size * 0.78);
  return (
    <svg width={w} height={h} viewBox="0 0 28 22" fill="none" aria-hidden="true">
      <path
        d="M3 18 L4 7 L9 11 L14 4 L19 11 L24 7 L25 18 Z"
        fill={color}
        stroke={color}
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
      <rect x="3" y="18" width="22" height="2" fill={color} />
    </svg>
  );
}
/* ─────────────────────────────────────────────────────────
   Podium (Top 3) — 2(좌) / 1(중) / 3(우)
   레퍼런스 스타일: 단순한 컬러 바 + 위에 캐릭터/이름/포인트
   ───────────────────────────────────────────────────────── */
function Podium({ top3 }) {
  const first  = top3[0];
  const second = top3[1];
  const third  = top3[2];
  return (
    <div className="flex items-end justify-center" style={{ gap: 8, paddingInline: 4 }}>
      <PodiumColumn user={second} rank={2} barHeight={90}  charSize={62} />
      <PodiumColumn user={first}  rank={1} barHeight={130} charSize={76} showCrown />
      <PodiumColumn user={third}  rank={3} barHeight={70}  charSize={56} />
    </div>
  );
}

function PodiumColumn({ user, rank, barHeight, charSize, showCrown }) {
  if (!user) return <div style={{ width: 92 }} />;
  return (
    <div className="flex flex-col items-center" style={{ width: 92 }}>
      {/* 캐릭터 + 이름 + 포인트 */}
      <div className="flex flex-col items-center" style={{ marginBottom: 6 }}>
        {showCrown && <div style={{ marginBottom: -4 }}><Crown /></div>}
        <img
          src={levelFull(levelFromXp(user.xp))}
          alt=""
          draggable="false"
          className="select-none pointer-events-none"
          style={{ width: charSize, height: charSize, objectFit: "contain" }}
        />
        <span
          className="font-sejong"
          style={{ fontSize: 13, fontWeight: 700, color: "#000", letterSpacing: "-0.43px", marginTop: 2 }}
        >
          {user.name}
        </span>
        <span
          className="font-sejong"
          style={{ fontSize: 11, color: "#75726e", letterSpacing: "-0.43px" }}
        >
          {user.xp} EXP
        </span>
      </div>
      {/* 시상대 바 — 전부 동일한 컬러로 깔끔하게 */}
      <div
        className="flex items-center justify-center"
        style={{
          width: "100%",
          height: barHeight,
          background: "#DDEBC9",
          borderTopLeftRadius: 16,
          borderTopRightRadius: 16,
        }}
      >
        <span
          className="font-noto"
          style={{
            color: "#3a3a3a",
            fontSize: rank === 1 ? 28 : 24,
            fontWeight: 600,
            letterSpacing: "-0.43px",
          }}
        >
          {rank}
        </span>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   순위 변동 칩 (▲ 2 / ▼ 1 / −)
   ───────────────────────────────────────────────────────── */
function ChangeChip({ change }) {
  if (change === 0) {
    return (
      <span
        className="font-sejong inline-flex items-center justify-center"
        style={{
          minWidth: 36, height: 24, borderRadius: 999,
          paddingInline: 10,
          background: "rgba(167, 167, 167, 0.15)",
          color: "#9a9a9a",
          fontSize: 12, fontWeight: 600, letterSpacing: "-0.43px",
        }}
      >
        −
      </span>
    );
  }
  const up = change > 0;
  const bg = up ? "rgba(227, 93, 73, 0.12)" : "rgba(167, 218, 167, 0.18)";
  const color = up ? "#E35D49" : "#7BA45C";
  return (
    <span
      className="font-sejong inline-flex items-center"
      style={{
        minWidth: 40, height: 24, borderRadius: 999,
        paddingInline: 10,
        background: bg, color,
        fontSize: 12, fontWeight: 700, letterSpacing: "-0.43px",
        gap: 3,
      }}
    >
      <svg width="9" height="10" viewBox="0 0 9 10" fill="none">
        {up ? (
          <path d="M4.5 1 L8 6 H1 Z" fill={color} />
        ) : (
          <path d="M4.5 9 L8 4 H1 Z" fill={color} />
        )}
      </svg>
      {Math.abs(change)}
    </span>
  );
}

/* ─────────────────────────────────────────────────────────
   내 상태 강조 카드 (Points / Level / Position)
   ───────────────────────────────────────────────────────── */
function MeStatusCard({ me }) {
  if (!me) return null;
  const lv = levelFromXp(me.xp);
  return (
    <div
      className="flex items-center"
      style={{
        background: "#E35D49",
        borderRadius: 20,
        padding: "12px 16px",
        gap: 14,
        boxShadow: "0 4px 12px rgba(227, 93, 73, 0.25)",
      }}
    >
      <span
        className="inline-flex items-center justify-center flex-shrink-0"
        style={{ width: 48, height: 48, borderRadius: "50%", background: "#FFFFFF" }}
      >
        <img src={levelFace(lv)} alt="" style={{ width: ME_FACE_SIZE[lv], height: ME_FACE_SIZE[lv], objectFit: "contain" }} />
      </span>
      <StatCell label="EXP" value={me.xp} />
      <div style={{ width: 1, height: 28, background: "rgba(255,255,255,0.4)" }} />
      <StatCell label="Level" value={`Lv.${lv}`} />
      <div style={{ width: 1, height: 28, background: "rgba(255,255,255,0.4)" }} />
      <StatCell label="Position" value={`#${me.rank}`} />
    </div>
  );
}
function StatCell({ label, value }) {
  return (
    <div className="flex flex-col" style={{ minWidth: 0 }}>
      <span
        className="font-sejong"
        style={{ fontSize: 11, color: "rgba(255,255,255,0.85)", letterSpacing: "-0.43px" }}
      >
        {label}
      </span>
      <span
        className="font-sejong"
        style={{ fontSize: 16, fontWeight: 700, color: "#FFFFFF", letterSpacing: "-0.43px", lineHeight: "20px" }}
      >
        {value}
      </span>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   리스트 행
   ───────────────────────────────────────────────────────── */
function RankRow({ rank, user, isMe }) {
  const lv = levelFromXp(user.xp);
  return (
    <div
      className="flex items-center"
      style={{
        height: 60,
        paddingInline: 14,
        borderRadius: 16,
        background: isMe ? "rgba(227, 93, 73, 0.10)" : "rgba(255, 255, 255, 0.7)",
        border: isMe ? "1px solid rgba(227, 93, 73, 0.45)" : "1px solid rgba(227, 93, 73, 0.10)",
        gap: 12,
      }}
    >
      <span
        className="font-noto"
        style={{
          width: 28, textAlign: "center",
          fontSize: 14, fontWeight: 700,
          color: isMe ? "#E35D49" : "#A6A29D",
          letterSpacing: "-0.43px",
        }}
      >
        {String(rank).padStart(2, "0")}
      </span>
      <span
        className="inline-flex items-center justify-center flex-shrink-0"
        style={{ width: 40, height: 40, borderRadius: "50%", background: "#FFFFFF", border: "1px solid rgba(227, 93, 73, 0.15)" }}
      >
        <img src={levelFace(lv)} alt="" style={{ width: LIST_FACE_SIZE[lv], height: LIST_FACE_SIZE[lv], objectFit: "contain" }} />
      </span>
      <div className="flex-1 min-w-0">
        <div
          className="font-sejong truncate"
          style={{ fontSize: 14, fontWeight: 700, color: "#000", letterSpacing: "-0.43px" }}
        >
          {user.name}{isMe ? " (나)" : ""}
        </div>
        <div
          className="font-sejong"
          style={{ fontSize: 12, color: "#75726e", letterSpacing: "-0.43px", marginTop: 1 }}
        >
          {user.xp} EXP
        </div>
      </div>
      <ChangeChip change={user.change} />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   Ranking — 메인
   ───────────────────────────────────────────────────────── */
export default function Ranking({ studentName = "민준", currentXp = 55, onNavigate }) {
  const [tab, setTab] = useState("week");
  const [activeNav, setActiveNav] = useState("rank");

  const ranked = useMemo(() => {
    const src = tab === "week" ? WEEK_USERS : MONTH_USERS;
    const hasMe = src.some((u) => u.name === studentName);
    const data = hasMe
      ? src
      : [...src, { id: "me-injected", name: studentName, xp: currentXp, change: 0 }];
    const sorted = [...data].sort((a, b) => b.xp - a.xp);
    return sorted.map((u, i) => ({ ...u, rank: i + 1, isMe: u.name === studentName }));
  }, [tab, studentName, currentXp]);

  const top3 = ranked.slice(0, 3);
  const me = ranked.find((u) => u.isMe);
  const meIsTop3 = me && me.rank <= 3;

  const restList = useMemo(() => {
    if (!me || meIsTop3) return ranked.slice(3);
    return [me, ...ranked.slice(3).filter((u) => !u.isMe)];
  }, [ranked, me, meIsTop3]);

  function handleNav(key) {
    setActiveNav(key);
    onNavigate?.(key);
  }

  return (
    <div
      className="relative w-[402px] h-[874px] overflow-hidden mx-auto flex flex-col"
      style={{ background: "#FFF3E7" }}
    >
      {/* 헤더 — 설정 화면과 동일한 스타일 */}
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
        <span
          className="font-sejong"
          style={{ fontSize: 16, fontWeight: 700, color: "#000", letterSpacing: "-0.43px" }}
        >
          랭킹
        </span>
        <DateChip label={tab === "week" ? getWeekEndLabel() : "이번 달"} />
      </header>

      {/* 탭 */}
      <div className="flex-shrink-0" style={{ paddingInline: 19, paddingTop: 16, paddingBottom: 12 }}>
        <Tabs value={tab} onChange={setTab} />
      </div>

      {/* 본문 — 스크롤 가능 */}
      <div
        className="flex-1 overflow-y-auto"
        style={{ paddingInline: 19, paddingBottom: 88 }}
      >
        {/* TOP 3 카드 */}
        <section
          className="relative"
          style={{
            background: "rgba(255, 255, 255, 0.7)",
            borderRadius: 24,
            border: "1px solid rgba(227, 93, 73, 0.18)",
            padding: "20px 12px 16px",
            overflow: "hidden",
          }}
        >
          <div
            className="font-jeju flex items-center justify-center"
            style={{
              fontSize: 18,
              color: "#E35D49",
              letterSpacing: "-0.43px",
              marginBottom: 18,
              gap: 10,
            }}
          >
            <img
              src={leaf}
              alt=""
              draggable="false"
              style={{ width: 22, height: 17, transform: "rotate(-20deg)" }}
            />
            이번 {tab === "week" ? "주" : "달"} TOP 3
            <img
              src={leaf}
              alt=""
              draggable="false"
              style={{ width: 22, height: 17, transform: "scaleX(-1) rotate(-20deg)" }}
            />
          </div>
          <Podium top3={top3} />
        </section>

        {/* 내 상태 카드 */}
        {me && (
          <div className="mt-3">
            <MeStatusCard me={me} />
          </div>
        )}

        {/* 4등 이하 리스트 */}
        <div className="mt-3 flex flex-col" style={{ gap: 8 }}>
          {restList.map((u) => (
            <RankRow key={u.id} rank={u.rank} user={u} isMe={u.isMe} />
          ))}
        </div>
      </div>

      <BottomNav active={activeNav} onChange={handleNav} />
    </div>
  );
}
