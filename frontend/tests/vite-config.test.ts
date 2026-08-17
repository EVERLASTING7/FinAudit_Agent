import { describe, expect, it } from 'vitest'

import { resolveEnvDir } from '../vite-env-policy.ts'

describe('Vite 离线质量门禁', () => {
  it('只在显式离线标志下禁用 .env 文件加载', () => {
    expect(resolveEnvDir('1')).toBe(false)
    expect(resolveEnvDir(undefined)).toBeUndefined()
    expect(resolveEnvDir('0')).toBeUndefined()
  })
})
