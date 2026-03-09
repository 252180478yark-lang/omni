'use client'

import { useEffect } from 'react'
import { useChatStore } from '@/stores/tri-mind/chatStore'
import { useUIStore } from '@/stores/tri-mind/uiStore'

export function useAppShortcuts() {
  const { isGenerating, stopGeneration, verdictContent } = useChatStore()
  const { setSettingsOpen } = useUIStore()

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === 'Enter') {
        e.preventDefault()
        window.dispatchEvent(new CustomEvent('app:send-message'))
      }
      if (e.key === 'Escape' && isGenerating) {
        e.preventDefault()
        stopGeneration()
      }
      if (e.ctrlKey && e.key === ',') {
        e.preventDefault()
        setSettingsOpen(true)
      }
      if (e.ctrlKey && e.shiftKey && e.key === 'E') {
        e.preventDefault()
        if (verdictContent) {
          const blob = new Blob([verdictContent], { type: 'text/markdown' })
          const url = URL.createObjectURL(blob)
          const a = document.createElement('a')
          a.href = url
          a.download = 'debate-verdict.md'
          a.click()
          URL.revokeObjectURL(url)
        }
      }
      if (e.ctrlKey && e.key === 'n') {
        e.preventDefault()
        window.dispatchEvent(new CustomEvent('app:new-session'))
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isGenerating, stopGeneration, setSettingsOpen, verdictContent])
}
