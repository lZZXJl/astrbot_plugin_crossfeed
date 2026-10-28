# 私聊转达 / astrbot_plugin_crossfeed

给 AstrBot 补一条路：**让一个会话里的话，能被另一个会话里的“它”看见。**

## 为什么需要它

AstrBot 的私聊天然是一人一格，各自有各自的上下文。
主人这一格里看不见别人的话，别人那一格里也不知道主人是谁。
“会话隔离（unique_session）”那个开关只管群聊，管不到两个不同的人之间的私聊。

## 它做两件事

### 一、把别人的私聊转给主人

- 监听 `watch_ids` 里那些号发来的私聊；
- 每一条存进待投递队列（`data/plugin_data/astrbot_plugin_crossfeed/pending.json`）；
- 主人下一次请求模型之前，把这些还没看过的话补进系统提示，送完即清。

一条消息在 QQ 那边会被拆成好几个事件（空白、图片、撤回各算一个）。
所以空白的不转，十秒内一模一样的话也只留一条。

### 二、让别人知道有主人这么个人

在 `watch_ids` 那些号的会话里，会补一段固定说明：
有这么一个人在用这个身体，叫夏季，是正主。

**主人的聊天内容不会过去。** 那边只知道“有这个人”，不知道他说了什么。

## 配置项

| 键 | 说明 | 默认 |
|---|---|---|
| `owner_umo` | 主人的会话地址，形如 `平台:消息类型:会话号` | `平台:消息类型:会话号` |
| `watch_ids` | 要转达的号 | `[]` |
| `forward_live` | 除了存队列，是否同时抄一份原文到主人会话 | `false` |
| `max_chars` | 单条最多转多少字 | `800` |
| `notify_delay` | 启动后等多少秒再报“起来了” | `25` |

## 附带的两个功能

- **起身报信**：AstrBot 加载完成（`on_astrbot_loaded`）后等 `notify_delay` 秒，往主人会话发一句“起来了”，确认它活着。
- **调试图**：每来一条事件都往 `debug.log` 写一行，含会话地址、发送者、消息类型、前 30 个字。
  排查“为什么收不到”时，先看这个文件。

## 文件在哪

```
data/plugins/astrbot_plugin_crossfeed/     # 代码
data/config/astrbot_plugin_crossfeed_config.json   # 配置
data/plugin_data/astrbot_plugin_crossfeed/  # 运行时数据
    ├── pending.json   # 待投递的别人的话
    └── debug.log      # 事件流水
```

## 坑

- **白名单**：AstrBot 的 `id_whitelist` 比的是**整个会话地址**，不是纯号。
  只写 `189147453` 是匹配不上的，要写 `DeepSeek.0:FriendMessage:189147453`。
  管理员不受这条限制，所以主人的号不写也能进——这一点最容易看漏。
- **必须真重启**：改完代码或配置，要在主页停止再启动，或者在系统里强制停止 App。
  点插件卡片的刷新有时只重扫目录，不换代码。
- **没权限时连调试都进不来**：白名单在事件管线的前段，插件在它后头；
  被白名单掐掉的消息，连这里的 `debug.log` 都不会留痕。

## 卸载

删掉 `data/plugins/astrbot_plugin_crossfeed` 整个目录即可。配置和数据目录可以留着，也可以一并删。

回滚：动手前的备份在 `/root/astrbot_backup/`。
