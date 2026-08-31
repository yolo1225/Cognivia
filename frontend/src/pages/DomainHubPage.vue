<template>
  <section class="page domain-page">
    <PageHeader title="领域管理" description="检查领域是否具备诊断、检索和资源生成条件，并维护支撑运行的知识资产。">
      <template #actions>
        <label class="domain-select"
          ><span>当前领域</span
          ><select v-model="selectedCode" class="field" @change="switchDomain">
            <option
              v-for="domain in domains"
              :key="domain.domain_code"
              :value="domain.domain_code"
            >
              {{ domain.name }}
            </option>
          </select></label
        >
        <button type="button" class="btn" :disabled="loading" :aria-busy="loading" @click="loadDomain">
          {{ loading ? "正在刷新" : "刷新数据" }}
        </button>
        <button type="button" class="btn" @click="openDomainEditor()">新建领域</button>
        <button v-if="selectedDomain" type="button" class="btn" @click="openDomainEditor(selectedDomain)">编辑领域</button>
        <button
          v-if="selectedDomain?.status !== 'ready'"
          class="btn primary"
          :disabled="lifecycleLoading"
          @click="publishSelectedDomain"
        >发布领域</button>
        <button
          v-else
          class="btn"
          :disabled="lifecycleLoading"
          @click="disableSelectedDomain"
        >停用领域</button>
      </template>
    </PageHeader>

    <div v-if="errorMessage && !stats" class="error-state" role="alert">
      <strong>领域数据加载失败</strong>
      <p>{{ errorMessage }}</p>
      <button class="btn" @click="loadAll">重新加载</button>
    </div>
    <template v-else>
      <div class="domain-banner">
        <div class="domain-identity">
          <span class="domain-mark">域</span>
          <div>
            <strong>{{ selectedDomain?.name || "-" }}</strong
            ><small>{{ selectedCode }} · 管理员工作区</small>
          </div>
        </div>
        <span class="domain-state"><i />{{ domainStatusLabel(selectedDomain?.status) }}</span>
      </div>

      <nav class="domain-tabs" aria-label="领域管理区域">
        <button
          v-for="pane in panes"
          :key="pane.id"
          :class="{ active: activePane === pane.id }"
          @click="selectPane(pane.id)"
        >
          {{ pane.label }}
        </button>
      </nav>

      <div
        v-if="loading && !stats"
        class="page-skeleton"
        aria-label="正在加载领域数据"
      >
        <i /><i /><i /><i />
      </div>

      <section v-else-if="activePane === 'overview'" class="pane-stack">
        <div v-if="errorMessage" class="inline-error">
          <span>{{ errorMessage }}</span
          ><button class="btn text" @click="loadDomain">重试</button>
        </div>
        <section class="current-task" :class="currentTask.tone">
          <div class="task-kicker">当前任务</div>
          <div class="current-task-content">
            <div>
              <h2>{{ currentTask.title }}</h2>
              <p>{{ currentTask.description }}</p>
            </div>
            <button
              class="btn primary"
              :disabled="primaryActionBusy"
              :aria-busy="primaryActionBusy"
              @click="runPrimaryAction"
            >{{ primaryActionBusy ? '处理中...' : currentTask.label }}</button>
          </div>
          <div class="overview-statuses">
            <span><i :class="overallReadinessClass" />{{ overallReadinessLabel }}</span>
            <span><i :class="currentIndexState === 'ready' ? 'ready' : 'warning'" />检索索引 {{ indexStatusLabel }}</span>
            <span><i :class="selectedDomain?.status === 'ready' ? 'ready' : 'warning'" />{{ domainStatusLabel(selectedDomain?.status) }}</span>
          </div>
        </section>
        <section class="panel readiness-panel">
          <div class="section-head">
            <div>
              <h2>领域运行概览</h2>
              <p>已通过 {{ passedReadinessItems.length }} / {{ readinessItems.length }} 项基础检查。</p>
            </div>
            <span class="summary-status" :class="overallReadinessClass"
              ><i />{{ overallReadinessLabel }}</span
            >
          </div>
          <ReadinessList v-if="attentionItems.length" class="readiness-list">
            <div
              v-for="item in attentionItems"
              :key="item.key"
              class="readiness-row"
            >
              <span class="readiness-icon" :class="item.state">{{
                item.state === "ready"
                  ? "✓"
                  : item.state === "running"
                    ? "…"
                    : "!"
              }}</span>
              <div>
                <strong>{{ item.label }}</strong
                ><small>{{ readinessDescription(item) }}</small>
              </div>
              <span class="readiness-value"
                >{{ item.actual }} / {{ item.target }}</span
              >
            </div>
          </ReadinessList>
          <p v-else class="readiness-empty">当前基础检查均已通过，可以继续执行运行检查或发布领域。</p>
          <button v-if="passedReadinessItems.length" class="btn text readiness-toggle" type="button" @click="showReadinessDetails = !showReadinessDetails">
            {{ showReadinessDetails ? '收起已通过项' : `查看已通过项（${passedReadinessItems.length}）` }}
          </button>
          <ReadinessList v-if="showReadinessDetails" class="readiness-list readiness-passed-list">
            <div v-for="item in passedReadinessItems" :key="item.key" class="readiness-row">
              <span class="readiness-icon ready">✓</span>
              <div><strong>{{ item.label }}</strong><small>{{ readinessDescription(item) }}</small></div>
              <span class="readiness-value">{{ item.actual }} / {{ item.target }}</span>
            </div>
          </ReadinessList>
          <button
            v-if="validationResult?.evidence_coverage"
            class="evidence-toggle"
            type="button"
            @click="showEvidenceDetails = !showEvidenceDetails"
          >
            <span>实训支撑信息</span><span>{{ showEvidenceDetails ? '收起' : '查看' }}</span>
          </button>
          <div
            v-if="showEvidenceDetails && validationResult?.evidence_coverage"
            class="evidence-coverage"
            :class="{ 'is-conceptual': practiceGenerationMode === 'safe_conceptual' }"
          >
            <div class="evidence-coverage-summary">
              <div>
                <strong>实训证据覆盖</strong>
                <p>{{ practiceModeDescription }}</p>
              </div>
              <StatusBadge
                :label="practiceGenerationMode === 'evidence_backed' ? '证据支撑模式' : '概念练习模式'"
                :type="practiceGenerationMode === 'evidence_backed' ? 'ok' : 'wait'"
              />
            </div>
            <div class="evidence-capability-list" aria-label="证据能力知识点数量">
              <span v-for="item in evidenceCapabilityItems" :key="item.key">
                {{ item.label }} <strong>{{ item.count }}</strong>
              </span>
            </div>
          </div>
        </section>
        <section class="panel quick-links">
          <div class="section-head">
            <div>
              <h2>领域资产</h2>
              <p>按资产类型维护知识内容、来源材料和知识结构。</p>
            </div>
          </div>
          <div class="asset-links">
            <button @click="openAssetView('items')">
              <strong>{{ stats?.knowledge_items || 0 }} 个知识点</strong
              ><span>维护内容、难度与来源</span></button
            ><button @click="openAssetView('documents')">
              <strong>{{ stats?.knowledge_documents || 0 }} 份来源文档</strong
              ><span>{{
                stats?.failed_documents
                  ? `${stats.failed_documents} 份处理失败`
                  : "来源文件处理正常"
              }}</span></button
            ><button @click="openAssetView('graph')">
              <strong>{{ stats?.knowledge_relations || 0 }} 条知识关系</strong
              ><span>查看前置、后继与关联结构</span>
            </button>
          </div>
        </section>
      </section>

      <section v-else-if="activePane === 'assets'" class="panel assets-panel">
        <div class="section-head asset-heading">
          <div>
            <h2>知识资产</h2>
            <p>{{
              assetView === 'items' ? '维护可追溯的知识内容、难度与检索状态。'
                : assetView === 'questions' ? '检查三类正式题目的覆盖与认证状态。'
                  : assetView === 'documents' ? '管理进入领域知识库的来源材料与处理状态。'
                    : '浏览知识点之间的前置、后继与关联结构。'
            }}</p>
          </div>
          <button
            v-if="assetView === 'items'"
            class="btn primary"
            @click="openKnowledgeEditor()"
          >
            新增知识点</button
          ><div v-else-if="assetView === 'questions'" class="row-actions">
            <button class="btn" :disabled="questionImportActionLoading" @click="downloadQuestionBankTemplate">下载补题模板</button>
            <button class="btn primary" :disabled="questionImportActionLoading" @click="openQuestionImport">导入题库</button>
          </div>
          <button
            v-else-if="assetView === 'documents'"
            class="btn primary"
            @click="uploadOpen = true"
          >
            上传实验文档
          </button>
        </div>
        <div class="segmented">
          <button
            v-for="view in assetViews"
            :key="view.id"
            :class="{ active: assetView === view.id }"
            @click="selectAssetView(view.id)"
          >
            {{ view.label }} <span>{{ view.count }}</span>
          </button>
        </div>

        <div v-if="assetView === 'items'" class="asset-body">
          <div class="filterbar knowledge-filters">
            <label class="search-field"
              ><span aria-hidden="true">⌕</span
              ><input
                v-model="knowledgeFilters.keyword"
                type="search"
                placeholder="搜索名称、标签或来源" /></label
            ><select v-model="knowledgeFilters.category" class="field">
              <option value="all">全部分类</option>
              <option
                v-for="category in categories"
                :key="category"
                :value="category"
              >
                {{ category }}
              </option></select
            ><select v-model="knowledgeFilters.difficulty" class="field">
              <option value="all">全部难度</option>
              <option v-for="level in 5" :key="level" :value="String(level)">
                难度 {{ level }}
              </option></select
            ><select v-model="knowledgeFilters.indexStatus" class="field">
              <option value="all">全部索引状态</option>
              <option value="ready">索引已同步</option>
              <option value="pending">待重新索引</option></select
            ><button
              v-if="hasKnowledgeFilters"
              class="btn text"
              @click="clearKnowledgeFilters"
            >
              清除筛选
            </button>
          </div>
          <p class="knowledge-results" aria-live="polite">
            显示 {{ filteredKnowledgeItems.length }} 个，共 {{ knowledgeItems.length }} 个知识点
          </p>
          <div v-if="filteredKnowledgeItems.length === 0" class="empty-view">
            <strong>{{
              knowledgeItems.length
                ? "没有符合条件的知识点"
                : "当前领域暂无知识点"
            }}</strong>
            <p>
              {{
                knowledgeItems.length
                  ? "调整筛选条件后再试。"
                  : "新增知识点后，系统会将其标记为待重建索引。"
              }}
            </p>
            <button
              v-if="knowledgeItems.length"
              class="btn"
              @click="clearKnowledgeFilters"
            >
              清除筛选</button
            ><button v-else class="btn primary" @click="openKnowledgeEditor()">
              新增知识点
            </button>
          </div>
          <div v-else class="table-wrap knowledge-table-wrap">
            <table class="knowledge-table">
              <thead>
                <tr>
                  <th>知识点</th>
                  <th>分类</th>
                  <th>难度</th>
                  <th class="source-col">来源</th>
                  <th>索引状态</th>
                  <th class="table-actions">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in filteredKnowledgeItems"
                  :key="item.knowledge_id"
                  :ref="(element) => setKnowledgeRowRef(item.knowledge_id, element)"
                  :class="{ 'is-located': highlightedKnowledgeId === item.knowledge_id }"
                >
                  <td>
                    <strong :title="item.name">{{ knowledgeNameLabel(item) }}</strong
                    ><small>{{
                      item.tags.length
                        ? item.tags.join(" · ")
                        : item.knowledge_id
                    }}</small>
                  </td>
                  <td>{{ item.category }}</td>
                  <td>
                    <span class="difficulty-dots"
                      ><i
                        v-for="level in 5"
                        :key="level"
                        :class="{ on: level <= item.difficulty }" /></span
                    ><small>{{ item.difficulty }}/5</small>
                  </td>
                  <td class="source-col">
                    <span class="source-text" :title="item.source_title">{{ item.source_title }}</span>
                  </td>
                  <td>
                    <StatusBadge
                      :label="item.needs_reembedding ? '待重新索引' : '已同步'"
                      :type="item.needs_reembedding ? 'wait' : 'ok'"
                    />
                  </td>
                  <td class="table-actions">
                    <div class="row-actions">
                      <button class="btn text" @click="locateInGraph(item.knowledge_id)">图谱定位</button>
                      <button class="btn text" @click="openKnowledgeEditor(item)">查看与编辑</button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-else-if="assetView === 'questions'" class="asset-body">
          <article v-if="activeChangeSet" class="upload-warning question-change-set">
            <div>
              <strong>待启用知识变更</strong>
              <p>本次增量维护使用独立题库缺口模板，当前状态：{{ changeSetStatusLabel(activeChangeSet.status) }}。</p>
            </div>
            <button
              v-if="activeChangeSet.status === 'ready_to_activate'"
              class="btn primary"
              :disabled="questionImportActionLoading"
              @click="activateCurrentChangeSet"
            >一次启用变更</button>
            <button
              v-else
              class="btn"
              type="button"
              :disabled="pendingGraphLoading || !pendingChangeDocument"
              @click="openPendingChangeGraph"
            >查看待启用图谱</button>
          </article>
          <div class="asset-summary-grid question-summary-grid">
            <article v-for="item in questionCoverageCards" :key="item.label" :class="{ 'has-gap': item.missing }">
              <span>{{ item.label }}</span>
              <strong>{{ item.ready }} / {{ questionCoverage?.total_items || stats?.knowledge_items || 0 }}</strong>
              <small>{{ item.note }}</small>
            </article>
          </div>
          <p class="asset-summary-note" aria-live="polite">
            活动正式题 {{ activeQuestionBankTotal }} 道；当前筛选范围 {{ questionBankTotal }} 道，生成资源时根据关联知识点动态检索当前证据。
          </p>
          <div class="filterbar asset-filters">
            <label class="search-field"><span aria-hidden="true">⌕</span><input v-model="questionFilters.keyword" type="search" placeholder="搜索知识点或题干" /></label>
            <select v-model="questionFilters.purpose" class="field"><option value="all">全部用途</option><option value="diagnosis">诊断题</option><option value="graded_quiz">分阶测验</option><option value="mastery_validation">掌握检查</option></select>
            <select v-model="questionFilters.level" class="field"><option value="all">全部层级</option><option value="foundation">基础巩固</option><option value="improvement">能力提升</option><option value="challenge">挑战突破</option></select>
            <select v-model="questionFilters.difficulty" class="field"><option value="all">全部难度</option><option v-for="level in 5" :key="level" :value="String(level)">难度 {{ level }}</option></select>
            <select v-model="questionFilters.status" class="field" @change="loadQuestionBankForStatus"><option value="all">全部状态</option><option value="active">启用</option><option value="staged">待启用</option><option value="stale">待替换</option><option value="disabled">已停用</option></select>
            <button v-if="hasQuestionFilters" class="btn text" type="button" @click="clearQuestionFilters">清除筛选</button>
          </div>
          <p class="asset-results" aria-live="polite">显示 {{ filteredQuestionBank.length }} 道，共 {{ questionBankTotal }} 道题</p>
          <div v-if="filteredQuestionBank.length === 0" class="empty-view">
            <strong>{{ questionBankTotal ? '没有符合条件的题目' : '当前领域暂无正式题目' }}</strong>
            <p>{{ questionBankTotal ? '调整筛选条件后再试。' : '下载缺口模板后填写并导入正式题目。' }}</p>
            <button v-if="!questionBankTotal" class="btn primary" type="button" @click="downloadQuestionBankTemplate">下载补题模板</button>
            <button v-if="questionBankTotal" class="btn" type="button" @click="clearQuestionFilters">清除筛选</button>
          </div>
          <div v-else class="table-wrap asset-table-wrap">
            <table class="knowledge-table">
              <thead><tr><th>主要知识点</th><th>用途</th><th>层级与难度</th><th>数据状态</th><th class="table-actions">操作</th></tr></thead>
              <tbody>
                <tr v-for="question in filteredQuestionBank" :key="question.question_id">
                  <td><strong>{{ question.knowledge_name }}</strong><small v-if="question.related_knowledge_ids.length">关联 {{ question.related_knowledge_ids.length }} 个知识点</small></td>
                  <td>{{ questionPoolLabel(question) }}</td>
                  <td>{{ quizLevelLabel(question.quiz_level) }} / 难度 {{ question.difficulty }}</td>
                  <td><StatusBadge :label="questionStatusLabel(question.status)" :type="question.status === 'active' ? 'ok' : question.status === 'stale' ? 'warning' : 'wait'" /></td>
                  <td class="table-actions"><div class="row-actions"><button class="btn text" @click="openQuestionDetail(question)">查看</button><button v-if="question.status === 'active'" class="btn text danger" :disabled="questionActionLoading === question.question_id" @click="disableBankQuestion(question)">停用</button><span v-else class="system-label">等待补槽</span></div></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-else-if="assetView === 'documents'" class="asset-body">
          <div class="asset-summary-grid document-summary-grid">
            <article><span>已就绪</span><strong>{{ documentSummary.ready }}</strong><small>可作为当前来源材料</small></article>
            <article :class="{ 'has-gap': documentSummary.processing }"><span>处理中</span><strong>{{ documentSummary.processing }}</strong><small>{{ documentSummary.processing ? '等待导入完成' : '当前无处理任务' }}</small></article>
            <article :class="{ 'has-gap': documentSummary.failed }"><span>处理失败</span><strong>{{ documentSummary.failed }}</strong><small>{{ documentSummary.failed ? '优先处理失败材料' : '当前无失败材料' }}</small></article>
          </div>
          <div class="filterbar asset-filters">
            <label class="search-field"><span aria-hidden="true">⌕</span><input v-model="documentFilters.keyword" type="search" placeholder="搜索文件名或来源标题" /></label>
            <select v-model="documentFilters.status" class="field"><option value="all">全部处理状态</option><option value="attention">待处理</option><option value="processing">处理中</option><option value="ready">已就绪</option></select>
            <select v-model="documentFilters.fileType" class="field"><option value="all">全部文件类型</option><option value="pdf">PDF</option><option value="markdown">Markdown</option><option value="text">TXT</option><option value="seed_package">系统包</option></select>
            <button v-if="hasDocumentFilters" class="btn text" type="button" @click="clearDocumentFilters">清除筛选</button>
          </div>
          <p class="asset-results" aria-live="polite">显示 {{ filteredDocuments.length }} 份，共 {{ documents.length }} 份来源文档</p>
          <div v-if="filteredDocuments.length === 0" class="empty-view">
            <strong>{{ documents.length ? '没有符合条件的来源文档' : '当前领域暂无来源文档' }}</strong>
            <p>{{ documents.length ? '调整筛选条件后再试。' : '上传 PDF、Markdown 或 TXT，进入可追溯的知识导入流程。' }}</p>
            <button v-if="documents.length" class="btn" type="button" @click="clearDocumentFilters">清除筛选</button>
            <button class="btn primary" @click="uploadOpen = true">
              上传实验文档
            </button>
          </div>
          <div v-else class="table-wrap asset-table-wrap">
            <table class="document-table">
              <thead>
                <tr>
                  <th>文件与来源</th>
                  <th>类型</th>
                  <th>大小</th>
                  <th>向量切片</th>
                  <th>状态</th>
                  <th class="date-col">上传时间</th>
                  <th class="table-actions">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="document in filteredDocuments" :key="document.document_id">
                  <td>
                    <strong>{{ document.original_name }}</strong
                    ><small>{{ document.source_title || "未填写来源" }}</small>
                  </td>
                  <td>{{ fileTypeLabel(document.file_type) }}</td>
                  <td>{{ formatBytes(document.size_bytes) }}</td>
                  <td>{{ document.chunk_count || "-" }}</td>
                  <td>
                    <StatusBadge
                      :label="documentStatusLabel(document.status)"
                      :type="document.status === 'ready' ? 'ok' : 'wait'"
                    /><small
                      v-if="document.error_summary"
                      class="document-error"
                      >{{ document.error_summary }}</small
                    >
                  </td>
                  <td class="date-col">
                    {{ formatDate(document.created_at) }}
                  </td>
                  <td class="table-actions">
                    <span v-if="document.is_system" class="system-label"
                      >系统内置</span
                    ><button
                      v-if="!document.is_system"
                      class="btn text"
                      @click="openImportReview(document)"
                    >{{ isProcessing(document.status) ? "查看进度" : "查看任务" }}</button><button
                      v-if="!document.is_system && isProcessing(document.status)"
                      class="btn text danger"
                      @click="cancelDocumentImport(document)"
                    >中断</button><button
                      v-if="!document.is_system && ['failed', 'cancelled', 'interrupted'].includes(document.status)"
                      class="btn text"
                      @click="retry(document)"
                    >
                      重新处理</button
                    ><button
                      v-if="!document.is_system"
                      class="btn text danger"
                      :disabled="isProcessing(document.status) && !isCancellationRequested(document)"
                      @click="requestRemove(document)"
                    >
                      删除
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-else class="asset-body graph-body">
          <div class="graph-summary graph-summary-with-view" aria-live="polite">
            <div>
              <span><strong>{{ displayedGraphItems.length }}</strong> 个知识点</span>
              <span><strong>{{ displayedGraphRelations.length }}</strong> 条关系</span>
              <span>{{ graphView === 'pending' ? '待启用预览，不影响当前学习任务' : '当前已启用图谱' }}</span>
            </div>
            <div v-if="activeChangeSet" class="graph-view-toggle" role="group" aria-label="图谱版本">
              <button class="btn small" :class="{ active: graphView === 'active' }" type="button" @click="showActiveGraph">正式图谱</button>
              <button class="btn small" :class="{ active: graphView === 'pending' }" type="button" :disabled="pendingGraphLoading || !pendingChangeDocument" @click="showPendingGraph">
                {{ pendingGraphLoading ? '加载预览...' : '待启用变更' }}
              </button>
            </div>
          </div>
          <div v-if="graphView === 'pending'" class="pending-graph-notice">
            <strong>{{ changeSetStatusLabel(activeChangeSet?.status || 'preparing') }}</strong>
            <span>候选知识和关系将在题库缺口补齐、确认后一次启用。</span>
            <span v-if="pendingGraphPathIsolatedCount">其中 {{ pendingGraphPathIsolatedCount }} 个节点尚未接入有向学习路径；关联关系不计作路径衔接。</span>
          </div>
          <div v-if="!graphLoading && !displayedGraphItems.length" class="empty-view">
            <strong>{{ graphView === 'pending' ? '待启用变更尚未生成图谱候选' : '暂无可展示的知识关系' }}</strong>
            <p>{{ graphView === 'pending' ? '请从导入任务中重新校验图谱，或等待导入完成。' : '新增知识点和关系后，这里将展示领域知识结构。' }}</p>
          </div>
          <KnowledgeGraph
            v-else
            :items="displayedGraphItems"
            :relations="displayedGraphRelations"
            :loading="graphView === 'active' && graphLoading"
            :readonly="graphView === 'pending'"
            :selected-knowledge-id="selectedKnowledgeId"
            @select="selectedKnowledgeId = $event"
            @edit="returnToKnowledgeItem"
          />
        </div>
      </section>

      <section v-else-if="activePane === 'rules'" class="pane-stack">
        <section class="panel config-panel">
          <div class="section-head">
            <div>
              <h2>领域配置摘要</h2>
              <p>这些配置决定学习者画像、可生成资源和学习方向。</p>
            </div>
            <span class="readonly-badge">自动生效</span>
          </div>
          <div class="rule-sections">
            <div class="rule-block">
              <div>
                <h3>能力维度</h3>
                <p>用于诊断结果和学情画像的能力判断。</p>
              </div>
              <div class="rule-values">
                <span
                  v-for="value in parsedConfig.abilityDimensions"
                  :key="value"
                  >{{ value }}</span
                ><small v-if="!parsedConfig.abilityDimensions.length"
                  >未配置</small
                >
              </div>
            </div>
            <div class="rule-block">
              <div>
                <h3>可生成资源</h3>
                <p>通过审核后，可为学习者生成的资源形态。</p>
              </div>
              <div class="rule-values">
                <span
                  v-for="value in parsedConfig.resourceTypes"
                  :key="value"
                  >{{ resourceTypeLabel(value) }}</span
                ><small v-if="!parsedConfig.resourceTypes.length">未配置</small>
              </div>
            </div>
            <div class="rule-block">
              <div>
                <h3>学习方向</h3>
                <p>用于学习者建档时选择目标，并影响资源匹配。</p>
              </div>
              <div class="rule-values rule-values-action">
                <span v-for="direction in parsedConfig.learningDirections" :key="direction.value">{{ direction.label }}</span>
                <small v-if="!parsedConfig.learningDirections.length">尚未生成，发布首份导入文档后自动出现</small>
                <button v-if="parsedConfig.learningDirections.length" class="btn small" type="button" @click="openDomainEditor(selectedDomain || undefined)">编辑学习方向</button>
              </div>
            </div>
          </div>
          <button class="config-details-toggle" type="button" @click="showConfigDetails = !showConfigDetails">
            {{ showConfigDetails ? '收起运行规则与来源' : '查看运行规则与来源' }}
          </button>
          <div v-if="showConfigDetails" class="config-details">
            <div class="rule-block">
              <div>
                <h3>发布数量门槛</h3>
                <p>领域校验使用的最低数据规模。</p>
              </div>
              <div class="target-list">
                <div v-for="entry in parsedConfig.mvpTargets" :key="entry[0]"><span>{{ targetLabel(entry[0]) }}</span><strong>{{ entry[1] }}</strong></div>
              </div>
            </div>
            <p class="config-source-note">
              能力维度：{{ parsedConfig.sources.abilityDimensions }} · 资源类型：{{ parsedConfig.sources.resourceTypes }} · 发布门槛：{{ parsedConfig.sources.mvpTargets }} · 学习方向：{{ parsedConfig.sources.learningDirections }}
            </p>
          </div>
        </section>
      </section>

      <section v-else class="operations-workbench">
        <div class="section-head">
          <div>
            <h2>运行检查</h2>
            <p>{{ currentTask.tone === 'ready' ? '4 项运行检查均已通过。' : '按来源材料、检索索引、领域校验和发布状态确认领域是否可用。' }}</p>
          </div>
          <StatusBadge :label="overallReadinessLabel" :type="overallReadinessClass === 'ready' ? 'ok' : 'wait'" />
        </div>
        <ol class="operation-steps" :class="{ compact: currentTask.tone === 'ready' }">
          <li :class="{ active: currentTask.id === 'open_documents', complete: documentSummary.failed === 0 && documentSummary.processing === 0 }">
            <span>1</span><div><strong>来源文档</strong><small>{{ documentSummary.failed ? `${documentSummary.failed} 份需要处理` : documentSummary.processing ? `${documentSummary.processing} 份正在处理` : '来源材料正常' }}</small></div><StatusBadge :label="documentSummary.failed ? '待处理' : documentSummary.processing ? '处理中' : '已就绪'" :type="documentSummary.failed ? 'error' : documentSummary.processing ? 'wait' : 'ok'" />
          </li>
          <li :class="{ active: currentTask.id === 'rebuild_index' || (currentTask.id === 'review_operations' && currentIndexState === 'running'), complete: currentIndexState === 'ready' }">
            <span>2</span><div><strong>检索索引</strong><small>当前活动索引：{{ indexStatusLabel }} · Candidate RAG</small></div><StatusBadge :label="indexStatusLabel" :type="indexStatusType" />
          </li>
          <li :class="{ active: currentTask.id === 'open_questions' || currentTask.id === 'open_validation', complete: validationResult?.passed }">
            <span>3</span><div><strong>领域校验</strong><small>{{ missingQuestionKnowledgeIds.length ? `题库仍有 ${missingQuestionKnowledgeIds.length} 个知识点缺口` : validationResult?.passed ? '当前校验通过' : '等待处理未达标项' }}</small></div><StatusBadge :label="validationResult?.passed ? '已通过' : '待校验'" :type="validationResult?.passed ? 'ok' : 'wait'" />
          </li>
          <li :class="{ active: currentTask.id === 'publish_domain', complete: selectedDomain?.status === 'ready' }">
            <span>4</span><div><strong>发布领域</strong><small>{{ selectedDomain?.status === 'ready' ? '学习者可选择此领域' : '通过全部检查后可发布' }}</small></div><StatusBadge :label="domainStatusLabel(selectedDomain?.status)" :type="selectedDomain?.status === 'ready' ? 'ok' : 'wait'" />
          </li>
        </ol>
        <section v-if="currentTask.tone === 'ready'" class="operation-normal">
          <div><strong>领域可用</strong><span>{{ activeChangeSet ? '活动知识、检索索引、领域校验和发布状态均正常；待启用变更不会影响当前学习者运行。' : '来源材料、检索索引、领域校验和发布状态均正常。' }}</span></div>
          <button class="btn text" type="button" @click="showValidationDetails = !showValidationDetails">{{ showValidationDetails ? '收起检查明细' : '查看检查明细' }}</button>
        </section>
        <section v-else class="operation-focus" :class="currentTask.tone">
          <div class="section-head">
            <div><h3>{{ currentTask.title }}</h3><p>{{ currentTask.description }}</p></div>
            <button class="btn primary" :disabled="primaryActionBusy" @click="runPrimaryAction">{{ primaryActionBusy ? '处理中...' : currentTask.label }}</button>
          </div>
          <div v-if="currentTask.id === 'rebuild_index' || currentIndexState === 'running'" class="operation-stats">
            <div><span>待重新索引知识点</span><strong>{{ stats?.pending_embeddings || 0 }}</strong></div>
            <div><span>最近模型</span><strong>{{ rebuildStatus?.result?.embedding_model || '-' }}</strong></div>
            <div><span>最近结果</span><strong>{{ rebuildResultLabel }}</strong></div>
          </div>
          <div v-if="showRebuildMessage" class="operation-message" :class="rebuildStatus?.status || currentIndexState"><strong>{{ rebuildMessageTitle }}</strong><p>{{ rebuildMessageBody }}</p></div>
          <div v-if="validationResult && ['open_validation', 'open_questions', 'review_operations', 'publish_domain'].includes(currentTask.id)" class="validation-list">
            <div v-for="row in validationRows" :key="row.key"><span>{{ row.label }}</span><strong>{{ row.actual }} / {{ row.target }}</strong><StatusBadge :label="row.passed ? '达标' : '未达标'" :type="row.passed ? 'ok' : 'wait'" /></div>
            <div v-for="issue in validationResult.issues" :key="issue.message" class="validation-issue"><span>!</span><p>{{ issue.message }}<small v-if="issue.actual !== undefined">实际 {{ issue.actual }}，目标 {{ issue.target }}</small></p></div>
          </div>
        </section>
        <section v-if="activeChangeSet" class="operation-change-set">
          <div>
            <strong>待启用知识变更</strong>
            <p>{{ pendingChangeOperationDescription }}</p>
          </div>
          <button class="btn" type="button" @click="openAssetView('questions')">查看补题进度</button>
        </section>
        <section v-if="currentTask.tone === 'ready' && showValidationDetails && validationResult" class="validation-details">
          <div class="validation-list">
            <div v-for="row in validationRows" :key="row.key"><span>{{ row.label }}</span><strong>{{ row.actual }} / {{ row.target }}</strong><StatusBadge :label="row.passed ? '达标' : '未达标'" :type="row.passed ? 'ok' : 'wait'" /></div>
          </div>
          <div class="operation-actions"><button class="btn" :disabled="rebuilding" @click="rebuild">{{ rebuilding ? '正在重建...' : '重建检索索引' }}</button><button class="btn" :disabled="validating" @click="validate">{{ validating ? '正在校验...' : '重新执行检查' }}</button></div>
          <p class="manual-operation-note">索引重建用于知识内容、来源或嵌入配置变更后的维护确认。</p>
        </section>
      </section>
    </template>

    <AppDrawer
      v-model="domainDrawerOpen"
      :title="editingDomain ? '编辑领域' : '新建领域'"
      :subtitle="editingDomain ? '可调整系统生成的学习方向' : '创建后上传文档，系统将自动生成学习方向'"
    >
      <form id="domain-form" class="drawer-form" @submit.prevent="saveDomain">
        <label>领域代码<input v-model.trim="domainForm.domain_code" class="field" required maxlength="64" pattern="[a-z][a-z0-9_]*" :disabled="Boolean(editingDomain)" /></label>
        <label>领域名称<input v-model.trim="domainForm.name" class="field" required maxlength="128" /></label>
        <label>领域说明<textarea v-model.trim="domainForm.description" rows="3" maxlength="500" /></label>
        <div v-if="editingDomain" class="section-head"><div><strong>学习方向</strong></div><button class="btn" type="button" :disabled="domainForm.learning_directions.length >= 6" @click="addDirection">添加方向</button></div>
        <div v-for="(direction, index) in (editingDomain ? domainForm.learning_directions : [])" :key="index" class="rule-block">
          <label>代码<input v-model.trim="direction.value" class="field" required pattern="[A-Za-z0-9_-]+" /></label>
          <label>名称<input v-model.trim="direction.label" class="field" required /></label>
          <label>说明<input v-model.trim="direction.description" class="field" /></label>
          <label>匹配标签<input v-model="direction.tags" class="field" placeholder="逗号分隔" /></label>
          <button v-if="domainForm.learning_directions.length > 1" class="btn text" type="button" @click="removeDirection(index)">删除方向</button>
        </div>
        <p v-if="domainFormError" class="form-error" role="alert">{{ domainFormError }}</p>
      </form>
      <template #footer><div class="drawer-footer"><button class="btn" :disabled="lifecycleLoading" @click="domainDrawerOpen = false">取消</button><button class="btn primary" type="submit" form="domain-form" :disabled="lifecycleLoading">{{ lifecycleLoading ? '正在保存...' : '保存领域' }}</button></div></template>
    </AppDrawer>

    <AppDrawer
      v-model="knowledgeDrawerOpen"
      :title="editingKnowledge ? '编辑知识点' : '新增知识点'"
      :subtitle="
        editingKnowledge
          ? editingKnowledge.knowledge_id
          : `添加到 ${selectedCode}`
      "
    >
      <form
        id="knowledge-form"
        class="drawer-form"
        @submit.prevent="saveKnowledge"
      >
        <label
          >知识点名称<input
            v-model.trim="knowledgeForm.name"
            class="field"
            required
            maxlength="255"
            placeholder="例如：RAG 检索结果重排"
        /></label>
        <div class="form-pair">
          <label
            >分类<input
              v-model.trim="knowledgeForm.category"
              class="field"
              required
              maxlength="64"
              placeholder="例如：RAG" /></label
          ><label
            >难度<select
              v-model.number="knowledgeForm.difficulty"
              class="field"
            >
              <option v-for="level in 5" :key="level" :value="level">
                {{ level }} 级
              </option>
            </select></label
          >
        </div>
        <label
          >标签<input
            v-model="knowledgeForm.tags"
            class="field"
            placeholder="使用中文逗号分隔" /></label
        ><label
          >知识内容<textarea
            v-model.trim="knowledgeForm.content"
            required
            minlength="10"
            rows="8"
            placeholder="至少 10 个字符，建议使用 Markdown"
          /></label
        ><label
          >来源标题<input
            v-model.trim="knowledgeForm.source_title"
            class="field"
            required
            maxlength="255"
            placeholder="教材、课程资料或官方文档名称" /></label
        ><label
          >来源链接（可选）<input
            v-model.trim="knowledgeForm.source_url"
            class="field"
            type="url"
            maxlength="512"
            placeholder="https://" /></label
        ><label
          >来源与授权说明<input
            v-model.trim="knowledgeForm.license_note"
            class="field"
            required
            maxlength="255"
            placeholder="例如：官方文档，允许教学引用"
        /></label>
        <p v-if="knowledgeFormError" class="form-error" role="alert">
          {{ knowledgeFormError }}
        </p>
      </form>
      <template #footer
        ><div class="drawer-footer">
          <button
            class="btn"
            :disabled="savingKnowledge"
            @click="knowledgeDrawerOpen = false"
          >
            取消</button
          ><button
            class="btn primary"
            type="submit"
            form="knowledge-form"
            :disabled="savingKnowledge"
          >
            {{ savingKnowledge ? "正在保存..." : "保存知识点" }}
          </button>
        </div></template
      >
    </AppDrawer>

    <AppDrawer
      v-model="questionDrawerOpen"
      title="题目详情"
      :subtitle="selectedQuestion ? `${selectedQuestion.knowledge_name} · ${questionPoolLabel(selectedQuestion)}` : ''"
    >
      <div v-if="selectedQuestion" class="question-detail">
        <div class="question-detail-meta">
          <span>{{ selectedQuestion.question_type === 'single_choice' ? '单选题' : '简答题' }}</span>
          <span>{{ quizLevelLabel(selectedQuestion.quiz_level) }} · 难度 {{ selectedQuestion.difficulty }}</span>
          <StatusBadge :label="questionStatusLabel(selectedQuestion.status)" :type="selectedQuestion.status === 'active' ? 'ok' : selectedQuestion.status === 'stale' ? 'warning' : 'wait'" />
        </div>
        <section class="question-detail-block">
          <h3>题干</h3>
          <p>{{ selectedQuestion.stem }}</p>
          <ul v-if="selectedQuestion.options.length" class="question-options">
            <li v-for="(option, index) in selectedQuestion.options" :key="`${index}-${option}`">{{ String.fromCharCode(65 + index) }}. {{ option }}</li>
          </ul>
        </section>
        <section class="question-detail-block"><h3>答案与解析</h3><p><strong>答案：</strong>{{ selectedQuestion.answer }}</p><p>{{ selectedQuestion.explanation }}</p></section>
      </div>
      <template #footer><div class="drawer-footer"><button class="btn" @click="questionDrawerOpen = false">关闭</button></div></template>
    </AppDrawer>

    <AppDrawer
      v-model="uploadOpen"
      title="导入领域文档"
      :subtitle="`${selectedDomain?.name || selectedCode} · 生成候选后由管理员复核`"
      size="wide"
      ><div class="upload-warning">
        <strong>结构化知识导入</strong>
        <p>
          系统保留页码、标题或段落位置，并生成知识与关系候选；正式题目在题库管理中单独导入。
        </p>
      </div>
      <div
        class="upload-compact"
        :class="{ dragging }"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="handleDrop"
      >
        <span>⇧</span><strong>拖入 PDF、Markdown 或 TXT</strong>
        <p>单个文件不超过 20MB</p>
        <button class="btn" :disabled="uploading" @click="fileInput?.click()">
          {{ uploading ? "正在上传..." : "选择文件" }}</button
        ><input
          ref="fileInput"
          class="hidden"
          type="file"
          multiple
          accept=".pdf,.md,.markdown,.txt"
          @change="handleFileInput"
        />
      </div>
      <div class="drawer-form upload-fields">
        <label
          >来源名称<input
            v-model="sourceTitle"
            class="field"
            placeholder="默认使用文件名" /></label
        ><label
          >来源与授权说明<input
            v-model="licenseNote"
            class="field"
            placeholder="例如：内部资料，经授权使用"
        /></label>
      </div>
      <div v-if="uploadResults.length" class="upload-results">
        <div
          v-for="item in uploadResults"
          :key="item.name"
          :class="item.ok ? 'upload-ok' : 'upload-fail'"
        >
          <strong>{{ item.name }}</strong
          ><span>{{ item.message }}</span>
        </div>
      </div></AppDrawer
    >

    <AppDrawer
      ref="importReviewDrawer"
      v-model="importReviewOpen"
      title="自动导入进度与发布"
      :subtitle="importSummary ? `${importSummary.import_id} · ${importSummary.status}` : ''"
      size="wide"
    >
      <div v-if="importLoading && !importSummary" class="empty-view"><strong>正在加载导入状态</strong></div>
      <div v-else-if="!importSummary" class="empty-view"><strong>暂无导入运行</strong></div>
      <div v-else class="candidate-list import-review-content" :aria-busy="importLoading">
        <article class="import-stage-card">
          <div>
            <span class="import-stage-label">当前阶段</span>
            <strong>{{ importStepLabel(importSummary.current_step) }}</strong>
            <p>第 {{ importSummary.attempt }} 次执行 · 基线 {{ importSummary.quality_baseline_version || 'knowledge-import-gold-v1' }}</p>
          </div>
          <StatusBadge :label="importStatusLabel(importSummary.status)" :type="importSummary.error_summary ? 'danger' : 'wait'" />
          <p v-if="importSummary.total_batches">
            模型批次 {{ importSummary.completed_batches || 0 }} / {{ importSummary.total_batches }}
            · 失败 {{ importSummary.failed_batches || 0 }}
            · 已耗时 {{ Math.round(Number(importSummary.elapsed_ms || 0) / 1000) }} 秒
            <span v-if="importSummary.eta_seconds">· 预计剩余 {{ importSummary.eta_seconds }} 秒</span>
          </p>
          <p v-if="importSummary.error_summary" class="document-error">{{ importSummary.error_summary }}</p>
        </article>
        <section class="import-metrics" aria-label="导入质量摘要">
          <article v-for="metric in importMetrics" :key="metric.label">
            <span>{{ metric.label }}</span>
            <strong>{{ metric.value }}</strong>
          </article>
        </section>
        <article v-if="importSummary.blocking_issues?.length" class="candidate-item quality-blockers">
          <header><strong>暂不可发布</strong><StatusBadge label="质量门禁未通过" type="danger" /></header>
          <p v-for="issue in importSummary.blocking_issues" :key="`${issue.code}-${issue.message}`">
            {{ issue.message }}<span v-if="issue.count !== undefined">（{{ issue.count }} 项）</span>
          </p>
        </article>
        <article v-if="importSummary.direction_metrics?.length" class="candidate-item">
          <header><strong>各学习方向质量</strong><StatusBadge label="全节点口径" type="wait" /></header>
          <div class="direction-quality-list">
            <div v-for="metric in importSummary.direction_metrics" :key="metric.value">
              <strong>{{ metric.label }}</strong>
              <span>{{ metric.path_participating_nodes }} / {{ metric.nodes }} 节点 · {{ metric.directional_relations }} 条关系 · 主路径 {{ metric.longest_path_nodes }} 节点</span>
            </div>
          </div>
        </article>
        <article v-if="importSummary.projected_readiness?.proposed_learning_directions?.length" class="candidate-item">
          <header><strong>系统建议的学习方向</strong><StatusBadge label="确认后生效" type="wait" /></header>
          <p>{{ importSummary.projected_readiness.proposed_learning_directions.map((item: any) => item.label).join("、") }}</p>
        </article>
        <article v-if="knowledgeImportCandidates.length" class="candidate-item">
          <header><strong>知识点能力权重复核</strong><StatusBadge label="发布强门禁" type="wait" /></header>
          <p class="candidate-source">前四维之和必须为 1；学习速度由学习过程证据计算，导入值固定为 0。</p>
          <div class="ability-candidate-list">
            <section v-for="candidate in knowledgeImportCandidates" :key="candidate.candidate_id" class="ability-candidate">
              <header>
                <div><strong>{{ candidate.payload.name || candidate.payload.knowledge_id || candidate.candidate_id }}</strong><span>{{ candidate.payload.category || "未分类" }}</span></div>
                <StatusBadge :label="weightSourceLabel(candidate.payload.ability_weight_source)" :type="candidate.validation_errors.length ? 'danger' : 'wait'" />
              </header>
              <div class="ability-weight-grid">
                <label v-for="field in abilityWeightFields" :key="field.key">
                  <span>{{ field.label }}</span>
                  <input
                    v-model.number="ensureCandidateWeights(candidate)[field.key]"
                    type="number"
                    min="0"
                    max="1"
                    step="0.01"
                    :disabled="field.key === 'learning_speed' || savingCandidateId === candidate.candidate_id"
                  />
                </label>
              </div>
              <div class="ability-candidate-footer">
                <span>置信度 {{ Math.round(Number(candidate.payload.ability_weight_confidence || 0) * 100) }}%</span>
                <button class="btn" :disabled="savingCandidateId === candidate.candidate_id" @click="saveCandidateWeights(candidate)">
                  {{ savingCandidateId === candidate.candidate_id ? "保存中" : "保存并校验" }}
                </button>
              </div>
              <p v-for="error in candidate.validation_errors" :key="error" class="document-error">{{ error }}</p>
            </section>
          </div>
        </article>
        <KnowledgeGraph v-if="previewItems.length" :items="previewItems" :relations="previewRelations" />
        <article v-for="event in importSummary.events || []" :key="event.event_id" class="candidate-item">
          <header><strong>{{ event.step }}</strong><StatusBadge :label="event.status" type="wait" /></header>
          <p>执行 {{ event.attempt }} · 事件 {{ event.event_id }}</p>
        </article>
      </div>
      <template #footer>
        <button class="btn" :disabled="importActionLoading" @click="loadImportReview">刷新</button>
        <button v-if="importSummary?.status === 'needs_attention'" class="btn" :disabled="importActionLoading" @click="revalidateImportGraph">重新校验图谱</button>
        <button class="btn primary" :disabled="importActionLoading || importSummary?.status !== 'ready_to_publish'" @click="confirmImport">确认并发布</button>
      </template>
    </AppDrawer>

    <AppDrawer v-model="questionImportOpen" title="导入正式题库" :subtitle="activeQuestionImport ? `${activeQuestionImport.original_name} · ${questionImportStatusLabel(activeQuestionImport.status)}` : `${selectedDomain?.name || selectedCode} · 仅支持 XLSX`" size="wide">
      <template v-if="!activeQuestionImport">
        <div class="upload-warning">
          <strong>按缺口补齐题库</strong>
          <p>模板预填知识点、用途和槽位。上传后执行字段与库存一致性校验，并预览题目数据。</p>
        </div>
        <div class="upload-compact question-upload-dropzone">
          <span>⇧</span><strong>选择已填写的 XLSX 模板</strong>
          <p>一次导入必须全部通过数据校验后才能发布</p>
          <button class="btn primary" :disabled="questionImportActionLoading" @click="questionImportFile?.click()">选择 XLSX</button>
          <input ref="questionImportFile" class="hidden" type="file" accept=".xlsx" @change="handleQuestionImportFile" />
        </div>
      </template>
      <div v-if="questionImportLoading" class="empty-view"><strong>正在加载题目校验结果</strong></div>
      <template v-else-if="activeQuestionImport">
        <article class="import-stage-card question-import-stage">
          <div>
            <span class="import-stage-label">当前阶段</span>
            <strong>{{ questionImportStatusLabel(activeQuestionImport.status) }}</strong>
            <p>逐题预览模板字段与题目数据；题目证据在运行时按关联知识点检索。</p>
          </div>
          <StatusBadge :label="questionImportStatusLabel(activeQuestionImport.status)" :type="activeQuestionImport.status === 'ready_to_publish' || activeQuestionImport.status === 'published' ? 'ok' : activeQuestionImport.needs_attention_count ? 'warning' : 'wait'" />
        </article>
        <section class="import-metrics question-import-metrics" aria-label="题库导入摘要">
          <article><span>模板题目</span><strong>{{ activeQuestionImport.row_count }}</strong><small>本次需全部通过</small></article>
          <article><span>字段有效</span><strong>{{ activeQuestionImport.valid_row_count }}</strong><small>结构、答案、解析与用途有效</small></article>
          <article :class="{ 'has-gap': activeQuestionImport.template_invalid_count }"><span>字段错误</span><strong>{{ activeQuestionImport.template_invalid_count }}</strong><small>修正后重新上传</small></article>
        </section>
        <p v-if="activeQuestionImport.error_summary" class="document-error">{{ activeQuestionImport.error_summary }}</p>
        <div class="question-preview-toolbar">
          <div class="segmented" aria-label="题目校验状态">
            <button v-for="item in questionImportStatusFilters" :key="item.value" type="button" :class="{ active: questionImportPreview.status === item.value }" @click="questionImportPreview.status = item.value">{{ item.label }} <span>{{ item.count }}</span></button>
          </div>
          <select v-model="questionImportPreview.purpose" class="field"><option value="all">全部用途</option><option value="diagnosis">诊断题</option><option value="graded_quiz">分阶测验</option><option value="mastery_validation">掌握检查</option></select>
          <label class="search-field"><span aria-hidden="true">⌕</span><input v-model="questionImportPreview.keyword" type="search" placeholder="搜索题干或知识点" /></label>
        </div>
        <p class="question-preview-count">显示 {{ filteredQuestionImportRows.length }} / {{ questionImportRows.length }} 题</p>
        <div class="question-import-preview">
          <article v-for="row in filteredQuestionImportRows" :key="row.row_id" class="question-import-card" :class="{ 'has-issue': questionRowIssue(row) }">
            <header><div><span class="question-import-kicker">{{ questionImportKnowledgeName(row) }}</span><strong>第 {{ row.row_number }} 行 · {{ questionPurposeLabel(row.purpose) }} · {{ questionLevelLabel(row.quiz_level) }}</strong></div><StatusBadge :label="questionRowStatusLabel(row)" :type="questionRowIssue(row) ? 'warning' : 'ok'" /></header>
            <p class="question-import-meta">{{ questionTypeLabel(row.question_type) }} · 难度 {{ row.difficulty || '--' }}</p>
            <h3>{{ row.stem || '题干尚未填写' }}</h3>
            <ol v-if="row.question_type === 'single_choice'" class="question-option-preview">
              <li v-for="(option, index) in row.options" :key="`${row.row_id}-${index}`" :class="{ correct: questionAnswerLabel(row) === optionLabel(index) }"><b>{{ optionLabel(index) }}</b><span>{{ option }}</span></li>
            </ol>
            <div v-else class="question-answer-preview"><span>参考答案</span><p>{{ String(row.answer || '未填写') }}</p><small v-if="row.rubric.length">评分点：{{ row.rubric.join('；') }}</small></div>
            <details class="question-explanation"><summary>查看答案与解析</summary><p><strong>正确答案：</strong>{{ questionAnswerDisplay(row) }}</p><p><strong>解析：</strong>{{ row.explanation || '未填写' }}</p></details>
            <section v-if="questionRowIssue(row)" class="question-row-issue">
              <div><strong>{{ questionRowIssue(row)?.title }}</strong><p>{{ questionRowIssue(row)?.description }}</p></div>
              <small v-if="questionRowIssue(row)?.fields.length">涉及：{{ questionRowIssue(row)?.fields.join('、') }}</small>
            </section>
          </article>
        </div>
      </template>
      <template #footer><div class="drawer-footer"><template v-if="activeQuestionImport"><button class="btn" :disabled="questionImportActionLoading" @click="startNewQuestionImport">导入另一份</button><button class="btn" :disabled="questionImportActionLoading || activeQuestionImport.status === 'published'" @click="reloadQuestionImport">重新校验</button><button v-if="activeQuestionImport.change_set_id && activeQuestionImport.status === 'published'" class="btn primary" :disabled="questionImportActionLoading" @click="activatePendingChangeSet">一次启用变更</button><button v-else class="btn primary" :disabled="questionImportActionLoading || activeQuestionImport.status !== 'ready_to_publish'" @click="publishImportedQuestions">确认发布</button></template><template v-else><button class="btn" @click="questionImportOpen = false">取消</button><button class="btn" :disabled="questionImportActionLoading" @click="downloadQuestionBankTemplate">重新下载模板</button></template></div></template>
    </AppDrawer>

    <AppDialog
      ref="deleteDialog"
      title="删除来源文档"
      :subtitle="deleteTarget?.original_name || ''"
      ><div class="delete-message">
        <span>!</span>
        <p>系统将撤回该文档来源。仍有其他有效来源的知识继续保留；失去全部来源的知识进入待处理状态。</p>
      </div>
      <template #footer
        ><button class="btn" :disabled="deleting" @click="closeDeleteDialog">
          取消</button
        ><button
          class="btn danger-action"
          :disabled="deleting"
          @click="confirmRemove"
        >
          {{ deleting ? "正在删除..." : "删除文档" }}
        </button></template
      ></AppDialog
    >
  </section>
</template>

<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  type ComponentPublicInstance,
} from "vue";
import { useRoute, useRouter } from "vue-router";
import AppDialog from "@/components/Shared/AppDialog.vue";
import AppDrawer from "@/components/Shared/AppDrawer.vue";
import StatusBadge from "@/components/Shared/StatusBadge.vue";
import PageHeader from "@/components/Shared/PageHeader.vue";
import ReadinessList from "@/components/Shared/ReadinessList.vue";
import KnowledgeGraph from "@/components/KnowledgeGraph/KnowledgeGraph.vue";
import { knowledgeNameLabel } from "@/components/KnowledgeGraph/knowledgeGraph";
import {
  createDomain,
  disableDomain,
  getDomainReadiness,
  getDomainStats,
  listDomains,
  publishDomain,
  updateDomain,
  type DomainStats,
  type DomainSummary,
  type DomainValidationResult,
} from "@/api/domains";
import {
  createKnowledgeItem,
  disableQuestion,
  getRebuildIndexStatus,
  listKnowledgeItems,
  listQuestionBank,
  listKnowledgeRelations,
  rebuildKnowledgeIndex,
  updateKnowledgeItem,
  type KnowledgeItem,
  type KnowledgeRelation,
  type QuestionBankItem,
  type QuestionBankResponse,
  type RebuildIndexStatus,
} from "@/api/knowledge";
import {
  deleteKnowledgeDocument,
  listKnowledgeDocuments,
  retryKnowledgeDocument,
  uploadKnowledgeDocument,
  type KnowledgeDocumentItem,
  type KnowledgeDocumentStatus,
} from "@/api/knowledgeDocuments";
import {
  confirmKnowledgeImport,
  cancelKnowledgeImport,
  getKnowledgeImportGraph,
  getKnowledgeImportSummary,
  listImportCandidates,
  revalidateKnowledgeImportGraph,
  updateImportCandidate,
  validateKnowledgeImport,
  type AbilityWeights,
  type GraphPreview,
  type ImportCandidate,
  type KnowledgeImportSummary,
} from "@/api/knowledgeImports";
import {
  downloadQuestionTemplate,
  getQuestionImport,
  listQuestionImportRows,
  publishQuestionImport,
  uploadQuestionImport,
  validateQuestionImport,
  type QuestionImportRow,
  type QuestionImportRun,
} from "@/api/questionImports";
import {
  activateDomainChangeSet,
  listDomainChangeSets,
  type DomainChangeSet,
} from "@/api/domainChangeSets";
import { useDomainStore } from "@/stores/domainStore";
import { useToast } from "@/composables/useToast";
import { formatBeijingDateTime } from "@/utils/dateTime";
import {
  configList,
  domainReadiness,
  filterAndSortDocuments,
  filterKnowledgeItems,
  filterQuestionBank,
  getDomainTaskAction,
  indexUiState,
  type DocumentFilters,
  type KnowledgeFilters,
  type QuestionFilters,
} from "./domainHubState";

type PaneId = "overview" | "assets" | "rules" | "operations";
type AssetView = "items" | "questions" | "documents" | "graph";
const route = useRoute(),
  router = useRouter(),
  domainStore = useDomainStore(),
  { showToast } = useToast();
const panes: Array<{ id: PaneId; label: string }> = [
  { id: "overview", label: "概览" },
  { id: "assets", label: "知识资产" },
  { id: "rules", label: "领域配置" },
  { id: "operations", label: "运行检查" },
];
const domains = ref<DomainSummary[]>([]),
  selectedCode = ref(domainStore.currentDomainCode),
  activePane = ref<PaneId>(
    validPane(route.query.tab) ? (route.query.tab as PaneId) : "overview",
  ),
  assetView = ref<AssetView>(
    validAssetView(route.query.view)
      ? (route.query.view as AssetView)
      : "items",
  );
const stats = ref<DomainStats | null>(null),
  documents = ref<KnowledgeDocumentItem[]>([]),
  knowledgeItems = ref<KnowledgeItem[]>([]),
  questionBank = ref<QuestionBankItem[]>([]),
  questionBankTotal = ref(0),
  activeQuestionBankTotal = ref(0),
  questionCoverage = ref<QuestionBankResponse["coverage"] | null>(null),
  relations = ref<KnowledgeRelation[]>([]);
const loading = ref(false),
  graphLoading = ref(false),
  errorMessage = ref(""),
  validating = ref(false),
  rebuilding = ref(false),
  validationResult = ref<DomainValidationResult | null>(null),
  rebuildStatus = ref<RebuildIndexStatus | null>(null);
const questionActionLoading = ref("");
const selectedKnowledgeId = ref<string | null>(null),
  highlightedKnowledgeId = ref<string | null>(null);
const questionDrawerOpen = ref(false),
  selectedQuestion = ref<QuestionBankItem | null>(null);
const showReadinessDetails = ref(false),
  showEvidenceDetails = ref(false),
  showConfigDetails = ref(false),
  showValidationDetails = ref(false);
const knowledgeRowRefs = new Map<string, HTMLElement>();
const domainDrawerOpen = ref(false),
  editingDomain = ref<DomainSummary | null>(null),
  lifecycleLoading = ref(false),
  domainFormError = ref("");
const domainForm = reactive({
  domain_code: "",
  name: "",
  description: "",
  learning_directions: [] as Array<{ value: string; label: string; description: string; tags: string }>,
});
const knowledgeFilters = reactive<KnowledgeFilters>({
  keyword: "",
  category: "all",
  difficulty: "all",
  indexStatus: "all",
});
const questionFilters = reactive<QuestionFilters>({
  keyword: "",
  purpose: "all",
  level: "all",
  difficulty: "all",
  status: "active",
});
const documentFilters = reactive<DocumentFilters>({
  keyword: "",
  status: "all",
  fileType: "all",
});
const knowledgeDrawerOpen = ref(false),
  editingKnowledge = ref<KnowledgeItem | null>(null),
  savingKnowledge = ref(false),
  knowledgeFormError = ref("");
const knowledgeForm = reactive({
  name: "",
  category: "",
  difficulty: 2,
  tags: "",
  content: "",
  source_title: "",
  source_url: "",
  license_note: "",
});
const uploadOpen = ref(false),
  uploading = ref(false),
  dragging = ref(false),
  fileInput = ref<HTMLInputElement | null>(null),
  sourceTitle = ref(""),
  licenseNote = ref(""),
  uploadResults = ref<Array<{ name: string; ok: boolean; message: string }>>(
    [],
  );
const importReviewOpen = ref(false),
  importLoading = ref(false),
  importActionLoading = ref(false),
  importSummary = ref<KnowledgeImportSummary | null>(null),
  importGraph = ref<GraphPreview | null>(null),
  importCandidates = ref<ImportCandidate[]>([]),
  savingCandidateId = ref(""),
  activeImportId = ref("");
type DrawerController = {
  getBodyScrollTop: () => number;
  setBodyScrollTop: (value: number) => void;
};
const importReviewDrawer = ref<DrawerController | null>(null);
const knowledgeImportCandidates = computed(() =>
  importCandidates.value.filter((candidate) => candidate.candidate_type === "knowledge_item"),
);
function previewItem(node: GraphPreview["nodes"][number]): KnowledgeItem {
  return {
    knowledge_id: node.knowledge_id || node.id,
    domain_code: selectedCode.value,
    name: node.name,
    category: node.category,
    difficulty: node.difficulty,
    tags: node.tags,
    content: "",
    source_title: node.source_chunk_ids.join(", "),
    source_url: null,
    license_note: "",
    needs_reembedding: true,
  };
}
function previewRelationsFor(graph: GraphPreview | null, availableIds: Set<string>): KnowledgeRelation[] {
  const nodes = new Map((graph?.nodes || []).map((node) => [node.id, previewItem(node)]));
  return (graph?.edges || [])
    .filter((edge) => edge.accepted)
    .map((edge) => {
      const source = nodes.get(edge.source);
      const target = nodes.get(edge.target);
      return {
        source_id: source?.knowledge_id || edge.source,
        source_name: source?.name || edge.source,
        target_id: target?.knowledge_id || edge.target,
        target_name: target?.name || edge.target,
        relation_type: ["depends_on", "next_step"].includes(edge.relation_type)
          ? "dependent"
          : edge.relation_type === "related_to"
            ? "related"
            : edge.relation_type,
      } as KnowledgeRelation;
    })
    .filter((edge) => availableIds.has(edge.source_id) && availableIds.has(edge.target_id));
}
const previewItems = computed<KnowledgeItem[]>(() => (importGraph.value?.nodes || []).map(previewItem));
const previewRelations = computed<KnowledgeRelation[]>(() =>
  previewRelationsFor(importGraph.value, new Set(previewItems.value.map((item) => item.knowledge_id))),
);
const importMetrics = computed(() => {
  const summary = importSummary.value;
  if (!summary) return [];
  const readinessComplete = Boolean(summary.projected_readiness);
  const candidateTotal = summary.knowledge_items || 0;
  const projectedTotal = summary.projected_knowledge_items || (
    Number(summary.path_participating_nodes || 0) + Number(summary.isolated_nodes || 0)
  );
  return [
    { label: "本次候选知识", value: String(candidateTotal) },
    { label: "来源追溯", value: `${Math.round(Number(summary.source_traceability || 0) * 100)}%` },
    {
      label: "预计全域路径参与",
      value: readinessComplete ? `${summary.path_participating_nodes || 0} / ${projectedTotal}` : "未完成",
    },
    {
      label: "预计全域学习路径孤立",
      value: readinessComplete ? `${summary.isolated_nodes || 0}` : "未完成",
    },
    { label: "事实关系", value: String(summary.factual_relations || 0) },
    { label: "教学推荐", value: String(summary.recommended_relations || 0) },
    {
      label: "候选权重就绪",
      value: readinessComplete ? `${summary.ability_weights_ready || 0} / ${candidateTotal}` : "未完成",
    },
    { label: "自动修复", value: `${summary.repair_rounds || 0} 轮` },
  ];
});
const deleteDialog = ref<InstanceType<typeof AppDialog> | null>(null),
  deleteTarget = ref<KnowledgeDocumentItem | null>(null),
  deleting = ref(false);
let pollTimer: number | undefined,
  rebuildPollTimer: number | undefined,
  highlightTimer: number | undefined,
  loadVersion = 0;

const selectedDomain = computed(
  () =>
    domains.value.find((domain) => domain.domain_code === selectedCode.value) ||
    null,
);
const parsedConfig = computed(() => configList(selectedDomain.value));
const filteredKnowledgeItems = computed(() =>
    filterKnowledgeItems(knowledgeItems.value, knowledgeFilters),
  ),
  categories = computed(() =>
    [...new Set(knowledgeItems.value.map((item) => item.category))].sort(
      (a, b) => a.localeCompare(b, "zh-CN"),
    ),
  );
const hasKnowledgeFilters = computed(
  () =>
    Boolean(knowledgeFilters.keyword.trim()) ||
    knowledgeFilters.category !== "all" ||
    knowledgeFilters.difficulty !== "all" ||
    knowledgeFilters.indexStatus !== "all",
);
const filteredQuestionBank = computed(() =>
  filterQuestionBank(questionBank.value, questionFilters),
);
const hasQuestionFilters = computed(
  () =>
    Boolean(questionFilters.keyword.trim()) ||
    questionFilters.purpose !== "all" ||
    questionFilters.level !== "all" ||
    questionFilters.difficulty !== "all" ||
    questionFilters.status !== "all",
);
const filteredDocuments = computed(() =>
  filterAndSortDocuments(documents.value, documentFilters),
);
const hasDocumentFilters = computed(
  () =>
    Boolean(documentFilters.keyword.trim()) ||
    documentFilters.status !== "all" ||
    documentFilters.fileType !== "all",
);
const readinessItems = computed(() =>
    domainReadiness(
      stats.value,
      validationResult.value?.rag?.ready,
      rebuildStatus.value?.running,
      ["failed", "interrupted"].includes(rebuildStatus.value?.status || ""),
    ),
  ),
  attentionItems = computed(() =>
    readinessItems.value.filter((item) => item.state !== "ready"),
  );
const questionImportOpen = ref(false),
  questionImportLoading = ref(false),
  questionImportActionLoading = ref(false),
  questionImportFile = ref<HTMLInputElement | null>(null),
  activeQuestionImport = ref<QuestionImportRun | null>(null),
  questionImportChangeSetId = ref(""),
  questionImportRows = ref<QuestionImportRow[]>([]);
const questionImportPreview = reactive({ status: "all", purpose: "all", keyword: "" });
const questionImportStatusFilters = computed(() => [
  { value: "all", label: "全部", count: questionImportRows.value.length },
  { value: "passed", label: "已通过", count: questionImportRows.value.filter((row) => ["valid", "published"].includes(row.status)).length },
  { value: "invalid", label: "字段错误", count: questionImportRows.value.filter((row) => row.status === "template_invalid").length },
]);
const filteredQuestionImportRows = computed(() => {
  const keyword = questionImportPreview.keyword.trim().toLowerCase();
  return questionImportRows.value.filter((row) => {
    if (questionImportPreview.status === "passed" && !["valid", "published"].includes(row.status)) return false;
    if (questionImportPreview.status === "invalid" && row.status !== "template_invalid") return false;
    if (questionImportPreview.purpose !== "all" && row.purpose !== questionImportPreview.purpose) return false;
    return !keyword || [row.stem, questionImportKnowledgeName(row), row.knowledge_ref].join(" ").toLowerCase().includes(keyword);
  });
});
const domainChangeSets = ref<DomainChangeSet[]>([]);
const activeChangeSet = computed(() =>
  domainChangeSets.value.find((changeSet) =>
    ["preparing", "ready_for_questions", "questions_preparing", "ready_to_activate"].includes(changeSet.status),
  ) || null,
);
const pendingChangeOperationDescription = computed(() => {
  const changeSet = activeChangeSet.value;
  if (!changeSet) return "";
  const stagedCount = stats.value?.staged_knowledge_items || 0;
  const label = changeSetStatusLabel(changeSet.status);
  if (changeSet.status === "ready_to_activate") {
    return `${stagedCount} 个新增知识及其候选索引已准备完成，点击“一次启用变更”后才会切换活动索引。`;
  }
  if (["ready_for_questions", "questions_preparing"].includes(changeSet.status)) {
    return `${stagedCount} 个新增知识不属于当前活动索引；候选索引已准备，当前阶段为“${label}”。`;
  }
  return `${stagedCount} 个新增知识正在准备，尚未影响当前活动索引。当前阶段为“${label}”。`;
});
const graphView = ref<"active" | "pending">("active");
const pendingGraph = ref<GraphPreview | null>(null);
const pendingGraphLoading = ref(false);
const pendingGraphPathIsolatedCount = computed(
  () => pendingGraph.value?.nodes.filter((node) => node.isolated).length || 0,
);
const pendingChangeDocument = computed(() => {
  const documentIds = activeChangeSet.value?.summary.documents || [];
  return documents.value.find((document) => documentIds.includes(document.document_id)) || null;
});
const pendingGraphItems = computed<KnowledgeItem[]>(() => {
  if (!pendingGraph.value) return [];
  const items = new Map(knowledgeItems.value.map((item) => [item.knowledge_id, item]));
  for (const node of pendingGraph.value.nodes) {
    const item = previewItem(node);
    items.set(item.knowledge_id, { ...items.get(item.knowledge_id), ...item });
  }
  return [...items.values()];
});
const pendingGraphRelations = computed<KnowledgeRelation[]>(() => {
  const availableIds = new Set(pendingGraphItems.value.map((item) => item.knowledge_id));
  const relationMap = new Map(
    relations.value.map((relation) => [
      `${relation.source_id}:${relation.target_id}:${relation.relation_type}`,
      relation,
    ]),
  );
  for (const relation of previewRelationsFor(pendingGraph.value, availableIds)) {
    relationMap.set(`${relation.source_id}:${relation.target_id}:${relation.relation_type}`, relation);
  }
  return [...relationMap.values()];
});
const displayedGraphItems = computed(() =>
  graphView.value === "pending" ? pendingGraphItems.value : knowledgeItems.value,
);
const displayedGraphRelations = computed(() =>
  graphView.value === "pending" ? pendingGraphRelations.value : relations.value,
);
const passedReadinessItems = computed(() =>
  readinessItems.value.filter((item) => item.state === "ready"),
);
const overallReadinessClass = computed(() =>
    attentionItems.value.some((item) => item.state === "error")
      ? "error"
      : attentionItems.value.length
        ? "warning"
        : "ready",
  ),
  overallReadinessLabel = computed(() =>
    overallReadinessClass.value === "ready"
      ? "可用于生成"
      : overallReadinessClass.value === "error"
        ? "存在阻断项"
        : "需要处理",
  );
const practiceGenerationMode = computed(
  () => validationResult.value?.evidence_coverage?.practice_generation_mode,
);
const practiceModeDescription = computed(() =>
  practiceGenerationMode.value === "evidence_backed"
    ? "知识库包含可核对的预期结果证据，实训字段仍按切片逐项授权。"
    : "当前缺少预期结果证据，实训指南将自动生成阅读、比较和观察练习，不生成固定输出、命令或排错结论。",
);
const evidenceCapabilityItems = computed(() => {
  const counts = validationResult.value?.evidence_coverage?.capabilities;
  if (!counts) return [];
  return [
    { key: "operation", label: "操作步骤", count: counts.operation || 0 },
    { key: "command", label: "命令", count: counts.command || 0 },
    { key: "code_example", label: "代码", count: counts.code_example || 0 },
    { key: "expected_result", label: "预期结果", count: counts.expected_result || 0 },
    { key: "error_handling", label: "排错", count: counts.error_handling || 0 },
    { key: "version_boundary", label: "版本边界", count: counts.version_boundary || 0 },
  ];
});
const assetViews = computed(() => [
  { id: "items" as const, label: "知识点", count: knowledgeItems.value.length },
  { id: "questions" as const, label: "题库", count: activeQuestionBankTotal.value },
  {
    id: "documents" as const,
    label: "来源文档",
    count: documents.value.length,
  },
  { id: "graph" as const, label: "关系图谱", count: relations.value.length },
]);
const currentIndexState = computed(() =>
  indexUiState(
    validationResult.value?.rag_ready,
    stats.value?.pending_embeddings || 0,
    rebuilding.value ? "running" : rebuildStatus.value?.status,
  ),
);
const missingQuestionKnowledgeIds = computed(() => {
  const coverage = questionCoverage.value;
  if (!coverage) return [];
  return [...new Set([
    ...coverage.missing_diagnosis_knowledge_ids,
    ...coverage.missing_quiz_knowledge_ids,
    ...coverage.missing_mastery_reserve_knowledge_ids,
  ])];
});
const questionCoverageCards = computed(() => {
  const coverage = questionCoverage.value;
  const total = coverage?.total_items || stats.value?.knowledge_items || 0;
  const groups = [
    { label: "诊断题", missing: coverage?.missing_diagnosis_knowledge_ids.length || 0 },
    { label: "分阶测验", missing: coverage?.missing_quiz_knowledge_ids.length || 0 },
    { label: "掌握检查", missing: coverage?.missing_mastery_reserve_knowledge_ids.length || 0 },
  ];
  return groups.map((group) => ({
    ...group,
    ready: Math.max(0, total - group.missing),
    note: group.missing ? `待补 ${group.missing} 个知识点` : "覆盖完整",
  }));
});
const indexBlockedByQuestionBank = computed(() =>
  Boolean(validationResult.value?.rag?.reason?.startsWith("question_")),
);
const currentTask = computed(() =>
  getDomainTaskAction({
    stats: stats.value,
    domainStatus: selectedDomain.value?.status,
    indexState: currentIndexState.value,
    validationPassed: validationResult.value?.passed,
    missingQuestionKnowledgeCount: missingQuestionKnowledgeIds.value.length,
    indexBlockedByQuestionBank: indexBlockedByQuestionBank.value,
  }),
);
const primaryActionBusy = computed(() => {
  if (currentTask.value.id === "loading") return true;
  if (currentTask.value.id === "rebuild_index") return rebuilding.value;
  if (currentTask.value.id === "open_validation") return validating.value;
  if (currentTask.value.id === "publish_domain") return lifecycleLoading.value;
  return false;
});
const documentSummary = computed(() => ({
  ready: documents.value.filter((document) => document.status === "ready").length,
  processing: documents.value.filter((document) => isProcessing(document.status)).length,
  failed: documents.value.filter((document) => ["failed", "cancelled", "interrupted"].includes(document.status)).length,
}));
const indexStatusLabel = computed(() => ({
  running: "重建中",
  ready: "已同步",
  needs_rebuild: "需重建",
  failed: "异常",
})[currentIndexState.value]);
const indexStatusType = computed(() =>
  currentIndexState.value === "ready"
    ? "ok"
    : currentIndexState.value === "failed"
      ? "error"
      : currentIndexState.value === "running"
        ? "info"
        : "wait",
);
const showRebuildMessage = computed(
  () =>
    currentIndexState.value === "needs_rebuild" ||
    Boolean(rebuildStatus.value?.status && rebuildStatus.value.status !== "idle"),
);
const rebuildResultLabel = computed(() =>
  rebuildStatus.value?.status === "success"
    ? rebuildStatus.value.result?.status === "unchanged"
      ? "无变化"
      : "成功"
    : rebuildStatus.value?.status === "failed"
      ? "失败"
      : rebuildStatus.value?.status === "interrupted"
        ? "已中断"
        : "-",
);
const rebuildMessageTitle = computed(() =>
  currentIndexState.value === "needs_rebuild"
    ? validationResult.value?.rag?.reason?.startsWith("question_")
      ? "正式题库尚未就绪"
      : "活动索引尚未同步"
    : rebuildStatus.value?.status === "running"
    ? "正在重建索引"
    : rebuildStatus.value?.status === "success"
      ? "索引重建完成"
      : rebuildStatus.value?.status === "interrupted"
        ? "索引重建已中断"
        : "索引重建失败",
);
const rebuildMessageBody = computed(
  () =>
    (currentIndexState.value === "needs_rebuild"
      ? validationResult.value?.rag?.reason?.startsWith("question_")
        ? `当前阻断项来自正式题库（${validationResult.value.rag.reason}），无需重建向量索引。`
        : `当前检索索引校验未通过（${validationResult.value?.rag?.reason || "索引版本或数据版本不一致"}），请重建索引。`
      : rebuildStatus.value?.message) ||
    (rebuildStatus.value?.result?.status === "unchanged"
      ? "知识库没有变化，未重复向量化。"
      : rebuildStatus.value?.status === "success"
        ? `已索引 ${rebuildStatus.value.result?.indexed_items ?? "-"} 个知识点，重新向量化 ${rebuildStatus.value.result?.reembedded_items ?? 0} 个。`
        : "请检查依赖状态后重试。"),
);
const validationRows = computed(() => {
  const result = validationResult.value;
  if (result?.checks?.length) {
    return result.checks.map((check) => ({
      key: check.key,
      label: check.label,
      actual: check.actual,
      target: check.target,
      passed: check.passed,
    }));
  }
  if (!result?.counts || !result.targets) return [];
  const labels: Record<string, string> = {
    knowledge_items: "知识点",
    diagnostic_questions: "诊断题",
    chroma_vectors: "检索索引向量",
  };
  return Object.entries(result.targets).map(([key, target]) => {
    const countKey = key === "vector_chunks" ? "chroma_vectors" : key;
    const actual = result.counts?.[countKey] ?? 0;
    return {
      key,
      label: labels[countKey] || key,
      actual,
      target,
      passed: actual >= target,
    };
  });
});

function validPane(value: unknown): value is PaneId {
  return panes.some((pane) => pane.id === value);
}
function validAssetView(value: unknown): value is AssetView {
  return ["items", "questions", "documents", "graph"].includes(String(value));
}
function updateRoute() {
  router.replace({
    query: {
      tab: activePane.value,
      ...(activePane.value === "assets" ? { view: assetView.value } : {}),
    },
  });
}
function selectPane(id: PaneId) {
  activePane.value = id;
  updateRoute();
}
function selectAssetView(id: AssetView) {
  assetView.value = id;
  updateRoute();
}
function openAssetView(id: AssetView) {
  activePane.value = "assets";
  assetView.value = id;
  updateRoute();
}
function openQuestionDetail(question: QuestionBankItem) {
  selectedQuestion.value = question;
  questionDrawerOpen.value = true;
}
async function runPrimaryAction() {
  switch (currentTask.value.id) {
    case "open_documents":
      openAssetView("documents");
      return;
    case "rebuild_index":
      selectPane("operations");
      await rebuild();
      return;
    case "open_questions":
      openAssetView("questions");
      return;
    case "open_validation":
      selectPane("operations");
      await validate();
      return;
    case "publish_domain":
      await publishSelectedDomain();
      return;
    case "review_operations":
      selectPane("operations");
      return;
    default:
      return;
  }
}
function setKnowledgeRowRef(
  knowledgeId: string,
  element: Element | ComponentPublicInstance | null,
) {
  if (element instanceof HTMLElement) knowledgeRowRefs.set(knowledgeId, element);
  else knowledgeRowRefs.delete(knowledgeId);
}
function locateInGraph(knowledgeId: string) {
  if (!knowledgeItems.value.some((item) => item.knowledge_id === knowledgeId)) {
    showToast("未找到该知识点，请刷新数据后重试。", "error");
    return;
  }
  selectedKnowledgeId.value = knowledgeId;
  openAssetView("graph");
}
async function returnToKnowledgeItem(knowledgeId: string) {
  if (!knowledgeItems.value.some((item) => item.knowledge_id === knowledgeId)) {
    showToast("未找到该知识点，请刷新数据后重试。", "error");
    return;
  }
  clearKnowledgeFilters();
  openAssetView("items");
  await nextTick();
  const row = knowledgeRowRefs.get(knowledgeId);
  if (!row) {
    showToast("知识点已加载，但暂时无法定位到对应行。", "error");
    return;
  }
  row.scrollIntoView({ behavior: "smooth", block: "center" });
  highlightedKnowledgeId.value = knowledgeId;
  if (highlightTimer) window.clearTimeout(highlightTimer);
  highlightTimer = window.setTimeout(() => {
    highlightedKnowledgeId.value = null;
  }, 1500);
}
function readinessDescription(item: {
  key: string;
  actual: number;
  target: number;
  state: string;
}) {
  if (item.key === "knowledge")
    return item.state === "ready"
      ? "已达到比赛 MVP 数据规模"
      : `还需补充 ${Math.max(0, item.target - item.actual)} 个知识点`;
  if (item.key === "questions")
    return item.state === "ready"
      ? "诊断题规模达到目标"
      : `还需补充 ${Math.max(0, item.target - item.actual)} 道诊断题`;
  if (item.key === "index")
    return item.state === "ready"
      ? `当前活动索引可用，共 ${validationResult.value?.rag?.indexed_chunk_count ?? "-"} 个切片`
      : item.state === "running"
        ? "后台正在重建 Candidate RAG 索引"
        : validationResult.value?.rag?.reason ||
          "当前 Candidate RAG 索引不可用";
  return item.state === "ready"
    ? "来源文档没有处理失败项"
    : `${item.actual} 份来源文档处理失败`;
}

function domainStatusLabel(status?: string) {
  return ({ draft: "草稿", preparing: "准备中", ready: "已发布", disabled: "已停用" } as Record<string, string>)[status || ""] || "未知状态";
}

function addDirection() {
  if (domainForm.learning_directions.length < 6)
    domainForm.learning_directions.push({ value: "", label: "", description: "", tags: "" });
}

function removeDirection(index: number) {
  if (domainForm.learning_directions.length > 1)
    domainForm.learning_directions.splice(index, 1);
}

function openDomainEditor(domain?: DomainSummary) {
  editingDomain.value = domain || null;
  domainForm.domain_code = domain?.domain_code || "";
  domainForm.name = domain?.name || "";
  domainForm.description = domain?.description || "";
  domainForm.learning_directions = (domain?.learning_directions || []).map((item) => ({
    value: item.value,
    label: item.label,
    description: item.description || "",
    tags: (item.match_tags || []).join(","),
  }));
  domainFormError.value = "";
  domainDrawerOpen.value = true;
}

async function saveDomain() {
  lifecycleLoading.value = true;
  domainFormError.value = "";
  const payload = {
    name: domainForm.name,
    description: domainForm.description,
    learning_directions: (editingDomain.value ? domainForm.learning_directions : []).map((item) => ({
      value: item.value,
      label: item.label,
      description: item.description,
      match_tags: item.tags.split(/[，,]/).map((tag) => tag.trim()).filter(Boolean),
    })),
  };
  try {
    const saved = editingDomain.value
      ? await updateDomain(editingDomain.value.domain_code, payload)
      : await createDomain({ ...payload, domain_code: domainForm.domain_code });
    selectedCode.value = saved.domain_code;
    domainDrawerOpen.value = false;
    await loadAll();
    showToast(editingDomain.value ? "领域配置已保存" : "领域已创建", "success");
  } catch (error: any) {
    domainFormError.value = error?.response?.data?.detail || "领域保存失败，请检查代码和学习方向。";
  } finally {
    lifecycleLoading.value = false;
  }
}

async function publishSelectedDomain() {
  if (!selectedCode.value) return;
  lifecycleLoading.value = true;
  try {
    await publishDomain(selectedCode.value);
    await loadAll();
    showToast("领域已发布，学习者现在可以选择该领域", "success");
  } catch (error: any) {
    const detail = error?.response?.data?.detail;
    validationResult.value = detail?.readiness || validationResult.value;
    showToast(detail?.code || "领域尚未通过全部就绪检查", "error");
  } finally {
    lifecycleLoading.value = false;
  }
}

async function disableSelectedDomain() {
  if (!selectedCode.value) return;
  lifecycleLoading.value = true;
  try {
    await disableDomain(selectedCode.value);
    await loadAll();
    showToast("领域已停用；历史任务和资源仍可查看", "success");
  } catch (error: any) {
    showToast(error?.response?.data?.detail || "领域停用失败", "error");
  } finally {
    lifecycleLoading.value = false;
  }
}

async function loadAll() {
  loading.value = true;
  errorMessage.value = "";
  try {
    domains.value = await listDomains();
    if (
      !domains.value.some(
        (domain) => domain.domain_code === selectedCode.value,
      ) &&
      domains.value.length
    )
      selectedCode.value = domains.value[0].domain_code;
    await loadDomain();
  } catch {
    errorMessage.value = "无法读取领域数据，请确认数据库和后端服务可用。";
  } finally {
    loading.value = false;
  }
}
async function switchDomain() {
  stopPolling();
  graphView.value = "active";
  pendingGraph.value = null;
  validationResult.value = null;
  rebuildStatus.value = null;
  stats.value = null;
  documents.value = [];
  knowledgeItems.value = [];
  relations.value = [];
  clearKnowledgeFilters();
  clearQuestionFilters();
  clearDocumentFilters();
  await loadDomain();
  await syncRebuildStatus();
}
async function loadDomain() {
  const version = ++loadVersion;
  selectedKnowledgeId.value = null;
  highlightedKnowledgeId.value = null;
  loading.value = true;
  graphLoading.value = true;
  errorMessage.value = "";
  domainStore.domains = domains.value;
  domainStore.setWorkspaceDomain(selectedCode.value);
  try {
    const [s, d, r, i, q, validation, changeSets] = await Promise.all([
      getDomainStats(selectedCode.value),
      listKnowledgeDocuments(selectedCode.value),
      listKnowledgeRelations(selectedCode.value),
      listKnowledgeItems(selectedCode.value, 500),
      listQuestionBank(selectedCode.value, "active"),
      getDomainReadiness(selectedCode.value),
      listDomainChangeSets(selectedCode.value),
    ]);
    if (version !== loadVersion) return;
    stats.value = s;
    documents.value = d.documents;
    relations.value = r;
    knowledgeItems.value = i.items;
    questionBank.value = q.items;
    questionBankTotal.value = q.total;
    activeQuestionBankTotal.value = q.total;
    questionCoverage.value = q.coverage;
    validationResult.value = validation;
    domainChangeSets.value = changeSets;
    if (!changeSets.some((changeSet) => changeSet.status !== "activated")) {
      graphView.value = "active";
      pendingGraph.value = null;
    }
    const acceptingChangeSet = changeSets.find((changeSet) =>
      ["preparing", "ready_for_questions", "questions_preparing"].includes(changeSet.status),
    );
    questionImportChangeSetId.value = acceptingChangeSet?.change_set_id || "";
    schedulePolling();
  } catch {
    if (version === loadVersion)
      errorMessage.value = "当前领域数据加载失败，请稍后重试。";
  } finally {
    if (version === loadVersion) {
      loading.value = false;
      graphLoading.value = false;
    }
  }
}
async function loadDocuments(silent = false) {
  const domain = selectedCode.value;
  const wasProcessing = documents.value.some((item) => isProcessing(item.status));
  try {
    const data = await listKnowledgeDocuments(domain);
    if (domain !== selectedCode.value) return;
    documents.value = data.documents;
    if (importReviewOpen.value && activeImportId.value) void loadImportReview();
    const stillProcessing = documents.value.some((item) => isProcessing(item.status));
    if (wasProcessing && !stillProcessing) {
      await loadDomain();
      return;
    }
    schedulePolling();
  } catch {
    if (!silent) showToast("来源文档加载失败");
  }
}
function stopPolling() {
  if (pollTimer !== undefined) {
    window.clearTimeout(pollTimer);
    pollTimer = undefined;
  }
}
function schedulePolling() {
  stopPolling();
  if (documents.value.some((item) => isProcessing(item.status)))
    pollTimer = window.setTimeout(() => loadDocuments(true), 2000);
}
function clearKnowledgeFilters() {
  knowledgeFilters.keyword = "";
  knowledgeFilters.category = "all";
  knowledgeFilters.difficulty = "all";
  knowledgeFilters.indexStatus = "all";
}
function clearQuestionFilters() {
  questionFilters.keyword = "";
  questionFilters.purpose = "all";
  questionFilters.level = "all";
  questionFilters.difficulty = "all";
  const statusChanged = questionFilters.status !== "active";
  questionFilters.status = "active";
  if (statusChanged) void loadQuestionBankForStatus();
}

let questionBankLoadVersion = 0;
async function loadQuestionBankForStatus() {
  const requestVersion = ++questionBankLoadVersion;
  const status = questionFilters.status === "all" ? undefined : questionFilters.status;
  try {
    const result = await listQuestionBank(selectedCode.value, status);
    if (requestVersion !== questionBankLoadVersion) return;
    questionBank.value = result.items;
    questionBankTotal.value = result.total;
    questionCoverage.value = result.coverage;
    if (status === "active") activeQuestionBankTotal.value = result.total;
  } catch {
    if (requestVersion === questionBankLoadVersion) {
      showToast("题库列表加载失败，请稍后重试", "error");
    }
  }
}
function clearDocumentFilters() {
  documentFilters.keyword = "";
  documentFilters.status = "all";
  documentFilters.fileType = "all";
}
function openKnowledgeEditor(item?: KnowledgeItem) {
  editingKnowledge.value = item || null;
  Object.assign(
    knowledgeForm,
    item
      ? {
          name: item.name,
          category: item.category,
          difficulty: item.difficulty,
          tags: item.tags.join("，"),
          content: item.content,
          source_title: item.source_title,
          source_url: item.source_url || "",
          license_note: item.license_note,
        }
      : {
          name: "",
          category: "",
          difficulty: 2,
          tags: "",
          content: "",
          source_title: "",
          source_url: "",
          license_note: "",
        },
  );
  knowledgeFormError.value = "";
  knowledgeDrawerOpen.value = true;
}
async function saveKnowledge() {
  if (knowledgeForm.content.length < 10) {
    knowledgeFormError.value = "知识内容至少需要 10 个字符。";
    return;
  }
  savingKnowledge.value = true;
  knowledgeFormError.value = "";
  const payload = {
    name: knowledgeForm.name,
    category: knowledgeForm.category,
    difficulty: knowledgeForm.difficulty,
    tags: knowledgeForm.tags
      .split(/[，,]/)
      .map((tag) => tag.trim())
      .filter(Boolean),
    content: knowledgeForm.content,
    source_title: knowledgeForm.source_title,
    source_url: knowledgeForm.source_url || null,
    license_note: knowledgeForm.license_note,
  };
  try {
    const result = editingKnowledge.value
      ? await updateKnowledgeItem(editingKnowledge.value.knowledge_id, payload)
      : await createKnowledgeItem({
          ...payload,
          domain_code: selectedCode.value,
        });
    const index = knowledgeItems.value.findIndex(
      (item) => item.knowledge_id === result.item.knowledge_id,
    );
    if (index >= 0) knowledgeItems.value[index] = result.item;
    else knowledgeItems.value.push(result.item);
    knowledgeDrawerOpen.value = false;
    showToast(
      `知识点已保存，需要重建索引；影响 ${result.affected_learning_paths} 条学习路径、${result.affected_resources} 份资源`,
    );
    await loadDomain();
  } catch (error: any) {
    knowledgeFormError.value =
      error?.response?.data?.detail || "知识点保存失败，请检查填写内容。";
  } finally {
    savingKnowledge.value = false;
  }
}
async function uploadFiles(files: File[]) {
  if (!files.length) return;
  uploading.value = true;
  uploadResults.value = [];
  let latestImportId = "";
  for (const file of files) {
    try {
      const document = await uploadKnowledgeDocument(
        file,
        selectedCode.value,
        sourceTitle.value,
        licenseNote.value,
      );
      latestImportId = document.import_id || document.run_id || document.document_id;
      uploadResults.value.push({
        name: file.name,
        ok: true,
        message: "已进入结构化候选解析流程",
      });
    } catch (error: any) {
      uploadResults.value.push({
        name: file.name,
        ok: false,
        message: error?.response?.data?.detail || "上传失败",
      });
    }
  }
  uploading.value = false;
  if (fileInput.value) fileInput.value.value = "";
  await loadDocuments();
  if (latestImportId) {
    activeImportId.value = latestImportId;
    uploadOpen.value = false;
    importReviewOpen.value = true;
    await loadImportReview();
  }
}
async function loadImportReview() {
  if (!activeImportId.value) return;
  const scrollTop = importReviewDrawer.value?.getBodyScrollTop() || 0;
  importLoading.value = true;
  try {
    [importSummary.value, importGraph.value, importCandidates.value] = await Promise.all([
      getKnowledgeImportSummary(activeImportId.value),
      getKnowledgeImportGraph(activeImportId.value),
      listImportCandidates(activeImportId.value),
    ]);
    if (graphView.value === "pending" && pendingChangeDocument.value?.document_id === activeImportId.value) {
      pendingGraph.value = importGraph.value;
    }
  } catch (error: any) {
    showToast(error?.response?.data?.detail || "导入候选加载失败");
  } finally {
    importLoading.value = false;
    await nextTick();
    if (scrollTop > 0) importReviewDrawer.value?.setBodyScrollTop(scrollTop);
  }
}
async function showPendingGraph() {
  const document = pendingChangeDocument.value;
  if (!document) return;
  graphView.value = "pending";
  selectedKnowledgeId.value = null;
  if (pendingGraph.value?.import_id === document.document_id) return;
  pendingGraphLoading.value = true;
  try {
    pendingGraph.value = await getKnowledgeImportGraph(document.document_id);
  } catch (error: any) {
    graphView.value = "active";
    showToast(error?.response?.data?.detail || "待启用图谱加载失败", "error");
  } finally {
    pendingGraphLoading.value = false;
  }
}
function showActiveGraph() {
  graphView.value = "active";
  selectedKnowledgeId.value = null;
}
async function openPendingChangeGraph() {
  openAssetView("graph");
  await nextTick();
  await showPendingGraph();
}
async function revalidateImportGraph() {
  if (!activeImportId.value) return;
  return withImportAction(
    () => revalidateKnowledgeImportGraph(activeImportId.value),
    "图谱质量已重新校验",
  );
}
function openImportReview(document: KnowledgeDocumentItem) {
  activeImportId.value = document.document_id;
  importReviewOpen.value = true;
  loadImportReview();
}
async function withImportAction(action: () => Promise<unknown>, success: string) {
  importActionLoading.value = true;
  try {
    const result = await action();
    showToast(typeof result === "string" ? result : success);
    await loadImportReview();
    await loadDomain();
  }
  catch (error: any) { showToast(error?.response?.data?.detail || "导入操作失败"); }
  finally { importActionLoading.value = false; }
}
function confirmImport() {
  const summary = importSummary.value;
  const indexVersion = summary?.candidate_manifest?.index_version;
  if (!summary || !indexVersion) return;
  return withImportAction(
    async () => {
      const result = await confirmKnowledgeImport(
        activeImportId.value,
        summary.input_version,
        indexVersion,
      );
      questionImportChangeSetId.value = String(result.change_set_id || "");
      if (result.status === "ready_for_questions") {
        return "知识变更已暂存，请补齐题库后一次启用";
      }
      return "知识与索引已发布，请在题库管理下载缺口模板";
    },
    "导入状态已更新",
  );
}
const abilityWeightFields: Array<{ key: keyof AbilityWeights; label: string }> = [
  { key: "theory", label: "理论" },
  { key: "practice", label: "实操" },
  { key: "problem_solving", label: "问题解决" },
  { key: "knowledge_breadth", label: "知识广度" },
  { key: "learning_speed", label: "学习速度" },
];
function ensureCandidateWeights(candidate: ImportCandidate): AbilityWeights {
  if (!candidate.payload.ability_weights) {
    candidate.payload.ability_weights = {
      theory: 0,
      practice: 0,
      problem_solving: 0,
      knowledge_breadth: 0,
      learning_speed: 0,
    };
  }
  return candidate.payload.ability_weights;
}
function weightSourceLabel(source?: string): string {
  return { explicit: "领域包", model: "模型补全", admin: "管理员", missing: "缺失" }[source || "missing"] || source || "缺失";
}
async function saveCandidateWeights(candidate: ImportCandidate) {
  const weights = ensureCandidateWeights(candidate);
  const firstFour = weights.theory + weights.practice + weights.problem_solving + weights.knowledge_breadth;
  if (Object.values(weights).some((value) => !Number.isFinite(Number(value)) || Number(value) < 0 || Number(value) > 1)) {
    showToast("五维权重必须是 0 到 1 之间的数字");
    return;
  }
  if (Math.abs(firstFour - 1) > 0.000001) {
    showToast(`前四维权重之和必须为 1，当前为 ${firstFour.toFixed(4)}`);
    return;
  }
  weights.learning_speed = 0;
  savingCandidateId.value = candidate.candidate_id;
  try {
    await updateImportCandidate(activeImportId.value, candidate.candidate_id, candidate.payload);
    await validateKnowledgeImport(activeImportId.value);
    showToast("能力权重已保存并重新校验");
    await loadImportReview();
  } catch (error: any) {
    showToast(error?.response?.data?.detail || "能力权重保存失败");
  } finally {
    savingCandidateId.value = "";
  }
}
function quizLevelLabel(level: QuestionBankItem["quiz_level"]) {
  return { foundation: "基础", improvement: "提升", challenge: "挑战" }[level] || level;
}

function questionPoolLabel(question: QuestionBankItem) {
  if (question.question_bank_uses.includes('diagnosis')) return '首次诊断题'
  if (question.question_bank_uses.includes('graded_quiz')) return '分阶测验题'
  return '掌握检查题'
}
function questionStatusLabel(status: QuestionBankItem["status"]) {
  return { active: "启用", staged: "待启用", stale: "待替换", disabled: "已停用" }[status];
}
async function disableBankQuestion(question: QuestionBankItem) {
  const reason = window.prompt("请输入停用原因（停用后该知识点需要补齐对应槽位）", "题目质量不符合要求");
  if (!reason?.trim()) return;
  questionActionLoading.value = question.question_id;
  try {
    await disableQuestion(question.question_id, reason.trim());
    showToast("题目已停用，该知识点已进入缺槽状态");
    await loadDomain();
  } catch (error: any) {
    showToast(error?.response?.data?.detail || "停用题目失败");
  } finally {
    questionActionLoading.value = "";
  }
}
async function downloadQuestionBankTemplate() {
  questionImportActionLoading.value = true;
  try {
    const response = await downloadQuestionTemplate(
      selectedCode.value,
      [],
      questionImportChangeSetId.value || undefined,
    );
    const url = URL.createObjectURL(response.data);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${selectedCode.value}-question-bank-template.xlsx`;
    link.click();
    URL.revokeObjectURL(url);
    showToast("已生成当前题库缺口模板");
  } catch (error: any) {
    showToast(error?.response?.data?.detail || "题库模板下载失败", "error");
  } finally {
    questionImportActionLoading.value = false;
  }
}
function openQuestionImport() {
  questionImportOpen.value = true;
}
function startNewQuestionImport() {
  activeQuestionImport.value = null;
  questionImportRows.value = [];
  questionImportPreview.status = "all";
  questionImportPreview.purpose = "all";
  questionImportPreview.keyword = "";
}
async function loadQuestionImport(run: QuestionImportRun, silent = false) {
  if (!silent) questionImportLoading.value = true;
  activeQuestionImport.value = run;
  try {
    questionImportRows.value = await listQuestionImportRows(run.run_id);
    questionImportOpen.value = true;
  } finally {
    if (!silent) questionImportLoading.value = false;
  }
}
async function handleQuestionImportFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  questionImportActionLoading.value = true;
  try {
    const run = await uploadQuestionImport(
      file,
      selectedCode.value,
      questionImportChangeSetId.value || undefined,
    );
    await loadQuestionImport(run);
    showToast("题库已完成字段校验");
  } catch (error: any) {
    showToast(questionImportErrorMessage(error, "题库导入失败"), "error");
  } finally {
    questionImportActionLoading.value = false;
    if (questionImportFile.value) questionImportFile.value.value = "";
  }
}
async function reloadQuestionImport() {
  if (!activeQuestionImport.value) return;
  questionImportActionLoading.value = true;
  try {
    const run = await validateQuestionImport(activeQuestionImport.value.run_id);
    await loadQuestionImport(run);
    showToast("题库已重新校验");
  } catch (error: any) {
    showToast(questionImportErrorMessage(error, "重新校验失败"), "error");
  } finally {
    questionImportActionLoading.value = false;
  }
}
async function publishImportedQuestions() {
  if (!activeQuestionImport.value) return;
  questionImportActionLoading.value = true;
  try {
    const result = await publishQuestionImport(activeQuestionImport.value.run_id);
    questionImportChangeSetId.value = result.change_set_id || questionImportChangeSetId.value;
    if (result.change_set_id) {
      activeQuestionImport.value = result;
      showToast("题库已暂存，确认后可一次启用变更", "success");
    } else {
      showToast("题库已原子发布，正在刷新领域就绪状态", "success");
      questionImportOpen.value = false;
      await loadDomain();
    }
  } catch (error: any) {
    showToast(questionImportErrorMessage(error, "题库发布失败"), "error");
  } finally {
    questionImportActionLoading.value = false;
  }
}
async function activatePendingChangeSet() {
  const changeSetId = activeQuestionImport.value?.change_set_id || questionImportChangeSetId.value;
  if (!changeSetId) return;
  questionImportActionLoading.value = true;
  try {
    await activateDomainChangeSet(changeSetId);
    questionImportOpen.value = false;
    questionImportChangeSetId.value = "";
    showToast("知识、图谱、索引和题库已一次启用", "success");
    await loadDomain();
  } catch (error: any) {
    showToast(error?.response?.data?.detail || "变更集启用失败", "error");
  } finally {
    questionImportActionLoading.value = false;
  }
}
async function activateCurrentChangeSet() {
  const changeSetId = activeChangeSet.value?.change_set_id;
  if (!changeSetId) return;
  questionImportActionLoading.value = true;
  try {
    await activateDomainChangeSet(changeSetId);
    questionImportChangeSetId.value = "";
    showToast("知识、图谱、索引和题库已一次启用", "success");
    await loadDomain();
  } catch (error: any) {
    showToast(error?.response?.data?.detail || "变更集启用失败", "error");
  } finally {
    questionImportActionLoading.value = false;
  }
}
async function cancelDocumentImport(document: KnowledgeDocumentItem) {
  try {
    await cancelKnowledgeImport(document.document_id);
    showToast("已请求中断导入，当前模型调用结束后停止");
    await loadDocuments(true);
    if (activeImportId.value === document.document_id) await loadImportReview();
  } catch (error: any) {
    showToast(error?.response?.data?.detail || "导入中断失败");
  }
}
function handleFileInput(event: Event) {
  uploadFiles(Array.from((event.target as HTMLInputElement).files || []));
}
function handleDrop(event: DragEvent) {
  dragging.value = false;
  uploadFiles(Array.from(event.dataTransfer?.files || []));
}
async function retry(document: KnowledgeDocumentItem) {
  try {
    await retryKnowledgeDocument(document.document_id);
    showToast("已重新提交处理");
    await loadDocuments();
  } catch {
    showToast("重新处理失败");
  }
}
function requestRemove(document: KnowledgeDocumentItem) {
  deleteTarget.value = document;
  deleteDialog.value?.open();
}
function closeDeleteDialog() {
  deleteDialog.value?.close();
  deleteTarget.value = null;
}
async function confirmRemove() {
  if (!deleteTarget.value) return;
  deleting.value = true;
  try {
    const result = await deleteKnowledgeDocument(deleteTarget.value.document_id);
    showToast(
      result.change_set_cancelled
        ? "待启用变更已取消，正式知识图谱未受影响"
        : "来源文档已撤回，正在重建索引",
      "success",
    );
    closeDeleteDialog();
    await loadDomain();
  } catch (error: any) {
    showToast(error?.response?.data?.detail || "删除失败");
  } finally {
    deleting.value = false;
  }
}
function stopRebuildPolling() {
  if (rebuildPollTimer !== undefined) {
    window.clearTimeout(rebuildPollTimer);
    rebuildPollTimer = undefined;
  }
}
function finishRebuildPolling() {
  rebuilding.value = false;
  if (rebuildStatus.value?.status === "success") {
    showToast("索引重建完成");
    loadDomain();
  } else if (
    ["failed", "interrupted"].includes(rebuildStatus.value?.status || "")
  )
    showToast(rebuildStatus.value?.message || "索引重建失败");
}
async function pollRebuild() {
  const domain = selectedCode.value;
  try {
    const status = await getRebuildIndexStatus(selectedCode.value);
    if (domain !== selectedCode.value) return;
    rebuildStatus.value = status;
    if (status.running) {
      rebuildPollTimer = window.setTimeout(pollRebuild, 2000);
      return;
    }
  } catch {
    rebuildStatus.value = {
      job_id: null,
      status: "failed",
      running: false,
      domain_code: domain,
      started_at: null,
      finished_at: null,
      message: "无法读取重建状态",
      result: null,
    };
  }
  finishRebuildPolling();
}
async function rebuild() {
  stopRebuildPolling();
  rebuilding.value = true;
  try {
    const started = await rebuildKnowledgeIndex(selectedCode.value);
    rebuildStatus.value = {
      job_id: started.job_id,
      status: "running",
      running: true,
      domain_code: started.domain_code,
      started_at: null,
      finished_at: null,
      message: "",
      result: null,
    };
    rebuildPollTimer = window.setTimeout(pollRebuild, 1500);
  } catch (error: any) {
    rebuilding.value = false;
    rebuildStatus.value = {
      job_id: null,
      status: "failed",
      running: false,
      domain_code: selectedCode.value,
      started_at: null,
      finished_at: null,
      message: error?.response?.data?.detail || "索引重建失败",
      result: null,
    };
    showToast(rebuildStatus.value.message);
  }
}
async function syncRebuildStatus() {
  try {
    const status = await getRebuildIndexStatus(selectedCode.value);
    if (status.domain_code && status.domain_code !== selectedCode.value) return;
    rebuildStatus.value = status;
    if (status.running) {
      rebuilding.value = true;
      rebuildPollTimer = window.setTimeout(pollRebuild, 2000);
    }
  } catch {
    /* 后台未就绪时保留领域页其他能力 */
  }
}
async function validate() {
  validating.value = true;
  try {
    validationResult.value = await getDomainReadiness(selectedCode.value);
  } catch (error: any) {
    const detail = error?.response?.data?.detail;
    showToast(
      typeof detail === "string"
        ? detail
        : detail?.message || detail?.code || "领域校验请求失败，请检查后端服务状态",
      "error",
    );
  } finally {
    validating.value = false;
  }
}
function isProcessing(status: KnowledgeDocumentStatus) {
  return [
    "queued",
    "parsing",
    "extracting",
    "graph_generation",
    "graph_review",
    "validating",
    "staging",
    "indexing",
    "smoke_testing",
    "publishing",
    "cancel_requested",
  ].includes(status);
}
function isCancellationRequested(document: KnowledgeDocumentItem) {
  return document.error_summary?.includes("已请求中断") ?? false;
}
function documentStatusLabel(status: KnowledgeDocumentStatus) {
  return (
    (
      {
        queued: "等待处理",
        parsing: "正在解析",
        extracting: "正在抽取知识与关系",
        graph_generation: "正在生成知识图谱",
        graph_review: "正在复核事实关系",
        validating: "正在校验",
        staging: "正在暂存候选结果",
        index_pending: "等待构建索引",
        indexing: "正在索引",
        smoke_testing: "正在验证检索",
        smoke_passed: "检索验证通过",
        ready_to_publish: "等待确认发布",
        ready_for_questions: "等待补齐题库",
        publishing: "正在发布",
        cancel_requested: "正在中断",
        cancelled: "已中断",
        ready: "已就绪",
        needs_attention: "质量检查未通过",
        failed: "处理失败",
        interrupted: "已中断",
        withdrawn: "已撤回",
      } as Record<string, string>
    )[status] || "未知状态"
  );
}
function importStatusLabel(status: string) {
  return documentStatusLabel(status as KnowledgeDocumentStatus);
}
function importStepLabel(step: string) {
  return (
    {
      parsing: "解析来源文档",
      extracting: "抽取知识与关系",
      graph_generation: "构建候选图谱",
      graph_review: "复核图谱关系",
      validating: "校验知识目录",
      staging: "暂存候选结果",
      indexing: "构建候选索引",
      smoke_testing: "验证检索结果",
      ready_to_publish: "等待确认知识发布",
      ready_for_questions: "等待补齐正式题库",
      publishing: "正在发布知识变更",
      ready: "知识变更已启用",
    } as Record<string, string>
  )[step] || step;
}
function changeSetStatusLabel(status: DomainChangeSet["status"]) {
  return {
    preparing: "正在准备知识",
    ready_for_questions: "待补齐题库",
    questions_preparing: "题库补齐中",
    ready_to_activate: "可一次启用",
    activated: "已启用",
    cancelled: "已取消",
  }[status];
}
function questionImportStatusLabel(status: QuestionImportRun["status"]) {
  return {
    uploaded: "已接收",
    needs_attention: "待处理",
    ready_to_publish: "可发布",
    published: "已发布",
    cancelled: "已取消",
  }[status];
}
function questionImportErrorMessage(error: any, fallback: string) {
  const code = String(error?.response?.data?.error?.code || error?.response?.data?.detail || "");
  const messages: Record<string, string> = {
    QUESTION_IMPORT_XLSX_REQUIRED: "仅支持 XLSX 题库模板",
    QUESTION_TEMPLATE_DOMAIN_OR_VERSION_INVALID: "模板不属于当前领域或模板版本已过期，请重新下载",
    QUESTION_TEMPLATE_CHANGE_SET_INVALID: "模板所属的待启用知识变更不一致，请刷新页面后重新下载模板",
    QUESTION_TEMPLATE_INVENTORY_CHANGED: "题库缺口已变化，请重新下载模板后再填写",
    QUESTION_TEMPLATE_KNOWLEDGE_SCOPE_INVALID: "模板中的知识点范围已变化，请重新下载模板",
    QUESTION_IMPORT_FILE_EMPTY: "上传文件为空",
    QUESTION_IMPORT_FILE_TOO_LARGE: "题库文件不能超过 20MB",
    QUESTION_IMPORT_NOT_READY_TO_PUBLISH: "题库存在字段错误或尚未完成校验，暂不能发布",
    QUESTION_IMPORT_ALREADY_PUBLISHED: "该题库已发布，无需重复校验",
  };
  return messages[code] || code || fallback;
}
function questionImportKnowledgeName(row: QuestionImportRow) {
  return knowledgeItems.value.find((item) => item.knowledge_id === row.knowledge_ref)?.name || row.knowledge_ref;
}
function questionPurposeLabel(purpose: string | null) {
  return { diagnosis: "诊断题", graded_quiz: "分阶测验", mastery_validation: "掌握检查" }[purpose || ""] || "未指定用途";
}
function questionLevelLabel(level: string | null) {
  return { foundation: "基础", improvement: "提升", challenge: "挑战" }[level || ""] || "未指定层级";
}
function questionTypeLabel(type: string) {
  return type === "single_choice" ? "单选题" : type === "short_answer" ? "简答题" : "未识别题型";
}
function optionLabel(index: number) {
  return String.fromCharCode("A".charCodeAt(0) + index);
}
function questionAnswerLabel(row: QuestionImportRow) {
  return typeof row.answer === "number" ? optionLabel(row.answer) : "";
}
function questionAnswerDisplay(row: QuestionImportRow) {
  if (row.question_type === "single_choice") {
    const index = typeof row.answer === "number" ? row.answer : -1;
    return index >= 0 ? `${optionLabel(index)}. ${row.options[index] || ""}` : "未填写";
  }
  return String(row.answer || "未填写");
}
function questionRowStatusLabel(row: QuestionImportRow) {
  if (["valid", "published"].includes(row.status)) return "已通过";
  return questionRowIssue(row)?.title || "待处理";
}
function questionRowIssue(row: QuestionImportRow) {
  if (row.status === "template_invalid") {
    return { title: "字段校验未通过", description: "模板中的必填字段或预填元数据不符合导入规则，请修正对应字段后重新上传。", fields: row.validation_errors };
  }
  return null;
}
function fileTypeLabel(type: string) {
  return (
    (
      {
        pdf: "PDF",
        markdown: "Markdown",
        text: "TXT",
        seed_package: "知识包",
      } as Record<string, string>
    )[type] || type
  );
}
function formatBytes(value: number) {
  if (!value) return "-";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
function resourceTypeLabel(value: string) {
  return (
    (
      {
        lecture: "定制化讲义",
        practice_guide: "实操指南",
        graded_quiz: "分阶测试",
      } as Record<string, string>
    )[value] || value
  );
}
function targetLabel(value: string) {
  return (
    (
      {
        knowledge_items: "知识点",
        minimum_published_knowledge: "已发布知识点",
        diagnostic_questions: "诊断题",
        minimum_diagnostic_questions: "可用诊断题",
        evaluation_cases: "评测样例",
      } as Record<string, string>
    )[value] || value
  );
}
const formatDate = formatBeijingDateTime;
onMounted(() => {
  loadAll();
  syncRebuildStatus();
});
onBeforeUnmount(() => {
  stopPolling();
  stopRebuildPolling();
  if (highlightTimer) window.clearTimeout(highlightTimer);
});
</script>

<style scoped>
.domain-page {
  gap: 16px;
}
.domain-select {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  font-size: 12px;
}
.domain-select select {
  min-width: 190px;
}
.readonly-badge {
  align-self: center;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--panel);
  color: var(--muted);
  padding: 6px 10px;
  font-size: 11px;
  font-weight: 700;
}
.domain-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--soft);
  padding: 13px 16px;
}
.domain-identity {
  display: flex;
  align-items: center;
  gap: 11px;
}
.domain-mark {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  background: var(--blue2);
  color: var(--blue);
  font-weight: 800;
}
.domain-identity small {
  display: block;
  margin-top: 4px;
  color: var(--muted);
  font-size: 11px;
}
.domain-state {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--body);
  font-size: 12px;
}
.domain-state i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--green);
}
.domain-tabs {
  display: flex;
  gap: 4px;
  overflow-x: auto;
  border-bottom: 1px solid var(--line);
  padding-inline: 4px;
}
.domain-tabs button {
  flex: none;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--muted);
  padding: 12px 15px;
  font: inherit;
  font-size: 12px;
  font-weight: 680;
}
.domain-tabs button.active {
  border-bottom-color: var(--blue);
  color: var(--blue);
}
.pane-stack {
  display: grid;
  gap: 16px;
}
.domain-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
}
.domain-metrics > div {
  padding: 15px 18px;
  border-right: 1px solid var(--line);
}
.domain-metrics > div:last-child {
  border-right: 0;
}
.domain-metrics span,
.domain-metrics small {
  display: block;
  color: var(--muted);
  font-size: 11px;
}
.domain-metrics strong {
  display: block;
  margin: 8px 0 5px;
  font-size: 25px;
}
.current-task {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--soft);
  padding: 16px 18px;
}
.current-task.ready { background: var(--green2); }
.current-task.warning { background: var(--amber2); }
.current-task.error { background: var(--red2); }
.current-task.info { background: var(--blue2); }
.task-kicker { color: var(--muted); font-size: 11px; font-weight: 700; }
.current-task-content { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-top: 5px; }
.current-task h2 { font-size: 17px; }
.current-task p { max-width: 700px; margin: 5px 0 0; color: var(--body); font-size: 12px; line-height: 1.55; }
.overview-statuses { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 14px; color: var(--muted); font-size: 11px; }
.overview-statuses span { display: inline-flex; align-items: center; gap: 6px; }
.overview-statuses i { width: 7px; height: 7px; border-radius: 50%; background: var(--amber); }
.overview-statuses i.ready { background: var(--green); }
.overview-statuses i.error { background: var(--red); }
.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.section-head p {
  margin: 6px 0 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
}
.summary-status {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 11px;
  font-weight: 700;
}
.summary-status i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}
.summary-status.ready {
  background: var(--green2);
  color: var(--green);
}
.summary-status.warning {
  background: var(--amber2);
  color: var(--amber);
}
.summary-status.error {
  background: var(--red2);
  color: var(--red);
}
.readiness-list {
  display: grid;
  grid-template-columns: 1fr;
  margin-top: 15px;
  border-top: 1px solid var(--line);
}
.readiness-row {
  display: grid;
  grid-template-columns: 30px 1fr auto;
  gap: 10px;
  align-items: center;
  padding: 15px 12px;
  border-bottom: 1px solid var(--line);
}
.readiness-icon {
  width: 27px;
  height: 27px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--green2);
  color: var(--green);
  font-size: 11px;
  font-weight: 800;
}
.readiness-icon.warning,
.readiness-icon.running {
  background: var(--amber2);
  color: var(--amber);
}
.readiness-icon.error {
  background: var(--red2);
  color: var(--red);
}
.readiness-row strong,
.readiness-row small {
  display: block;
}
.readiness-row small {
  margin-top: 4px;
  color: var(--muted);
  font-size: 11px;
}
.readiness-value {
  color: var(--body);
  font-size: 12px;
  font-weight: 700;
}
.readiness-empty { margin: 16px 0 0; color: var(--muted); font-size: 12px; }
.readiness-toggle,
.config-details-toggle { margin-top: 10px; padding-inline: 0; }
.readiness-passed-list { margin-top: 8px; }
.evidence-toggle { width: 100%; display: flex; justify-content: space-between; margin-top: 12px; border: 0; border-top: 1px solid var(--line); background: transparent; padding: 12px 0 0; color: var(--muted); font: inherit; font-size: 11px; font-weight: 650; text-align: left; }
.evidence-coverage {
  display: grid;
  gap: 12px;
  margin-top: 14px;
  border-radius: 10px;
  background: var(--green2);
  padding: 14px;
}
.evidence-coverage.is-conceptual {
  background: var(--amber2);
}
.evidence-coverage-summary {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}
.evidence-coverage-summary p {
  max-width: 760px;
  margin-top: 4px;
  color: var(--body);
  font-size: 11px;
  line-height: 1.6;
}
.evidence-capability-list {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}
.evidence-capability-list span {
  border-radius: 999px;
  background: var(--panel);
  color: var(--muted);
  padding: 5px 8px;
  font-size: 11px;
}
.evidence-capability-list strong {
  margin-left: 3px;
  color: var(--ink);
}
.attention-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  border: 1px solid color-mix(in srgb, var(--amber) 45%, var(--line));
  border-radius: 10px;
  background: var(--amber2);
  padding: 14px 16px;
  color: var(--amber);
}
.attention-strip p {
  margin: 5px 0 0;
  font-size: 11px;
}
.quick-links {
  padding-bottom: 8px;
}
.asset-links {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  margin-top: 12px;
  border-top: 1px solid var(--line);
}
.asset-links button {
  border: 0;
  border-right: 1px solid var(--line);
  background: transparent;
  padding: 16px;
  text-align: left;
  color: var(--ink);
}
.asset-links button:last-child {
  border-right: 0;
}
.asset-links button:hover {
  background: var(--soft);
}
.asset-links strong,
.asset-links span {
  display: block;
}
.asset-links span {
  margin-top: 6px;
  color: var(--muted);
  font-size: 11px;
}
.inline-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-radius: 8px;
  background: var(--red2);
  color: var(--red);
  padding: 10px 12px;
  font-size: 12px;
}
.assets-panel {
  padding: 0;
}
.asset-heading {
  padding: 18px;
}
.segmented {
  display: flex;
  gap: 5px;
  overflow-x: auto;
  border-block: 1px solid var(--line);
  background: var(--soft);
  padding: 7px 18px;
}
.segmented button {
  flex: none;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--muted);
  padding: 8px 11px;
  font: inherit;
  font-size: 12px;
  font-weight: 680;
}
.segmented button span {
  margin-left: 5px;
  color: var(--muted);
}
.segmented button.active {
  background: var(--panel);
  color: var(--blue);
  box-shadow: var(--shadow-card);
}
.asset-body {
  padding: 16px 18px 0;
}
.asset-summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; overflow: hidden; border: 1px solid var(--line); border-radius: 9px; background: var(--line); }
.asset-summary-grid article { display: grid; gap: 5px; background: var(--panel); padding: 12px 14px; }
.asset-summary-grid article.has-gap { background: var(--amber2); }
.asset-summary-grid span,
.asset-summary-grid small { color: var(--muted); font-size: 10px; }
.asset-summary-grid strong { font-size: 18px; }
.asset-summary-note { margin: 10px 0 12px; color: var(--muted); font-size: 11px; }
.knowledge-filters {
  padding-bottom: 14px;
}
.asset-filters { align-items: center; padding: 2px 0 10px; }
.asset-filters .search-field { min-width: 220px; }
.asset-results { margin: -2px 0 10px; color: var(--muted); font-size: 11px; }
.knowledge-results {
  margin: -4px 0 10px;
  color: var(--muted);
  font-size: 11px;
}
.knowledge-table-wrap {
  max-height: 480px;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.asset-table-wrap {
  max-height: clamp(360px, 56vh, 540px);
  overflow: auto;
  overscroll-behavior: contain;
}
.knowledge-table-wrap thead th {
  position: sticky;
  z-index: 1;
  top: 0;
  background: var(--soft);
  box-shadow: 0 1px 0 var(--line);
}
.asset-table-wrap thead th {
  position: sticky;
  z-index: 1;
  top: 0;
  background: var(--soft);
  box-shadow: 0 1px 0 var(--line);
}
.knowledge-table tbody tr {
  transition: background-color 180ms ease-out;
}
.knowledge-table tbody tr.is-located {
  background: var(--blue2);
}
.knowledge-table .source-col {
  width: 18%;
  max-width: 220px;
}
.source-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  white-space: nowrap;
}
.search-field {
  min-width: 240px;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  padding: 0 10px;
  color: var(--muted);
}
.search-field:focus-within {
  border-color: var(--blue);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--blue) 22%, transparent);
}
.search-field input {
  width: 100%;
  border: 0;
  outline: 0;
  font: inherit;
  font-size: 12px;
  color: var(--ink);
}
.knowledge-table td,
.document-table td {
  vertical-align: middle;
}
.knowledge-table td > strong,
.knowledge-table td > small,
.document-table td > strong,
.document-table td > small {
  display: block;
}
.knowledge-table td > small,
.document-table td > small {
  max-width: 320px;
  margin-top: 4px;
  color: var(--muted);
  font-size: 10px;
}
.difficulty-dots {
  display: inline-flex;
  gap: 3px;
  margin-right: 6px;
}
.difficulty-dots i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--track);
}
.difficulty-dots i.on {
  background: var(--blue);
}
.table-actions {
  width: 140px;
  text-align: right;
  white-space: nowrap;
}
.experimental-note {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  border-radius: 8px;
  background: var(--blue2);
  padding: 10px 12px;
  color: var(--info);
}
.experimental-note span {
  border-radius: 999px;
  background: var(--blue2);
  padding: 4px 7px;
  font-size: 10px;
  font-weight: 800;
}
.experimental-note p {
  margin: 0;
  font-size: 11px;
}
.system-label {
  color: var(--muted);
  font-size: 11px;
}
.graph-body {
  padding-bottom: 18px;
}
.graph-summary { display: flex; flex-wrap: wrap; gap: 8px 14px; margin-bottom: 12px; color: var(--muted); font-size: 11px; }
.graph-summary strong { color: var(--body); }
.graph-summary-with-view { align-items: center; justify-content: space-between; gap: 12px; }
.graph-summary-with-view > div:first-child { display: flex; flex-wrap: wrap; gap: 8px 14px; }
.graph-view-toggle { display: inline-flex; gap: 6px; padding: 3px; border: 1px solid var(--line); border-radius: 7px; background: var(--soft); }
.graph-view-toggle .btn { border-color: transparent; }
.graph-view-toggle .btn.active { border-color: var(--blue); background: var(--blue2); color: var(--blue); }
.pending-graph-notice { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; margin: 0 0 12px; border: 1px solid var(--blue); border-radius: 7px; background: var(--blue2); padding: 10px 12px; color: var(--body); font-size: 12px; }
.pending-graph-notice strong { color: var(--blue); }
.empty-view {
  min-height: 210px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 7px;
  text-align: center;
  padding: 28px;
}
.empty-view p {
  max-width: 520px;
  margin: 0 0 5px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
}
.rule-sections {
  margin-top: 14px;
  border-top: 1px solid var(--line);
}
.config-details { margin-top: 10px; border-top: 1px solid var(--line); }
.config-details .rule-block { padding-bottom: 12px; }
.config-source-note { margin: 0; color: var(--muted); font-size: 11px; line-height: 1.6; }
.rule-block {
  display: grid;
  grid-template-columns: minmax(180px, 0.45fr) 1fr;
  gap: 18px;
  padding: 18px 4px;
  border-bottom: 1px solid var(--line);
}
.rule-block p {
  margin: 5px 0 0;
  color: var(--muted);
  font-size: 11px;
}
.rule-source {
  display: inline-flex;
  margin-left: 6px;
  border-radius: 999px;
  background: var(--soft);
  padding: 2px 7px;
  color: var(--muted);
  font-size: 10px;
  font-weight: 600;
}
.rule-values {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}
.rule-values span {
  border-radius: 999px;
  background: var(--blue2);
  color: var(--info);
  padding: 6px 9px;
  font-size: 11px;
  font-weight: 650;
}
.rule-values-action .btn {
  margin-left: auto;
}
.rule-values small,
.target-list > small {
  color: var(--muted);
}
.target-list {
  display: grid;
  gap: 8px;
}
.target-list > div {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  border-bottom: 1px solid var(--line);
  padding-bottom: 8px;
  color: var(--body);
  font-size: 12px;
}
.operations-workbench { display: grid; gap: 16px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); padding: 18px; }
.operation-steps { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin: 0; padding: 0; overflow: hidden; border: 1px solid var(--line); border-radius: 9px; background: var(--line); list-style: none; }
.operation-steps li { display: grid; grid-template-columns: 26px 1fr; align-items: center; gap: 9px; min-height: 72px; background: var(--panel); padding: 11px; }
.operation-steps li.active { background: var(--blue2); }
.operation-steps li.complete { background: var(--green2); }
.operation-steps > li > span:first-child { width: 24px; height: 24px; display: grid; place-items: center; border-radius: 50%; background: var(--soft); color: var(--muted); font-size: 11px; font-weight: 750; }
.operation-steps strong,
.operation-steps small { display: block; }
.operation-steps strong { font-size: 12px; }
.operation-steps small { margin-top: 4px; color: var(--muted); font-size: 10px; line-height: 1.4; }
.operation-steps .status { grid-column: 2; justify-self: start; }
.operation-steps.compact li { min-height: 52px; grid-template-columns: 24px 1fr; padding: 9px 11px; }
.operation-steps.compact small { display: none; }
.operation-steps.compact .status { display: none; }
.operation-normal { display: flex; align-items: center; justify-content: space-between; gap: 16px; border-top: 1px solid var(--line); padding-top: 14px; }
.operation-normal > div { display: grid; gap: 4px; }
.operation-normal strong { color: var(--green); font-size: 14px; }
.operation-normal span { color: var(--muted); font-size: 11px; }
.operation-focus { border: 1px solid var(--line); border-radius: 9px; background: var(--soft); padding: 15px; }
.operation-focus.warning { background: var(--amber2); }
.operation-focus.error { background: var(--red2); }
.operation-focus.ready { background: var(--green2); }
.operation-focus.info { background: var(--blue2); }
.operation-focus h3 { font-size: 14px; }
.operation-focus .section-head p { max-width: 650px; }
.operation-change-set { display: flex; align-items: center; justify-content: space-between; gap: 16px; border: 1px solid var(--blue); border-radius: 8px; background: var(--blue2); padding: 14px; }
.operation-change-set strong { display: block; color: var(--blue); font-size: 13px; }
.operation-change-set p { max-width: 720px; margin: 5px 0 0; color: var(--body); font-size: 11px; line-height: 1.55; }
.validation-details { border-top: 1px solid var(--line); padding-top: 2px; }
.operation-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1px;
  margin-top: 16px;
  border: 1px solid var(--line);
  border-radius: 9px;
  overflow: hidden;
  background: var(--line);
}
.operation-stats > div {
  background: var(--panel);
  padding: 12px;
}
.operation-stats span,
.operation-stats strong {
  display: block;
}
.operation-stats span {
  color: var(--muted);
  font-size: 10px;
}
.operation-stats strong {
  margin-top: 6px;
  font-size: 14px;
  overflow-wrap: anywhere;
}
.operation-message {
  margin-top: 14px;
  border-radius: 8px;
  background: var(--soft);
  padding: 12px;
}
.operation-message.success {
  background: var(--green2);
  color: var(--green);
}
.operation-message.failed,
.operation-message.interrupted {
  background: var(--red2);
  color: var(--red);
}
.operation-message p {
  margin: 5px 0 0;
  font-size: 11px;
  line-height: 1.55;
}
.operation-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: auto;
  padding-top: 18px;
}
.manual-operation-note { margin: 9px 0 0; color: var(--muted); font-size: 11px; text-align: right; }
.validation-empty {
  display: grid;
  place-items: center;
  flex: 1;
  color: var(--muted);
  font-size: 12px;
  text-align: center;
}
.validation-list {
  display: grid;
  margin-top: 15px;
}
.validation-list > div:not(.validation-issue) {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 12px;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
  font-size: 12px;
}
.validation-issue {
  display: grid;
  grid-template-columns: 25px 1fr;
  gap: 8px;
  margin-top: 10px;
  border-radius: 8px;
  background: var(--amber2);
  padding: 10px;
  color: var(--amber);
}
.validation-issue > span {
  width: 23px;
  height: 23px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--amber2);
  font-weight: 800;
}
.validation-issue p {
  margin: 2px 0 0;
  font-size: 11px;
}
.validation-issue small {
  display: block;
  margin-top: 3px;
}
.question-detail { display: grid; gap: 16px; }
.question-detail-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.question-detail-meta > span { border-radius: 999px; background: var(--soft); padding: 5px 8px; color: var(--muted); font-size: 11px; }
.question-detail-block { border-top: 1px solid var(--line); padding-top: 14px; }
.question-detail-block h3 { font-size: 13px; }
.question-detail-block p { margin: 8px 0 0; color: var(--body); font-size: 12px; line-height: 1.7; white-space: pre-wrap; }
.question-detail-block small { display: block; margin-top: 8px; color: var(--muted); font-size: 11px; overflow-wrap: anywhere; }
.question-options { display: grid; gap: 7px; margin: 10px 0 0; padding: 0; list-style: none; color: var(--body); font-size: 12px; line-height: 1.55; }
.question-detail-warning { border-radius: 8px; border-top: 0; background: var(--amber2); padding: 12px; }
.page-skeleton {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.page-skeleton i {
  height: 90px;
  border-radius: 11px;
  background: linear-gradient(90deg, var(--track) 25%, var(--soft) 50%, var(--track) 75%);
  background-size: 200% 100%;
  animation: skeleton 1.2s linear infinite;
}
@keyframes skeleton {
  to {
    background-position: -200% 0;
  }
}
.drawer-form {
  display: grid;
  gap: 14px;
}
.drawer-form label {
  display: grid;
  gap: 6px;
  color: var(--body);
  font-size: 12px;
  font-weight: 650;
}
.drawer-form textarea {
  width: 100%;
  resize: vertical;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 9px 10px;
  color: var(--ink);
  font: inherit;
  font-size: 12px;
  line-height: 1.6;
}
.form-pair {
  display: grid;
  grid-template-columns: 1fr 120px;
  gap: 10px;
}
.form-error {
  margin: 0;
  border-radius: 8px;
  background: var(--red2);
  color: var(--red);
  padding: 10px;
  font-size: 12px;
}
.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.upload-warning {
  border-radius: 9px;
  background: var(--blue2);
  padding: 12px;
  color: var(--info);
}
.upload-warning p {
  margin: 6px 0 0;
  font-size: 11px;
  line-height: 1.6;
}
.upload-compact {
  display: grid;
  place-items: center;
  min-height: 190px;
  margin-top: 14px;
  border: 1px dashed var(--line);
  border-radius: 10px;
  background: var(--soft);
  padding: 20px;
  text-align: center;
  transition: 180ms ease;
}
.upload-compact.dragging {
  border-color: var(--blue);
  background: var(--blue2);
}
.upload-compact > span {
  font-size: 24px;
  color: var(--blue);
}
.upload-compact p {
  margin: 6px 0 12px;
  color: var(--muted);
  font-size: 11px;
}
.upload-fields {
  margin-top: 16px;
}

.candidate-list {
  display: grid;
  gap: 12px;
}

.import-review-content { gap: 16px; }
.import-stage-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px 18px;
  align-items: start;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--soft);
  padding: 16px;
}
.import-stage-card > div { display: grid; gap: 4px; }
.import-stage-card p { grid-column: 1 / -1; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.55; }
.import-stage-card > div > strong { color: var(--ink); font-size: 17px; line-height: 1.35; }
.import-stage-label { color: var(--muted); font-size: 11px; font-weight: 700; }
.import-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--line);
  gap: 1px;
}
.import-metrics article { display: grid; gap: 5px; min-height: 68px; background: var(--panel); padding: 11px 12px; }
.import-metrics span { color: var(--muted); font-size: 11px; }
.import-metrics strong { color: var(--ink); font-size: 15px; line-height: 1.25; overflow-wrap: anywhere; }
.question-upload-dropzone { min-height: 260px; }
.question-import-stage { margin-bottom: 12px; }
.question-import-metrics { grid-template-columns: repeat(5, minmax(0, 1fr)); margin-bottom: 14px; }
.question-import-metrics article.has-gap { background: var(--amber2); }
.question-row-warning { margin: 0; padding: 8px 10px; border-left: 3px solid var(--amber); background: var(--amber2); color: var(--ink); font-size: 12px; }
.question-preview-toolbar { display: grid; grid-template-columns: minmax(0, 1fr) 138px minmax(190px, .8fr); align-items: center; gap: 10px; margin: 12px 0 8px; }
.question-preview-toolbar .segmented { padding: 4px; border: 1px solid var(--line); border-radius: 8px; background: var(--soft); }
.question-preview-toolbar .segmented button { padding: 7px 9px; }
.question-preview-toolbar .field { min-height: 36px; }
.question-preview-toolbar .search-field { min-width: 0; }
.question-preview-count { margin: 0 0 10px; color: var(--muted); font-size: 11px; }
.question-import-preview { display: grid; gap: 10px; }
.question-import-card { display: grid; gap: 10px; border: 1px solid var(--line); border-radius: 7px; background: var(--panel); padding: 14px; }
.question-import-card.has-issue { border-color: color-mix(in srgb, var(--amber) 55%, var(--line)); }
.question-import-card > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.question-import-card > header > div { display: grid; gap: 3px; min-width: 0; }
.question-import-kicker, .question-import-meta { margin: 0; color: var(--muted); font-size: 11px; }
.question-import-card h3 { margin: 0; color: var(--ink); font-size: 14px; line-height: 1.6; }
.question-option-preview { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin: 0; padding: 0; list-style: none; }
.question-option-preview li { display: grid; grid-template-columns: 20px minmax(0, 1fr); gap: 7px; align-items: start; border: 1px solid var(--line); border-radius: 6px; padding: 8px; color: var(--body); font-size: 12px; line-height: 1.45; }
.question-option-preview li.correct { border-color: var(--green); background: var(--green2); }
.question-option-preview b { display: grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; background: var(--soft); color: var(--muted); font-size: 10px; }
.question-option-preview li.correct b { background: var(--green); color: white; }
.question-answer-preview { border-left: 3px solid var(--blue); background: var(--blue2); padding: 9px 11px; }
.question-answer-preview span, .question-answer-preview small { color: var(--muted); font-size: 11px; }
.question-answer-preview p { margin: 4px 0; font-size: 12px; line-height: 1.5; }
.question-explanation { border-top: 1px solid var(--line); padding-top: 9px; }
.question-explanation summary { cursor: pointer; color: var(--blue); font-size: 12px; font-weight: 700; }
.question-explanation p { margin: 8px 0 0; color: var(--body); font-size: 12px; line-height: 1.55; }
.question-row-issue { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; border: 1px solid color-mix(in srgb, var(--amber) 55%, var(--line)); border-radius: 6px; background: var(--amber2); padding: 10px 11px; }
.question-row-issue strong { color: var(--amber); font-size: 12px; }
.question-row-issue p { margin: 4px 0 0; color: var(--body); font-size: 12px; line-height: 1.55; }
.question-row-issue small { color: var(--muted); font-size: 11px; text-align: right; }
.source-confirmation { display: grid; grid-template-columns: 180px minmax(0, 1fr) auto; gap: 8px; align-items: start; border-top: 1px solid var(--line); padding-top: 10px; }
.source-confirmation select, .source-confirmation textarea { width: 100%; min-width: 0; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); color: var(--ink); padding: 8px; font: inherit; font-size: 12px; }
.source-confirmation textarea { min-height: 70px; resize: vertical; }

.quality-blockers {
  border-color: var(--red);
  background: var(--red2);
}

.direction-quality-list {
  display: grid;
  gap: 8px;
}

.direction-quality-list > div {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  border-top: 1px solid var(--line);
  padding-top: 8px;
}

.direction-quality-list span {
  color: var(--muted);
  font-size: 11px;
  text-align: right;
}

.candidate-item {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--line-color, var(--line));
  border-radius: 6px;
}

.candidate-item header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.candidate-item label {
  display: grid;
  gap: 6px;
  font-size: 13px;
}

.candidate-source {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}
.ability-candidate-list {
  display: grid;
  gap: 10px;
}
.ability-candidate {
  display: grid;
  gap: 9px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface-soft, transparent);
}
.ability-candidate > header,
.ability-candidate-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.ability-candidate > header div {
  display: grid;
  gap: 2px;
}
.ability-candidate > header span,
.ability-candidate-footer span {
  color: var(--muted);
  font-size: 11px;
}
.ability-weight-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(90px, 1fr));
  gap: 8px;
}
.ability-weight-grid input {
  width: 100%;
  box-sizing: border-box;
  padding: 7px 8px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--surface);
  color: var(--body);
}
.delete-message {
  display: grid;
  grid-template-columns: 32px 1fr;
  gap: 10px;
  align-items: start;
  padding: 12px 0;
}
.delete-message span {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--red2);
  color: var(--red);
  font-weight: 800;
}
.delete-message p {
  margin: 4px 0;
  color: var(--body);
  font-size: 12px;
  line-height: 1.6;
}
@media (max-width: 1000px) {
  .import-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .question-preview-toolbar { grid-template-columns: 1fr 138px; }
  .question-preview-toolbar .search-field { grid-column: 1 / -1; }
  .ability-weight-grid {
    grid-template-columns: repeat(2, minmax(100px, 1fr));
  }
  .domain-metrics {
    grid-template-columns: 1fr 1fr;
  }
  .domain-metrics > div:nth-child(2) {
    border-right: 0;
  }
  .domain-metrics > div:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line);
  }
  .source-col {
    display: none;
  }
}
@media (max-width: 760px) {
  .graph-summary-with-view { align-items: stretch; }
  .graph-view-toggle { width: 100%; }
  .graph-view-toggle .btn { flex: 1; }
  .import-stage-card { grid-template-columns: 1fr; }
  .import-stage-card .status { justify-self: start; }
  .question-import-metrics, .question-preview-toolbar, .question-option-preview, .question-row-issue, .source-confirmation { grid-template-columns: 1fr; }
  .question-preview-toolbar .search-field { grid-column: auto; }
  .question-row-issue small { text-align: left; }
  .rp-head-actions {
    width: 100%;
  }
  .domain-select {
    flex: 1;
  }
  .domain-select select {
    min-width: 0;
    width: 100%;
  }
  .domain-banner {
    align-items: flex-start;
  }
  .current-task-content {
    align-items: flex-start;
    flex-direction: column;
  }
  .current-task-content .btn { width: 100%; }
  .readiness-list {
    grid-template-columns: 1fr;
  }
  .readiness-row:nth-child(odd) {
    border-right: 0;
  }
  .attention-strip {
    align-items: flex-start;
    flex-direction: column;
  }
  .asset-links {
    grid-template-columns: 1fr;
  }
  .asset-links button {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .asset-heading {
    align-items: flex-start;
    flex-direction: column;
  }
  .asset-summary-grid { grid-template-columns: 1fr; }
  .knowledge-filters {
    align-items: stretch;
  }
  .knowledge-filters > * {
    flex: 1;
  }
  .asset-filters {
    align-items: stretch;
  }
  .asset-filters > * {
    flex: 1;
  }
  .knowledge-table-wrap {
    max-height: none;
    overflow-y: visible;
    overscroll-behavior: auto;
  }
  .knowledge-table-wrap thead th {
    position: static;
    box-shadow: none;
  }
  .asset-table-wrap {
    max-height: min(500px, 62vh);
    overflow: auto;
  }
  .search-field {
    min-width: 100%;
  }
  .date-col {
    display: none;
  }
  .rule-block {
    grid-template-columns: 1fr;
  }
  .operation-stats {
    grid-template-columns: 1fr;
  }
  .operations-workbench { padding: 14px; }
  .operation-steps { grid-template-columns: 1fr; }
  .operation-steps.compact li { grid-template-columns: 24px 1fr; }
  .operation-normal { align-items: flex-start; flex-direction: column; }
  .operation-focus .section-head { align-items: flex-start; flex-direction: column; }
  .operation-change-set { align-items: flex-start; flex-direction: column; }
  .operation-focus .section-head .btn { width: 100%; }
  .table-actions {
    width: auto;
  }
}
@media (max-width: 480px) {
  .domain-metrics {
    grid-template-columns: 1fr 1fr;
  }
  .domain-metrics > div {
    padding: 13px;
  }
  .domain-metrics strong {
    font-size: 22px;
  }
  .domain-state {
    display: none;
  }
  .knowledge-table th:nth-child(2),
  .knowledge-table td:nth-child(2),
  .document-table th:nth-child(2),
  .document-table td:nth-child(2),
  .document-table th:nth-child(3),
  .document-table td:nth-child(3) {
    display: none;
  }
  .form-pair {
    grid-template-columns: 1fr;
  }
  .section-head {
    align-items: flex-start;
    flex-direction: column;
  }
  .summary-status {
    align-self: flex-start;
  }
}
@media (prefers-reduced-motion: reduce) {
  .knowledge-table tbody tr {
    transition: none;
  }
  .page-skeleton i {
    animation: none;
  }
  .upload-compact {
    transition: none;
  }
}
</style>
