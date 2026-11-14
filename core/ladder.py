"""Udhaar limit ladder (plan P2 step 4). OUR design choice, not from the study; say so if asked.

Steps: Rs100 -> Rs200 -> Rs400 -> Rs700 -> Rs1,000 cap.
- up one step after 3 on-time repayments in a row at the current step
- repaid late (> 7 days past due): drop one step
- unpaid at 30 days: freeze; no new offers until cleared
- the shopkeeper can always override or switch it off
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import config

STEPS = config.LADDER_STEPS_PAISE


@dataclass(frozen=True)
class LadderState:
    step: int = 0           # index into STEPS
    streak: int = 0         # on-time repayments in a row at this step
    frozen: bool = False
    switched_off: bool = False

    @property
    def offer_paise(self) -> int | None:
        if self.frozen or self.switched_off:
            return None
        return STEPS[self.step]


def classify(days_to_repay: float | None, days_open: float | None = None, due_days: int = config.ONTIME_DAYS) -> str:
    """-> on_time | slightly_late | late | unpaid_30 | open"""
    if days_to_repay is None:
        if days_open is not None and days_open >= config.LADDER_FREEZE_DAYS:
            return "unpaid_30"
        return "open"
    past_due = days_to_repay - due_days
    if past_due <= 0:
        return "on_time"
    if past_due <= config.LADDER_LATE_DAYS:
        return "slightly_late"
    return "late"


def next_state(s: LadderState, event: str) -> LadderState:
    if event == "switch_off":
        return replace(s, switched_off=True)
    if event == "switch_on":
        return replace(s, switched_off=False)
    if event == "unpaid_30":
        return replace(s, frozen=True, streak=0)
    if event == "cleared":                    # frozen udhaar finally repaid: unfreeze at the same step
        return replace(s, frozen=False, streak=0)
    if s.frozen:
        return s
    if event == "on_time":
        streak = s.streak + 1
        if streak >= config.LADDER_UP_AFTER_ONTIME and s.step < len(STEPS) - 1:
            return replace(s, step=s.step + 1, streak=0)
        return replace(s, streak=min(streak, config.LADDER_UP_AFTER_ONTIME))
    if event == "late":
        return replace(s, step=max(0, s.step - 1), streak=0)
    if event == "slightly_late":
        return replace(s, streak=0)
    if event == "override":
        return s
    raise ValueError(f"unknown ladder event {event!r}")


def replay(events: list[str], start: LadderState | None = None) -> LadderState:
    s = start or LadderState()
    for e in events:
        s = next_state(s, e)
    return s
