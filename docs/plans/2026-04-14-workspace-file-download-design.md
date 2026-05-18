# Workspace File Download Design

**Date:** 2026-04-14

**Status:** Approved for implementation

## Goal

让 WebUI 中的 agent 能把工作区产物作为“可下载文件”交付给用户，而不是只把内容展示在聊天消息里。

第一版范围明确限定为：

- 仅支持 workspace 内文件
- 仅支持 agent 明确通过 `message(..., media=[...])` 暴露的文件
- 下载链接长期有效
- 知道链接的人即可下载，不要求登录
- 不处理外部 URL、不处理对象存储直链、不做文件预览

## Current State

当前系统已经具备两段相关能力，但没有把链路打通：

1. agent prompt 已经明确要求发送文件时使用 `message(..., media=[...])`
2. Web 聊天路径已经在 `webui/api/routes/ws.py` 里截获了 `message()` 工具发往 `channel="web"` 的消息

缺口在于：

- WebSocket 只转发 `content`，没有转发 `media`
- 前端聊天消息模型没有 `attachments`
- 前端消息气泡没有文件卡片
- 后端没有一个匿名 token 下载接口来安全暴露 workspace 产物

## Considered Approaches

### Option A: Plain Markdown Links in Message Content

让 agent 在正文里输出一个普通下载链接。

优点：

- 后端改动最小
- 前端几乎不用改

缺点：

- 前端无法把它当成“文件消息”处理
- 无法自然展示文件名、大小、图标、下载按钮
- 后续扩展成更好的文件交付体验会比较别扭

结论：

可以作为临时方案，但不适合作为正式底座。

### Option B: Structured Attachments + Anonymous Token Download Links

让 agent 继续发送 `message(..., media=[...])`。后端把 `media` 转成结构化附件，并为每个附件生成匿名 token 下载链接，前端按附件卡片渲染。

优点：

- 与现有 prompt 约束一致
- 用户体验更像“agent 把文件发过来了”
- 下载链接不暴露真实本地路径
- 为未来扩展图片预览、文件类型图标、多附件消息留下空间

缺点：

- 需要同时修改 ws 协议、前端消息模型、后端下载路由

结论：

这是推荐方案。

### Option C: Expose Workspace as Static Files

把 workspace 目录直接当作静态目录对外暴露。

优点：

- 实现快

缺点：

- 安全边界很差
- 容易误暴露没有显式授权的文件
- 难以收敛访问范围

结论：

不采用。

## Recommended Architecture

采用 Option B。

### Message Flow

1. agent 在工作区生成文件
2. agent 通过 `message(content="...", media=["/root/.nanobot/workspace/..."])` 发送给 web 用户
3. `webui/api/routes/ws.py` 捕获 `content` 和 `media`
4. 后端把每个 `media` 转换成附件元数据：
   - `id`
   - `name`
   - `mime_type`
   - `size`
   - `download_url`
5. WebSocket `done` 消息把正文和附件列表一起发给前端
6. 前端把消息渲染成“正文 + 文件卡片 + 下载按钮”
7. 用户点击按钮后访问 `GET /api/files/d/{token}`
8. 后端根据 token 找到已登记的 workspace 文件并返回 `FileResponse`

## Token Model

下载链接使用长期有效的匿名 token。

设计要求：

- token 不可猜，推荐使用 `secrets.token_urlsafe(...)`
- token 不包含真实路径信息
- token 映射记录持久化到 session 消息里，而不是只放进内存
- 同一附件可以在会话刷新、页面重开后继续下载

因为用户已经明确接受“知道链接就能下载”，所以 token 本身就是权限，不做额外鉴权。

## Persistence Model

附件需要和消息一起持久化，否则刷新后下载按钮会丢失。

建议在 session message 中为 assistant 消息增加：

```json
{
  "role": "assistant",
  "content": "这是处理后的文件",
  "attachments": [
    {
      "id": "att_xxx",
      "name": "report.docx",
      "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "size": 12345,
      "token": "abc123",
      "download_url": "/api/files/d/abc123"
    }
  ],
  "timestamp": "..."
}
```

## File Safety Rules

只允许暴露满足以下条件的文件：

- 文件位于当前 workspace 目录内
- 文件真实存在
- 文件是普通文件，不是目录
- 文件由 agent 通过 `media` 明确指定

明确不支持：

- 任意绝对路径下载
- 目录下载
- 未登记 token 的直接路径访问
- 通过 URL 参数传本地路径

## API Changes

### WebSocket Payload

现有 `done` 消息：

```json
{
  "type": "done",
  "content": "..."
}
```

扩展为：

```json
{
  "type": "done",
  "content": "...",
  "attachments": [
    {
      "id": "att_xxx",
      "name": "report.docx",
      "mime_type": "...",
      "size": 12345,
      "download_url": "/api/files/d/abc123"
    }
  ]
}
```

### Download Route

新增：

```text
GET /api/files/d/{token}
```

响应行为：

- token 不存在：`404`
- token 对应文件不存在：`404`
- token 对应路径越界到 workspace 外：`403`
- 正常情况：返回文件流，并附带 `Content-Disposition: attachment`

## Frontend Changes

前端需要最小支持三件事：

1. `WsMessage` 增加 `attachments`
2. `ChatMessage` 增加 `attachments`
3. `MessageBubble` 渲染文件卡片

第一版文件卡片建议显示：

- 文件名
- 文件大小
- 下载按钮
- 可选：文件类型图标

第一版不做：

- 在线预览
- 拖拽另存
- 进度条

## Why This Design Fits the Existing Codebase

- 与现有 `message(..., media=[...])` 语义一致
- 不需要改动 agent 侧工具契约
- 改动集中在 WebSocket 捕获层、一个新增下载路由、以及前端消息渲染层
- 不依赖对象存储，适合当前 workspace-first 部署模型

## Risks

### Risk 1: Token Metadata Loss

如果附件 token 只存在内存里，刷新后链接会失效。

应对：

- token 和附件元数据必须进 session 持久化

### Risk 2: Path Traversal

如果 token 最终能映射到任意路径，会导致越权下载。

应对：

- token 只映射到已登记的 workspace 相对路径
- 下载前再做一次 `resolve()` 和 workspace containment 校验

### Risk 3: Frontend/Backend Schema Drift

如果 ws 增加 `attachments` 但前端不接，会导致 UI 无文件入口。

应对：

- 后端、ws 类型、store、bubble 一次性同步修改
- 增加最小测试覆盖

## Success Criteria

满足以下条件即视为完成：

1. agent 通过 `message(..., media=[...])` 发送的工作区文件能在 WebUI 中显示为文件卡片
2. 用户点击下载后能拿到真实文件
3. 刷新页面或重新打开会话后，历史消息中的下载按钮仍然可用
4. 非 workspace 文件不会被暴露
5. 未登记 token 不能下载任何文件
