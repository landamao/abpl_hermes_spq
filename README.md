# Hermes Agent 适配器插件

实现 AstrBot 与 [Hermes Agent](https://github.com/landamao/abpl_hermes_spq) 的双向通信，让 Hermes 能够接收 QQ 群消息、执行 AstrBot 的所有插件指令。

## ✨ 功能特性

- 🔄 **双向 WebSocket 通信**：通过 WebSocket 与 Hermes 保持长连接，实时转发消息和接收指令
- 📨 **消息转发**：监听 QQ 群消息，根据关键词、@机器人等规则过滤后转发给 Hermes
- 🎯 **指令代理**：接收 Hermes 的 API 请求，动态执行 AstrBot 中已注册的任意插件指令
- 🔒 **安全控制**：支持群/用户白名单、指令黑白名单、HTTP Token 认证
- 📊 **状态监控**：提供 HTTP API 查看插件状态、缓存指令列表、统计信息
- 🚀 **零依赖其他插件**：纯独立实现，不依赖 HTTP Platform 或 LLM Executor

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
                            │  └─────────────────────────────────────┘ │
                            └──────────────────────────────────────────┘
                                                   ↕ WebSocket / HTTP
                                            ┌─────────────────┐
                                            │   Hermes Agent  │
                                            │  (反向 WS 服务)  │
                                            └─────────────────┘
```

## 📦 安装

### 1. 复制插件

```bash
# 将插件目录复制到 AstrBot 插件目录
cp -r hermes_adapter /root/AstrBot/data/plugins/
```

### 2. 安装 Python 依赖

插件依赖 `aiohttp` 和 `websockets`，通常 AstrBot 已自带。若缺失，可手动安装：

```bash
pip install aiohttp>=3.8.0 websockets>=11.0
```

### 3. 重启 AstrBot

```bash
# 重启 AstrBot 服务
systemctl restart astrbot   # 或使用你的启动方式
```

### 4. 配置 Hermes 端

确保 Hermes 启动了**反向 WebSocket 服务器**（默认 `ws://0.0.0.0:6701`），并接受连接。

## ⚙️ 配置项

在 AstrBot WebUI 或 `data/config.yaml` 中配置以下选项（插件名称：`hermes_adapter`）：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `onebot_api_url` | string | `http://127.0.0.1:5700` | NapCat 的 HTTP API 地址，用于发送消息 |
| `hermes_ws_url` | string | `ws://127.0.0.1:6701` | Hermes 反向 WebSocket 地址 |
| `hermes_access_token` | string | `""` | 连接 Hermes 的 Bearer Token，为空表示不认证 |
| `enable_http_server` | bool | `true` | 是否启动 HTTP 服务器（接收 Hermes 指令请求） |
| `http_server_port` | int | `8567` | HTTP 服务器监听端口 |
| `http_server_token` | string | `""` | HTTP 请求认证 Token（Bearer），为空不验证 |
| `trigger_keywords` | list | `["纳西妲", "hermes", "Hermes"]` | 消息包含这些关键词时触发转发 |
| `trigger_at_bot` | bool | `true` | 消息 @机器人 时触发转发 |
| `allowed_groups` | list | `[]` | 允许转发的群号列表，空表示所有群 |
| `allowed_users` | list | `[]` | 允许转发的用户 QQ 列表，空表示所有用户 |
| `forward_all_messages` | bool | `false` | 是否转发所有消息（慎用，会消耗大量 token） |
| `command_whitelist` | list | `[]` | 允许 Hermes 执行的指令白名单，空表示全部 |
| `command_blacklist` | list | `["重启", "关机", "更新"]` | 禁止 Hermes 执行的指令黑名单 |
| `max_message_length` | int | `2000` | 转发消息的最大长度，超出截断 |
| `approve_deny_enabled` | bool | `true` | 是否启用 `/approve` 和 `/deny` 特殊指令 |
| `approve_deny_users` | list | `[]` | 允许使用 `/approve` `/deny` 的用户 QQ 号 |

## 📡 消息转发（AstrBot → Hermes）

### 触发条件

当群消息满足**任一**条件时，适配器会将消息以 **OneBot v11 标准格式**通过 WebSocket 发送给 Hermes：

1. 消息文本包含 `trigger_keywords` 中的任意关键词（不区分大小写）
2. 消息中 @ 了机器人（且 `trigger_at_bot = true`）
3. `forward_all_messages = true`（转发所有消息）

### 转发格式

```json
{
  "time": 1703123456,
  "self_id": "astrbot",
  "post_type": "message",
  "message_type": "group",
  "sub_type": "normal",
  "message_id": "1234567890",
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

Hermes 端需要实现**反向 WebSocket 服务**来接收这些消息。

## 🎮 指令执行（Hermes → AstrBot）

Hermes 可以通过调用适配器提供的 HTTP API 来执行任意 AstrBot 指令（如点歌、查天气等）。

### 基础 URL

```
http://<AstrBot主机>:8567
```

### 认证

如果配置了 `http_server_token`，所有请求需要在 `Authorization` 头中携带 Bearer Token：

```
Authorization: Bearer your_token_here
```

### API 端点

#### 1. 执行指令

```
POST /api/execute
```

**请求体：**

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `command` | string | 是 | 指令名称（如 `点歌`，不需要 `/` 前缀） |
| `args` | string | 否 | 指令参数（如 `周杰伦 晴天`） |
| `group_id` | string | 推荐 | 目标群号（用于上下文和发送结果） |
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

```
POST /api/send
```

**请求体：**

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `group_id` | int | 二选一 | 目标群号 |
| `user_id` | int | 二选一 | 目标用户 QQ（私聊） |
| `message` | string | 是 | 消息内容 |

#### 3. 获取指令列表（为 Hermes 优化）

```
GET /api/commands/for_hermes
```

返回所有可用指令及其分类、别名、描述，便于 Hermes 构建工具列表。

#### 4. 获取单个指令详情

```
GET /api/command/{command_name}
```

#### 5. 健康检查

```
GET /api/health
```

返回 WebSocket 连接状态、缓存群数量等。

#### 6. 统计信息

```
GET /api/stats
```

需要认证。

## 💬 用户指令（在 QQ 中发送）

插件本身提供了几个管理指令，需在群内发送：

| 指令 | 说明 | 示例 |
|------|------|------|
| `/hermes status` | 查看适配器运行状态 | `/hermes status` |
| `/hermes test` | 测试 WebSocket 连接 | `/hermes test` |

（旧版的 `/hermes execute` 已注释，暂不提供）

## 🔧 Hermes 端配置示例

### 启动 Hermes 反向 WebSocket 服务

```bash
hermes server --ws-reverse --port 6701
```

或通过配置文件：

```yaml
# hermes_config.yaml
websocket:
  reverse:
    enabled: true
    port: 6701
    access_token: ""   # 可选，与插件中的 hermes_access_token 对应
```

### 处理接收到的消息

Hermes 收到 OneBot 格式的消息后，可以调用 AstrBot 的 HTTP API 执行指令：

```python
# 伪代码示例
async def on_qq_message(message):
    text = message["raw_message"]
    group_id = message["group_id"]
    user_id = message["user_id"]
    
    # 调用 AstrBot 执行指令
    async with aiohttp.ClientSession() as session:
        resp = await session.post(
            "http://localhost:8567/api/execute",
            json={
                "command": "点歌",
                "args": text,
                "group_id": group_id,
                "user_id": user_id
            },
            headers={"Authorization": "Bearer your_token"}
        )
        result = await resp.json()
        # result["result"]["texts"] 即为执行结果
```

## 🛡️ 安全建议

1. **设置 `http_server_token`**：防止外部非法调用指令执行 API。
2. **设置 `hermes_access_token`**：防止未授权的客户端连接到 WebSocket。
3. **使用白名单**：通过 `allowed_groups` 和 `allowed_users` 限制转发范围。
4. **配置指令黑名单**：将危险指令（如 `重启`、`更新`）加入 `command_blacklist`，禁止 Hermes 执行。
5. **不要开启 `forward_all_messages`**：除非必要，否则会泄露大量隐私信息。

## ❓ 常见问题

### Q1：插件启动后提示 WebSocket 连接失败？

- 检查 Hermes 是否已启动反向 WebSocket 服务，且端口与 `hermes_ws_url` 一致。
- 检查防火墙是否允许该端口访问。
- 如果配置了 `hermes_access_token`，确保 Hermes 端也要求相同 token。

### Q2：执行指令返回 `未找到指令`？

- 确保指令名称正确（不要带 `/` 前缀）。
- 使用 `GET /api/commands/for_hermes` 查看实际可用的指令名和别名。
- 如果指令来自某个未激活的插件，请先激活该插件。

### Q3：消息转发正常，但 Hermes 执行指令后无法收到结果？

- 指令执行结果会直接通过 HTTP API 返回给 Hermes，Hermes 需要自行处理响应。
- 如果 Hermes 需要将结果发回 QQ 群，可以再调用 `/api/send` 接口发送。
- 或者插件在执行指令时会**自动将结果通过 OneBot API 发送到原群**（只要请求中提供了 `group_id`）。

### Q4：插件是否依赖 HTTP Platform 或 LLM Executor？

**不依赖**。本插件独立实现了所有功能，只需要 AstrBot 核心和 aiocqhttp 平台支持。

### Q5：如何让 Hermes 主动向 QQ 群发送消息？

使用 `/api/send` 接口：

```bash
curl -X POST http://localhost:8567/api/send \
  -H "Content-Type: application/json" \
  -d '{"group_id": 123456789, "message": "你好，我是 Hermes"}'
```

## 📝 版本历史

### v2.0 (当前)

- 完全重写为 WebSocket 版本
- 移除对 HTTP Platform 和 LLM Executor 的依赖
- 新增指令缓存和别名解析
- 新增 `/api/commands/for_hermes` 端点
- 支持 OneBot v11 标准消息格式
- 支持自动重连和指数退避
- 新增 `/approve` `/deny` 特殊指令授权机制

### v1.0 (旧版，已废弃)

- 基于 HTTP webhook 和 HTTP Platform 的旧版实现

## 📄 许可证

遵循 AstrBot 插件生态的许可协议。

## 👤 作者

懒大猫

## 🔗 相关链接

- [Hermes Agent](https://github.com/landamao/abpl_hermes_spq)

---

**如有问题，欢迎提交 Issue 或联系作者。**
