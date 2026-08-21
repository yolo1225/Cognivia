import type { AdminUser } from '@/api/adminUsers'

export type AdminUserFilters = {
  keyword: string
  role: 'all' | AdminUser['role']
  status: 'all' | AdminUser['status']
}

export function roleLabel(role: AdminUser['role']) {
  return role === 'admin' ? '管理员' : '普通用户'
}

export function statusLabel(status: AdminUser['status']) {
  return status === 'active' ? '正常' : '已禁用'
}

export function filterAndSortAdminUsers(users: AdminUser[], filters: AdminUserFilters) {
  const keyword = filters.keyword.trim().toLocaleLowerCase('zh-CN')
  return users
    .filter((user) => {
      const matchesKeyword = !keyword || `${user.display_name || ''} ${user.username || ''}`.toLocaleLowerCase('zh-CN').includes(keyword)
      return matchesKeyword && (filters.role === 'all' || user.role === filters.role) && (filters.status === 'all' || user.status === filters.status)
    })
    .sort((left, right) => Number(right.role === 'admin') - Number(left.role === 'admin') || (left.display_name || left.username || '').localeCompare(right.display_name || right.username || '', 'zh-CN'))
}
