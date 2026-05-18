# Word / PPT 处理

## 适用场景

- 查看 Word 正文
- 总结 Word 或 PPT 内容
- 提取新版 Office 文档正文
- 兼容旧版文档

## 新版格式

适用：
- `docx`
- `pptx`

优先命令：

```bash
markitdown "/path/to/file.docx" > /tmp/office-document.md
sed -n '1,160p' /tmp/office-document.md
```

PPT 同理：

```bash
markitdown "/path/to/file.pptx" > /tmp/office-document.md
sed -n '1,160p' /tmp/office-document.md
```

## 旧版格式

适用：
- `doc`
- `ppt`

先转格式：

```bash
sh scripts/convert_legacy_office.sh "/path/to/file.doc"
```

脚本会输出转换后的新文件路径。然后对转换结果继续使用 `markitdown`。

## 交付规则

如果用户要最终文件：
- 优先发送用户真正需要的最终文件
- 不要把中间 Markdown 误发成最终文档，除非用户明确要提取版结果

