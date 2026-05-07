import { useState } from "react";
import gachaImg from "../assets/tomato/draw/gacha.png";
import yahoImg from "../assets/tomato/draw/yaho.png";
import heartImg from "../assets/tomato/_shared/heart.png";
import ticketImg from "../assets/tomato/_shared/ticket.png";
import pointerImg from "../assets/tomato/draw/pointer.png";
import { LevelRing, BottomNav } from "./Home.jsx";

/* ─────────────────────────────────────────────────────────
   레벨 임계값 — 누적 XP (그 레벨에 도달하기 위해 필요한 누적 XP)
   Lv2=5, Lv3=17, Lv4=37, Lv5=70 (Lv5 bar max: 150)
   ───────────────────────────────────────────────────────── */
const LEVEL_THRESHOLDS = { 2: 5, 3: 17, 4: 37, 5: 70, 6: 150 };

/* ─────────────────────────────────────────────────────────
   리워드 추첨은 백엔드(claim_draw_reward)가 단독으로 결정함.
   프론트는 응답을 받아 애니메이션만 표시.
   ───────────────────────────────────────────────────────── */

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

function RewardBurst({ children, compact = false }) {
  return (
    <div
      className="relative flex items-center justify-center"
      style={{
        width: compact ? 268 : 332,
        height: compact ? 268 : 332,
        transform: compact ? "scale(0.75)" : "none",
      }}
    >
      {/* 주황 방사형 글로우 */}
      <div
        aria-hidden="true"
        className="absolute burst-pulse"
        style={{
          width: 320,
          height: 320,
          transform: compact ? "scale(0.82)" : "none",
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
  );
}

/* ─────────────────────────────────────────────────────────
   결과 카드 (heart / exp / both)
   ───────────────────────────────────────────────────────── */
function RewardCard({ reward, ticketCount, onConfirm, onDrawAgain }) {
  const heartMessage =
    reward.heart > 0
      ? `게임에 참여할 수 있는 하트 ${reward.heart}개 획득!`
      : "";
  const hasTicket = ticketCount > 0;

  return (
    <div
      className="mx-auto"
      style={{
        width: "min(336px, calc(100vw - 40px))",
        borderRadius: 30,
        background: "rgba(255, 255, 255, 0.85)",
        border: "1px solid rgba(227, 93, 73, 0.4)",
        padding: "16px 20px 18px",
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
        {reward.type === "heart" && heartMessage}
        {reward.type === "exp" && "경험치를 얻었어! 레벨업까지 한 걸음 더~"}
        {reward.type === "both" && "레어 보상! 하트 + 경험치 모두 획득!"}
      </p>
      <div className="mt-4 flex flex-col gap-2">
        <button
          type="button"
          onClick={onConfirm}
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
        {hasTicket ? (
          <>
            <button
              type="button"
              onClick={onDrawAgain}
              className="w-full font-sejong text-white flex items-center justify-center transition-all duration-200"
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
            </button>
            <p
              className="font-sejong"
              style={{
                fontSize: 12,
                color: "#8A8580",
                letterSpacing: "-0.43px",
                lineHeight: "16px",
              }}
            >
              남은 티켓 수량: {ticketCount}
            </p>
          </>
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
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   DrawScreen — 메인 컴포넌트
   ───────────────────────────────────────────────────────── */
export default function DrawScreen({
  level = 3,
  currentXp = 12,
  maxXp = LEVEL_THRESHOLDS[4],
  ticketCount = 3,
  heartCount = 4,
  onDraw,
  onNavigate,
  onBack,
}) {
  // phase: idle | drawing | result
  const [phase, setPhase] = useState("idle");
  const [reward, setReward] = useState(null);
  const [activeTab, setActiveTab] = useState("rank"); // 뽑기는 일단 랭킹 탭에 매핑
  const [expOpen, setExpOpen] = useState(false);

  const canDraw = ticketCount > 0 && phase === "idle";

  async function runDraw() {
    setPhase("drawing");
    try {
      // 최소 1.7초 애니메이션 보장 + 백엔드 응답을 병렬로 대기
      const minWait = new Promise((r) => setTimeout(r, 1700));
      const [, result] = await Promise.all([minWait, onDraw()]);
      setReward(result.reward);
      setPhase("result");
    } catch {
      setPhase("idle");
    }
  }

  async function handleDraw() {
    if (!canDraw || !onDraw) return;
    runDraw();
  }

  async function handleDrawAgain() {
    if (ticketCount <= 0 || !onDraw) return;
    setReward(null);
    runDraw();
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
      className="mobile-frame flex flex-col"
      style={{ background: "#FFF3E7" }}
    >
      {/* 상단: LevelRing + 뱃지 */}
      <div
        className="relative flex-shrink-0 flex items-start justify-between"
        style={{ padding: "16px 19px 0", zIndex: 5 }}
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
        <TopBadges ticketCount={ticketCount} heartCount={heartCount} />
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

      <main
        className="flex-1 overflow-y-auto"
        style={{
          padding: isResult
            ? "18px 20px calc(96px + env(safe-area-inset-bottom))"
            : "10px 20px calc(112px + env(safe-area-inset-bottom))",
        }}
      >
        {!isResult ? (
          <div className="flex min-h-full flex-col">
            <div style={{ paddingLeft: 6, paddingTop: 4 }}>
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
                행운의 뽑기!
              </h1>
            </div>

            <div className="mx-auto mt-8" style={{ width: 164, height: 51 }}>
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
              <svg
                aria-hidden="true"
                className="relative"
                style={{ left: 75, top: -1, width: 14, height: 16 }}
                viewBox="0 0 14 16"
              >
                <path
                  d="M0 0 L7 14 L14 0 Z"
                  fill="rgba(255, 255, 255, 0.6)"
                  stroke="rgba(227, 93, 73, 0.5)"
                  strokeWidth="1"
                  strokeLinejoin="round"
                />
                <path d="M1 0 L13 0" stroke="rgba(255, 251, 246, 1)" strokeWidth="1.5" />
              </svg>
            </div>

            <div className="flex flex-1 items-center justify-center">
              <img
                src={gachaImg}
                alt="가챠"
                draggable="false"
                className={`select-none pointer-events-none ${isDrawing ? "gacha-shake" : "gacha-idle"}`}
                style={{ width: "min(320px, 82vw)", height: "auto", maxHeight: 395, objectFit: "contain" }}
              />
            </div>

            <div style={{ paddingInline: 36 }}>
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
            </div>
          </div>
        ) : (
          <div className="flex min-h-full flex-col items-center">
            <div className="w-full" style={{ paddingLeft: 6 }}>
              <p
                className="font-noto"
                style={{
                  fontSize: 14,
                  fontWeight: 900,
                  color: "#FFBD2C",
                  letterSpacing: "-0.43px",
                  lineHeight: "20px",
                }}
              >
                BONUS
              </p>
              <h1
                className="font-jeju"
                style={{
                  fontSize: 24,
                  color: "#E35D49",
                  letterSpacing: "-0.43px",
                  lineHeight: "30px",
                }}
              >
                {reward?.type === "both" ? "짜잔!" : reward?.type === "exp" ? "오~ 좋아!" : "축하해!"}
              </h1>
              {reward?.type === "both" && (
                <p
                  className="font-sejong"
                  style={{ fontSize: 13, color: "#E35D49", letterSpacing: "-0.43px", fontWeight: 700, marginTop: 2 }}
                >
                  레어 보상이에요!
                </p>
              )}
            </div>

            <div
              className="flex flex-shrink-0 items-center justify-center"
              style={{ height: "clamp(250px, 38dvh, 332px)", marginTop: 4 }}
            >
              <RewardBurst compact>
                <img
                  src={yahoImg}
                  alt="기뻐하는 토미"
                  draggable="false"
                  className="select-none pointer-events-none reward-pop"
                  style={{ width: "min(210px, 52vw)", height: "auto", objectFit: "contain", position: "relative", zIndex: 2 }}
                />
              </RewardBurst>
            </div>

            {reward && (
              <div className="w-full flex-shrink-0">
                <RewardCard
                  reward={reward}
                  ticketCount={ticketCount}
                  onConfirm={handleConfirm}
                  onDrawAgain={handleDrawAgain}
                />
              </div>
            )}
          </div>
        )}
      </main>

      {/* 하단 네비 */}
      <BottomNav active={activeTab} onChange={handleNav} />
    </div>
  );
}
