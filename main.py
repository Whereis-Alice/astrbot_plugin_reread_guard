from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.event.filter import EventMessageType
from astrbot.api.message_components import BaseMessageComponent, Plain
from astrbot.api.star import Context, Star

from .core.echo_ban import EchoBanHandler
from .core.echo_config import EchoGuardConfig
from .core.echo_engine import EchoGuardEngine
from .core.echo_state import EchoStateManager


class EchoGuardPlugin(Star):
    """独立发送复读消息、不会改变原事件结果的复读插件。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = EchoGuardConfig(config)
        self.state_mgr = EchoStateManager(self.cfg.window_sizes)
        self.engine = EchoGuardEngine(self.cfg)
        self.ban_handler = EchoBanHandler(self.cfg, context)
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._closed = False

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def echo_guard_handle(self, event: AstrMessageEvent) -> None:
        """观察群消息并独立发送复读动作，始终让事件继续流转。"""
        if self._closed:
            return
        try:
            self._observe(event)
        except Exception:  # noqa: BLE001 - observer failures must not stop AstrBot's event.
            # AstrBot 会在 handler 异常时停止事件；旁路功能必须 fail-open。
            logger.exception("[echo_guard] observation failed; leaving event untouched")

    def _observe(self, event: AstrMessageEvent) -> None:
        """仅完成同步判定和动作调度，不等待平台 I/O。"""
        sender_id = str(event.get_sender_id() or "")
        self_id = str(event.get_self_id() or "")
        if self_id and sender_id == self_id:
            return
        if event.is_at_or_wake_command or self._looks_like_command(event):
            return

        chain = event.get_messages()
        if len(chain) != 1:
            return
        seg = chain[0]
        seg_type = str(seg.type).split(".")[-1]
        if not self.cfg.is_supported_type(seg_type):
            return
        if isinstance(seg, Plain) and any(word and word in seg.text for word in self.cfg.blocked_words):
            return

        group_id = event.get_group_id()
        send_id = event.get_sender_id()
        if self.cfg.group_whitelist and not self.cfg.is_white_group(group_id):
            return

        state = self.state_mgr.get_state(f"{event.get_platform_id()}:{group_id}")
        # 此方法在首次 await 前完成，单一事件循环中不会与另一条消息交错更新。
        plan = self.engine.evaluate(state, seg_type, send_id, seg)

        if not plan:
            return
        if plan.action == "ban":
            self._schedule(self.ban_handler.handle(event, plan.repeat_count))
            return
        if plan.output_segment is None:
            return

        self._schedule(
            self._send_independent(event.unified_msg_origin, plan.output_segment)
        )

    def _schedule(self, coroutine: Coroutine[Any, Any, Any]) -> None:
        """安排独立动作，避免等待平台 I/O 阻塞当前事件流水线。"""
        if self._closed:
            coroutine.close()
            return
        if len(self._background_tasks) >= self.cfg.max_pending_actions_limit():
            coroutine.close()
            logger.warning("[echo_guard] pending action limit reached; dropping action")
            return
        task = asyncio.create_task(self._run_background(coroutine))
        self._background_tasks.add(task)
        task.add_done_callback(self._finish_task)

    async def _run_background(self, coroutine: Coroutine[Any, Any, Any]) -> None:
        """Apply the configured time limit to each independent action."""
        try:
            await asyncio.wait_for(coroutine, timeout=self.cfg.action_timeout())
        except TimeoutError:
            logger.warning("[echo_guard] independent action timed out")

    def _finish_task(self, task: asyncio.Task[Any]) -> None:
        self._background_tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:  # noqa: BLE001 - report background failures without propagation.
            logger.exception("[echo_guard] background action failed")

    async def _send_independent(
        self,
        session: str,
        segment: BaseMessageComponent,
    ) -> None:
        """通过会话主动发送，不写入当前事件结果。"""
        try:
            sent = await self.context.send_message(
                session,
                MessageChain([segment]),
            )
            if sent is False:
                logger.warning("[echo_guard] no matching platform for %s", session)
        except Exception as exc:  # noqa: BLE001 - platform failures must remain isolated.
            logger.warning("[echo_guard] failed to send echo message: %s", exc)

    def _looks_like_command(self, event: AstrMessageEvent) -> bool:
        if not self.cfg.ignore_command_messages:
            return False
        text = (getattr(event, "message_str", "") or "").strip()
        return any(text.startswith(prefix) for prefix in self.cfg.command_prefixes if prefix)

    async def terminate(self) -> None:
        """取消未完成的独立动作并清理内存状态。"""
        self._closed = True
        tasks = tuple(self._background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._background_tasks.clear()
        self.state_mgr.clear()
