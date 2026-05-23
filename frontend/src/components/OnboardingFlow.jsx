import { useState } from "react";
import InfoInput from "./InfoInput.jsx";
import HealthNote from "./HealthNote.jsx";
import OnboardingPreferences from "./OnboardingPreferences.jsx";
import OnboardingTutorial from "./OnboardingTutorial.jsx";
import Welcome from "./Welcome.jsx";

const STEPS = {
  FEATURE_INTRO: "feature_intro",
  TUTORIAL: "tutorial",
  INFO: "info",
  HEALTH: "health",
  PREFERENCES: "preferences",
  START: "start",
};

function PlaceholderStep({ title, onNext }) {
  return (
    <div
      className="mobile-frame flex flex-col items-center justify-center"
      onClick={onNext}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onNext();
      }}
      style={{
        background: "#FFF3E7",
        cursor: "pointer",
        padding: "clamp(24px, 8dvh, 72px) 24px calc(24px + env(safe-area-inset-bottom))",
      }}
    >
      <div
        className="bg-white flex flex-col items-center justify-center text-center px-6"
        style={{
          width: "100%",
          maxWidth: 354,
          minHeight: 0,
          flex: "1 1 auto",
          borderRadius: 24,
          border: "1px solid rgba(227, 93, 73, 0.25)",
        }}
      >
        <h1
          className="font-jeju"
          style={{
            color: "#E35D49",
            fontSize: 34,
            fontWeight: 400,
            lineHeight: "42px",
          }}
        >
          {title}
        </h1>
      </div>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onNext();
        }}
        className="signup-submit text-white font-sejong shadow-md flex items-center justify-center transition-all duration-200"
        style={{
          width: "min(100%, 290px)",
          height: "clamp(42px, 5.2dvh, 45px)",
          borderRadius: 50,
          background: "#E35D49",
          fontSize: "clamp(17px, 2.3dvh, 20px)",
          fontWeight: 400,
          lineHeight: "22px",
          padding: 0,
          border: "none",
          marginTop: "clamp(16px, 3dvh, 28px)",
          flexShrink: 0,
        }}
      >
        계속하기
      </button>
    </div>
  );
}

export default function OnboardingFlow({
  onInfoSubmit,
  onInfoBack,
  onHealthSubmit,
  onHealthSkip,
  onPreferencesSubmit,
  onComplete,
  preferencesLoading,
  preferencesError,
}) {
  const [step, setStep] = useState(STEPS.INFO);
  const [tutorialInitialStep, setTutorialInitialStep] = useState(0);
  const [savedInfo, setSavedInfo] = useState({ birth: "", gender: "", isPrivate: false });

  async function handleHealthSubmit(note) {
    await onHealthSubmit?.(note);
    setStep(STEPS.PREFERENCES);
  }

  async function handleHealthSkip() {
    await onHealthSkip?.();
    setStep(STEPS.PREFERENCES);
  }

  async function handlePreferencesSubmit(values) {
    const ok = await onPreferencesSubmit?.(values);
    if (ok !== false) {
      setStep(STEPS.START);
    }
  }

  function handlePreferencesSkip() {
    setStep(STEPS.START);
  }

  if (step === STEPS.FEATURE_INTRO) {
    return <PlaceholderStep title="기능 소개" onNext={() => setStep(STEPS.HEALTH)} />;
  }

  if (step === STEPS.TUTORIAL) {
    return (
      <OnboardingTutorial
        onComplete={() => setStep(STEPS.HEALTH)}
        initialStep={tutorialInitialStep}
        onBack={() => setStep(STEPS.INFO)}
      />
    );
  }

  if (step === STEPS.INFO) {
    return (
      <InfoInput
        onSubmit={(info) => {
          setSavedInfo(info);
          onInfoSubmit?.(info);
          setStep(STEPS.TUTORIAL);
        }}
        onBack={onInfoBack}
        loading={false}
        error=""
        defaultBirth={savedInfo.birth}
        defaultGender={savedInfo.gender}
        defaultIsPrivate={savedInfo.isPrivate}
      />
    );
  }

  if (step === STEPS.HEALTH) {
    return (
      <HealthNote
        onSubmit={handleHealthSubmit}
        onSkip={handleHealthSkip}
        onBack={() => { setTutorialInitialStep(8); setStep(STEPS.TUTORIAL); }}
        loading={false}
      />
    );
  }

  if (step === STEPS.PREFERENCES) {
    return (
      <OnboardingPreferences
        onSubmit={handlePreferencesSubmit}
        onSkip={handlePreferencesSkip}
        onBack={() => setStep(STEPS.HEALTH)}
        loading={preferencesLoading}
        error={preferencesError}
        embedded
      />
    );
  }

  return <Welcome onContinue={onComplete} />;
}
