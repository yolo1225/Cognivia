import type { GenerationTaskDetail } from '@/api/generation'
import type { ResourceSummary } from '@/api/resources'
import type { NodeGate } from '@/api/tutoring'
import type { LearningAdjustmentSummary } from '@/api/learningAdjustments'

export type DashboardState =
  | { kind: 'assessment' }
  | { kind: 'preparing'; task: GenerationTaskDetail; feedbackTriggered: boolean }
  | { kind: 'mistake_review'; blockingMistakeCount: number }
  | { kind: 'adjustment'; proposal: LearningAdjustmentSummary }
  | { kind: 'resource'; resource: ResourceSummary }
  | { kind: 'failed'; task: GenerationTaskDetail }

export function getDashboardState(
  activeTask: GenerationTaskDetail | null,
  resources: ResourceSummary[],
  recentTasks: GenerationTaskDetail[],
  nodeGate: NodeGate | null | undefined = null,
  adjustment: LearningAdjustmentSummary | null = null,
): DashboardState {
  if (activeTask && !['completed', 'failed'].includes(activeTask.status)) {
    return {
      kind: 'preparing',
      task: activeTask,
      feedbackTriggered: activeTask.trigger_type === 'resource_feedback',
    }
  }

  if (adjustment && (
    adjustment.status === 'resource_pending'
    || adjustment.recovery_available
    || adjustment.generation_task?.status === 'failed'
  )) {
    return { kind: 'adjustment', proposal: adjustment }
  }

  const publishedResource = resources.find((resource) => resource.review_status === 'passed')
  const blockingMistakeCount = nodeGate?.blocking_mistake_count || 0
  // Mistake consolidation gates progression to the next node. It must not
  // prevent the learner from creating this node's first learning package.
  if (publishedResource && blockingMistakeCount > 0) {
    return { kind: 'mistake_review', blockingMistakeCount }
  }

  if (publishedResource) return { kind: 'resource', resource: publishedResource }

  const failedTask = [activeTask, ...recentTasks].find((task) => task?.status === 'failed')
  if (failedTask) return { kind: 'failed', task: failedTask }

  return { kind: 'assessment' }
}
