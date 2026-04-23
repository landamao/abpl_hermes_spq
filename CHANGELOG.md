# 更新日志

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

### 📦 依赖变更

无新增依赖，继续使用 `aiohttp>=3.8.0` 和 `websockets>=11.0`。

### 📝 文档更新

- README 完全重写，补充了 LLM 工具使用说明。
- `metadata.yaml` 中的 `help` 字段更新，新增工具和 API 描述。

---

**升级建议**：  
若你正在使用 v2.0，替换插件目录后重启 AstrBot 即可自动升级。无需修改现有配置，新配置项 `approve_deny_enabled` 和 `approve_deny_users` 有默认值，不影响旧行为。