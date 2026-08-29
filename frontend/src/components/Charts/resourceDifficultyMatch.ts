export type DifficultyMatchResource = {
  resource_id: string
  resource_type: string
  resource_type_label?: string
  title: string
  difficulty: number
  difficulty_match_score?: number | null
}

export type ResourceDifficultyMatchDatum = {
  resourceId: string
  label: string
  title: string
  difficulty: number
  difficultyMatchScore: number
}

function shortTitle(title: string) {
  const chars = Array.from(title.trim())
  return chars.length > 10 ? `${chars.slice(0, 10).join('')}…` : chars.join('')
}

export function toResourceDifficultyMatchData(
  resources: DifficultyMatchResource[],
): ResourceDifficultyMatchDatum[] {
  return resources.flatMap((resource) => {
    const score = Number(resource.difficulty_match_score)
    if (resource.difficulty_match_score == null || !Number.isFinite(score)) return []

    return [{
      resourceId: resource.resource_id,
      label: `${resource.resource_type_label || resource.resource_type} · ${shortTitle(resource.title)}`,
      title: resource.title,
      difficulty: Math.max(1, Math.min(5, Number(resource.difficulty) || 1)),
      difficultyMatchScore: Math.max(0, Math.min(100, score)),
    }]
  })
}
