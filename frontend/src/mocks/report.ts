import type { LearningReport } from '@/api/reports'

/**
 * 演示用假数据（Mock）——仅用于前端 UI 优化。
 * 后端有真实学习报告后，页面会自动改用真实数据，此文件可整体删除。
 */
export const mockReport: LearningReport = {
  learner_id: 'learner_001',
  profile_id: 'prof_demo_001',
  profile_type: 'beginner',
  radar: [72, 55, 68, 80, 61],
  path: ['Embedding 与相似度', 'Top-K 与召回评测', '重排序与噪声控制', '端到端 RAG 评测'],
  diagnostic_summary: {
    answer_count: 10,
    correct_count: 7,
    accuracy: 0.7,
    latest_session_id: 'sess_demo_001',
  },
  path_detail: [
    { name: 'Embedding 与相似度', description: '能够解释余弦相似度并运行基础检索' },
    { name: 'Top-K 与召回评测', description: '对比 3 组 Top-K 并计算 Recall@K' },
    { name: '重排序与噪声控制', description: '处理高召回带来的噪声' },
    { name: '端到端 RAG 评测', description: '分别报告检索指标和生成指标' },
  ],
  weak_knowledge: [
    { knowledge_id: 'k001', name: 'RAG 召回评测', category: 'RAG', weakness_level: 3 },
    { knowledge_id: 'k002', name: '重排序', category: 'RAG', weakness_level: 2 },
  ],
  metrics: {
    hallucination_rate: 0.04,
    difficulty_match: 0.91,
    difficulty_match_accuracy: 0.91,
    knowledge_coverage: 0.93,
  },
  loop_status: {
    diagnosis: 'complete',
    profile: 'complete',
    generation: 'complete',
    review: 'complete',
    feedback: 'complete',
    path_update: 'complete',
  },
  resource_summary: {
    total: 3,
    by_type: { lecture: 1, practice_guide: 1, graded_quiz: 1 },
    recent: [
      {
        resource_id: 'res_lecture_001',
        resource_type: 'lecture',
        resource_type_label: '个性化讲义',
        title: '检索不是回答',
        difficulty: 2,
        review_status: 'passed',
        source_count: 4,
      },
      {
        resource_id: 'res_practice_001',
        resource_type: 'practice_guide',
        resource_type_label: '实操指南',
        title: 'Top-K 对照实验',
        difficulty: 3,
        review_status: 'passed',
        source_count: 2,
      },
      {
        resource_id: 'res_quiz_001',
        resource_type: 'graded_quiz',
        resource_type_label: '分阶测试',
        title: 'RAG 检索评测',
        difficulty: 3,
        review_status: 'pending',
        source_count: 2,
      },
    ],
  },
  review_summary: {
    total_reports: 3,
    passed: 2,
    manual_review_required: 1,
    review_status_counts: { passed: 2, pending: 1 },
    source_coverage: 0.95,
  },
  feedback_summary: {
    total: 1,
    latest_action: 'path_refresh',
    learning_path_needs_refresh: false,
    path_refresh_performed: true,
    recent: [
      {
        resource_id: 'res_lecture_001',
        resource_title: '检索不是回答',
        feedback_type: 'too_easy',
        rating: 4,
        triggered_action: 'difficulty_adjust',
        created_at: '2026-07-28T14:36:00Z',
      },
    ],
  },
  next_actions: [
    {
      type: 'generate',
      label: '生成进阶资源',
      description: '针对薄弱点生成新的学习资源',
      route: '/resources',
    },
    {
      type: 'diagnostic',
      label: '重新诊断',
      description: '再次测评以刷新画像',
      route: '/diagnostic',
    },
  ],
}
