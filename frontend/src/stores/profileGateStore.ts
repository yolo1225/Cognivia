import { defineStore } from 'pinia'
import { getLearnerProfile } from '@/api/learners'

export const useProfileGateStore = defineStore('profileGate', {
  state: () => ({ learnerId: '', ready: false, loading: false }),
  actions: {
    async refresh(learnerId: string) {
      if (!learnerId) {
        this.learnerId = ''
        this.ready = false
        return false
      }
      this.loading = true
      try {
        const detail = await getLearnerProfile(learnerId)
        this.learnerId = learnerId
        this.ready = detail.profile_status === 'ready'
        return this.ready
      } catch {
        return false
      } finally {
        this.loading = false
      }
    },
    clear() {
      this.learnerId = ''
      this.ready = false
      this.loading = false
    },
  },
})
