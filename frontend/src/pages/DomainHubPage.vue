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
        <div class="domain-metrics">
          <div v-for="metric in overviewMetrics" :key="metric.label">
            <span>{{ metric.label }}</span
            ><strong>{{ metric.value }}</strong
            ><small>{{ metric.note }}</small>
          </div>
        </div>
        <div v-if="errorMessage" class="inline-error">
          <span>{{ errorMessage }}</span
          ><button class="btn text" @click="loadDomain">重试</button>
        </div>
        <section class="panel readiness-panel">
          <div class="section-head">
            <div>
              <h2>领域就绪度</h2>
              <p>
                以下条件共同决定该领域能否稳定完成诊断、检索和个性化资源生成。
              </p>
            </div>
            <span class="summary-status" :class="overallReadinessClass"
              ><i />{{ overallReadinessLabel }}</span
            >
          </div>
          <ReadinessList class="readiness-list">
            <div
              v-for="item in readinessItems"
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
          <div
            v-if="validationResult?.evidence_coverage"
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
        <section v-if="attentionItems.length" class="attention-strip">
          <div>
            <strong>有 {{ attentionItems.length }} 项需要处理</strong>
            <p>{{ attentionSummary }}</p>
          </div>
          <div class="actions">
            <button
              v-if="stats?.pending_embeddings"
              class="btn"
              @click="openPendingKnowledge"
            >
              查看待索引知识点</button
            ><button class="btn primary" @click="selectPane('operations')">
              进入运行检查
            </button>
          </div>
        </section>
        <section class="panel quick-links">
          <div class="section-head">
            <div>
              <h2>领域资产</h2>
              <p>查看领域当前使用的知识来源与结构。</p>
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
            <p>
              知识点提供依据，正式题库统一服务诊断与分级测验，关系图谱表达知识结构。
            </p>
          </div>
          <button
            v-if="assetView === 'items'"
            class="btn primary"
            @click="openKnowledgeEditor()"
          >
            新增知识点</button
          ><button
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
          <div class="experimental-note">
            <span>正式题库</span>
            <p>每个知识点保留 3 道分阶测验题和 2 道独立掌握验证题；全部绑定精确来源并通过认证，运行时不临时生成。</p>
          </div>
          <p class="knowledge-results" aria-live="polite">
            已覆盖 {{ questionCoverage?.ready_items || 0 }} / {{ questionCoverage?.total_items || 0 }} 个知识点，
              当前显示 {{ questionBank.length }} 道题，其中已认证 {{ certifiedQuestionCount }} 道；
              缺少测验题的知识点 {{ questionCoverage?.missing_quiz_knowledge_ids.length || 0 }} 个，
              缺少验证预留题的知识点 {{ questionCoverage?.missing_mastery_reserve_knowledge_ids.length || 0 }} 个
          </p>
          <div v-if="questionBank.length === 0" class="empty-view">
            <strong>当前领域暂无正式题目</strong>
            <p>请通过来源文档导入并完成题目审核发布。</p>
          </div>
          <div v-else class="table-wrap">
            <table class="knowledge-table">
              <thead><tr><th>主要知识点</th><th>用途</th><th>层级</th><th>题型</th><th>题干</th><th>精确来源</th><th>认证</th><th>运营状态</th><th class="table-actions">操作</th></tr></thead>
              <tbody>
                <tr v-for="question in questionBank" :key="question.question_id">
                  <td><strong>{{ question.knowledge_name }}</strong><small v-if="question.related_knowledge_ids.length">关联 {{ question.related_knowledge_ids.length }} 个知识点</small></td>
                  <td>{{ questionPoolLabel(question) }}</td>
                  <td>{{ quizLevelLabel(question.quiz_level) }} / 难度 {{ question.difficulty }}</td>
                  <td>{{ question.question_type === 'single_choice' ? '单选题' : '简答题' }}</td>
                  <td><span class="source-text" :title="question.stem">{{ question.stem }}</span></td>
                  <td><span class="source-text" :title="question.source_quote || question.source_ref_ids.join('、')">{{ question.source_ref_ids.join('、') }}</span></td>
                  <td><StatusBadge :label="certificationStatusLabel(question.certification_status)" :type="question.certification_status === 'certified' ? 'ok' : question.certification_status === 'rejected' ? 'error' : 'wait'" /><small v-if="question.certification_summary.failed_fields.length" class="document-error">{{ question.certification_summary.failed_fields.join('、') }}</small></td>
                  <td><StatusBadge :label="question.status === 'active' ? '启用' : '已停用'" :type="question.status === 'active' ? 'ok' : 'wait'" /></td>
                  <td class="table-actions"><button v-if="question.status === 'active'" class="btn text danger" :disabled="questionActionLoading === question.question_id" @click="disableBankQuestion(question)">停用</button><span v-else class="system-label">等待补槽</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-else-if="assetView === 'documents'" class="asset-body">
          <div class="experimental-note">
            <span>结构化导入</span>
            <p>
              文档会生成知识点、关系和诊断题候选，经复核、校验和索引冒烟后发布。
            </p>
          </div>
          <div v-if="documents.length === 0" class="empty-view">
            <strong>当前领域暂无来源文档</strong>
            <p>上传 PDF、Markdown 或 TXT，进入可追溯的知识导入流程。</p>
            <button class="btn primary" @click="uploadOpen = true">
              上传实验文档
            </button>
          </div>
          <div v-else class="table-wrap">
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
                <tr v-for="document in documents" :key="document.document_id">
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
          <div
            v-if="!graphLoading && !knowledgeItems.length"
            class="empty-view"
          >
            <strong>暂无可展示的知识关系</strong>
            <p>新增知识点和关系后，这里将展示领域知识结构。</p>
          </div>
          <KnowledgeGraph
            v-else
            :items="knowledgeItems"
            :relations="relations"
            :loading="graphLoading"
            :selected-knowledge-id="selectedKnowledgeId"
            @select="selectedKnowledgeId = $event"
            @edit="returnToKnowledgeItem"
          />
        </div>
      </section>

      <section v-else-if="activePane === 'rules'" class="pane-stack">
        <section class="panel">
          <div class="section-head">
            <div>
              <h2>当前生效规则</h2>
              <p>合并展示系统默认、文档自动生成和领域自定义规则。</p>
            </div>
            <span class="readonly-badge">自动生效</span>
          </div>
          <div class="rule-sections">
            <div class="rule-block">
              <div>
                <h3>能力维度 <small class="rule-source">{{ parsedConfig.sources.abilityDimensions }}</small></h3>
                <p>用于诊断画像和学习报告。</p>
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
                <h3>资源类型 <small class="rule-source">{{ parsedConfig.sources.resourceTypes }}</small></h3>
                <p>当前领域允许生成的资源形态。</p>
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
                <h3>发布数量门槛 <small class="rule-source">{{ parsedConfig.sources.mvpTargets }}</small></h3>
                <p>领域校验使用的最低数据规模。</p>
              </div>
              <div class="target-list">
                <div v-for="entry in parsedConfig.mvpTargets" :key="entry[0]">
                  <span>{{ targetLabel(entry[0]) }}</span
                  ><strong>{{ entry[1] }}</strong>
                </div>
                <small v-if="!parsedConfig.mvpTargets.length">未配置</small>
              </div>
            </div>
            <div class="rule-block">
              <div>
                <h3>学习方向 <small class="rule-source">{{ parsedConfig.sources.learningDirections }}</small></h3>
                <p>上传文档后由系统自动生成，可在领域编辑中调整名称和标签映射。</p>
              </div>
              <div class="rule-values rule-values-action">
                <span v-for="direction in parsedConfig.learningDirections" :key="direction.value">{{ direction.label }}</span>
                <small v-if="!parsedConfig.learningDirections.length">尚未生成，发布首份导入文档后自动出现</small>
                <button v-if="parsedConfig.learningDirections.length" class="btn small" type="button" @click="openDomainEditor(selectedDomain || undefined)">编辑学习方向</button>
              </div>
            </div>
          </div>
        </section>
      </section>

      <section v-else class="operations-grid">
        <section class="panel operation-panel">
          <div class="section-head">
            <div>
              <h2>Candidate RAG 索引</h2>
              <p>以当前活动索引校验为准；待重新嵌入数量为 0 不代表活动索引已同步。</p>
            </div>
            <StatusBadge :label="indexStatusLabel" :type="indexStatusType" />
          </div>
          <div class="operation-stats">
            <div>
              <span>待重新嵌入知识点</span
              ><strong>{{ stats?.pending_embeddings || 0 }}</strong>
            </div>
            <div>
              <span>最近模型</span
              ><strong>{{
                rebuildStatus?.result?.embedding_model || "-"
              }}</strong>
            </div>
            <div>
              <span>最近结果</span><strong>{{ rebuildResultLabel }}</strong>
            </div>
          </div>
          <div
            v-if="showRebuildMessage"
            class="operation-message"
            :class="rebuildStatus?.status || currentIndexState"
          >
            <strong>{{ rebuildMessageTitle }}</strong>
            <p>{{ rebuildMessageBody }}</p>
          </div>
          <div class="operation-actions">
            <button class="btn primary" :disabled="rebuilding" @click="rebuild">
              {{ rebuilding ? "正在重建..." : "重建索引" }}
            </button>
          </div>
        </section>
        <section class="panel operation-panel">
          <div class="section-head">
            <div>
              <h2>领域校验</h2>
              <p>核对知识点、诊断题和向量索引是否达到当前交付门槛。</p>
            </div>
            <StatusBadge
              v-if="validationResult"
              :label="validationResult.passed ? '校验通过' : '存在问题'"
              :type="validationResult.passed ? 'ok' : 'wait'"
            />
          </div>
          <div v-if="!validationResult" class="validation-empty">
            <p>执行校验后，将逐项显示实际值、目标值和问题原因。</p>
          </div>
          <div v-else class="validation-list">
            <div v-for="row in validationRows" :key="row.key">
              <span>{{ row.label }}</span
              ><strong>{{ row.actual }} / {{ row.target }}</strong
              ><StatusBadge
                :label="row.passed ? '达标' : '未达标'"
                :type="row.passed ? 'ok' : 'wait'"
              />
            </div>
            <div
              v-for="issue in validationResult.issues"
              :key="issue.message"
              class="validation-issue"
            >
              <span>!</span>
              <p>
                {{ issue.message
                }}<small v-if="issue.actual !== undefined"
                  >实际 {{ issue.actual }}，目标 {{ issue.target }}</small
                >
              </p>
            </div>
          </div>
          <div class="operation-actions">
            <button class="btn" :disabled="validating" @click="validate">
              {{
                validating
                  ? "正在校验..."
                  : validationResult
                    ? "重新校验"
                    : "执行领域校验"
              }}
            </button>
          </div>
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
      v-model="uploadOpen"
      title="导入领域文档"
      :subtitle="`${selectedDomain?.name || selectedCode} · 生成候选后由管理员复核`"
      ><div class="upload-warning">
        <strong>结构化知识导入</strong>
        <p>
          系统保留页码、标题或段落位置，并生成知识、关系和诊断题候选。
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
      v-model="importReviewOpen"
      title="自动导入进度与发布"
      :subtitle="importSummary ? `${importSummary.import_id} · ${importSummary.status}` : ''"
    >
      <div v-if="importLoading" class="empty-view"><strong>正在加载导入状态</strong></div>
      <div v-else-if="!importSummary" class="empty-view"><strong>暂无导入运行</strong></div>
      <div v-else class="candidate-list">
        <article class="candidate-item">
          <header><strong>当前阶段：{{ importSummary.current_step }}</strong><StatusBadge :label="importSummary.status" :type="importSummary.error_summary ? 'danger' : 'wait'" /></header>
          <p>第 {{ importSummary.attempt }} 次执行 · 基线 {{ importSummary.quality_baseline_version || 'knowledge-import-gold-v1' }}</p>
          <p v-if="importSummary.total_batches">
            模型批次 {{ importSummary.completed_batches || 0 }} / {{ importSummary.total_batches }}
            · 失败 {{ importSummary.failed_batches || 0 }}
            · 已耗时 {{ Math.round(Number(importSummary.elapsed_ms || 0) / 1000) }} 秒
            <span v-if="importSummary.eta_seconds">· 预计剩余 {{ importSummary.eta_seconds }} 秒</span>
          </p>
          <p v-if="importSummary.empty_result_batches" class="document-error">
            题目生成空结果 {{ importSummary.empty_result_batches }} 批；请补充对应知识点材料后重新导入。
          </p>
          <p v-if="importSummary.error_summary" class="document-error">{{ importSummary.error_summary }}</p>
        </article>
        <div class="metric-grid compact">
          <article><span>知识点</span><strong>{{ importSummary.knowledge_items || 0 }}</strong></article>
          <article><span>诊断题</span><strong>{{ importSummary.diagnostic_questions || 0 }}</strong></article>
          <article><span>方向性关系</span><strong>{{ importSummary.directional_relations || 0 }}</strong></article>
          <article><span>路径参与节点</span><strong>{{ importSummary.path_participating_nodes || 0 }} / {{ importSummary.knowledge_items || 0 }}</strong></article>
        </div>
        <div class="metric-grid compact">
          <article><span>事实关系</span><strong>{{ importSummary.factual_relations || 0 }}</strong></article>
          <article><span>教学推荐</span><strong>{{ importSummary.recommended_relations || 0 }}</strong></article>
          <article><span>权重就绪</span><strong>{{ importSummary.ability_weights_ready || 0 }} / {{ importSummary.knowledge_items || 0 }}</strong></article>
          <article><span>权重缺失</span><strong>{{ importSummary.ability_weights_missing || 0 }}</strong></article>
        </div>
        <div class="metric-grid compact">
          <article><span>全节点参与率</span><strong>{{ Math.round(Number(importSummary.path_participation_ratio || 0) * 100) }}%</strong></article>
          <article><span>孤立节点</span><strong>{{ importSummary.isolated_nodes || 0 }}（{{ Math.round(Number(importSummary.isolated_node_ratio || 0) * 100) }}%）</strong></article>
          <article><span>题目覆盖</span><strong>{{ Math.round(Number(importSummary.question_knowledge_coverage || 0) * 100) }}%</strong></article>
          <article><span>自动修复</span><strong>{{ importSummary.repair_rounds || 0 }} 轮</strong></article>
        </div>
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
        <button class="btn primary" :disabled="importActionLoading || importSummary?.status !== 'ready_to_publish'" @click="confirmImport">确认并发布</button>
      </template>
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
  updateImportCandidate,
  validateKnowledgeImport,
  type AbilityWeights,
  type GraphPreview,
  type ImportCandidate,
  type KnowledgeImportSummary,
} from "@/api/knowledgeImports";
import { useDomainStore } from "@/stores/domainStore";
import { useToast } from "@/composables/useToast";
import { formatBeijingDateTime } from "@/utils/dateTime";
import {
  configList,
  domainReadiness,
  filterKnowledgeItems,
  indexUiState,
  type KnowledgeFilters,
} from "./domainHubState";

type PaneId = "overview" | "assets" | "rules" | "operations";
type AssetView = "items" | "questions" | "documents" | "graph";
const route = useRoute(),
  router = useRouter(),
  domainStore = useDomainStore(),
  { showToast } = useToast();
const panes: Array<{ id: PaneId; label: string }> = [
  { id: "overview", label: "领域概览" },
  { id: "assets", label: "知识资产" },
  { id: "rules", label: "领域规则" },
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
const knowledgeImportCandidates = computed(() =>
  importCandidates.value.filter((candidate) => candidate.candidate_type === "knowledge_item"),
);
const previewItems = computed<KnowledgeItem[]>(() => (importGraph.value?.nodes || []).map((node) => ({
  knowledge_id: node.id, domain_code: selectedCode.value, name: node.name,
  category: node.category, difficulty: node.difficulty, tags: node.tags,
  content: "", source_title: node.source_chunk_ids.join(", "), source_url: null,
  license_note: "", needs_reembedding: true,
})));
const previewRelations = computed<KnowledgeRelation[]>(() => {
  const names = new Map((importGraph.value?.nodes || []).map((node) => [node.id, node.name]));
  return (importGraph.value?.edges || []).filter((edge) => edge.accepted).map((edge) => ({
    source_id: edge.source, source_name: names.get(edge.source) || edge.source,
    target_id: edge.target, target_name: names.get(edge.target) || edge.target,
    relation_type: edge.relation_type === "depends_on" ? "dependent" : edge.relation_type === "related_to" ? "related" : edge.relation_type,
  }));
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
const overviewMetrics = computed(() => [
  {
    label: "知识点",
    value: stats.value?.knowledge_items || 0,
    note: "MVP 目标 ≥ 50",
  },
  {
    label: "诊断题",
    value: stats.value?.diagnostic_questions || 0,
    note: "MVP 目标 ≥ 60",
  },
  {
    label: "知识关系",
    value: stats.value?.knowledge_relations || 0,
    note: "前置、后继与关联",
  },
  {
    label: "已发布资源",
    value: stats.value?.published_resources || 0,
    note: "通过审核的当前版本",
  },
]);
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
const attentionSummary = computed(() =>
  attentionItems.value.map((item) => item.label).join("、"),
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
  { id: "questions" as const, label: "题库", count: questionBank.value.length },
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
const indexStatusLabel = computed(() => ({
  running: "重建中",
  ready: "已同步",
  needs_rebuild: "需重建",
  failed: "异常",
})[currentIndexState.value]);
const indexStatusType = computed(() =>
  currentIndexState.value === "ready" ? "ok" : ("wait" as const),
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
        : `当前 Candidate RAG 校验未通过（${validationResult.value?.rag?.reason || "索引版本或数据版本不一致"}），请重建索引。`
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
    chroma_vectors: "Candidate RAG 向量",
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
function openPendingKnowledge() {
  knowledgeFilters.indexStatus = "pending";
  openAssetView("items");
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
  validationResult.value = null;
  rebuildStatus.value = null;
  stats.value = null;
  documents.value = [];
  knowledgeItems.value = [];
  relations.value = [];
  clearKnowledgeFilters();
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
    const [s, d, r, i, q, validation] = await Promise.all([
      getDomainStats(selectedCode.value),
      listKnowledgeDocuments(selectedCode.value),
      listKnowledgeRelations(selectedCode.value),
      listKnowledgeItems(selectedCode.value, 500),
      listQuestionBank(selectedCode.value),
      getDomainReadiness(selectedCode.value),
    ]);
    if (version !== loadVersion) return;
    stats.value = s;
    documents.value = d.documents;
    relations.value = r;
    knowledgeItems.value = i.items;
    questionBank.value = q.items;
    questionCoverage.value = q.coverage;
    validationResult.value = validation;
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
  for (const file of files) {
    try {
      await uploadKnowledgeDocument(
        file,
        selectedCode.value,
        sourceTitle.value,
        licenseNote.value,
      );
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
}
async function loadImportReview() {
  if (!activeImportId.value) return;
  importLoading.value = true;
  try {
    [importSummary.value, importGraph.value, importCandidates.value] = await Promise.all([
      getKnowledgeImportSummary(activeImportId.value),
      getKnowledgeImportGraph(activeImportId.value),
      listImportCandidates(activeImportId.value),
    ]);
  } catch (error: any) {
    showToast(error?.response?.data?.detail || "导入候选加载失败");
  } finally {
    importLoading.value = false;
  }
}
function openImportReview(document: KnowledgeDocumentItem) {
  activeImportId.value = document.document_id;
  importReviewOpen.value = true;
  loadImportReview();
}
async function withImportAction(action: () => Promise<unknown>, success: string) {
  importActionLoading.value = true;
  try { await action(); showToast(success); await loadImportReview(); await loadDomain(); }
  catch (error: any) { showToast(error?.response?.data?.detail || "导入操作失败"); }
  finally { importActionLoading.value = false; }
}
function confirmImport() {
  const summary = importSummary.value;
  const indexVersion = summary?.candidate_manifest?.index_version;
  if (!summary || !indexVersion) return;
  return withImportAction(
    () => confirmKnowledgeImport(activeImportId.value, summary.input_version, indexVersion),
    "知识导入已发布",
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
  if (!question.question_bank_uses.includes('mastery_validation')) return '诊断 / 动态分阶测验'
  return question.reserve_role === 'consolidation'
    ? '错题巩固预留'
    : question.reserve_role === 'mastery_transfer'
      ? '掌握验证预留'
      : '验证 / 巩固预留'
}
const certifiedQuestionCount = computed(
  () => questionBank.value.filter((item) => item.certification_status === "certified").length,
);
function certificationStatusLabel(status: QuestionBankItem["certification_status"]) {
  return { pending: "待认证", certified: "已认证", rejected: "已拒绝", stale: "已失效" }[status];
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
    await deleteKnowledgeDocument(deleteTarget.value.document_id);
    showToast("来源文档已删除");
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
    "question_generation",
    "question_certification",
    "question_review",
    "question_repair",
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
        question_generation: "正在生成诊断题",
        question_certification: "正在认证正式题目",
        question_review: "正在复核诊断题",
        question_repair: "正在补充诊断题",
        validating: "正在校验",
        staging: "正在暂存候选结果",
        indexing: "正在索引",
        smoke_testing: "正在验证检索",
        ready_to_publish: "等待确认发布",
        publishing: "正在发布",
        cancel_requested: "正在中断",
        cancelled: "已中断",
        ready: "已就绪",
        needs_attention: "质量检查未通过",
        failed: "处理失败",
        withdrawn: "已撤回",
      } as Record<string, string>
    )[status] || "未知状态"
  );
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
  border-radius: 12px;
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
  grid-template-columns: 1fr 1fr;
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
.readiness-row:nth-child(odd) {
  border-right: 1px solid var(--line);
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
  box-shadow: 0 1px 3px rgb(22 35 55/0.09);
}
.asset-body {
  padding: 16px 18px 0;
}
.knowledge-filters {
  padding-bottom: 14px;
}
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
.knowledge-table-wrap thead th {
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
.operations-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.operation-panel {
  display: flex;
  min-height: 360px;
  flex-direction: column;
}
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
  margin-top: auto;
  padding-top: 18px;
}
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
  .operations-grid {
    grid-template-columns: 1fr;
  }
  .source-col {
    display: none;
  }
}
@media (max-width: 760px) {
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
  .knowledge-filters {
    align-items: stretch;
  }
  .knowledge-filters > * {
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
