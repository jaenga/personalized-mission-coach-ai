import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Home from "./Home.jsx";
import ChatScreen from "./ChatScreen.jsx";
import LearnScreen from "./LearnScreen.jsx";
import onb1 from "../assets/tomato/onboarding/onb1.svg";
import onb2 from "../assets/tomato/onboarding/onb2.svg";
import onb3 from "../assets/tomato/onboarding/onb3.svg";
import onb4 from "../assets/tomato/onboarding/onb4.svg";
import onb5 from "../assets/tomato/onboarding/onb5.svg";
import onb6 from "../assets/tomato/onboarding/onb6.svg";
import onb7 from "../assets/tomato/onboarding/onb7.svg";
import onb8 from "../assets/tomato/onboarding/onb8.svg";
import onb9 from "../assets/tomato/onboarding/onb9.svg";
import indImg from "../assets/tomato/onboarding/ind.svg";

const SAMPLE_MISSION = {
  title: "엘리베이터 대신 계단으로 걷기",
  description: "계단을 이용해 몸을 조금 더 움직여보세요.",
  done: false,
};

const SAMPLE_MESSAGES = [
  {
    role: "assistant",
    content: "오늘 미션을 했는지 알려줘! 궁금한 것도 나에게 물어봐.",
  },
  {
    role: "user",
    content: "토미야 나 오늘 미션 성공했어!",
  },
  {
    role: "assistant",
    content: "와, 정말 멋진걸! 🎉 오늘 미션을 해냈다니 너무 자랑스러워! 이렇게 하나씩 쌓아가다 보면 건강한 습관이 생길 거야. 내일 미션도 같이 해보자! 💪",
  },
];

const SAMPLE_SUCCESS_DATES = ["2026-05-08", "2026-05-09"];

const STEPS = [
  // 1. 홈 — 토미 자기소개 (스포트라이트 없음)
  { id: "mission_intro", screen: "home" },
  // 2. 홈 — 오늘의 미션 카드
  {
    id: "home_mission",
    screen: "home",
    target: "home-mission-card",
    pad: { top: 22, right: 16, bottom: 16, left: 18 },
    scrollTo: "top",
    blur: 7,
  },
  // 3. 홈 — 이번 주 기록 카드
  {
    id: "home_calendar",
    screen: "home",
    target: "home-calendar-card",
    pad: { top: 10, right: 10, bottom: 10, left: 10 },
    blur: 7,
  },
  // 4. 채팅 화면 소개
  { id: "chat_intro", screen: "chat", target: "chat-plus-btn", pad: { top: 10, right: 10, bottom: 10, left: 10 }, blur: 5, scrollTo: "none" },
  // 5. 배움 — 교육 소개 (스포트라이트 없음)
  { id: "learn_intro", screen: "learn" },
  // 6. 배움 — 뽑기권 티켓
  { id: "reward_ticket", screen: "learn", target: "learn-ticket", blur: 5 },
  // 7. 배움 — 하트
  { id: "reward_heart", screen: "learn", target: "learn-heart", blur: 5 },
  // 8. 배움 — 레벨
  { id: "reward_level", screen: "learn", target: "learn-level", blur: 5 },
  // 9. 배움 — 마무리 (스포트라이트 없음)
  { id: "rewards_done", screen: "learn" },
];

// ── 스텝별 에셋 ─────────────────────────────────────────────────────────
// style: 캐릭터 위치·크기 / bubble.style: 말풍선 위치·크기 / bubble.tail: 꼬리 방향
const STEP_ASSETS = {
  mission_intro: {
    src: onb1,
    style:  { left: "50%", transform: "translateX(-50%)", bottom: 100, width: 200 },
    bubble: {
      texts: [
        "안녕! 나는 토미야. 앞으로 너랑 같이 건강한 생활 습관을 만들어갈 거야!",
        "매일 도전하기 쉬운 작은 미션들을 알려줄게.",
        "이제 앱 사용법을 간단히 소개해줄게. 천천히 따라와봐!"
      ],
      highlights: ["토미", "건강한 생활 습관", "도전하기 쉬운 작은 미션"],
      tail: "down",
      style: { left: "50%", transform: "translateX(-50%)", bottom: 310, width: 220 },
    },
  },
  home_mission: {
    src: onb2,
    style:  { left: "70%", transform: "translateX(-50%)", bottom: 210, width: 160 },
    bubble: { texts: ["이곳에서 항상 오늘의 미션을 확인할 수 있어!", "누르면 자세한 미션 설명이 나오니까 잘 확인하고 미션을 도전해보자."], highlights: ["오늘의 미션", "미션 설명"], tail: "down-right",
              style: { left: 70, bottom: 360, width: 200 } },
  },
  home_calendar: {
    src: onb3,
    style:  { right: 20, bottom: 100, width: 160 },
    bubble: { texts: ["여기서 미션 기록을 확인할 수 있어!", "미션을 성공하면 캘린더 위에 스티커가 올라가! 캘린더를 토미 스티커로 꽉 채워보자~"], highlights: ["미션 기록", "캘린더", "스티커"], tail: "right-bottom",
              style: { left: 30, bottom: 160, width: 200 } },
  },
  chat_intro: {
    src: onb4,
    style:  { left: "50%", transform: "translateX(-50%)", bottom: 100, width: 200 },
    bubble: { texts: ["이곳에선 나와 대화할 수 있어!", "왼쪽 아래 + 버튼을 누르면, 내가 할 수 있는 일들을 볼 수 있어. 건강 관련된 이야기는 무엇이든 물어봐!"], highlights: ["+ 버튼", "건강 관련된 이야기"], tail: "down",
              style: { left: "50%", transform: "translateX(-50%)", bottom: 310, width: 220 } },
  },
  learn_intro: {
    src: onb5,
    style:  { left: "50%", transform: "translateX(-50%)", bottom: 100, width: 200 },
    bubble: { texts: ["여기는 재미있고 도움되는 건강 지식을 배울 수 있는 곳이야!", "매일 두 개의 교육과, 퀴즈가 있어. 퀴즈를 모두 맞추면 보상도 있으니 꼭 풀어보자!"], highlights: ["건강 지식", "교육", "퀴즈", "보상"], tail: "down",
              style: { left: "50%", transform: "translateX(-50%)", bottom: 320, width: 220 } },
  },
  reward_ticket: {
    src: onb6,
    style:  { left: "50%", transform: "translateX(-50%)", bottom: 100, width: 200 },
    bubble: { texts: ["건강 교육을 다 듣고, 퀴즈를 모두 맞추면 뽑기권을 받을 수 있어!", "뽑기에서는 하트와 경험치를 얻을 수 있어."], highlights: ["퀴즈", "뽑기권", "하트", "경험치"], tail: "down",
              style: { left: "50%", transform: "translateX(-50%)", bottom: 350, width: 250 } },
  },
  reward_heart: {
    src: onb7,
    style:  { left: "50%", transform: "translateX(-50%)", bottom: 100, width: 230 },
    bubble: { text: "하트는 토미런의 입장권이야! 하트를 모아 게임을 할 수 있지.", tail: "down",
              style: { left: "50%", transform: "translateX(-50%)", bottom: 350, width: 250 } },
  },
  reward_level: {
    src: onb8,
    style:  { left: "45%", transform: "translateX(-50%)", bottom: 270, width: 310 },
    bubble: { texts: ["경험치를 모으면 레벨이 올라가! 경험치를 많이 모으면 더 높은 레벨에 도달할 수 있어.", "특정 레벨에 도달하면 더 멋진 토마토가 될 수 있어!"], highlights: ["경험치", "레벨", "토마토"], tail: "up",
              style: { left: "50%", transform: "translateX(-50%)", bottom: 150, width: 300 } },
  },
  rewards_done: {
    src: onb9,
    style:  { left: "50%", transform: "translateX(-50%)", bottom: 100, width: 250 },
    bubble: { texts: ["나의 안내는 여기까지야! 우리 앞으로 열심히 나아가보자!", "너에게 딱 맞는 미션을 주기 위해 필요한 정보가 있어. 대답해줄래?"], highlights: ["딱 맞는 미션"], tail: "down",
              style: { left: "50%", transform: "translateX(-50%)", bottom: 350, width: 250 } },
  },
};

// 텍스트를 강조/일반 세그먼트 배열로 미리 분리
// 타이핑 애니메이션 시작 전에 호출해 글자 수 카운트만으로 렌더링
function buildSegments(text, keywords) {
  if (!keywords?.length) return [{ text, style: null }];
  const normalized = keywords.map((k) =>
    typeof k === "string" ? { text: k, color: "#E35D49", bold: true } : k
  );
  const sorted = [...normalized].sort((a, b) => b.text.length - a.text.length);
  const regex = new RegExp(
    `(${sorted.map((k) => k.text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`,
    "g"
  );
  return text.split(regex).map((part) => {
    const match = normalized.find((k) => k.text === part);
    return {
      text: part,
      style: match
        ? {
            color: match.color || "#E35D49",
            fontWeight: match.bold !== false ? 800 : undefined,
            ...(match.bg && { background: match.bg, borderRadius: 4, padding: "1px 5px" }),
          }
        : null,
    };
  });
}

// 세그먼트 배열 + 표시할 글자 수 → JSX
function renderSegments(segments, charCount) {
  const out = [];
  let remaining = charCount;
  for (let i = 0; i < segments.length; i++) {
    if (remaining <= 0) break;
    const seg = segments[i];
    const visible = seg.text.slice(0, remaining);
    remaining -= seg.text.length;
    out.push(
      seg.style
        ? <span key={i} style={seg.style}>{visible}</span>
        : visible
    );
  }
  return out;
}

const SPOTLIGHT_RADIUS = 20;

function findScrollable(el) {
  while (el) {
    if (el.scrollHeight > el.clientHeight) return el;
    el = el.parentElement;
  }
  return null;
}

// 꼬리 방향 → 위치·테두리 매핑
// 45deg 회전한 정사각형의 각 꼭짓점을 이용해 방향 표현
// down/up: 하단·상단 중앙·좌·우  /  left/right: 좌측·우측 중앙·상·하
const TAIL_CONFIG = {
  // ── 하단 ──
  "down":         { bottom: -8, left: "50%", transform: "translateX(-50%) rotate(45deg)", borderRight: true,  borderBottom: true },
  "down-left":    { bottom: -8, left: 24,    transform: "rotate(45deg)",                  borderRight: true,  borderBottom: true },
  "down-right":   { bottom: -8, right: 24,   transform: "rotate(45deg)",                  borderRight: true,  borderBottom: true },
  // ── 상단 ──
  "up":           { top:    -8, left: "50%", transform: "translateX(-50%) rotate(45deg)", borderLeft:  true,  borderTop:    true },
  "up-left":      { top:    -8, left: 24,    transform: "rotate(45deg)",                  borderLeft:  true,  borderTop:    true },
  "up-right":     { top:    -8, right: 24,   transform: "rotate(45deg)",                  borderRight: true,  borderTop:    true },
  // ── 좌측 ──
  "left":         { left:   -8, top: "50%",  transform: "translateY(-50%) rotate(45deg)", borderBottom: true, borderLeft:  true },
  "left-top":     { left:   -8, top: 20,     transform: "rotate(45deg)",                  borderBottom: true, borderLeft:  true },
  "left-bottom":  { left:   -8, bottom: 20,  transform: "rotate(45deg)",                  borderBottom: true, borderLeft:  true },
  // ── 우측 ──
  "right":        { right:  -8, top: "50%",  transform: "translateY(-50%) rotate(45deg)", borderTop:   true,  borderRight: true },
  "right-top":    { right:  -8, top: 20,     transform: "rotate(45deg)",                  borderTop:   true,  borderRight: true },
  "right-bottom": { right:  -8, bottom: 20,  transform: "rotate(45deg)",                  borderTop:   true,  borderRight: true },
};

const BUBBLE_BORDER = "1px solid rgba(227, 93, 73, 0.2)";

function makeTailStyle(tail, bgColor) {
  if (!tail) return null;
  const tc = TAIL_CONFIG[tail] ?? TAIL_CONFIG["down"];
  return {
    position: "absolute",
    width: 16,
    height: 16,
    background: bgColor,
    transform: tc.transform,
    ...(tc.bottom  !== undefined && { bottom: tc.bottom }),
    ...(tc.top     !== undefined && { top:    tc.top    }),
    ...(tc.left    !== undefined && { left:   tc.left   }),
    ...(tc.right   !== undefined && { right:  tc.right  }),
    ...(tc.borderRight  && { borderRight:  BUBBLE_BORDER }),
    ...(tc.borderBottom && { borderBottom: BUBBLE_BORDER }),
    ...(tc.borderLeft   && { borderLeft:   BUBBLE_BORDER }),
    ...(tc.borderTop    && { borderTop:    BUBBLE_BORDER }),
  };
}

function SpeechBubble({ text, style, tail = "down", bgColor = "#FFFFFF", textColor = "#1a1a1a", speed = 60 }) {
  const [displayed, setDisplayed] = useState("");

  useEffect(() => {
    setDisplayed("");
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setDisplayed(text.slice(0, i));
      if (i >= text.length) clearInterval(id);
    }, speed);
    return () => clearInterval(id);
  }, [text]);

  const tailStyle = makeTailStyle(tail, bgColor);

  return (
    <div
      className="absolute font-sejong"
      style={{
        padding: "12px 16px",
        borderRadius: 18,
        background: bgColor,
        border: "1px solid rgba(227, 93, 73, 0.18)",
        boxShadow: "0 8px 20px rgba(184, 72, 56, 0.12), 0 2px 6px rgba(0,0,0,0.05)",
        color: textColor,
        fontSize: 14,
        fontWeight: 700,
        lineHeight: "20px",
        pointerEvents: "none",
        maxWidth: 220,
        wordBreak: "keep-all",
        zIndex: 1002,
        ...style,
      }}
    >
      {displayed}
      {tailStyle && <span aria-hidden="true" style={tailStyle} />}
    </div>
  );
}

// Single bubble item for use inside BubbleStack (not absolutely positioned)
function BubbleItem({ text, tail, bgColor = "#FFFFFF", textColor = "#1a1a1a", speed = 50, onDone, highlights }) {
  const segments = buildSegments(text, highlights);
  const [charCount, setCharCount] = useState(speed === 0 ? text.length : 0);

  useEffect(() => {
    if (speed === 0) {
      setCharCount(text.length);
      return;
    }
    setCharCount(0);
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setCharCount(i);
      if (i >= text.length) {
        clearInterval(id);
        onDone?.();
      }
    }, speed);
    return () => clearInterval(id);
  }, [text, speed]);

  const tailStyle = makeTailStyle(tail, bgColor);

  return (
    <div
      className="font-sejong"
      style={{
        position: "relative",
        padding: "10px 14px",
        borderRadius: 16,
        background: bgColor,
        border: "1px solid rgba(227, 93, 73, 0.18)",
        boxShadow: "0 4px 12px rgba(184, 72, 56, 0.10), 0 1px 4px rgba(0,0,0,0.04)",
        color: textColor,
        fontSize: 14,
        fontWeight: 700,
        lineHeight: "19px",
        pointerEvents: "none",
        wordBreak: "keep-all",
      }}
    >
      {renderSegments(segments, charCount)}
      {tailStyle && <span aria-hidden="true" style={tailStyle} />}
    </div>
  );
}

// Multi-message chat-style bubble stack — messages appear one by one sequentially
function BubbleStack({ texts, style, tail = "down", bgColor = "#FFFFFF", textColor = "#1a1a1a", speed = 50, highlights }) {
  const [visibleCount, setVisibleCount] = useState(1);

  function handleDone() {
    setVisibleCount((c) => {
      if (c < texts.length) {
        setTimeout(() => setVisibleCount((prev) => Math.min(prev + 1, texts.length)), 350);
      }
      return c;
    });
  }

  return (
    <div
      className="absolute"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        pointerEvents: "none",
        zIndex: 1002,
        ...style,
      }}
    >
      {texts.slice(0, visibleCount).map((text, i) => {
        const isLast = i === visibleCount - 1;
        const isFinal = i === texts.length - 1;
        return (
          <BubbleItem
            key={i}
            text={text}
            tail={isFinal ? tail : undefined}
            bgColor={bgColor}
            textColor={textColor}
            speed={isLast ? speed : 0}
            onDone={isLast ? handleDone : undefined}
            highlights={highlights}
          />
        );
      })}
    </div>
  );
}

function TutorialScreen({ screen, stepId }) {
  return (
    <div className="onboarding-tutorial-preview">
      {screen === "home" && (
        <Home
          studentName="토미"
          level={1}
          currentXp={0}
          maxXp={20}
          streakDays={2}
          ticketCount={0}
          heartCount={3}
          todayMission={SAMPLE_MISSION}
          successDates={SAMPLE_SUCCESS_DATES}
          initialCalendarOpen={stepId === "home_calendar"}
          onNavigate={() => {}}
        />
      )}
      {screen === "chat" && (
        <ChatScreen
          onBack={() => {}}
          messages={SAMPLE_MESSAGES}
          loading={false}
          onSend={() => {}}
          todayMission={SAMPLE_MISSION}
        />
      )}
      {screen === "learn" && (
        <LearnScreen
          onNavigate={() => {}}
          studentId={null}
          todayMission={SAMPLE_MISSION}
          level={1}
          currentXp={0}
          maxXp={20}
          ticketCount={0}
          heartCount={3}
          onAppStateUpdate={() => {}}
          disablePulse={true}
        />
      )}
    </div>
  );
}

export default function OnboardingTutorial({ onComplete, onBack, initialStep = 0 }) {
  const [index, setIndex] = useState(initialStep);
  const [spotlight, setSpotlight] = useState(null);
  const shellRef = useRef(null);
  const step = STEPS[index];

  useLayoutEffect(() => {
    if (!step.target) {
      setSpotlight(null);
      return;
    }
    const shell = shellRef.current;
    const target = shell?.querySelector(`[data-tutorial-target="${step.target}"]`);
    if (!target) {
      setSpotlight(null);
      return;
    }

    // scrollTo: "top" → 컨테이너를 맨 위로 (카드가 화면 하단에 자연스럽게 위치)
    // scrollTo: "center"(기본) → 타겟을 뷰포트 중앙으로 스크롤
    if (step.scrollTo === "top") {
      const scroller = findScrollable(target);
      if (scroller) scroller.scrollTop = 0;
    } else if (step.scrollTo !== "none") {
      target.scrollIntoView({ block: "center", behavior: "instant" });
    }

    const shellRect = shell.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const pad = step.pad ?? { top: 0, right: 0, bottom: 0, left: 0 };

    setSpotlight({
      x: targetRect.left - shellRect.left - pad.left,
      y: targetRect.top - shellRect.top - pad.top,
      w: targetRect.width + pad.left + pad.right,
      h: targetRect.height + pad.top + pad.bottom,
    });
  }, [step]);

  function go(delta) {
    const next = index + delta;
    if (next < 0) {
      onBack?.();
      return;
    }
    if (next >= STEPS.length) {
      onComplete?.();
      return;
    }
    setIndex(next);
  }

  function handleClick(e) {
    const { left, width } = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - left;
    go(x < width * 0.35 ? -1 : 1);
  }

  const maskId = `spotlight-mask-${index}`;

  return (
    <div ref={shellRef} className="relative onboarding-tutorial-shell" onClick={handleClick}>
      <TutorialScreen key={step.id} screen={step.screen} stepId={step.id} />

      <svg
        className="absolute inset-0 pointer-events-none"
        style={{ zIndex: 1000, width: "100%", height: "100%" }}
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <filter id={`blur-${index}`} x="-35%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation={step.blur ?? 7} />
          </filter>
          <mask id={maskId}>
            <rect width="100%" height="100%" fill="white" />
            {spotlight && (
              <rect
                x={spotlight.x}
                y={spotlight.y}
                width={spotlight.w}
                height={spotlight.h}
                rx={SPOTLIGHT_RADIUS}
                fill="black"
                filter={`url(#blur-${index})`}
              />
            )}
          </mask>
        </defs>

        {/* 어두운 오버레이 — 구멍 뚫린 부분만 원래 밝기로 */}
        <rect
          width="100%"
          height="100%"
          fill="rgba(0,0,0,0.48)"
          mask={`url(#${maskId})`}
        />
      </svg>

      {/* 스포트라이트 펄스 링 — 뽑기권/하트/레벨 스텝 */}
      {spotlight && ["chat_intro", "reward_ticket", "reward_heart", "reward_level"].includes(step.id) && (
        <>
          <style>{`
            @keyframes onbPulseRing {
              0%   { box-shadow: 0 0 0 0 rgba(244, 211, 82, 0.32); }
              70%  { box-shadow: 0 0 0 16px rgba(244, 211, 82, 0); }
              100% { box-shadow: 0 0 0 16px rgba(244, 211, 82, 0); }
            }
          `}</style>
          <div
            aria-hidden="true"
            style={{
              position: "absolute",
              left: spotlight.x,
              top: spotlight.y,
              width: spotlight.w,
              height: spotlight.h,
              borderRadius: SPOTLIGHT_RADIUS,
              animation: "onbPulseRing 1.6s ease-out infinite",
              pointerEvents: "none",
              zIndex: 1001,
            }}
          />
        </>
      )}

      {/* 스텝별 튜토리얼 에셋 + 말풍선 */}
      {STEP_ASSETS[step.id] && (() => {
        const asset = STEP_ASSETS[step.id];
        return (
          <>
            <img
              src={asset.src}
              alt=""
              draggable="false"
              className="absolute pointer-events-none select-none"
              style={{ ...asset.style, zIndex: 1001 }}
            />
            {asset.bubble && (
              asset.bubble.texts ? (
                <BubbleStack
                  key={step.id}
                  texts={asset.bubble.texts}
                  style={asset.bubble.style}
                  tail={asset.bubble.tail}
                  bgColor={asset.bubble.bgColor}
                  textColor={asset.bubble.textColor}
                  highlights={asset.bubble.highlights}
                />
              ) : (
                <SpeechBubble
                  text={asset.bubble.text}
                  style={asset.bubble.style}
                  tail={asset.bubble.tail}
                  bgColor={asset.bubble.bgColor}
                  textColor={asset.bubble.textColor}
                />
              )
            )}
          </>
        );
      })()}


      {/* 좌우 넘기기 힌트 */}
      <div
        style={{
          position: "absolute", top: "50%", left: 6, transform: "translateY(-50%)",
          zIndex: 1004, color: "rgba(255,255,255,0.45)", fontSize: 56, pointerEvents: "none",
          userSelect: "none", lineHeight: 1,
        }}
      >‹</div>
      <div
        style={{
          position: "absolute", top: "50%", right: 6, transform: "translateY(-50%)",
          zIndex: 1004, color: "rgba(255,255,255,0.45)", fontSize: 56, pointerEvents: "none",
          userSelect: "none", lineHeight: 1,
        }}
      >›</div>

      {/* 하단 인디케이터 — 점 + 현재 위치 토마토 */}
      <div
        className="absolute"
        style={{
          left: "50%", transform: "translateX(-50%)", bottom: 18,
          display: "flex", alignItems: "center", gap: 8,
          zIndex: 1003,
        }}
      >
        {STEPS.map((s, i) =>
          i === index ? (
            <img key={s.id} src={indImg} alt="" draggable="false"
              style={{ width: 22, height: 22, pointerEvents: "none", userSelect: "none" }} />
          ) : (
            <span key={s.id} style={{
              width: 7, height: 7, borderRadius: "50%",
              background: "rgba(255,255,255,0.55)", display: "inline-block",
            }} />
          )
        )}
      </div>
    </div>
  );
}
