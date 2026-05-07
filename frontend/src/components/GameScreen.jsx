import { useEffect, useRef, useState } from "react";
import { BottomNav } from "./Home.jsx";
import { fetchGameRanking } from "../api.js";
import runImg from "../assets/tomato/run.png";
import jumpImg from "../assets/tomato/jump.png";
import fallImg from "../assets/tomato/fall.png";
import exerciseImg from "../assets/tomato/exercise.png";
import stoneImg from "../assets/tomato/stone.png";
import lv1Face from "../assets/tomato/_shared/Level/Lv1_face.png";
import lv2Face from "../assets/tomato/_shared/Level/Lv2_face.png";
import lv3Face from "../assets/tomato/_shared/Level/Lv3_face.png";
import lv4Face from "../assets/tomato/_shared/Level/Lv4_face.png";
import lv5Face from "../assets/tomato/_shared/Level/Lv5_face.png";
import heartImg from "../assets/tomato/_shared/heart.png";

const LEVEL_FACES = { 1: lv1Face, 2: lv2Face, 3: lv3Face, 4: lv4Face, 5: lv5Face };

/* ─────────────────────────────────────────────────────────
   토마토 달리기 게임
   - 인트로 → 플레이 → 결과 phase로 구성
   - 탭하면 점프, 돌(stone) 충돌 시 게임 오버
   ───────────────────────────────────────────────────────── */
const STAGE_W = 402;
const STAGE_H = 600; 
const GROUND_Y = 430;
const TOMATO_X = 80;
const TOMATO_W = 70;
const TOMATO_H = 70;
const STONE_W = 42;
const STONE_H = 42;
const STONE_SINK = 8;
const GRAVITY = 2150; // px/s^2
const JUMP_VELOCITY = -720; // px/s
const BASE_SPEED = 320; // px/s
const SPEED_GROWTH = 16; // 시간당 속도 증가
const MAX_SPEED = 620;
const EARLY_RETRY_LIMIT = 5;
const SCORE_DISTANCE_SCALE = 0.035;

export default function GameScreen({ onNavigate, studentId, onRecordRun, level = 3, bestScore = 0, heartCount = 4, onSpendHeart, onRefundHeart }) {
  const [phase, setPhase] = useState("intro"); // intro | play | result
  const [score, setScore] = useState(0);
  const [activeNav, setActiveNav] = useState("home");
  const [best, setBest] = useState(bestScore);
  const [bestLoaded, setBestLoaded] = useState(studentId == null);
  const [lastRun, setLastRun] = useState({ elapsed: 0, earlyRetry: false, isNewBest: false });
  const [currentFree, setCurrentFree] = useState(false); // 이번 라운드가 무료 재도전이었는지
  const [rankingOpen, setRankingOpen] = useState(false);

  useEffect(() => {
    if (studentId == null) {
      setBest(bestScore);
      setBestLoaded(true);
      return;
    }
    let cancelled = false;
    setBestLoaded(false);
    fetchGameRanking("all", "run")
      .then((data) => {
        if (cancelled) return;
        const me = Array.isArray(data) ? data.find((r) => r.student_id === studentId) : null;
        setBest(me?.best_score || 0);
      })
      .catch(() => {
        if (!cancelled) setBest(0);
      })
      .finally(() => {
        if (!cancelled) setBestLoaded(true);
      });
    return () => { cancelled = true; };
  }, [studentId, bestScore]);

  async function start({ free = false } = {}) {
    if (!free) {
      if (heartCount <= 0) return;
    }
    setCurrentFree(free);
    setScore(0);
    setPhase("play");
    if (!free && studentId != null) {
      onSpendHeart?.().catch(() => {});
    }
  }

  async function handleGameOver({ score: finalScore, elapsed }) {
    const earlyRetry = elapsed < EARLY_RETRY_LIMIT;
    const recordableRun = !earlyRetry && finalScore > 0;
    const isNewBest = recordableRun && finalScore > best;
    if (isNewBest) setBest(finalScore);
    if (currentFree) {
      // 무료 재도전 라운드 — 5초 넘게 살았으면 그제서야 하트 차감
      if (!earlyRetry) await onSpendHeart?.();
    } else {
      // 차감하고 시작한 라운드 — 5초 안에 죽으면 환불
      if (earlyRetry) await onRefundHeart?.();
    }
    // 5초 미만(early retry) 라운드는 hateful이라 백엔드 기록 X — 점수 0/스팸 방지
    if (recordableRun && studentId != null) {
      await onRecordRun?.({ score: finalScore, durationSec: Math.round(elapsed) });
    }
    setScore(finalScore);
    setLastRun({ elapsed, earlyRetry, isNewBest });
    setPhase("result");
  }

  function handleNav(key) {
    setActiveNav(key);
    onNavigate?.(key);
  }

  return (
    <div
      className="mobile-frame flex flex-col"
      style={{ background: "#FFF3E7" }}
    >
      {/* 본문 — 게임 영역 */}
      <div className="flex-1 relative overflow-hidden">
        {phase === "intro" && (
          <IntroScreen
            onStart={() => start()}
            onOpenRanking={() => setRankingOpen(true)}
            bestScore={best}
            bestLoaded={bestLoaded}
            heartCount={heartCount}
          />
        )}
        {phase === "play" && (
          <PlayScreen
            level={level}
            onGameOver={handleGameOver}
          />
        )}
        {phase === "result" && (
          <ResultScreen
            studentId={studentId}
            score={score}
            best={best}
            heartCount={heartCount}
            earlyRetry={lastRun.earlyRetry}
            elapsed={lastRun.elapsed}
            isNewBest={lastRun.isNewBest}
            onOpenRanking={() => setRankingOpen(true)}
            onRetry={() => start({ free: lastRun.earlyRetry })}
            onConfirm={() => setPhase("intro")}
          />
        )}
      </div>

      <BottomNav active={activeNav} onChange={handleNav} />
      <GameRankingModal
        open={rankingOpen}
        studentId={studentId}
        currentScore={score}
        onClose={() => setRankingOpen(false)}
      />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   인트로 화면
   ───────────────────────────────────────────────────────── */
function IntroScreen({ onStart, onOpenRanking, bestScore, bestLoaded, heartCount }) {
  const canStart = heartCount > 0;
  return (
    <div
      className="absolute inset-0 flex flex-col items-center"
      style={{
        background: "linear-gradient(180deg, #BFE5FF 0%, #FFF3E7 68%)",
        cursor: canStart ? "pointer" : "default",
      }}
      onClick={() => {
        if (canStart) onStart();
      }}
    >
      <Sun style={{ right: 30, top: 30 }} />
      <Hill style={{ left: -40, top: 245, opacity: 0.6, transform: "scale(1.05)" }} />
      <Hill style={{ right: -62, top: 278, opacity: 0.45, transform: "scale(0.82)" }} />
      {/* 타이틀 */}
      <div className="flex-shrink-0 text-center" style={{ paddingTop: 36 }}>
        <div className="flex items-center justify-center" style={{ gap: 8 }}>
          <span
            className="font-sejong"
            style={{ fontSize: 30, fontWeight: 700, color: "#1a1a1a", letterSpacing: "-0.43px" }}
          >
            토미랑 달리기
          </span>
        </div>
        <p
          className="font-sejong"
          style={{
            fontSize: 14, color: "#444", letterSpacing: "-0.43px",
            marginTop: 8, lineHeight: "20px",
          }}
        >
          돌을 피해서<br />더 멀리 달려보세요!
        </p>

        {/* 최고기록 */}
        <div className="flex items-center justify-center" style={{ gap: 12, marginTop: 18 }}>
          <span
            className="inline-flex items-center font-sejong"
            style={{
              background: "#FFD56B",
              border: "none",
              borderRadius: 999,
              paddingInline: 14,
              height: 30,
              gap: 6,
              fontSize: 13,
              fontWeight: 800,
              color: "#7A5A0E",
              letterSpacing: "-0.3px",
            }}
          >
            <span>★</span>
            최고 기록 {bestLoaded ? bestScore.toLocaleString() : "..."}
          </span>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onOpenRanking?.();
            }}
            className="font-sejong inline-flex items-center justify-center transition-transform active:scale-95"
            style={{
              height: 30,
              paddingInline: 14,
              borderRadius: 999,
              background: "#FFFFFF",
              border: "1px solid rgba(227, 93, 73, 0.26)",
              color: "#E35D49",
              fontSize: 12,
              fontWeight: 800,
              letterSpacing: "-0.3px",
              cursor: "pointer",
              boxShadow: "0 4px 10px rgba(80, 60, 40, 0.06)",
            }}
          >
            랭킹 보기
          </button>
        </div>
      </div>

      {/* 캐릭터 */}
      <div className="flex-1 flex items-end justify-center w-full" style={{ paddingBottom: "calc(110px + env(safe-area-inset-bottom))" }}>
        <DesertGround speed={0} distance={0} groundY={390}>
          <img
            src={runImg}
            alt=""
            draggable="false"
            className="select-none pointer-events-none"
            style={{ width: 130, height: 130, objectFit: "contain", zIndex: 2, transform: "translateX(16px)" }}
          />
        </DesertGround>
      </div>

      {/* 시작하기 안내 */}
      <div
        className="absolute flex flex-col items-center"
        style={{
          bottom: 26,
          left: 0, right: 0,
        }}
      >
        {!canStart && (
          <span
            className="font-sejong"
            style={{
              height: 34,
              paddingInline: 16,
              borderRadius: 999,
              background: "rgba(255,255,255,0.9)",
              border: "1px solid rgba(227, 93, 73, 0.18)",
              display: "inline-flex",
              alignItems: "center",
              color: "#E35D49",
              fontSize: 13,
              fontWeight: 700,
              letterSpacing: "-0.3px",
            }}
          >
            하트가 부족해요
          </span>
        )}
        {canStart && (
          <span
            className="font-sejong"
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: "#444",
              letterSpacing: "-0.43px",
              marginTop: 4,
            }}
          >
            화면을 눌러 시작하기
          </span>
        )}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   플레이 화면 — 게임 루프
   ───────────────────────────────────────────────────────── */
function PlayScreen({ level, onGameOver }) {
  const [tomatoY, setTomatoY] = useState(GROUND_Y);
  const [stones, setStones] = useState([]);
  const [distance, setDistance] = useState(0);
  const [speedView, setSpeedView] = useState(BASE_SPEED);
  const [paused, setPaused] = useState(true);
  const [jumping, setJumping] = useState(false);
  const [crashed, setCrashed] = useState(false);
  const [countdown, setCountdown] = useState(3);
  const lastTimeRef = useRef(performance.now());
  const spawnTimerRef = useRef(0);
  const elapsedRef = useRef(0);
  const rafRef = useRef(null);
  const tomatoYRef = useRef(GROUND_Y);
  const vyRef = useRef(0);
  const stonesRef = useRef([]);
  const distanceRef = useRef(0);
  const pausedRef = useRef(true);
  const gameOverRef = useRef(false);
  const onGameOverRef = useRef(onGameOver);
  onGameOverRef.current = onGameOver;

  // 점프
  function jump() {
    if (pausedRef.current || gameOverRef.current) return;
    if (tomatoYRef.current >= GROUND_Y - 0.5) {
      vyRef.current = JUMP_VELOCITY;
      tomatoYRef.current = GROUND_Y - 1;
      setTomatoY(tomatoYRef.current);
      setJumping(true);
    }
  }

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  useEffect(() => {
    if (countdown == null) return undefined;
    if (countdown <= 0) {
      setCountdown(null);
      setPaused(false);
      return undefined;
    }
    const timer = setTimeout(() => setCountdown((value) => value - 1), 850);
    return () => clearTimeout(timer);
  }, [countdown]);

  function togglePause() {
    if (gameOverRef.current) return;
    if (pausedRef.current) {
      setCountdown(3);
      return;
    }
    setCountdown(null);
    setPaused(true);
  }

  function startCountdownNow() {
    setCountdown(null);
    setPaused(false);
  }

  // 게임 루프
  useEffect(() => {
    function tick(now) {
      const dt = Math.min((now - lastTimeRef.current) / 1000, 0.05);
      lastTimeRef.current = now;

      if (!pausedRef.current && !gameOverRef.current) {
        elapsedRef.current += dt;
        const speed = Math.min(MAX_SPEED, BASE_SPEED + elapsedRef.current * SPEED_GROWTH);
        setSpeedView(speed);

        // 거리 증가
        distanceRef.current += speed * dt * SCORE_DISTANCE_SCALE;
        setDistance(distanceRef.current);

        // 토마토 물리
        vyRef.current += GRAVITY * dt;
        tomatoYRef.current += vyRef.current * dt;
        if (tomatoYRef.current >= GROUND_Y) {
          tomatoYRef.current = GROUND_Y;
          vyRef.current = 0;
          setJumping(false);
        }
        setTomatoY(tomatoYRef.current);

        // 돌 이동
        stonesRef.current = stonesRef.current
          .map((s) => ({ ...s, x: s.x - speed * dt }))
          .filter((s) => s.x > -STONE_W - 10);

        // 돌 스폰
        spawnTimerRef.current -= dt;
        if (spawnTimerRef.current <= 0) {
          stonesRef.current = [...stonesRef.current, makeStone()];
          const difficulty = Math.min(1, elapsedRef.current / 45);
          const minGap = 0.75 - difficulty * 0.16;
          const randomGap = 1.4 - difficulty * 0.35;
          spawnTimerRef.current = minGap + Math.random() * randomGap;
        }
        setStones(stonesRef.current);

        // 충돌 체크
        const tomatoBox = {
          x: TOMATO_X + 8,
          y: tomatoYRef.current - TOMATO_H + 8,
          w: TOMATO_W - 16,
          h: TOMATO_H - 16,
        };
        for (const s of stonesRef.current) {
          const sBox = { x: s.x + 4, y: GROUND_Y - s.h + 6 + STONE_SINK, w: s.w - 8, h: s.h - 10 };
          if (
            tomatoBox.x < sBox.x + sBox.w &&
            tomatoBox.x + tomatoBox.w > sBox.x &&
            tomatoBox.y < sBox.y + sBox.h &&
            tomatoBox.y + tomatoBox.h > sBox.y
          ) {
            gameOverRef.current = true;
            pausedRef.current = true;
            setPaused(true);
            setJumping(false);
            setCrashed(true);
            const finalScore = Math.floor(distanceRef.current);
            const elapsed = elapsedRef.current;
            setTimeout(() => onGameOverRef.current?.({ score: finalScore, elapsed }), 600);
            return;
          }
        }
      }

      rafRef.current = requestAnimationFrame(tick);
    }

    lastTimeRef.current = performance.now();
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  return (
    <div
      className="absolute inset-0"
      style={{
        background: "linear-gradient(180deg, #BFE5FF 0%, #FFF3E7 76%)",
        cursor: "pointer",
        userSelect: "none",
        touchAction: "none",
      }}
      onPointerDown={(e) => {
        if (e.pointerType === "mouse" && e.button !== 0) return;
        e.preventDefault();
        if (countdown != null) {
          startCountdownNow();
          return;
        }
        jump();
      }}
    >
      {/* 점수 (좌측 상단) */}
      <div
        className="absolute flex items-center"
        style={{
          left: 14, top: 14,
          background: "rgba(255,255,255,0.92)",
          border: "1px solid rgba(227, 93, 73, 0.16)",
          borderRadius: 18,
          padding: "7px 12px",
          height: 52,
          gap: 10,
          boxShadow: "0 8px 18px rgba(80, 60, 40, 0.10)",
          zIndex: 8,
        }}
      >
        <img
          src={LEVEL_FACES[Math.min(5, Math.max(1, level))]}
          alt=""
          draggable="false"
          style={{ width: 30, height: 30, objectFit: "contain" }}
        />
        <div className="font-sejong" style={{ lineHeight: 1 }}>
          <div style={{ fontSize: 10, color: "#E35D49", fontWeight: 700, letterSpacing: "-0.3px" }}>DISTANCE</div>
          <div style={{ fontSize: 18, fontWeight: 800, color: "#1a1a1a", letterSpacing: "-0.3px", marginTop: 4 }}>
            {Math.floor(distance)}m
          </div>
        </div>
      </div>

      {/* 일시정지 (우측 상단) */}
      <button
        type="button"
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => { e.stopPropagation(); togglePause(); }}
        aria-label={paused ? "계속하기" : "일시정지"}
        className="absolute flex items-center justify-center transition-transform active:scale-95"
        style={{
          right: 14, top: 14,
          width: 38,
          height: 38,
          padding: 0,
          borderRadius: "50%",
          background: paused ? "#92B774" : "#E35D49",
          border: "2px solid rgba(255,255,255,0.86)",
          boxShadow: paused
            ? "0 5px 12px rgba(146, 183, 116, 0.32)"
            : "0 5px 12px rgba(227, 93, 73, 0.30)",
          cursor: "pointer",
          zIndex: 8,
          color: "#FFFFFF",
        }}
      >
        {paused ? (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M7 4 L19 12 L7 20 Z" />
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="4" width="4" height="16" rx="1" />
            <rect x="14" y="4" width="4" height="16" rx="1" />
          </svg>
        )}
      </button>

      {countdown != null && countdown > 0 && (
        <div
          className="absolute inset-0 flex items-center justify-center font-sejong"
          style={{
            zIndex: 12,
            background: "rgba(255, 243, 231, 0.34)",
            backdropFilter: "blur(1px)",
            pointerEvents: "none",
          }}
        >
          <div
            style={{
              width: 104,
              height: 104,
              borderRadius: "50%",
              background: "#FFFFFF",
              border: "3px solid rgba(227, 93, 73, 0.16)",
              boxShadow: "0 14px 28px rgba(80, 60, 40, 0.16)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#E35D49",
              fontSize: 48,
              fontWeight: 800,
              letterSpacing: "0",
            }}
          >
            {countdown}
          </div>
        </div>
      )}

      {/* 구름 데코 */}
      <Cloud style={{ left: 40, top: 80, opacity: 0.85 }} />
      <Cloud style={{ right: 60, top: 130, opacity: 0.7, transform: "scale(0.8)" }} />
      <Cloud style={{ left: 200, top: 60, opacity: 0.6, transform: "scale(0.7)" }} />
      <Sun style={{ right: 54, top: 84, opacity: 0.85 }} />
      <Hill style={{ left: -64, top: 300, opacity: 0.56 }} />
      <Hill style={{ right: -72, top: 322, opacity: 0.42, transform: "scale(0.78)" }} />

      {/* 땅 */}
      <DesertGround speed={speedView} distance={distance} />

      {/* 토마토 */}
      <img
        src={crashed ? fallImg : jumping ? jumpImg : runImg}
        alt=""
        draggable="false"
        className="absolute select-none pointer-events-none"
        style={{
          left: TOMATO_X,
          top: tomatoY - TOMATO_H,
          width: TOMATO_W,
          height: TOMATO_H,
          objectFit: "contain",
          zIndex: 3,
        }}
      />

      {/* 돌 장애물 */}
      {stones.map((s) => (
        <img
          key={s.id}
          src={stoneImg}
          alt=""
          draggable="false"
          className="absolute select-none pointer-events-none"
          style={{
            left: s.x,
            top: GROUND_Y - s.h + STONE_SINK,
            width: s.w,
            height: s.h,
            objectFit: "contain",
            zIndex: 2,
          }}
        />
      ))}

      {/* 안내 */}
      <div
        className="absolute flex justify-center"
        style={{ left: 0, right: 0, bottom: 26 }}
      >
        <span
          className="font-sejong"
          style={{
            background: "rgba(255,255,255,0.92)",
            border: "1px solid rgba(227, 93, 73, 0.2)",
            borderRadius: 999,
            paddingInline: 18,
            height: 36,
            display: "inline-flex",
            alignItems: "center",
            fontSize: 14,
            fontWeight: 600,
            color: "#1a1a1a",
            letterSpacing: "-0.43px",
            boxShadow: "0 4px 10px rgba(0,0,0,0.06)",
          }}
        >
          탭해서 점프! · 점점 빨라져요
        </span>
      </div>
    </div>
  );
}

function makeStone() {
  const scale = 0.82 + Math.random() * 0.42;
  return {
    id: `${Date.now()}-${Math.random()}`,
    x: STAGE_W + 28 + Math.random() * 70,
    w: STONE_W * scale,
    h: STONE_H * scale,
  };
}

/* ─────────────────────────────────────────────────────────
   결과 화면
   ───────────────────────────────────────────────────────── */
function ResultScreen({ studentId, score, best, heartCount, earlyRetry, elapsed, isNewBest, onOpenRanking, onRetry, onConfirm }) {
  const canRetry = earlyRetry || heartCount > 0;
  return (
    <div
      className="absolute inset-0 overflow-y-auto"
      style={{
        background: "linear-gradient(180deg, #FFF3E7 0%, #FFEFE1 100%)",
        padding: "28px 24px calc(100px + env(safe-area-inset-bottom))",
      }}
    >
      <div className="flex flex-col items-center">
        <div
          className="font-sejong"
          style={{ fontSize: 15, fontWeight: 800, color: "#E35D49", letterSpacing: "-0.3px" }}
        >
          {isNewBest ? "NEW BEST!" : "GAME OVER"}
        </div>
        <div
          className="font-sejong"
          style={{ fontSize: 25, fontWeight: 800, color: "#1a1a1a", letterSpacing: "-0.3px", marginTop: 4 }}
        >
          {isNewBest ? "최고 기록을 세웠어요!" : earlyRetry ? "한 번 더 도전해볼까요?" : "수고했어요!"}
        </div>
        <span
          className="font-sejong inline-flex items-center"
          style={{
            marginTop: 10,
            height: 30,
            paddingInline: 12,
            borderRadius: 999,
            background: "rgba(252, 228, 225, 0.85)",
            border: "1px solid rgba(227, 93, 73, 0.16)",
            color: "#E35D49",
            fontSize: 13,
            fontWeight: 800,
            letterSpacing: "-0.3px",
            gap: 6,
          }}
        >
          <img src={heartImg} alt="" style={{ width: 15, height: 15, objectFit: "contain" }} />
          남은 하트 {heartCount}
        </span>
      </div>

      {/* 점수 카드 */}
      <div
        className="mt-4 w-full text-center relative"
        style={{
          background: "#FFFFFF",
          borderRadius: 28,
          padding: "22px 18px 24px",
          boxShadow: "0 12px 26px rgba(227, 93, 73, 0.10)",
          border: `2px solid ${isNewBest ? "rgba(227, 93, 73, 0.42)" : "rgba(227, 93, 73, 0.12)"}`,
        }}
      >
        <div
          className="font-sejong"
          style={{ fontSize: 12, color: "#75726e", letterSpacing: "-0.43px" }}
        >
          점수
        </div>
        <div
          className="font-sejong"
          style={{
            fontSize: 36,
            fontWeight: 800,
            color: "#1a1a1a",
            letterSpacing: "-0.43px",
            marginTop: 2,
          }}
        >
          {score.toLocaleString()}
          <span style={{ fontSize: 16, color: "#8A8580", marginLeft: 4 }}>m</span>
        </div>
        {isNewBest && (
          <span
            className="font-sejong inline-flex items-center justify-center"
            style={{
              marginTop: 10,
              height: 28,
              paddingInline: 12,
              borderRadius: 999,
              background: "#FFE5DD",
              color: "#E35D49",
              fontSize: 12,
              fontWeight: 800,
              letterSpacing: "-0.3px",
            }}
          >
            최고 기록 달성
          </span>
        )}
        <img
          src={exerciseImg}
          alt=""
          draggable="false"
          className="absolute select-none pointer-events-none"
          style={{
            right: -5,
            bottom: -18,
            width: 86,
            height: 86,
            objectFit: "contain",
            opacity: 0.95,
            zIndex: 0,
          }}
        />
      </div>

      {/* 최고기록 + 생존시간 */}
      <div className="mt-3 w-full flex" style={{ gap: 10 }}>
        <StatBox label="최고 기록" value={`${best.toLocaleString()}m`} />
        <StatBox label="생존 시간" value={`${elapsed.toFixed(1)}초`} accent />
      </div>

      <GameRankingPreview studentId={studentId} score={score} onOpenRanking={onOpenRanking} />

      {/* 버튼 */}
      <div className="mt-4 w-full flex flex-col" style={{ gap: 10 }}>
        <button
          type="button"
          onClick={onConfirm}
          className="signup-submit font-sejong text-white shadow-md transition-all flex items-center justify-center"
          style={{
            height: 50, borderRadius: 999, background: "#E35D49",
            fontSize: 16, fontWeight: 500, border: "none", padding: 0,
            letterSpacing: "-0.43px", cursor: "pointer",
          }}
        >
          확인
        </button>
        <button
          type="button"
          onClick={onRetry}
          disabled={!canRetry}
          className="font-sejong flex items-center justify-center transition-all"
          style={{
            height: 45,
            borderRadius: 50,
            background: canRetry ? "#92B774" : "#E5E1DC",
            color: canRetry ? "#FFFFFF" : "#8A8580",
            border: "none",
            fontSize: 15,
            fontWeight: 400,
            letterSpacing: "-0.43px",
            cursor: canRetry ? "pointer" : "not-allowed",
            gap: 8,
            padding: 0,
          }}
        >
          {earlyRetry ? (
            "한 번 더 도전"
          ) : heartCount > 0 ? (
            <>
              하트로 다시 도전
              <img src={heartImg} alt="" style={{ width: 14, height: 14, objectFit: "contain" }} />
              {heartCount}
            </>
          ) : (
            "하트가 부족해요"
          )}
        </button>
      </div>
    </div>
  );
}

function StatBox({ label, value, accent }) {
  return (
    <div
      className="flex-1 flex flex-col items-center font-sejong"
      style={{
        background: "#FFFFFF",
        borderRadius: 18,
        padding: "12px 10px",
        border: "1px solid rgba(227, 93, 73, 0.12)",
      }}
    >
      <span style={{ fontSize: 11, color: "#75726e", letterSpacing: "-0.43px" }}>{label}</span>
      <span
        style={{
          fontSize: 18,
          fontWeight: 800,
          color: accent ? "#E35D49" : "#1a1a1a",
          letterSpacing: "-0.43px",
          marginTop: 2,
        }}
      >
        {value}
      </span>
    </div>
  );
}

function GameRankingPreview({ studentId, score, onOpenRanking }) {
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);

  // 결과 화면 진입 시 주간 게임 랭킹 조회
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchGameRanking("week", "run")
      .then((data) => { if (!cancelled) setList(Array.isArray(data) ? data : []); })
      .catch(() => { if (!cancelled) setList([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [studentId, score]);

  // API 응답 → 표시 모양으로 변환 자기 자신은 student_id 매칭
  const ranked = list.map((r) => ({
    name: r.student_id === studentId ? "나" : r.student_name,
    score: r.student_id === studentId ? Math.max(r.best_score, score) : r.best_score,
    rank: r.rank,
    isMe: r.student_id === studentId,
  }));

  const top3 = ranked.slice(0, 3);
  const me = ranked.find((u) => u.isMe);
  const meInTop3 = me && me.rank <= 3;
  const rows = me && !meInTop3 ? [...top3, me] : ranked.slice(0, 4);
  const placeholderRows = Array.from({ length: 4 }, (_, i) => ({ rank: i + 1 }));

  return (
    <button
      type="button"
      onClick={onOpenRanking}
      className="mt-3 w-full font-sejong"
      style={{
        background: "#FFFFFF",
        borderRadius: 22,
        padding: "14px 16px",
        minHeight: 214,
        border: "1px solid rgba(227, 93, 73, 0.12)",
        boxShadow: "0 6px 14px rgba(80, 60, 40, 0.06)",
        cursor: "pointer",
        textAlign: "left",
      }}
    >
      <div
        className="flex items-center justify-between"
        style={{ marginBottom: 10 }}
      >
        <span style={{ fontSize: 13, fontWeight: 800, color: "#1a1a1a", letterSpacing: "-0.3px" }}>
          게임 랭킹 <span style={{ fontSize: 11, fontWeight: 600, color: "#75726e" }}>· 주간</span>
        </span>
        <span style={{ fontSize: 11, fontWeight: 700, color: "#E35D49", letterSpacing: "-0.3px" }}>
          전체 보기
        </span>
      </div>
      <div className="flex flex-col" style={{ gap: 7 }}>
        {(loading ? placeholderRows : rows).map((row) => {
          if (loading) {
            return (
              <div
                key={`placeholder-${row.rank}`}
                style={{
                  height: 34,
                  borderRadius: 999,
                  background: "rgba(246, 241, 235, 0.76)",
                }}
              />
            );
          }
          const mine = !!row.isMe;
          return (
            <div
              key={`${row.name}-${row.rank}`}
              className="flex items-center"
              style={{
                height: 34,
                borderRadius: 999,
                paddingInline: 10,
                background: mine ? "rgba(227, 93, 73, 0.09)" : "rgba(246, 241, 235, 0.76)",
                color: mine ? "#E35D49" : "#444",
                gap: 9,
              }}
            >
              <span
                className="flex items-center justify-center"
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: "50%",
                  background: row.rank === 1 ? "#FFD56B" : "#FFFFFF",
                  color: row.rank === 1 ? "#7A5A0E" : "#75726e",
                  fontSize: 11,
                  fontWeight: 800,
                }}
              >
                {row.rank}
              </span>
              <span style={{ flex: 1, fontSize: 12, fontWeight: 800, letterSpacing: "-0.3px" }}>
                {row.name}
              </span>
              <span style={{ fontSize: 12, fontWeight: 800, letterSpacing: "-0.3px" }}>
                {row.score.toLocaleString()}m
              </span>
            </div>
          );
        })}
      </div>
    </button>
  );
}

function GameRankingModal({ open, studentId, currentScore = 0, onClose }) {
  const [period, setPeriod] = useState("week");
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    fetchGameRanking(period, "run")
      .then((data) => {
        if (!cancelled) setList(Array.isArray(data) ? data : []);
      })
      .catch(() => {
        if (!cancelled) setList([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [open, period, studentId, currentScore]);

  if (!open) return null;

  const rows = list.map((r) => ({
    id: r.student_id,
    rank: r.rank,
    name: r.student_id === studentId ? "나" : r.student_name,
    score: r.student_id === studentId ? Math.max(r.best_score || 0, currentScore) : r.best_score || 0,
    plays: r.plays || 0,
    isMe: r.student_id === studentId,
  }));
  const me = rows.find((r) => r.isMe);
  const visibleRows = rows.slice(0, 8);
  const meVisible = me && !visibleRows.some((r) => r.id === me.id);

  return (
    <div
      className="absolute inset-0 flex items-end justify-center"
      style={{ zIndex: 30, background: "rgba(34, 28, 24, 0.28)", padding: "0 16px calc(88px + env(safe-area-inset-bottom))" }}
      onClick={onClose}
    >
      <section
        className="w-full font-sejong"
        onClick={(e) => e.stopPropagation()}
        style={{
          maxWidth: 360,
          maxHeight: "min(620px, calc(100dvh - 120px))",
          borderRadius: "28px 28px 22px 22px",
          background: "linear-gradient(180deg, #FFFFFF 0%, #FFF7EE 100%)",
          border: "1px solid rgba(227, 93, 73, 0.18)",
          boxShadow: "0 18px 40px rgba(80, 60, 40, 0.22)",
          overflow: "hidden",
        }}
      >
        <div
          className="flex items-center justify-between"
          style={{ padding: "16px 16px 12px", borderBottom: "1px solid rgba(227, 93, 73, 0.10)" }}
        >
          <div>
            <div style={{ fontSize: 11, color: "#E35D49", fontWeight: 900, letterSpacing: "-0.2px" }}>
              TOMI RUN
            </div>
            <h2 style={{ marginTop: 2, fontSize: 20, color: "#1a1a1a", fontWeight: 900, letterSpacing: "-0.43px" }}>
              달리기 랭킹
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="게임 랭킹 닫기"
            className="flex items-center justify-center"
            style={{
              width: 34,
              height: 34,
              borderRadius: "50%",
              border: "none",
              background: "rgba(227, 93, 73, 0.10)",
              color: "#E35D49",
              fontSize: 20,
              cursor: "pointer",
            }}
          >
            ×
          </button>
        </div>

        <div style={{ padding: "12px 16px 0" }}>
          <div
            className="flex"
            style={{ background: "rgba(246, 241, 235, 0.9)", borderRadius: 999, padding: 4 }}
          >
            {[
              ["week", "주간"],
              ["month", "월간"],
              ["all", "전체"],
            ].map(([key, label]) => {
              const active = period === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setPeriod(key)}
                  className="flex-1 font-sejong"
                  style={{
                    height: 34,
                    borderRadius: 999,
                    border: "none",
                    background: active ? "#E35D49" : "transparent",
                    color: active ? "#FFFFFF" : "#8A8580",
                    fontSize: 13,
                    fontWeight: 800,
                    cursor: "pointer",
                  }}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="overflow-y-auto" style={{ maxHeight: "calc(min(620px, 100dvh - 120px) - 132px)", padding: "12px 16px 16px" }}>
          {loading ? (
            <div style={{ padding: "28px 0", textAlign: "center", color: "#8A8580", fontSize: 13 }}>
              랭킹 불러오는 중...
            </div>
          ) : visibleRows.length === 0 ? (
            <div style={{ padding: "28px 0", textAlign: "center", color: "#8A8580", fontSize: 13 }}>
              아직 기록이 없어요
            </div>
          ) : (
            <div className="flex flex-col" style={{ gap: 8 }}>
              {visibleRows.map((row) => (
                <GameRankingRow key={row.id} row={row} />
              ))}
              {meVisible && (
                <>
                  <div style={{ height: 1, background: "rgba(227, 93, 73, 0.14)", margin: "2px 0" }} />
                  <GameRankingRow row={me} />
                </>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function GameRankingRow({ row }) {
  const medal =
    row.rank === 1 ? "#FFD56B" :
    row.rank === 2 ? "#D9D5D0" :
    row.rank === 3 ? "#E8B53D" :
    "#FFFFFF";

  return (
    <div
      className="flex items-center"
      style={{
        minHeight: 46,
        borderRadius: 18,
        padding: "8px 10px",
        background: row.isMe ? "rgba(227, 93, 73, 0.10)" : "#FFFFFF",
        border: row.isMe ? "1px solid rgba(227, 93, 73, 0.30)" : "1px solid rgba(227, 93, 73, 0.10)",
        gap: 10,
      }}
    >
      <span
        className="flex items-center justify-center"
        style={{
          width: 28,
          height: 28,
          borderRadius: "50%",
          background: medal,
          color: row.rank <= 3 ? "#7A5A0E" : "#8A8580",
          fontSize: 12,
          fontWeight: 900,
          flexShrink: 0,
        }}
      >
        {row.rank}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 900, color: row.isMe ? "#E35D49" : "#1a1a1a", letterSpacing: "-0.3px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {row.name}
        </div>
        <div style={{ marginTop: 1, fontSize: 11, color: "#8A8580", letterSpacing: "-0.2px" }}>
          플레이 {row.plays}회
        </div>
      </div>
      <div
        className="flex items-baseline justify-end"
        style={{ textAlign: "right", flexShrink: 0, minWidth: 72, gap: 2 }}
      >
        <span style={{ fontSize: 15, fontWeight: 900, color: "#1a1a1a", letterSpacing: "-0.3px" }}>
          {row.score.toLocaleString()}
        </span>
        <span style={{ fontSize: 10, color: "#8A8580", letterSpacing: "-0.2px" }}>m</span>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   배경 — 사막 땅 + 선인장
   ───────────────────────────────────────────────────────── */
function DesertGround({ children, speed = BASE_SPEED, distance = 0, groundY = GROUND_Y }) {
  const stripeOffset = -(distance * 1.8) % 84;
  const pebbleOffset = -(distance * 1.2) % 120;
  return (
    <div
      className="absolute"
      style={{
        left: 0, right: 0, top: groundY, bottom: 0,
        background: "linear-gradient(180deg, #F8D79A 0%, #E6B362 100%)",
        zIndex: 0,
        overflow: "hidden",
      }}
    >
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: 0,
          height: 10,
          background: "rgba(255,255,255,0.34)",
          borderBottom: "2px solid rgba(173, 112, 43, 0.12)",
        }}
      />
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          left: stripeOffset,
          right: -120,
          top: 54,
          height: 8,
          background: "repeating-linear-gradient(90deg, rgba(255,255,255,0.56) 0 34px, transparent 34px 84px)",
          opacity: Math.min(1, 0.55 + (speed - BASE_SPEED) / 500),
        }}
      />
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          left: pebbleOffset,
          right: -140,
          top: 94,
          height: 44,
          background: "radial-gradient(circle at 12px 12px, rgba(128,83,42,0.18) 0 3px, transparent 4px), radial-gradient(circle at 72px 30px, rgba(128,83,42,0.14) 0 2px, transparent 3px)",
          backgroundSize: "120px 44px",
        }}
      />
      {children}
    </div>
  );
}

function Sun({ style }) {
  return (
    <div
      aria-hidden="true"
      style={{
        position: "absolute",
        width: 58,
        height: 58,
        borderRadius: "50%",
        background: "#FFD56B",
        boxShadow: "0 0 0 12px rgba(255, 213, 107, 0.18)",
        ...style,
      }}
    />
  );
}

function Hill({ style }) {
  return (
    <svg
      width="260"
      height="112"
      viewBox="0 0 260 112"
      fill="none"
      aria-hidden="true"
      style={{ position: "absolute", ...style }}
    >
      <path d="M0 112 C42 34 92 16 136 64 C174 18 225 32 260 112 H0Z" fill="#CDE6B8" />
      <path d="M70 112 C103 48 143 36 178 78 C205 44 235 56 260 112 H70Z" fill="#B8DFA8" opacity="0.8" />
    </svg>
  );
}

function Cloud({ style }) {
  return (
    <svg
      width="60" height="32" viewBox="0 0 60 32" fill="none"
      style={{ position: "absolute", ...style }}
      aria-hidden="true"
    >
      <ellipse cx="18" cy="20" rx="12" ry="10" fill="#FFFFFF" />
      <ellipse cx="32" cy="14" rx="14" ry="11" fill="#FFFFFF" />
      <ellipse cx="46" cy="20" rx="11" ry="9" fill="#FFFFFF" />
    </svg>
  );
}
