# Excel 处理

## 适用场景

- 判断有多少个 sheet
- 查看工作表名称和规模
- 预览某个指定 sheet
- 总结整个工作簿

## 结构问题

适用：
- `xls`
- `xlsx`

优先命令：

```bash
python3 scripts/inspect_workbook.py "/path/to/file.xlsx"
```

用途：
- 列出 sheet 名
- 给出每个 sheet 的行列规模
- 作为后续局部提取前的第一步

## 局部内容问题

优先命令：

```bash
python3 scripts/extract_sheet_preview.py "/path/to/file.xlsx" --sheet "差动" --rows 40
```

也可以用索引：

```bash
python3 scripts/extract_sheet_preview.py "/path/to/file.xlsx" --index 1 --rows 40
```

## 全文或整体总结

- `xlsx`
  - 优先 `markitdown`
- `xls`
  - 通常先转 `xlsx`，再 `markitdown`

命令模板：

```bash
markitdown "/path/to/file.xlsx" > /tmp/office-document.md
sed -n '1,160p' /tmp/office-document.md
```

对 `xlsx`：
- 先看输出是否保留了 sheet 边界
- 如果没有，再补用 workbook 脚本

## 常见错误

- 为了列出 sheet 先转 CSV
- 拿单个 sheet 的内容冒充整个工作簿结论
- 明明只问结构，却直接做整本 `markitdown`

