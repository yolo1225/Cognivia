type ApiFailure = {
  response?: {
    data?: {
      error?: {
        code?: unknown
      }
    }
  }
}

const MASTERY_CHECK_MESSAGES: Record<string, string> = {
  MASTERY_CHECK_PENDING: '已有掌握检查待完成，请先完成当前验证题。',
  MASTERY_CHECK_QUESTION_UNAVAILABLE: '当前知识点缺少可判分的单选验证题，请联系管理员补题后重试。',
  MASTERY_CHECK_CONTEXT_STALE: '当前学习资源与学习路线已更新，请刷新页面后重新发起掌握检查。',
}

export function masteryCheckErrorMessage(error: unknown): string {
  const code = (error as ApiFailure | null)?.response?.data?.error?.code
  return typeof code === 'string'
    ? (MASTERY_CHECK_MESSAGES[code] || '暂时无法发起掌握检查，请刷新页面后重试。')
    : '暂时无法发起掌握检查，请刷新页面后重试。'
}
