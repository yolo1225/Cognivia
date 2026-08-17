import { getData } from "./client";

export interface DomainSummary {
  domain_code: string;
  name: string;
  status: string;
  domain_schema_version?: string;
  config?: Record<string, unknown>;
}

export interface DomainStats {
  domain_code: string;
  knowledge_items: number;
  diagnostic_questions: number;
  knowledge_relations: number;
  pending_embeddings: number;
  knowledge_documents: number;
  ready_documents: number;
  failed_documents: number;
  document_chunks: number;
  published_resources: number;
}

export interface DomainValidationIssue {
  level?: string;
  message: string;
  actual?: number | string;
  target?: number | string;
}

export interface DomainValidationResult {
  domain_code: string;
  passed: boolean;
  counts?: Record<string, number>;
  targets?: Record<string, number>;
  issues: DomainValidationIssue[];
  rag?: {
    ready: boolean;
    reason?: string;
    active_collection?: string;
    indexed_chunk_count?: number;
    embedding_model?: string;
  };
}

export function listDomains() {
  return getData<DomainSummary[]>("/domains");
}

export function getDomainStats(domainCode: string) {
  return getData<DomainStats>(`/domains/${domainCode}/stats`);
}

export function validateDomain(domainCode: string) {
  return getData<DomainValidationResult>(`/domains/${domainCode}/validate`);
}
