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
  { path: '/review', component: () => import('@/pages/ManualReviewPage.vue') },
  { path: '/agents', redirect: '/metrics' },
  { path: '/diagnostics', redirect: '/diagnostic' },
  { path: '/domain', redirect: { path: '/domain-hub', query: { tab: 'config' } } },
  { path: '/knowledge', redirect: { path: '/domain-hub', query: { tab: 'knowledge' } } },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
