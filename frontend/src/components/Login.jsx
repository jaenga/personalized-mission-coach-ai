import tomatoMain from "../assets/tomato/login/main.png";
import tomatoLeaf from "../assets/tomato/_shared/leaf.png";

export default function Login({ onStart }) {
  return (
    <div className="mobile-frame" style={{ background: "#FFF3E7" }}>
        <img
          src={tomatoLeaf}
          alt=""
          aria-hidden="true"
          className="absolute"
          style={{ left: 176, top: 114, width: 49, height: 26 }}
        />

        <h1
          className="absolute font-jeju text-tomato text-center"
          style={{
            left: 83,
            top: 136,
            width: 236,
            height: 57,
            fontSize: 50,
            fontWeight: 400,
            letterSpacing: "-0.43px",
            lineHeight: "57px",
          }}
        >
          토마토미
        </h1>

        <p
          className="absolute font-sejong text-gray-700 text-center"
          style={{
            left: 98,
            top: 193,
            width: 206,
            height: 15,
            fontSize: 15,
            fontWeight: 400,
            letterSpacing: "-0.43px",
            lineHeight: "15px",
          }}
        >
          함께하는 건강 어플
        </p>

        <svg
          aria-hidden="true"
          className="absolute pointer-events-none"
          style={{
            left: 33,
            top: 358,
            width: 35,
            height: 25,
            transform: "rotate(-45deg)",
            transformOrigin: "center",
          }}
          viewBox="0 0 35 25"
          fill="none"
          stroke="#1f1f1f"
          strokeWidth="2.2"
          strokeLinecap="round"
        >
          <line x1="3"  y1="6"  x2="9"  y2="14" />
          <line x1="17" y1="3"  x2="18" y2="14" />
          <line x1="33" y1="6"  x2="27" y2="14" />
        </svg>

        <div
          className="absolute select-none pointer-events-none tomato-float"
          style={{ left: 53, top: 256, width: 296, height: 268 }}
        >
          <img
            src={tomatoMain}
            alt="토마토 캐릭터"
            draggable="false"
            className="w-full h-full"
            style={{ objectFit: "contain" }}
          />
        </div>

        <div
          aria-hidden="true"
          className="absolute"
          style={{
            left: 102,
            top: 506,
            width: 205,
            height: 32,
            background:
              "radial-gradient(ellipse at center, rgba(0,0,0,0.18) 0%, rgba(0,0,0,0.09) 40%, rgba(0,0,0,0) 75%)",
            filter: "blur(5px)",
            pointerEvents: "none",
          }}
        />

        <button
          type="button"
          onClick={onStart}
          className="absolute bg-tomato text-white font-sejong shadow-md active:scale-[0.98] hover:bg-tomato-dark transition flex items-center justify-center"
          style={{
            left: 56,
            top: 593,
            width: 290,
            height: 59,
            borderRadius: 50,
            fontSize: 25,
            fontWeight: 400,
            letterSpacing: "-0.43px",
            lineHeight: "22px",
          }}
        >
          시작하기!
        </button>
    </div>
  );
}
