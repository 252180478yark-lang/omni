'use client'

import { create } from 'zustand'

type Theme = 'light' | 'dark' | 'system'
type SettingsTab = 'models' | 'rates' | 'general'

interface UIState {
  sidebarOpen: boolean
  settingsOpen: boolean
  settingsTab: SettingsTab
  theme: Theme
  toggleSidebar: () => void
  setSettingsOpen: (open: boolean) => void
  setSettingsTab: (tab: SettingsTab) => void
  setTheme: (theme: Theme) => void
}

export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: true,
  settingsOpen: false,
  settingsTab: 'models',
  theme: 'light',
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSettingsOpen: (open) => set({ settingsOpen: open }),
  setSettingsTab: (tab) => set({ settingsTab: tab }),
  setTheme: (theme) => set({ theme }),
}))
