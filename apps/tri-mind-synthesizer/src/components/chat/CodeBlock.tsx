import { useState } from 'react'
import { Copy, Check, Download } from 'lucide-react'
import { cn } from '../../lib/utils'
import { ipc } from '../../lib/ipc'

interface CodeBlockProps {
  language: string
  code: string
}

// 语言到文件扩展名的映射
const languageExtensions: Record<string, string> = {
  javascript: 'js',
  typescript: 'ts',
  python: 'py',
  java: 'java',
  rust: 'rs',
  go: 'go',
  cpp: 'cpp',
  c: 'c',
  csharp: 'cs',
  ruby: 'rb',
  php: 'php',
  swift: 'swift',
  kotlin: 'kt',
  html: 'html',
  css: 'css',
  json: 'json',
  yaml: 'yaml',
  xml: 'xml',
  sql: 'sql',
  bash: 'sh',
  shell: 'sh',
  markdown: 'md',
}

export function CodeBlock({ language, code }: CodeBlockProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (error) {
      console.error('复制失败:', error)
    }
  }

  const handleSave = async () => {
    const extension = languageExtensions[language.toLowerCase()] || 'txt'
    await ipc.saveFile?.({
      content: code,
      defaultName: `code.${extension}`,
      extension,
    })
  }

  return (
    <div className="relative my-2 rounded-lg overflow-hidden bg-zinc-900">
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-2 bg-zinc-800">
        <span className="text-xs text-zinc-400 font-mono">{language}</span>
        <div className="flex items-center gap-1">
          {/* 复制按钮 */}
          <button
            onClick={handleCopy}
            className={cn(
              'p-1.5 rounded hover:bg-zinc-700 transition-colors',
              'text-zinc-400 hover:text-zinc-200'
            )}
            title="复制代码"
          >
            {copied ? (
              <Check className="w-4 h-4 text-green-500" />
            ) : (
              <Copy className="w-4 h-4" />
            )}
          </button>
          
          {/* 保存按钮 */}
          <button
            onClick={handleSave}
            className={cn(
              'p-1.5 rounded hover:bg-zinc-700 transition-colors',
              'text-zinc-400 hover:text-zinc-200'
            )}
            title="保存为文件"
          >
            <Download className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* 代码内容 */}
      <pre className="p-4 overflow-x-auto">
        <code className="text-sm text-zinc-100 font-mono whitespace-pre">
          {code}
        </code>
      </pre>
    </div>
  )
}
