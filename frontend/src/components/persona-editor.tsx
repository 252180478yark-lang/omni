'use client'

import React, { useEffect, useState } from 'react'
import type { Persona } from '@/lib/personas/types'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'

interface PersonaEditorProps {
  initial?: Partial<Persona> | null
  onSave: (data: {
    name: string
    icon: string
    description: string
    systemPrompt: string
    exampleQueries: string[]
  }) => void
  onCancel: () => void
}

export function PersonaEditor({ initial, onSave, onCancel }: PersonaEditorProps) {
  const [name, setName] = useState(initial?.name ?? '')
  const [icon, setIcon] = useState(initial?.icon ?? '🔧')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [systemPrompt, setSystemPrompt] = useState(initial?.systemPrompt ?? '')
  const [examplesText, setExamplesText] = useState(
    (initial?.exampleQueries ?? []).join('\n'),
  )

  useEffect(() => {
    setName(initial?.name ?? '')
    setIcon(initial?.icon ?? '🔧')
    setDescription(initial?.description ?? '')
    setSystemPrompt(initial?.systemPrompt ?? '')
    setExamplesText((initial?.exampleQueries ?? []).join('\n'))
  }, [initial])

  const handleSave = () => {
    const exampleQueries = examplesText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
    onSave({ name: name.trim(), icon: icon.trim() || '🔧', description: description.trim(), systemPrompt, exampleQueries })
  }

  return (
    <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <div className="text-xs text-gray-500 mb-1">角色名称</div>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="名称" />
        </div>
        <div>
          <div className="text-xs text-gray-500 mb-1">图标 (emoji)</div>
          <Input value={icon} onChange={(e) => setIcon(e.target.value)} placeholder="🔧" />
        </div>
      </div>
      <div>
        <div className="text-xs text-gray-500 mb-1">角色描述</div>
        <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="一行简介" />
      </div>
      <div>
        <div className="text-xs text-gray-500 mb-1">System Prompt</div>
        <Textarea
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          rows={10}
          className="font-mono text-xs"
          placeholder="你是一位..."
        />
      </div>
      <div>
        <div className="text-xs text-gray-500 mb-1">示例问题（每行一个）</div>
        <Textarea
          value={examplesText}
          onChange={(e) => setExamplesText(e.target.value)}
          rows={4}
          className="text-sm"
          placeholder="问题1&#10;问题2"
        />
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          取消
        </Button>
        <Button type="button" onClick={handleSave} disabled={!name.trim()}>
          保存
        </Button>
      </div>
    </div>
  )
}
