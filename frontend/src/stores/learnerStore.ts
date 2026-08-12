import { defineStore } from 'pinia'

const STORAGE_KEY = 'domainmind:selectedLearnerId'
export const useLearnerStore = defineStore('learner', {
  state: () => ({ selectedLearnerId: null as string | null }),
  actions: {
    bindIdentity(role: string, learnerId: string | null) {
      if (role === 'learner') { this.selectedLearnerId = learnerId; localStorage.removeItem(STORAGE_KEY); return }
      this.selectedLearnerId = localStorage.getItem(STORAGE_KEY)
    },
    setSelectedLearner(learnerId: string) {
      this.selectedLearnerId = learnerId.trim() || null
      if (this.selectedLearnerId) localStorage.setItem(STORAGE_KEY, this.selectedLearnerId)
    },
    clear(){ this.selectedLearnerId=null },
  },
})
