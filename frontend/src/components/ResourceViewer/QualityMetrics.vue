<template>
  <div class="quality-grid">
    <div><span>本资源审核幻觉率</span><strong :class="metrics.hallucination_rate < 5 ? 'ok' : 'bad'">{{ format(metrics.hallucination_rate) }}%</strong><small v-if="showDetails">{{ metrics.hallucinated_claim_count }}/{{ metrics.verifiable_claim_count }} 条可核验声明</small></div>
    <div><span>本资源难度适配</span><strong :class="metrics.difficulty_match_score >= 85 ? 'ok' : 'bad'">{{ format(metrics.difficulty_match_score) }}%</strong><small v-if="showDetails">达标线 ≥ 85%</small></div>
    <div><span>本资源核心覆盖</span><strong :class="metrics.core_knowledge_coverage >= 90 ? 'ok' : 'bad'">{{ format(metrics.core_knowledge_coverage) }}%</strong><small v-if="showDetails">{{ metrics.covered_core_knowledge_count }}/{{ metrics.target_core_knowledge_count }} 个目标知识点</small></div>
  </div>
</template>

<script setup lang="ts">
import type { ResourceQualityMetrics } from '@/api/resources'
defineProps<{ metrics: ResourceQualityMetrics; showDetails?: boolean }>()
const format = (value: number) => Number(value || 0).toFixed(1)
</script>

<style scoped>
.quality-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1px; overflow:hidden; border:1px solid var(--line); border-radius:8px; background:var(--line); }
.quality-grid div { min-width:0; background:var(--panel); padding:14px 16px; }
.quality-grid span,.quality-grid small { display:block; color:var(--muted); font-size:12px; line-height:1.5; }
.quality-grid strong { display:block; margin:5px 0; font-size:22px; }
.ok { color:var(--green); }.bad { color:var(--red); }
@media (max-width:700px){.quality-grid{grid-template-columns:1fr}.quality-grid strong{font-size:19px}}
</style>
