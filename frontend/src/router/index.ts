import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: () => import('@/pages/DashboardPage.vue') },
  { path: '/diagnostic', component: () => import('@/pages/DiagnosticPage.vue') },
  { path: '/resources', component: () => import('@/pages/ResourcePage.vue') },
  { path: '/report', component: () => import('@/pages/ReportPage.vue') },
  { path: '/metrics', component: () => import('@/pages/MetricsPage.vue') },
  { path: '/learners', component: () => import('@/pages/LearnersPage.vue') },
  { path: '/domain-hub', component: () => import('@/pages/DomainHubPage.vue') },
  { path: '/knowledge', component: () => import('@/pages/KnowledgeAdminPage.vue') },
  { path: '/domain', component: () => import('@/pages/DomainConfigPage.vue') },
  { path: '/review', component: () => import('@/pages/ManualReviewPage.vue') },
  { path: '/agents', component: () => import('@/pages/AgentWorkspacePage.vue') },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
