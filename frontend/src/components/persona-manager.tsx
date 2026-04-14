'use client'

import React, { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { usePersonaStore } from '@/stores/personaStore'
import { PRESET_PERSONA_IDS } from '@/lib/personas/preset-personas'
import type { Persona } from '@/lib/personas/types'
import { PersonaEditor } from '@/components/persona-editor'

interface PersonaManagerProps {
  open: boolean
  onOpenChange: (v: boolean) => void
}

export function PersonaManager({ open, onOpenChange }: PersonaManagerProps) {
  const { personas, createPersona, updatePersona, deletePersona, resetPresetPrompt } =
    usePersonaStore()

  const presetSet = new Set(PRESET_PERSONA_IDS as unknown as string[])
  const presetPersonas = PRESET_PERSONA_IDS.map((id) => personas.find((p) => p.id === id)).filter(
    Boolean,
  ) as Persona[]
  const customPersonas = personas.filter((p) => !presetSet.has(p.id))

  const [editorOpen, setEditorOpen] = useState(false)
  const [editorMode, setEditorMode] = useState<'create' | 'edit'>('create')
  const [editing, setEditing] = useState<Persona | null>(null)

  const openCreate = () => {
    setEditing(null)
    setEditorMode('create')
    setEditorOpen(true)
  }

  const openEdit = (p: Persona) => {
    setEditing(p)
    setEditorMode('edit')
    setEditorOpen(true)
  }

  const handleSave = (data: {
    name: string
    icon: string
    description: string
    systemPrompt: string
    exampleQueries: string[]
  }) => {
    if (editorMode === 'create') {
      createPersona({
        name: data.name,
        icon: data.icon,
        description: data.description,
        systemPrompt: data.systemPrompt,
        exampleQueries: data.exampleQueries,
      })
    } else if (editing) {
      updatePersona(editing.id, {
        name: data.name,
        icon: data.icon,
        description: data.description,
        systemPrompt: data.systemPrompt,
        exampleQueries: data.exampleQueries,
      })
    }
    setEditorOpen(false)
    setEditing(null)
  }

  const handleDelete = (p: Persona) => {
    if (p.isPreset) return
    if (!window.confirm(`确定删除角色「${p.name}」？`)) return
    deletePersona(p.id)
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle>角色管理</DialogTitle>
          </DialogHeader>
          <div className="overflow-y-auto flex-1 space-y-4 pr-1">
            <div>
              <div className="text-xs font-semibold text-gray-500 mb-2">预设角色</div>
              <div className="space-y-2">
                {presetPersonas.map((p) => (
                  <div
                    key={p.id}
                    className="flex items-center justify-between gap-2 py-2 border-b border-gray-100"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-lg">{p.icon}</span>
                      <span className="text-sm font-medium truncate">{p.name}</span>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <Button size="sm" variant="outline" onClick={() => openEdit(p)}>
                        编辑 Prompt
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => resetPresetPrompt(p.id)}>
                        恢复默认
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <div className="text-xs font-semibold text-gray-500 mb-2">自建角色</div>
              {customPersonas.length === 0 && (
                <p className="text-sm text-gray-400 py-2">暂无自建角色</p>
              )}
              <div className="space-y-2">
                {customPersonas.map((p) => (
                  <div
                    key={p.id}
                    className="flex items-center justify-between gap-2 py-2 border-b border-gray-100"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-lg">{p.icon}</span>
                      <span className="text-sm font-medium truncate">{p.name}</span>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <Button size="sm" variant="outline" onClick={() => openEdit(p)}>
                        编辑
                      </Button>
                      <Button size="sm" variant="destructive" onClick={() => handleDelete(p)}>
                        删除
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <Button className="w-full" variant="secondary" onClick={openCreate}>
              + 创建新角色
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle>{editorMode === 'create' ? '创建角色' : '编辑角色'}</DialogTitle>
          </DialogHeader>
          <PersonaEditor
            initial={editing}
            onSave={handleSave}
            onCancel={() => setEditorOpen(false)}
          />
        </DialogContent>
      </Dialog>
    </>
  )
}
