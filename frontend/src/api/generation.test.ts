import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getData, postData } from './client'
import { createGenerationTask, getActiveGenerationTask } from './generation'

vi.mock('./client', () => ({
  getData: vi.fn(),
  postData: vi.fn(),
}))

describe('generation task API', () => {
  beforeEach(() => {
    vi.mocked(getData).mockReset()
    vi.mocked(postData).mockReset()
  })

  it('queries the active task for the encoded learner id', async () => {
    vi.mocked(getData).mockResolvedValue(null)

    await getActiveGenerationTask('learner demo/1')

    expect(getData).toHaveBeenCalledWith(
      '/generation-tasks/active?learner_id=learner%20demo%2F1',
    )
  })

  it('forwards a retry idempotency key for the same generation action', () => {
    const options = { idempotencyKey: 'generation-retry-001' }

    createGenerationTask('profile_001', 'learner_001', '生成个性化学习资源', options)

    expect(postData).toHaveBeenCalledWith(
      '/generation-tasks',
      expect.objectContaining({
        learner_id: 'learner_001',
        profile_id: 'profile_001',
      }),
      options,
    )
  })
})
