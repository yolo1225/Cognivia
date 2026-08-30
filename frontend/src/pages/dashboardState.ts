import type { GenerationTaskDetail } from '@/api/generation'
import type { ResourceSummary } from '@/api/resources'
import type { NodeGate } from '@/api/tutoring'

export type DashboardState =
  | { kind: 'assessment' }
  | { kind: 'preparing'; task: GenerationTaskDetail; feedbackTriggered: boolean }
  | { kind: 'mistake_review'; blockingMistakeCount: number }
  | { kind: 'resource'; resource: ResourceSummary }
  | { kind: 'failed'; task: GenerationTaskDetail }

export function getDashboardState(
  activeTask: GenerationTaskDetail | null,
  resources: ResourceSummary[],
  recentTasks: GenerationTaskDetail[],
  nodeGate: NodeGate | null | undefined = null,
): DashboardState {
  if (activeTask && !['completed', 'failed'].includes(activeTask.status)) {
    return {
      kind: 'preparing',
      task: activeTask,
      feedbackTriggered: activeTask.trigger_type === 'resource_feedback',
    }
  }

  const blockingMistakeCount = nodeGate?.blocking_mistake_count || 0
  if (blockingMistakeCount > 0) {
    return { kind: 'mistake_review', blockingMistakeCount }
  }

  const publishedResource = resources.find((resource) => resource.review_status === 'passed')
  if (publishedResource) return { kind: 'resource', resource: publishedResource }

  const failedTask = [activeTask, ...recentTasks].find((task) => task?.status === 'failed')
  if (failedTask) return { kind: 'failed', task: failedTask }

  return { kind: 'assessment' }
}
