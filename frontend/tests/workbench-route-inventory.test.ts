import { readdirSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import { describe, expect, it } from 'vitest'

import { FEATURE_REGISTRY, resolveFeatureSurface } from '@/lib/feature-registry'

function filesBelow(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = join(root, entry.name)
    return entry.isDirectory() ? filesBelow(path) : [path]
  })
}

function pageRoutes(): string[] {
  const root = join(process.cwd(), 'src', 'app')
  return filesBelow(root)
    .filter((path) => path.endsWith(`${sep}page.tsx`))
    .map((path) => {
      const value = relative(root, path).split(sep).join('/').replace(/\/page\.tsx$/, '')
      return value === 'page.tsx' ? '/' : `/${value}`
    })
    .sort()
}

describe('workbench route inventory', () => {
  it('partitions all 45 Next pages and permits non-page compatibility aliases', () => {
    const pages = pageRoutes()
    const owned = FEATURE_REGISTRY.flatMap((entry) => entry.owned_surfaces)
    const aliases = FEATURE_REGISTRY.flatMap((entry) => entry.aliases.map((alias) => alias.href))

    expect(pages).toHaveLength(45)
    expect(owned).toHaveLength(44)
    expect(aliases).toEqual(['/marketing/review', '/qa'])
    expect(new Set(owned).size).toBe(owned.length)
    expect(new Set(aliases).size).toBe(aliases.length)
    expect(owned.filter((href) => aliases.includes(href))).toEqual([])
    expect([...owned, ...aliases.filter((href) => pages.includes(href))].sort()).toEqual(pages)
  })

  it('requires every alias to target its owning feature canonical in one hop', () => {
    const canonicalOwner = new Map(FEATURE_REGISTRY.map((entry) => [entry.href, entry.feature_id]))
    for (const entry of FEATURE_REGISTRY) {
      for (const alias of entry.aliases) {
        expect(canonicalOwner.get(alias.target)).toBe(entry.feature_id)
        expect(FEATURE_REGISTRY.some((candidate) => candidate.aliases.some((item) => item.href === alias.target))).toBe(false)
        expect(resolveFeatureSurface(alias.href)).toMatchObject({
          kind: 'alias',
          canonicalHref: alias.target,
          featureId: entry.feature_id,
        })
      }
    }
  })

  it('keeps every physical page resolvable and never reports an ambiguous owner', () => {
    for (const route of pageRoutes()) {
      const sample = route.replace(/\[([^\]]+)\]/g, 'sample-$1')
      expect(resolveFeatureSurface(sample).kind).not.toBe('ambiguous')
      expect(resolveFeatureSurface(sample).kind).not.toBe('unregistered')
    }
  })
})
