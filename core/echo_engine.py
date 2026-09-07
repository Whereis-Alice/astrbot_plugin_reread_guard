from __future__ import annotations

import random
from copy import deepcopy
from dataclasses import dataclass

from astrbot.api import logger
from astrbot.api.message_components import BaseMessageComponent, Face, Image, Plain

from .echo_config import EchoGuardConfig
from .echo_state import EchoGroupState


@dataclass(slots=True)
class EchoGuardActionPlan:
    repeat_count: int
    action: str
    output_segment: BaseMessageComponent | None = None


class EchoGuardEngine:
    ACTIONS = ("follow", "interrupt", "ban")

    def __init__(self, cfg: EchoGuardConfig):
        self.cfg = cfg
        pool = [(action, cfg.weight_of(action)) for action in self.ACTIONS]
        pool = [(action, weight) for action, weight in pool if weight > 0]
        self._actions, self._weights = zip(*pool) if pool else ((), ())
        if not self._actions:
            logger.warning("[echo_guard] all action weights are 0; actions disabled")

    @staticmethod
    def make_fingerprint(seg: BaseMessageComponent) -> str | None:
        if isinstance(seg, Plain):
            return f"text:{seg.text}"
        if isinstance(seg, Image):
            key = seg.file or seg.url or seg.path
            return f"image:{key}" if key else None
        if isinstance(seg, Face):
            return f"face:{seg.id}"
        return f"unknown:{seg.type}"

    def evaluate(
        self,
        state: EchoGroupState,
        seg_type: str,
        send_id: str,
        seg: BaseMessageComponent,
    ) -> EchoGuardActionPlan | None:
        state.clear_if_same_sender(seg_type, send_id, self.cfg.need_different)
        fingerprint = self.make_fingerprint(seg)
        if fingerprint is None:
            return None
        state.push_message(seg_type, send_id, fingerprint)
        threshold = self.cfg.get_threshold(seg_type)
        candidate = state.get_uniform_tail_fingerprint(seg_type, threshold)
        if not candidate or state.is_same_as_last_action(candidate) or not self.cfg.should_echo() or not self._actions:
            return None
        state.mark_handled(candidate)
        action = random.choices(self._actions, self._weights, k=1)[0]
        if action == "ban":
            return EchoGuardActionPlan(repeat_count=threshold, action=action)
        output = Plain(self.cfg.interrupt.text) if action == "interrupt" else deepcopy(seg)
        return EchoGuardActionPlan(
            repeat_count=threshold,
            action=action,
            output_segment=output,
        )
