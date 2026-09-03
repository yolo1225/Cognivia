import { describe, expect, it } from 'vitest'
import { learningDecision } from './learningDecision'
import type { LearningAdjustmentSummary } from '@/api/learningAdjustments'

function proposal(decisionType: NonNullable<LearningAdjustmentSummary['resource_recommendation']['decision_type']>): LearningAdjustmentSummary {
  return {
    proposal_id: 'adjustment_test',
    hypothesis_type: 'support_down',
    status: 'resource_pending',
    resource_recommendation: {
      proposal_id: 'adjustment_test',
      path_id: 'path_test',
      path_node_id: 'node_test',
      mode: 'remedial',
      decision_type: decisionType,
      resource_types: decisionType === 'no_generation' || decisionType === 'future_path_reprioritize' ? [] : ['lecture'],
    },
  }
}

describe('learning decision copy', () => {
  it.each([
    ['remedial', true],
    ['challenge', true],
    ['next_stage', true],
    ['no_generation', false],
    ['future_path_reprioritize', false],
  ] as const)('maps %s to one actionable presentation', (type, expectsGeneration) => {
    const decision = learningDecision(proposal(type))

    expect(decision.type).toBe(type)
    expect(Boolean(decision.generateLabel)).toBe(expectsGeneration)
  })
})
