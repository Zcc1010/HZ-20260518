import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import GithubSlugger from "github-slugger";
import "katex/dist/katex.min.css";

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

function slugify(text: string): string {
  const slugger = new GithubSlugger()
  return slugger.slug(text)
}

function extractText(children: React.ReactNode): string {
  if (typeof children === 'string') return children
  if (typeof children === 'number') return String(children)
  if (Array.isArray(children)) return children.map(extractText).join('')
  if (React.isValidElement(children) && children.props) {
    return extractText((children.props as any).children)
  }
  return ''
}

export function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  if (!content) return null;

  return (
    <div className={`markdown-body ${className ?? ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex, rehypeRaw]}
        components={{
          h1: ({ children, ...props }) => <h1 id={slugify(extractText(children))} {...props}>{children}</h1>,
          h2: ({ children, ...props }) => <h2 id={slugify(extractText(children))} {...props}>{children}</h2>,
          h3: ({ children, ...props }) => <h3 id={slugify(extractText(children))} {...props}>{children}</h3>,
          h4: ({ children, ...props }) => <h4 id={slugify(extractText(children))} {...props}>{children}</h4>,
          h5: ({ children, ...props }) => <h5 id={slugify(extractText(children))} {...props}>{children}</h5>,
          h6: ({ children, ...props }) => <h6 id={slugify(extractText(children))} {...props}>{children}</h6>,
          table: ({ children, ...props }) => (
            <div className="table-wrapper">
              <table {...props}>{children}</table>
            </div>
          ),
          img: ({ ...props }) => (
            <img loading="lazy" className="markdown-img" {...props} />
          ),
          a: ({ children, ...props }) => (
            <a target="_blank" rel="noopener noreferrer" {...props}>
              {children}
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
