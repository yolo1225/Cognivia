import { describe, expect, it } from "vitest";
import type {
  IndexRebuildHint,
  ModelConfigStatus,
  ModelSettings,
} from "@/api/modelSettings";
import {
  embeddingModelChanged,
  formFromSettings,
  modelSettingsDirty,
  modelSettingsPayload,
  readinessItems,
  validateModelSettingsForm,
} from "./modelSettingsState";

const settings: ModelSettings = {
  openai_api_base: "https://example.com/v1",
  openai_api_key_set: true,
  primary_llm_model: "generate",
  primary_review_model: "review-a",
  secondary_review_model: "review-b",
  embedding_model: "embed-a",
};

it("validates required values and distinct review models", () => {
  const form = {
    ...formFromSettings(settings),
    secondary_review_model: "review-a",
  };
  const result = validateModelSettingsForm(form, true, false);
  expect(result.valid).toBe(false);
  expect(result.errors.secondary_review_model).toContain("不同");
});

it("requires a key only on first configuration", () => {
  const form = formFromSettings(settings);
  expect(validateModelSettingsForm(form, true, false).valid).toBe(true);
  expect(
    validateModelSettingsForm(form, false, false).errors.openai_api_key,
  ).toBeTruthy();
  expect(validateModelSettingsForm(form, true, true).valid).toBe(true);
});

it("detects dirty state and embedding impact", () => {
  const form = formFromSettings(settings);
  expect(modelSettingsDirty(settings, form, false)).toBe(false);
  form.embedding_model = "embed-b";
  expect(modelSettingsDirty(settings, form, false)).toBe(true);
  expect(embeddingModelChanged(settings, form)).toBe(true);
});

it("builds a trimmed payload without echoing a blank key", () => {
  const form = {
    ...formFromSettings(settings),
    primary_llm_model: " generate-2 ",
  };
  expect(modelSettingsPayload(form, false)).toMatchObject({
    primary_llm_model: "generate-2",
    openai_api_key: null,
    clear_openai_api_key: false,
  });
});

describe("readiness mapping", () => {
  it("separates model readiness from Candidate RAG readiness", () => {
    const status = {
      model_gateway: { configured: true, base_url_configured: true },
      generation_model: { configured: true, model_name: "generate" },
      primary_review_model: { configured: true, model_name: "a" },
      secondary_review_model: { configured: true, model_name: "b" },
      review_models_distinct: true,
    } as ModelConfigStatus;
    const index = {
      ready: false,
      reason: "candidate_index_stale",
    } as IndexRebuildHint;
    expect(readinessItems(status, index).map((item) => item.state)).toEqual([
      "ready",
      "ready",
      "ready",
      "warning",
    ]);
  });
});
