import { useEffect, useState } from "react";
import tomatoHi from "../assets/tomato/_shared/hi.png";

function useFrameScale(width, height) {
  const [scale, setScale] = useState(1);

  useEffect(() => {
    function updateScale() {
      const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
      const nextScale = Math.min(1, (viewportHeight - 24) / height, window.innerWidth / width);
      setScale(Number.isFinite(nextScale) ? Math.max(0.1, nextScale) : 1);
    }

    updateScale();
    window.addEventListener("resize", updateScale);
    window.visualViewport?.addEventListener("resize", updateScale);

    return () => {
      window.removeEventListener("resize", updateScale);
      window.visualViewport?.removeEventListener("resize", updateScale);
    };
  }, [width, height]);

  return scale;
}

export default function Signup({
  onSubmit,
  loading,
  error,
  pendingSignup,
  farewell,
  onConfirmSignup,
  onCancelSignup,
  onBack,
}) {
  const [name, setName] = useState("");
  const [phone4, setPhone4] = useState("");

  const canSubmit = name.trim().length > 0 && phone4.length === 4 && !loading;
  const frameScale = useFrameScale(402, 700);

  function handleSubmit(e) {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit?.({ name: name.trim(), phone4 });
  }

  return (
    <div className="mobile-frame flex justify-center" style={{ background: "#FFF3E7" }}>
      <div
        className="relative"
        style={{
          width: 402,
          height: 700,
          flexShrink: 0,
          transform: `scale(${frameScale})`,
          transformOrigin: "top center",
        }}
      >
      <button
        type="button"
        onClick={onBack}
        aria-label="처음 화면으로 돌아가기"
        className="absolute flex items-center justify-center"
        style={{
          left: 8,
          top: 18,
          border: "none",
          background: "transparent",
          color: "rgba(180, 80, 60, 0.5)",
          fontSize: 48,
          cursor: "pointer",
          lineHeight: 1,
          userSelect: "none",
          padding: 0,
        }}
      >
        ‹
      </button>

      <div
        className="absolute bg-white flex items-center justify-center px-4"
        style={{
          left: 109.5,
          top: 209,
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
        style={{ left: 193, top: 249, width: 16, height: 14 }}
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
          top: 313,
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
        style={{ left: 144, top: 280, width: 114, height: 107, objectFit: "contain" }}
      />

      <div
        aria-hidden="true"
        className="absolute rounded-full bg-black/15 blur-[4px]"
        style={{ left: 164, top: 381, width: 74, height: 12 }}
      />

      <p
        className="absolute font-sejong text-center text-gray-700"
        style={{
          left: 56,
          top: 420,
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
            top: 452,
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
            top: 506,
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
            top: 560,
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

      {pendingSignup && (
        <div
          className="absolute inset-0 flex items-center justify-center"
          style={{ background: "rgba(0,0,0,0.18)", zIndex: 20, padding: 28 }}
        >
          <div
            className="font-sejong text-center"
            style={{
              width: "100%",
              borderRadius: 24,
              background: "#FFFFFF",
              border: "1.5px solid #F2C5BA",
              padding: "26px 22px 22px",
              boxShadow: "0 10px 30px rgba(0,0,0,0.12)",
            }}
          >
            <p
              style={{
                fontSize: 17,
                fontWeight: 700,
                color: "#000",
                letterSpacing: "-0.43px",
                lineHeight: "24px",
              }}
            >
              처음 만나는 친구네요!
            </p>
            <p
              className="mt-2"
              style={{
                fontSize: 13,
                color: "#75726e",
                letterSpacing: "-0.43px",
                lineHeight: "20px",
              }}
            >
              {pendingSignup.name}님 정보를 새로 등록할까요?
            </p>
            <div className="mt-5 flex gap-2">
              <button
                type="button"
                onClick={onCancelSignup}
                disabled={loading}
                className="font-sejong flex-1"
                style={{
                  height: 44,
                  borderRadius: 50,
                  background: "#F5E4DD",
                  color: "#A05F50",
                  fontSize: 15,
                  fontWeight: 700,
                  padding: 0,
                }}
              >
                안할래요
              </button>
              <button
                type="button"
                onClick={onConfirmSignup}
                disabled={loading}
                className="font-sejong flex-1"
                style={{
                  height: 44,
                  borderRadius: 50,
                  background: "#E35D49",
                  color: "#FFFFFF",
                  fontSize: 15,
                  fontWeight: 700,
                  padding: 0,
                }}
              >
                {loading ? "등록 중..." : "좋아요"}
              </button>
            </div>
          </div>
        </div>
      )}

      {farewell && (
        <div
          className="absolute inset-0 flex items-center justify-center font-sejong"
          style={{ background: "rgba(255,243,231,0.92)", zIndex: 21, fontSize: 22, color: "#E35D49" }}
        >
          다음에 만나요!
        </div>
      )}

      {error && !pendingSignup && (
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
    </div>
  );
}
