import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'

const admin = { requiresAuth:true, roles:['admin'] }
const auth = { requiresAuth:true }
const routes = [
  { path:'/login', component:()=>import('@/pages/LoginPage.vue'), meta:{ guest:true } },
  { path:'/register', component:()=>import('@/pages/LoginPage.vue'), meta:{ guest:true } },
  { path:'/', redirect:'/dashboard' },
  { path:'/dashboard', component:()=>import('@/pages/DashboardPage.vue'), meta:auth },
  { path:'/diagnostic', component:()=>import('@/pages/DiagnosticPage.vue'), meta:auth },
  { path:'/resources', component:()=>import('@/pages/ResourcePage.vue'), meta:auth },
  { path:'/report', component:()=>import('@/pages/ReportPage.vue'), meta:auth },
  { path:'/metrics', component:()=>import('@/pages/MetricsPage.vue'), meta:auth },
  { path:'/learners', component:()=>import('@/pages/LearnersPage.vue'), meta:admin },
  { path:'/domain-hub', component:()=>import('@/pages/DomainHubPage.vue'), meta:admin },
  { path:'/review', component:()=>import('@/pages/ManualReviewPage.vue'), meta:admin },
  { path:'/:pathMatch(.*)*', redirect:'/dashboard' },
]
export const router=createRouter({history:createWebHistory(),routes})
router.beforeEach(async to=>{
  const store=useAuthStore(); if(!store.initialized) await store.restore()
  if(to.meta.requiresAuth && !store.isAuthenticated) return {path:'/login',query:{redirect:to.fullPath}}
  if(to.meta.guest && store.isAuthenticated) return '/dashboard'
  if(Array.isArray(to.meta.roles) && !to.meta.roles.includes(store.role)) return '/dashboard'
})
