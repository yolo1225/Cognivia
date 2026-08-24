import { defineStore } from 'pinia'
import { apiClient } from '@/api/client'
import { useToast } from '@/composables/useToast'
import { useLearnerStore } from '@/stores/learnerStore'

export interface AuthUser { user_id:string; username:string; display_name:string; role:'learner'|'admin'; learner_id:string|null }

export const useAuthStore = defineStore('auth', {
  state: () => ({ user: null as AuthUser|null, initialized:false }),
  getters: { userId: s => s.user?.display_name || '', role: s => s.user?.role || '', isAuthenticated: s => !!s.user },
  actions: {
    syncLearner(){ useLearnerStore().bindIdentity(this.user?.role||'',this.user?.learner_id||null) },
    async restore(){ try { this.user=(await apiClient.get('/auth/me')).data.data; this.syncLearner() } catch { this.user=null; useLearnerStore().clear(); useToast().clearNotifications() } finally { this.initialized=true } },
    async login(username:string,password:string){ useToast().clearNotifications(); this.user=(await apiClient.post('/auth/login',{username,password})).data.data; this.syncLearner(); this.initialized=true },
    async register(username:string,password:string,display_name:string){ useToast().clearNotifications(); this.user=(await apiClient.post('/auth/register',{username,password,display_name})).data.data; this.syncLearner(); this.initialized=true },
    async logout(){ try { await apiClient.post('/auth/logout') } finally { this.user=null; useLearnerStore().clear(); useToast().clearNotifications() } },
  },
})
