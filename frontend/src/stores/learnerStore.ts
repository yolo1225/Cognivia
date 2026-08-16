import { defineStore } from 'pinia'

const STORAGE_KEY = 'domainmind:selectedLearnerId'
function validLearnerId(value: unknown): string | null {
  const normalized = typeof value === 'string' ? value.trim() : ''
  return normalized && !['null', 'undefined'].includes(normalized.toLowerCase()) ? normalized : null
}
export const useLearnerStore = defineStore('learner', {
  state: () => ({ selectedLearnerId: null as string | null }),
  actions: {
    bindIdentity(_role: string, learnerId: string | null) {
      const ownLearner = validLearnerId(learnerId)
      this.selectedLearnerId = ownLearner
      localStorage.removeItem(STORAGE_KEY)
    },
    setSelectedLearner(learnerId: string) {
      this.selectedLearnerId = validLearnerId(learnerId)
      if (this.selectedLearnerId) localStorage.setItem(STORAGE_KEY, this.selectedLearnerId)
      else localStorage.removeItem(STORAGE_KEY)
    },
    clear(){ this.selectedLearnerId=null },
  },
})
