<template>
  <main class="login-page">
    <section class="login-intro" aria-labelledby="product-title">
      <div class="brand-lockup">
        <span class="brand-mark" aria-hidden="true">云</span>
        <span>云川智汇</span>
      </div>

      <div class="intro-copy">
        <h1 id="product-title">让每一次学习，<br />都有可追溯的下一步。</h1>
        <p class="intro-summary">从诊断、知识检索到资源审核与反馈调整，为学习者生成可解释的实训路径。</p>
      </div>
    </section>

    <section class="login-panel" :aria-label="isRegister ? '注册账号' : '账号登录'">
      <div class="auth-switch" role="tablist" aria-label="认证方式">
        <button type="button" role="tab" :aria-selected="!isRegister" :class="{ active: !isRegister }" @click="setMode(false)">登录</button>
        <button type="button" role="tab" :aria-selected="isRegister" :class="{ active: isRegister }" @click="setMode(true)">注册</button>
      </div>

      <form class="login-form" @submit.prevent="submit">
        <div class="form-heading">
          <p class="form-kicker">{{ isRegister ? '开始实训' : '欢迎回来' }}</p>
          <h2>{{ isRegister ? '创建学习账号' : '登录工作区' }}</h2>
          <p>{{ isRegister ? '填写基本信息后，即可建立个人实训档案。' : '使用您的账号继续本次实训。' }}</p>
        </div>

        <label class="field-label" for="username">用户名
          <input id="username" v-model.trim="username" autocomplete="username" required minlength="3" maxlength="32" pattern="[A-Za-z0-9_]{3,32}" placeholder="3 至 32 位字母、数字或下划线" />
        </label>
        <label v-if="isRegister" class="field-label" for="display-name">显示名称
          <input id="display-name" v-model.trim="displayName" autocomplete="name" required placeholder="在学习报告中显示的名称" />
        </label>
        <label class="field-label" for="password">密码
          <input id="password" v-model="password" type="password" :autocomplete="isRegister ? 'new-password' : 'current-password'" required minlength="8" maxlength="72" :placeholder="isRegister ? '至少 8 位密码' : '请输入密码'" />
        </label>

        <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
        <button class="submit-button" :disabled="loading" type="submit">
          <span>{{ loading ? (isRegister ? '正在创建账号…' : '正在验证身份…') : (isRegister ? '创建账号并进入实训' : '登录并进入工作区') }}</span>
          <span v-if="!loading" aria-hidden="true">→</span>
        </button>
        <p class="register-link">
          {{ isRegister ? '已有学习账号？' : '还没有学习账号？' }}
          <button type="button" @click="setMode(!isRegister)">{{ isRegister ? '返回登录' : '创建账号' }}</button>
        </p>
      </form>

      <p class="security-note"><span aria-hidden="true">✓</span> 登录后将按学习者或管理员角色进入对应工作区</p>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)
const store = useAuthStore()
const router = useRouter()
const route = useRoute()
const displayName = ref('')
const isRegister = computed(() => route.path === '/register')

watch(() => route.path, () => { error.value = '' })

function setMode(register: boolean) {
  error.value = ''
  router.push(register ? '/register' : '/login')
}

async function submit() {
  loading.value = true
  error.value = ''
  try {
    if (isRegister.value) await store.register(username.value, password.value, displayName.value)
    else await store.login(username.value, password.value)
    await router.push(String(route.query.redirect || '/dashboard'))
  } catch (caught: any) {
    error.value = isRegister.value ? caught.response?.data?.error?.message || '注册失败，请检查填写的信息。' : '用户名或密码错误，请检查后重试。'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  --auth-ink: #172746;
  --auth-muted: #61718a;
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(420px, 0.85fr);
  background: #f7f9fc;
}

.login-intro {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: clamp(32px, 6vw, 72px);
  color: #f8fbff;
  background: #162b55;
}

.brand-lockup { display: flex; align-items: center; gap: 10px; font-size: 16px; font-weight: 760; letter-spacing: .01em; }
.brand-mark { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 9px; background: #7da7ff; color: #10254b; font-size: 11px; letter-spacing: 0; }
.intro-copy { max-width: 620px; margin: auto 0; padding: 64px 0; }
.form-kicker { margin: 0 0 12px; color: #a8c1ff; font-size: 13px; font-weight: 700; }
.intro-copy h1 { max-width: 590px; margin: 0; font-size: clamp(36px, 4.1vw, 60px); line-height: 1.17; letter-spacing: -.035em; text-wrap: balance; }
.intro-summary { max-width: 500px; margin: 24px 0 0; color: #c3d0e9; font-size: 16px; line-height: 1.8; }

.login-panel { min-height: 100vh; display: flex; flex-direction: column; justify-content: center; padding: clamp(28px, 7vw, 88px); background: #fff; }
.auth-switch { width: min(100%, 380px); display: grid; grid-template-columns: 1fr 1fr; gap: 4px; margin: 0 auto 28px; border-radius: 9px; background: #f1f4f8; padding: 4px; }
.auth-switch button { min-height: 36px; border: 0; border-radius: 6px; background: transparent; color: #61718a; font-size: 13px; font-weight: 700; transition: background 180ms ease, color 180ms ease, box-shadow 180ms ease; }
.auth-switch button.active { background: #fff; color: #172746; box-shadow: 0 1px 3px rgb(31 48 75 / .12); }
.login-form { width: min(100%, 380px); margin: auto; display: grid; gap: 18px; }
.form-heading { margin-bottom: 12px; }
.form-kicker { color: #315fce; }
.form-heading h2 { margin: 0; color: var(--auth-ink); font-size: 30px; line-height: 1.25; letter-spacing: -.025em; }
.form-heading > p:last-child { margin: 10px 0 0; color: var(--auth-muted); font-size: 14px; line-height: 1.65; }
.field-label { display: grid; gap: 8px; color: #344762; font-size: 13px; font-weight: 700; }
.field-label input { width: 100%; height: 46px; border: 1px solid #cbd6e4; border-radius: 8px; background: #fff; color: var(--auth-ink); padding: 0 13px; font-size: 15px; outline: 0; transition: border-color 180ms ease, box-shadow 180ms ease, background 180ms ease; }
.field-label input::placeholder { color: #718096; opacity: 1; }
.field-label input:hover { border-color: #9eafc6; }
.field-label input:focus { border-color: #315fce; background: #fbfcff; box-shadow: 0 0 0 3px rgb(49 95 206 / .16); }
.auth-error { margin: -2px 0 0; border-radius: 8px; background: #fff1f1; color: #ae3030; padding: 10px 12px; font-size: 13px; line-height: 1.45; }
.submit-button { min-height: 48px; display: flex; align-items: center; justify-content: space-between; border: 0; border-radius: 8px; background: #315fce; color: #fff; padding: 0 16px; font-size: 15px; font-weight: 720; transition: background 180ms ease, transform 180ms ease, box-shadow 180ms ease; }
.submit-button:hover:not(:disabled) { background: #274fae; box-shadow: 0 4px 8px rgb(39 79 174 / .22); transform: translateY(-1px); }
.submit-button:disabled { cursor: wait; background: #7896d9; }
.register-link { margin: 2px 0 0; color: var(--auth-muted); font-size: 13px; text-align: center; }
.register-link button { border: 0; background: transparent; color: #315fce; padding: 0; font: inherit; font-weight: 700; text-decoration: underline; text-underline-offset: 3px; }
.security-note { width: min(100%, 380px); margin: 40px auto 0; color: #6b7b91; font-size: 12px; line-height: 1.55; }
.security-note span { margin-right: 5px; color: #138a63; font-weight: 800; }

@media (max-width: 820px) {
  .login-page { grid-template-columns: 1fr; }
  .login-intro { min-height: auto; padding: 26px 24px 28px; }
  .intro-copy { margin: 38px 0 34px; padding: 0; }
  .intro-copy h1 { font-size: 34px; }
  .intro-summary { margin-top: 14px; font-size: 14px; }
  .login-panel { min-height: auto; padding: 38px 24px 32px; }
  .auth-switch { margin-bottom: 24px; }
  .login-form { margin: 0 auto; }
}

@media (max-width: 420px) { .login-intro, .login-panel { padding-left: 20px; padding-right: 20px; } .intro-copy h1 { font-size: 30px; } }
@media (prefers-reduced-motion: reduce) { .field-label input, .submit-button { transition: none; } }
</style>
