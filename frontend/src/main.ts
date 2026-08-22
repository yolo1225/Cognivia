import '@vue-flow/core/dist/style.css'
import './assets/global.css'

import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import { router } from './router'

try {
  document.documentElement.classList.toggle('theme-dark', window.localStorage.getItem('cognivia.dark-mode') === 'true')
} catch {
  // Use the default light theme when browser storage is unavailable.
}

createApp(App).use(createPinia()).use(router).mount('#app')
