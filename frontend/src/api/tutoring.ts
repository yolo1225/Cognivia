import { getData, postData } from './client'

export interface TutoringSession {
  session_id: string
  status: string
  turn_count: number
  node_adjustment_state: 'collecting' | 'pending_validation' | 'confirmed' | 'none'
  pending_assessment?: TutoringAssessment | null
  node_adjustment_result?: TutoringAssessment | null
  evidence_scope?: {
    path_node_id: string
    path_node_title: string | null
    generation_task_id: string
  } | null
  messages: Array<{
    message_id: string
    sender: string
    message_type: string
    content: string
    created_at: string | null
    sources?: Array<{ knowledge_id: string; name: string; source_title: string }>
    scope_status?: string | null
    assessment?: TutoringAssessment | null
    assessment_unavailable?: string | null
    evidence_accepted?: boolean
    evidence_reason?: string | null
    stream_status?: 'streaming' | 'completed' | 'paused' | 'interrupted' | 'failed'
    error_code?: string | null
  }>
}

export interface TutoringAssessment {
  assessment_id: string
  adjustment_proposal_id?: string
  hypothesis_type?: 'mastery_up' | 'support_down'
  trigger_reason?: string
  question_id: string
  knowledge_id: string
  question_type: 'single_choice'
  difficulty: number
  stem: string
  options: string[]
  status: 'pending' | 'scored'
  score?: number
  is_correct?: boolean
  decision?: 'confirmed_mastery' | 'confirmed_support_need' | 'hypothesis_rejected'
  profile_changed?: boolean
  resulting_profile_id?: string
  resulting_path_id?: string
  completed_node_id?: string | null
  current_node_id?: string | null
  resource_recommendation?: ResourceRecommendation | null
  resource_decision?: 'generate' | 'skip'
}

export interface ResourceRecommendation {
  proposal_id: string
  path_id: string
  path_node_id: string | null
  resource_types: string[]
  mode: 'next_node' | 'remedial'
}

export interface TutoringDecision {
  feedback_id: string
  feedback_intent: string
  recommended_action: string
  profile_update_required: boolean
  decision_reason: string
  task_id: string | null
  node_adjustment_state: TutoringSession['node_adjustment_state']
  pending_assessment?: TutoringAssessment | null
  node_adjustment_result?: TutoringAssessment | null
  evidence_scope?: TutoringSession['evidence_scope']
  evidence_accepted: boolean
  evidence_reason?: string | null
}

export function createTutoringSession(resourceId: string, learnerId?: string) {
  const body: Record<string, unknown> = {
    resource_id: resourceId,
  }
  if (learnerId) body.learner_id = learnerId
  return postData<TutoringSession>('/tutoring/sessions', body)
}

export function sendTutoringMessage(sessionId: string, content: string) {
  return postData<{
    session_id: string
    reply: {
      message_id: string; message_type: string; content: string
      sources?: Array<{ knowledge_id: string; name: string; source_title: string }>
      scope_status?: string | null
      assessment?: TutoringAssessment | null
      assessment_unavailable?: string | null
    }
  } & TutoringDecision>(`/tutoring/sessions/${sessionId}/messages`, { content })
}

export function getTutoringSession(sessionId: string) {
  return getData<TutoringSession>(`/tutoring/sessions/${sessionId}`)
}

export type TutoringStreamEvent =
  | { type: 'accepted'; learner_message_id: string; reply_message_id: string }
  | { type: 'agent_status'; agent: string; status: string }
  | { type: 'delta'; reply_message_id: string; content: string }
  | ({ type: 'completed'; reply_message_id: string; content: string; sources: NonNullable<TutoringSession['messages'][number]['sources']>; scope_status: string | null; assessment: TutoringSession['messages'][number]['assessment']; assessment_unavailable: string | null } & TutoringDecision)
  | { type: 'paused'; reply_message_id: string; content: string }
  | { type: 'error'; reply_message_id: string; code: string; recoverable: boolean }

export async function streamTutoringMessage(sessionId: string, content: string, onEvent: (event: TutoringStreamEvent) => void, signal: AbortSignal) {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const csrf = document.cookie.split('; ').find(item => item.startsWith('csrf_token='))?.split('=')[1]
  const response = await fetch(`${baseUrl}/tutoring/sessions/${sessionId}/messages/stream`, { method: 'POST', credentials: 'include', signal, headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {}) }, body: JSON.stringify({ content }) })
  if (!response.ok || !response.body) throw new Error('stream_request_failed')
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ''
  while (true) {
    const { done, value } = await reader.read(); buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    let boundary: number
    while ((boundary = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2)
      const name = frame.match(/^event:\s*(.+)$/m)?.[1]; const data = frame.match(/^data:\s*(.+)$/m)?.[1]
      if (name && data) onEvent({ type: name, ...JSON.parse(data) } as TutoringStreamEvent)
    }
    if (done) break
  }
}

export function answerTutoringAssessment(sessionId: string, assessmentId: string, answer: number) {
  return postData<{
    answer_record_id: string
    score: number
    is_correct: boolean
    confirmed: boolean
    feedback_id: string
    profile_update_required: boolean
    decision_reason: string
    task_id: string | null
    adjustment_proposal_id?: string
    hypothesis_type?: 'mastery_up' | 'support_down'
    decision?: 'confirmed_mastery' | 'confirmed_support_need' | 'hypothesis_rejected'
    profile_changed?: boolean
    resulting_profile_id?: string
    resulting_path_id?: string
    completed_node_id?: string | null
    current_node_id?: string | null
    resource_recommendation?: ResourceRecommendation | null
  }>(`/tutoring/sessions/${sessionId}/assessments/${assessmentId}/answers`, { answer })
}

export function requestMasteryCheck(sessionId: string) {
  return postData<TutoringAssessment>(`/tutoring/sessions/${sessionId}/mastery-check`)
}

export function pauseTutoringMessage(sessionId: string, replyMessageId: string) {
  return postData<{ reply_message_id: string; stream_status: string; content: string }>(`/tutoring/sessions/${sessionId}/messages/${replyMessageId}/pause`)
}
