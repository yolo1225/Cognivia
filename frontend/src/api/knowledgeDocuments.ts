import { apiClient } from './client'
import type { ApiResponse } from '@/types/api'

export type KnowledgeDocumentStatus = 'queued' | 'parsing' | 'validating' | 'review_pending' | 'index_pending' | 'indexing' | 'ready' | 'failed'

export interface KnowledgeDocumentItem {
  document_id: string
  domain_code: string
  original_name: string
  file_type: 'pdf' | 'markdown' | 'text' | 'seed_package'
  mime_type: string
  size_bytes: number
  status: KnowledgeDocumentStatus
  error_summary: string | null
  knowledge_item_count: number
  chunk_count: number
  embedding_model: string | null
  source_title: string
  license_note: string
  uploaded_by: string
  is_system: boolean
  indexed_at: string | null
  created_at: string | null
}

export interface KnowledgeDocumentList {
  domain_code: string
  documents: KnowledgeDocumentItem[]
  summary: { total: number; ready: number; processing: number; failed: number; chunks: number }
}

export async function listKnowledgeDocuments(domainCode: string) {
  const response = await apiClient.get<ApiResponse<KnowledgeDocumentList>>(
    `/knowledge/documents?domain_code=${encodeURIComponent(domainCode)}`,
  )
  return response.data.data
}

export async function uploadKnowledgeDocument(
  file: File,
  domainCode: string,
  sourceTitle: string,
  licenseNote: string,
) {
  const response = await apiClient.post<ApiResponse<KnowledgeDocumentItem>>(
    '/knowledge/documents', file,
    {
      params: { domain_code: domainCode, source_title: sourceTitle, license_note: licenseNote },
      headers: {
        'Content-Type': file.type || 'application/octet-stream',
        'X-File-Name': encodeURIComponent(file.name),
      },
    },
  )
  return response.data.data
}

export async function retryKnowledgeDocument(documentId: string) {
  const response = await apiClient.post<ApiResponse<KnowledgeDocumentItem>>(
    `/knowledge/documents/${documentId}/retry`, {},
  )
  return response.data.data
}

export async function deleteKnowledgeDocument(documentId: string) {
  const response = await apiClient.delete<ApiResponse<{ document_id: string; status: string }>>(
    `/knowledge/documents/${documentId}`,
  )
  return response.data.data
}
