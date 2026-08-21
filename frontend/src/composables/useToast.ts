import { ref } from 'vue'

export type ToastType = 'info' | 'success' | 'error'

export interface NotificationItem {
  id: number
  message: string
  type: ToastType
  createdAt: number
  read: boolean
}

const toastMessage = ref('')
const toastType = ref<ToastType>('info')
const toastVisible = ref(false)
const notifications = ref<NotificationItem[]>([])
let notificationId = 0
let timer: ReturnType<typeof setTimeout> | null = null

export function useToast() {
  function showToast(msg: string, type: ToastType = 'info') {
    toastMessage.value = msg
    toastType.value = type
    toastVisible.value = true
    notifications.value.unshift({ id: ++notificationId, message: msg, type, createdAt: Date.now(), read: false })
    notifications.value = notifications.value.slice(0, 20)
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      toastVisible.value = false
    }, 2600)
  }
  function closeToast() {
    if (timer) clearTimeout(timer)
    toastVisible.value = false
  }

  function markAllNotificationsRead() {
    notifications.value.forEach(notification => { notification.read = true })
  }

  function clearNotifications() {
    notifications.value = []
    closeToast()
  }

  return { toastMessage, toastType, toastVisible, notifications, showToast, closeToast, markAllNotificationsRead, clearNotifications }
}
