import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { listDomains, getDomainReadiness, updateTargetDomain } = vi.hoisted(() => ({
  listDomains: vi.fn(),
  getDomainReadiness: vi.fn(),
  updateTargetDomain: vi.fn(),
}))

vi.mock('@/api/domains', () => ({ listDomains, getDomainReadiness }))
vi.mock('@/api/learners', () => ({ updateTargetDomain }))

import { useDomainStore } from './domainStore'

describe('domainStore runtime selection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    listDomains.mockReset()
    getDomainReadiness.mockReset()
    updateTargetDomain.mockReset()
    listDomains.mockResolvedValue([
      { domain_code: 'domain_a', name: '领域 A', status: 'ready' },
      { domain_code: 'domain_b', name: '领域 B', status: 'ready' },
    ])
    updateTargetDomain.mockResolvedValue({ domain_changed: true })
  })

  it('loads the selected workspace domain without fetching admin readiness', async () => {
    const store = useDomainStore()
    await store.initialize('domain_a')

    expect(store.currentDomainName).toBe('领域 A')
    expect(store.selectionVersion).toBe(1)
    expect(getDomainReadiness).not.toHaveBeenCalled()

    await store.selectForLearner('learner_a', 'domain_b')
    expect(updateTargetDomain).toHaveBeenCalledWith('learner_a', 'domain_b')
    expect(store.currentDomainName).toBe('领域 B')
    expect(store.selectionVersion).toBe(2)
  })
})
