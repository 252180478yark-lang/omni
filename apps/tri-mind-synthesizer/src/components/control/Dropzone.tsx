import { useState, useRef, useCallback } from 'react'
import { Upload, X, FileText, Code, FileType } from 'lucide-react'
import { cn } from '../../lib/utils'
import { FileAttachment } from '../../lib/types'

/**
 * 支持的文件扩展名
 */
const SUPPORTED_EXTENSIONS = [
  '.pdf', '.txt', '.md',
  '.py', '.js', '.ts', '.jsx', '.tsx',
  '.rs', '.go', '.java', '.json', '.csv',
  '.c', '.cpp', '.h', '.hpp',
  '.html', '.css', '.xml', '.yaml', '.yml',
  '.sql', '.sh',
]

const ACCEPT_STRING = SUPPORTED_EXTENSIONS.join(',')

interface DropzoneProps {
  files: FileAttachment[]
  onFilesChange: (files: FileAttachment[]) => void
  disabled?: boolean
}

/**
 * 文件拖拽上传区域
 * 
 * 支持：
 * - 拖拽上传
 * - 点击选择文件
 * - 多文件同时上传
 * - 文件列表管理（删除已添加的文件）
 */
export function Dropzone({ files, onFilesChange, disabled = false }: DropzoneProps) {
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!disabled) setIsDragOver(true)
  }, [disabled])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)
  }, [])

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)

    if (disabled) return

    const droppedFiles = Array.from(e.dataTransfer.files)
    await processFiles(droppedFiles)
  }, [disabled, files, onFilesChange])

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const selected = Array.from(e.target.files)
      await processFiles(selected)
    }
    // 重置 input 以便再次选择相同文件
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }, [files, onFilesChange])

  const processFiles = async (newFiles: File[]) => {
    const attachments: FileAttachment[] = [...files]

    for (const file of newFiles) {
      // 检查扩展名
      const ext = '.' + file.name.split('.').pop()?.toLowerCase()
      if (!SUPPORTED_EXTENSIONS.includes(ext)) {
        console.warn(`不支持的文件类型: ${file.name}`)
        continue
      }

      // 检查大小限制 (10MB)
      if (file.size > 10 * 1024 * 1024) {
        console.warn(`文件过大: ${file.name} (${(file.size / 1024 / 1024).toFixed(1)}MB)`)
        continue
      }

      // 检查是否已添加
      if (attachments.some(f => f.name === file.name)) {
        continue
      }

      try {
        const content = await file.text()
        const type = getFileType(file.name)
        attachments.push({ name: file.name, content, type })
      } catch (error) {
        console.error(`读取文件失败: ${file.name}`, error)
      }
    }

    onFilesChange(attachments)
  }

  const removeFile = (filename: string) => {
    onFilesChange(files.filter(f => f.name !== filename))
  }

  const getFileIcon = (type: string) => {
    switch (type) {
      case 'code': return <Code className="w-4 h-4 text-blue-400" />
      case 'pdf': return <FileType className="w-4 h-4 text-red-400" />
      default: return <FileText className="w-4 h-4 text-gray-500" />
    }
  }

  return (
    <div className="space-y-2">
      {/* 拖拽区域 */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => !disabled && fileInputRef.current?.click()}
        className={cn(
          'border-2 border-dashed rounded-xl p-3 transition-colors cursor-pointer',
          'flex items-center justify-center gap-2',
          isDragOver
            ? 'border-blue-500 bg-blue-50/50'
            : 'border-gray-300 hover:border-gray-400',
          disabled && 'opacity-50 cursor-not-allowed'
        )}
      >
        <Upload className="w-4 h-4 text-gray-500" />
        <span className="text-sm text-gray-500">
          拖拽文件到此处或点击选择
        </span>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPT_STRING}
          onChange={handleFileSelect}
          className="hidden"
        />
      </div>

      {/* 已添加的文件列表 */}
      {files.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {files.map((file) => (
            <div
              key={file.name}
              className={cn(
                'flex items-center gap-1.5 px-2 py-1 rounded-lg',
                'bg-gray-100 text-sm'
              )}
            >
              {getFileIcon(file.type)}
              <span className="max-w-[120px] truncate">{file.name}</span>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  removeFile(file.name)
                }}
                className="p-0.5 rounded hover:bg-red-100 text-gray-500 hover:text-red-500 transition-colors"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * 根据文件名判断文件类型
 */
function getFileType(filename: string): string {
  const ext = '.' + filename.split('.').pop()?.toLowerCase()
  if (ext === '.pdf') return 'pdf'
  const codeExts = ['.js', '.ts', '.jsx', '.tsx', '.py', '.rs', '.go', '.java', '.json', '.c', '.cpp', '.h', '.hpp', '.rb', '.php', '.swift', '.kt', '.html', '.css', '.scss', '.xml', '.sql', '.sh']
  if (codeExts.includes(ext)) return 'code'
  return 'text'
}
