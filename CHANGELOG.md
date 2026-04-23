# 更新日志

## [v3.2]

### 🏗️ 模块化重构

将原本 1000+ 行的单体文件按职责拆分为独立模块，提高代码可读性和可维护性：

- **`command_cache.py`**  
  指令缓存构建、指令查找、别名解析、黑白名单校验、指令分类等逻辑。

- **`message_handler.py`**  
  消息转发条件判断（关键词/@机器人/白名单）、OneBot v11 事件体构造。

- **`http_server.py`**  
  HTTP API 服务器（`/api/execute`、`/api/send`、`/api/commands/for_hermes` 等端点）及指令执行入口。

- **`ws_client.py`**  
  WebSocket 连接管理、自动重连、心跳保活、消息收发。

- **`onebot_api.py`**  
  封装 OneBot API 调用（发送群消息/私聊消息、获取群信息等）。

### ✨ 新增特性

- **框架指令自动跳过**  
  当用户发送的消息以已注册的指令名称（如 `/help`、`点歌`）开头时，不再转发给 Hermes，避免与 AstrBot 原生指令处理产生冲突。

- **消息链过滤增强**  
  在构造 OneBot 事件时，自动移除 `Reply`（回复）组件，确保与 Hermes OneBot 适配器的完全兼容。

### 🔧 改进

- 指令缓存重建时机优化，在 LLM 工具调用前自动检查并重建。
- 日志输出调整，减少冗余 debug 信息。

### 🐛 修复

- 修复当消息同时命中 Hermes 转发条件和 LLM 唤醒词时，`hermes_only` 模式下仍可能触发 LLM 的竞态问题（通过 `event.stop_event()` 严格终止）。

### 📝 升级说明

- **无配置变更**，所有原有配置项保持不变，**仅重构了代码**
- 模块拆分不影响任何外部行为，转发、API 调用、LLM 工具功能与 v3.1 完全一致。
- 建议覆盖更新后重启 AstrBot。

<details>
<summary>📋 点击查看历史更新日志</summary>

---
## [v3.1] - 2026-04-23

### ✨ 新增

- **冲突处理模式配置项 `llm_hermes_conflict_mode`**  
  当一条消息同时满足 Hermes 转发条件和 AstrBot LLM 唤醒条件时，可通过该配置选择处理策略：
  - `hermes_only`（默认）：终止 LLM 处理器，仅转发给 Hermes，避免重复回答。
  - `llm_only`：仅使用原始 LLM，不转发给 Hermes。
  - `both`：同时触发 LLM 和 Hermes（可能导致混乱，仅供测试）。

- **消息事件优先级控制**  
  监听器优先级设置为 `priority=-1`，确保在 LLM 处理前优先拦截并决定是否终止事件传播。

### 🔧 改进

- **更精准的消息链过滤**  
  在构造 OneBot 格式消息时，额外过滤掉 `Reply`（回复）组件，防止不兼容的段被转发给 Hermes。

- **内部冲突判断逻辑拆分**  
  新增 `是否转发(event)` 方法，根据 `llm_hermes_conflict_mode` 和事件的 `is_at_or_wake_command` 属性决定是否拦截事件，提高代码可读性。

### 🐛 修复

- **修复同时唤醒时可能出现的双重回复问题**  
  通过 `event.stop_event()` 机制，在 `hermes_only` 模式下彻底阻止 LLM 处理器被调用。

### 📝 文档

- 更新 README，补充 `llm_hermes_conflict_mode` 配置说明及冲突处理行为描述。

---

**升级建议**：  
从 v3.0 升级到 v3.1 无需修改配置，默认 `llm_hermes_conflict_mode = "hermes_only"` 可有效避免 LLM 和 Hermes 同时回复。如果您希望保留旧版“同时触发”的行为，请手动将配置改为 `both`。

## [v3.0] - 2026-04-23

### ✨ 新增

- **LLM 工具集成**  
  为 AstrBot 内置 AI 提供了三个可调用的工具，使 AI 能够直接与 Hermes 交互：
  - `hermes_agent`：调用 Hermes Agent 执行任务或指令（支持直接执行 AstrBot 指令或转发任务描述给 Hermes）。
  - `hermes_status`：查询 Hermes 适配器与 WebSocket 连接状态、运行时长、统计信息。
  - `hermes_list_commands`：列出所有可通过 Hermes 执行的 AstrBot 指令，支持按分类过滤（音乐、宠物、好感度等）。

- **特殊指令支持 `/approve` 与 `/deny`**  
  - 新增配置项 `approve_deny_enabled`（默认 `true`）和 `approve_deny_users`。
  - 当用户在白名单中发送 `/approve` 或 `/deny` 时，适配器会自动转发给 Hermes（并自动添加触发关键词前缀），用于人工干预 Hermes 的审批流程。

- **消息去重与更精准的构造**  
  - 引入 `构造请求体` 异步方法，完全遵循 OneBot v11 标准，保留原始消息中的图片、At、Json 等非文本段。
  - 转发时自动检测是否为重复消息（通过扩展标记 `已转发键`），避免同一消息被重复转发造成循环。

### 🔧 改进

- **更完善的消息过滤日志**  
  在 `_是否应转发` 方法中添加了详细的 debug 日志，明确记录消息被转发或被忽略的原因（命中关键词、@机器人、白名单过滤等），便于排查问题。

- **更稳定的指令执行异常处理**  
  - 优化了 `_内部执行指令` 中对 `MessageChain` 的解析，兼容更多 AstrBot 插件返回的消息组件（如 JSON 卡片、图片、纯文本）。
  - 异步生成器失败时回退到同步调用，提高指令执行成功率。

- **HTTP 服务器健壮性增强**  
  - `/api/commands/for_hermes` 端点返回的分类映射更全面，现在自动识别音乐、宠物、好感度、群管理、系统、生图、表情包、分析等类别。
  - 所有 API 端点在 Token 认证失败时返回标准的 `401 Unauthorized`。

- **WebSocket 连接优化**  
  - 连接成功后发送 `connect` 确认消息，包含平台标识 `qq` 和 `self_id`，便于 Hermes 识别来源。
  - 心跳支持 `ping` / `pong`，减少连接意外断开。

### 🐛 修复

- **消息 ID 重复问题**  
  之前转发消息时可能使用固定的或已用过的 `message_id` 导致 Hermes 端去重逻辑误判。现在对于已转发的消息会使用基于时间戳的随机 ID，并保留原始 ID 供调试。

- **长消息截断后仍保留原消息链结构**  
  以前截断消息时会丢失原始消息中的 At、图片等段。现在 `构造请求体` 会保留所有非文本段，仅将 Plain 文本替换为截断后的内容。

- **指令执行结果无法自动发回群的问题**  
  修复了当通过 HTTP `/api/execute` 调用指令且提供了 `group_id` 时，结果未能正确通过 OneBot API 发送到群的 bug。

- **`hermes_ws_url` 配置含路径时的连接错误**  
  现在支持 WebSocket 地址中包含路径（例如 `ws://host:6701/ws`）。

### 📝 文档更新

- README 完全重写，补充了 LLM 工具使用说明。
- `metadata.yaml` 中的 `help` 字段更新，新增工具和 API 描述。

---

**升级建议**：  
若你正在使用 v2.0，替换插件目录后重启 AstrBot 即可自动升级。无需修改现有配置，新配置项 `approve_deny_enabled` 和 `approve_deny_users` 有默认值，不影响旧行为。

</details>

最后修改：2026-4-24 6:38
