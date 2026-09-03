import type { MistakeReviewItem } from '@/api/mistakeReview'

export function isTextAnswerQuestion(questionType: string) {
  return questionType === 'short_answer'
}

export function mistakePathLabel(item: MistakeReviewItem): string {
  if (item.is_current_priority) return '当前必做'
  if (item.path_node_status === 'locked') {
    return item.path_order
      ? `路线第 ${item.path_order} 节 · 可提前练习`
      : '后续节点 · 可提前练习'
  }
  if (item.path_node_status === 'completed') return '已完成节点'
  if (item.path_node_status === 'current') return '当前节点 · 非阻断'
  return '路径外错题'
}

export function mistakePathTone(item: MistakeReviewItem): string {
  if (item.is_current_priority) return 'is-priority'
  if (item.path_node_status === 'locked') return 'is-future'
  if (item.path_node_status === 'completed') return 'is-completed'
  return 'is-neutral'
}
