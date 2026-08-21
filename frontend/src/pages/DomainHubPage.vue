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
        <span class="schema-badge"
          >Schema {{ selectedDomain?.domain_schema_version || "1.0" }}</span
        >
        <button class="btn" :disabled="loading" @click="loadDomain">
          {{ loading ? "正在刷新" : "刷新数据" }}
        </button>
        <button class="btn" @click="openDomainEditor()">新建领域</button>
        <button v-if="selectedDomain" class="btn" @click="openDomainEditor(selectedDomain)">编辑领域</button>
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
              知识点用于诊断与检索，来源文档提供依据，关系图谱表达知识结构。
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
          <div v-else class="table-wrap">
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
                >
                  <td>
                    <strong>{{ item.name }}</strong
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
                  <td class="source-col">{{ item.source_title }}</td>
                  <td>
                    <StatusBadge
                      :label="item.needs_reembedding ? '待重新索引' : '已同步'"
                      :type="item.needs_reembedding ? 'wait' : 'ok'"
                    />
                  </td>
                  <td class="table-actions">
                    <button class="btn text" @click="openKnowledgeEditor(item)">
                      查看与编辑
                    </button>
                  </td>
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
                      v-if="!document.is_system && document.status !== 'parsing'"
                      class="btn text"
                      @click="openImportReview(document)"
                    >复核候选</button><button
                      v-else-if="document.status === 'failed'"
                      class="btn text"
                      @click="retry(document)"
                    >
                      重新处理</button
                    ><button
                      v-if="!document.is_system"
                      class="btn text danger"
                      :disabled="isProcessing(document.status)"
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
          />
        </div>
      </section>

      <section v-else-if="activePane === 'rules'" class="pane-stack">
        <section class="panel">
          <div class="section-head">
            <div>
              <h2>领域规则</h2>
              <p>以下内容来自当前领域真实配置，供诊断、资源生成与验收读取。</p>
            </div>
            <span class="readonly-badge">当前只读</span>
          </div>
          <div v-if="!hasDomainConfig" class="empty-view">
            <strong>当前领域未保存结构化规则</strong>
            <p>页面不会使用硬编码内容替代缺失配置。</p>
          </div>
          <div v-else class="rule-sections">
            <div class="rule-block">
              <div>
                <h3>能力维度</h3>
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
                <h3>资源类型</h3>
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
                <h3>MVP 数量目标</h3>
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
          </div>
        </section>
      </section>

      <section v-else class="operations-grid">
        <section class="panel operation-panel">
          <div class="section-head">
            <div>
              <h2>Candidate RAG 索引</h2>
              <p>知识更新后必须重建索引，生成任务才会使用最新知识。</p>
            </div>
            <StatusBadge :label="indexStatusLabel" :type="indexStatusType" />
          </div>
          <div class="operation-stats">
            <div>
              <span>待重新索引</span
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
            v-if="rebuildStatus && rebuildStatus.status !== 'idle'"
            class="operation-message"
            :class="rebuildStatus.status"
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
      subtitle="配置基本信息和学习方向；就绪门槛由系统统一管理"
    >
      <form id="domain-form" class="drawer-form" @submit.prevent="saveDomain">
        <label>领域代码<input v-model.trim="domainForm.domain_code" class="field" required maxlength="64" pattern="[a-z][a-z0-9_]*" :disabled="Boolean(editingDomain)" /></label>
        <label>领域名称<input v-model.trim="domainForm.name" class="field" required maxlength="128" /></label>
        <label>领域说明<textarea v-model.trim="domainForm.description" rows="3" maxlength="500" /></label>
        <div class="section-head"><div><strong>学习方向</strong><p>至少 1 项，最多 6 项。</p></div><button class="btn" type="button" :disabled="domainForm.learning_directions.length >= 6" @click="addDirection">添加方向</button></div>
        <div v-for="(direction, index) in domainForm.learning_directions" :key="index" class="rule-block">
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
      title="复核导入候选"
      :subtitle="importSummary ? `${importSummary.import_id} · ${importSummary.status}` : ''"
    >
      <div v-if="importLoading" class="empty-view"><strong>正在加载候选</strong></div>
      <div v-else-if="!importCandidates.length" class="empty-view">
        <strong>暂无候选</strong><p>文档可能仍在解析，稍后重新打开。</p>
      </div>
      <div v-else class="candidate-list">
        <article v-for="candidate in importCandidates" :key="candidate.candidate_id" class="candidate-item">
          <header><strong>{{ candidateTypeLabel(candidate.candidate_type) }}</strong><StatusBadge :label="candidate.status" :type="candidate.validation_errors.length ? 'danger' : 'wait'" /></header>
          <label v-if="candidate.candidate_type === 'knowledge_item'">名称<input v-model="candidate.payload.name" class="field" /></label>
          <label v-if="candidate.candidate_type === 'knowledge_item'">难度<input v-model.number="candidate.payload.difficulty" class="field" type="number" min="1" max="5" /></label>
          <label v-if="candidate.candidate_type === 'diagnostic_question'">题干<textarea v-model="candidate.payload.stem" class="field" rows="2" /></label>
          <p class="candidate-source">来源：{{ sourceLabel(candidate.source_locator) }}</p>
          <p v-if="candidate.validation_errors.length" class="document-error">{{ candidate.validation_errors.join('；') }}</p>
          <button class="btn text" :disabled="importActionLoading" @click="saveCandidate(candidate)">保存修改</button>
        </article>
      </div>
      <template #footer>
        <button class="btn" :disabled="importActionLoading" @click="runImportValidation">校验</button>
        <button class="btn" :disabled="importActionLoading" @click="approveImport">批准并写入</button>
        <button class="btn" :disabled="importActionLoading" @click="buildImportIndex">构建索引</button>
        <button class="btn" :disabled="importActionLoading" @click="smokeImport">冒烟</button>
        <button class="btn primary" :disabled="importActionLoading" @click="publishImport">发布</button>
      </template>
    </AppDrawer>

    <AppDialog
      ref="deleteDialog"
      title="删除来源文档"
      :subtitle="deleteTarget?.original_name || ''"
      ><div class="delete-message">
        <span>!</span>
        <p>删除后，相关向量和内部知识将同步移除。该操作无法从页面恢复。</p>
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
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import AppDialog from "@/components/Shared/AppDialog.vue";
import AppDrawer from "@/components/Shared/AppDrawer.vue";
import StatusBadge from "@/components/Shared/StatusBadge.vue";
import PageHeader from "@/components/Shared/PageHeader.vue";
import ReadinessList from "@/components/Shared/ReadinessList.vue";
import KnowledgeGraph from "@/components/KnowledgeGraph/KnowledgeGraph.vue";
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
  getRebuildIndexStatus,
  listKnowledgeItems,
  listKnowledgeRelations,
  rebuildKnowledgeIndex,
  updateKnowledgeItem,
  type KnowledgeItem,
  type KnowledgeRelation,
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
  approveKnowledgeImport,
  buildKnowledgeImportIndex,
  getKnowledgeImport,
  listImportCandidates,
  publishKnowledgeImport,
  smokeKnowledgeImport,
  updateImportCandidate,
  validateKnowledgeImport,
  type ImportCandidate,
  type ImportCandidateType,
  type KnowledgeImportSummary,
} from "@/api/knowledgeImports";
import { useDomainStore } from "@/stores/domainStore";
import { useToast } from "@/composables/useToast";
import { formatBeijingDateTime } from "@/utils/dateTime";
import {
  configList,
  domainReadiness,
  filterKnowledgeItems,
  type KnowledgeFilters,
} from "./domainHubState";

type PaneId = "overview" | "assets" | "rules" | "operations";
type AssetView = "items" | "documents" | "graph";
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
  relations = ref<KnowledgeRelation[]>([]);
const loading = ref(false),
  graphLoading = ref(false),
  errorMessage = ref(""),
  validating = ref(false),
  rebuilding = ref(false),
  validationResult = ref<DomainValidationResult | null>(null),
  rebuildStatus = ref<RebuildIndexStatus | null>(null);
const domainDrawerOpen = ref(false),
  editingDomain = ref<DomainSummary | null>(null),
  lifecycleLoading = ref(false),
  domainFormError = ref("");
const domainForm = reactive({
  domain_code: "",
  name: "",
  description: "",
  learning_directions: [
    { value: "general", label: "综合学习", description: "", tags: "general" },
  ],
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
  importCandidates = ref<ImportCandidate[]>([]),
  activeImportId = ref("");
const deleteDialog = ref<InstanceType<typeof AppDialog> | null>(null),
  deleteTarget = ref<KnowledgeDocumentItem | null>(null),
  deleting = ref(false);
let pollTimer: number | undefined,
  rebuildPollTimer: number | undefined,
  loadVersion = 0;

const selectedDomain = computed(
  () =>
    domains.value.find((domain) => domain.domain_code === selectedCode.value) ||
    null,
);
const parsedConfig = computed(() => configList(selectedDomain.value)),
  hasDomainConfig = computed(
    () =>
      parsedConfig.value.abilityDimensions.length +
        parsedConfig.value.resourceTypes.length +
        parsedConfig.value.mvpTargets.length >
      0,
  );
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
const assetViews = computed(() => [
  { id: "items" as const, label: "知识点", count: knowledgeItems.value.length },
  {
    id: "documents" as const,
    label: "来源文档",
    count: documents.value.length,
  },
  { id: "graph" as const, label: "关系图谱", count: relations.value.length },
]);
const indexStatusLabel = computed(() =>
  rebuilding.value
    ? "重建中"
    : rebuildStatus.value?.status === "success"
      ? "已完成"
      : ["failed", "interrupted"].includes(rebuildStatus.value?.status || "")
        ? "异常"
        : stats.value?.pending_embeddings
          ? "待同步"
          : "已同步",
);
const indexStatusType = computed(() =>
  indexStatusLabel.value === "已同步" || indexStatusLabel.value === "已完成"
    ? "ok"
    : ("wait" as const),
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
  rebuildStatus.value?.status === "running"
    ? "正在重建索引"
    : rebuildStatus.value?.status === "success"
      ? "索引重建完成"
      : rebuildStatus.value?.status === "interrupted"
        ? "索引重建已中断"
        : "索引重建失败",
);
const rebuildMessageBody = computed(
  () =>
    rebuildStatus.value?.message ||
    (rebuildStatus.value?.result?.status === "unchanged"
      ? "知识库没有变化，未重复向量化。"
      : rebuildStatus.value?.status === "success"
        ? `已索引 ${rebuildStatus.value.result?.indexed_items ?? "-"} 个知识点，重新向量化 ${rebuildStatus.value.result?.reembedded_items ?? 0} 个。`
        : "请检查依赖状态后重试。"),
);
const validationRows = computed(() => {
  const result = validationResult.value;
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
  return ["items", "documents", "graph"].includes(String(value));
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
  domainForm.learning_directions = (domain?.learning_directions?.length
    ? domain.learning_directions
    : [{ value: "general", label: "综合学习", description: "", match_tags: ["general"] }]
  ).map((item) => ({
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
    learning_directions: domainForm.learning_directions.map((item) => ({
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
  loading.value = true;
  graphLoading.value = true;
  errorMessage.value = "";
  domainStore.domains = domains.value;
  domainStore.setWorkspaceDomain(selectedCode.value);
  try {
    const [s, d, r, i, validation] = await Promise.all([
      getDomainStats(selectedCode.value),
      listKnowledgeDocuments(selectedCode.value),
      listKnowledgeRelations(selectedCode.value),
      listKnowledgeItems(selectedCode.value, 500),
      getDomainReadiness(selectedCode.value),
    ]);
    if (version !== loadVersion) return;
    stats.value = s;
    documents.value = d.documents;
    relations.value = r;
    knowledgeItems.value = i.items;
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
  try {
    const data = await listKnowledgeDocuments(domain);
    if (domain !== selectedCode.value) return;
    documents.value = data.documents;
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
    [importSummary.value, importCandidates.value] = await Promise.all([
      getKnowledgeImport(activeImportId.value),
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
function saveCandidate(candidate: ImportCandidate) { return withImportAction(() => updateImportCandidate(activeImportId.value, candidate.candidate_id, candidate.payload), "候选已保存"); }
function runImportValidation() { return withImportAction(() => validateKnowledgeImport(activeImportId.value), "候选校验完成"); }
function approveImport() { return withImportAction(() => approveKnowledgeImport(activeImportId.value), "候选已写入正式知识库"); }
function buildImportIndex() { return withImportAction(() => buildKnowledgeImportIndex(activeImportId.value), "Candidate 索引任务已启动"); }
function smokeImport() { return withImportAction(() => smokeKnowledgeImport(activeImportId.value), "检索冒烟通过"); }
function publishImport() { return withImportAction(() => publishKnowledgeImport(activeImportId.value), "知识导入已发布"); }
function candidateTypeLabel(type: ImportCandidateType) { return ({ knowledge_item: "知识点", knowledge_relation: "知识关系", diagnostic_question: "诊断题" } as Record<ImportCandidateType, string>)[type]; }
function sourceLabel(locator: Record<string, any>) { return locator.page_start ? `第 ${locator.page_start} 页` : (locator.heading_path || []).join(" / ") || "已定位段落"; }
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
  } catch {
    showToast("领域校验失败，请检查向量数据库状态");
  } finally {
    validating.value = false;
  }
}
function isProcessing(status: KnowledgeDocumentStatus) {
  return ["queued", "parsing", "validating", "indexing"].includes(status);
}
function documentStatusLabel(status: KnowledgeDocumentStatus) {
  return (
    (
      {
        queued: "等待处理",
        parsing: "正在解析",
        validating: "正在校验",
        review_pending: "等待复核",
        index_pending: "待构建索引",
        smoke_passed: "冒烟已通过",
        indexing: "正在索引",
        ready: "已就绪",
        failed: "处理失败",
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
        diagnostic_questions: "诊断题",
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
.schema-badge,
.readonly-badge {
  align-self: center;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #fff;
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
  background: #fff;
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
  color: #405067;
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
  background: #fff;
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
  background: #fff0f0;
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
  border-bottom: 1px solid #edf0f4;
}
.readiness-row:nth-child(odd) {
  border-right: 1px solid #edf0f4;
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
  background: #fff0f0;
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
  color: #405067;
  font-size: 12px;
  font-weight: 700;
}
.attention-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  border: 1px solid #ecd4aa;
  border-radius: 10px;
  background: var(--amber2);
  padding: 14px 16px;
  color: #784207;
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
  background: #fff0f0;
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
  color: #8a97a9;
}
.segmented button.active {
  background: #fff;
  color: var(--blue);
  box-shadow: 0 1px 3px rgb(22 35 55/0.09);
}
.asset-body {
  padding: 16px 18px 0;
}
.knowledge-filters {
  padding-bottom: 14px;
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
  background: #fff;
  padding: 0 10px;
  color: var(--muted);
}
.search-field:focus-within {
  border-color: var(--blue);
  box-shadow: 0 0 0 3px rgb(49 95 206/0.14);
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
  background: #d9dfe7;
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
  background: #eef3ff;
  padding: 10px 12px;
  color: #27457f;
}
.experimental-note span {
  border-radius: 999px;
  background: #dce7ff;
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
  border-bottom: 1px solid #edf0f4;
}
.rule-block p {
  margin: 5px 0 0;
  color: var(--muted);
  font-size: 11px;
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
  color: #27457f;
  padding: 6px 9px;
  font-size: 11px;
  font-weight: 650;
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
  border-bottom: 1px solid #edf0f4;
  padding-bottom: 8px;
  color: #405067;
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
  background: #fff;
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
  background: #fff0f0;
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
  border-bottom: 1px solid #edf0f4;
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
  color: #784207;
}
.validation-issue > span {
  width: 23px;
  height: 23px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #f8deb8;
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
  background: linear-gradient(90deg, #eef1f5 25%, #f7f9fb 50%, #eef1f5 75%);
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
  color: #405067;
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
  background: #fff0f0;
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
  background: #eef3ff;
  padding: 12px;
  color: #27457f;
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
  border: 1px dashed #aebbd0;
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

.candidate-item {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--line-color, #d9dee8);
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
  color: #667085;
  font-size: 12px;
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
  background: #fff0f0;
  color: var(--red);
  font-weight: 800;
}
.delete-message p {
  margin: 4px 0;
  color: #405067;
  font-size: 12px;
  line-height: 1.6;
}
@media (max-width: 1000px) {
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
  .schema-badge {
    display: none;
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
  .page-skeleton i {
    animation: none;
  }
  .upload-compact {
    transition: none;
  }
}
</style>
