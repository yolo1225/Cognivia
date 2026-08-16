import type { GenerationTaskDetail } from '@/api/generation'
import type { ResourceSummary } from '@/api/resources'

export type DashboardState =
  | { kind: 'assessment' }
  | { kind: 'preparing'; task: GenerationTaskDetail; feedbackTriggered: boolean }
  | { kind: 'resource'; resource: ResourceSummary }
  | { kind: 'failed'; task: GenerationTaskDetail }

export function getDashboardState(
  activeTask: GenerationTaskDetail | null,
  resources: ResourceSummary[],
  recentTasks: GenerationTaskDetail[],
): DashboardState {
  if (activeTask && !['completed', 'failed'].includes(activeTask.status)) {
    return {
      kind: 'preparing',
      task: activeTask,
      feedbackTriggered: activeTask.trigger_type === 'resource_feedback',
    }
  }

  const publishedResource = resources.find((resource) => resource.review_status === 'passed')
  if (publishedResource) return { kind: 'resource', resource: publishedResource }

  const failedTask = [activeTask, ...recentTasks].find((task) => task?.status === 'failed')
  if (failedTask) return { kind: 'failed', task: failedTask }

  return { kind: 'assessment' }
}
