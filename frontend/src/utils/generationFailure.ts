export interface GenerationFailureCopy {
  title: string
  description: string
}

const FAILURE_COPY: Record<string, GenerationFailureCopy> = {
  revision_claim_set_empty_after_repair: {
    title: '实操指南修订后缺少可核验内容',
    description: '系统已停止发布仅剩教学占位语的实操指南。请重新生成；若仍失败，需要为当前知识点补充可核验的实操来源。',
  },
  review_claim_set_empty: {
    title: '实操指南修订后缺少可核验内容',
    description: '历史修订结果没有留下可供双模型审核的事实内容，可使用最新修订策略重新生成。',
  },
  revision_exhausted: {
    title: '学习包质量指标未达标',
    description: '两轮局部修订后，幻觉率、难度匹配或核心知识覆盖仍有指标未达到发布门槛，本次学习包未发布。',
  },
  node_package_resources_incomplete: {
    title: '最终学习包未达到发布门槛',
    description: '三类资源未能同时满足幻觉率、难度匹配和核心覆盖门槛，可重新生成。',
  },
  generation_incomplete: {
    title: '最终学习包未达到发布门槛',
    description: '资源完成审核后仍未满足最终发布条件，可重新生成。',
  },
  generated_content_policy_invalid: {
    title: '实训内容缺少可核对的知识库证据',
    description: '系统未发布包含无依据命令、固定结果或排错结论的资源，三类资源仍按完整包规则统一处理。',
  },
}

export function generationFailureCopy(reason?: string | null): GenerationFailureCopy {
  if (reason && FAILURE_COPY[reason]) return FAILURE_COPY[reason]
  return {
    title: '本次资源未达到发布标准',
    description: reason || '自动修订后仍未达到发布条件，未达标资源不会向学习者发布。',
  }
}
