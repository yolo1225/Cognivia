import { defineStore } from 'pinia'

import {
  getDomainReadiness,
  listDomains,
  type DomainSummary,
  type DomainValidationResult,
} from '@/api/domains'
import { updateTargetDomain } from '@/api/learners'
import { useTaskStore } from '@/stores/taskStore'

export const useDomainStore = defineStore('domain', {
  state: () => ({
    currentDomainCode: '',
    currentDomainName: '',
    domains: [] as DomainSummary[],
    loading: false,
    error: '',
    readiness: null as DomainValidationResult | null,
    selectionVersion: 0,
  }),
  actions: {
    async loadAvailable() {
      this.loading = true
      this.error = ''
      try {
        this.domains = await listDomains()
        return this.domains
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'DOMAIN_LOAD_FAILED'
        throw error
      } finally {
        this.loading = false
      }
    },
    async initialize(targetDomain: string) {
      await this.loadAvailable()
      if (!targetDomain) {
        this.setWorkspaceDomain('')
        return
      }
      const selected = this.domains.find(item => item.domain_code === targetDomain)
      if (!selected) {
        this.setWorkspaceDomain('')
        throw new Error('LEARNER_DOMAIN_NOT_CONFIGURED')
      }
      this.setWorkspaceDomain(selected.domain_code)
    },
    setWorkspaceDomain(domainCode: string) {
      const selected = this.domains.find(item => item.domain_code === domainCode)
      const nextCode = selected?.domain_code || ''
      const changed = this.currentDomainCode !== nextCode
      this.currentDomainCode = nextCode
      this.currentDomainName = selected?.name || ''
      this.readiness = null
      if (changed) this.selectionVersion += 1
    },
    async loadReadiness(domainCode?: string) {
      const selectedDomain = domainCode || this.currentDomainCode
      if (!selectedDomain) return null
      this.readiness = await getDomainReadiness(selectedDomain)
      return this.readiness
    },
    async selectForLearner(learnerId: string, domainCode: string) {
      const selected = this.domains.find(item => item.domain_code === domainCode)
      if (!selected || selected.status !== 'ready') throw new Error('DOMAIN_NOT_READY')
      await updateTargetDomain(learnerId, domainCode)
      this.setWorkspaceDomain(domainCode)
      useTaskStore().clearTask()
    },
  },
})
