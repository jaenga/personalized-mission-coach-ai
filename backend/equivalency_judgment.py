from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass, field
from typing import Any


VALID_DECISIONS = {"approved", "denied", "clarify"}


def normalize_decision(value: Any, *, approved: Any = None, need_clarification: Any = None) -> str:
    decision = str(value or "").strip().lower()
    if decision in VALID_DECISIONS:
        return decision
    if approved is True and not need_clarification:
        return "approved"
    if need_clarification:
        return "clarify"
    return "denied"


@dataclass
class EquivalencyJudgment(MutableMapping[str, Any]):
    decision: str
    reason: str = ""
    reply: str = ""
    clarify_question: str | None = None
    raw: dict | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.decision = normalize_decision(self.decision)
        self.reason = str(self.reason or "").strip()
        self.reply = str(self.reply or "").strip()
        if not isinstance(self.clarify_question, str) or not self.clarify_question.strip():
            self.clarify_question = None
        else:
            self.clarify_question = self.clarify_question.strip()

    @property
    def approved(self) -> bool:
        return self.decision == "approved"

    @property
    def need_clarification(self) -> bool:
        return self.decision == "clarify"

    @classmethod
    def from_mapping(cls, data: MutableMapping[str, Any] | dict | None) -> "EquivalencyJudgment":
        data = dict(data or {})
        decision = normalize_decision(
            data.get("decision"),
            approved=data.get("approved"),
            need_clarification=data.get("need_clarification"),
        )
        known = {"decision", "approved", "need_clarification", "reason", "reply", "clarify_question", "raw"}
        extra = {key: value for key, value in data.items() if key not in known}
        return cls(
            decision=decision,
            reason=data.get("reason") or "",
            reply=data.get("reply") or "",
            clarify_question=data.get("clarify_question"),
            raw=data.get("raw"),
            extra=extra,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "approved": self.approved,
            "need_clarification": self.need_clarification,
            "reason": self.reason,
            "reply": self.reply,
            "clarify_question": self.clarify_question,
            "raw": self.raw,
            **self.extra,
        }

    def __getitem__(self, key: str) -> Any:
        if key == "decision":
            return self.decision
        if key == "approved":
            return self.approved
        if key == "need_clarification":
            return self.need_clarification
        if key == "reason":
            return self.reason
        if key == "reply":
            return self.reply
        if key == "clarify_question":
            return self.clarify_question
        if key == "raw":
            return self.raw
        return self.extra[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if key == "decision":
            self.decision = normalize_decision(value)
        elif key == "approved":
            self.decision = "approved" if value else ("clarify" if self.need_clarification else "denied")
        elif key == "need_clarification":
            if value:
                self.decision = "clarify"
            elif self.decision == "clarify":
                self.decision = "denied"
        elif key == "reason":
            self.reason = str(value or "").strip()
        elif key == "reply":
            self.reply = str(value or "").strip()
        elif key == "clarify_question":
            self.clarify_question = str(value).strip() if value else None
        elif key == "raw":
            self.raw = value
        else:
            self.extra[key] = value

    def __delitem__(self, key: str) -> None:
        if key in {"decision", "approved", "need_clarification", "reason", "reply", "clarify_question", "raw"}:
            raise KeyError(f"Cannot delete core judgment field: {key}")
        del self.extra[key]

    def __iter__(self) -> Iterator[str]:
        yield from self.to_dict()

    def __len__(self) -> int:
        return len(self.to_dict())
