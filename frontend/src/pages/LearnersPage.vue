<template>
  <section class="page users-page">
    <PageHeader title="用户管理" description="集中管理登录账号、访问状态与安全会话，并按需查看关联学习者的学情画像。">
      <template #actions>
        <span v-if="lastLoadedAt" class="last-updated"
          >更新于 {{ lastLoadedAt }}</span
        ><button type="button" class="btn" :disabled="loading" :aria-busy="loading" @click="loadAll">
          {{ loading ? "正在刷新" : "刷新列表" }}
        </button>
      </template>
    </PageHeader>

    <MetricStrip :items="metricItems.map(item => ({ ...item, value: loading && !hasLoaded ? '—' : item.value }))" aria-label="账号概览" />

    <div v-if="errorMessage && !hasLoaded" class="error-state" role="alert">
      <strong>账号加载失败</strong>
      <p>{{ errorMessage }}</p>
      <button class="btn" @click="loadAll">重新加载</button>
    </div>

    <section
      v-else
      class="panel accounts-panel"
      aria-labelledby="accounts-title"
    >
      <div class="accounts-heading">
        <div>
          <h2 id="accounts-title">登录账号</h2>
          <p>{{ resultSummary }}</p>
        </div>
        <span class="result-count"
          >{{ filteredAccounts.length }} / {{ accounts.length }}</span
        >
      </div>
      <div class="account-toolbar" role="search">
        <label class="search-field"
          ><span class="sr-only">搜索用户</span><span aria-hidden="true">⌕</span
          ><input
            v-model="filters.keyword"
            type="search"
            placeholder="搜索显示名称或用户名"
        /></label>
        <label
          ><span class="sr-only">筛选账号角色</span
          ><select v-model="filters.role" class="field">
            <option value="all">全部角色</option>
            <option value="admin">管理员</option>
            <option value="learner">普通用户</option>
          </select></label
        >
        <label
          ><span class="sr-only">筛选账号状态</span
          ><select v-model="filters.status" class="field">
            <option value="all">全部状态</option>
            <option value="active">正常</option>
            <option value="disabled">已禁用</option>
          </select></label
        >
        <button
          v-if="hasActiveFilters"
          class="btn text clear-filter"
          type="button"
          @click="clearFilters"
        >
          清除筛选
        </button>
      </div>
      <div v-if="errorMessage" class="inline-error" role="alert">
        <span>{{ errorMessage }}</span
        ><button class="btn text" @click="loadAll">重试</button>
      </div>
      <div
        v-if="loading && !hasLoaded"
        class="table-skeleton"
        aria-label="正在加载账号"
      >
        <div v-for="index in 5" :key="index" class="skeleton-row">
          <i /><i /><i /><i />
        </div>
      </div>
      <div v-else-if="accounts.length === 0" class="account-empty">
        <strong>暂无登录账号</strong>
        <p>当前系统还没有可管理的登录账号。</p>
      </div>
      <div v-else-if="filteredAccounts.length === 0" class="account-empty">
        <strong>没有符合条件的账号</strong>
        <p>调整关键词或筛选条件后再试。</p>
        <button class="btn" @click="clearFilters">清除筛选</button>
      </div>
      <div v-else class="table-wrap">
        <table class="accounts-table">
          <thead>
            <tr>
              <th>用户</th>
              <th>角色</th>
              <th>状态</th>
              <th class="profile-col">关联档案</th>
              <th class="created-col">创建时间</th>
              <th class="actions-col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="account in filteredAccounts"
              :key="account.user_id"
              :class="{ 'row-busy': busyUserId === account.user_id }"
            >
              <td>
                <div class="learner-name">
                  <span class="mini-avatar">{{ accountInitial(account) }}</span
                  ><span
                    ><strong>{{
                      account.display_name || account.username || "未命名账号"
                    }}</strong
                    ><small
                      >@{{ account.username || "未设置用户名" }}</small
                    ></span
                  >
                </div>
              </td>
              <td>
                <span
                  class="role-label"
                  :class="{ admin: account.role === 'admin' }"
                  >{{ roleLabel(account.role) }}</span
                >
              </td>
              <td>
                <StatusBadge
                  :label="statusLabel(account.status)"
                  :type="account.status === 'active' ? 'ok' : 'wait'"
                />
              </td>
              <td class="profile-col">
                <span
                  class="profile-link-state"
                  :class="{ linked: account.learner_id }"
                  ><i />{{ account.learner_id ? "已关联" : "未关联" }}</span
                >
              </td>
              <td class="created-col">
                <time :datetime="account.created_at">{{
                  formatBeijingDate(account.created_at)
                }}</time>
              </td>
              <td class="actions-col">
                <div class="row-actions">
                  <button
                    class="btn text view-profile"
                    :disabled="
                      !account.learner_id || busyUserId === account.user_id
                    "
                    :title="
                      account.learner_id
                        ? '查看学情画像'
                        : '该账号未关联学习者档案'
                    "
                    @click="account.learner_id && openProfile(account)"
                  >
                    查看画像
                  </button>
                  <div class="action-menu">
                    <button
                      class="more-button"
                      :disabled="busyUserId === account.user_id"
                      :aria-expanded="openMenuId === account.user_id"
                      aria-haspopup="menu"
                      :aria-label="`${account.username} 的更多操作`"
                      @click.stop="toggleMenu(account, $event)"
                    >
                      {{ busyUserId === account.user_id ? "处理中" : "更多" }}
                      <span aria-hidden="true">⌄</span>
                    </button>
                  </div>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <Teleport to="body">
      <div
        v-if="menuTarget"
        class="menu-popover floating-menu"
        :style="menuPosition"
        role="menu"
        @click.stop
      >
        <button
          v-if="menuTarget.role !== 'admin'"
          role="menuitem"
          @click="requestStatusChange(menuTarget)"
        >
          {{ menuTarget.status === "active" ? "禁用账号" : "启用账号" }}
        </button>
        <span v-else class="menu-note">管理员账号不可禁用</span>
        <button role="menuitem" @click="openResetDialog(menuTarget)">
          重置密码
        </button>
        <button role="menuitem" @click="requestSessionRevoke(menuTarget)">
          撤销登录会话
        </button>
      </div>
    </Teleport>

    <AppDrawer
      v-model="profileOpen"
      title="学情画像"
      :subtitle="
        profileTarget
          ? `${profileTarget.display_name || profileTarget.username} · 管理视图`
          : '管理视图'
      "
    >
      <div v-if="profileTarget" class="drawer-account">
        <span class="mini-avatar large">{{
          accountInitial(profileTarget)
        }}</span>
        <div>
          <strong>{{
            profileTarget.display_name || profileTarget.username
          }}</strong
          ><span
            >@{{ profileTarget.username }} ·
            {{ roleLabel(profileTarget.role) }}</span
          >
        </div>
        <StatusBadge
          :label="statusLabel(profileTarget.status)"
          :type="profileTarget.status === 'active' ? 'ok' : 'wait'"
        />
      </div>
      <div v-if="profileLoading" class="profile-loading"><i /><i /><i /></div>
      <div v-else-if="profileError" class="drawer-error" role="alert">
        <strong>学情画像加载失败</strong>
        <p>{{ profileError }}</p>
        <button class="btn" @click="retryProfile">重新加载</button>
      </div>
      <div
        v-else-if="profile && profile.profile_status !== 'ready'"
        class="profile-empty"
      >
        <span aria-hidden="true">○</span><strong>尚未完成首次诊断</strong>
        <p>
          完成学习背景采集和诊断测评后，这里将显示能力结构、学习重点和个性化路线。
        </p>
      </div>
      <template v-else-if="profile">
        <section class="admin-profile-overview">
          <span>当前学情</span>
          <h3>{{ profileTypeLabel(profile.profile_type) }}</h3>
          <p>{{ profile.education_level || '学习背景待补充' }}<template v-if="profile.major"> · {{ profile.major }}</template></p>
          <div class="admin-profile-stats">
            <div><span>诊断表现</span><strong>{{ Math.round(profile.diagnostic_summary.accuracy || 0) }}%</strong><small>{{ profile.diagnostic_summary.correct_count }}/{{ profile.diagnostic_summary.answer_count }} 题答对</small></div>
            <div><span>待加强</span><strong>{{ profile.weak_knowledge.length }}</strong><small>项重点知识</small></div>
            <div><span>学习路线</span><strong>{{ profileRouteItems.length }}</strong><small>个学习节点</small></div>
          </div>
        </section>
        <section class="profile-section profile-insight-section">
          <div class="section-title"><h3>能力结论</h3><span>诊断依据</span></div>
          <div class="profile-insights"><article v-for="item in profileInsights" :key="item.label" :class="`insight-${item.tone}`"><span>{{ item.label }}</span><strong>{{ item.value }}</strong><p>{{ item.description }}</p></article></div>
        </section>
        <section class="profile-section">
          <div class="section-title"><h3>当前学习重点</h3><span>{{ profile.weak_knowledge.length }} 项</span></div>
          <div v-if="profile.weak_knowledge.length" class="profile-focus-list"><article v-for="(item, index) in profile.weak_knowledge.slice(0, 5)" :key="item.knowledge_id"><span>{{ index + 1 }}</span><div><strong>{{ item.name }}</strong><small>{{ item.category }}</small></div><em :class="weaknessTone(item.weakness_level)">{{ weaknessLabel(item.weakness_level) }}</em></article></div>
          <p v-else class="section-empty">当前没有已确认的薄弱知识点。</p>
        </section>
        <section class="profile-section">
          <div class="section-title"><h3>个性化学习路线</h3><span>{{ profileRouteItems.length }} 个节点</span></div>
          <div v-if="profileRouteItems.length" class="profile-route-list"><article v-for="item in profileRouteItems" :key="item.id" :class="`route-${item.status}`"><span>{{ String(item.order).padStart(2, '0') }}</span><div><strong>{{ item.title }}</strong><p>{{ item.description }}</p></div><em>{{ pathStatusLabel(item.status) }}</em></article></div>
          <p v-else class="section-empty">尚未生成学习路线。</p>
        </section>
      </template>
    </AppDrawer>

    <AppDialog
      ref="confirmDialog"
      :title="confirmCopy.title"
      :subtitle="confirmCopy.subtitle"
      ><div
        class="confirm-content"
        :class="{
          caution:
            pendingAction?.kind === 'disable' ||
            pendingAction?.kind === 'revoke',
        }"
      >
        <span aria-hidden="true">!</span>
        <p>{{ confirmCopy.body }}</p>
      </div>
      <template #footer
        ><button class="btn" :disabled="confirming" @click="closeConfirmDialog">
          取消</button
        ><button
          class="btn"
          :class="{ primary: pendingAction?.kind === 'enable' }"
          :disabled="confirming"
          @click="confirmAccountAction"
        >
          {{ confirming ? "正在处理..." : confirmCopy.confirmLabel }}
        </button></template
      ></AppDialog
    >
    <AppDialog
      ref="resetDialog"
      title="重置密码"
      :subtitle="resetTarget ? `为账号 ${resetTarget.username} 设置新密码` : ''"
      ><form
        id="reset-password-form"
        class="reset-form"
        @submit.prevent="confirmReset"
      >
        <label for="new-password"
          >新密码<input
            id="new-password"
            v-model="newPassword"
            type="password"
            autocomplete="new-password"
            required
            minlength="8"
            maxlength="72"
            placeholder="至少 8 位密码"
        /></label>
        <p v-if="resetError" class="reset-error" role="alert">
          {{ resetError }}
        </p>
        <p class="reset-hint">
          保存后当前登录会话不会自动撤销。如需强制重新登录，请再执行“撤销登录会话”。
        </p>
      </form>
      <template #footer
        ><button
          class="btn"
          type="button"
          :disabled="resetting"
          @click="closeResetDialog"
        >
          取消</button
        ><button
          class="btn primary"
          type="submit"
          form="reset-password-form"
          :disabled="resetting"
        >
          {{ resetting ? "正在重置..." : "重置密码" }}
        </button></template
      ></AppDialog
    >
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import AppDialog from "@/components/Shared/AppDialog.vue";
import AppDrawer from "@/components/Shared/AppDrawer.vue";
import StatusBadge from "@/components/Shared/StatusBadge.vue";
import MetricStrip from "@/components/Shared/MetricStrip.vue";
import PageHeader from "@/components/Shared/PageHeader.vue";
import { getLearnerProfile, type LearnerProfileDetail } from "@/api/learners";
import { useToast } from "@/composables/useToast";
import {
  listUsers,
  resetPassword,
  revokeSessions,
  setUserStatus,
  type AdminUser,
} from "@/api/adminUsers";
import {
  filterAndSortAdminUsers,
  roleLabel,
  statusLabel,
  type AdminUserFilters,
} from "./adminUsersState";
import { formatBeijingDate } from "@/utils/dateTime";

type PendingAction = {
  kind: "enable" | "disable" | "revoke";
  account: AdminUser;
};
const { showToast } = useToast();
const accounts = ref<AdminUser[]>([]);
const loading = ref(false),
  hasLoaded = ref(false);
const errorMessage = ref(""),
  lastLoadedAt = ref("");
const filters = reactive<AdminUserFilters>({
  keyword: "",
  role: "all",
  status: "all",
});
const openMenuId = ref<string | null>(null),
  menuTarget = ref<AdminUser | null>(null),
  busyUserId = ref<string | null>(null);
const menuPosition = reactive({ top: "0px", left: "0px" });
const profileOpen = ref(false),
  profileTarget = ref<AdminUser | null>(null),
  profile = ref<LearnerProfileDetail | null>(null),
  profileLoading = ref(false),
  profileError = ref("");
const confirmDialog = ref<InstanceType<typeof AppDialog> | null>(null),
  pendingAction = ref<PendingAction | null>(null),
  confirming = ref(false);
const resetDialog = ref<InstanceType<typeof AppDialog> | null>(null),
  resetTarget = ref<AdminUser | null>(null),
  newPassword = ref(""),
  resetError = ref(""),
  resetting = ref(false);
const radarLabels = ["理论掌握", "实操应用", "场景解决", "知识广度", "学习速度"];
const activeCount = computed(
  () => accounts.value.filter((a) => a.status === "active").length,
);
const disabledCount = computed(
  () => accounts.value.filter((a) => a.status === "disabled").length,
);
const adminCount = computed(
  () => accounts.value.filter((a) => a.role === "admin").length,
);
const filteredAccounts = computed(() =>
  filterAndSortAdminUsers(accounts.value, filters),
);
const hasActiveFilters = computed(
  () =>
    Boolean(filters.keyword.trim()) ||
    filters.role !== "all" ||
    filters.status !== "all",
);
const metricItems = computed(() => [
  {
    label: "账号总数",
    value: accounts.value.length,
    description: "当前已创建账号",
  },
  {
    label: "正常账号",
    value: activeCount.value,
    description: "可正常登录使用",
  },
  {
    label: "已禁用账号",
    value: disabledCount.value,
    description: "已暂停登录权限",
  },
  { label: "管理员", value: adminCount.value, description: "具备管理权限" },
]);
const resultSummary = computed(() =>
  hasActiveFilters.value
    ? `已从 ${accounts.value.length} 个账号中筛选出 ${filteredAccounts.value.length} 个`
    : `管理 ${accounts.value.length} 个登录账号的访问状态与安全设置`,
);
const profileRouteItems = computed(() => {
  const nodes = profile.value?.learning_path?.nodes || [];
  if (nodes.length) {
    return [...nodes]
      .sort((left, right) => left.path_order - right.path_order)
      .map((node) => ({
        id: node.path_node_id,
        order: node.path_order,
        title: node.title,
        description: node.learning_objective || "按当前学情推荐",
        status: node.status,
      }));
  }
  return (profile.value?.learning_path?.stages || []).map((stage, index) => ({
    id: `legacy-stage-${index}`,
    order: index + 1,
    title: stage.name,
    description: stage.description || "按当前学情推荐",
    status: (index === 0 ? "current" : "locked") as "current" | "locked",
  }));
});
const profileInsights = computed(() => {
  if (!profile.value) return [];
  const scores = profile.value.radar.map((value, index) => ({
    label: radarLabels[index] || `能力维度 ${index + 1}`,
    value: Math.max(0, Math.min(100, Number(value) || 0)),
  }));
  const strongest = [...scores].sort((left, right) => right.value - left.value)[0];
  const weakest = [...scores].sort((left, right) => left.value - right.value)[0];
  const focus = [...profile.value.weak_knowledge].sort(
    (left, right) => right.weakness_level - left.weakness_level,
  )[0];
  return [
    strongest && { label: "当前优势", value: strongest.label, description: "当前诊断中表现相对稳定。", tone: "strength" },
    {
      label: "优先提升",
      value: focus?.name || weakest?.label || "持续练习",
      description: focus ? "已纳入学习重点，建议优先完成相关路线。" : "通过当前学习路线继续巩固。",
      tone: "focus",
    },
  ].filter(Boolean) as Array<{ label: string; value: string; description: string; tone: "strength" | "focus" }>;
});
const confirmCopy = computed(() => {
  const action = pendingAction.value;
  const username = action?.account.username || "该账号";
  if (action?.kind === "disable")
    return {
      title: "禁用账号",
      subtitle: username,
      body: "禁用后，该用户将无法继续登录。已有业务数据和学习档案不会被删除。",
      confirmLabel: "禁用账号",
    };
  if (action?.kind === "enable")
    return {
      title: "启用账号",
      subtitle: username,
      body: "启用后，该用户可以重新登录并访问其原有学习数据。",
      confirmLabel: "启用账号",
    };
  return {
    title: "撤销登录会话",
    subtitle: username,
    body: "该账号当前的刷新会话将失效，用户需要重新登录。账号本身不会被禁用。",
    confirmLabel: "撤销会话",
  };
});

async function loadAll() {
  loading.value = true;
  errorMessage.value = "";
  try {
    accounts.value = await listUsers();
    hasLoaded.value = true;
    lastLoadedAt.value = new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).format(new Date());
  } catch {
    errorMessage.value = "无法读取登录账号，请确认后端服务可用后重试。";
  } finally {
    loading.value = false;
  }
}
function clearFilters() {
  filters.keyword = "";
  filters.role = "all";
  filters.status = "all";
}
function accountInitial(account: AdminUser) {
  return (account.display_name || account.username || "?")
    .trim()
    .slice(0, 1)
    .toUpperCase();
}
function profileTypeLabel(type?: string) {
  return ({
    beginner: "基础起步型学习者",
    intermediate: "进阶提升型学习者",
    advanced: "综合应用型学习者",
    practice_oriented: "实操导向型学习者",
  } as Record<string, string>)[type || ""] || type || "画像待确认";
}
function weaknessLabel(level: number) {
  if (level >= 4) return "优先补强";
  if (level === 3) return "重点巩固";
  return "持续练习";
}
function weaknessTone(level: number) {
  if (level >= 4) return "high";
  if (level === 3) return "mid";
  return "low";
}
function pathStatusLabel(status: "locked" | "current" | "completed" | "skipped") {
  return ({ locked: "待解锁", current: "当前学习", completed: "已完成", skipped: "已跳过" } as const)[status];
}
function toggleMenu(account: AdminUser, event: MouseEvent) {
  if (openMenuId.value === account.user_id) {
    closeMenus();
    return;
  }
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
  const menuWidth = 168;
  const menuHeight = account.role === "admin" ? 126 : 132;
  const gap = 5;
  const top =
    rect.bottom + gap + menuHeight <= window.innerHeight
      ? rect.bottom + gap
      : Math.max(8, rect.top - menuHeight - gap);
  const left = Math.min(
    window.innerWidth - menuWidth - 8,
    Math.max(8, rect.right - menuWidth),
  );
  menuPosition.top = `${top}px`;
  menuPosition.left = `${left}px`;
  menuTarget.value = account;
  openMenuId.value = account.user_id;
}
function closeMenus() {
  openMenuId.value = null;
  menuTarget.value = null;
}
function requestStatusChange(account: AdminUser) {
  pendingAction.value = {
    kind: account.status === "active" ? "disable" : "enable",
    account,
  };
  closeMenus();
  confirmDialog.value?.open();
}
function requestSessionRevoke(account: AdminUser) {
  pendingAction.value = { kind: "revoke", account };
  closeMenus();
  confirmDialog.value?.open();
}
function closeConfirmDialog() {
  confirmDialog.value?.close();
  pendingAction.value = null;
}
async function confirmAccountAction() {
  const action = pendingAction.value;
  if (!action) return;
  confirming.value = true;
  busyUserId.value = action.account.user_id;
  try {
    if (action.kind === "revoke") {
      await revokeSessions(action.account.user_id);
      showToast("登录会话已撤销");
    } else {
      const status = action.kind === "disable" ? "disabled" : "active";
      const updated = await setUserStatus(action.account.user_id, status);
      const index = accounts.value.findIndex(
        (item) => item.user_id === action.account.user_id,
      );
      if (index >= 0)
        accounts.value[index] = {
          ...accounts.value[index],
          ...updated,
          status,
        };
      showToast(action.kind === "disable" ? "账号已禁用" : "账号已启用");
    }
    closeConfirmDialog();
  } catch {
    showToast(
      action.kind === "revoke"
        ? "会话撤销失败，请稍后重试"
        : "账号状态更新失败，请稍后重试",
    );
  } finally {
    confirming.value = false;
    busyUserId.value = null;
  }
}
async function openProfile(account: AdminUser) {
  if (!account.learner_id) return;
  profileTarget.value = account;
  profile.value = null;
  profileError.value = "";
  profileOpen.value = true;
  await loadProfile(account.learner_id);
}
async function loadProfile(learnerId: string) {
  profileLoading.value = true;
  profileError.value = "";
  try {
    profile.value = await getLearnerProfile(learnerId);
  } catch {
    profileError.value = "无法读取该学习者的学情画像，请稍后重试。";
  } finally {
    profileLoading.value = false;
  }
}
function retryProfile() {
  if (profileTarget.value?.learner_id)
    loadProfile(profileTarget.value.learner_id);
}
function openResetDialog(account: AdminUser) {
  resetTarget.value = account;
  newPassword.value = "";
  resetError.value = "";
  closeMenus();
  resetDialog.value?.open();
}
function closeResetDialog() {
  resetDialog.value?.close();
  resetTarget.value = null;
  newPassword.value = "";
  resetError.value = "";
}
async function confirmReset() {
  if (!resetTarget.value) return;
  if (newPassword.value.length < 8) {
    resetError.value = "新密码至少需要 8 位。";
    return;
  }
  resetting.value = true;
  busyUserId.value = resetTarget.value.user_id;
  resetError.value = "";
  try {
    await resetPassword(resetTarget.value.user_id, newPassword.value);
    showToast("密码已重置");
    closeResetDialog();
  } catch {
    resetError.value = "密码重置失败，请稍后重试。";
  } finally {
    resetting.value = false;
    busyUserId.value = null;
  }
}
onMounted(() => {
  loadAll();
  document.addEventListener("click", closeMenus);
  window.addEventListener("scroll", closeMenus, true);
  window.addEventListener("resize", closeMenus);
});
onUnmounted(() => {
  document.removeEventListener("click", closeMenus);
  window.removeEventListener("scroll", closeMenus, true);
  window.removeEventListener("resize", closeMenus);
});
</script>

<style scoped>
.users-page {
  gap: 16px;
}
.last-updated {
  align-self: center;
  color: var(--muted);
  font-size: 12px;
}
/* 保持原有四项指标布局，仅统一管理侧边框与浅色底面。 */
.users-page :deep(.metric-strip) {
  border-color: var(--line);
  background: var(--soft);
}
.account-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
}
.account-metric {
  min-width: 0;
  padding: 15px 18px;
  border-right: 1px solid var(--line);
}
.account-metric:last-child {
  border-right: 0;
}
.account-metric span,
.account-metric small {
  display: block;
  color: var(--muted);
  font-size: 12px;
}
.account-metric strong {
  display: block;
  margin: 7px 0 5px;
  color: var(--ink);
  font-size: 25px;
  line-height: 1;
}
.accounts-panel {
  padding: 0;
  overflow: visible;
}
.accounts-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 18px 14px;
}
.accounts-heading p {
  margin: 5px 0 0;
  color: var(--muted);
  font-size: 12px;
}
.result-count {
  border-radius: 999px;
  background: var(--soft);
  color: var(--muted);
  padding: 5px 9px;
  font-size: 11px;
  font-weight: 700;
}
.account-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 18px 14px;
  border-bottom: 1px solid var(--line);
}
.search-field {
  min-width: 260px;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  padding: 0 11px;
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
  color: var(--ink);
  font: inherit;
  font-size: 12px;
}
.field {
  min-width: 120px;
  min-height: 38px;
}
.clear-filter {
  flex: none;
}
.inline-error {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin: 12px 18px 0;
  border-radius: 8px;
  background: var(--red2);
  color: var(--red);
  padding: 9px 11px;
  font-size: 12px;
}
.accounts-table th {
  white-space: nowrap;
  padding: 10px 18px;
}
.accounts-table td {
  height: 62px;
  padding: 10px 18px;
  vertical-align: middle;
}
.accounts-table tbody tr {
  transition: background-color 180ms ease;
}
.accounts-table tbody tr:hover {
  background: var(--soft);
}
.accounts-table tbody tr:last-child td {
  border-bottom: 0;
}
.row-busy {
  opacity: 0.66;
}
.role-label {
  display: inline-flex;
  color: var(--body);
  font-weight: 650;
}
.role-label.admin {
  color: var(--blue);
}
.profile-link-state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
}
.profile-link-state i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--muted);
}
.profile-link-state.linked {
  color: var(--body);
}
.profile-link-state.linked i {
  background: var(--green);
}
.created-col time {
  color: var(--muted);
}
.actions-col {
  width: 202px;
  text-align: right;
}
.row-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  white-space: nowrap;
}
.view-profile {
  padding-inline: 8px;
}
.action-menu {
  position: relative;
}
.more-button {
  min-height: 32px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--panel);
  color: var(--body);
  padding: 5px 9px;
  font: inherit;
  font-size: 12px;
  font-weight: 650;
}
.more-button:hover {
  border-color: var(--body);
  background: var(--soft);
}
.menu-popover {
  position: absolute;
  top: calc(100% + 5px);
  right: 0;
  z-index: 8;
  width: 168px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--panel);
  padding: 5px;
  box-shadow: var(--shadow-hover);
  text-align: left;
}
.floating-menu {
  position: fixed;
  right: auto;
  z-index: 50;
}
.menu-popover button {
  width: 100%;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--ink);
  padding: 9px 10px;
  text-align: left;
  font: inherit;
  font-size: 12px;
}
.menu-popover button:hover {
  background: var(--soft);
}
.menu-note {
  display: block;
  padding: 7px 10px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.45;
}
.account-empty {
  min-height: 220px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 7px;
  padding: 28px;
  text-align: center;
}
.account-empty strong {
  font-size: 15px;
}
.account-empty p {
  margin: 0 0 4px;
  color: var(--muted);
  font-size: 12px;
}
.table-skeleton {
  padding: 4px 18px 10px;
}
.skeleton-row {
  display: grid;
  grid-template-columns: 1.8fr 0.7fr 0.7fr 1fr;
  gap: 28px;
  align-items: center;
  min-height: 60px;
  border-bottom: 1px solid var(--line);
}
.skeleton-row i,
.profile-loading i {
  height: 12px;
  border-radius: 5px;
  background: linear-gradient(90deg, var(--track) 25%, var(--soft) 50%, var(--track) 75%);
  background-size: 200% 100%;
  animation: skeleton 1.2s linear infinite;
}
@keyframes skeleton {
  to {
    background-position: -200% 0;
  }
}
.drawer-account {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) auto;
  gap: 11px;
  align-items: center;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--line);
}
.mini-avatar.large {
  width: 42px;
  height: 42px;
}
.drawer-account div > strong,
.drawer-account div > span {
  display: block;
}
.drawer-account div > span {
  margin-top: 4px;
  color: var(--muted);
  font-size: 11px;
}
.profile-loading {
  display: grid;
  gap: 14px;
  padding: 24px 0;
}
.profile-loading i:nth-child(2) {
  width: 82%;
}
.profile-loading i:nth-child(3) {
  width: 65%;
}
.drawer-error,
.profile-empty {
  margin-top: 18px;
  border-radius: 10px;
  background: var(--soft);
  padding: 18px;
}
.drawer-error p,
.profile-empty p {
  margin: 7px 0 12px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.65;
}
.profile-empty {
  display: grid;
  justify-items: start;
}
.profile-empty > span {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  margin-bottom: 11px;
  border-radius: 50%;
  background: var(--blue2);
  color: var(--blue);
  font-weight: 800;
}
.profile-section {
  padding-top: 20px;
}
.section-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}
.section-title span {
  color: var(--muted);
  font-size: 11px;
}
.section-empty {
  margin: 5px 0 0;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.55;
}
.confirm-content {
  display: grid;
  grid-template-columns: 32px 1fr;
  gap: 11px;
  align-items: start;
  padding: 12px 0;
}
.confirm-content > span {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--blue2);
  color: var(--blue);
  font-weight: 800;
}
.confirm-content.caution > span {
  background: var(--amber2);
  color: var(--amber);
}
.confirm-content p {
  margin: 4px 0 0;
  color: var(--body);
  font-size: 13px;
  line-height: 1.65;
}
.reset-form {
  display: grid;
  gap: 10px;
  padding: 10px 0;
}
.reset-form label {
  display: grid;
  gap: 7px;
  color: var(--body);
  font-size: 13px;
  font-weight: 700;
}
.reset-form input {
  min-height: 40px;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--ink);
  padding: 8px 10px;
}
.reset-form input:focus {
  border-color: var(--blue);
  outline: 0;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--blue) 24%, transparent);
}
.reset-hint {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
}
.reset-error {
  margin: 0;
  border-radius: 7px;
  background: var(--red2);
  color: var(--red);
  padding: 9px 10px;
  font-size: 12px;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
@media (max-width: 900px) {
  .account-metrics {
    grid-template-columns: 1fr 1fr;
  }
  .account-metric:nth-child(2) {
    border-right: 0;
  }
  .account-metric:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line);
  }
  .created-col {
    display: none;
  }
}
@media (max-width: 700px) {
  .account-toolbar {
    align-items: stretch;
    flex-wrap: wrap;
  }
  .search-field {
    min-width: 100%;
  }
  .account-toolbar label:not(.search-field) {
    flex: 1;
  }
  .field {
    width: 100%;
  }
  .profile-col {
    display: none;
  }
  .accounts-table th,
  .accounts-table td {
    padding-inline: 12px;
  }
  .actions-col {
    width: 142px;
  }
  .view-profile {
    display: none;
  }
  .last-updated {
    display: none;
  }
}
@media (max-width: 480px) {
  .account-metric {
    padding: 13px;
  }
  .account-metric strong {
    font-size: 22px;
  }
  .accounts-heading {
    align-items: flex-start;
  }
  .accounts-table th:nth-child(2),
  .accounts-table td:nth-child(2) {
    display: none;
  }
  .actions-col {
    width: 86px;
  }
  .floating-menu {
    padding: 8px;
  }
  .menu-popover button {
    min-height: 44px;
  }
  .drawer-account {
    grid-template-columns: 42px 1fr;
  }
  .drawer-account > .status {
    grid-column: 2;
    justify-self: start;
  }
}
@media (prefers-reduced-motion: reduce) {
  .skeleton-row i,
  .profile-loading i {
    animation: none;
  }
}

/* 管理侧学情画像：与学习者端保持相同的信息顺序，避免复刻旧版长列表。 */
:global(.drawer) { width: min(500px, 95vw); }
:global(.drawer-head) { padding: 18px 20px 16px; background: var(--panel); }
:global(.drawer-body) { padding: 16px 18px 22px; background: var(--bg); }
.drawer-account { margin: -1px -1px 0; border: 1px solid var(--line); border-radius: 9px; background: var(--panel); padding: 13px; }
.admin-profile-overview { margin-top: 14px; border: 1px solid var(--line); border-left: 3px solid var(--blue); border-radius: 9px; background: var(--panel); padding: 15px 16px 0; }
.admin-profile-overview > span { color: var(--blue); font-size: 10px; font-weight: 750; }.admin-profile-overview h3 { margin: 4px 0 0; color: var(--ink); font-size: 17px; line-height: 1.45; }.admin-profile-overview > p { margin: 5px 0 0; color: var(--muted); font-size: 11px; }
.admin-profile-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; margin: 15px -16px 0; border-top: 1px solid var(--line); background: var(--line); }.admin-profile-stats div { display: grid; gap: 4px; min-width: 0; background: var(--panel); padding: 12px; }.admin-profile-stats span,.admin-profile-stats small { overflow: hidden; color: var(--muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.admin-profile-stats strong { color: var(--ink); font-size: 19px; line-height: 1.1; }
.profile-section { padding-top: 18px; }.profile-insight-section { padding-top: 16px; }.section-title h3 { color: var(--ink); font-size: 14px; }.section-title span { border-radius: 5px; background: var(--soft); padding: 3px 6px; }
.profile-insights { display: grid; gap: 8px; margin-top: 10px; }.profile-insights article { display: grid; gap: 3px; border-left: 3px solid var(--amber); background: var(--soft); padding: 11px 12px; }.profile-insights article.insight-strength { border-left-color: var(--green); }.profile-insights span { color: var(--muted); font-size: 10px; }.profile-insights strong { color: var(--ink); font-size: 13px; }.profile-insights p { color: var(--body); font-size: 11px; line-height: 1.55; }
.profile-focus-list { display: grid; margin-top: 9px; }.profile-focus-list article { display: grid; grid-template-columns: 23px minmax(0, 1fr) auto; align-items: center; gap: 9px; border-top: 1px solid var(--line); padding: 9px 0; }.profile-focus-list article:first-child { border-top: 0; }.profile-focus-list article > span { display: grid; width: 23px; height: 23px; place-items: center; border-radius: 6px; background: var(--soft); color: var(--muted); font-size: 10px; font-weight: 750; }.profile-focus-list div { min-width: 0; display: grid; gap: 2px; }.profile-focus-list strong { overflow: hidden; color: var(--ink); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.profile-focus-list small { color: var(--muted); font-size: 10px; }.profile-focus-list em { border-radius: 5px; padding: 3px 6px; font-size: 10px; font-style: normal; font-weight: 700; }.profile-focus-list em.high { background: var(--red2); color: var(--red); }.profile-focus-list em.mid { background: var(--amber2); color: var(--amber); }.profile-focus-list em.low { background: var(--green2); color: var(--green); }
.profile-route-list { display: grid; gap: 0; margin-top: 10px; }.profile-route-list article { position: relative; display: grid; grid-template-columns: 28px minmax(0, 1fr) auto; gap: 10px; align-items: start; padding: 0 0 13px; }.profile-route-list article:last-child { padding-bottom: 0; }.profile-route-list article:not(:last-child)::before { position: absolute; top: 24px; bottom: 0; left: 13px; width: 1px; background: var(--line); content: ''; }.profile-route-list article > span { z-index: 1; display: grid; width: 27px; height: 27px; place-items: center; border-radius: 50%; background: var(--soft); color: var(--muted); font-size: 9px; font-weight: 800; }.profile-route-list div { min-width: 0; padding-top: 2px; }.profile-route-list strong { color: var(--ink); font-size: 12px; }.profile-route-list p { margin: 3px 0 0; color: var(--muted); font-size: 11px; line-height: 1.5; }.profile-route-list em { margin-top: 3px; border-radius: 5px; background: var(--soft); color: var(--muted); padding: 3px 6px; font-size: 9px; font-style: normal; font-weight: 700; white-space: nowrap; }.profile-route-list article.route-current > span { background: var(--blue); color: #fff; }.profile-route-list article.route-current em { background: var(--blue2); color: var(--blue); }.profile-route-list article.route-completed > span { background: var(--green); color: #fff; }.profile-route-list article.route-completed em { background: var(--green2); color: var(--green); }.profile-route-list article.route-locked { opacity: .72; }
@media (max-width: 420px) { .admin-profile-stats div { padding: 10px; }.admin-profile-stats strong { font-size: 17px; }.profile-focus-list em { max-width: 72px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } }
</style>
