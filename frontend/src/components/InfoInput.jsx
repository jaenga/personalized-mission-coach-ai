import { useState } from "react";
import tomatoHi from "../assets/tomato/_shared/hi.png";

function formatBirth(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${y}. ${m}. ${d}`;
}

export default function InfoInput({ onSubmit, loading, error }) {
  const [birth, setBirth] = useState("");
  const [gender, setGender] = useState("");
  const [isPrivate, setIsPrivate] = useState(false);

  const canSubmit = !loading && (isPrivate || (birth.length > 0 && gender.length > 0));

  function handleSubmit(e) {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit?.({
      birth: isPrivate ? "" : birth,
      gender: isPrivate ? "" : gender,
      isPrivate,
    });
  }

  const today = new Date().toISOString().split("T")[0];

  return (
    <div className="relative w-[402px] h-[874px] overflow-hidden mx-auto" style={{ background: "#FFF3E7" }}>
      <div
        className="absolute bg-white flex items-center justify-center text-center px-4"
        style={{
          left: 68,
          top: 221,
          width: 265,
          height: 65.57,
          borderRadius: 14,
          border: "1.5px solid #F2C5BA",
          whiteSpace: "pre-line",
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
          <span style={{ color: "#E35D49", fontWeight: 700 }}>생년월일</span>
          {"과 "}
          <span style={{ color: "#E35D49", fontWeight: 700 }}>성별</span>
          {"을 알려주면\n토미가 더 잘 맞는 미션을 준비할 수 있어!"}
        </span>
      </div>

      <svg
        aria-hidden="true"
        className="absolute"
        style={{ left: 188, top: 285, width: 23, height: 16 }}
        viewBox="0 0 23 16"
        fill="none"
      >
        <path
          d="M0 0 L11.5 15 L23 0"
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
          top: 353,
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
        style={{ left: 144, top: 320, width: 114, height: 107, objectFit: "contain" }}
      />

      <div
        aria-hidden="true"
        className="absolute rounded-full bg-black/15 blur-[4px]"
        style={{ left: 164, top: 421, width: 74, height: 12 }}
      />

      <form onSubmit={handleSubmit}>
        <label
          className="absolute font-sejong flex items-center"
          style={{
            left: 56,
            top: 472,
            width: 290,
            height: 45,
            borderRadius: 50,
            paddingLeft: 24,
            paddingRight: 24,
            fontSize: 15,
            fontWeight: 400,
            letterSpacing: "-0.43px",
            background: "#EDB6A8",
            color: "#FFFFFF",
            cursor: isPrivate ? "not-allowed" : "pointer",
            opacity: isPrivate ? 0.5 : 1,
            transition: "opacity 0.18s ease",
          }}
        >
          <input
            type="date"
            value={birth}
            onChange={(e) => setBirth(e.target.value)}
            max={today}
            disabled={isPrivate}
            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed"
            style={{ borderRadius: 50 }}
          />
          <span style={{ color: birth ? "#FFFFFF" : "rgba(255,255,255,0.85)" }}>
            {birth ? formatBirth(birth) : "생년월일"}
          </span>
        </label>

        <div
          className="absolute flex gap-2"
          style={{
            left: 56,
            top: 526,
            width: 290,
            height: 45,
            opacity: isPrivate ? 0.5 : 1,
            transition: "opacity 0.18s ease",
          }}
        >
          {[
            { value: "female", label: "여자" },
            { value: "male", label: "남자" },
          ].map((opt) => {
            const selected = gender === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => !isPrivate && setGender(opt.value)}
                disabled={isPrivate}
                className="flex-1 font-sejong transition-all duration-150 active:scale-[0.98]"
                style={{
                  borderRadius: 50,
                  fontSize: 15,
                  fontWeight: selected ? 700 : 400,
                  letterSpacing: "-0.43px",
                  background: selected ? "#EDB6A8" : "transparent",
                  color: selected ? "#FFFFFF" : "#C77C6C",
                  border: `1.5px solid #EDB6A8`,
                  cursor: isPrivate ? "not-allowed" : "pointer",
                }}
              >
                {opt.label}
              </button>
            );
          })}
        </div>

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
          {loading ? "저장 중..." : "계속하기"}
        </button>

        <label
          className="absolute flex items-center gap-1.5 cursor-pointer select-none"
          style={{ left: 89, top: 638 }}
        >
          <input
            type="checkbox"
            checked={isPrivate}
            onChange={(e) => setIsPrivate(e.target.checked)}
            className="sr-only peer"
          />
          <span
            aria-hidden="true"
            className="inline-flex items-center justify-center bg-white border-[1.5px] border-gray-400 rounded-[5px] transition-colors peer-checked:bg-tomato peer-checked:border-tomato"
            style={{ width: 16, height: 16 }}
          >
            {isPrivate && (
              <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 8.5 L7 12 L13 4" />
              </svg>
            )}
          </span>
          <span
            className="font-sejong text-gray-700"
            style={{
              fontSize: 10,
              fontWeight: 400,
              letterSpacing: "-0.43px",
              lineHeight: "16px",
            }}
          >
            비공개로 할래요. 토미가 정보를 사용하지 않습니다
          </span>
        </label>
      </form>

      {error && (
        <p
          className="absolute text-center text-red-500 font-sejong"
          style={{
            left: 56,
            top: 660,
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
