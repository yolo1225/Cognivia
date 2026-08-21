import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { getLearnerProfile } from '@/api/learners'

const admin = { requiresAuth:true, roles:['admin'] }
const auth = { requiresAuth:true }
const routes = [
  { path:'/login', component:()=>import('@/pages/LoginPage.vue'), meta:{ guest:true } },
  { path:'/register', component:()=>import('@/pages/LoginPage.vue'), meta:{ guest:true } },
  { path:'/', redirect:'/dashboard' },
  { path:'/dashboard', component:()=>import('@/pages/DashboardPage.vue'), meta:auth },
  { path:'/diagnostic', redirect:'/dashboard', meta:auth },
  { path:'/resources', component:()=>import('@/pages/ResourcePage.vue'), meta:auth },
  { path:'/report', component:()=>import('@/pages/ReportPage.vue'), meta:auth },
  { path:'/metrics', component:()=>import('@/pages/MetricsPage.vue'), meta:auth },
  { path:'/learners', component:()=>import('@/pages/LearnersPage.vue'), meta:admin },
  { path:'/domain-hub', component:()=>import('@/pages/DomainHubPage.vue'), meta:admin },
  { path:'/model-settings', component:()=>import('@/pages/ModelSettingsPage.vue'), meta:admin },
  { path:'/:pathMatch(.*)*', redirect:'/dashboard' },
]
export const router=createRouter({history:createWebHistory(),routes})
router.beforeEach(async to=>{
  const store=useAuthStore(); if(!store.initialized) await store.restore()
  if(to.meta.requiresAuth && !store.isAuthenticated) return {path:'/login',query:{redirect:to.fullPath}}
  if(to.meta.guest && store.isAuthenticated) return '/dashboard'
  if(Array.isArray(to.meta.roles) && !to.meta.roles.includes(store.role)) return '/dashboard'
  if (store.role === 'learner' && ['/resources', '/report', '/metrics'].includes(to.path) && store.user?.learner_id) {
    try {
      const profile = await getLearnerProfile(store.user.learner_id)
      if (profile.profile_status !== 'ready') return '/dashboard'
    } catch {
      // Preserve the destination when profile status cannot be read; the page renders its normal error state.
    }
  }
})
