import type { LearningAdjustmentSummary } from '@/api/learningAdjustments'

export type LearningDecisionType = 'remedial' | 'challenge' | 'no_generation' | 'future_path_reprioritize' | 'next_stage'

export type LearningDecisionPresentation = {
  type: LearningDecisionType
  title: string
  description: string
  generateLabel: string | null
  skipLabel: string | null
  resourceLabel: string
}

const RESOURCE_LABELS: Record<string, string> = {
  lecture: '讲义',
  practice_guide: '实操指南',
  graded_quiz: '分阶测验',
}

export function learningDecision(proposal: LearningAdjustmentSummary): LearningDecisionPresentation {
  const recommendation = proposal.resource_recommendation
  const legacy = recommendation.mode === 'next_node' ? 'next_stage' : 'remedial'
  const type = (recommendation.decision_type || legacy) as LearningDecisionType
  const resourceLabel = recommendation.resource_types.map(item => RESOURCE_LABELS[item] || item).join('、') || '当前学习资源'
  const reason = recommendation.reason || proposal.route_message?.description || '路线仅在正式测验、错题闭环和未见掌握验证均满足后推进。'
  const copy: Record<LearningDecisionType, Omit<LearningDecisionPresentation, 'type' | 'resourceLabel'>> = {
    remedial: { title: `补充${resourceLabel}`, description: reason, generateLabel: '生成补救资源', skipLabel: '继续现有学习' },
    challenge: { title: '安排挑战练习', description: reason, generateLabel: '生成挑战练习', skipLabel: '暂不生成，继续学习' },
    no_generation: { title: '保持当前学习资源', description: reason, generateLabel: null, skipLabel: null },
    future_path_reprioritize: { title: '已调整后续学习顺序', description: reason, generateLabel: null, skipLabel: null },
    next_stage: { title: '准备下一阶段学习包', description: reason, generateLabel: '生成下一阶段学习包', skipLabel: '暂不生成' },
  }
  return { type, resourceLabel, ...copy[type] }
}
