import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { getLearnerProfile } from '@/api/learners'

const admin = { requiresAuth:true, roles:['admin'] }
const auth = { requiresAuth:true }
const routes = [
  { path:'/login', component:()=>import('@/pages/LoginPage.vue'), meta:{ guest:true, title:'登录' } },
  { path:'/register', component:()=>import('@/pages/LoginPage.vue'), meta:{ guest:true, title:'注册' } },
  { path:'/', component:()=>import('@/pages/LandingPage.vue'), meta:{ guest:true, title:'首页' } },
  { path:'/dashboard', component:()=>import('@/pages/DashboardPage.vue'), meta:{ ...auth, title:'首页' } },
  { path:'/diagnostic', redirect:'/dashboard', meta:{ ...auth, title:'诊断训练' } },
  { path:'/resources', component:()=>import('@/pages/ResourcePage.vue'), meta:{ ...auth, title:'学习资源' } },
  { path:'/mistake-review', component:()=>import('@/pages/MistakeReviewPage.vue'), meta:{ ...auth, title:'错题巩固' } },
  { path:'/report', component:()=>import('@/pages/ReportPage.vue'), meta:{ ...auth, title:'学情画像' } },
  { path:'/metrics', component:()=>import('@/pages/MetricsPage.vue'), meta:{ ...auth, title:'学习历程' } },
  { path:'/learners', component:()=>import('@/pages/LearnersPage.vue'), meta:{ ...admin, title:'用户管理' } },
  { path:'/domain-hub', component:()=>import('@/pages/DomainHubPage.vue'), meta:{ ...admin, title:'领域管理' } },
  { path:'/model-settings', component:()=>import('@/pages/ModelSettingsPage.vue'), meta:{ ...admin, title:'模型配置' } },
  { path:'/:pathMatch(.*)*', redirect:'/dashboard' },
]
export const router=createRouter({
  history:createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})
router.beforeEach(async to=>{
  const store=useAuthStore(); if(!store.initialized) await store.restore()
  if(to.meta.requiresAuth && !store.isAuthenticated) return {path:'/login',query:{redirect:to.fullPath}}
  if(to.meta.guest && store.isAuthenticated) return '/dashboard'
  if(Array.isArray(to.meta.roles) && !to.meta.roles.includes(store.role)) return '/dashboard'
  if (store.role === 'learner' && ['/resources', '/mistake-review', '/report', '/metrics'].includes(to.path) && store.user?.learner_id) {
    try {
      const profile = await getLearnerProfile(store.user.learner_id)
      if (profile.profile_status !== 'ready') return '/dashboard'
    } catch {
      // Preserve the destination when profile status cannot be read; the page renders its normal error state.
    }
  }
})
router.afterEach((to) => {
  document.title = `${String(to.meta.title || '工作区')} · 云川智汇`
})
