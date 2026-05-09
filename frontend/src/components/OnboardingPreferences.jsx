import { useMemo, useState } from "react";

const ACTIVITY_OPTIONS = [
  { key: "걷기", label: "걷기" },
  { key: "물 마시기", label: "물 마시기" },
  { key: "줄넘기", label: "줄넘기" },
  { key: "스쿼트", label: "스쿼트" },
  { key: "스트레칭", label: "스트레칭" },
  { key: "채소 먹기", label: "채소 먹기" },
  { key: "과일 먹기", label: "과일 먹기" },
  { key: "간식 줄이기", label: "간식 줄이기" },
  { key: "스마트폰 절제", label: "스마트폰 절제" },
  { key: "게임 시간 줄이기", label: "게임 시간 줄이기" },
  { key: "취침 시간 지키기", label: "취침 시간 지키기" },
  { key: "손 씻기", label: "손 씻기" },
  { key: "양치하기", label: "양치하기" },
];

function toggleValue(list, value) {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

function PreferenceSection({ title, description, selected, onToggle, variant = "like" }) {
  return (
    <section className="onboarding-section">
      <div className="onboarding-section-title">
        <span className={`onboarding-section-icon ${variant}`}>{variant === "like" ? "♡" : "!"}</span>
        <div>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
      </div>
      <div className="preference-chip-grid">
        {ACTIVITY_OPTIONS.map((option) => {
          const active = selected.includes(option.key);
          return (
            <button
              key={option.key}
              type="button"
              className={`preference-chip ${active ? "selected" : ""}`}
              onClick={() => onToggle(option.key)}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </section>
  );
}

export default function OnboardingPreferences({ onSubmit, onSkip, loading, error, embedded = false }) {
  const [preferred, setPreferred] = useState([]);
  const [disliked, setDisliked] = useState([]);
  const [restrictionText, setRestrictionText] = useState("");

  const restrictions = useMemo(
    () =>
      restrictionText
        .split(/[,\n]/)
        .map((item) => item.trim())
        .filter(Boolean),
    [restrictionText]
  );

  function handleSubmit(e) {
    e.preventDefault();
    onSubmit?.({
      preferred_activity_keys: preferred,
      disliked_activity_keys: disliked,
      restrictions,
    });
  }

  const content = (
      <form className="onboarding-card" onSubmit={handleSubmit}>
        <div className="onboarding-hero">
          <div>
            <span className="tomato-mark">🍅</span>
          </div>
          <div>
            <h2>좋아하는 미션을 알려주세요</h2>
            <p>취향과 주의사항을 기억해서 더 잘 맞는 미션을 고를게요.</p>
          </div>
        </div>

        <PreferenceSection
          title="좋아하는 활동/미션"
          description="자주 해도 괜찮은 활동을 골라주세요."
          selected={preferred}
          onToggle={(key) => setPreferred((prev) => toggleValue(prev, key))}
          variant="like"
        />

        <PreferenceSection
          title="싫어하는 활동/미션"
          description="가능하면 피하고 싶은 활동을 골라주세요."
          selected={disliked}
          onToggle={(key) => setDisliked((prev) => toggleValue(prev, key))}
          variant="dislike"
        />

        <section className="onboarding-section">
          <div className="onboarding-section-title">
            <span className="onboarding-section-icon caution">i</span>
            <div>
              <h3>피해야 하는 것 / 알레르기 / 주의사항</h3>
              <p>쉼표나 줄바꿈으로 여러 개를 입력할 수 있어요.</p>
            </div>
          </div>
          <textarea
            className="restriction-textarea"
            value={restrictionText}
            onChange={(e) => setRestrictionText(e.target.value)}
            placeholder="예: 우유, 견과류, 야외 활동 어려움"
            rows={3}
          />
          {restrictions.length > 0 && (
            <div className="restriction-preview">
              {restrictions.map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
          )}
        </section>

        {error && <p className="form-error">{error}</p>}

        <div className="modal-actions">
          <button type="button" className="secondary-action" onClick={onSkip} disabled={loading}>
            건너뛰기
          </button>
          <button type="submit" className="primary-action" disabled={loading}>
            {loading ? "저장 중..." : "저장하기"}
          </button>
        </div>
      </form>
  );

  if (embedded) {
    return (
      <div className="mobile-frame onboarding-preferences-page" style={{ background: "#FFF3E7" }}>
        {content}
      </div>
    );
  }

  return (
    <div className="modal-backdrop soft">
      {content}
    </div>
  );
}
