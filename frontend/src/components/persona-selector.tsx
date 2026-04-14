'use client'

import React, { useState } from 'react'
import { ChevronDown, Settings2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { usePersonaStore } from '@/stores/personaStore'
import { PRESET_PERSONA_IDS } from '@/lib/personas/preset-personas'
import { PersonaManager } from '@/components/persona-manager'

export function PersonaSelector() {
  const { personas, selectedPersonaId, selectPersona } = usePersonaStore()
  const [open, setOpen] = useState(false)
  const [managerOpen, setManagerOpen] = useState(false)

  const presetSet = new Set(PRESET_PERSONA_IDS as unknown as string[])
  const presetPersonas = PRESET_PERSONA_IDS.map((id) => personas.find((p) => p.id === id)).filter(
    Boolean,
  ) as typeof personas
  const customPersonas = personas.filter((p) => !presetSet.has(p.id))

  const selected = selectedPersonaId ? personas.find((p) => p.id === selectedPersonaId) : null

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger
            type="button"
            className="flex items-center gap-2 min-w-[200px] max-w-[280px] px-3 py-2 text-sm rounded-xl border border-gray-200 bg-white/90 hover:bg-white shadow-sm text-left"
          >
            <span className="text-lg shrink-0">{selected?.icon || '💬'}</span>
            <span className="truncate flex-1 font-medium text-gray-800">
              {selected ? selected.name : '无角色 / 通用助手'}
            </span>
            <ChevronDown className="w-4 h-4 text-gray-400 shrink-0" />
          </PopoverTrigger>
          <PopoverContent className="w-80 p-0" align="start">
            <div className="max-h-80 overflow-auto py-1">
              <button
                type="button"
                onClick={() => {
                  selectPersona(null)
                  setOpen(false)
                }}
                className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-50 flex items-center gap-2 ${
                  !selectedPersonaId ? 'bg-blue-50 text-blue-800' : ''
                }`}
              >
                <span>💬</span>
                <span>无角色 / 通用助手</span>
              </button>
              <div className="border-t border-gray-100 my-1" />
              {presetPersonas.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => {
                    selectPersona(p.id)
                    setOpen(false)
                  }}
                  className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-50 flex items-start gap-2 ${
                    selectedPersonaId === p.id ? 'bg-blue-50 text-blue-800' : ''
                  }`}
                >
                  <span className="text-lg shrink-0">{p.icon}</span>
                  <span className="min-w-0">
                    <span className="font-medium block">{p.name}</span>
                    <span className="text-xs text-gray-500 line-clamp-2">{p.description}</span>
                  </span>
                </button>
              ))}
              {customPersonas.length > 0 && (
                <>
                  <div className="border-t border-gray-100 my-1" />
                  {customPersonas.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => {
                        selectPersona(p.id)
                        setOpen(false)
                      }}
                      className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-50 flex items-start gap-2 ${
                        selectedPersonaId === p.id ? 'bg-blue-50 text-blue-800' : ''
                      }`}
                    >
                      <span className="text-lg shrink-0">{p.icon}</span>
                      <span className="min-w-0">
                        <span className="font-medium block">{p.name}</span>
                        <span className="text-xs text-gray-500 line-clamp-2">{p.description}</span>
                      </span>
                    </button>
                  ))}
                </>
              )}
            </div>
            <div className="border-t border-gray-100 p-2">
              <Button
                variant="outline"
                size="sm"
                className="w-full gap-2"
                onClick={() => {
                  setOpen(false)
                  setManagerOpen(true)
                }}
              >
                <Settings2 className="w-3.5 h-3.5" />
                管理角色
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      </div>

      <PersonaManager open={managerOpen} onOpenChange={setManagerOpen} />
    </>
  )
}
