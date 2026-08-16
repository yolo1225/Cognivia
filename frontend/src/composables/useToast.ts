import { ref } from 'vue'

export type ToastType = 'info' | 'success' | 'error'

const toastMessage = ref('')
const toastType = ref<ToastType>('info')
const toastVisible = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

export function useToast() {
  function showToast(msg: string, type: ToastType = 'info') {
    toastMessage.value = msg
    toastType.value = type
    toastVisible.value = true
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      toastVisible.value = false
    }, 2600)
  }
  return { toastMessage, toastType, toastVisible, showToast }
}
