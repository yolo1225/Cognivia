<template>
  <header class="top">
    <div>
      <strong class="workspace-name">个性化实训工作区</strong>
      <span class="sep"></span>
      <span class="crumb">{{ pageLabel }}</span>
    </div>

    <div ref="headerActions" class="header-actions">
      <div class="context notification-menu">
        <button class="top-icon-button" type="button" title="查看消息" :aria-expanded="notificationOpen" aria-haspopup="dialog" @click="toggleNotifications">
          <AppIcon name="bell" />
          <span v-if="unreadCount" class="notification-badge" aria-label="有未读消息"></span>
        </button>
        <section v-if="notificationOpen" class="notification-dropdown" role="dialog" aria-label="消息中心" @keydown.esc="notificationOpen = false">
          <header class="dropdown-heading">
            <div><strong>消息中心</strong><span>{{ notifications.length ? `${notifications.length} 条最新消息` : '暂无新消息' }}</span></div>
            <button v-if="unreadCount" type="button" @click="markAllNotificationsRead">全部已读</button>
          </header>
          <div v-if="notifications.length" class="notification-list">
            <article v-for="item in notifications" :key="item.id" class="notification-item" :class="[`is-${item.type}`, { unread: !item.read }]">
              <span class="notification-state" aria-hidden="true">{{ notificationIcon(item.type) }}</span>
              <div><strong>{{ notificationTitle(item.type) }}</strong><p>{{ item.message }}</p><time>{{ notificationTime(item.createdAt) }}</time></div>
            </article>
          </div>
          <div v-else class="notification-empty"><AppIcon name="bell" /><p>新的操作反馈会显示在这里。</p></div>
        </section>
      </div>

      <div class="context account-menu">
        <button class="top-profile" type="button" :title="`${authStore.userId}，打开账户菜单`" :aria-expanded="menuOpen" aria-haspopup="menu" @click="menuOpen = !menuOpen">
          <span class="top-avatar">{{ authStore.userId.charAt(0) }}</span>
          <span class="profile-meta"><strong>{{ authStore.userId }}</strong><small>{{ authStore.role === 'admin' ? '管理员' : '学习者' }}</small></span>
          <span class="profile-chevron" aria-hidden="true">⌄</span>
        </button>
        <div v-if="menuOpen" class="account-dropdown" role="menu" @keydown.esc="menuOpen = false">
          <div class="account-summary">
            <strong>{{ authStore.userId }}</strong>
            <span>{{ authStore.role === 'admin' ? '管理员' : '学习者' }}</span>
          </div>
          <button type="button" role="menuitem" class="menu-item" @click="goTo('/dashboard')">我的工作台</button>
          <button v-if="authStore.role === 'learner'" type="button" role="menuitem" class="menu-item" @click="goTo('/report')">学习报告</button>
          <button v-else type="button" role="menuitem" class="menu-item" @click="goTo('/learners')">用户管理</button>
          <button type="button" role="menuitem" class="menu-item" @click="openNotifications">消息中心</button>
          <div class="menu-divider"></div>
          <button type="button" role="menuitem" class="logout" @click="logout">退出登录</button>
        </div>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/Shared/AppIcon.vue'
import { type ToastType, useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/authStore'

const route = useRoute()
const authStore = useAuthStore()
const router = useRouter()
const menuOpen = ref(false)
const notificationOpen = ref(false)
const headerActions = ref<HTMLElement | null>(null)
const { notifications, markAllNotificationsRead, clearNotifications } = useToast()
const unreadCount = computed(() => notifications.value.filter(item => !item.read).length)

watch(() => authStore.user?.user_id, clearNotifications, { immediate: true })

function closeOnOutsideClick(event: MouseEvent) {
  if (headerActions.value && !headerActions.value.contains(event.target as Node)) {
    menuOpen.value = false
    notificationOpen.value = false
  }
}

onMounted(() => document.addEventListener('click', closeOnOutsideClick))
onBeforeUnmount(() => document.removeEventListener('click', closeOnOutsideClick))

async function logout() {
  menuOpen.value = false
  await authStore.logout()
  await router.push('/login')
}

function goTo(path: string) {
  menuOpen.value = false
  void router.push(path)
}

function openNotifications() {
  menuOpen.value = false
  notificationOpen.value = true
  markAllNotificationsRead()
}

function toggleNotifications() {
  notificationOpen.value = !notificationOpen.value
  if (notificationOpen.value) markAllNotificationsRead()
}

function notificationIcon(type: ToastType) {
  return ({ info: 'i', success: '✓', error: '!' } as Record<ToastType, string>)[type]
}

function notificationTitle(type: ToastType) {
  return ({ info: '系统提示', success: '操作完成', error: '需要处理' } as Record<ToastType, string>)[type]
}

function notificationTime(createdAt: number) {
  const minutes = Math.floor((Date.now() - createdAt) / 60000)
  return minutes < 1 ? '刚刚' : `${minutes} 分钟前`
}

const labels: Record<string, string> = {
  '/dashboard': '首页',
  '/resources': '学习资源',
  '/report': '学习报告',
  '/metrics': '任务记录',
  '/learners': '用户管理',
  '/domain-hub': '领域管理',
  '/model-settings': '模型配置',
  '/review': '人工复核',
}

const pageLabel = computed(() => labels[route.path] || '工作区')
</script>

<style scoped>
.header-actions { display: flex; align-items: center; gap: 5px; }
.account-menu, .notification-menu { position: relative; }
.top-icon-button { position: relative; width: 36px; height: 36px; display: grid; place-items: center; border: 0; border-radius: 9px; background: transparent; color: var(--muted); font-size: 18px; transition: background var(--transition-fast), color var(--transition-fast); }
.top-icon-button:hover { background: var(--soft); color: var(--blue); }
.notification-badge { position: absolute; top: 7px; right: 7px; width: 6px; height: 6px; border-radius: 50%; background: var(--red); box-shadow: 0 0 0 2px #fff; }
.top-profile { display: flex; align-items: center; gap: 8px; min-height: 42px; border: 0; border-radius: 10px; background: transparent; padding: 4px 7px 4px 5px; color: var(--ink); text-align: left; transition: background var(--transition-fast); }
.top-profile:hover { background: var(--soft); }
.top-profile .top-avatar { width: 32px; height: 32px; min-height: 32px; flex: 0 0 auto; border-radius: 9px; background: var(--blue2); color: var(--blue); font-size: 13px; }
.profile-meta { display: grid; gap: 1px; min-width: 0; }
.profile-meta strong { max-width: 112px; overflow: hidden; font-size: 12px; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.profile-meta small { color: var(--muted); font-size: 10px; line-height: 1.35; }
.profile-chevron { color: var(--muted); font-size: 16px; line-height: 1; transform: translateY(-2px); }
.account-dropdown, .notification-dropdown { position: absolute; top: calc(100% + 12px); right: 0; z-index: 10; overflow: hidden; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); box-shadow: 0 8px 14px rgb(22 35 55 / .12); }
.account-dropdown { width: 236px; }
.notification-dropdown { width: min(368px, calc(100vw - 32px)); }
.account-summary { display: grid; gap: 4px; padding: 16px; background: var(--soft); }
.account-summary strong { overflow: hidden; color: var(--ink); font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.account-summary span { color: var(--muted); font-size: 11px; }
.menu-item, .logout { width: 100%; border: 0; background: var(--panel); color: var(--body); padding: 10px 16px; text-align: left; font-size: 13px; transition: background var(--transition-fast), color var(--transition-fast); }
.menu-item:hover { background: var(--blue2); color: var(--blue); }
.menu-divider { height: 1px; margin: 5px 12px; background: var(--line); }
.logout { color: var(--red); }
.logout:hover { background: var(--red2); color: var(--red); }
.dropdown-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 15px 16px 12px; }
.dropdown-heading div { display: grid; gap: 4px; }
.dropdown-heading strong { color: var(--ink); font-size: 14px; }
.dropdown-heading span { color: var(--muted); font-size: 11px; }
.dropdown-heading button { border: 0; border-radius: 6px; background: transparent; color: var(--blue); padding: 5px 6px; font-size: 11px; transition: background var(--transition-fast); }
.dropdown-heading button:hover { background: var(--blue2); }
.notification-list { max-height: 342px; overflow-y: auto; padding: 0 8px 8px; }
.notification-item { display: grid; grid-template-columns: 26px minmax(0, 1fr); gap: 10px; border-radius: 9px; padding: 11px 8px; }
.notification-item + .notification-item { margin-top: 2px; }
.notification-item.unread { background: var(--blue2); }
.notification-state { width: 26px; height: 26px; display: grid; place-items: center; border-radius: 8px; background: var(--info2); color: var(--info); font-size: 12px; font-weight: 800; }
.notification-item.is-success .notification-state { background: var(--green2); color: var(--green); }
.notification-item.is-error .notification-state { background: var(--red2); color: var(--red); }
.notification-item div { min-width: 0; }
.notification-item strong { display: block; color: var(--ink); font-size: 12px; }
.notification-item p { margin: 3px 0 0; color: var(--body); font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.notification-item time { display: block; margin-top: 4px; color: var(--muted); font-size: 10px; }
.notification-empty { display: grid; justify-items: center; gap: 8px; padding: 36px 20px; color: var(--muted); text-align: center; }
.notification-empty :deep(.app-icon) { color: #9caac0; font-size: 24px; }
.notification-empty p { margin: 0; font-size: 12px; }
@media (max-width: 640px) { .profile-meta, .profile-chevron { display: none; } .top-profile { padding: 4px; } }
@media (max-width: 640px) { .notification-dropdown { position: fixed; top: 68px; right: 16px; } }
</style>
