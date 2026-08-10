import { ref } from 'vue'

const toastMessage = ref('')
const toastVisible = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

export function useToast() {
  function showToast(msg: string) {
    toastMessage.value = msg
    toastVisible.value = true
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      toastVisible.value = false
    }, 2600)
  }
  return { toastMessage, toastVisible, showToast }
}
