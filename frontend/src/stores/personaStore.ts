'use client'

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { v4 as uuidv4 } from 'uuid'
import type { Persona } from '@/lib/personas/types'
import { PRESET_PERSONAS, getDefaultPresetById } from '@/lib/personas/preset-personas'

function mergePersonaLists(stored: Persona[] | undefined): Persona[] {
  if (!stored?.length) return [...PRESET_PERSONAS]
  const presetIds = new Set(PRESET_PERSONAS.map((p) => p.id))
  const mergedPresets = PRESET_PERSONAS.map((bp) => {
    const s = stored.find((x) => x.id === bp.id && x.isPreset)
    return s ?? bp
  })
  const customs = stored.filter((x) => !presetIds.has(x.id))
  return [...mergedPresets, ...customs]
}

export interface PersonaState {
  personas: Persona[]
  selectedPersonaId: string | null

  selectPersona: (id: string | null) => void
  createPersona: (data: Omit<Persona, 'id' | 'isPreset' | 'createdAt' | 'updatedAt'>) => void
  updatePersona: (id: string, data: Partial<Persona>) => void
  deletePersona: (id: string) => void
  resetPresetPrompt: (id: string) => void
  getSelectedPersona: () => Persona | null
  getPersonaById: (id: string) => Persona | undefined
}

export const usePersonaStore = create<PersonaState>()(
  persist(
    (set, get) => ({
      personas: [...PRESET_PERSONAS],
      selectedPersonaId: null,

      selectPersona: (id) => set({ selectedPersonaId: id }),

      createPersona: (data) => {
        const now = Date.now()
        const newPersona: Persona = {
          ...data,
          id: uuidv4(),
          isPreset: false,
          createdAt: now,
          updatedAt: now,
        }
        set((state) => ({
          personas: [...state.personas, newPersona],
        }))
      },

      updatePersona: (id, data) => {
        set((state) => ({
          personas: state.personas.map((p) =>
            p.id === id ? { ...p, ...data, updatedAt: Date.now() } : p,
          ),
        }))
      },

      deletePersona: (id) => {
        const persona = get().personas.find((p) => p.id === id)
        if (persona?.isPreset) return
        set((state) => ({
          personas: state.personas.filter((p) => p.id !== id),
          selectedPersonaId:
            state.selectedPersonaId === id ? null : state.selectedPersonaId,
        }))
      },

      resetPresetPrompt: (id) => {
        const preset = getDefaultPresetById(id)
        if (!preset) return
        set((state) => ({
          personas: state.personas.map((p) =>
            p.id === id
              ? {
                  ...p,
                  systemPrompt: preset.systemPrompt,
                  exampleQueries: [...preset.exampleQueries],
                  name: preset.name,
                  description: preset.description,
                  icon: preset.icon,
                  updatedAt: Date.now(),
                }
              : p,
          ),
        }))
      },

      getSelectedPersona: () => {
        const { personas, selectedPersonaId } = get()
        if (!selectedPersonaId) return null
        return personas.find((p) => p.id === selectedPersonaId) ?? null
      },

      getPersonaById: (id) => get().personas.find((p) => p.id === id),
    }),
    {
      name: 'omni-persona-store',
      version: 1,
      partialize: (s) => ({
        personas: s.personas,
        selectedPersonaId: s.selectedPersonaId,
      }),
      merge: (persisted, current) => {
        const p = persisted as Partial<Pick<PersonaState, 'personas' | 'selectedPersonaId'>>
        return {
          ...current,
          selectedPersonaId:
            p.selectedPersonaId !== undefined ? p.selectedPersonaId : current.selectedPersonaId,
          personas: mergePersonaLists(p.personas),
        }
      },
    },
  ),
)
