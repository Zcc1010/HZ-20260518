# Chat Streaming and LaTeX Rendering Design

**Date:** 2026-04-14

**Status:** Approved for implementation

## Goal

提升 WebUI 聊天体验，覆盖两个明确问题：

1. assistant 正文在 WebUI 中改为真正的流式显示，而不是把增量拆成多条独立消息
2. Markdown 中的 LaTeX 数学公式可以正常渲染

## Scope

本次范围只包含：

- Web 聊天通道的 assistant 正文流式显示
- 工具提示继续保留为独立工具消息
- Markdown 数学公式渲染
- 保持现有 thinking/tool/attachment 渲染能力

本次不包含：

- 工具结果流式化
- 图片/文件预览
- 数学公式编辑器
- 对整个聊天 UI 的大规模重构

## Current State

### Streaming

当前前端和状态层已经有一部分流式结构，但没有真正接通：

- `chatStore.ts` 里有 `appendAssistantText` 和 `setStreaming`
- `ChatWindow.tsx` 里维护了 `assistantMsgIdRef`
- 但 `progress` 分支实际仍然直接 `addMessage(...)`

所以目前“增量文本”会被当成多条 assistant 消息，而不是一条持续增长的消息。

同时，WebSocket 路径当前主要依赖 `on_progress`，没有把稳定的 assistant 文本 delta 事件设计清楚。

### LaTeX

当前 `MessageBubble.tsx` 只启用了：

- `remark-gfm`
- `rehype-highlight`

没有启用：

- `remark-math`
- `rehype-katex`
- KaTeX CSS

因此公式目前不会被正确渲染。

## Considered Approaches

### Option A: Minimal Frontend-Only Patch

继续复用现有 `progress` 事件，但前端改成把部分内容 append 到同一条消息。

优点：

- 后端改动少
- 短期见效快

缺点：

- `progress` 语义本来就混着“工具提示”和“普通文本”
- 前端需要猜测某条消息是正文 delta 还是普通提示
- 后续维护会更脆

结论：

不推荐作为正式方案。

### Option B: Explicit Streaming Event Model

后端明确区分：

- `stream_start`
- `stream_delta`
- `stream_end`
- `progress` / `tool_hint`
- `done`

前端按事件类型驱动同一条 assistant 消息的创建、追加、收尾。

优点：

- 语义清晰
- 前后端职责明确
- 后续更容易稳定扩展

缺点：

- 需要同时改 ws 后端和前端事件处理

结论：

这是推荐方案。

### Option C: Full Rich-Message Refactor

把正文、thinking、工具、附件、公式统一成块级渲染模型。

优点：

- 最完整

缺点：

- 明显超出这次需求

结论：

这次不做。

## Recommended Architecture

采用 Option B。

### Streaming Event Contract

新增三类 WebSocket 事件：

```json
{ "type": "stream_start", "session_key": "web:..." }
{ "type": "stream_delta", "session_key": "web:...", "content": "增量文本" }
{ "type": "stream_end", "session_key": "web:..." }
```

现有事件继续保留：

- `progress`：主要用于非正文提示
- `subagent_progress`：子任务提示
- `done`：最终完成态
- `error`：错误态

### Frontend Rendering Model

前端处理规则：

1. 收到 `stream_start`
   - 创建一条空 assistant 消息
   - `isStreaming=true`
   - 记录该消息 id

2. 收到 `stream_delta`
   - 把文本 append 到当前 streaming assistant 消息

3. 收到 `stream_end`
   - 关闭 streaming 状态

4. 收到 `done`
   - 如果当前流式消息已经有内容，则只做收尾/附件合并/状态纠正
   - 如果没有流式消息，则按现有逻辑添加完整 assistant 消息

### Tool Hints

工具提示仍然作为独立消息渲染，不与正文流式合并。

原因：

- assistant 正文和工具提示属于不同信息层
- 混在一个气泡里会让阅读体验变差

### LaTeX Rendering Model

在 Markdown 渲染链路中增加：

- `remark-math`
- `rehype-katex`

并全局引入 KaTeX CSS。

第一版目标：

- 行内公式 `$...$`
- 块级公式 `$$...$$`

保持现有能力不变：

- GFM 表格/列表/任务项
- 代码高亮

## UI Behavior

### Streaming

- 同一条 assistant 气泡持续增长
- 尾部保持当前已有的闪烁光标
- 结束时光标消失

### Math

- 公式遵循正文排版
- 不额外加入沉重卡片或特殊框
- 只在需要时使用 KaTeX 默认结构，再用现有主题做轻量适配

## Risks

### Risk 1: Double Rendering on `done`

如果 `done` 到达时前端已经有完整流式消息，再额外 append 一次完整内容，会造成正文重复。

应对：

- `done` 分支优先检查当前 streaming 消息是否已存在
- 若存在，则只同步状态与附件，不重复插入正文

### Risk 2: Streaming and Tool Hint Interleaving

如果工具提示和正文 delta 没分清，仍会继续生成杂乱消息流。

应对：

- 新增明确事件类型，不复用模糊的 `progress`

### Risk 3: KaTeX CSS Pollution

引入 KaTeX 样式后，可能影响现有 prose 排版。

应对：

- 只引入官方 CSS
- 在 `MessageBubble` 层做轻量局部样式修正

## Success Criteria

满足以下条件即视为完成：

1. assistant 回复在前端表现为单条流式消息，而不是多条碎片 assistant 消息
2. 工具提示仍然单独显示
3. Markdown 中的 `$...$` 和 `$$...$$` 公式正确渲染
4. 附件卡、thinking、代码高亮不回归
5. 前端构建和基础后端验证通过
