import lv1 from "../assets/tomato/_shared/Level/LV1.png";
import lv2 from "../assets/tomato/_shared/Level/LV2.png";
import lv3 from "../assets/tomato/_shared/Level/LV3.png";
import lv4 from "../assets/tomato/_shared/Level/LV4.png";
import lv5 from "../assets/tomato/_shared/Level/LV5.png";
import leaf from "../assets/tomato/_shared/leaf.png";
import heart from "../assets/tomato/_shared/heart.png";

const LEVEL_IMAGES = { 1: lv1, 2: lv2, 3: lv3, 4: lv4, 5: lv5 };

const LEVEL_THEMES = {
  1: { name: "시작하는 토마", main: "#A8D17C", soft: "#E5F0DC" },
  2: { name: "배우는 토마",   main: "#7BA45C", soft: "#DDEBC9" },
  3: { name: "성장하는 토마", main: "#E8B53D", soft: "#FFEFC2" },
  4: { name: "익어가는 토마", main: "#F08A3E", soft: "#FFD9B8" },
  5: { name: "반짝이는 토마", main: "#E35D49", soft: "#FCE0DA" },
};

// 토마토 PNG마다 캐릭터 발 위치가 달라서 그림자를 레벨별로 미세 조정
// top: 그림자 세로 위치 / left·width: 가로 위치/너비
const LEVEL_SHADOWS = {
  1: { left: 111, top: 418, width: 180 },
  2: { left: 111, top: 420, width: 180 },
  3: { left: 111, top: 413, width: 180 },
  4: { left: 111, top: 420, width: 180 },
  5: { left: 111, top: 430, width: 180 },
};

const CONFETTI = [
  { x: 70,  y: 320, size: 8,  color: "#F2A8A0", shape: "diamond" },
  { x: 320, y: 310, size: 9,  color: "#F4B6C2", shape: "diamond" },
  { x: 60,  y: 430, size: 7,  color: "#A7DAA7", shape: "diamond" },
  { x: 330, y: 440, size: 8,  color: "#A7DAA7", shape: "diamond" },
  { x: 110, y: 270, size: 12, color: "#FFD56B", shape: "star" },
  { x: 290, y: 260, size: 10, color: "#F4B6C2", shape: "star" },
  { x: 50,  y: 360, size: 9,  color: "#FFD56B", shape: "dot" },
  { x: 350, y: 370, size: 9,  color: "#F2A8A0", shape: "dot" },
  { x: 130, y: 470, size: 7,  color: "#FFAE6B", shape: "dot" },
  { x: 280, y: 470, size: 7,  color: "#9DC9E8", shape: "dot" },
];

function ConfettiShape({ shape, color, size }) {
  if (shape === "dot") return <circle cx={size / 2} cy={size / 2} r={size / 2.5} fill={color} />;
  if (shape === "diamond")
    return <path d={`M${size / 2} 0 L${size} ${size / 2} L${size / 2} ${size} L0 ${size / 2} Z`} fill={color} />;
  const c = size / 2;
  const t = size * 0.18;
  return (
    <path
      d={`M${c} 0 C${c} ${c - t} ${c + t} ${c} ${size} ${c} C${c + t} ${c} ${c} ${c + t} ${c} ${size} C${c} ${c + t} ${c - t} ${c} 0 ${c} C${c - t} ${c} ${c} ${c - t} ${c} 0 Z`}
      fill={color}
    />
  );
}

// 레벨 배지 양옆에서 가로로 뻗는 빛줄기
const RAY_ANGLES = [
  // 오른쪽
  -22, -8, 8, 22,
  // 왼쪽
  158, 172, -172, -158,
];

export default function LevelUp({ level = 2, onContinue }) {
  const lv = Math.min(5, Math.max(1, level));
  const theme = LEVEL_THEMES[lv];
  const tomatoImg = LEVEL_IMAGES[lv];
  const shadow = LEVEL_SHADOWS[lv];

  return (
    <div
      className="relative w-[402px] h-[874px] overflow-hidden mx-auto"
      style={{ background: "#FFF3E7" }}
    >
      {/* 카드 배경 */}
      <div
        className="absolute"
        style={{
          left: 17,
          top: 54,
          width: 363,
          height: 671,
          borderRadius: 30,
          background: "rgba(255, 255, 255, 0.5)",
          border: `1px solid ${theme.main}55`,
        }}
      />

      {/* 잎사귀 데코 (좌우) */}
      <img
        src={leaf}
        alt=""
        draggable="false"
        className="absolute select-none pointer-events-none"
        style={{ left: 78, top: 118, width: 26, height: 20, transform: "rotate(-30deg)" }}
      />
      <img
        src={leaf}
        alt=""
        draggable="false"
        className="absolute select-none pointer-events-none"
        style={{ left: 298, top: 118, width: 26, height: 20, transform: "scaleX(-1) rotate(-30deg)" }}
      />

      {/* 레벨업! */}
      <div
        className="absolute font-jeju"
        style={{
          left: 0,
          right: 0,
          top: 110,
          color: theme.main,
          fontSize: 44,
          fontWeight: 400,
          textAlign: "center",
          letterSpacing: "-0.43px",
          lineHeight: "50px",
        }}
      >
        레벨업!
      </div>

      {/* 부제 */}
      <div
        className="absolute font-sejong"
        style={{
          left: 0,
          right: 0,
          top: 172,
          color: "#000",
          fontSize: 15,
          fontWeight: 400,
          textAlign: "center",
          letterSpacing: "-0.43px",
        }}
      >
        축하해요! 새로운 레벨이 되었어요
      </div>

      {/* 컨페티 */}
      {CONFETTI.map((c, i) => (
        <svg
          key={i}
          className="sparkle absolute pointer-events-none"
          style={{ left: c.x, top: c.y - 100, width: c.size, height: c.size, animationDelay: `${(i % 5) * 0.2}s` }}
          viewBox={`0 0 ${c.size} ${c.size}`}
          aria-hidden="true"
        >
          <ConfettiShape shape={c.shape} color={c.color} size={c.size} />
        </svg>
      ))}

      {/* 토마토 캐릭터 */}
      <img
        src={tomatoImg}
        alt={`Lv.${lv} ${theme.name}`}
        draggable="false"
        className="absolute select-none pointer-events-none"
        style={{
          left: 71,
          top: 188,
          width: 270,
          height: 270,
          objectFit: "contain",
        }}
      />

      {/* 토마토 그림자 */}
      <div
        aria-hidden="true"
        className="absolute"
        style={{
          left: shadow.left,
          top: shadow.top,
          width: shadow.width,
          height: 13,
          background:
            "radial-gradient(ellipse at center, rgba(0,0,0,0.20) 0%, rgba(0,0,0,0.10) 40%, rgba(0,0,0,0) 75%)",
          filter: "blur(5px)",
          pointerEvents: "none",
        }}
      />

      {/* 레벨 배지 (LEVEL + 숫자 + 레벨명) + 빛줄기 */}
      <div
        className="absolute"
        style={{
          left: 0,
          right: 0,
          top: 478,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
        }}
      >
        {/* 빛줄기를 LEVEL+숫자+레벨명 전체 뒤에 깔기 위해 relative 래퍼 */}
        <div className="relative" style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <svg
            aria-hidden="true"
            width="320"
            height="200"
            viewBox="-160 -100 320 200"
            style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%, -50%)", overflow: "visible", pointerEvents: "none", zIndex: 0 }}
          >
            {RAY_ANGLES.map((a, i) => {
              const rad = (a * Math.PI) / 180;
              const r1 = 92;
              const r2 = (i % 2 === 0) ? 118 : 110;
              return (
                <line
                  key={i}
                  x1={Math.cos(rad) * r1}
                  y1={Math.sin(rad) * r1}
                  x2={Math.cos(rad) * r2}
                  y2={Math.sin(rad) * r2}
                  stroke={theme.soft}
                  strokeWidth="6"
                  strokeLinecap="round"
                />
              );
            })}
          </svg>

          <div
            className="font-noto"
            style={{
              position: "relative",
              zIndex: 1,
              background: theme.main,
              color: "#FFFFFF",
              fontSize: 14,
              fontWeight: 700,
              letterSpacing: "1.8px",
              paddingInline: 18,
              height: 28,
              borderRadius: 999,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            LEVEL
          </div>

          {/* 숫자 */}
          <div
            className="font-jeju"
            style={{
              position: "relative",
              zIndex: 1,
              color: theme.main,
              fontSize: 60,
              fontWeight: 400,
              lineHeight: "66px",
              letterSpacing: "-0.43px",
              marginTop: 4,
            }}
          >
            {lv}
          </div>

          {/* 레벨 명 */}
          <div
            className="font-sejong"
            style={{
              position: "relative",
              zIndex: 1,
              color: theme.main,
              fontSize: 16,
              fontWeight: 700,
              letterSpacing: "-0.43px",
              marginTop: 2,
            }}
          >
            {theme.name}
          </div>
        </div>
      </div>

      {/* 보상 카드 (하트 +1) */}
      <div
        className="absolute flex items-center justify-center"
        style={{
          left: 81,
          top: 638,
          width: 240,
          height: 60,
          borderRadius: 20,
          background: `${theme.main}22`,
          border: `1px solid ${theme.main}55`,
          gap: 10,
        }}
      >
        <img
          src={heart}
          alt=""
          draggable="false"
          className="select-none pointer-events-none"
          style={{ width: 28, height: 28, objectFit: "contain" }}
        />
        <span
          className="font-sejong"
          style={{
            color: theme.main,
            fontSize: 24,
            fontWeight: 400,
            letterSpacing: "-0.43px",
            lineHeight: "28px",
          }}
        >
          +1
        </span>
      </div>

      {/* 홈으로 가기 버튼 */}
      <button
        type="button"
        onClick={onContinue}
        className="signup-submit absolute font-sejong text-white shadow-md transition-all duration-200 flex items-center justify-center"
        style={{
          left: 56,
          top: 747,
          width: 290,
          height: 45,
          borderRadius: 50,
          background: theme.main,
          fontSize: 20,
          fontWeight: 400,
          letterSpacing: "-0.43px",
          lineHeight: "22px",
          padding: 0,
          border: "none",
        }}
      >
        홈으로 가기
      </button>
    </div>
  );
}
