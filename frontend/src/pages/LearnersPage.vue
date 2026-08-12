<template>
  <section class="page">
    <div class="head">
      <div><h1>用户管理</h1><p class="sub">管理登录账号，并按需查看关联学习者的只读学习档案。</p></div>
      <button class="btn" :disabled="loading" @click="loadAll">刷新列表</button>
    </div>

    <div class="metrics">
      <div class="metric"><div><span>账号总数</span></div><strong>{{ accounts.length }}</strong><small>当前已创建的登录账号</small></div>
      <div class="metric"><div><span>正常账号</span></div><strong>{{ activeCount }}</strong><small>可正常登录使用</small></div>
      <div class="metric"><div><span>已禁用账号</span></div><strong>{{ disabledCount }}</strong><small>已暂停登录权限</small></div>
      <div class="metric"><div><span>管理员</span></div><strong>{{ adminCount }}</strong><small>具备管理权限的账号</small></div>
    </div>

    <div v-if="errorMessage" class="error-state"><strong>账号加载失败</strong><p>{{ errorMessage }}</p><button class="btn" @click="loadAll">重新加载</button></div>
    <div v-else class="panel">
      <div class="panel-head"><h2>登录账号</h2><span class="tag">{{ accounts.length }} 个</span></div>
      <div class="table-wrap"><table><thead><tr><th>用户名</th><th>账号角色</th><th>账号状态</th><th>操作</th></tr></thead><tbody>
        <tr v-if="!loading && accounts.length === 0"><td colspan="4" class="empty-cell">暂无登录账号</td></tr>
        <tr v-for="account in sortedAccounts" :key="account.user_id">
          <td><div class="learner-name"><span class="mini-avatar">{{ (account.display_name || account.username || '?').slice(0, 1).toUpperCase() }}</span><span><strong>{{ account.display_name || account.username || '未命名账号' }}</strong><small>{{ account.username || '未设置用户名' }}</small></span></div></td>
          <td>{{ account.role === 'admin' ? '管理员' : '普通用户' }}</td>
          <td><span class="status" :class="account.status === 'active' ? 'ok' : 'wait'">{{ account.status === 'active' ? '正常' : '已禁用' }}</span></td>
          <td class="row-actions"><button v-if="account.role !== 'admin'" class="btn text" @click="toggleAccount(account)">{{ account.status === 'active' ? '禁用' : '启用' }}</button><span v-else class="admin-lock">管理员账号不可禁用</span><button class="btn text" @click="openResetDialog(account)">重置密码</button><button class="btn text" :disabled="!account.learner_id" :title="account.learner_id ? '查看学习档案' : '该账号未关联学习档案'" @click="account.learner_id && openProfile(account.learner_id)">查看学习档案</button></td>
        </tr>
      </tbody></table></div>
    </div>

    <div v-if="profileLoading" class="panel">正在加载学习档案...</div>
    <section v-else-if="profile" class="panel task-detail-panel" aria-label="只读学习档案">
      <div class="panel-head"><div><h2>{{ profile.learner_id }} 的学习档案</h2><p class="sub">仅供查看，不支持在此发起诊断或生成学习资源。</p></div><button class="btn" @click="closeProfile">收起档案</button></div>
      <div v-if="profile.profile_status !== 'ready'" class="empty-hint">该学习者暂未完成诊断，暂无可展示的能力画像与学习路径。</div>
      <template v-else>
        <div class="task-detail-grid"><div><span>画像类型</span><strong>{{ profile.profile_type }}</strong></div><div><span>诊断正确率</span><strong>{{ Math.round(profile.diagnostic_summary.accuracy || 0) }}%</strong></div><div><span>答题数量</span><strong>{{ profile.diagnostic_summary.answer_count }}</strong></div><div><span>学习风格</span><strong>{{ profile.learning_style }}</strong></div></div>
        <div class="cols" style="margin-top:16px"><div><h3>五维能力</h3><div class="mastery"><div v-for="(score,index) in profile.radar" :key="index"><span>{{ radarLabels[index] }}</span><strong>{{ score }}</strong></div></div></div><div><h3>薄弱知识点</h3><div v-if="profile.weak_knowledge.length"><div v-for="item in profile.weak_knowledge" :key="item.knowledge_id" class="source"><strong>{{ item.name }}</strong><span>{{ item.category }} · 薄弱等级 {{ item.weakness_level }}</span></div></div><div v-else class="empty-hint">当前没有已确认的薄弱知识点。</div></div></div>
        <h3 style="margin:18px 0 10px">推荐学习路径</h3><div v-if="profile.learning_path?.stages?.length" class="path"><div v-for="(stage,index) in profile.learning_path.stages" :key="index" class="node"><div class="node-num">{{ index+1 }}</div><div><strong>{{ stage.name }}</strong><p>{{ stage.description || '按诊断结果推荐' }}</p></div></div></div><div v-else class="empty-hint">尚未生成学习路径。</div>
      </template>
    </section>

    <AppDialog ref="resetDialog" title="重置密码" :subtitle="resetTarget ? `为账号 ${resetTarget.username} 设置新密码` : ''">
      <form id="reset-password-form" class="reset-form" @submit.prevent="confirmReset">
        <label for="new-password">新密码
          <input id="new-password" v-model="newPassword" type="password" autocomplete="new-password" required minlength="8" maxlength="72" placeholder="至少 8 位密码" />
        </label>
        <p v-if="resetError" class="reset-error" role="alert">{{ resetError }}</p>
        <p class="reset-hint">确认后，用户需要使用新密码重新登录。</p>
      </form>
      <template #footer><button class="btn" type="button" :disabled="resetting" @click="closeResetDialog">取消</button><button class="btn primary" type="submit" form="reset-password-form" :disabled="resetting">{{ resetting ? '正在重置...' : '确认重置' }}</button></template>
    </AppDialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppDialog from '@/components/Shared/AppDialog.vue'
import { getLearnerProfile, type LearnerProfileDetail } from '@/api/learners'
import { useToast } from '@/composables/useToast'
import { listUsers, resetPassword, setUserStatus, type AdminUser } from '@/api/adminUsers'

const { showToast } = useToast()
const accounts = ref<AdminUser[]>([])
const profile = ref<LearnerProfileDetail | null>(null)
const loading = ref(false)
const profileLoading = ref(false)
const errorMessage = ref('')
const resetDialog = ref<InstanceType<typeof AppDialog> | null>(null)
const resetTarget = ref<AdminUser | null>(null)
const newPassword = ref('')
const resetError = ref('')
const resetting = ref(false)
const radarLabels = ['理论基础', '实操能力', '问题解决', '知识广度', '学习速度']
const activeCount = computed(() => accounts.value.filter(account => account.status === 'active').length)
const disabledCount = computed(() => accounts.value.filter(account => account.status === 'disabled').length)
const adminCount = computed(() => accounts.value.filter(account => account.role === 'admin').length)
const sortedAccounts = computed(() => [...accounts.value].sort((left, right) => Number(right.role === 'admin') - Number(left.role === 'admin') || (left.username || '').localeCompare(right.username || '', 'zh-CN')))

async function loadAll() {
  loading.value = true
  errorMessage.value = ''
  try { accounts.value = await listUsers() }
  catch { errorMessage.value = '无法读取登录账号，请确认后端服务可用。' }
  finally { loading.value = false }
}
async function toggleAccount(account: AdminUser) {
  try { await setUserStatus(account.user_id, account.status === 'active' ? 'disabled' : 'active'); await loadAll(); showToast('账号状态已更新') }
  catch { showToast('账号状态更新失败') }
}
function openResetDialog(account: AdminUser) {
  resetTarget.value = account
  newPassword.value = ''
  resetError.value = ''
  resetDialog.value?.open()
}
function closeResetDialog() {
  resetDialog.value?.close()
  resetTarget.value = null
  newPassword.value = ''
  resetError.value = ''
}
async function confirmReset() {
  if (!resetTarget.value) return
  if (newPassword.value.length < 8) { resetError.value = '新密码至少需要 8 位。'; return }
  resetting.value = true
  resetError.value = ''
  try { await resetPassword(resetTarget.value.user_id, newPassword.value); showToast('密码已重置'); closeResetDialog() }
  catch { resetError.value = '密码重置失败，请稍后重试。' }
  finally { resetting.value = false }
}
async function openProfile(learnerId: string) {
  profileLoading.value = true
  try { profile.value = await getLearnerProfile(learnerId) }
  catch { showToast('学习档案加载失败') }
  finally { profileLoading.value = false }
}
function closeProfile() { profile.value = null }

onMounted(loadAll)
</script>

<style scoped>
.row-actions { white-space: nowrap; }
.row-actions .btn:disabled { color: var(--muted); }
.admin-lock { margin-right: 8px; color: var(--muted); font-size: 12px; }
.reset-form { display: grid; gap: 10px; padding: 10px 0; }
.reset-form label { display: grid; gap: 7px; color: #405067; font-size: 13px; font-weight: 700; }
.reset-form input { min-height: 40px; border: 1px solid var(--line); border-radius: 8px; color: var(--ink); padding: 8px 10px; }
.reset-form input:focus { border-color: var(--blue); outline: 0; box-shadow: 0 0 0 3px rgb(49 95 206 / .16); }
.reset-hint { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.6; }
.reset-error { margin: 0; border-radius: 7px; background: #fff0f0; color: var(--red); padding: 9px 10px; font-size: 12px; }
</style>
