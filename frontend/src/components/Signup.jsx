import { useState } from "react";
import tomatoHi from "../assets/tomato/_shared/hi.png";

export default function Signup({ onSubmit, loading, error }) {
  const [name, setName] = useState("");
  const [phone4, setPhone4] = useState("");

  const canSubmit = name.trim().length > 0 && phone4.length === 4 && !loading;

  function handleSubmit(e) {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit?.({ name: name.trim(), phone4 });
  }

  return (
    <div className="relative w-[402px] h-[874px] overflow-hidden bg-cream mx-auto">
      <div
        className="absolute bg-white flex items-center justify-center px-4"
        style={{
          left: 109.5,
          top: 229,
          width: 183,
          height: 42,
          borderRadius: 14,
          border: "1.5px solid #F2C5BA",
        }}
      >
        <span
          className="font-sejong text-gray-800"
          style={{
            fontSize: 15,
            fontWeight: 400,
            letterSpacing: "-0.43px",
            lineHeight: "22px",
          }}
        >
          만나서 반가워~ 난 토미야!
        </span>
      </div>

      <svg
        aria-hidden="true"
        className="absolute"
        style={{ left: 193, top: 269, width: 16, height: 14 }}
        viewBox="0 0 16 14"
        fill="none"
      >
        <path
          d="M0 0 L8 13 L16 0"
          fill="#FFFFFF"
          stroke="#F2C5BA"
          strokeWidth="1.5"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </svg>

      <svg
        aria-hidden="true"
        className="absolute pointer-events-none"
        style={{
          left: 253,
          top: 333,
          width: 21,
          height: 25,
          transform: "rotate(45deg)",
          transformOrigin: "center",
        }}
        viewBox="0 0 21 25"
        fill="none"
        stroke="#1f1f1f"
        strokeWidth="2"
        strokeLinecap="round"
      >
        <line x1="2"  y1="6"  x2="6"  y2="13" />
        <line x1="10" y1="3"  x2="11" y2="13" />
        <line x1="19" y1="6"  x2="15" y2="13" />
      </svg>

      <img
        src={tomatoHi}
        alt="토미 캐릭터"
        draggable="false"
        className="absolute select-none pointer-events-none"
        style={{ left: 144, top: 300, width: 114, height: 107, objectFit: "contain" }}
      />

      <div
        aria-hidden="true"
        className="absolute rounded-full bg-black/15 blur-[4px]"
        style={{ left: 164, top: 401, width: 74, height: 12 }}
      />

      <p
        className="absolute font-sejong text-center text-gray-700"
        style={{
          left: 56,
          top: 440,
          width: 290,
          fontSize: 13,
          fontWeight: 400,
          letterSpacing: "-0.43px",
          lineHeight: "18px",
        }}
      >
        다음 정보를 입력해주세요
      </p>

      <form onSubmit={handleSubmit}>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="이름"
          className="signup-input absolute outline-none font-sejong"
          style={{
            left: 56,
            top: 472,
            width: 290,
            height: 45,
            borderRadius: 50,
            fontSize: 15,
            fontWeight: 400,
            letterSpacing: "-0.43px",
            lineHeight: "22px",
            paddingLeft: 24,
            paddingRight: 24,
            textAlign: "left",
            background: "#EDB6A8",
            color: "#FFFFFF",
            border: "none",
            transition: "box-shadow 0.18s ease, background 0.18s ease",
          }}
        />

        <input
          type="text"
          inputMode="numeric"
          maxLength={4}
          value={phone4}
          onChange={(e) => setPhone4(e.target.value.replace(/\D/g, ""))}
          placeholder="전화번호 뒷 4자리"
          className="signup-input absolute outline-none font-sejong"
          style={{
            left: 56,
            top: 526,
            width: 290,
            height: 45,
            borderRadius: 50,
            fontSize: 15,
            fontWeight: 400,
            letterSpacing: "-0.43px",
            lineHeight: "22px",
            paddingLeft: 24,
            paddingRight: 24,
            textAlign: "left",
            background: "#EDB6A8",
            color: "#FFFFFF",
            border: "none",
            transition: "box-shadow 0.18s ease, background 0.18s ease",
          }}
        />

        <button
          type="submit"
          disabled={!canSubmit}
          className={`signup-submit absolute text-white font-sejong shadow-md flex items-center justify-center gap-2 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed ${loading ? "is-loading" : ""}`}
          style={{
            left: 56,
            top: 580,
            width: 290,
            height: 45,
            borderRadius: 50,
            fontSize: 20,
            fontWeight: 400,
            letterSpacing: "-0.43px",
            lineHeight: "22px",
            background: "#E35D49",
          }}
        >
          {loading && (
            <span
              aria-hidden="true"
              className="inline-block w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin"
            />
          )}
          {loading ? "확인 중..." : "계속하기"}
        </button>
      </form>

      {error && (
        <p
          className="absolute text-center text-red-500 font-sejong"
          style={{
            left: 56,
            top: 638,
            width: 290,
            fontSize: 13,
            letterSpacing: "-0.43px",
          }}
        >
          {error}
        </p>
      )}
    </div>
  );
}
