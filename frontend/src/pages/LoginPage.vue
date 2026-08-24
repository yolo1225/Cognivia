<template>
  <main class="login-page">
    <section class="login-intro" aria-labelledby="product-title">
      <div class="decor" aria-hidden="true">
        <span class="decor-ring r1"></span>
        <span class="decor-ring r2"></span>
        <span class="decor-ring r3"></span>
        <span class="decor-dot d1"></span>
        <span class="decor-dot d2"></span>
        <span class="decor-dot d3"></span>
        <span class="decor-dot d4"></span>
      </div>

      <div class="brand-lockup">
        <span class="brand-mark" aria-hidden="true">云</span>
        <div class="brand-text">
          <span>云川智汇</span>
          <small>Cognivia · 学习决策工作台</small>
        </div>
      </div>

      <div class="intro-copy">
        <p class="intro-eyebrow">个性化 · 多智能体 · 可解释</p>
        <h1 id="product-title">让每一次学习，<br />都有可追溯的下一步。</h1>
        <p class="intro-summary">从诊断、知识检索到资源审核与反馈调整，为学习者生成可解释的实训路径。</p>
        <div class="intro-features">
          <div class="feature"><span class="feature-num">01</span><span>个性化诊断，生成你的能力画像</span></div>
          <div class="feature"><span class="feature-num">02</span><span>多智能体协同，检索 · 生成 · 审核分工</span></div>
          <div class="feature"><span class="feature-num">03</span><span>反馈闭环，每次反馈都驱动内容更新</span></div>
        </div>
      </div>

      <div class="intro-foot">
        <div class="loop-hint" aria-hidden="true">
          <span>诊断</span><i>→</i><span>画像</span><i>→</i><span>生成</span><i>→</i><span>审核</span><i>→</i><span>反馈</span>
        </div>
        <p class="copyright">云川智汇 Cognivia · 领域知识个性化生成与多智能体协同决策系统</p>
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

        <label class="field-label" for="username">
          <span class="field-text">用户名</span>
          <div class="field-control">
            <svg class="field-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
            <input id="username" v-model.trim="username" autocomplete="username" required minlength="3" maxlength="32" pattern="[A-Za-z0-9_]{3,32}" placeholder="3 至 32 位字母、数字或下划线" />
          </div>
        </label>
        <label v-if="isRegister" class="field-label" for="display-name">
          <span class="field-text">显示名称</span>
          <div class="field-control">
            <svg class="field-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2" /><circle cx="8" cy="11" r="2" /><path d="M5 17c.5-1.5 1.6-2 3-2s2.5.5 3 2" /><path d="M14 10h4M14 14h4" /></svg>
            <input id="display-name" v-model.trim="displayName" autocomplete="name" required placeholder="在学习报告中显示的名称" />
          </div>
        </label>
        <label class="field-label" for="password">
          <span class="field-text">密码</span>
          <div class="field-control">
            <svg class="field-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>
            <input id="password" v-model="password" type="password" :autocomplete="isRegister ? 'new-password' : 'current-password'" required minlength="8" maxlength="72" :placeholder="isRegister ? '至少 8 位密码' : '请输入密码'" />
          </div>
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
  background: var(--soft);
}

.login-intro {
  position: relative;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: clamp(32px, 5vw, 64px);
  color: #f8fbff;
  background:
    radial-gradient(1100px 560px at 88% -8%, rgb(125 167 255 / .3), transparent 60%),
    radial-gradient(760px 480px at -6% 108%, rgb(99 102 241 / .42), transparent 55%),
    linear-gradient(158deg, #14264e 0%, #1d3a7a 46%, #26317f 74%, #16305f 100%);
  overflow: hidden;
}
.login-intro::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgb(255 255 255 / .03) 1px, transparent 1px),
    linear-gradient(90deg, rgb(255 255 255 / .03) 1px, transparent 1px);
  background-size: 52px 52px;
  mask-image: linear-gradient(180deg, rgb(0 0 0 / .55), transparent 72%);
  pointer-events: none;
}

/* 同心圆环装饰 */
.decor { position: absolute; right: -150px; bottom: -90px; width: 540px; height: 540px; pointer-events: none; }
.decor-ring { position: absolute; border-radius: 50%; }
.decor-ring.r1 { inset: 0; border: 1px solid rgb(143 177 255 / .16); }
.decor-ring.r2 { inset: 74px; border: 1px dashed rgb(143 177 255 / .24); }
.decor-ring.r3 { inset: 152px; background: radial-gradient(circle, rgb(125 167 255 / .16), transparent 70%); border: 1px solid rgb(143 177 255 / .12); }
.decor-dot { position: absolute; width: 9px; height: 9px; border-radius: 50%; background: #8fb1ff; box-shadow: 0 0 18px rgb(125 167 255 / .95); }
.decor-dot.d1 { top: 30px; right: 138px; }
.decor-dot.d2 { bottom: 50px; left: 32px; }
.decor-dot.d3 { top: 168px; left: -8px; width: 6px; height: 6px; box-shadow: 0 0 12px rgb(125 167 255 / .8); }
.decor-dot.d4 { bottom: 140px; right: 46px; width: 6px; height: 6px; box-shadow: 0 0 12px rgb(125 167 255 / .8); }

.brand-lockup { position: relative; z-index: 1; display: flex; align-items: center; gap: 12px; }
.brand-mark { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 10px; background: #7da7ff; color: #10254b; font-size: 13px; font-weight: 800; box-shadow: 0 4px 14px rgb(0 0 0 / .22); }
.brand-text { display: grid; gap: 2px; }
.brand-text span { font-size: 16px; font-weight: 760; letter-spacing: .01em; }
.brand-text small { color: #93a9d6; font-size: 11px; letter-spacing: .04em; }

.intro-copy { position: relative; z-index: 1; max-width: 620px; margin: auto 0; padding: 48px 0; }
.intro-eyebrow { margin: 0 0 16px; color: #8fb1ff; font-size: 13px; font-weight: 700; letter-spacing: .14em; }
.intro-copy h1 { max-width: 590px; margin: 0; font-size: clamp(34px, 3.9vw, 56px); line-height: 1.16; letter-spacing: -.03em; text-wrap: balance; }
.intro-summary { max-width: 500px; margin: 22px 0 0; color: #c3d0e9; font-size: 15px; line-height: 1.8; }

.intro-features { display: grid; margin-top: 34px; border-top: 1px solid rgb(143 177 255 / .16); }
.feature { display: flex; align-items: center; gap: 14px; padding: 14px 0; border-bottom: 1px solid rgb(143 177 255 / .12); color: #dbe5f7; font-size: 13.5px; }
.feature-num { width: 32px; height: 32px; flex-shrink: 0; display: grid; place-items: center; border: 1px solid rgb(143 177 255 / .35); border-radius: 9px; color: #8fb1ff; font-size: 11px; font-weight: 700; background: rgb(125 167 255 / .1); }

.intro-foot { position: relative; z-index: 1; display: grid; gap: 14px; }
.loop-hint { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.loop-hint span { border: 1px solid rgb(143 177 255 / .3); border-radius: 999px; background: rgb(125 167 255 / .1); color: #c9d8f5; padding: 5px 12px; font-size: 12px; }
.loop-hint i { color: #6f8fd0; font-style: normal; font-size: 13px; }
.copyright { margin: 0; color: #7d93bd; font-size: 11.5px; letter-spacing: .02em; }

.login-panel { min-height: 100vh; display: flex; flex-direction: column; justify-content: center; padding: clamp(28px, 7vw, 88px); background: var(--panel); }
.auth-switch { width: min(100%, 380px); display: grid; grid-template-columns: 1fr 1fr; gap: 4px; margin: 0 auto 28px; border-radius: 10px; background: var(--soft); padding: 4px; }
.auth-switch button { min-height: 38px; border: 0; border-radius: 7px; background: transparent; color: #61718a; font-size: 13px; font-weight: 700; transition: background 180ms ease, color 180ms ease, box-shadow 180ms ease; }
.auth-switch button.active { background: var(--panel); color: #172746; box-shadow: 0 1px 3px rgb(31 48 75 / .14); }
.login-form { width: min(100%, 380px); margin: auto; display: grid; gap: 18px; }
.form-heading { margin-bottom: 12px; }
.form-kicker { color: #315fce; }
.form-heading h2 { margin: 0; color: var(--auth-ink); font-size: 30px; line-height: 1.25; letter-spacing: -.025em; }
.form-heading > p:last-child { margin: 10px 0 0; color: var(--auth-muted); font-size: 14px; line-height: 1.65; }
.field-label { display: grid; gap: 8px; color: #344762; font-size: 13px; font-weight: 700; }
.field-text { display: block; }
.field-control { position: relative; }
.field-icon { position: absolute; left: 14px; top: 50%; width: 18px; height: 18px; transform: translateY(-50%); color: #94a3b8; pointer-events: none; transition: color 180ms ease; }
.field-control:focus-within .field-icon { color: #315fce; }
.field-label input { width: 100%; height: 48px; border: 1px solid #cbd6e4; border-radius: 10px; background: var(--panel); color: var(--auth-ink); padding: 0 14px 0 42px; font-size: 15px; outline: 0; transition: border-color 180ms ease, box-shadow 180ms ease, background 180ms ease; }
.field-label input::placeholder { color: #718096; opacity: 1; }
.field-label input:hover { border-color: #9eafc6; }
.field-label input:focus { border-color: #315fce; background: var(--panel); box-shadow: 0 0 0 3px rgb(49 95 206 / .16); }
.auth-error { margin: -2px 0 0; border-radius: 8px; background: var(--red2); color: #ae3030; padding: 10px 12px; font-size: 13px; line-height: 1.45; }
.submit-button { min-height: 48px; display: flex; align-items: center; justify-content: space-between; border: 0; border-radius: 10px; background: linear-gradient(135deg, #3d6fe0, #274fae); color: #fff; padding: 0 16px; font-size: 15px; font-weight: 720; box-shadow: 0 4px 14px rgb(39 79 174 / .24); transition: transform 180ms ease, box-shadow 180ms ease, filter 180ms ease; }
.submit-button:hover:not(:disabled) { filter: brightness(1.04); box-shadow: 0 6px 18px rgb(39 79 174 / .3); transform: translateY(-1px); }
.submit-button:disabled { cursor: wait; filter: saturate(.7) brightness(1.05); }
.register-link { margin: 2px 0 0; color: var(--auth-muted); font-size: 13px; text-align: center; }
.register-link button { border: 0; background: transparent; color: #315fce; padding: 0; font: inherit; font-weight: 700; text-decoration: underline; text-underline-offset: 3px; }
.security-note { width: min(100%, 380px); margin: 40px auto 0; color: #6b7b91; font-size: 12px; line-height: 1.55; }
.security-note span { margin-right: 5px; color: #138a63; font-weight: 800; }

@media (max-width: 820px) {
  .login-page { grid-template-columns: 1fr; }
  .login-intro { min-height: auto; padding: 26px 24px 28px; }
  .decor { right: -180px; bottom: -140px; opacity: .5; }
  .intro-copy { margin: 34px 0 30px; padding: 0; }
  .intro-copy h1 { font-size: 32px; }
  .intro-summary { margin-top: 14px; font-size: 14px; }
  .intro-features { margin-top: 22px; }
  .intro-foot { display: none; }
  .login-panel { min-height: auto; padding: 38px 24px 32px; }
  .auth-switch { margin-bottom: 24px; }
  .login-form { margin: 0 auto; }
}

@media (max-width: 420px) { .login-intro, .login-panel { padding-left: 20px; padding-right: 20px; } .intro-copy h1 { font-size: 28px; } }
@media (prefers-reduced-motion: reduce) { .field-label input, .submit-button { transition: none; } }
</style>
