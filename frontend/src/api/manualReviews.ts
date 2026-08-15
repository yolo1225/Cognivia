import { getData, postData } from './client'

export interface ManualReviewItem {
  manual_review_id: string
  task_id: string
  trigger_reason: string
  status: string
  decision: string | null
  review_comment: string | null
  reviewed_by: string | null
  created_at: string | null
}

export interface ManualReviewDetail extends ManualReviewItem {
  resource: { resource_id: string; title: string; resource_type: string; review_status: string } | null
  review: {
    primary: Record<string, unknown>
    secondary: Record<string, unknown>
    arbitration: Record<string, unknown>
    scores: Record<string, number>
    evidence_refs: unknown[]
    disagreement: Record<string, unknown>
    issues: unknown[]
  } | null
}

export function listManualReviews(status?: string) {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  return getData<ManualReviewItem[]>(`/manual-reviews${query}`)
}

export function getManualReview(reviewId: string) {
  return getData<ManualReviewDetail>(`/manual-reviews/${reviewId}`)
}

export function decideManualReview(
  reviewId: string,
  decision: 'approve' | 'request_revision' | 'reject',
  comment: string,
) {
  return postData(`/manual-reviews/${reviewId}/decision`, {
    decision,
    comment,
    reviewed_by: 'demo_admin',
  })
}
