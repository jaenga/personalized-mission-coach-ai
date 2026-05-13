import { useMemo, useState } from "react";
import tomatoHi from "../assets/tomato/_shared/hi.png";

const APP_NAME = "토마토미";

const TWO_SYLLABLE_SURNAMES = new Set([
  "남궁", "황보", "제갈", "사공", "선우", "독고", "동방", "서문", "어금",
]);

function formatKoreanDate(value) {
  if (!value) return "";
  const [, month, day] = String(value).split("-");
  return `${Number(month)}월 ${Number(day)}일`;
}

function hasJongseong(name) {
  if (!name) return false;
  const last = name[name.length - 1];
  const code = last.charCodeAt(0) - 0xac00;
  return code >= 0 && code <= 11171 && code % 28 !== 0;
}

function dropSurname(fullName) {
  if (!fullName) return "";
  if (fullName.length <= 1) return fullName;
  if (TWO_SYLLABLE_SURNAMES.has(fullName.slice(0, 2))) {
    return fullName.slice(2) || fullName;
  }
  return fullName.slice(1);
}

function withSubjectParticle(name) {
  if (!name) return "";
  return hasJongseong(name) ? `${name}이가` : `${name}가`;
}

function withPossessiveParticle(name) {
  if (!name) return "";
  return hasJongseong(name) ? `${name}이의` : `${name}의`;
}

function withTopicParticle(name) {
  if (!name) return "";
  return hasJongseong(name) ? `${name}이는` : `${name}는`;
}

function buildShareBody({ studentName, successCount, failCount }) {
  const subject = withSubjectParticle(studentName);
  const total = successCount + failCount;

  if (failCount === 0) {
    if (successCount === 1) {
      return `${subject} 지난주에 미션 1번 도전해서 성공했어요! 🍅 오늘 만나면 잘했다고 한 번 칭찬해주세요!`;
    }
    return `${subject} 지난주에 도전한 미션 ${successCount}번을 모두 성공했어요! 🍅 오늘 만나면 크게 한 번 칭찬해주세요! 🎉`;
  }
  if (successCount === 0) {
    return `${subject} 지난주에 미션 ${total}번 도전했는데 아직 성공은 못 했어요. 그래도 시도해봤다는 점은 칭찬해주고 싶습니다! 오늘 만나면 따뜻한 응원 한마디 부탁드려요! 🍅`;
  }
  if (successCount >= failCount) {
    return `${subject} 지난주에 미션 ${total}번 도전해서 ${successCount}번 성공했어요! 꾸준히 해내고 있으니까, 오늘 만나면 칭찬과 응원 한마디 부탁드려요 🍅`;
  }
  return `${subject} 지난주에 미션 ${total}번 도전해서 ${successCount}번 성공했어요. 아직 적응 중이지만 계속 시도하고 있어요. 오늘 만나면 따뜻한 응원 부탁드려요! 🍅`;
}

function formatMissionList(missions, max = 3) {
  if (!missions.length) return "";
  const shown = missions.slice(0, max);
  const truncated = missions.length > shown.length;
  return truncated ? `${shown.join(", ")} 등` : shown.join(", ");
}

function buildShareText({ studentName, weekStart, weekEnd, summary }) {
  const firstName = dropSurname(studentName);
  const successCount = summary?.success_count ?? 0;
  const failCount = summary?.fail_count ?? 0;
  const successMissions = (summary?.missions || [])
    .filter((mission) => ["success", "completed"].includes(mission.result))
    .map((mission) => mission.mission_name);
  const failMissions = (summary?.missions || [])
    .filter((mission) => ["fail", "failure"].includes(mission.result))
    .map((mission) => mission.mission_name);

  const lines = [
    `${withPossessiveParticle(firstName)} 지난주 ${APP_NAME} 기록 🍅`,
    `${formatKoreanDate(weekStart)} - ${formatKoreanDate(weekEnd)}`,
    "",
    buildShareBody({ studentName: firstName, successCount, failCount }),
  ];

  const successStr = formatMissionList(successMissions);
  if (successStr) {
    lines.push(`성공한 미션: ${successStr}`);
  }
  const failStr = formatMissionList(failMissions);
  if (failStr) {
    lines.push(`아쉬웠던 미션: ${failStr}`);
  }

  return lines.join("\n");
}

export default function WeeklyShareModal({ open, studentName, prompt, onDismiss, onShared }) {
  const [step, setStep] = useState("ask");
  const [sharing, setSharing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  const firstName = dropSurname(studentName);
  const shareTitle = `${withPossessiveParticle(firstName)} 지난주 ${APP_NAME} 기록 🍅`;
  const shareText = useMemo(
    () =>
      buildShareText({
        studentName,
        weekStart: prompt?.week_start,
        weekEnd: prompt?.week_end,
        summary: prompt?.summary,
      }),
    [studentName, prompt]
  );

  if (!open || !prompt) return null;

  const successCount = prompt.summary?.success_count ?? 0;
  const failCount = prompt.summary?.fail_count ?? 0;

  async function handleNativeShare() {
    setSharing(true);
    setCopied(false);
    setError("");
    try {
      if (navigator.share) {
        await navigator.share({
          title: shareTitle,
          text: shareText,
        });
      } else if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(shareText);
        setCopied(true);
      } else {
        throw new Error("공유를 지원하지 않는 브라우저예요.");
      }
      await onShared?.();
    } catch (err) {
      if (err?.name !== "AbortError") {
        setError(err.message || "공유에 실패했어요. 다시 시도해 주세요.");
      }
    } finally {
      setSharing(false);
    }
  }

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "center",
        zIndex: 2100,
      }}
    >
      <div
        className="font-sejong"
        style={{
          width: "100%",
          background: "#FFF8F4",
          borderRadius: "28px 28px 0 0",
          padding: "12px 24px 32px",
          boxSizing: "border-box",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          color: "#1a1a1a",
        }}
      >
        <div style={{ width: 40, height: 4, borderRadius: 2, background: "rgba(0,0,0,0.12)" }} />
        <img
          src={tomatoHi}
          alt=""
          draggable="false"
          style={{ width: 82, height: 82, objectFit: "contain", marginTop: 14 }}
        />

        {step === "ask" ? (
          <>
            <p style={{ marginTop: 6, marginBottom: 4, fontSize: 12, fontWeight: 700, color: "#E35D49" }}>
              {formatKoreanDate(prompt.week_start)} - {formatKoreanDate(prompt.week_end)}
            </p>
            <h2 style={{ margin: "0 0 12px", fontSize: 21, fontWeight: 800, textAlign: "center", lineHeight: "30px" }}>
              지난주 {APP_NAME} 미션 결과를
              <br />
              공유해볼까요? 🍅
            </h2>
            <p style={{ margin: "0 0 22px", fontSize: 14, lineHeight: "21px", color: "#5f5a55", textAlign: "center" }}>
              {withTopicParticle(firstName)} 지난주에
              <br />
              {successCount === 0
                ? `미션 ${failCount}번 도전했어요!`
                : failCount === 0
                ? successCount === 1
                  ? "미션 1번 도전해서 성공했어요!"
                  : `미션 ${successCount}번 모두 성공했어요!`
                : `미션 ${successCount + failCount}번 도전 · ${successCount}번 성공했어요!`}
            </p>
            <div style={{ display: "flex", gap: 10, width: "100%" }}>
              <button type="button" onClick={onDismiss} style={secondaryButtonStyle}>
                나중에
              </button>
              <button type="button" onClick={() => setStep("share")} style={primaryButtonStyle}>
                공유하기
              </button>
            </div>
          </>
        ) : (
          <>
            <p style={{ marginTop: 6, marginBottom: 4, fontSize: 12, fontWeight: 700, color: "#E35D49" }}>
              공유 미리보기
            </p>
            <h2 style={{ margin: "0 0 14px", fontSize: 21, fontWeight: 800, textAlign: "center", lineHeight: "29px" }}>
              공유해볼까요? 🍅
            </h2>
            <div
              style={{
                width: "100%",
                borderRadius: 18,
                border: "1.5px solid rgba(227, 93, 73, 0.2)",
                background: "#FFFFFF",
                padding: "14px 15px",
                boxSizing: "border-box",
                fontSize: 13,
                lineHeight: "20px",
                whiteSpace: "pre-line",
                color: "#3d3834",
              }}
            >
              {shareText}
            </div>
            {copied && (
              <p style={{ width: "100%", margin: "10px 0 0", fontSize: 12, color: "#E35D49" }}>
                공유 문구를 복사했어요.
              </p>
            )}
            {error && (
              <p style={{ width: "100%", margin: "10px 0 0", fontSize: 12, color: "#E35D49" }}>
                {error}
              </p>
            )}
            <div style={{ display: "flex", gap: 10, width: "100%", marginTop: 18 }}>
              <button type="button" onClick={onDismiss} disabled={sharing} style={secondaryButtonStyle}>
                닫기
              </button>
              <button type="button" onClick={handleNativeShare} disabled={sharing} style={primaryButtonStyle}>
                {sharing ? "여는 중..." : "공유창 열기"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const primaryButtonStyle = {
  flex: "1 1 0",
  height: 48,
  borderRadius: 999,
  border: "none",
  background: "#E35D49",
  color: "#FFFFFF",
  fontSize: 16,
  fontWeight: 700,
  cursor: "pointer",
  boxShadow: "0 4px 14px rgba(227,93,73,0.3)",
};

const secondaryButtonStyle = {
  flex: "1 1 0",
  height: 48,
  borderRadius: 999,
  border: "none",
  background: "#ECEAE7",
  color: "#5a5754",
  fontSize: 15,
  fontWeight: 700,
  cursor: "pointer",
};
