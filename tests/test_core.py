import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT.parent / "_astrbot_src_check_20260818"))
sys.path.insert(0, str(ROOT.parent))

from astrbot.core.message.components import Face, Image, Plain
from astrbot_plugin_reread_guard.core.echo_config import EchoGuardConfig
from astrbot_plugin_reread_guard.core.echo_engine import EchoGuardEngine
from astrbot_plugin_reread_guard.core.echo_state import EchoStateManager
from astrbot_plugin_reread_guard.main import EchoGuardPlugin


def test_state_managers_are_isolated_and_clear():
    a = EchoStateManager({"Plain": 2})
    b = EchoStateManager({"Plain": 2})
    a.get_state("g").push_message("Plain", "u", "text:x")
    assert len(a.get_state("g").messages["Plain"]) == 1
    assert len(b.get_state("g").messages["Plain"]) == 0
    a.clear()
    assert len(a.get_state("g").messages["Plain"]) == 0


def test_fingerprints_are_stable():
    assert EchoGuardEngine.make_fingerprint(Plain("x")) == "text:x"
    assert EchoGuardEngine.make_fingerprint(Face(id="1")) == "face:1"
    assert EchoGuardEngine.make_fingerprint(Image(file="f.png")) == "image:f.png"
    assert EchoGuardEngine.make_fingerprint(Image(file=None)) is None


class _Context:
    def __init__(self):
        self.sent = []

    async def send_message(self, session, chain):
        self.sent.append((session, chain))
        return True


class _Event:
    def __init__(self, sender_id, text="echo", command=False):
        self._sender_id = sender_id
        self._text = text
        self.segment = Plain(text)
        self.is_at_or_wake_command = command
        self.message_str = text
        self.unified_msg_origin = "onebot:group:123"
        self._has_send_oper = False
        self._result = None
        self.stopped = False

    def get_sender_id(self):
        return self._sender_id

    def get_self_id(self):
        return "bot"

    def get_messages(self):
        return [self.segment]

    def get_group_id(self):
        return "123"

    def get_platform_id(self):
        return "onebot"

    def stop_event(self):
        self.stopped = True


def _plugin(context):
    cfg = EchoGuardConfig(
        {
            "group_whitelist": [],
            "blocked_words": [],
            "need_different": True,
            "thresholds": {"Plain": 2, "Image": 2, "Face": 2},
            "echo_probability": 1.0,
            "ignore_command_messages": True,
            "command_prefixes": ["/", "!"],
            "follow": {"weight": 1},
            "interrupt": {"weight": 0, "text": "打断！"},
            "ban": {"weight": 0, "duration": 0, "prompt": ""},
        }
    )
    plugin = object.__new__(EchoGuardPlugin)
    plugin.context = context
    plugin.cfg = cfg
    plugin.state_mgr = EchoStateManager(cfg.window_sizes)
    plugin.engine = EchoGuardEngine(cfg)
    plugin._background_tasks = set()
    plugin._closed = False
    return plugin


def test_reread_uses_independent_send_without_mutating_event():
    context = _Context()
    plugin = _plugin(context)
    assert plugin.cfg.get_threshold("Plain") == 2
    assert plugin.cfg.weight_of("follow") == 1
    first = _Event("user-a")
    second = _Event("user-b")

    async def run_handler():
        await plugin.echo_guard_handle(first)
        await plugin.echo_guard_handle(second)
        await asyncio.gather(*plugin._background_tasks)

    asyncio.run(run_handler())

    assert len(context.sent) == 1
    assert context.sent[0][0] == second.unified_msg_origin
    assert context.sent[0][1].chain[0].text == "echo"
    assert context.sent[0][1].chain[0] is not second.get_messages()[0]
    assert second._has_send_oper is False
    assert second._result is None
    assert second.stopped is False


class _SlowContext:
    async def send_message(self, session, chain):
        await asyncio.Event().wait()


def test_slow_independent_send_times_out_without_touching_event():
    plugin = _plugin(_SlowContext())
    plugin.cfg.action_timeout_seconds = 0.01
    first = _Event("user-a")
    second = _Event("user-b")

    async def run_handler():
        await plugin.echo_guard_handle(first)
        await plugin.echo_guard_handle(second)
        await asyncio.gather(*plugin._background_tasks)
        await asyncio.sleep(0)

    asyncio.run(run_handler())

    assert plugin._background_tasks == set()
    assert second._has_send_oper is False
    assert second._result is None
    assert second.stopped is False


def test_command_message_is_ignored_before_it_changes_reread_state():
    context = _Context()
    plugin = _plugin(context)
    command = _Event("user-a", text="/echo", command=True)

    asyncio.run(plugin.echo_guard_handle(command))

    assert context.sent == []
    assert plugin.state_mgr._group_states == {}


def test_observer_failure_does_not_escape_to_astrbot():
    context = _Context()
    plugin = _plugin(context)
    broken = _Event("user-a")

    def raise_on_messages():
        raise RuntimeError("bad adapter payload")

    broken.get_messages = raise_on_messages
    asyncio.run(plugin.echo_guard_handle(broken))

    assert broken._result is None
    assert broken.stopped is False

