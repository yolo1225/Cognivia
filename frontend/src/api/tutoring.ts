import { getData, postData } from './client'

export interface TutoringSession {
  session_id: string
  status: string
  turn_count: number
  messages: Array<{
    message_id: string
    sender: string
    message_type: string
    content: string
    created_at: string | null
    sources?: Array<{ knowledge_id: string; name: string; source_title: string }>
    scope_status?: string | null
    assessment?: { assessment_id: string; kind: string; prompt: string; status: string } | null
    stream_status?: 'streaming' | 'completed' | 'paused' | 'interrupted' | 'failed'
    error_code?: string | null
  }>
}

export function createTutoringSession(resourceId: string, learnerId = 'learner_001') {
  return postData<TutoringSession>('/tutoring/sessions', {
    resource_id: resourceId,
    learner_id: learnerId,
  })
}

export function sendTutoringMessage(sessionId: string, content: string) {
  return postData<{
    session_id: string
    reply: {
      message_id: string; message_type: string; content: string
      sources?: Array<{ knowledge_id: string; name: string; source_title: string }>
      scope_status?: string | null
      assessment?: { assessment_id: string; kind: string; prompt: string; status: string } | null
    }
    feedback_intent: string
    recommended_action: string
    profile_update_required: boolean
    decision_reason: string
    task_id: string | null
  }>(`/tutoring/sessions/${sessionId}/messages`, { content })
}

export function getTutoringSession(sessionId: string) {
  return getData<TutoringSession>(`/tutoring/sessions/${sessionId}`)
}

export type TutoringStreamEvent =
  | { type: 'accepted'; learner_message_id: string; reply_message_id: string }
  | { type: 'delta'; reply_message_id: string; content: string }
  | { type: 'completed'; reply_message_id: string; content: string; sources: NonNullable<TutoringSession['messages'][number]['sources']>; scope_status: string | null; assessment: TutoringSession['messages'][number]['assessment']; task_id: string | null }
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

export function pauseTutoringMessage(sessionId: string, replyMessageId: string) {
  return postData<{ reply_message_id: string; stream_status: string; content: string }>(`/tutoring/sessions/${sessionId}/messages/${replyMessageId}/pause`)
}
