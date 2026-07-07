import { useEffect, useRef, useState, Children } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeRaw from 'rehype-raw'
import rehypeSlug from 'rehype-slug'
import mermaid from 'mermaid'

interface Props {
  children: string
  workspacePath?: string
  fileDir?: string
  renderMermaid?: boolean
}

let mermaidCounter = 0
function nextMermaidId() {
  return `mermaid-svg-${++mermaidCounter}`
}

mermaid.initialize({
  startOnLoad: false,
  theme: 'default',
  themeVariables: {
    fontSize: '12px',
  },
} as any)

function sanitizeMermaid(src: string): string {
  return src.replace(/&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)/g, '&amp;')
}

function MermaidBlock({ source }: { source: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [, setStatus] = useState<'pending' | 'ok' | 'error'>('pending')

  useEffect(() => {
    if (!ref.current) return
    const el = ref.current
    const code = sanitizeMermaid(source)
    const id = nextMermaidId()
    setStatus('pending')
    mermaid.render(id, code)
      .then(({ svg }) => {
        el.innerHTML = svg
        const svgEl = el.querySelector('svg')
        if (svgEl) {
          const vb = svgEl.getAttribute('viewBox')?.split(/\s+/).map(Number)
          if (vb && vb.length === 4 && vb[2] > 0) {
            svgEl.style.width = vb[2] + 'px'
            svgEl.style.height = vb[3] + 'px'
          }
          svgEl.style.maxWidth = 'none'
          svgEl.style.maxHeight = 'none'
        }
        setStatus('ok')
      })
      .catch((err) => {
        el.innerHTML = `<pre style="color:red">mermaid 渲染失败: ${err.message}</pre>`
        setStatus('error')
      })
  }, [source])

  return (
    <div className="my-4 overflow-x-auto overflow-y-hidden bg-gray-50 rounded-md p-4">
      <div ref={ref} className="mermaid inline-block">
        <pre className="mermaid-source hidden">{source}</pre>
      </div>
    </div>
  )
}

export function Markdown({ children, workspacePath, fileDir, renderMermaid = true }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!containerRef.current) return
    const root = containerRef.current
    if (renderMermaid) {
      root.querySelectorAll<HTMLElement>('details').forEach((d) => {
        d.setAttribute('open', '')
        const summary = d.querySelector<HTMLElement>('summary')
        if (summary) summary.style.display = 'none'
      })
    } else {
      root.querySelectorAll<HTMLElement>('details').forEach((d) => {
        const summary = d.querySelector<HTMLElement>('summary')
        if (summary?.textContent?.trim() === 'flowchart') {
          d.style.display = 'none'
        }
      })
    }
  }, [children, renderMermaid])

  const components: Record<string, any> = {}

  if (workspacePath) {
    components.img = ({ src, alt }: any) => {
      if (src && !src.startsWith('http') && !src.startsWith('/api/') && !src.startsWith('data:')) {
        let resolved = src.replace(/^\.?\//, '')
        if (fileDir) {
          const parts = [...fileDir.split('/'), ...resolved.split('/')]
          const stack: string[] = []
          for (const p of parts) {
            if (p === '' || p === '.') continue
            if (p === '..') stack.pop()
            else stack.push(p)
          }
          resolved = stack.join('/')
        }
        src = `/api/setting-check-v2/workspaces/${encodeURIComponent(workspacePath)}/read?path=${encodeURIComponent(resolved)}`
      }
      return <img src={src} alt={alt} />
    }
  }

  components.pre = ({ children, ...props }: any) => {
    const arr = Children.toArray(children)
    const codeEl = arr.find((c: any) => c?.props?.className?.includes?.('language-mermaid')) as any
    if (codeEl) {
      if (!renderMermaid) return null
      const text = Children.toArray(codeEl.props.children).map((c: any) =>
        typeof c === 'string' ? c : (c?.props?.children || '')
      ).join('')
      return <MermaidBlock source={text} />
    }
    return <pre {...props}>{children}</pre>
  }

  return (
    <div className="md-content" ref={containerRef}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeRaw, rehypeKatex, rehypeSlug]}
        components={components}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
