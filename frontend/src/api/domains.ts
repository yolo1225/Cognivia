import { getData, patchData, postData } from "./client";

export interface DomainSummary {
  domain_code: string;
  name: string;
  status: string;
  domain_schema_version?: string;
  description?: string;
  learning_directions?: LearningDirection[];
  created_at?: string | null;
  updated_at?: string | null;
  config?: Record<string, unknown>;
}

export interface LearningDirection {
  value: string;
  label: string;
  description: string;
  match_tags: string[];
}

export interface DomainMutationPayload {
  domain_code?: string;
  name: string;
  description: string;
  learning_directions?: LearningDirection[];
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
  profile_ready: boolean;
  diagnostic_ready: boolean;
  rag_ready: boolean;
  generation_ready: boolean;
  runtime_reasons?: string[];
  evidence_coverage?: {
    total_items: number;
    capabilities: Record<
      | "concept"
      | "operation"
      | "command"
      | "code_example"
      | "expected_result"
      | "error_handling"
      | "version_boundary",
      number
    >;
    practice_generation_mode: "evidence_backed" | "safe_conceptual";
  };
  question_bank_coverage?: {
    total_items: number;
    ready_items: number;
    ready_knowledge_ids: string[];
    missing_knowledge_ids: string[];
    missing_diagnosis_knowledge_ids: string[];
    missing_quiz_knowledge_ids: string[];
    missing_mastery_reserve_knowledge_ids: string[];
    counts_by_knowledge: Record<string, {
      single_choice: number;
      short_answer: number;
      total: number;
      diagnosis: number;
      graded_quiz: number;
      mastery_validation: number;
      mastery_reserve: number;
    }>;
    requirements: {
      primary_total: number;
      diagnosis_per_knowledge: number;
      graded_quiz_per_knowledge: number;
      mastery_reserve_per_knowledge: number;
      domain_total: number;
      levels: string[];
      question_types: string[];
      difficulty_levels: number[];
    };
  };
  status?: string;
  policy?: Record<string, number>;
  checks?: Array<{
    key: string;
    label: string;
    passed: boolean;
    level: string;
    actual: number;
    target: number;
  }>;
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

export function getDomainReadiness(domainCode: string) {
  return getData<DomainValidationResult>(`/domains/${domainCode}/readiness`);
}

export function getDomain(domainCode: string) {
  return getData<DomainSummary>(`/domains/${domainCode}`);
}

export function createDomain(payload: DomainMutationPayload & { domain_code: string }) {
  return postData<DomainSummary>('/domains', payload);
}

export function updateDomain(domainCode: string, payload: DomainMutationPayload) {
  return patchData<DomainSummary>(`/domains/${domainCode}`, payload);
}

export function publishDomain(domainCode: string) {
  return postData<{ domain: DomainSummary; readiness: DomainValidationResult }>(
    `/domains/${domainCode}/publish`,
  );
}

export function disableDomain(domainCode: string) {
  return postData<DomainSummary>(`/domains/${domainCode}/disable`);
}
