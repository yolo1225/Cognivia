import { getData, postData, putData } from './client'

export interface ModelSettings {
  openai_api_base: string
  openai_api_key_set: boolean
  primary_llm_model: string
  primary_review_model: string
  secondary_review_model: string
  embedding_model: string
}

export interface ModelConfigStatus {
  status: 'ok' | 'degraded'
  ready_for_live_demo: boolean
  fixture_enabled: boolean
  review_models_distinct: boolean
  model_gateway: { configured: boolean; base_url_configured: boolean }
  generation_model: { configured: boolean; model_name: string | null }
  primary_review_model: { configured: boolean; model_name: string | null }
  secondary_review_model: { configured: boolean; model_name: string | null }
}

export interface IndexRebuildHint {
  ready: boolean
  reason: string | null
}

export interface ModelSettingsResponse {
  settings: ModelSettings
  status: ModelConfigStatus
  index: IndexRebuildHint
}

export interface ModelSettingsBody {
  openai_api_base: string
  primary_llm_model: string
  primary_review_model: string
  secondary_review_model: string
  embedding_model: string
  openai_api_key?: string | null
  clear_openai_api_key?: boolean
}

export interface ModelTestResult {
  ok: boolean
  message: string
  sample?: string
  code?: string
}

export const getModelSettings = () => getData<ModelSettingsResponse>('/admin/model-settings')
export const updateModelSettings = (body: ModelSettingsBody) =>
  putData<ModelSettingsResponse>('/admin/model-settings', body)
export const testModelSettings = (body: ModelSettingsBody) =>
  postData<ModelTestResult>('/admin/model-settings/test', body)
