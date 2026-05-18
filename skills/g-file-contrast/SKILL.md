---
name: g-file-contrast
description: Use when comparing one D5000 G file with one 新一代 G file, or when an Agent Playground G 文件对比 job needs a report generated from an app workspace.
---

# G File Contrast

## 概述

这个 skill 用来对比两份厂站专属 G 文件，并生成中文 HTML 报告和 JSON 结果。

不要手工做 XML diff。运行内置脚本，让脚本完成：

- 按设备对象提取 G 文件内容
- 以同类型 `id` 检查 D5000 与 6.0 设备映射关系
- 列出 D5000 独有设备和 6.0 独有设备
- 对已映射设备检查名称和坐标是否一致
- 输出中文 HTML 报告
- 同时写出 JSON 结果，便于后续处理

## Agent Playground 任务入口

当调用方提供 `app_root` 和 `job_id` 时，使用任务入口：

```bash
python skills/g-file-contrast/scripts/run_job.py --app-root <app_root> --job-id <job_id>
```

目录约定：

```text
<app_root>/
  skills/
    g-file-contrast/
      SKILL.md
      scripts/
        run_job.py
        compare_g_files.py
  jobs/
    <job_id>/
      inputs.json
      inputs/
        d5000/
          <D5000原文件名>
        new-gen/
          <新一代原文件名>
      report.html    # 输出
      result.json    # 输出
```

应用后端只从 `<app_root>/skills/g-file-contrast/scripts/run_job.py` 调用这个 skill，不从聊天 workspace 的 `skills/` 目录读取。任务入口通过 `inputs.json` 找到两份原始文件，保留原始文件名，并在 stdout 打印生成的 `report.html` 绝对路径。调用方不需要、也不应该传入任意输出路径。

## 直接文件对比入口

当用户直接提供两份文件路径时，使用底层对比脚本：

```bash
python skills/g-file-contrast/scripts/compare_g_files.py <d5000文件> <新一代文件> --json-out /tmp/g-file-contrast.json
```

如果只需要纯文本预览：

```bash
python skills/g-file-contrast/scripts/compare_g_files.py <d5000文件> <新一代文件> --format text
```

如果只需要 JSON：

```bash
python skills/g-file-contrast/scripts/compare_g_files.py <d5000文件> <新一代文件> --format json
```

## 输入要求

要求输入两份 `.g` 文件：

- 一份 D5000 文件
- 一份新一代文件

如果用户没有明确标注来源，优先从文件路径或上下文推断；只有在无法安全判断时才追问。

脚本特性：

- 按 `GBK` 解码并解析 XML
- 以同类型 `id` 作为对象匹配键
- 默认坐标容差为 `0.001`
- 默认输出中文 HTML，包含对比结果、检查范围、问题明细
- 不比较文件级属性、voltype、颜色等系统属性差异

## 输出结果

报告重点分成这些类别：

- `设备是否缺失`
  检查同类型 `id` 在两份文件中是否都存在
- `设备是否关联keyid`
  D5000 有 `keyid` 的设备，检查 6.0 是否也保留相同 `keyid`
- `设备名称`
  已映射设备的 `key_name` 或显示名称不一致
- `设备坐标`
  已映射设备的坐标差异超出容差
- `DText实时库ID`
  DText 作为量测显示点时，检查 6.0 是否缺少实时库 ID
- `DText名称` / `DText坐标`
  DText 量测显示点的名称和显示位置差异

问题明细表包含 `关联类型` 列。对于 `DText`，该列根据名称和 6.0 `rtkeyid` 前缀推断，例如线路量测、母线量测、主变量测、储能遥测、光伏量测等。

## 面向用户汇报

优先使用脚本已经生成的中文 HTML 报告，不要自己再把结论改回英文术语。

汇报时遵循这几个原则：

- 先给对比结果
- 再给检查范围
- 问题明细表直接列出对象类型、关联类型、id、问题类型和明细
- 对 DText 问题要保留推断出的关联类型
- 不展示文件级检查、对象类型检查、字段级 diff、voltype、颜色差异
- 正常设备不在报告正文逐项展开；完整逐设备明细保留在 `result.json`
- 如果没有问题，明确写“未发现异常设备”
- 如果用户需要，再补充完整 JSON 或更细的逐设备明细

## 备注

- 这些 G 文件是厂站内部图，不要假设不同厂站之间的设备命名可以直接复用。
- 新一代文件通常会比 D5000 文件多很多元数据和主题字段，所以不要按原始文本差异下结论，优先相信脚本归一化后的比较结果。
