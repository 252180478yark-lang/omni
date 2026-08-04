export type WorkbenchFlagName = 'unified_shell'

export interface WorkbenchFlagSource {
  unified_shell?: string | boolean | null
}

export interface WorkbenchFlags {
  unifiedShell: boolean
}

const DEFAULT_SOURCE: WorkbenchFlagSource = {
  // Keep this as a direct reference so Next can inline the same public build flag
  // in middleware and in the browser bundle.
  unified_shell: process.env.NEXT_PUBLIC_OMNI_UNIFIED_SHELL,
}

const DISABLED_VALUES = new Set(['0', 'false', 'off', 'no'])

function enabled(value: string | boolean | null | undefined): boolean {
  if (typeof value === 'boolean') return value
  if (value == null || value.trim() === '') return true
  return !DISABLED_VALUES.has(value.trim().toLowerCase())
}

export function workbenchFlags(source: WorkbenchFlagSource = DEFAULT_SOURCE): WorkbenchFlags {
  return {
    unifiedShell: enabled(source.unified_shell),
  }
}

export function isWorkbenchFlagEnabled(
  name: WorkbenchFlagName,
  source: WorkbenchFlagSource = DEFAULT_SOURCE,
): boolean {
  if (name === 'unified_shell') return workbenchFlags(source).unifiedShell
  return false
}
