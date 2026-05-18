# 旧格式与 OFD 回退

## LibreOffice 的定位

`libreoffice/soffice` 是格式转换后备层，不是默认主解析器。

优先使用它的场景：
- 旧版二进制 `doc/xls/ppt`
- `markitdown` 对旧格式直接解析效果差

不优先使用它的场景：
- 只想知道 Excel 有哪些 sheet
- 只想预览某个 sheet

## 旧版 Office 转换

```bash
sh scripts/convert_legacy_office.sh "/path/to/file.xls"
```

这个脚本会输出转换后的新文件路径。

之后：
- 如果要看全文，用转换后的文件走 `markitdown`
- 如果是 Excel 且只问结构或单个 sheet，优先继续走 workbook 脚本

## OFD 规则

不要把 OFD 当成稳定保证支持的格式，但也不要在看到 `ofd` 时立刻放弃。

推荐顺序：
1. 先尝试 `soffice` 转换成更常见格式
2. 如果转换成功，再按转换后的类型继续处理
3. 如果转换失败，再明确告知当前运行时无法稳定处理这个 OFD

## 失败处理

如果失败，按这个顺序报告：
1. 哪一步失败了
2. 用的是哪条命令
3. 是 `markitdown`、`soffice`、还是 workbook 脚本失败
4. 是否还有可用回退路径
