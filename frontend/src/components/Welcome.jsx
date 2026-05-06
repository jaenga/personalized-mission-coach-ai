import tomatoHi from "../assets/tomato/_shared/hi.png";
import heart from "../assets/tomato/_shared/heart.png";
import leaf from "../assets/tomato/_shared/leaf.png";

const SPARKLE_COLORS = ["#F2A8A0", "#FFD56B", "#9DC9E8", "#F4B6C2", "#A7DAA7", "#FFAE6B", "#E35D49"];

const SPARKLES = [
  { x: 60,  y: 140, size: 10, color: 0, delay: 0,    shape: "star" },
  { x: 170, y: 100, size: 14, color: 1, delay: 0.2,  shape: "star" },
  { x: 280, y: 130, size: 12, color: 2, delay: 0.4,  shape: "star" },
  { x: 330, y: 200, size: 9,  color: 3, delay: 0.1,  shape: "dot" },
  { x: 50,  y: 230, size: 8,  color: 4, delay: 0.7,  shape: "diamond" },
  { x: 110, y: 280, size: 11, color: 5, delay: 0.5,  shape: "star" },
  { x: 320, y: 290, size: 10, color: 0, delay: 0.9,  shape: "diamond" },
  { x: 90,  y: 380, size: 8,  color: 6, delay: 0.3,  shape: "dot" },
  { x: 350, y: 380, size: 12, color: 1, delay: 1.1,  shape: "star" },
  { x: 60,  y: 460, size: 10, color: 2, delay: 0.6,  shape: "diamond" },
  { x: 340, y: 480, size: 11, color: 3, delay: 0.4,  shape: "star" },
  { x: 200, y: 500, size: 7,  color: 4, delay: 1.0,  shape: "dot" },
  { x: 250, y: 175, size: 8,  color: 5, delay: 1.3,  shape: "dot" },
  { x: 130, y: 200, size: 6,  color: 6, delay: 1.5,  shape: "dot" },
];

function SparkleShape({ shape, color, size }) {
  if (shape === "dot") {
    return <circle cx={size / 2} cy={size / 2} r={size / 2.5} fill={color} />;
  }
  if (shape === "diamond") {
    return <path d={`M${size / 2} 0 L${size} ${size / 2} L${size / 2} ${size} L0 ${size / 2} Z`} fill={color} />;
  }
  const c = size / 2;
  const t = size * 0.18;
  return (
    <path
      d={`M${c} 0 C${c} ${c - t} ${c + t} ${c} ${size} ${c} C${c + t} ${c} ${c} ${c + t} ${c} ${size} C${c} ${c + t} ${c - t} ${c} 0 ${c} C${c - t} ${c} ${c} ${c - t} ${c} 0 Z`}
      fill={color}
    />
  );
}

export default function Welcome({ onContinue }) {
  return (
    <div
      className="relative w-[402px] h-[874px] overflow-hidden mx-auto"
      style={{ background: "#FFF3E7" }}
    >
      {/* 흰색 반투명 카드 */}
      <div
        className="absolute"
        style={{
          left: 17,
          top: 54,
          width: 363,
          height: 671,
          borderRadius: 30,
          background: "rgba(255, 255, 255, 0.5)",
          border: "1px solid rgba(227, 93, 73, 0.5)",
        }}
      />

      {/* 스파클 (애니메이션 유지) */}
      {SPARKLES.map((s, i) => (
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
          <SparkleShape shape={s.shape} color={SPARKLE_COLORS[s.color]} size={s.size} />
        </svg>
      ))}

      {/* 꼭지 (leaf) */}
      <img
        src={leaf}
        alt=""
        draggable="false"
        className="absolute select-none pointer-events-none"
        style={{ left: 251, top: 98, width: 31.2, height: 23.65, transform: "rotate(23deg)", transformOrigin: "center" }}
      />

      {/* 환영해요! */}
      <div
        className="absolute font-jeju"
        style={{
          left: 83,
          top: 110,
          width: 236,
          height: 57,
          color: "#E35D49",
          fontSize: 50,
          fontWeight: 400,
          textAlign: "center",
          letterSpacing: "-0.43px",
          lineHeight: "57px",
        }}
      >
        환영해요!
      </div>

      {/* 가입이 완료되었습니다 */}
      <div
        className="absolute font-sejong"
        style={{
          left: 119,
          top: 172,
          width: 163,
          height: 22,
          color: "#000000",
          fontSize: 20,
          fontWeight: 400,
          textAlign: "center",
          letterSpacing: "-0.43px",
          lineHeight: "22px",
        }}
      >
        가입이 완료되었습니다
      </div>

      {/* hi.png 히어로 (애니메이션 없음) */}
      <img
        src={tomatoHi}
        alt="환영하는 토미"
        draggable="false"
        className="absolute select-none pointer-events-none"
        style={{
          left: 83,
          top: 270,
          width: 231,
          height: 231,
          objectFit: "contain",
        }}
      />

      {/* 그림자 (부드러운 타원 그라데이션) */}
      <div
        aria-hidden="true"
        className="absolute"
        style={{
          left: 122,
          top: 482,
          width: 150,
          height: 22,
          background:
            "radial-gradient(ellipse at center, rgba(0,0,0,0.22) 0%, rgba(0,0,0,0.12) 40%, rgba(0,0,0,0) 75%)",
          filter: "blur(4px)",
          pointerEvents: "none",
        }}
      />

      {/* 가입 기념 선물 */}
      <div
        className="absolute font-noto"
        style={{
          left: 106,
          top: 533,
          width: 190,
          height: 22,
          color: "#000000",
          fontSize: 15,
          fontWeight: 500,
          textAlign: "center",
          letterSpacing: "-0.43px",
          lineHeight: "22px",
          whiteSpace: "nowrap",
        }}
      >
        가입 기념 선물
      </div>

      {/* 선물 카드 */}
      <div
        className="absolute"
        style={{
          left: 57,
          top: 565,
          width: 288,
          height: 133,
          borderRadius: 30,
          background: "rgba(227, 93, 73, 0.2)",
          border: "1px solid rgba(227, 93, 73, 0.5)",
        }}
      />

      {/* 하트 */}
      <img
        src={heart}
        alt=""
        draggable="false"
        className="absolute select-none pointer-events-none"
        style={{ left: 181, top: 596, width: 36, height: 36, objectFit: "contain" }}
      />

      {/* +1 */}
      <div
        className="absolute font-sejong"
        style={{
          left: 184,
          top: 643,
          width: 29,
          height: 22,
          color: "#E35D49",
          fontSize: 30,
          fontWeight: 400,
          textAlign: "center",
          letterSpacing: "-0.43px",
          lineHeight: "22px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        +1
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
          background: "#E35D49",
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
