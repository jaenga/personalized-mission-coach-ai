import tomatoHi from "../assets/tomato/_shared/hi.png";
import heart from "../assets/tomato/_shared/heart.png";
import leaf from "../assets/tomato/_shared/leaf.png";

const SPARKLE_COLORS = ["#F2A8A0", "#FFD56B", "#9DC9E8", "#F4B6C2", "#A7DAA7", "#FFAE6B", "#E35D49"];

const SPARKLES = [
  { x: "15%", y: "11%", size: 10, color: 0, delay: 0, shape: "star" },
  { x: "43%", y: "5%", size: 14, color: 1, delay: 0.2, shape: "star" },
  { x: "72%", y: "10%", size: 12, color: 2, delay: 0.4, shape: "star" },
  { x: "86%", y: "24%", size: 9, color: 3, delay: 0.1, shape: "dot" },
  { x: "12%", y: "30%", size: 8, color: 4, delay: 0.7, shape: "diamond" },
  { x: "28%", y: "39%", size: 11, color: 5, delay: 0.5, shape: "star" },
  { x: "82%", y: "40%", size: 10, color: 0, delay: 0.9, shape: "diamond" },
  { x: "23%", y: "58%", size: 8, color: 6, delay: 0.3, shape: "dot" },
  { x: "90%", y: "58%", size: 12, color: 1, delay: 1.1, shape: "star" },
  { x: "15%", y: "74%", size: 10, color: 2, delay: 0.6, shape: "diamond" },
  { x: "86%", y: "78%", size: 11, color: 3, delay: 0.4, shape: "star" },
  { x: "50%", y: "82%", size: 7, color: 4, delay: 1.0, shape: "dot" },
  { x: "63%", y: "20%", size: 8, color: 5, delay: 1.3, shape: "dot" },
  { x: "32%", y: "24%", size: 6, color: 6, delay: 1.5, shape: "dot" },
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
      className="mobile-frame flex items-center justify-center"
      style={{
        background: "#FFF3E7",
        padding: "clamp(14px, 4dvh, 42px) 17px calc(16px + env(safe-area-inset-bottom))",
      }}
    >
      <div
        className="relative flex h-full w-full flex-col items-center overflow-hidden"
        style={{
          maxWidth: 363,
          maxHeight: 790,
          borderRadius: 30,
          background: "rgba(255, 255, 255, 0.5)",
          border: "1px solid rgba(227, 93, 73, 0.5)",
          padding: "clamp(46px, 8dvh, 72px) 20px clamp(14px, 2.6dvh, 22px)",
        }}
      >
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

        <img
          src={leaf}
          alt=""
          draggable="false"
          className="absolute select-none pointer-events-none"
          style={{ right: "23%", top: "clamp(44px, 7dvh, 56px)", width: 31.2, height: 23.65, transform: "rotate(23deg)", transformOrigin: "center" }}
        />

        <h1
          className="font-jeju"
          style={{
            color: "#E35D49",
            fontSize: "clamp(38px, 5.8dvh, 50px)",
            fontWeight: 400,
            textAlign: "center",
            letterSpacing: "-0.43px",
            lineHeight: 1.14,
            flexShrink: 0,
          }}
        >
          환영해요!
        </h1>

        <p
          className="font-sejong"
          style={{
            color: "#000000",
            fontSize: "clamp(16px, 2.3dvh, 20px)",
            fontWeight: 400,
            textAlign: "center",
            letterSpacing: "-0.43px",
            lineHeight: 1.1,
            marginTop: "clamp(8px, 1.4dvh, 12px)",
            flexShrink: 0,
          }}
        >
          가입이 완료되었습니다
        </p>

        <div
          className="relative flex w-full flex-1 items-center justify-center"
          style={{ minHeight: 0, marginTop: "clamp(18px, 4dvh, 58px)" }}
        >
          <img
            src={tomatoHi}
            alt="환영하는 토미"
            draggable="false"
            className="select-none pointer-events-none"
            style={{
              width: "clamp(160px, 27dvh, 231px)",
              height: "clamp(160px, 27dvh, 231px)",
              objectFit: "contain",
              zIndex: 1,
            }}
          />

          <div
            aria-hidden="true"
            className="absolute left-1/2 -translate-x-1/2"
            style={{
              bottom: "clamp(8px, 1.4dvh, 16px)",
              width: "clamp(112px, 18dvh, 150px)",
              height: 22,
              background:
                "radial-gradient(ellipse at center, rgba(0,0,0,0.22) 0%, rgba(0,0,0,0.12) 40%, rgba(0,0,0,0) 75%)",
              filter: "blur(4px)",
              pointerEvents: "none",
            }}
          />
        </div>

        <p
          className="font-sejong"
          style={{
            color: "#4e4949",
            fontSize: "clamp(13px, 1.8dvh, 15px)",
            fontWeight: 500,
            textAlign: "center",
            letterSpacing: "-0.43px",
            lineHeight: "22px",
            whiteSpace: "nowrap",
            flexShrink: 0,
            marginTop: "clamp(8px, 1.5dvh, 16px)",
          }}
        >
          가입 기념 선물
        </p>

        <div
          className="flex flex-col items-center justify-center"
          style={{
            width: "min(100%, 288px)",
            height: "clamp(72px, 9.8dvh, 85px)",
            borderRadius: 24,
            background: "rgba(227, 93, 73, 0.2)",
            border: "1px solid rgba(227, 93, 73, 0.5)",
            flexShrink: 0,
            marginTop: "clamp(6px, 1dvh, 10px)",
          }}
        >
          <img
            src={heart}
            alt=""
            draggable="false"
            className="select-none pointer-events-none"
            style={{ width: "clamp(26px, 3.6dvh, 32px)", height: "clamp(26px, 3.6dvh, 32px)", objectFit: "contain" }}
          />
          <div
            className="font-sejong"
            style={{
              color: "#E35D49",
              fontSize: "clamp(24px, 3.4dvh, 30px)",
              fontWeight: 400,
              textAlign: "center",
              letterSpacing: "-0.43px",
              lineHeight: 1,
              marginTop: 4,
            }}
          >
            +1
          </div>
        </div>

        <button
          type="button"
          onClick={onContinue}
          className="signup-submit font-sejong text-white shadow-md transition-all duration-200 flex items-center justify-center"
          style={{
            width: "min(100%, 290px)",
            height: "clamp(42px, 5.2dvh, 45px)",
            borderRadius: 50,
            background: "#E35D49",
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
