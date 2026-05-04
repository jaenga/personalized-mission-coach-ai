import { useEffect, useRef, useState } from "react";
import gachaImg from "../assets/tomato/draw/gacha.png";
import yahoImg from "../assets/tomato/draw/yaho.png";
import heartImg from "../assets/tomato/_shared/heart.png";
import ticketImg from "../assets/tomato/_shared/ticket.png";
import pointerImg from "../assets/tomato/draw/pointer.png";
import { LevelRing, BottomNav } from "./Home.jsx";

/* ─────────────────────────────────────────────────────────
   레벨 임계값 — 다음 레벨까지 필요한 경험치
   누적: lvl1=5, lvl2=17, lvl3=37, lvl4=70
   ───────────────────────────────────────────────────────── */
const LEVEL_THRESHOLDS = { 1: 5, 2: 12, 3: 20, 4: 33, 5: 50 };

function applyExp(level, currentXp, gain) {
  let lv = level;
  let xp = currentXp + gain;
  while (LEVEL_THRESHOLDS[lv] && xp >= LEVEL_THRESHOLDS[lv]) {
    xp -= LEVEL_THRESHOLDS[lv];
    lv += 1;
  }
  return { level: lv, xp, max: LEVEL_THRESHOLDS[lv] || 100 };
}

/* ─────────────────────────────────────────────────────────
   리워드 추첨 — 하루 첫 뽑기는 하트 확정, 이후 40/40/20
   ───────────────────────────────────────────────────────── */
const EXP_REWARD = 1;
function rollReward(isFirstOfDay) {
  if (isFirstOfDay) return { type: "heart", heart: 1, exp: 0 };
  const r = Math.random();
  if (r < 0.4) return { type: "heart", heart: 1, exp: 0 };
  if (r < 0.8) return { type: "exp", heart: 0, exp: EXP_REWARD };
  return { type: "both", heart: 1, exp: EXP_REWARD };
}

/* ─────────────────────────────────────────────────────────
   결과 — 토마토 주위 주황 버스트 + 색종이
   ───────────────────────────────────────────────────────── */
const CONFETTI_COLORS = ["#E35D49", "#FFD56B", "#9DC9E8", "#A7DAA7", "#F4B6C2", "#FFAE6B"];
const CONFETTI = Array.from({ length: 18 }, (_, i) => ({
  left: 30 + Math.random() * 240,
  delay: Math.random() * 0.5,
  tx: (Math.random() - 0.5) * 80,
  color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
  size: 6 + Math.random() * 6,
  rot: Math.random() * 360,
}));

function RewardBurst({ children }) {
  return (
    <div className="relative flex items-center justify-center" style={{ width: 332, height: 332 }}>
      {/* 주황 방사형 글로우 */}
      <div
        aria-hidden="true"
        className="absolute burst-pulse"
        style={{
          width: 320,
          height: 320,
          borderRadius: "50%",
          background:
            "radial-gradient(circle, rgba(255,189,44,0.6) 0%, rgba(255,144,77,0.35) 35%, rgba(255,243,231,0) 70%)",
        }}
      />
      {/* 방사형 광선 */}
      <svg
        aria-hidden="true"
        className="absolute burst-pulse"
        width="332" height="332" viewBox="0 0 332 332"
        style={{ animationDelay: "0.3s" }}
      >
        {Array.from({ length: 12 }).map((_, i) => {
          const angle = (i * 30 * Math.PI) / 180;
          const x1 = 166 + Math.cos(angle) * 110;
          const y1 = 166 + Math.sin(angle) * 110;
          const x2 = 166 + Math.cos(angle) * 150;
          const y2 = 166 + Math.sin(angle) * 150;
          return (
            <line
              key={i}
              x1={x1} y1={y1} x2={x2} y2={y2}
              stroke="#FFBD2C"
              strokeWidth="4"
              strokeLinecap="round"
              opacity="0.65"
            />
          );
        })}
      </svg>
      {/* 색종이 */}
      {CONFETTI.map((c, i) => (
        <span
          key={i}
          className="absolute confetti-piece"
          style={{
            left: c.left,
            top: 0,
            width: c.size,
            height: c.size,
            background: c.color,
            transform: `rotate(${c.rot}deg)`,
            ["--tx"]: `${c.tx}px`,
            animationDelay: `${c.delay}s`,
            borderRadius: i % 3 === 0 ? "50%" : 2,
          }}
        />
      ))}
      {children}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   상단 뱃지 (티켓 / 하트)
   ───────────────────────────────────────────────────────── */
function TopBadges({ ticketCount, heartCount }) {
  return (
    <div className="flex gap-1.5">
      <span
        className="flex items-center gap-1 font-sejong"
        style={{
          background: "rgba(255, 218, 137, 0.5)",
          borderRadius: 50,
          paddingInline: 8,
          height: 24,
          fontSize: 12,
        }}
      >
        <img src={ticketImg} alt="" style={{ width: 12, height: 12 }} />
        {ticketCount}
      </span>
      <span
        className="flex items-center gap-1 font-sejong"
        style={{
          background: "rgba(252, 228, 225, 0.7)",
          borderRadius: 50,
          paddingInline: 8,
          height: 24,
          fontSize: 12,
        }}
      >
        <img src={heartImg} alt="" style={{ width: 12, height: 12 }} />
        {heartCount}
      </span>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   결과 카드 (heart / exp / both)
   ───────────────────────────────────────────────────────── */
function RewardCard({ reward }) {
  return (
    <div
      className="mx-auto"
      style={{
        width: 290,
        borderRadius: 30,
        background: "rgba(255, 255, 255, 0.85)",
        border: "1px solid rgba(227, 93, 73, 0.4)",
        padding: "16px 20px",
        textAlign: "center",
      }}
    >
      <div className="flex items-center justify-center gap-2">
        {reward.heart > 0 && (
          <>
            <img src={heartImg} alt="" style={{ width: 32, height: 32 }} />
            <span
              className="font-sejong"
              style={{ fontSize: 26, color: "#E35D49", fontWeight: 700, letterSpacing: "-0.43px" }}
            >
              +{reward.heart}
            </span>
          </>
        )}
        {reward.exp > 0 && (
          <>
            {reward.heart > 0 && <span style={{ width: 12 }} />}
            <img src={pointerImg} alt="" style={{ width: 28, height: 28 }} />
            <span
              className="font-sejong"
              style={{ fontSize: 26, color: "#FFBD2C", fontWeight: 700, letterSpacing: "-0.43px" }}
            >
              +{reward.exp} EXP
            </span>
          </>
        )}
      </div>
      <p
        className="font-sejong mt-2"
        style={{ fontSize: 12, color: "#000", letterSpacing: "-0.43px" }}
      >
        {reward.type === "heart" && "게임에 참여할 수 있는 하트 하나 획득!"}
        {reward.type === "exp" && "경험치를 얻었어! 레벨업까지 한 걸음 더~"}
        {reward.type === "both" && "레어 보상! 하트 + 경험치 모두 획득!"}
      </p>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   DrawScreen — 메인 컴포넌트
   ───────────────────────────────────────────────────────── */
export default function DrawScreen({
  initialLevel = 3,
  initialCurrentXp = 12,
  initialMaxXp = LEVEL_THRESHOLDS[3],
  initialTickets = 3,
  initialHearts = 4,
  initialFirstOfDay = true,
  onNavigate,
  onBack,
}) {
  const [level, setLevel] = useState(initialLevel);
  const [currentXp, setCurrentXp] = useState(initialCurrentXp);
  const [maxXp, setMaxXp] = useState(initialMaxXp);
  const [tickets, setTickets] = useState(initialTickets);
  const [hearts, setHearts] = useState(initialHearts);
  const [firstOfDay, setFirstOfDay] = useState(initialFirstOfDay);

  // phase: idle | drawing | result
  const [phase, setPhase] = useState("idle");
  const [reward, setReward] = useState(null);
  const [activeTab, setActiveTab] = useState("rank"); // 뽑기는 일단 랭킹 탭에 매핑
  const [expOpen, setExpOpen] = useState(false);
  const drawTimerRef = useRef(null);

  useEffect(() => () => clearTimeout(drawTimerRef.current), []);

  const canDraw = tickets > 0 && phase === "idle";

  function handleDraw() {
    if (!canDraw) return;
    setPhase("drawing");
    setTickets((t) => t - 1);
    drawTimerRef.current = setTimeout(() => {
      const r = rollReward(firstOfDay);
      setReward(r);
      // 보상 적용
      if (r.heart > 0) setHearts((h) => h + r.heart);
      if (r.exp > 0) {
        const next = applyExp(level, currentXp, r.exp);
        // ring 애니메이션을 보여주기 위해 약간 딜레이
        setTimeout(() => {
          setLevel(next.level);
          setCurrentXp(next.xp);
          setMaxXp(next.max);
        }, 400);
      }
      setFirstOfDay(false);
      setPhase("result");
    }, 1700);
  }

  function handleConfirm() {
    setReward(null);
    setPhase("idle");
  }

  function handleNav(key) {
    setActiveTab(key);
    onNavigate?.(key);
    if (key === "home") onBack?.();
  }

  const isResult = phase === "result";
  const isDrawing = phase === "drawing";

  return (
    <div
      className="relative w-[402px] h-[874px] overflow-hidden mx-auto"
      style={{ background: "#FFF3E7" }}
    >
      {/* 상단: LevelRing + 뱃지 */}
      <div
        className="absolute flex items-start justify-between"
        style={{ left: 19, right: 19, top: 16, zIndex: 5 }}
      >
        <button
          type="button"
          onClick={() => setExpOpen((v) => !v)}
          aria-expanded={expOpen}
          aria-label={`레벨 ${level} EXP ${currentXp}/${maxXp}`}
          className="transition-transform active:scale-95"
          style={{ background: "transparent", border: "none", padding: 0, cursor: "pointer" }}
        >
          <LevelRing level={level} currentXp={currentXp} maxXp={maxXp} size={44} />
        </button>
        <TopBadges ticketCount={tickets} heartCount={hearts} />
      </div>

      {/* EXP 상세 팝오버 */}
      <div
        className="absolute"
        style={{
          left: 19,
          top: 64,
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
          zIndex: 15,
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

      {/* BONUS / 행운의 뽑기! 헤더 (idle/drawing만) */}
      {!isResult && (
      <div className="absolute" style={{ left: 26, top: 69 }}>
        <p
          className="font-noto"
          style={{
            fontSize: 15,
            fontWeight: 900,
            color: "#FFBD2C",
            letterSpacing: "-0.43px",
            lineHeight: "22px",
          }}
        >
          BONUS
        </p>
        <h1
          className="font-jeju"
          style={{
            fontSize: 25,
            color: "#E35D49",
            letterSpacing: "-0.43px",
            lineHeight: "30px",
          }}
        >
          {isResult
            ? reward?.type === "both"
              ? "짜잔!"
              : reward?.type === "exp"
              ? "오~ 좋아!"
              : "축하해!"
            : "행운의 뽑기!"}
        </h1>
        {isResult && reward?.type === "both" && (
          <p
            className="font-sejong"
            style={{ fontSize: 14, color: "#E35D49", letterSpacing: "-0.43px", fontWeight: 700, marginTop: 4 }}
          >
            레어 보상이에요!
          </p>
        )}
      </div>
      )}

      {/* 말풍선: 과연! 뭐가 나올까? (idle/drawing) */}
      {!isResult && (
        <div
          className="absolute"
          style={{ left: 119, top: 156, width: 164, height: 51 }}
        >
          <div
            className="flex items-center justify-center font-sejong"
            style={{
              width: 164,
              height: 42,
              borderRadius: 14,
              background: "rgba(255, 255, 255, 0.6)",
              border: "1px solid rgba(227, 93, 73, 0.5)",
              fontSize: 14,
              color: "#000",
              letterSpacing: "-0.43px",
            }}
          >
            과연! 뭐가 나올까?
          </div>
          {/* 말풍선 꼬리 (아래로 향하는 삼각형) */}
          <svg
            aria-hidden="true"
            className="absolute"
            style={{ left: 75, top: 41, width: 14, height: 16 }}
            viewBox="0 0 14 16"
          >
            <path
              d="M0 0 L7 14 L14 0 Z"
              fill="rgba(255, 255, 255, 0.6)"
              stroke="rgba(227, 93, 73, 0.5)"
              strokeWidth="1"
              strokeLinejoin="round"
            />
            {/* 위쪽 line은 배경에 가려지도록 흰선 덮어쓰기 */}
            <path d="M1 0 L13 0" stroke="rgba(255, 251, 246, 1)" strokeWidth="1.5" />
          </svg>
        </div>
      )}

      {/* 가챠/결과 영역 */}
      <div
        className="absolute flex items-center justify-center"
        style={{ left: 0, right: 0, top: isResult ? 105 : 200 }}
      >
        {!isResult ? (
          <img
            src={gachaImg}
            alt="가챠"
            draggable="false"
            className={`select-none pointer-events-none ${isDrawing ? "gacha-shake" : "gacha-idle"}`}
            style={{ width: 320, height: 395
              , objectFit: "contain" }}
          />
        ) : (
          <div className="relative" style={{ width: 332, height: 360 }}>
            <RewardBurst>
              <img
                src={yahoImg}
                alt="기뻐하는 토미"
                draggable="false"
                className="select-none pointer-events-none reward-pop"
                style={{ width: 240, height: 240, objectFit: "contain", position: "relative", zIndex: 2 }}
              />
            </RewardBurst>
          </div>
        )}
      </div>

      {/* 결과 카드 */}
      {isResult && reward && (
        <div className="absolute" style={{ left: 0, right: 0, top: 485 }}>
          <RewardCard reward={reward} />
        </div>
      )}

      {/* 하단 버튼 */}
      <div className="absolute" style={{ left: 56, right: 56, bottom: 112 }}>
        {!isResult ? (
          <button
            type="button"
            onClick={handleDraw}
            disabled={!canDraw}
            className="signup-submit w-full font-sejong text-white shadow-md flex items-center justify-center gap-2 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              height: 45,
              borderRadius: 50,
              background: "#92B774",
              fontSize: 16,
              fontWeight: 400,
              letterSpacing: "-0.43px",
              border: "none",
              padding: 0,
              cursor: canDraw ? "pointer" : "not-allowed",
            }}
          >
            <img src={ticketImg} alt="" style={{ width: 16, height: 16 }} />
            1개 사용해서 뽑기
          </button>
        ) : (
          <div className="flex flex-col gap-2">
            <button
              type="button"
              onClick={handleConfirm}
              className="signup-submit w-full font-sejong text-white shadow-md flex items-center justify-center transition-all duration-200"
              style={{
                height: 45,
                borderRadius: 50,
                background: "#E35D49",
                fontSize: 16,
                fontWeight: 400,
                letterSpacing: "-0.43px",
                border: "none",
                padding: 0,
                cursor: "pointer",
              }}
            >
              확인
            </button>
            {tickets > 0 ? (
              <button
                type="button"
                onClick={() => {
                  setReward(null);
                  setPhase("idle");
                  setTimeout(handleDraw, 50);
                }}
                className="w-full font-sejong text-white flex items-center justify-center gap-2 transition-all duration-200"
                style={{
                  height: 45,
                  borderRadius: 50,
                  background: "#92B774",
                  fontSize: 15,
                  fontWeight: 400,
                  letterSpacing: "-0.43px",
                  border: "none",
                  padding: 0,
                  cursor: "pointer",
                }}
              >
                한 번 더 뽑기
                <img src={ticketImg} alt="" style={{ width: 14, height: 14 }} />
                {tickets}
              </button>
            ) : (
              <div
                className="w-full font-sejong flex items-center justify-center"
                style={{
                  height: 45,
                  borderRadius: 50,
                  background: "#E5E1DC",
                  color: "#8A8580",
                  fontSize: 14,
                  fontWeight: 400,
                  letterSpacing: "-0.43px",
                }}
              >
                뽑기권이 없어요 · 다음 기회에!
              </div>
            )}
          </div>
        )}
      </div>

      {/* 하단 네비 */}
      <BottomNav active={activeTab} onChange={handleNav} />
    </div>
  );
}
