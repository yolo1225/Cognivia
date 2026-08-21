import { describe, expect, it } from 'vitest'
import type { AdminUser } from '@/api/adminUsers'
import { filterAndSortAdminUsers, roleLabel, statusLabel } from './adminUsersState'

const users: AdminUser[] = [
  { user_id: '2', username: 'zhangsan', display_name: '张三', role: 'learner', status: 'active', learner_id: 'l-2', created_at: '2026-08-01T00:00:00Z' },
  { user_id: '1', username: 'admin', display_name: '系统管理员', role: 'admin', status: 'active', learner_id: null, created_at: '2026-07-01T00:00:00Z' },
  { user_id: '3', username: 'lisi', display_name: '李四', role: 'learner', status: 'disabled', learner_id: null, created_at: '2026-08-02T00:00:00Z' },
]

describe('admin user list state', () => {
  it('keeps administrators first and sorts the remaining users by name', () => {
    const result = filterAndSortAdminUsers(users, { keyword: '', role: 'all', status: 'all' })
    expect(result.map(user => user.user_id)).toEqual(['1', '3', '2'])
  })

  it('searches display names and usernames without case sensitivity', () => {
    expect(filterAndSortAdminUsers(users, { keyword: 'ZHANG', role: 'all', status: 'all' }).map(user => user.user_id)).toEqual(['2'])
    expect(filterAndSortAdminUsers(users, { keyword: '李四', role: 'all', status: 'all' }).map(user => user.user_id)).toEqual(['3'])
  })

  it('combines role and status filters', () => {
    expect(filterAndSortAdminUsers(users, { keyword: '', role: 'learner', status: 'disabled' }).map(user => user.user_id)).toEqual(['3'])
  })

  it('maps roles and statuses to readable Chinese labels', () => {
    expect(roleLabel('admin')).toBe('管理员')
    expect(roleLabel('learner')).toBe('普通用户')
    expect(statusLabel('active')).toBe('正常')
    expect(statusLabel('disabled')).toBe('已禁用')
  })
})
