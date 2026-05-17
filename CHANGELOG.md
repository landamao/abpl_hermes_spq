# 更新日志

## [v6.0.1] - 2026-05-18

### 🚀 重大更新：指令代理引擎回归

- 新增 `command_manager.py` 完整指令管理器，支持扫描、缓存、执行框架所有插件指令
- 新增指令执行 HTTP 服务器（`http_server.py`），提供 `/api/execute`、`/api/commands` 等端点，支持 Bearer Token 认证
- 新增 LLM 工具 `execute_command`、`list_commands`，框架内置 AI 可主动调用任意插件指令
- 新增群聊/私聊事件缓存，指令执行时自动匹配正确的 event
- WebSocket 消息类型智能处理（`send_message`、`ping`、`api_request`）
- 新增可配置指令前缀（默认 `/`）
- 敏感字符过滤增强，自动添加 `http指令服务器token` 及 Hermes 配置中的 `api_key`
- 修复 LLM 工具 `hermes_agent` 中 WebSocket 连接判断逻辑错误
- 修复消息纯文本提取时的崩溃问题
- 修复配置解析污染原列表的问题

---

<details>
<summary>📋 点击查看历史更新日志（v3.9.0 及更早版本）</summary>

## [v3.9.0] - 2026-04-25

### ✨ 新增

- **引用 Hermes 消息直接唤醒**：新增配置项 `reply_to_hermes_trigger`，适配器发送消息时自动记录 message_id，用户引用 Hermes 消息时无需触发关键词即可唤醒

### 🔧 改进

- 所有 error 日志添加 `exc_info=True` 打印完整堆栈
- 发送消息时打印完整请求和结果
- 启动时打印所有 py/pyc 文件的最后修改日期
- 指令执行前检测 handler 返回类型（异步生成器/协程），消除类型错误警告

### 📦 新增 API

- `upload_group_file` - 上传文件到群
- `upload_private_file` - 上传文件到私聊

---

## [v3.3] - 2026-04-24

### 🏗️ 模块化重构

将单体文件拆分为独立模块：

- `command_cache.py` - 指令缓存、查找、别名解析、黑白名单
- `message_handler.py` - 消息过滤与 OneBot 事件体构造
- `http_server.py` - HTTP API 服务器
- `ws_client.py` - WebSocket 连接管理
- `onebot_api.py` - OneBot API 调用封装

### ✨ 新增特性

- 框架指令自动跳过（以已注册指令名开头的消息不再转发给 Hermes）
- 消息链过滤增强，自动移除 `Reply` 组件，确保与 Hermes 适配器兼容

### 🔧 改进

- 指令缓存重建时机优化
- 日志输出调整

### 🐛 修复

- 修复同时命中 Hermes 转发和 LLM 唤醒时，`hermes_only` 模式下仍可能触发 LLM 的竞态问题（通过 `event.stop_event()` 严格终止）

---

## [v3.1] - 2026-04-23

### ✨ 新增

- **冲突处理模式**：新增配置项 `llm_hermes_conflict_mode`，可选 `hermes_only`（默认）、`llm_only`、`both`
- 消息事件优先级控制（`priority=-1`），确保在 LLM 处理前优先拦截

### 🔧 改进

- 更精准的消息链过滤
- 内部冲突判断逻辑拆分，提高可读性

### 🐛 修复

- 修复同时唤醒时可能出现的双重回复问题

---

## [v3.0] - 2026-04-23

### ✨ 新增

- **LLM 工具集成**：提供 `hermes_agent`、`hermes_status`、`hermes_list_commands` 三个工具
- **特殊指令支持**：`/approve` 与 `/deny`，配置项 `approve_deny_enabled` 和 `approve_deny_users`
- **消息去重与精准构造**：遵循 OneBot v11 标准，通过扩展标记 `已转发键` 避免循环

### 🔧 改进

- 完善消息过滤日志
- 更稳定的指令执行异常处理（兼容 MessageChain 异步生成器）
- HTTP 服务器健壮性增强，返回标准 `401 Unauthorized`
- WebSocket 连接优化，支持 `ping`/`pong` 心跳

### 🐛 修复

- 消息 ID 重复问题（转发时使用随机 ID）
- 长消息截断后保留原消息链结构
- 指令执行结果无法自动发回群的问题
- `hermes_ws_url` 含路径时的连接错误

---

## [v2.0] - 2026-04-20

### 🏗️ 架构重写

- HTTP Webhook 方案替换为 **WebSocket 全双工通信**
- 引入指令缓存引擎（`command_cache.py`），支持别名解析、分类索引
- 自动重连机制，指数退避策略

### ✨ 新增特性

- 支持私聊消息转发
- 新增 `/hermes status` 用户指令
- 支持配置多个触发关键词
- 表情回应自动贴表情功能

---

## [v1.0] - 2026-04-15

### 🎉 初始发布

- 通过 HTTP Webhook 将框架消息转发给 Hermes
- 消息过滤：关键词触发、@触发、群白名单
- 基础配置：Hermes 地址、OneBot API 地址、Token 认证

**已知限制**：仅支持群聊、单向转发、无自动重连

</details>

---

**作者：懒大猫**