import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import {
  buildCodexSpawnArgs,
  CODEX_SPAWN_WITH_SHELL,
  resolveCodexCommand,
  resolveCodexCwd,
} from '@/lib/agent-chat/codex-runner'

const tempRoots: string[] = []

afterEach(() => {
  for (const root of tempRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})

describe('codex-runner', () => {
  describe('buildCodexSpawnArgs', () => {
    it('passes model and model_reasoning_effort to codex exec args', () => {
      const args = buildCodexSpawnArgs({
        prompt: 'review this change',
        model: 'gpt-5.5',
        effort: 'high',
      })

      expect(args.slice(0, 2)).toEqual(['exec', '--json'])
      expect(args).toContain('--model')
      expect(args[args.indexOf('--model') + 1]).toBe('gpt-5.5')
      expect(args).toContain('--config')
      expect(args[args.indexOf('--config') + 1]).toBe('model_reasoning_effort="high"')
      expect(args[args.length - 1]).toBe('review this change')
    })

    it('passes the resolved project cwd to a new Codex task', () => {
      const args = buildCodexSpawnArgs({
        prompt: 'implement the feature',
        cwd: 'E:\\agent\\omni',
      })

      expect(args.slice(args.indexOf('-C'), args.indexOf('-C') + 2)).toEqual([
        '-C',
        'E:\\agent\\omni',
      ])
    })
  })

  describe('resolveCodexCwd', () => {
    it('prefers the explicit spawn cwd, then OMNI_PROJECT_DIR', () => {
      const root = mkdtempSync(join(tmpdir(), 'omni-codex-priority-'))
      tempRoots.push(root)
      const explicit = join(root, 'explicit')
      const configured = join(root, 'configured')
      for (const project of [explicit, configured]) {
        mkdirSync(project)
        writeFileSync(join(project, 'AGENTS.md'), '# test')
      }

      expect(resolveCodexCwd(explicit, configured, root)).toBe(explicit)
      expect(resolveCodexCwd(undefined, configured, root)).toBe(configured)
    })

    it('finds the sibling omni repository before falling back to process cwd', () => {
      const root = mkdtempSync(join(tmpdir(), 'omni-codex-cwd-'))
      tempRoots.push(root)
      const systemRoot = join(root, 'omni-system')
      const projectRoot = join(root, 'omni')
      mkdirSync(systemRoot)
      mkdirSync(projectRoot)
      writeFileSync(join(projectRoot, 'AGENTS.md'), '# test')

      expect(resolveCodexCwd(undefined, undefined, join(root, 'launcher'), systemRoot)).toBe(
        projectRoot,
      )
    })

    it('fails closed when an explicit project root cannot load AGENTS.md', () => {
      const root = mkdtempSync(join(tmpdir(), 'omni-codex-bad-cwd-'))
      tempRoots.push(root)

      expect(() => resolveCodexCwd(join(root, 'missing'), '', root, root)).toThrow(
        'must be an existing project directory with AGENTS.md',
      )
    })
  })

  describe('resolveCodexCommand', () => {
    it('ignores a stale configured path and finds the bundled desktop executable', () => {
      const root = mkdtempSync(join(tmpdir(), 'omni-codex-command-'))
      tempRoots.push(root)
      const systemRoot = join(root, 'omni-system')
      const bundledExecutable = join(root, '.codex', 'app', 'resources', 'codex.exe')
      mkdirSync(systemRoot)
      mkdirSync(join(root, '.codex', 'app', 'resources'), { recursive: true })
      writeFileSync(bundledExecutable, '')

      expect(
        resolveCodexCommand(
          true,
          join(root, 'missing', 'codex.cmd'),
          systemRoot,
          join(root, 'local-app-data'),
        ),
      ).toBe(bundledExecutable)
    })

    it('keeps a PATH-resolved command name and uses codex.exe as the Windows fallback', () => {
      expect(resolveCodexCommand(true, 'codex-custom')).toBe('codex-custom')
      expect(
        resolveCodexCommand(
          true,
          '',
          join(tmpdir(), 'missing-omni-system'),
          join(tmpdir(), 'missing-local-app-data'),
        ),
      ).toBe('codex.exe')
    })

    it('does not select a Windows batch shim that would require shell execution', () => {
      expect(
        resolveCodexCommand(
          true,
          'codex.cmd',
          join(tmpdir(), 'missing-omni-system'),
          join(tmpdir(), 'missing-local-app-data'),
        ),
      ).toBe('codex.exe')
    })
  })

  it('spawns Codex without a shell so prompts stay argv data', () => {
    expect(CODEX_SPAWN_WITH_SHELL).toBe(false)
  })
})
