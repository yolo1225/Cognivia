import { describe, expect, it } from "vitest";
import type { DomainStats, DomainSummary } from "@/api/domains";
import type { KnowledgeItem, QuestionBankItem } from "@/api/knowledge";
import type { KnowledgeDocumentItem } from "@/api/knowledgeDocuments";
import {
  configList,
  filterAndSortDocuments,
  domainReadiness,
  filterKnowledgeItems,
  filterQuestionBank,
  getDomainTaskAction,
  indexUiState,
} from "./domainHubState";

const items: KnowledgeItem[] = [
  {
    knowledge_id: "1",
    domain_code: "ai_app_dev",
    name: "RAG 检索",
    category: "RAG",
    difficulty: 3,
    tags: ["向量"],
    content: "内容",
    source_title: "课程资料",
    source_url: null,
    license_note: "授权",
    needs_reembedding: true,
  },
  {
    knowledge_id: "2",
    domain_code: "ai_app_dev",
    name: "Prompt 基础",
    category: "Prompt",
    difficulty: 1,
    tags: ["提示词"],
    content: "内容",
    source_title: "教材",
    source_url: null,
    license_note: "授权",
    needs_reembedding: false,
  },
];

const prefixedItem: KnowledgeItem = {
  ...items[0],
  knowledge_id: "3",
  name: "AI 机器学习基础知识库 (ai_ml_basics) / 77. Bahdanau 注意力机制",
};

it("combines knowledge filters", () => {
  expect(
    filterKnowledgeItems(items, {
      keyword: "向量",
      category: "RAG",
      difficulty: "3",
      indexStatus: "pending",
    }).map((item) => item.knowledge_id),
  ).toEqual(["1"]);
});

it("filters by the normalized knowledge name instead of a source-library prefix", () => {
  const filters = {
    category: "all",
    difficulty: "all",
    indexStatus: "all",
  } as const;
  expect(filterKnowledgeItems([prefixedItem], { ...filters, keyword: "Bahdanau" })).toHaveLength(1);
  expect(filterKnowledgeItems([prefixedItem], { ...filters, keyword: "ai_ml_basics" })).toHaveLength(0);
});

it("derives readiness from real targets and failures", () => {
  const stats = {
    knowledge_items: 50,
    diagnostic_questions: 59,
    pending_embeddings: 2,
    failed_documents: 1,
  } as DomainStats;
  expect(domainReadiness(stats, false).map((item) => item.state)).toEqual([
    "ready",
    "warning",
    "error",
    "error",
  ]);
});

it("does not report a ready index from pending embeddings alone", () => {
  expect(indexUiState(false, 0, "success")).toBe("needs_rebuild");
  expect(indexUiState(true, 0, "success")).toBe("ready");
  expect(indexUiState(true, 2, "success")).toBe("needs_rebuild");
  expect(indexUiState(undefined, 0, "running")).toBe("running");
});

const questions: QuestionBankItem[] = [
  {
    question_id: "q-1",
    domain_code: "ai_app_dev",
    knowledge_id: "k-1",
    knowledge_name: "RAG 检索",
    related_knowledge_ids: [],
    question_slot: 1,
    question_bank_uses: ["diagnosis"],
    reserve_role: null,
    assessment_focus: null,
    quiz_level: "foundation",
    question_type: "single_choice",
    stem: "RAG 的检索步骤是什么？",
    options: [],
    answer: 0,
    explanation: "",
    difficulty: 2,
    status: "active",
    disabled_at: null,
    disabled_reason: null,
  },
  {
    question_id: "q-2",
    domain_code: "ai_app_dev",
    knowledge_id: "k-2",
    knowledge_name: "Prompt 工程",
    related_knowledge_ids: [],
    question_slot: 2,
    question_bank_uses: ["graded_quiz"],
    reserve_role: null,
    assessment_focus: null,
    quiz_level: "challenge",
    question_type: "short_answer",
    stem: "说明约束提示词的作用。",
    options: [],
    answer: "",
    explanation: "",
    difficulty: 4,
    status: "disabled",
    disabled_at: null,
    disabled_reason: null,
  },
];

it("filters question-bank entries across purpose, lifecycle, and searchable content", () => {
  expect(
    filterQuestionBank(questions, {
      keyword: "RAG",
      purpose: "diagnosis",
      level: "foundation",
      difficulty: "2",
      status: "active",
    }).map((question) => question.question_id),
  ).toEqual(["q-1"]);
  expect(
    filterQuestionBank(questions, {
      keyword: "约束提示词",
      purpose: "all",
      level: "all",
      difficulty: "all",
      status: "all",
    }).map((question) => question.question_id),
  ).toEqual(["q-2"]);
});

const documents: KnowledgeDocumentItem[] = [
  {
    document_id: "doc-ready",
    domain_code: "ai_app_dev",
    original_name: "rag.md",
    file_type: "markdown",
    mime_type: "text/markdown",
    size_bytes: 1,
    status: "ready",
    error_summary: null,
    knowledge_item_count: 1,
    chunk_count: 1,
    embedding_model: null,
    source_title: "RAG 手册",
    license_note: "",
    uploaded_by: "admin",
    is_system: false,
    indexed_at: null,
    created_at: "2026-08-01T00:00:00Z",
  },
  {
    document_id: "doc-processing",
    domain_code: "ai_app_dev",
    original_name: "prompt.pdf",
    file_type: "pdf",
    mime_type: "application/pdf",
    size_bytes: 1,
    status: "indexing",
    error_summary: null,
    knowledge_item_count: 0,
    chunk_count: 0,
    embedding_model: null,
    source_title: "Prompt 课程",
    license_note: "",
    uploaded_by: "admin",
    is_system: false,
    indexed_at: null,
    created_at: "2026-08-02T00:00:00Z",
  },
  {
    document_id: "doc-failed",
    domain_code: "ai_app_dev",
    original_name: "broken.txt",
    file_type: "text",
    mime_type: "text/plain",
    size_bytes: 1,
    status: "failed",
    error_summary: "解析失败",
    knowledge_item_count: 0,
    chunk_count: 0,
    embedding_model: null,
    source_title: "错误资料",
    license_note: "",
    uploaded_by: "admin",
    is_system: false,
    indexed_at: null,
    created_at: "2026-08-03T00:00:00Z",
  },
];

it("filters documents and keeps attention items ahead of processing and ready items", () => {
  expect(
    filterAndSortDocuments(documents, {
      keyword: "",
      status: "all",
      fileType: "all",
    }).map((document) => document.document_id),
  ).toEqual(["doc-failed", "doc-processing", "doc-ready"]);
  expect(
    filterAndSortDocuments(documents, {
      keyword: "课程",
      status: "processing",
      fileType: "pdf",
    }).map((document) => document.document_id),
  ).toEqual(["doc-processing"]);
});

describe("domain primary task", () => {
  const readyStats = {
    knowledge_items: 50,
    diagnostic_questions: 60,
    failed_documents: 0,
  } as DomainStats;

  it("prioritizes failed source documents", () => {
    expect(
      getDomainTaskAction({
        stats: { ...readyStats, failed_documents: 1 },
        domainStatus: "draft",
        indexState: "needs_rebuild",
        validationPassed: false,
        missingQuestionKnowledgeCount: 3,
      }).id,
    ).toBe("open_documents");
  });

  it("rebuilds an unavailable index before ordinary validation", () => {
    expect(
      getDomainTaskAction({
        stats: readyStats,
        domainStatus: "draft",
        indexState: "failed",
        validationPassed: false,
      }).id,
    ).toBe("rebuild_index");
  });

  it("routes question-bank blockers to the question bank instead of rebuilding", () => {
    expect(
      getDomainTaskAction({
        stats: readyStats,
        domainStatus: "draft",
        indexState: "needs_rebuild",
        validationPassed: false,
        missingQuestionKnowledgeCount: 2,
        indexBlockedByQuestionBank: true,
      }).id,
    ).toBe("open_questions");
  });

  it("offers publication only after all checks pass", () => {
    expect(
      getDomainTaskAction({
        stats: readyStats,
        domainStatus: "draft",
        indexState: "ready",
        validationPassed: true,
      }).id,
    ).toBe("publish_domain");
    expect(
      getDomainTaskAction({
        stats: readyStats,
        domainStatus: "ready",
        indexState: "ready",
        validationPassed: true,
      }).id,
    ).toBe("review_operations");
  });

  it("keeps loading and running states actionable without a destructive shortcut", () => {
    expect(
      getDomainTaskAction({ stats: null, indexState: "needs_rebuild" }).id,
    ).toBe("loading");
    expect(
      getDomainTaskAction({
        stats: readyStats,
        indexState: "running",
      }).id,
    ).toBe("review_operations");
  });
});

describe("domain config parsing", () => {
  it("reads existing config values", () => {
    const domain = {
      config: {
        ability_dimensions: ["理论"],
        resource_types: ["lecture"],
        mvp_targets: { knowledge_items: 50 },
      },
    } as unknown as DomainSummary;
    expect(configList(domain)).toEqual({
      abilityDimensions: ["理论"],
      resourceTypes: ["lecture"],
      mvpTargets: [
        ["minimum_published_knowledge", 50],
        ["minimum_diagnostic_questions", 10],
      ],
      learningDirections: [],
      sources: {
        abilityDimensions: "领域配置",
        resourceTypes: "领域配置",
        mvpTargets: "领域配置",
        learningDirections: "等待文档导入",
      },
    });
  });

  it("returns empty groups for missing config", () => {
    const config = configList(null);
    expect(config.abilityDimensions).toHaveLength(5);
    expect(config.resourceTypes).toEqual(["lecture", "practice_guide", "graded_quiz"]);
    expect(config.mvpTargets).toEqual([
      ["minimum_published_knowledge", 10],
      ["minimum_diagnostic_questions", 10],
    ]);
    expect(config.sources.abilityDimensions).toBe("系统默认");
  });
});
