import { useState } from "react";
import InfoInput from "./InfoInput.jsx";
import HealthNote from "./HealthNote.jsx";
import OnboardingPreferences from "./OnboardingPreferences.jsx";
import Welcome from "./Welcome.jsx";

const STEPS = {
  APP_INTRO: "app_intro",
  FEATURE_INTRO: "feature_intro",
  INFO: "info",
  HEALTH: "health",
  PREFERENCES: "preferences",
  START: "start",
};

function PlaceholderStep({ title, onNext }) {
  return (
    <div
      className="mobile-frame"
      onClick={onNext}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onNext();
      }}
      style={{ background: "#FFF3E7", cursor: "pointer" }}
    >
      <div
        className="absolute bg-white flex flex-col items-center justify-center text-center px-6"
        style={{
          left: 24,
          top: 72,
          width: 354,
          height: 580,
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
        className="signup-submit absolute text-white font-sejong shadow-md flex items-center justify-center transition-all duration-200"
        style={{
          left: 56,
          top: 704,
          width: 290,
          height: 45,
          borderRadius: 50,
          background: "#E35D49",
          fontSize: 20,
          fontWeight: 400,
          lineHeight: "22px",
          padding: 0,
          border: "none",
        }}
      >
        계속하기
      </button>
    </div>
  );
}

export default function OnboardingFlow({
  onInfoSubmit,
  onHealthSubmit,
  onHealthSkip,
  onPreferencesSubmit,
  onComplete,
  preferencesLoading,
  preferencesError,
}) {
  const [step, setStep] = useState(STEPS.APP_INTRO);

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

  if (step === STEPS.APP_INTRO) {
    return <PlaceholderStep title="앱 설명" onNext={() => setStep(STEPS.FEATURE_INTRO)} />;
  }

  if (step === STEPS.FEATURE_INTRO) {
    return <PlaceholderStep title="기능 소개" onNext={() => setStep(STEPS.INFO)} />;
  }

  if (step === STEPS.INFO) {
    return (
      <InfoInput
        onSubmit={(info) => {
          onInfoSubmit?.(info);
          setStep(STEPS.HEALTH);
        }}
        loading={false}
        error=""
      />
    );
  }

  if (step === STEPS.HEALTH) {
    return (
      <HealthNote
        onSubmit={handleHealthSubmit}
        onSkip={handleHealthSkip}
        onBack={() => setStep(STEPS.INFO)}
        loading={false}
      />
    );
  }

  if (step === STEPS.PREFERENCES) {
    return (
      <OnboardingPreferences
        onSubmit={handlePreferencesSubmit}
        onSkip={handlePreferencesSkip}
        loading={preferencesLoading}
        error={preferencesError}
        embedded
      />
    );
  }

  return <Welcome onContinue={onComplete} />;
}
