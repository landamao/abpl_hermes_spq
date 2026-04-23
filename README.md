# Hermes Agent 适配器插件

实现 **AstrBot** 与 **Hermes Agent** 的双向通信，让 Hermes 能够接收 QQ 群消息、执行 AstrBot 的所有插件指令，并作为 **LLM 工具**供 AstrBot 本身调用。

## ✨ 功能特性

- 🔄 **双向 WebSocket 通信**  
  通过 WebSocket 与 Hermes 保持长连接，实时转发消息和接收指令（支持自动重连及指数退避）。

- 📨 **智能消息转发**  
  监听 QQ 群消息，根据关键词、@机器人、白名单等规则过滤后，以 **OneBot v11 标准格式** 转发给 Hermes。

- 🎯 **指令代理与 HTTP API**  
  接收 Hermes 的 API 请求，动态执行 AstrBot 中已注册的任意插件指令，并支持将执行结果自动回复到 QQ 群。

- 🤖 **LLM 工具集成**  
  提供 `hermes_agent`、`hermes_status`、`hermes_list_commands` 三个 LLM 工具，让 AstrBot 自身的 AI 可以调用 Hermes 完成复杂任务或查询状态。

- 🔒 **完善的安全控制**  
  - 群/用户白名单  
  - 指令执行黑白名单  
  - HTTP API Bearer Token 认证  
  - WebSocket 连接 Access Token  
  - `/approve` / `/deny` 命令权限控制  

- 📊 **状态监控与运维**  
  - 健康检查、统计信息、指令列表等 HTTP 端点  
  - 用户侧指令 `/hermes status`、`/hermes test`  

- 🚀 **零依赖其他插件**  
  纯独立实现，不需要 HTTP Platform 或 LLM Executor 等外部插件。

## 🏗️ 架构

```
┌──────────┐   OneBot API   ┌──────────────────────────────────────────┐
│  NapCat  │ ─────────────→ │              AstrBot                     │
└──────────┘                │                                          │
                            │  ┌─────────────────────────────────────┐ │
                            │  │       Hermes 适配器插件              │ │
                            │  │  ┌─────────────────────────────┐    │ │
                            │  │  │ ① 群消息监听器                │   │ │
                            │  │  │    - 关键词/@触发             │   │ │
                            │  │  │    - 白名单过滤               │   │ │
                            │  │  └─────────────┬───────────────┘    │ │
                            │  │                │ WebSocket          │ │
                            │  │  ┌─────────────▼───────────────┐    │ │
                            │  │  │ WebSocket 客户端             │    │ │
                            │  │  │ (连接 Hermes)                │    │ │
                            │  │  └─────────────┬───────────────┘    │ │
                            │  │                │                    │ │
                            │  │  ┌─────────────▼───────────────┐    │ │
                            │  │  │ HTTP 服务器 (:8567)          │    │ │
                            │  │  │ - 执行指令 API               │    │ │
                            │  │  │ - 发送消息 API               │    │ │
                            │  │  │ - 查询指令列表               │    │ │
                            │  │  └─────────────┬───────────────┘    │ │
                            │  │                │                    │ │
                            │  │  ┌─────────────▼───────────────┐    │ │
                            │  │  │ 指令执行引擎                  │   │ │
                            │  │  │ - 动态调用 AstrBot 处理器     │   │ │
                            │  │  │ - 模拟消息事件                │   │ │
                            │  │  └─────────────────────────────┘    │ │
                            │  │                                     │ │
                            │  │  ┌─────────────────────────────┐    │ │
                            │  │  │ LLM 工具集                   │    │ │
                            │  │  │ - hermes_agent               │   │ │
                            │  │  │ - hermes_status              │   │ │
                            │  │  │ - hermes_list_commands       │   │ │
                            │  │  └─────────────────────────────┘    │ │
                            │  └─────────────────────────────────────┘ │
                            └──────────────────────────────────────────┘
                                                   ↕ WebSocket / HTTP
                                            ┌─────────────────┐
                                            │   Hermes Agent  │
                                            │  (反向 WS 服务)  │
                                            └─────────────────┘
```

## 📦 安装

### 1. 复制插件到 AstrBot

```bash
cp -r hermes_adapter /root/AstrBot/data/plugins/
```

### 2. 安装 Python 依赖（通常已满足）

```bash
pip install aiohttp>=3.8.0 websockets>=11.0
```

### 3. 重启 AstrBot

```bash
systemctl restart astrbot   # 或使用你的启动方式
```

### 4. 配置 Hermes 端

确保 Hermes 启动了**反向 WebSocket 服务器**（默认 `ws://0.0.0.0:6701`），并且该服务能够接受连接。

## ⚙️ 配置项

在 AstrBot WebUI 或 `data/config.yaml` 中配置（插件名：`hermes_adapter`）：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `onebot_api_url` | string | `http://127.0.0.1:5700` | NapCat 的 HTTP API 地址，用于发送 QQ 消息 |
| `hermes_ws_url` | string | `ws://127.0.0.1:6701` | Hermes 反向 WebSocket 地址 |
| `hermes_access_token` | string | `""` | 连接 Hermes 时的 Bearer Token（留空不认证） |
| `enable_http_server` | bool | `true` | 是否启动 HTTP 服务器（接收 Hermes 指令请求） |
| `http_server_port` | int | `8567` | HTTP 服务器监听端口 |
| `http_server_token` | string | `""` | HTTP 请求认证 Token（留空不验证） |
| `trigger_keywords` | list | `["纳西妲","hermes","Hermes"]` | 消息包含任一关键词则转发 |
| `trigger_at_bot` | bool | `true` | 消息 @机器人 时转发 |
| `allowed_groups` | list | `[]` | 允许转发的群号列表（空=所有群） |
| `allowed_users` | list | `[]` | 允许转发的用户 QQ 列表（空=所有用户） |
| `forward_all_messages` | bool | `false` | **危险**：转发所有群消息（会消耗大量 token） |
| `command_whitelist` | list | `[]` | 允许 Hermes 执行的指令白名单（空=所有） |
| `command_blacklist` | list | `["重启","关机","更新"]` | 禁止 Hermes 执行的指令黑名单 |
| `max_message_length` | int | `2000` | 转发消息的最大长度（超出截断） |
| `approve_deny_enabled` | bool | `true` | 是否启用 `/approve` 和 `/deny` 特殊指令 |
| `approve_deny_users` | list | `[]` | 允许使用 `/approve` `/deny` 的用户 QQ 号 |

## 📡 消息转发（AstrBot → Hermes）

### 触发条件

满足**任一**条件即转发：

1. 消息文本包含 `trigger_keywords` 中的任意关键词（不区分大小写）  
2. 消息中 @ 了机器人（且 `trigger_at_bot = true`）  
3. `forward_all_messages = true`（转发所有消息）  

> 另外，当消息以 `/approve` 或 `/deny` 开头且用户在白名单中时，也会触发转发（用于 Hermes 审批流程）。

### 转发格式（OneBot v11 标准）

```json
{
  "time": 1703123456,
  "self_id": "astrbot",
  "post_type": "message",
  "message_type": "group",
  "sub_type": "normal",
  "message_id": 1234567890,
  "group_id": 123456789,
  "user_id": 987654321,
  "message": [
    {
      "type": "text",
      "data": { "text": "纳西妲 你好" }
    }
  ],
  "raw_message": "纳西妲 你好",
  "font": 0,
  "sender": {
    "user_id": 987654321,
    "nickname": "小明",
    "card": "小明"
  }
}
```

> 注意：为了兼容 OneBot 标准，原消息中的图片、At、Json 等段会被保留，仅 Plain 文本段会被替换为过滤后的内容。

## 🎮 指令执行（Hermes → AstrBot）

Hermes 通过调用适配器的 HTTP API 来执行 AstrBot 指令。

### 基础 URL

```
http://<AstrBot主机>:8567
```

### 认证（可选）

若配置了 `http_server_token`，请求需携带 `Authorization: Bearer <token>`。

### API 端点详情

#### 1. 执行指令

`POST /api/execute`

**请求体：**

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `command` | string | 是 | 指令名称（例如 `点歌`，不用加 `/`） |
| `args` | string | 否 | 指令参数（例如 `周杰伦 晴天`） |
| `group_id` | string | 推荐 | 目标群号（提供后指令执行结果会直接发到该群） |
| `user_id` | string | 否 | 模拟的用户 ID（默认 `hermes_agent`） |
| `user_name` | string | 否 | 模拟的用户名（默认 `Hermes Agent`） |

**响应示例：**

```json
{
  "success": true,
  "command": "点歌",
  "args": "周杰伦 晴天",
  "result": {
    "texts": ["播放链接...", "歌词摘要..."],
    "images": ["https://...jpg"],
    "sent_messages": 1
  }
}
```

#### 2. 主动发送消息

`POST /api/send`

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `group_id` | int | 二选一 | 目标群号 |
| `user_id` | int | 二选一 | 目标用户 QQ（私聊） |
| `message` | string | 是 | 消息内容 |

#### 3. 获取指令列表（为 Hermes 优化）

`GET /api/commands/for_hermes`

返回所有可用指令及其分类、别名、描述，便于 Hermes 构建自己的工具列表。

#### 4. 获取单个指令详情

`GET /api/command/{command_name}`

#### 5. 健康检查

`GET /api/health`

返回 WebSocket 连接状态、缓存群数量等。

#### 6. 统计信息（需认证）

`GET /api/stats`

## 🤖 LLM 工具（供 AstrBot 自身 AI 使用）

当 AstrBot 启用了 LLM（如 ChatGPT、DeepSeek 等）时，AI 可以主动调用以下工具。

### 1. `hermes_agent`

**描述**：调用 Hermes Agent 执行任务或命令。Hermes 是一个强大的 AI Agent，可以完成复杂任务、查询信息、调用其他插件功能等。

**参数**：
- `task` (string, required) – 任务描述，详细说明需要完成什么  
- `command` (string, optional) – 具体要执行的 AstrBot 指令（如 `点歌`）  
- `args` (string, optional) – 指令参数

**行为**：
- 如果提供了 `command`，则直接执行该 AstrBot 指令，并将结果返回给 AI。
- 如果没有提供 `command`，则将 `task` 包装成一条消息（自动加上触发关键词前缀），通过 WebSocket 发送给 Hermes，让 Hermes 自主处理并回复。

**示例（AI 调用）**：
```json
{
  "task": "播放周杰伦的晴天",
  "command": "点歌",
  "args": "周杰伦 晴天"
}
```

### 2. `hermes_status`

**描述**：查询 Hermes Agent 和适配器的运行状态，包括 WebSocket 连接、运行时长、统计信息等。

**参数**：无

**返回**：多行文本状态信息。

### 3. `hermes_list_commands`

**描述**：列出所有可通过 Hermes 执行的 AstrBot 指令，支持按分类过滤。

**参数**：
- `category` (string, optional) – 分类名称（如 `音乐`、`宠物`、`好感度`、`群管理`、`系统` 等），不传则返回所有分类。

**返回**：按分类组织的指令列表，包含指令名、别名、描述、是否需要管理员权限。

## 💬 用户指令（在 QQ 群中发送）

插件提供了两个简单的状态查询指令：

| 指令 | 说明 | 示例 |
|------|------|------|
| `/hermes status` | 查看适配器运行状态 | `/hermes status` |
| `/hermes test` | 测试 WebSocket 连接 | `/hermes test` |

> 旧版用户指令 `/hermes execute` 由于稳定性原因暂未启用。

## 🛡️ 安全建议

1. **设置 `http_server_token`**：防止未授权调用指令执行 API。  
2. **设置 `hermes_access_token`**：防止未经认证的客户端连接 WebSocket。  
3. **配置 `allowed_groups` 和 `allowed_users`**：限制消息转发范围，避免隐私泄露。  
4. **使用 `command_blacklist`**：将敏感指令（如 `重启`、`更新`、`关机`）加入黑名单。  
5. **不要开启 `forward_all_messages`**：除非你真的需要将所有群消息转发给 Hermes。  
6. **`/approve` 和 `/deny` 权限**：通过 `approve_deny_users` 严格授权。

## 🔧 Hermes 端配置示例

### 启动 Hermes 反向 WebSocket 服务

```bash
hermes server --ws-reverse --port 6701
```

或在配置文件中：

```yaml
websocket:
  reverse:
    enabled: true
    port: 6701
    access_token: "your_token"   # 与插件中的 hermes_access_token 保持一致
```

### Hermes 接收消息并调用 AstrBot API 的伪代码

```python
async def on_qq_message(message):
    text = message["raw_message"]
    group_id = message["group_id"]
    
    # 提取指令（示例：将文本作为一个指令执行）
    async with aiohttp.ClientSession() as session:
        resp = await session.post(
            "http://localhost:8567/api/execute",
            json={
                "command": text.split()[0],   # 简单拆分
                "args": " ".join(text.split()[1:]),
                "group_id": group_id
            },
            headers={"Authorization": "Bearer your_http_token"}
        )
        result = await resp.json()
        # 可将 result 中的文本发回 QQ 或记录
```

## ❓ 常见问题

### Q1：插件启动后提示 WebSocket 连接失败？

- 检查 Hermes 是否已启动反向 WebSocket 服务，且端口与 `hermes_ws_url` 一致。  
- 检查防火墙。  
- 若配置了 `hermes_access_token`，确保 Hermes 端也要求相同的 token。

### Q2：执行指令返回 `未找到指令`？

- 确保指令名称正确（不要带 `/` 前缀）。  
- 使用 `GET /api/commands/for_hermes` 查看实际可用指令名和别名。  
- 如果指令来自某个未激活的插件，请先激活该插件。

### Q3：消息转发正常，但 Hermes 执行指令后收不到结果？

- 插件会在执行指令时将结果**自动通过 OneBot API 发送到原群**（前提是请求中提供了 `group_id`）。  
- 如果 Hermes 需要捕获结果进行进一步处理，可以从 HTTP `/api/execute` 的响应中直接获取 `result` 字段。

### Q4：插件是否依赖 HTTP Platform 或 LLM Executor？

**不依赖**。本插件独立实现所有功能，只需要 AstrBot 核心和 aiocqhttp 平台支持。

### Q5：如何让 AI（AstrBot 内置 LLM）使用 Hermes？

在 AstrBot 的 LLM 配置中启用“函数调用/工具”，插件会自动注册以下工具：
- `hermes_agent`
- `hermes_status`
- `hermes_list_commands`

AI 决策后会自动调用它们。

### Q6：`/approve` 和 `/deny` 是什么？

这两个是 Hermes 生态中常用的审批指令。当启用 `approve_deny_enabled` 后，用户发送 `/approve <内容>` 或 `/deny <内容>` 时，会触发转发给 Hermes（同时添加触发关键词作为前缀），通常用于人工介入 Hermes 的决策流程。

## 📝 版本历史

### v3.0 (当前)
- ✨ 新增三个 LLM 工具，AstrBot 自身 AI 可直接调用 Hermes  
- ✨ 新增 `/approve`/`/deny` 特殊指令支持及权限控制  
- ✨ 完善消息去重机制，避免同一消息重复转发  
- 🐛 修复长消息截断与 ID 重复问题  
- 📝 优化 HTTP API 稳定性与日志  

### v2.0
- 完全重写为 WebSocket 版本，移除对 HTTP Platform 的依赖  
- 新增指令缓存、别名解析、自动重连  
- 新增 `/api/commands/for_hermes` 端点  
- 支持 OneBot v11 标准消息格式  

### v1.0 (已废弃)
- 基于 HTTP webhook 的旧版实现  

## 📄 许可证

遵循 AstrBot 插件生态的许可协议。

## 👤 作者

懒大猫

## 🔗 相关链接

- [Hermes Agent GitHub](https://github.com/NousResearch/hermes-agent)  
- [Hermes QQ OneBot 平台适配器](https://github.com/chrysoljq/hermes_qq_onebot)

---

**如果遇到问题，欢迎提交 Issue 或联系作者。**