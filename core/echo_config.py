from __future__ import annotations

import random
from collections.abc import MutableMapping
from copy import deepcopy
from typing import Any, ClassVar, get_type_hints

from astrbot.api import AstrBotConfig, logger


class EchoConfigNode:
    """Read AstrBot configuration and provide safe defaults for missing fields."""

    _SCHEMA_CACHE: ClassVar[dict[type, dict[str, type]]] = {}
    _DEFAULTS: ClassVar[dict[str, Any]] = {}

    @classmethod
    def _schema(cls) -> dict[str, type]:
        return cls._SCHEMA_CACHE.setdefault(
            cls,
            {
                key: value
                for key, value in get_type_hints(cls).items()
                if not key.startswith("_")
            },
        )

    @classmethod
    def _default_for(cls, key: str) -> Any:
        return deepcopy(cls._DEFAULTS.get(key))

    def __init__(self, data: MutableMapping[str, Any]):
        object.__setattr__(self, "_data", data)
        object.__setattr__(self, "_children", {})
        for key in self._schema():
            if key not in data and key not in self._DEFAULTS:
                logger.warning("[echo_guard.config] missing key: %s", key)

    def __getattr__(self, key: str) -> Any:
        if key not in self._schema():
            raise AttributeError(key)

        value = self._data.get(key, self._default_for(key))
        value_type = self._schema()[key]
        if isinstance(value_type, type) and issubclass(value_type, EchoConfigNode):
            children: dict[str, EchoConfigNode] = self.__dict__["_children"]
            if key not in children:
                if not isinstance(value, MutableMapping):
                    value = {}
                    self._data[key] = value
                children[key] = value_type(value)
            return children[key]
        return value

    def __setattr__(self, key: str, value: Any) -> None:
        if key in self._schema():
            self._data[key] = value
            return
        object.__setattr__(self, key, value)


class EchoFollowConfig(EchoConfigNode):
    _DEFAULTS: ClassVar[dict[str, Any]] = {"weight": 90}

    weight: int


class EchoInterruptConfig(EchoConfigNode):
    _DEFAULTS: ClassVar[dict[str, Any]] = {"weight": 5, "text": "打断！"}

    weight: int
    text: str


class EchoBanConfig(EchoConfigNode):
    _DEFAULTS: ClassVar[dict[str, Any]] = {
        "weight": 5,
        "duration": 60,
        "prompt": "{user_name}复读过头了，先禁言{ban_duration}秒",
    }

    weight: int
    duration: int
    prompt: str


class EchoGuardConfig(EchoConfigNode):
    _DEFAULTS: ClassVar[dict[str, Any]] = {
        "group_whitelist": [],
        "blocked_words": [],
        "need_different": True,
        "thresholds": {"Plain": 4, "Image": 3, "Face": 2},
        "echo_probability": 0.8,
        "ignore_command_messages": True,
        "command_prefixes": ["/", "!"],
        "action_timeout_seconds": 10.0,
        "max_pending_actions": 32,
        "follow": {},
        "interrupt": {},
        "ban": {},
    }

    group_whitelist: list[str]
    blocked_words: list[str]
    need_different: bool
    thresholds: dict[str, int]
    echo_probability: float
    ignore_command_messages: bool
    command_prefixes: list[str]
    action_timeout_seconds: float
    max_pending_actions: int
    follow: EchoFollowConfig
    interrupt: EchoInterruptConfig
    ban: EchoBanConfig

    def __init__(self, cfg: AstrBotConfig):
        super().__init__(cfg)
        thresholds = self.thresholds
        if not isinstance(thresholds, MutableMapping):
            logger.warning("[echo_guard.config] invalid thresholds; disabling detection")
            thresholds = {}
        self.supported_type = [
            key for key in thresholds if self.get_threshold(key) > 0
        ]
        self.window_sizes = {
            segment_type: self.get_threshold(segment_type)
            for segment_type in self.supported_type
        }

    def get_threshold(self, segment_type: str) -> int:
        thresholds = self.thresholds
        if not isinstance(thresholds, MutableMapping):
            return 0
        try:
            return max(0, int(thresholds.get(segment_type, 0)))
        except (TypeError, ValueError):
            return 0

    def should_echo(self) -> bool:
        try:
            probability = min(1.0, max(0.0, float(self.echo_probability)))
        except (TypeError, ValueError):
            probability = 0.0
        return probability > 0 and random.random() < probability

    def action_timeout(self) -> float:
        try:
            return min(60.0, max(0.1, float(self.action_timeout_seconds)))
        except (TypeError, ValueError):
            return 10.0

    def max_pending_actions_limit(self) -> int:
        try:
            return min(256, max(1, int(self.max_pending_actions)))
        except (TypeError, ValueError):
            return 32

    def weight_of(self, action: str) -> int:
        values = {
            "follow": self.follow.weight,
            "interrupt": self.interrupt.weight,
            "ban": self.ban.weight if self.ban.duration > 0 else 0,
        }
        try:
            return max(0, int(values[action]))
        except (KeyError, TypeError, ValueError):
            return 0

    def is_supported_type(self, segment_type: str) -> bool:
        return segment_type in self.supported_type

    def is_white_group(self, group_id: str) -> bool:
        groups = self.group_whitelist
        if not isinstance(groups, (list, tuple, set)):
            return False
        return str(group_id) in {str(item) for item in groups}
