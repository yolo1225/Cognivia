import { describe, expect, it } from 'vitest'
import type { GenerationTaskDetail } from '@/api/generation'
import type { ResourceSummary } from '@/api/resources'
import { getDashboardState } from './dashboardState'
import type { LearningAdjustmentSummary } from '@/api/learningAdjustments'

const task = (overrides: Partial<GenerationTaskDetail> = {}): GenerationTaskDetail => ({
  task_id: 'task_001',
  status: 'running',
  revision_count: 0,
  decision: 'in_progress',
  resources: [],
  ...overrides,
})

const resource = (overrides: Partial<ResourceSummary> = {}): ResourceSummary => ({
  resource_id: 'resource_001',
  resource_type: 'lecture',
  title: 'RAG 基础讲义',
  difficulty: 2,
  review_status: 'passed',
  sources: [],
  ...overrides,
})

const adjustment = (overrides: Partial<LearningAdjustmentSummary> = {}): LearningAdjustmentSummary => ({
  proposal_id: 'adjustment_001',
  hypothesis_type: 'support_down',
  status: 'resource_pending',
  resource_recommendation: {
    proposal_id: 'adjustment_001',
    path_id: 'path_001',
    path_node_id: 'node_001',
    resource_types: ['lecture', 'practice_guide'],
    mode: 'remedial',
  },
  ...overrides,
})

describe('dashboard state', () => {
  it('shows the assessment entry when no learning service state exists', () => {
    expect(getDashboardState(null, [], [])).toEqual({ kind: 'assessment' })
  })

  it('prioritizes an active generation task', () => {
    const state = getDashboardState(task(), [resource()], [])

    expect(state.kind).toBe('preparing')
    expect(state.kind === 'preparing' && state.feedbackTriggered).toBe(false)
  })

  it('labels feedback-triggered work as an adjustment', () => {
    const state = getDashboardState(task({ trigger_type: 'resource_feedback' }), [], [])

    expect(state.kind === 'preparing' && state.feedbackTriggered).toBe(true)
  })

  it('prioritizes unresolved current-node mistakes before available resources', () => {
    const state = getDashboardState(null, [resource()], [], {
      status: 'in_progress',
      can_advance: false,
      reason: 'BLOCKING_MISTAKES_REMAIN',
      blocking_mistake_count: 2,
      quiz_completed: true,
      knowledge_progress: [],
    })

    expect(state).toEqual({ kind: 'mistake_review', blockingMistakeCount: 2 })
  })

  it('keeps an active generation task visible while mistakes remain', () => {
    const state = getDashboardState(task(), [resource()], [], {
      status: 'in_progress',
      can_advance: false,
      reason: 'BLOCKING_MISTAKES_REMAIN',
      blocking_mistake_count: 1,
      quiz_completed: true,
      knowledge_progress: [],
    })

    expect(state.kind).toBe('preparing')
  })

  it('prioritizes a confirmed resource adjustment over the existing package', () => {
    const state = getDashboardState(null, [resource()], [], null, adjustment())

    expect(state.kind).toBe('adjustment')
  })

  it('shows a published resource instead of an unreviewed resource', () => {
    const state = getDashboardState(null, [resource({ review_status: 'pending' }), resource()], [])

    expect(state.kind).toBe('resource')
    expect(state.kind === 'resource' && state.resource.resource_id).toBe('resource_001')
  })

  it('does not let a completed task hide an available resource', () => {
    const state = getDashboardState(task({ status: 'completed' }), [resource()], [])

    expect(state.kind).toBe('resource')
  })

  it('shows the latest failed task when no resource is available', () => {
    const state = getDashboardState(null, [], [task({ status: 'failed', failure_reason: '审核未通过' })])

    expect(state.kind).toBe('failed')
  })
})
