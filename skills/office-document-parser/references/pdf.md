# PDF 处理

## 适用场景

- 查看 PDF 正文
- 总结 PDF
- 从 PDF 提取文本
- 只有在用户明确要求处理后的文件或附件时，才把 PDF 转成 Markdown 后发给用户

## 默认路径

- 优先 `markitdown`
- 默认通过 CLI 提取成 Markdown，再读取提取结果
- 不要把 PDF 链接或二进制内容当成已经“读过正文”
- 这条本地路径适合可直接提取文本的 PDF，不等于本地 OCR

## 推荐命令

```bash
markitdown "/path/to/file.pdf" | sed -n '1,200p'
```

如果需要完整检查，可继续分段读取：

```bash
markitdown "/path/to/file.pdf" | sed -n '200,400p'
```

## OCR 边界

- 如果 PDF 是扫描件、图片版，或 `markitdown` 提取结果几乎为空，不要硬说已经成功读取正文。
- 当前默认本地路径不负责 OCR。
- 如果后续提供了外部 OCR 接口，优先切到外部 OCR；在那之前，只能如实说明“当前本地提取能力不足”。
- 需要对用户解释时，明确写“这份 PDF 可能需要外部 OCR 才能稳定提取文本”。

## 交付规则

只有在用户明确要求“处理后的文件”“导出的 Markdown”或“把文件发给我”时，才进入这条交付路径。

如果用户要的是“处理后的文件”而不是纯摘要：

```bash
mkdir -p "/root/.nanobot/workspace/exports"
markitdown "/path/to/file.pdf" > "/root/.nanobot/workspace/exports/result.md"
```

然后用：

```text
message(content="这是从 PDF 提取的 Markdown 文件。", media=["/root/.nanobot/workspace/exports/result.md"])
```

不要只回复“我已经处理好了”而不真正交付附件。
- 如果用户只是问“这个 PDF 是什么”“帮我总结”，默认先给摘要，不要主动发送 `result.md`。

## 失败处理

- 先报告失败命令
- 再说明是 `markitdown` 失败还是 PDF 本身不可解析
- 如果只能提取出部分文本，要明确说明限制
