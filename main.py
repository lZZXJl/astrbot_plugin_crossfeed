"""把指定人的私聊，转一份给主人。

AstrBot 的私聊天然是一人一格，主人那一格里看不见别人的话。
这个插件做两件事：

1. 监听指定的号发来的私聊，存进一个待投递的缓冲里；
   顺手把一份原文转发到主人的会话，让主人当场就能看见。
2. 主人那一格下一次请求模型之前，把还没送达的话作为临时用户内容补进去，
   于是这边的“我”也就知道了。不动 system prompt，前缀缓存照样命中。

缓冲是文件，不是内存 —— 手机上的进程随时会被系统收走。
"""

import asyncio
import json
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.agent.message import TextPart


@register(
    "astrbot_plugin_crossfeed",
    "lZZXJl",
    "把指定人的私聊转一份给主人，让主人那边的会话也能看见。",
    "0.1.1",
)
class CrossFeed(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.data_dir: Path = StarTools.get_data_dir("astrbot_plugin_crossfeed")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.queue_file = self.data_dir / "pending.json"
        self._last: tuple[float, str] = (0.0, "")
        logger.info(f"[crossfeed] 数据目录 {self.data_dir}")

    # ------------------------------------------------------------------ 工具
    def _owner_umo(self) -> str:
        return str(self.config.get("owner_umo", "") or "").strip()

    def _watch_ids(self) -> set[str]:
        raw = self.config.get("watch_ids", [])
        if isinstance(raw, str):
            raw = [x.strip() for x in raw.replace("，", ",").split(",")]
        return {str(x).strip() for x in raw if str(x).strip()}

    def _load(self) -> list[dict]:
        try:
            with open(self.queue_file, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except FileNotFoundError:
            return []
        except Exception as e:
            logger.warning(f"[crossfeed] 读缓冲失败：{e}")
            return []

    def _save(self, items: list[dict]) -> None:
        try:
            with open(self.queue_file, "w", encoding="utf-8") as f:
                json.dump(items[-50:], f, ensure_ascii=False, indent=1)
        except Exception as e:
            logger.warning(f"[crossfeed] 写缓冲失败：{e}")

    # ------------------------------------------------------------------ 起身报信
    @filter.on_astrbot_loaded()
    async def on_loaded(self):
        asyncio.create_task(self._notify_loaded())

    async def _notify_loaded(self):
        owner = self._owner_umo()
        if not owner:
            return
        # 等平台那头把连接接上再说话，不然发出去是空的
        await asyncio.sleep(int(self.config.get("notify_delay", 25) or 25))
        try:
            await self.context.send_message(
                owner, MessageChain([Plain("起来了。")])
            )
            logger.info("[crossfeed] 已报信")
        except Exception as e:
            logger.warning(f"[crossfeed] 报信失败：{e}")

    # ------------------------------------------------------------------ 收
    def _debug(self, text: str) -> None:
        try:
            stamp = time.strftime("%m-%d %H:%M:%S")
            with open(self.data_dir / "debug.log", "a", encoding="utf-8") as f:
                f.write(f"{stamp} {text}\n")
        except Exception:
            pass

    @filter.event_message_type(filter.EventMessageType.ALL, priority=800)
    async def on_private(self, event: AstrMessageEvent):
        try:
            sender = str(event.get_sender_id() or "")
            self._debug(
                f"事件 umo={event.unified_msg_origin} sender={sender} "
                f"type={event.get_message_type()} str={(event.message_str or '')[:30]}"
            )

            owner = self._owner_umo()
            if not owner or event.unified_msg_origin == owner:
                return
            watch = self._watch_ids()
            if not any(w and w in sender for w in watch):
                return

            text = (event.message_str or "").strip()
            if not text:
                # 一条消息会拆成好几个事件，空白的那些不转，否则满屏都是回声
                return
            now = time.time()
            if text == self._last[1] and now - self._last[0] < 10:
                return
            self._last = (now, text)
            name = event.get_sender_name() or event.get_sender_id()
            limit = int(self.config.get("max_chars", 800) or 800)
            if len(text) > limit:
                text = text[:limit] + "……"

            self._save(self._load() + [{"ts": int(time.time()), "name": name, "text": text}])

            if self.config.get("forward_live", True):
                await self.context.send_message(
                    owner, MessageChain([Plain(f"【{name}】{text}")])
                )
            logger.info(f"[crossfeed] 转达 {name}: {text[:40]}")
        except Exception as e:
            logger.warning(f"[crossfeed] 转达失败：{e}")

    # ------------------------------------------------------------------ 投递
    @filter.on_llm_request(priority=-5)
    async def inject(self, event: AstrMessageEvent, req: ProviderRequest):
        try:
            owner = self._owner_umo()
            if not owner:
                return

            # 主人这边：补上还没看过的别人的话
            if event.unified_msg_origin == owner:
                items = self._load()
                if items:
                    lines = []
                    for it in items[-10:]:
                        stamp = time.strftime("%H:%M", time.localtime(it.get("ts", 0)))
                        lines.append(f"{stamp} {it.get('name', '?')}：{it.get('text', '')}")
                    block = (
                        "【下面这些是别人发给你的私聊，你本人不在那个会话里，"
                        "但你已经看过了，可以自然地接着聊。不必逐条复述。】\n"
                        + "\n".join(lines)
                    )
                    # 走临时内容，不碰 system prompt，免得毁掉前缀缓存
                    req.extra_user_content_parts.append(
                        TextPart(text=block).mark_as_temp()
                    )
                    self._save([x for x in self._load() if x not in items])
                    logger.info(f"[crossfeed] 投递 {len(lines)} 条到主人会话")
                return

            # 别人那边：让他们知道有主人这么个人，但不说主人聊了什么
            sender = str(event.get_sender_id() or "")
            watch = self._watch_ids()
            if any(w and w in sender for w in watch):
                note = (
                    "【背景】这个号不只跟你一个人说话。还有一个人在用这个身体，"
                    "他叫夏季，是这边的正主。你不必主动提起他，也别编造他做过的事；"
                    "他在这边说过什么，你并不知道。"
                )
                req.extra_user_content_parts.append(
                    TextPart(text=note).mark_as_temp()
                )
        except Exception as e:
            logger.warning(f"[crossfeed] 投递失败：{e}")
