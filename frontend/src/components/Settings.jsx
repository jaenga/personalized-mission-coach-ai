import { useState } from "react";
import { BottomNav } from "./Home.jsx";
import heartImg from "../assets/tomato/_shared/heart.png";
import noticeImg from "../assets/tomato/settings/notice.png";
import messageImg from "../assets/tomato/settings/message.png";
import fireImg from "../assets/tomato/settings/fire.png";
import healthNoteImg from "../assets/tomato/settings/health_note.png";
import missionPreferenceImg from "../assets/tomato/settings/misicon.svg";
import outImg from "../assets/tomato/settings/out.png";
import warningImg from "../assets/tomato/settings/warning.png";
import lv1Face from "../assets/tomato/_shared/Level/Lv1_face.svg";
import lv2Face from "../assets/tomato/_shared/Level/Lv2_face.svg";
import lv3Face from "../assets/tomato/_shared/Level/Lv3_face.svg";
import lv4Face from "../assets/tomato/_shared/Level/Lv4_face.svg";
import lv5Face from "../assets/tomato/_shared/Level/Lv5_face.svg";

const LEVEL_FACES = {
  1: lv1Face,
  2: lv2Face,
  3: lv3Face,
  4: lv4Face,
  5: lv5Face,
};

function levelFace(level) {
  return LEVEL_FACES[Math.min(5, Math.max(1, level))];
}

const LEVEL_TITLES = {
  1: "시작하는 토마",
  2: "배우는 토마",
  3: "성장하는 토마",
  4: "익어가는 토마",
  5: "반짝이는 토마",
};

function levelTitle(level) {
  return LEVEL_TITLES[Math.min(5, Math.max(1, level))];
}

/* ─────────────────────────────────────────────────────────
   Toggle 스위치
   ───────────────────────────────────────────────────────── */
function Toggle({ on, onChange }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!on)}
      role="switch"
      aria-checked={on}
      className="transition-colors"
      style={{
        width: 44,
        height: 26,
        borderRadius: 999,
        background: on ? "#92B774" : "#D9D5D0",
        border: "none",
        padding: 2,
        cursor: "pointer",
        position: "relative",
      }}
    >
      <span
        aria-hidden="true"
        style={{
          display: "block",
          width: 22,
          height: 22,
          borderRadius: "50%",
          background: "#FFFFFF",
          transform: on ? "translateX(18px)" : "translateX(0)",
          transition: "transform 0.18s ease",
          boxShadow: "0 1px 2px rgba(0,0,0,0.15)",
        }}
      />
    </button>
  );
}

function Row({ icon, label, right, onClick }) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      type={onClick ? "button" : undefined}
      onClick={onClick}
      className="w-full flex items-center justify-between font-sejong"
      style={{
        padding: "14px 4px",
        background: "transparent",
        border: "none",
        fontSize: 14,
        fontWeight: 400,
        color: "#000",
        letterSpacing: "-0.43px",
        cursor: onClick ? "pointer" : "default",
        textAlign: "left",
      }}
    >
      <span className="flex items-center gap-3">
        {icon}
        {label}
      </span>
      {right}
    </Tag>
  );
}

function SectionCard({ title, children }) {
  const items = Array.isArray(children) ? children.filter(Boolean) : [children].filter(Boolean);
  return (
    <>
      <h3
        className="font-sejong mt-6 mb-2"
        style={{
          fontSize: 16,
          fontWeight: 700,
          color: "#000",
          letterSpacing: "-0.43px",
          paddingInline: 4,
        }}
      >
        {title}
      </h3>
      <div
        style={{
          padding: "4px 14px",
          borderRadius: 20,
          background: "rgba(255, 255, 255, 0.6)",
          border: "1px solid rgba(227, 93, 73, 0.25)",
        }}
      >
        {items.map((child, i) => (
          <div
            key={i}
            style={{
              borderTop: i === 0 ? "none" : "1px solid rgba(227, 93, 73, 0.12)",
            }}
          >
            {child}
          </div>
        ))}
      </div>
    </>
  );
}

function IconBox({ src, bg, size = 30 }) {
  return (
    <span
      className="flex items-center justify-center"
      style={{ width: 36, height: 36, borderRadius: 10, background: bg, flexShrink: 0 }}
    >
      <img src={src} alt="" style={{ width: size, height: size, objectFit: "contain" }} />
    </span>
  );
}

function ChevronRight() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#A6A29D" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

/* ─────────────────────────────────────────────────────────
   Settings — 메인
   ───────────────────────────────────────────────────────── */
export default function Settings({
  studentName = "민준",
  age = 10,
  level = 3,
  streakDays = 7,
  heartCount = 4,
  onBack,
  onNavigate,
  onOpenHealthNote,
  onOpenMissionPreferences,
  onLogout,
  onWithdraw,
}) {
  const [missionNoti, setMissionNoti] = useState(false);
  const [coachNoti, setCoachNoti] = useState(false);
  const [streakNoti, setStreakNoti] = useState(false);
  const [withdrawConfirmOpen, setWithdrawConfirmOpen] = useState(false);

  return (
    <div
      className="mobile-frame flex flex-col"
      style={{ background: "#FFF3E7" }}
    >
      {/* 헤더 */}
      <header
        className="flex items-center justify-between flex-shrink-0"
        style={{
          height: 56,
          paddingInline: 16,
          background: "rgba(255, 248, 240, 0.92)",
          backdropFilter: "blur(8px)",
          borderBottom: "1px solid rgba(227, 93, 73, 0.12)",
        }}
      >
        <button
          type="button"
          onClick={onBack}
          aria-label="뒤로가기"
          className="flex items-center justify-center"
          style={{
            width: 36, height: 36, padding: 0, border: "none",
            background: "transparent", cursor: "pointer",
          }}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#000" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 6l-6 6 6 6" />
          </svg>
        </button>
        <span
          className="font-sejong"
          style={{ fontSize: 16, fontWeight: 700, color: "#000", letterSpacing: "-0.43px" }}
        >
          설정
        </span>
      </header>

      {/* 본문 */}
      <div
        className="flex-1 overflow-y-auto"
        style={{ paddingInline: 19, paddingTop: 20, paddingBottom: "calc(96px + env(safe-area-inset-bottom))" }}
      >
        {/* 프로필 카드 */}
        <div
          className="relative flex items-center"
          style={{
            padding: "16px 18px",
            borderRadius: 24,
            background: "rgba(255, 255, 255, 0.6)",
            border: "1px solid rgba(227, 93, 73, 0.3)",
            gap: 14,
          }}
        >
          <img
            src={levelFace(level)}
            alt={`Lv.${level} 토미`}
            draggable="false"
            className="select-none pointer-events-none"
            style={{ width: 80, height: 80, objectFit: "contain", flexShrink: 0 }}
          />
          <div className="flex-1 min-w-0">
            <h2
              className="font-sejong"
              style={{ fontSize: 18, fontWeight: 700, color: "#000", letterSpacing: "-0.43px" }}
            >
              {studentName}
            </h2>
            <p
              className="font-sejong mt-0.5"
              style={{ fontSize: 12, color: "#75726e", letterSpacing: "-0.43px" }}
            >
              {age}세 · Lv.{level} {levelTitle(level)}
            </p>
            <div className="mt-2 flex items-center gap-2">
              <span
                className="flex items-center gap-1 font-sejong"
                style={{
                  background: "rgba(255, 218, 137, 0.5)",
                  borderRadius: 999,
                  paddingInline: 8,
                  height: 22,
                  fontSize: 11,
                  letterSpacing: "-0.43px",
                }}
              >
                <img src={fireImg} alt="" style={{ width: 13, height: 13 }} />
                {streakDays}일 연속
              </span>
              <button
                type="button"
                onClick={() => { window.location.hash = "#game"; }}
                aria-label={`하트 ${heartCount}개 — 토미랑 달리기 게임으로`}
                className="flex items-center gap-1 font-sejong"
                style={{
                  background: "rgba(252, 228, 225, 0.7)",
                  borderRadius: 999,
                  paddingInline: 8,
                  height: 22,
                  fontSize: 11,
                  letterSpacing: "-0.43px",
                  border: "none",
                  cursor: "pointer",
                }}
              >
                <img src={heartImg} alt="" style={{ width: 11, height: 11 }} />
                {heartCount}
              </button>
            </div>
          </div>
        </div>

        {/* 알림 */}
        <SectionCard title="알림">
          <Row
            label="미션 알림"
            icon={<IconBox src={noticeImg} bg="#FFF1C2" size={35} />}
            right={<Toggle on={missionNoti} onChange={setMissionNoti} />}
          />
          <Row
            label="코치 메시지"
            icon={<IconBox src={messageImg} bg="#DDEBFB" size={35} />}
            right={<Toggle on={coachNoti} onChange={setCoachNoti} />}
          />
          <Row
            label="연속 출석 알림"
            icon={<IconBox src={fireImg} bg="#FCE4E1" size={28} />}
            right={<Toggle on={streakNoti} onChange={setStreakNoti} />}
          />
        </SectionCard>

        {/* 맞춤 설정 */}
        <SectionCard title="맞춤 설정">
          <Row
            label="건강 노트"
            icon={<IconBox src={healthNoteImg} bg="#DCEEDD" size={28} />}
            right={<ChevronRight />}
            onClick={onOpenHealthNote}
          />
          <Row
            label="미션 취향"
            icon={<IconBox src={missionPreferenceImg} bg="#FEE9E3" size={30} />}
            right={<ChevronRight />}
            onClick={onOpenMissionPreferences}
          />
        </SectionCard>

        {/* 계정 */}
        <SectionCard title="계정">
          <Row
            label="로그아웃"
            icon={<IconBox src={outImg} bg="#EAE3F5" size={24} />}
            right={<ChevronRight />}
            onClick={onLogout}
          />
          <Row
            label="탈퇴"
            icon={<IconBox src={warningImg} bg="#FFDFB8" size={27} />}
            right={<ChevronRight />}
            onClick={() => setWithdrawConfirmOpen(true)}
          />
        </SectionCard>
      </div>

      <BottomNav active="settings" onChange={(key) => onNavigate?.(key)} />

      {withdrawConfirmOpen && (
        <div
          className="absolute inset-0 flex items-center justify-center"
          style={{
            zIndex: 20,
            padding: 24,
            background: "rgba(42, 30, 24, 0.28)",
          }}
        >
          <div
            className="font-sejong"
            role="dialog"
            aria-modal="true"
            aria-labelledby="withdraw-confirm-title"
            style={{
              width: "100%",
              maxWidth: 318,
              borderRadius: 24,
              background: "#FFF8F0",
              border: "1px solid rgba(227, 93, 73, 0.32)",
              boxShadow: "0 16px 36px rgba(80, 60, 40, 0.18)",
              padding: "24px 20px 18px",
              textAlign: "center",
              letterSpacing: "-0.43px",
            }}
          >
            <img
              src={warningImg}
              alt=""
              draggable="false"
              className="mx-auto select-none pointer-events-none"
              style={{ width: 54, height: 54, objectFit: "contain" }}
            />
            <h2
              id="withdraw-confirm-title"
              className="mt-3"
              style={{ fontSize: 19, fontWeight: 700, color: "#1f1f1f", lineHeight: "26px" }}
            >
              정말 탈퇴하시겠습니까?
            </h2>
            <p
              className="mt-2"
              style={{ fontSize: 13, color: "#6f6862", lineHeight: "20px", wordBreak: "keep-all" }}
            >
              탈퇴하면 대화내역이 사라집니다.
            </p>
            <div className="mt-5 flex gap-2">
              <button
                type="button"
                onClick={() => setWithdrawConfirmOpen(false)}
                className="flex-1 font-sejong transition-transform active:scale-[0.98]"
                style={{
                  height: 42,
                  borderRadius: 999,
                  border: "1.5px solid #E9C8BD",
                  background: "#FFFFFF",
                  color: "#6f6862",
                  fontSize: 14,
                  fontWeight: 700,
                }}
              >
                취소
              </button>
              <button
                type="button"
                onClick={() => {
                  setWithdrawConfirmOpen(false);
                  onWithdraw?.();
                }}
                className="flex-1 font-sejong transition-transform active:scale-[0.98]"
                style={{
                  height: 42,
                  borderRadius: 999,
                  border: "none",
                  background: "#E35D49",
                  color: "#FFFFFF",
                  fontSize: 14,
                  fontWeight: 700,
                }}
              >
                탈퇴하기
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
