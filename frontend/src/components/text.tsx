// Texto enriquecido sin dangerouslySetInnerHTML.
// - Highlight: el buscador marca coincidencias con <mark>; el resto ya llega escapado
//   como HTML, así que aquí se trocea y se pintan nodos de React (nunca HTML crudo).
// - Markdown: un subconjunto pequeño (títulos, listas, negrita, cursiva, código,
//   citas [n] y enlaces internos). Lo que escribe la IA nunca se interpreta como HTML.
import { Fragment, type ReactNode } from 'react'
import { Link } from 'react-router'

const ENTITIES: Record<string, string> = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#x27;': "'", '&#39;': "'" }

function unescape(text: string): string {
  return text.replace(/&(amp|lt|gt|quot|#x27|#39);/g, (m) => ENTITIES[m] ?? m)
}

export function Highlight({ html, fallback }: { html: string | null | undefined; fallback?: string }) {
  if (!html) return <>{fallback ?? ''}</>
  const parts = html.split(/(<mark>.*?<\/mark>)/g)
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith('<mark>') ? (
          <mark key={i}>{unescape(part.slice(6, -7))}</mark>
        ) : (
          <Fragment key={i}>{unescape(part)}</Fragment>
        ),
      )}
    </>
  )
}

// Enlaces internos que puede escribir la IA: [texto](/proposals/3). Los externos se
// muestran como texto, para que una respuesta no pueda llevar a un sitio de terceros.
const INLINE = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`|\[[^\]]+\]\(\/[a-z0-9/_-]*\)|\[\d+\])/gi

function inline(text: string, onCite?: (n: number) => void): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    if (!part) return null
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) return <strong key={i}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) return <code key={i}>{part.slice(1, -1)}</code>
    if (/^\[\d+\]$/.test(part)) {
      const n = Number(part.slice(1, -1))
      return onCite ? (
        <button key={i} className="cite" onClick={() => onCite(n)} title={`Ver la fuente ${n}`}>
          {n}
        </button>
      ) : (
        <sup key={i} className="cite">
          {n}
        </sup>
      )
    }
    const link = /^\[([^\]]+)\]\((\/[a-z0-9/_-]*)\)$/i.exec(part)
    if (link) {
      return (
        <Link key={i} to={link[2]}>
          {link[1]}
        </Link>
      )
    }
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) return <em key={i}>{part.slice(1, -1)}</em>
    return <Fragment key={i}>{part}</Fragment>
  })
}

export function Markdown({ text, onCite }: { text: string | null | undefined; onCite?: (n: number) => void }) {
  if (!text) return null
  const blocks: ReactNode[] = []
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  let list: { ordered: boolean; items: string[] } | null = null
  let para: string[] = []
  let code: string[] | null = null

  const flushPara = () => {
    if (para.length) {
      blocks.push(<p key={blocks.length}>{inline(para.join(' '), onCite)}</p>)
      para = []
    }
  }
  const flushList = () => {
    if (list) {
      const items = list.items.map((item, i) => <li key={i}>{inline(item, onCite)}</li>)
      blocks.push(list.ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>)
      list = null
    }
  }

  for (const raw of lines) {
    const line = raw.trimEnd()
    if (line.startsWith('```')) {
      if (code) {
        blocks.push(<pre key={blocks.length}>{code.join('\n')}</pre>)
        code = null
      } else {
        flushPara()
        flushList()
        code = []
      }
      continue
    }
    if (code) {
      code.push(raw)
      continue
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line)
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (!line.trim()) {
      flushPara()
      flushList()
    } else if (heading) {
      flushPara()
      flushList()
      const level = Math.min(heading[1].length + 2, 6)
      const Tag = `h${level}` as 'h3' | 'h4' | 'h5' | 'h6'
      blocks.push(<Tag key={blocks.length}>{inline(heading[2], onCite)}</Tag>)
    } else if (bullet || numbered) {
      flushPara()
      const ordered = !!numbered
      if (!list || list.ordered !== ordered) {
        flushList()
        list = { ordered, items: [] }
      }
      list.items.push((bullet ?? numbered)![1])
    } else {
      flushList()
      para.push(line.trim())
    }
  }
  if (code) blocks.push(<pre key={blocks.length}>{(code as string[]).join('\n')}</pre>)
  flushPara()
  flushList()
  return <div className="prose">{blocks}</div>
}
