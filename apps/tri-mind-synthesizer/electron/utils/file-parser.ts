/**
 * 文件解析器
 * 
 * 支持解析以下文件类型：
 * - 纯文本: .txt, .md
 * - 代码: .py, .js, .ts, .rs, .go, .java, .json, .csv 等
 * - PDF: 提取文本内容
 * 
 * 解析后的内容以 [FILE:filename.ext] 标签包裹，
 * 追加到用户消息中分发给所有模型。
 */

import fs from 'fs/promises'
import path from 'path'
import { FileAttachment } from '../../src/lib/types'

// 支持的文件扩展名
const SUPPORTED_EXTENSIONS = new Set([
  '.pdf', '.txt', '.md',
  '.py', '.js', '.ts', '.jsx', '.tsx',
  '.rs', '.go', '.java', '.json', '.csv',
  '.c', '.cpp', '.h', '.hpp',
  '.rb', '.php', '.swift', '.kt',
  '.html', '.css', '.scss', '.xml', '.yaml', '.yml',
  '.sql', '.sh', '.bash', '.zsh',
  '.toml', '.ini', '.cfg', '.env',
])

// 代码文件扩展名到语言的映射
const LANGUAGE_MAP: Record<string, string> = {
  '.js': 'javascript',
  '.ts': 'typescript',
  '.jsx': 'jsx',
  '.tsx': 'tsx',
  '.py': 'python',
  '.rs': 'rust',
  '.go': 'go',
  '.java': 'java',
  '.json': 'json',
  '.csv': 'csv',
  '.c': 'c',
  '.cpp': 'cpp',
  '.h': 'c',
  '.hpp': 'cpp',
  '.rb': 'ruby',
  '.php': 'php',
  '.swift': 'swift',
  '.kt': 'kotlin',
  '.html': 'html',
  '.css': 'css',
  '.scss': 'scss',
  '.xml': 'xml',
  '.yaml': 'yaml',
  '.yml': 'yaml',
  '.sql': 'sql',
  '.sh': 'bash',
  '.bash': 'bash',
  '.md': 'markdown',
  '.toml': 'toml',
}

/**
 * 检查文件扩展名是否受支持
 */
export function isSupportedFile(filename: string): boolean {
  const ext = path.extname(filename).toLowerCase()
  return SUPPORTED_EXTENSIONS.has(ext)
}

/**
 * 判断是否为代码文件
 */
export function isCodeFile(filename: string): boolean {
  const ext = path.extname(filename).toLowerCase()
  return ext in LANGUAGE_MAP && ext !== '.md' && ext !== '.txt'
}

/**
 * 获取文件的编程语言标识
 */
export function getLanguage(filename: string): string {
  const ext = path.extname(filename).toLowerCase()
  return LANGUAGE_MAP[ext] || 'text'
}

/**
 * 解析单个文件
 * 
 * @param filePath 文件绝对路径
 * @returns FileAttachment 对象
 */
export async function parseFile(filePath: string): Promise<FileAttachment> {
  const filename = path.basename(filePath)
  const ext = path.extname(filePath).toLowerCase()

  if (!isSupportedFile(filename)) {
    throw new Error(`不支持的文件类型: ${ext}`)
  }

  let content: string
  let type: string

  if (ext === '.pdf') {
    content = await parsePDF(filePath)
    type = 'pdf'
  } else if (isCodeFile(filename)) {
    content = await parseCodeFile(filePath)
    type = 'code'
  } else {
    content = await parseTextFile(filePath)
    type = 'text'
  }

  return { name: filename, content, type }
}

/**
 * 批量解析多个文件
 */
export async function parseFiles(filePaths: string[]): Promise<FileAttachment[]> {
  const results: FileAttachment[] = []
  
  for (const filePath of filePaths) {
    try {
      const attachment = await parseFile(filePath)
      results.push(attachment)
    } catch (error) {
      console.warn(`跳过无法解析的文件 ${filePath}:`, error)
    }
  }

  return results
}

/**
 * 解析纯文本文件
 */
async function parseTextFile(filePath: string): Promise<string> {
  const content = await fs.readFile(filePath, 'utf-8')
  return content
}

/**
 * 解析代码文件，以 Markdown 代码块形式包裹
 */
async function parseCodeFile(filePath: string): Promise<string> {
  const content = await fs.readFile(filePath, 'utf-8')
  const lang = getLanguage(path.basename(filePath))
  return `\`\`\`${lang}\n${content}\n\`\`\``
}

/**
 * 解析 PDF 文件
 * 
 * 使用简易文本提取（不依赖重量级 PDF 库）。
 * 对于复杂 PDF，建议用户直接复制文本内容。
 */
async function parsePDF(filePath: string): Promise<string> {
  try {
    const buffer = await fs.readFile(filePath)
    const text = extractTextFromPDF(buffer)
    
    if (!text.trim()) {
      return '[PDF 文件内容为空或无法提取文本。建议复制 PDF 中的文本内容并直接粘贴。]'
    }
    
    return text
  } catch (error) {
    return `[PDF 解析失败: ${String(error)}。建议复制 PDF 中的文本内容并直接粘贴。]`
  }
}

/**
 * 简易 PDF 文本提取
 * 从 PDF 二进制数据中提取可见文本（基于文本流解析）
 */
function extractTextFromPDF(buffer: Buffer): string {
  const content = buffer.toString('latin1')
  const texts: string[] = []

  // 匹配 PDF 文本流中的字符串
  // 匹配 (text) 格式的 PDF 字符串
  const textPattern = /\(([^)]*)\)/g
  let match

  // 查找所有 BT...ET 文本块
  const textBlocks = content.match(/BT[\s\S]*?ET/g) || []
  
  for (const block of textBlocks) {
    while ((match = textPattern.exec(block)) !== null) {
      const text = match[1]
      // 过滤掉非文本内容（二进制数据）
      if (text && /[\x20-\x7e\u4e00-\u9fa5]/.test(text)) {
        texts.push(decodePDFText(text))
      }
    }
  }

  return texts.join(' ').replace(/\s+/g, ' ').trim()
}

/**
 * 解码 PDF 文本转义序列
 */
function decodePDFText(text: string): string {
  return text
    .replace(/\\n/g, '\n')
    .replace(/\\r/g, '\r')
    .replace(/\\t/g, '\t')
    .replace(/\\\\/g, '\\')
    .replace(/\\([()])/g, '$1')
}

/**
 * 将 FileAttachment 数组格式化为用户消息内容
 */
export function formatFilesAsContext(files: FileAttachment[]): string {
  if (files.length === 0) return ''

  const parts: string[] = ['以下是用户提供的参考文件：\n']

  for (const file of files) {
    parts.push(`[FILE: ${file.name}]`)
    parts.push(file.content)
    parts.push(`[/FILE: ${file.name}]\n`)
  }

  return parts.join('\n')
}

/**
 * 获取所有支持的文件扩展名列表
 */
export function getSupportedExtensions(): string[] {
  return Array.from(SUPPORTED_EXTENSIONS)
}
