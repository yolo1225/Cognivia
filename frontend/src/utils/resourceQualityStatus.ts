/**
 * `review_status` is a persisted compatibility field.  In the current MVP it
 * represents the result/freshness of automatic quality validation, never a
 * learner-facing manual-review queue.
 */
const LABELS: Record<string, string> = {
  passed: '质量校验通过',
  pending: '质量校验中',
  revision_required: '正在自动修订',
  review_stale: '知识库已更新，需重新生成',
  failed: '未通过质量门槛',
  manual_review_required: '需重新生成',
}

export function resourceQualityStatusLabel(status?: string | null): string {
  return LABELS[String(status || '')] || '状态待确认'
}

export function resourceQualityStatusTone(status?: string | null): 'ok' | 'wait' {
  return status === 'passed' ? 'ok' : 'wait'
}
