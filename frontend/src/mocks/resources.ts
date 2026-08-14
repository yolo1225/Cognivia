import type { ResourceSummary } from '@/api/resources'

/**
 * 演示用假数据（Mock）——仅用于前端 UI 优化。
 * 后端有真实资源数据后，页面会自动改用真实数据，此文件可整体删除。
 */
export const mockResources: ResourceSummary[] = [
  {
    resource_id: 'res_lecture_001',
    resource_type: 'lecture',
    title: '检索不是回答：理解 RAG 的两阶段质量',
    difficulty: 2,
    review_status: 'passed',
    sources: ['k001', 'k002', 'k003', 'k004'],
    source_details: [
      { knowledge_id: 'k001', name: 'RAG 召回评测', source_title: 'RAG 检索质量评测规范' },
      { knowledge_id: 'k002', name: '向量召回与重排序', source_title: '向量召回与重排序实验' },
      { knowledge_id: 'k003', name: '文档切片策略', source_title: '文档切片实践指南' },
      { knowledge_id: 'k004', name: 'Embedding 相似度', source_title: 'Embedding 基础讲义' },
    ],
    version: 2,
    generation_task_id: 'task_demo_001',
    generation_task_status: 'completed',
    content:
      '<h2>学习目标</h2><p>分别解释检索阶段与生成阶段的评价目标，并使用 Recall@K 判断目标片段是否被成功召回。</p>' +
      '<h2>核心概念</h2><p>扩大 Top-K 通常会增加候选覆盖范围，但也可能带来更多无关信息，因此不能直接推导「最终答案一定更准确」。</p>' +
      '<div class="code">for k in [1, 3, 5, 10]:<br>&nbsp;&nbsp;results = retriever.search(query, top_k=k)<br>&nbsp;&nbsp;print(k, target_id in [x.id for x in results])</div>' +
      '<h2>常见误区</h2><p><strong>误区：</strong>Top-K 越大，回答一定越准确。<br><strong>修正：</strong>更大的候选集可能提高召回，但生成模型也会面对更多噪声。</p>',
  },
  {
    resource_id: 'res_practice_001',
    resource_type: 'practice_guide',
    title: 'Top-K 对照实验',
    difficulty: 3,
    review_status: 'passed',
    sources: ['k002', 'k004'],
    source_details: [
      { knowledge_id: 'k002', name: '向量召回与重排序', source_title: '向量召回与重排序实验' },
      { knowledge_id: 'k004', name: 'Embedding 相似度', source_title: 'Embedding 基础讲义' },
    ],
    version: 1,
    generation_task_id: 'task_demo_001',
    generation_task_status: 'completed',
    content:
      '<h2>实验目标</h2><p>对比不同 Top-K 值下的召回率与噪声比例，理解「召回范围」与「答案质量」的边界。</p>' +
      '<h2>实验步骤</h2><ol><li>准备 10 条查询与标注目标片段。</li><li>分别以 k=1、3、5、10 执行检索。</li><li>记录目标片段是否命中，并统计噪声比例。</li></ol>',
  },
  {
    resource_id: 'res_quiz_001',
    resource_type: 'graded_quiz',
    title: 'RAG 检索评测',
    difficulty: 3,
    review_status: 'pending',
    sources: ['k001', 'k003'],
    source_details: [
      { knowledge_id: 'k001', name: 'RAG 召回评测', source_title: 'RAG 检索质量评测规范' },
      { knowledge_id: 'k003', name: '文档切片策略', source_title: '文档切片实践指南' },
    ],
    version: 1,
    generation_task_id: 'task_demo_001',
    generation_task_status: 'completed',
    content:
      '<h2>测试说明</h2><p>完成以下题目，检验对 RAG 检索评测指标的理解。</p>' +
      '<h2>题目</h2><p>1. Recall@K 衡量的是什么？<br>2. 为什么 Top-K 增大不一定会提高最终答案准确率？</p>',
  },
]
