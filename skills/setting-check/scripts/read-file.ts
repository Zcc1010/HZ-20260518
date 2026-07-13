import { readFileSync, existsSync } from 'fs'
import { extname } from 'path'
import { createRequire } from 'module'

// Use createRequire so CommonJS resolution follows the agent/node_modules symlink → server/node_modules
const require = createRequire(import.meta.url)

const file = process.argv[2]
if (!file || !existsSync(file)) {
  console.error('Usage: npx tsx read-file.ts <file>')
  process.exit(1)
}

const ext = extname(file).toLowerCase().slice(1)
const buf = readFileSync(file)

function main() {
  switch (ext) {
    case 'txt':
    case 'md':
    case 'csv':
    case 'json':
    case 'xml':
    case 'html':
    case 'htm':
    case 'log':
    case 'yml':
    case 'yaml':
      console.log(buf.toString('utf-8'))
      break

    case 'xls':
    case 'xlsx': {
      const XLSX: any = require('xlsx')
      const wb = XLSX.read(buf, { type: 'buffer' })
      for (const name of wb.SheetNames) {
        if (wb.SheetNames.length > 1) console.log(`\n## ${name}\n`)
        const csv = XLSX.utils.sheet_to_csv(wb.Sheets[name])
        console.log(csv)
      }
      break
    }

    case 'docx': {
      const mammoth: any = require('mammoth')
      const result = mammoth.convertToHtml({ buffer: buf })
      // mammoth returns a Promise; handle synchronously via then
      result.then((r: any) => {
        const text = r.value
          .replace(/<table[^>]*>/g, '\n').replace(/<\/table>/g, '\n')
          .replace(/<tr[^>]*>/g, '').replace(/<\/tr>/g, '\n')
          .replace(/<t[hd][^>]*>/g, ' | ').replace(/<\/t[hd]>/g, '')
          .replace(/<p[^>]*>/g, '\n').replace(/<\/p>/g, '')
          .replace(/<h([1-6])[^>]*>/g, (_, n) => `\n${'#'.repeat(Number(n))} `).replace(/<\/h[1-6]>/g, '\n')
          .replace(/<br\s*\/?>/g, '\n')
          .replace(/<[^>]+>/g, '')
          .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
          .replace(/\n{3,}/g, '\n\n')
          .trim()
        console.log(text)
      }).catch((err: any) => {
        console.error(`Error: ${err.message}`)
        process.exit(1)
      })
      break
    }

    case 'doc': {
      // .doc 是 Word 97-2003 旧二进制格式，mammoth 不支持
      // 用 word-extractor（pure JS，通过 agent/node_modules symlink 复用 server 的依赖）
      const WordExtractor: any = require('word-extractor')
      const extractor = new WordExtractor()
      extractor.extract(file).then((doc: any) => {
        const body = doc.getBody() || ''
        // 段落分隔 + 简单标题识别
        const paragraphs = body.split(/\n\s*\n/).map((p: string) => p.trim()).filter(Boolean)
        for (const p of paragraphs) {
          if (p.length < 60 && /^第.{1,6}[章节条部分编]/.test(p)) {
            console.log(`## ${p}`)
          } else if (p.length < 40 && /^[一二三四五六七八九十]+[、.．]/.test(p)) {
            console.log(`### ${p}`)
          } else {
            console.log(p)
          }
          console.log('')
        }
      }).catch((err: any) => {
        console.error(`Error: ${err.message}`)
        console.error(`如转换失败，请用 Word / WPS 另存为 .docx 或 .txt，再读取。`)
        process.exit(1)
      })
      break
    }

    case 'pdf': {
      const pdfParse: any = require('pdf-parse')
      const fn = pdfParse.default || pdfParse
      Promise.resolve(fn(buf)).then((data: any) => {
        console.log(data.text)
      }).catch((err: any) => {
        console.error(`Error: ${err.message}`)
        process.exit(1)
      })
      break
    }

    case 'ppt':
    case 'pptx': {
      const JSZip: any = require('jszip')
      JSZip.loadAsync(buf).then(async (zip: any) => {
        const slides = Object.keys(zip.files)
          .filter((f: string) => /^ppt\/slides\/slide\d+\.xml$/.test(f))
          .sort()
        for (const slidePath of slides) {
          const xml = await zip.files[slidePath].async('text')
          const texts = xml.match(/<a:t>([^<]*)<\/a:t>/g)?.map((t: string) => t.replace(/<[^>]+>/g, '')) || []
          console.log(texts.join('\n'))
          console.log()
        }
      }).catch(() => {
        console.error(`PPTX support requires jszip. Install with: npm install jszip`)
        process.exit(1)
      })
      break
    }

    default:
      console.log(buf.toString('utf-8'))
  }
}

main()
