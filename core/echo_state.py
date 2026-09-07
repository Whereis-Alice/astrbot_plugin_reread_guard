from __future__ import annotations

import asyncio
from collections import deque
from typing import TypedDict


class MsgRecord(TypedDict):
    send_id: str
    fp: str


class EchoGroupState:
    def __init__(self, window_sizes: dict[str, int]):
        self.lock = asyncio.Lock()
        self.messages: dict[str, deque[MsgRecord]] = {
            seg_type: deque(maxlen=max(1, limit)) for seg_type, limit in window_sizes.items()
        }
        self.last_handled_fingerprint: str | None = None

    def clear_if_same_sender(self, seg_type: str, send_id: str, need_different: bool) -> None:
        if need_different and self.messages[seg_type] and self.messages[seg_type][-1]["send_id"] == send_id:
            self.messages[seg_type].clear()

    def push_message(self, seg_type: str, send_id: str, fp: str) -> None:
        if self.last_handled_fingerprint is not None and self.last_handled_fingerprint != fp:
            self.last_handled_fingerprint = None
        self.messages[seg_type].append({"send_id": send_id, "fp": fp})

    def get_uniform_tail_fingerprint(self, seg_type: str, count: int) -> str | None:
        if count <= 0 or len(self.messages[seg_type]) < count:
            return None
        tail = list(self.messages[seg_type])[-count:]
        first = tail[0]["fp"]
        return first if all(item["fp"] == first for item in tail) else None

    def clear_all(self) -> None:
        for messages in self.messages.values():
            messages.clear()

    def is_same_as_last_action(self, fingerprint: str) -> bool:
        return self.last_handled_fingerprint == fingerprint

    def mark_handled(self, fingerprint: str) -> None:
        self.last_handled_fingerprint = fingerprint
        self.clear_all()


class EchoStateManager:
    def __init__(self, window_sizes: dict[str, int]):
        self.window_sizes = window_sizes
        self._group_states: dict[str, EchoGroupState] = {}

    def get_state(self, gid: str) -> EchoGroupState:
        key = str(gid)
        if key not in self._group_states:
            self._group_states[key] = EchoGroupState(self.window_sizes)
        return self._group_states[key]

    def clear(self) -> None:
        """清理热重载时的群状态，避免旧配置残留。"""
        self._group_states.clear()
