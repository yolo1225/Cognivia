<template>
  <div class="tutor-assessment" :class="resultClass">
    <template v-if="assessment.status === 'pending'">
      <small class="assessment-trigger">{{ assessment.trigger_reason || '根据近期学习反馈，需要确认当前知识点的掌握情况' }}</small>
      <strong>{{ assessment.hypothesis_type === 'support_down' ? '补强确认' : '掌握检查' }} · 难度 {{ assessment.difficulty }}</strong>
      <p>{{ assessment.stem }}</p>
      <div class="assessment-options">
        <button v-for="(option, optionIndex) in assessment.options" :key="optionIndex" type="button" :disabled="submitting" @click="$emit('answer', optionIndex)">{{ option }}</button>
      </div>
      <small>{{ pendingHint }}</small>
    </template>
    <template v-else>
      <strong class="answer-outcome" :class="assessment.is_correct ? 'answer-correct' : 'answer-incorrect'">{{ assessment.is_correct ? '回答正确' : '回答错误' }}</strong>
      <p class="review-stem">{{ assessment.stem }}</p>
      <div class="assessment-options review-options">
        <div v-for="(option, optionIndex) in assessment.options" :key="optionIndex" :class="{ selected: assessment.submitted_option === optionIndex }">{{ option }}<small v-if="assessment.submitted_option === optionIndex">你的选择</small></div>
      </div>
      <p v-if="assessment.is_correct && assessment.correct_answer" class="correct-answer">正确答案：{{ assessment.correct_answer }}</p>
      <p v-if="assessment.is_correct && assessment.explanation" class="answer-explanation">解析：{{ assessment.explanation }}</p>
      <strong>{{ decisionLabel }}</strong>
      <p>{{ decisionDescription }}</p>
      <div v-if="assessment.node_gate && !assessment.node_gate.can_advance" class="evidence-progress">
        <span>核心知识 {{ assessment.node_gate.mastered_knowledge_count || 0 }} / {{ assessment.node_gate.core_knowledge_count || 0 }}</span>
        <span v-if="!assessment.node_gate.quiz_completed">分阶测验待完成</span>
        <span v-if="assessment.node_gate.blocking_mistake_count">待解决错题 {{ assessment.node_gate.blocking_mistake_count }} 道</span>
      </div>
      <div v-if="assessment.resource_recommendation && !assessment.resource_decision" class="adjustment-actions">
        <button class="btn primary" type="button" :disabled="resourceSubmitting" @click="$emit('resource-decision', 'generate')">生成新资源</button>
        <button class="btn" type="button" :disabled="resourceSubmitting" @click="$emit('resource-decision', 'skip')">暂不生成</button>
      </div>
      <small v-else-if="assessment.resource_decision === 'skip'">已暂不生成，之后可从当前节点重新发起。</small>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TutoringAssessment } from '@/api/tutoring'

const props = withDefaults(defineProps<{
  assessment: TutoringAssessment
  submitting?: boolean
  resourceSubmitting?: boolean
  pendingHint?: string
}>(), {
  submitting: false,
  resourceSubmitting: false,
  pendingHint: '本题只用于确认近期交互形成的判断，不会凭单次回答自由改写画像。',
})

defineEmits<{
  answer: [answer: number]
  'resource-decision': [decision: 'generate' | 'skip']
}>()

const resultClass = computed(() => {
  if (props.assessment.status !== 'scored') return ''
  return props.assessment.is_correct ? 'is-correct' : 'is-incorrect'
})
const decisionLabel = computed(() => {
  if (props.assessment.decision === 'confirmed_mastery') return '确认掌握并推进'
  if (props.assessment.decision === 'confirmed_support_need') return '确认需要补强'
  if (props.assessment.decision === 'evidence_recorded') return '掌握证据已记录'
  return '当前证据不足'
})
const decisionDescription = computed(() => {
  if (props.assessment.decision === 'confirmed_mastery') return '画像与路线已应用，下一节点资源等待你的确认。'
  if (props.assessment.decision === 'confirmed_support_need') return '画像已更新并保留当前节点，补救资源等待你的确认。'
  if (props.assessment.decision === 'evidence_recorded') {
    const progress = props.assessment.node_gate?.knowledge_progress.find(item => item.knowledge_id === props.assessment.knowledge_id)
    return progress
      ? `当前知识点已获得 ${progress.eligible_evidence_count}/${progress.required_evidence_count} 条独立正式证据，画像和路线暂不调整。`
      : '本次正式证据已记录，画像和路线暂不调整。'
  }
  return '验证结果与近期反馈不一致，画像和路线保持不变。'
})
</script>

<style scoped>
.tutor-assessment { margin-top: 4px; border: 1px solid #cbd9f4; border-radius: 9px; background: var(--blue2); padding: 12px; color: var(--info); font-size: 12px; line-height: 1.6; }
.tutor-assessment p { margin: 5px 0; background: transparent; padding: 0; color: inherit; }
.tutor-assessment small { color: var(--body); }
.tutor-assessment.is-correct { border-color: #9ed8c1; background: var(--green2); color: #176a4f; }
.tutor-assessment.is-incorrect { border-color: #edb4b4; background: #fff1f1; color: #9b2525; }
.answer-outcome { display: block; margin-bottom: 4px; }
.answer-correct { color: #176a4f; }
.answer-incorrect { color: #9b2525; }
.correct-answer { font-weight: 650; }
.answer-explanation { color: var(--body) !important; }
.assessment-trigger { display: block; margin-bottom: 6px; color: var(--blue) !important; font-weight: 650; }
.assessment-options { display: grid; gap: 6px; margin: 8px 0; }
.assessment-options button { min-height: 34px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); padding: 7px 9px; color: var(--ink); text-align: left; cursor: pointer; }
.assessment-options button:hover:not(:disabled) { border-color: var(--blue); background: var(--blue2); }
.review-options div { border: 1px solid var(--line); border-radius: 6px; background: var(--panel); padding: 7px 9px; color: var(--ink); }
.review-options div.selected { border-color: currentColor; font-weight: 650; }
.review-options small { display: block; margin-top: 2px; color: inherit; }
.adjustment-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.evidence-progress { display: flex; flex-wrap: wrap; gap: 6px 12px; margin-top: 8px; color: var(--body); }
</style>
