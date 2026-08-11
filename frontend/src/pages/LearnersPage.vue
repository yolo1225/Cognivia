<template>
  <section class="page">
    <div class="head"><div><h1>用户管理</h1><p class="sub">查看演示学习者及其诊断、画像和学习路径。</p></div><button class="btn" :disabled="loading" @click="loadLearners">刷新列表</button></div>
    <div class="metrics">
      <div class="metric"><div><span>用户总数</span></div><strong>{{ learners.length }}</strong><small>当前有效演示用户</small></div>
      <div class="metric"><div><span>已完成诊断</span></div><strong>{{ readyCount }}</strong><small>{{ learners.length - readyCount }} 人等待首次诊断</small></div>
      <div class="metric"><div><span>已建立画像</span></div><strong>{{ learners.filter(l => l.latest_profile_id).length }}</strong><small>来自真实画像记录</small></div>
      <div class="metric"><div><span>当前领域</span></div><strong>{{ domainCount }}</strong><small>按用户目标领域统计</small></div>
    </div>
    <div v-if="errorMessage" class="error-state"><strong>用户加载失败</strong><p>{{ errorMessage }}</p><button class="btn" @click="loadLearners">重新加载</button></div>
    <div v-else class="panel">
      <div class="panel-head"><h2>用户列表</h2><span class="tag">{{ learners.length }} 人</span></div>
      <div class="table-wrap"><table><thead><tr><th>用户</th><th>目标领域</th><th>能力等级</th><th>画像状态</th><th>最近更新</th><th>操作</th></tr></thead><tbody>
        <tr v-if="!loading && learners.length === 0"><td colspan="6" class="empty-cell">暂无用户数据</td></tr>
        <tr v-for="user in learners" :key="user.learner_id" :class="{ selected: selectedId === user.learner_id }">
          <td><div class="learner-name"><span class="mini-avatar">{{ user.learner_id.slice(-1).toUpperCase() }}</span><span><strong>{{ user.learner_id }}</strong><small>{{ user.profile_type || '尚未形成画像' }}</small></span></div></td>
          <td>{{ user.target_domain }}</td><td>{{ user.ability_level || '-' }}</td><td><span class="status" :class="user.profile_status === 'ready' ? 'ok' : 'wait'">{{ user.profile_status === 'ready' ? '已诊断' : '待诊断' }}</span></td><td>{{ formatDate(user.updated_at) }}</td><td><button class="btn text" @click="openProfile(user.learner_id)">查看用户档案</button></td>
        </tr>
      </tbody></table></div>
    </div>

    <div v-if="profileLoading" class="panel">正在加载用户档案...</div>
    <div v-else-if="profile" class="panel task-detail-panel">
      <div class="panel-head"><div><h2>{{ profile.learner_id }} 的学习档案</h2><p class="sub">{{ profile.background || '未填写背景' }}</p></div><div class="actions"><button class="btn" @click="goDiagnostic">创建诊断测评</button><button class="btn primary" :disabled="profile.profile_status !== 'ready' || generating" @click="generate">{{ generating ? '创建中...' : '生成学习资源' }}</button></div></div>
      <div v-if="profile.profile_status !== 'ready'" class="empty-hint">该用户尚未完成诊断，完成测评后才能形成能力画像并生成资源。</div>
      <template v-else>
        <div class="task-detail-grid"><div><span>画像类型</span><strong>{{ profile.profile_type }}</strong></div><div><span>诊断正确率</span><strong>{{ Math.round(profile.diagnostic_summary.accuracy || 0) }}%</strong></div><div><span>答题数量</span><strong>{{ profile.diagnostic_summary.answer_count }}</strong></div><div><span>学习风格</span><strong>{{ profile.learning_style }}</strong></div></div>
        <div class="cols" style="margin-top:16px"><div><h3>五维能力</h3><div class="mastery"><div v-for="(score,index) in profile.radar" :key="index"><span>{{ radarLabels[index] }}</span><strong>{{ score }}</strong></div></div></div><div><h3>薄弱知识点</h3><div v-if="profile.weak_knowledge.length"><div v-for="item in profile.weak_knowledge" :key="item.knowledge_id" class="source"><strong>{{ item.name }}</strong><span>{{ item.category }} · 薄弱等级 {{ item.weakness_level }}</span></div></div><div v-else class="empty-hint">当前没有已确认的薄弱知识点。</div></div></div>
        <h3 style="margin:18px 0 10px">推荐学习路径</h3><div v-if="profile.learning_path?.stages?.length" class="path"><div v-for="(stage,index) in profile.learning_path.stages" :key="index" class="node"><div class="node-num">{{ index+1 }}</div><div><strong>{{ stage.name }}</strong><p>{{ stage.description || '按诊断结果推荐' }}</p></div></div></div><div v-else class="empty-hint">尚未生成学习路径。</div>
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createGenerationTask } from '@/api/generation'
import { getLearnerProfile, listLearners, type LearnerProfileDetail, type LearnerSummary } from '@/api/learners'
import { useToast } from '@/composables/useToast'
import { useLearnerStore } from '@/stores/learnerStore'
import { formatBeijingDateTime } from '@/utils/dateTime'
const router = useRouter(); const { showToast } = useToast(); const learnerStore = useLearnerStore()
const learners = ref<LearnerSummary[]>([]); const profile = ref<LearnerProfileDetail | null>(null); const selectedId = ref(''); const loading = ref(false); const profileLoading = ref(false); const generating = ref(false); const errorMessage = ref('')
const radarLabels = ['理论基础','实操能力','问题解决','知识广度','学习速度']
const readyCount = computed(() => learners.value.filter(l => l.profile_status === 'ready').length)
const domainCount = computed(() => new Set(learners.value.map(l => l.target_domain).filter(Boolean)).size)
async function loadLearners(){ loading.value=true; errorMessage.value=''; try { learners.value=await listLearners() } catch { errorMessage.value='无法读取用户数据，请确认后端服务可用。' } finally { loading.value=false } }
async function openProfile(id:string){ selectedId.value=id; learnerStore.setSelectedLearner(id); profileLoading.value=true; try { profile.value=await getLearnerProfile(id) } catch { showToast('用户档案加载失败') } finally { profileLoading.value=false } }
function goDiagnostic(){ router.push({ path:'/diagnostic', query:{ learner_id:selectedId.value } }) }
async function generate(){ if(!profile.value?.profile_id) return; generating.value=true; try { const task=await createGenerationTask(profile.value.profile_id, profile.value.learner_id); router.push({path:'/metrics',query:{task_id:task.task_id}}) } catch { showToast('创建生成任务失败') } finally { generating.value=false } }
const formatDate = formatBeijingDateTime
onMounted(loadLearners)
</script>
