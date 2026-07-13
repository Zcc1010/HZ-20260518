import { existsSync, statSync, readdirSync, lstatSync, symlinkSync, readlinkSync } from 'fs'
import { join, basename, relative, resolve, dirname } from 'path'

// 调用方式：npx tsx tools/copy-templates.ts "<工作区名>" "<设备类型>" "[装置型号]"
// 示例：  npx tsx tools/copy-templates.ts "北湖变131线" "10~20kV线路" "PCS-9611A"
//
// 行为（软链模式）：
//   1. 整定原则文件 → 软链到工作区（人员参考）
//   2. 说明书（如提供了装置型号且手册存在）→ 软链整目录到工作区
//
// 软链是相对路径，agent 目录移动也能用。
// 工作区可放心 cp -r / rsync 复制（默认会展开软链，要保留用 cp -P）
//
// 说明书查找策略：
//   1. 精确匹配（型号目录存在）→ 直接软链
//   2. 型号前缀 + 设备类型推断 → 列出候选目录，agent 自行判断
//   3. 都没有 → 提示"说明书缺失"

const SKILLS_DIR = join(process.cwd(), 'skills', 'setting-check', 'references')
const PRINCIPLES_DIR = join(SKILLS_DIR, 'principles')
const MANUALS_BASE = join(process.cwd(), 'resources', 'manuals')
const WORKSPACE_BASE = join(process.cwd(), 'workspace')

// 厂家目录（manuals/ 下的厂家子目录）
const MANUFACTURERS = [
  '国电南自', '国电南瑞', '南瑞科技', '上海思源',
  '南瑞继保', '长园深瑞', '北京四方', '许继电气',
]

// 型号前缀 → 厂家推断（参考 references/说明书查找规则.md）
const PREFIX_TO_MFR: Record<string, string[]> = {
  PCS: ['南瑞继保'],
  RCS: ['南瑞继保'],
  PSL: ['国电南自'],
  PSC: ['国电南自'],
  PST: ['国电南自'],
  SGT: ['国电南自'],
  SGR: ['国电南自'],
  SGB: ['国电南自'],
  UDL: ['上海思源'],
  PRS: ['长园深瑞'],
  ISA: ['长园深瑞'],
  BP: ['长园深瑞'],
  CSC: ['北京四方'],
  PAC: ['许继电气'],
  WBH: ['许继电气'],
  WDLK: ['许继电气'],
  WMH: ['许继电气'],
}

// 设备类型关键词 → manuals/ 下的子目录
const TYPE_TO_DIR: Record<string, string[]> = {
  '线路': ['线路保护'],
  '变压器': ['变压器保护'],
  '母线': ['母线保护'],
  '电容器': ['电容器保护'],
  '电抗器': ['电抗器保护'],
  '站用变': ['站用变保护'],
  '断路器': ['断路器保护'],
}

const TYPE_DIR_NAMES = new Set(Object.values(TYPE_TO_DIR).flat())

const workspace = process.argv[2]
const deviceType = process.argv[3]
const manualModel = process.argv[4] // 可选：装置型号

if (!workspace || !deviceType) {
  console.error('Usage: npx tsx tools/copy-templates.ts <工作区名> <设备类型> [装置型号]')
  console.error('示例:  npx tsx tools/copy-templates.ts "北湖变131线" "10~20kV线路" "PCS-9611A"')
  process.exit(1)
}

const destDir = join(WORKSPACE_BASE, workspace)
if (!existsSync(destDir)) {
  console.error(`工作区不存在: ${destDir}`)
  console.error('请先创建工作区（`创建工作区` API）')
  process.exit(1)
}

let linked = 0
let skip = 0

// 1. 整定原则（软链）
const principleSrc = join(PRINCIPLES_DIR, `${deviceType}整定原则.md`)
const principleDest = join(destDir, `${deviceType}整定原则.md`)
if (existsSync(principleSrc)) {
  const result = ensureSymlink(principleSrc, principleDest)
  console.log(`${result} ${deviceType}整定原则.md`)
  if (result === '✓') linked++; else skip++
} else {
  console.log(`✗ 跳过: 找不到 ${deviceType}整定原则.md`)
  skip++
}

// 2. 说明书（软链整目录）
if (manualModel) {
  const found = findManualDir(MANUALS_BASE, manualModel)
  if (found) {
    const target = join(destDir, basename(found))
    const result = ensureSymlink(found, target)
    const rel = relative(destDir, found)
    console.log(`${result} ${basename(found)}/  → ${rel}`)
    if (result === '✓') linked++; else skip++
  } else {
    // 前缀 + 设备类型推断候选
    const candidates = findPrefixCandidates(MANUALS_BASE, manualModel, deviceType)
    if (candidates.length > 0) {
      console.log(`✗ 说明书未找到精确匹配: ${manualModel}`)
      console.log(`  推断的厂家/设备类型: ${inferMfrAndType(manualModel, deviceType)}`)
      console.log(`  候选目录（请人工确认后用 ln -s 创建软链）:`)
      for (const c of candidates) {
        const rel = relative(destDir, c)
        console.log(`    ln -s "${rel}" "${basename(c)}"`)
      }
    } else {
      console.log(`✗ 说明书未找到: ${manualModel}（前缀无匹配，维度三/四判"不适用"，报告中注明"说明书缺失"）`)
    }
    skip++
  }
}

console.log(`\n共软链 ${linked} 项${skip > 0 ? `，跳过 ${skip} 项` : ''}`)
console.log(`目标: ${destDir}`)

// 创建相对路径软链。已存在且指向同一目标 → 视为 ✓ 跳过；其它冲突 → 报错
function ensureSymlink(target: string, linkPath: string): '✓' | '= ' {
  const linkDir = dirname(linkPath)
  if (lstatSync(linkPath, { throwIfNoEntry: false }) as any) {
    const lst = lstatSync(linkPath)
    if (lst.isSymbolicLink()) {
      const cur = readlinkSync(linkPath)
      // 比较实际解析后的绝对路径
      if (resolve(linkDir, cur) === resolve(target)) return '= '
      throw new Error(`软链已存在但指向不同目标:\n  ${linkPath} -> ${cur}\n  期望: ${target}\n  请先删除: rm "${linkPath}"`)
    }
    throw new Error(`目标已存在且不是软链: ${linkPath}\n  请先删除或改名后再运行`)
  }
  const rel = relative(linkDir, target)
  symlinkSync(rel, linkPath)
  return '✓'
}

// 在 manuals/{厂家}/{设备类型}/{型号}/ 下精确匹配型号目录
function findManualDir(base: string, model: string): string | null {
  if (!existsSync(base)) return null
  const direct = join(base, model)
  if (existsSync(direct) && statSync(direct).isDirectory()) {
    return direct
  }
  return walkForExact(base, model)
}

function walkForExact(dir: string, model: string): string | null {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (!statSync(full).isDirectory()) continue
    // 型号是第三级目录：{厂家}/{设备类型}/{型号}/
    if (TYPE_DIR_NAMES.has(basename(dir)) && entry === model) return full
    const deeper = walkForExact(full, model)
    if (deeper) return deeper
  }
  return null
}

// 按前缀找候选目录
function findPrefixCandidates(base: string, model: string, devType: string): string[] {
  const prefix = model.match(/^[A-Za-z]+/)?.[0] || ''
  if (!prefix) return []

  const mfrs = PREFIX_TO_MFR[prefix] || []
  const typeDirs = matchTypeDirs(devType)

  const candidates: string[] = []
  for (const mfr of mfrs) {
    for (const tdir of typeDirs) {
      const dir = join(base, mfr, tdir)
      if (!existsSync(dir)) continue
      for (const entry of readdirSync(dir)) {
        // 同前缀开头的型号（避免误中兄弟目录）
        if (entry.startsWith(prefix) && statSync(join(dir, entry)).isDirectory()) {
          candidates.push(join(dir, entry))
        }
      }
    }
  }
  return candidates
}

function matchTypeDirs(devType: string): string[] {
  for (const [key, dirs] of Object.entries(TYPE_TO_DIR)) {
    if (devType.includes(key)) return dirs
  }
  return Object.values(TYPE_TO_DIR).flat() // 兜底：所有设备类型
}

function inferMfrAndType(model: string, devType: string): string {
  const prefix = model.match(/^[A-Za-z]+/)?.[0] || ''
  const mfrs = PREFIX_TO_MFR[prefix] || ['未知厂家']
  const typeDirs = matchTypeDirs(devType)
  return `${mfrs.join(' / ')} / ${typeDirs.join(' / ')}`
}
