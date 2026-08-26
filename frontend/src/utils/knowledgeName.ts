const SOURCE_KNOWLEDGE_PREFIX = /^.*?\([a-z][a-z0-9_-]*\)\s*[/／]\s*\d+\s*[.．、:-]?\s*/i

/** Removes document-import metadata from learner-facing knowledge labels. */
export function formatKnowledgeName(value: string | null | undefined): string {
  const name = String(value || '').trim()
  return SOURCE_KNOWLEDGE_PREFIX.test(name) ? name.replace(SOURCE_KNOWLEDGE_PREFIX, '').trim() || name : name
}
