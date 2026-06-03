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

const CONFETTI = [
  { x: "18%", y: "22%", size: 8, color: "#F2A8A0", shape: "diamond" },
  { x: "80%", y: "18%", size: 9, color: "#F4B6C2", shape: "diamond" },
  { x: "16%", y: "70%", size: 7, color: "#A7DAA7", shape: "diamond" },
  { x: "82%", y: "72%", size: 8, color: "#A7DAA7", shape: "diamond" },
  { x: "28%", y: "7%", size: 12, color: "#FFD56B", shape: "star" },
  { x: "72%", y: "5%", size: 10, color: "#F4B6C2", shape: "star" },
  { x: "12%", y: "42%", size: 9, color: "#FFD56B", shape: "dot" },
  { x: "88%", y: "45%", size: 9, color: "#F2A8A0", shape: "dot" },
  { x: "33%", y: "88%", size: 7, color: "#FFAE6B", shape: "dot" },
  { x: "70%", y: "88%", size: 7, color: "#9DC9E8", shape: "dot" },
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

  return (
    <div
      className="mobile-frame flex items-center justify-center"
      style={{
        background: "#FFF3E7",
        padding: "clamp(14px, 4dvh, 42px) 17px calc(16px + env(safe-area-inset-bottom))",
      }}
    >
      <div
        className="relative flex flex-col items-center"
        style={{
          width: "100%",
          maxWidth: 363,
          height: "100%",
          maxHeight: 790,
          minHeight: 0,
          borderRadius: 30,
          background: "rgba(255, 255, 255, 0.5)",
          border: `1px solid ${theme.main}55`,
          padding: "clamp(28px, 5dvh, 48px) 20px clamp(14px, 2.6dvh, 22px)",
          overflow: "hidden",
        }}
      >
      {/* 잎사귀 데코 (좌우) */}
      <img
        src={leaf}
        alt=""
        draggable="false"
        className="absolute select-none pointer-events-none"
        style={{ left: "17%", top: "clamp(30px, 6dvh, 56px)", width: 26, height: 20, transform: "rotate(-30deg)" }}
      />
      <img
        src={leaf}
        alt=""
        draggable="false"
        className="absolute select-none pointer-events-none"
        style={{ right: "17%", top: "clamp(30px, 6dvh, 56px)", width: 26, height: 20, transform: "scaleX(-1) rotate(-30deg)" }}
      />

      {/* 레벨업! */}
      <div
        className="font-jeju"
        style={{
          color: theme.main,
          fontSize: "clamp(34px, 5.1dvh, 44px)",
          fontWeight: 400,
          textAlign: "center",
          letterSpacing: "-0.43px",
          lineHeight: 1.12,
          flexShrink: 0,
        }}
      >
        레벨업!
      </div>

      {/* 부제 */}
      <div
        className="font-sejong"
        style={{
          color: "#000",
          fontSize: "clamp(13px, 1.8dvh, 15px)",
          fontWeight: 400,
          textAlign: "center",
          letterSpacing: "-0.43px",
          marginTop: "clamp(8px, 1.4dvh, 12px)",
          flexShrink: 0,
        }}
      >
        축하해요! 새로운 레벨이 되었어요
      </div>

      <div
        className="relative flex items-center justify-center"
        style={{
          width: "100%",
          minHeight: 0,
          flex: "1 1 230px",
          marginTop: "clamp(8px, 1.8dvh, 16px)",
        }}
      >
        {/* 컨페티 */}
        {CONFETTI.map((c, i) => (
          <svg
            key={i}
            className="sparkle absolute pointer-events-none"
            style={{ left: c.x, top: c.y, width: c.size, height: c.size, animationDelay: `${(i % 5) * 0.2}s` }}
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
          className="select-none pointer-events-none"
          style={{
            width: "clamp(158px, 28dvh, 230px)",
            height: "clamp(158px, 28dvh, 230px)",
            objectFit: "contain",
            zIndex: 1,
          }}
        />

        {/* 토마토 그림자 */}
        <div
          aria-hidden="true"
          className="absolute left-1/2 -translate-x-1/2"
          style={{
            bottom: "clamp(6px, 1.2dvh, 14px)",
            width: "clamp(112px, 20dvh, 160px)",
            height: 13,
            background:
              "radial-gradient(ellipse at center, rgba(0,0,0,0.20) 0%, rgba(0,0,0,0.10) 40%, rgba(0,0,0,0) 75%)",
            filter: "blur(5px)",
            pointerEvents: "none",
          }}
        />
      </div>

      {/* 레벨 배지 (LEVEL + 숫자 + 레벨명) + 빛줄기 */}
      <div
        className="relative"
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          flexShrink: 0,
          marginTop: "clamp(4px, 0.8dvh, 8px)",
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
              fontSize: "clamp(12px, 1.6dvh, 14px)",
              fontWeight: 700,
              letterSpacing: "1.8px",
              paddingInline: 18,
              height: "clamp(24px, 3.2dvh, 28px)",
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
              fontSize: "clamp(46px, 7dvh, 60px)",
              fontWeight: 400,
              lineHeight: 1.1,
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
              fontSize: "clamp(14px, 1.9dvh, 16px)",
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
        className="flex items-center justify-center"
        style={{
          width: "min(100%, 240px)",
          height: "clamp(48px, 6.6dvh, 60px)",
          borderRadius: 20,
          background: `${theme.main}22`,
          border: `1px solid ${theme.main}55`,
          gap: 10,
          flexShrink: 0,
          marginTop: "clamp(14px, 2.6dvh, 28px)",
        }}
      >
        <img
          src={heart}
          alt=""
          draggable="false"
          className="select-none pointer-events-none"
          style={{ width: "clamp(24px, 3.2dvh, 28px)", height: "clamp(24px, 3.2dvh, 28px)", objectFit: "contain" }}
        />
        <span
          className="font-sejong"
          style={{
            color: theme.main,
            fontSize: "clamp(20px, 2.8dvh, 24px)",
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
        className="signup-submit font-sejong text-white shadow-md transition-all duration-200 flex items-center justify-center"
        style={{
          width: "min(100%, 290px)",
          height: "clamp(42px, 5.2dvh, 45px)",
          borderRadius: 50,
          background: theme.main,
          fontSize: "clamp(17px, 2.3dvh, 20px)",
          fontWeight: 400,
          letterSpacing: "-0.43px",
          lineHeight: "22px",
          padding: 0,
          border: "none",
          flexShrink: 0,
          marginTop: "clamp(14px, 2.5dvh, 28px)",
        }}
      >
        홈으로 가기
      </button>
      </div>
    </div>
  );
}
