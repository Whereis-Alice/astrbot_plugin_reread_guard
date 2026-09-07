from __future__ import annotations

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.star import Context

from .echo_config import EchoGuardConfig


class _SafeFormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class EchoBanHandler:
    def __init__(self, cfg: EchoGuardConfig, context: Context):
        self.cfg = cfg
        self.context = context

    async def handle(self, event: AstrMessageEvent, repeat_count: int) -> bool:
        bot = getattr(event, "bot", None)
        if bot is None or not hasattr(bot, "set_group_ban"):
            logger.warning("[echo_guard] current adapter does not support group bans")
            return False
        group_id = event.get_group_id()
        sender_id = event.get_sender_id()
        try:
            await bot.set_group_ban(
                group_id=int(group_id),
                user_id=int(sender_id),
                duration=self.cfg.ban.duration,
            )
        except Exception as exc:  # noqa: BLE001 - adapter errors must not affect the source event.
            logger.warning(
                "[echo_guard] failed to ban user %s in group %s: %s",
                sender_id,
                group_id,
                exc,
            )
            return False
        prompt = self._format_prompt(event, repeat_count)
        if prompt:
            try:
                sent = await self.context.send_message(
                    event.unified_msg_origin,
                    MessageChain().message(prompt),
                )
                if sent is False:
                    logger.warning("[echo_guard] no matching platform for ban prompt")
            except Exception as exc:  # noqa: BLE001 - prompt failures must not affect the source event.
                logger.warning("[echo_guard] failed to send ban prompt: %s", exc)
        # 禁言动作也不终止事件传播，避免吞掉命令或 LLM 回复。
        return True

    def _format_prompt(self, event: AstrMessageEvent, repeat_count: int) -> str:
        prompt = (self.cfg.ban.prompt or "").strip()
        if not prompt:
            return ""
        values = _SafeFormatDict(
            user_name=event.get_sender_name(),
            user_id=event.get_sender_id(),
            group_id=event.get_group_id(),
            ban_duration=str(self.cfg.ban.duration),
            repeat_count=str(repeat_count),
        )
        try:
            return prompt.format_map(values)
        except Exception as exc:  # noqa: BLE001 - invalid custom templates fall back to raw text.
            logger.warning("[echo_guard] failed to format ban prompt: %s", exc)
            return prompt
