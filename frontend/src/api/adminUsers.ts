import { getData, patchData, postData } from './client'
export interface AdminUser { user_id:string; username:string; display_name:string; role:'learner'|'admin'; status:'active'|'disabled'; learner_id:string|null; created_at:string }
export const listUsers=()=>getData<AdminUser[]>('/admin/users')
export const setUserStatus=(id:string,status:'active'|'disabled')=>patchData<AdminUser>(`/admin/users/${id}/status`,{status})
export const resetPassword=(id:string,password:string)=>postData(`/admin/users/${id}/reset-password`,{password})
export const revokeSessions=(id:string)=>postData(`/admin/users/${id}/revoke-sessions`)
