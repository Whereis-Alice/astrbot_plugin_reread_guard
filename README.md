# 复读守护（EchoGuard）

![复读守护 Logo](logo.png)

一个面向 AstrBot 群聊的轻量复读插件。它只观察消息，在达到阈值后通过独立会话发送复读动作，**不会写入当前事件结果，也不会调用 `stop_event()`**。因此同一条消息同时触发命令、LLM 或其它插件时，这些功能仍会正常执行。

## 功能

- 文本、图片、QQ 表情分别设置复读阈值
- 跟随复读、打断文本、禁言三种动作，可分别设置权重
- 可要求连续消息来自不同用户
- 群白名单与文本屏蔽词
- 默认忽略 `/`、`!` 开头的命令消息，避免对命令本身刷屏
- 独立的群状态与内容指纹，复读成功后自动清理窗口
- 独立动作具备超时和队列上限，平台异常时不会积压机器人任务
- 插件不创建自己的数据库；检测状态仅保存在内存中，重载插件后自动清空

## 安装

在 AstrBot 插件市场搜索 `astrbot_plugin_reread_guard`，或将本目录复制到 AstrBot 的 `data/plugins/` 后重载插件。

要求 AstrBot `>=4.16,<5`。插件无额外 Python 依赖。

## 配置

安装后打开 AstrBot 的插件配置面板：

| 配置项 | 默认值 | 说明 |
| --- | ---: | --- |
| `thresholds.Plain` | `4` | 连续 4 条相同文本后进入判定 |
| `thresholds.Image` | `3` | 连续 3 条相同图片后进入判定 |
| `thresholds.Face` | `2` | 连续 2 个相同表情后进入判定 |
| `echo_probability` | `0.8` | 达到阈值后实际响应的概率（0 到 1） |
| `need_different` | `true` | 是否要求相邻消息来自不同用户 |
| `ignore_command_messages` | `true` | 是否忽略命令样式消息 |
| `command_prefixes` | `[/, !]` | 被视为命令的前缀 |
| `action_timeout_seconds` | `10` | 单次复读或禁言动作的最长执行时间 |
| `max_pending_actions` | `32` | 最多允许同时等待的独立动作数；超出时丢弃新动作 |
| `group_whitelist` | `[]` | 留空启用全部群；填写群号后只在这些群启用 |
| `blocked_words` | `[]` | 文本包含任一词时不参与复读 |
| `follow.weight` | `90` | 跟随动作权重 |
| `interrupt.weight` | `5` | 打断动作权重 |
| `interrupt.text` | `打断！` | 打断动作发送的文本 |
| `ban.weight` | `5` | 禁言动作权重；设为 0 关闭 |
| `ban.duration` | `60` | 禁言秒数；设为 0 关闭禁言 |
| `ban.prompt` | `{user_name}复读过头了，先禁言{ban_duration}秒` | 禁言成功后的提示；支持 `{user_name}`、`{user_id}`、`{group_id}`、`{ban_duration}`、`{repeat_count}` |

动作概率 = 动作权重 ÷ 启用动作权重总和。所有动作权重为 0 时不会发送任何复读动作。

## 为什么不会吞掉 LLM 或命令？

复读检测运行在群消息处理阶段，但只更新自己的内存状态。需要发送时调用 AstrBot 的 `Context.send_message` 向会话主动发消息，不使用 `yield event.chain_result(...)`，也不修改事件结果，更不会终止事件传播。AstrBot 后续仍可按原流程执行命令和 LLM。

命令样式消息（默认以 `/` 或 `!` 开头）会直接跳过复读检测。对于未被前缀识别、但由其它插件处理的消息，复读仍通过独立会话发送，不会覆盖命令或 LLM 的事件结果。若你的平台使用其它前缀，可在 `command_prefixes` 中添加。

## 故障排查

- **没有复读**：检查群白名单、阈值、`echo_probability` 和动作权重；图片判等依赖平台提供的 `file`、`url` 或 `path`。
- **禁言无效**：当前平台适配器需要提供 `set_group_ban`，并且机器人要有群管理权限。
- **提示没有发出**：`Context.send_message` 需要平台支持按会话主动发送；QQ 官方等不支持该接口的平台只能执行检测，不会发送独立复读提示。
- **仍看到命令消息被复读**：把平台命令前缀加入 `command_prefixes`，或关闭 `ignore_command_messages` 后自行控制。
- **重载后计数消失**：这是预期行为，状态不落库，不会保存用户消息内容。
- **发送失败后没有立即重试**：为避免重复刷屏，动作在判定时只占用一次窗口；平台失败会记录日志，下一轮新的连续消息才会重新判定。

## 隐私与限制

插件只在内存中保存每个群最近几条消息的发送者 ID 和内容指纹，不创建自己的数据库。它只处理单段文本、图片或表情消息；多段消息会忽略。请合理设置阈值，避免群聊刷屏。

复读消息通过 AstrBot 的会话发送接口发出。若 AstrBot 启用了 `group_message_history_enable`，AstrBot 可能按自身规则将这条机器人消息写入群消息历史；这是 AstrBot 的全局历史功能，不是 EchoGuard 的独立存储。需要避免保留时，请在 AstrBot 中关闭该群历史设置。

## 许可证

MIT License。欢迎提交 Issue 和 Pull Request。

## 来源与致谢

本项目基于 [Zhalslar/astrbot_plugin_reread](https://github.com/Zhalslar/astrbot_plugin_reread) 的 MIT 授权版本重新实现，并保留其版权声明。EchoGuard 重写了事件发送路径、状态管理和公开文档，以解决复读结果覆盖 LLM 或命令结果的问题。

