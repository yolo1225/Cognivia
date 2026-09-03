<template>
  <main class="welcome-page">
    <a class="skip-link" href="#welcome-main">跳到主要内容</a>

    <header class="welcome-header">
      <RouterLink class="welcome-brand" to="/" aria-label="Cognivia 首页">
        <img src="/favicon.svg" alt="" />
        <span><strong>Cognivia</strong><small>云川智汇</small></span>
      </RouterLink>
      <nav class="welcome-nav" aria-label="账户入口">
        <RouterLink to="/login">登录</RouterLink>
        <RouterLink class="register-link" to="/register">注册</RouterLink>
      </nav>
    </header>

    <section id="welcome-main" class="welcome-hero" aria-labelledby="welcome-title">
      <div class="hero-copy">
        <p class="eyebrow"><span></span>领域知识智能协同平台</p>
        <h1 id="welcome-title">让领域知识<br /><em>真正服务每一次学习决策</em></h1>
        <p>从学习证据出发，组织知识检索、多智能体生成、双模型审核与反馈更新，形成可解释、可追溯的个性化学习闭环。</p>
        <div class="hero-actions">
          <RouterLink class="start-button" to="/login">进入工作台 <span aria-hidden="true">→</span></RouterLink>
          <RouterLink class="outline-button" to="/register">创建账号</RouterLink>
        </div>
      </div>

      <section class="agent-canvas" aria-label="多智能体协同处理流程">
        <div class="canvas-header">
          <span class="live-indicator"><i></i>协同任务运行中</span>
          <span>DOMAIN-AGNOSTIC / 01</span>
        </div>
        <div class="canvas-body">
          <div class="connection connection-a" aria-hidden="true"><i></i></div>
          <div class="connection connection-b" aria-hidden="true"><i></i></div>
          <div class="connection connection-c" aria-hidden="true"><i></i></div>
          <div class="connection connection-d" aria-hidden="true"><i></i></div>
          <article v-for="node in agentNodes" :key="node.title" class="agent-node" :class="node.position">
            <span class="node-symbol" :class="node.tone" aria-hidden="true"><i></i><i></i><i></i></span>
            <div><small>{{ node.role }}</small><strong>{{ node.title }}</strong></div>
            <span class="node-state">{{ node.state }}</span>
          </article>
          <div class="decision-core" aria-label="协调编排 Agent">
            <span class="core-ring ring-one"></span><span class="core-ring ring-two"></span>
            <div><small>ORCHESTRATOR</small><strong>协同决策</strong><span>任务路由与质量决策</span></div>
          </div>
        </div>
        <div class="canvas-footer">
          <span>学习证据 → 资源生成 → 质量验证 → 反馈更新</span>
          <span class="canvas-status">TRACEABLE</span>
        </div>
      </section>
    </section>

    <section class="capability-strip" aria-label="平台能力概览">
      <article><span class="capability-number">01</span><div><strong>画像诊断</strong><p>识别学习差异，形成可解释的学习依据。</p></div></article>
      <article><span class="capability-number">02</span><div><strong>协同生成</strong><p>多 Agent 以独立职责组织内容与证据。</p></div></article>
      <article><span class="capability-number">03</span><div><strong>审核更新</strong><p>审核结果和反馈共同驱动后续决策。</p></div></article>
    </section>

    <footer class="welcome-footer"><span>Cognivia</span> · 领域知识个性化生成与多智能体协同决策系统</footer>
  </main>
</template>

<script setup lang="ts">
const agentNodes = [
  { position: 'node-profile', role: 'PROFILE AGENT', title: '画像分析', state: '已就绪', tone: 'green' },
  { position: 'node-retrieval', role: 'RETRIEVAL AGENT', title: '知识检索', state: '检索中', tone: 'blue' },
  { position: 'node-generation', role: 'GENERATION AGENT', title: '内容生成', state: '等待校验', tone: 'violet' },
  { position: 'node-review', role: 'REVIEW AGENT', title: '审核验证', state: '双路复核', tone: 'teal' },
]
</script>

<style scoped>
.welcome-page { --ink: #152337; --body: #586a7e; --line: #dbe5ee; --blue: #276fd7; --green: #14a487; --surface: #f7fafc; min-height: 100vh; overflow: hidden; background: #fff; color: var(--ink); }
.welcome-header { width: min(1180px, calc(100% - 64px)); min-height: 82px; display: flex; align-items: center; justify-content: space-between; margin: 0 auto; border-bottom: 1px solid var(--line); }
.welcome-brand { display: inline-flex; align-items: center; gap: 11px; color: inherit; text-decoration: none; }.welcome-brand img { width: 37px; height: 37px; display: block; }.welcome-brand > span { display: grid; gap: 1px; }.welcome-brand strong { font-size: 17px; letter-spacing: .01em; }.welcome-brand small { color: #718197; font-size: 11px; font-weight: 650; letter-spacing: .11em; }
.welcome-nav { display: flex; align-items: center; gap: 23px; }.welcome-nav a { color: #586a7d; font-size: 14px; font-weight: 670; text-decoration: none; transition: color 180ms ease; }.welcome-nav a:hover { color: var(--blue); }.welcome-nav .register-link { min-height: 36px; display: inline-flex; align-items: center; border: 1px solid #c6d8ed; border-radius: 6px; background: #fff; color: #286bc8; padding: 0 14px; }.welcome-nav .register-link:hover { border-color: #9bbce6; background: #f7fbff; }
.welcome-hero { width: min(1180px, calc(100% - 64px)); min-height: calc(100vh - 160px); display: grid; grid-template-columns: minmax(0, .85fr) minmax(470px, 1.15fr); align-items: center; gap: clamp(42px, 6vw, 88px); margin: 0 auto; padding: 44px 0 54px; }.hero-copy { max-width: 500px; padding-bottom: 22px; }.eyebrow { display: flex; align-items: center; gap: 9px; margin: 0 0 17px; color: #447490; font-size: 12px; font-weight: 760; letter-spacing: .13em; }.eyebrow span { width: 22px; height: 1px; background: var(--green); }.hero-copy h1 { margin: 0; font-size: clamp(39px, 4vw, 58px); line-height: 1.18; font-weight: 790; letter-spacing: 0; text-wrap: balance; }.hero-copy h1 em { color: var(--green); font-style: normal; }.hero-copy > p:last-of-type { max-width: 470px; margin: 24px 0 0; color: var(--body); font-size: 15px; line-height: 1.85; }.hero-actions { display: flex; gap: 12px; margin-top: 32px; }.hero-actions a { min-height: 43px; display: inline-flex; align-items: center; justify-content: center; border-radius: 6px; padding: 0 18px; font-size: 14px; font-weight: 730; text-decoration: none; transition: transform 180ms ease, box-shadow 180ms ease, background 180ms ease, border-color 180ms ease; }.start-button { background: var(--blue); color: #fff; box-shadow: 0 7px 16px rgb(39 111 215 / .18); }.start-button span { margin-left: 13px; font-size: 18px; }.start-button:hover { background: #1d61c4; box-shadow: 0 9px 20px rgb(39 111 215 / .25); transform: translateY(-1px); }.outline-button { border: 1px solid #cad8e6; color: #466078; background: #fff; }.outline-button:hover { border-color: #9ab9dc; background: #f8fbff; }
.agent-canvas { min-height: 420px; display: grid; grid-template-rows: 48px 1fr 42px; border: 1px solid #d5e2ec; border-radius: 10px; background: var(--surface); box-shadow: 0 18px 35px rgb(25 56 83 / .08); overflow: hidden; }.canvas-header, .canvas-footer { display: flex; align-items: center; justify-content: space-between; padding: 0 19px; color: #718397; font-size: 10px; font-weight: 750; letter-spacing: .1em; }.canvas-header { border-bottom: 1px solid #dce7ef; background: #fcfeff; }.canvas-footer { border-top: 1px solid #dce7ef; letter-spacing: .04em; }.live-indicator { display: inline-flex; align-items: center; gap: 7px; color: #2c786c; }.live-indicator i { width: 7px; height: 7px; border-radius: 50%; background: var(--green); animation: blink 1.5s ease-in-out infinite; }.canvas-status { color: #4279be; font-size: 9px; }.canvas-body { position: relative; min-height: 326px; overflow: hidden; background: #f8fbfd; }
.connection { position: absolute; height: 1px; transform-origin: left center; background: #bad0e2; overflow: visible; }.connection::before { content: ''; position: absolute; inset: -3px 0; opacity: .55; background: #c9f0e5; }.connection i { position: absolute; top: 50%; width: 8px; height: 8px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 4px rgb(20 164 135 / .13); animation: signal 3s linear infinite; }.connection-a { width: 41%; left: 17%; top: 35%; transform: rotate(15deg); }.connection-b { width: 39%; left: 48%; top: 50%; transform: rotate(-27deg); }.connection-c { width: 37%; left: 24%; top: 64%; transform: rotate(-12deg); }.connection-d { width: 25%; left: 56%; top: 57%; transform: rotate(37deg); }.connection-b i { animation-delay: 1.05s; }.connection-c i { animation-delay: 2.1s; }.connection-d i { animation-delay: .55s; }
.agent-node { position: absolute; z-index: 2; display: flex; align-items: center; gap: 9px; min-width: 145px; border: 1px solid #d0dee9; border-radius: 7px; background: #fff; padding: 10px 11px; box-shadow: 0 5px 10px rgb(25 56 83 / .055); }.agent-node small, .agent-node strong { display: block; }.agent-node small { color: #8092a3; font-size: 8px; font-weight: 760; letter-spacing: .08em; }.agent-node strong { margin-top: 2px; color: #2b3d52; font-size: 13px; }.node-profile { left: 7%; top: 14%; }.node-retrieval { right: 6%; top: 17%; }.node-generation { left: 8%; bottom: 14%; }.node-review { right: 6%; bottom: 15%; }.node-symbol { width: 28px; height: 28px; flex: 0 0 28px; display: grid; grid-template-columns: repeat(2, 1fr); align-content: center; justify-items: center; gap: 3px; border-radius: 7px; background: #edf7f4; padding: 6px; }.node-symbol i { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }.node-symbol i:last-child { grid-column: 1 / -1; }.node-symbol.green { color: #168d78; background: #e8f6f1; }.node-symbol.blue { color: #3979ce; background: #eaf2fd; }.node-symbol.violet { color: #7b62bf; background: #f1edfb; }.node-symbol.teal { color: #168da4; background: #e8f6f8; }.node-state { position: absolute; right: 8px; bottom: -17px; color: #7890a3; font-size: 9px; font-weight: 650; white-space: nowrap; }
.decision-core { position: absolute; z-index: 3; left: 50%; top: 50%; width: 142px; height: 142px; display: grid; place-items: center; border: 1px solid #8fc3e5; border-radius: 50%; background: #fafdff; transform: translate(-50%, -50%); box-shadow: 0 0 0 10px rgb(255 255 255 / .9), 0 10px 21px rgb(35 106 171 / .12); }.decision-core > div { display: grid; justify-items: center; gap: 3px; text-align: center; }.decision-core small { color: #4c7fa9; font-size: 8px; font-weight: 800; letter-spacing: .11em; }.decision-core strong { font-size: 18px; letter-spacing: .02em; }.decision-core div span { color: #708499; font-size: 9px; }.core-ring { position: absolute; border: 1px solid #b6d9eb; border-radius: 50%; pointer-events: none; }.ring-one { inset: -12px; border-style: dashed; animation: spin 18s linear infinite; }.ring-two { inset: 14px; border-color: #c5ebdf; animation: spin 13s linear infinite reverse; }
.capability-strip { width: min(1180px, calc(100% - 64px)); display: grid; grid-template-columns: repeat(3, 1fr); margin: 0 auto; border-top: 1px solid var(--line); }.capability-strip article { min-height: 122px; display: flex; align-items: center; gap: 16px; border-right: 1px solid var(--line); padding: 26px 28px; }.capability-strip article:first-child { padding-left: 0; }.capability-strip article:last-child { border-right: 0; padding-right: 0; }.capability-number { color: #9cc5e9; font-size: 13px; font-weight: 800; letter-spacing: .05em; }.capability-strip strong { font-size: 15px; }.capability-strip p { margin: 6px 0 0; color: #708194; font-size: 12px; line-height: 1.6; }.welcome-footer { padding: 25px 24px 29px; color: #8797a8; font-size: 11px; text-align: center; }.welcome-footer span { color: #4e789d; font-weight: 760; }
@keyframes blink { 0%, 100% { opacity: .35; box-shadow: 0 0 0 0 rgb(20 164 135 / .3); } 50% { opacity: 1; box-shadow: 0 0 0 5px rgb(20 164 135 / 0); } } @keyframes signal { from { left: 0; opacity: 0; } 12% { opacity: 1; } 88% { opacity: 1; } to { left: calc(100% - 8px); opacity: 0; } } @keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 940px) { .welcome-hero { grid-template-columns: 1fr; gap: 38px; padding-top: 68px; }.hero-copy { max-width: 610px; padding-bottom: 0; }.agent-canvas { width: min(650px, 100%); justify-self: center; }.capability-strip article { padding: 22px 16px; }.capability-strip article:first-child { padding-left: 0; } }
@media (max-width: 660px) { .welcome-header, .welcome-hero, .capability-strip { width: min(100% - 32px, 1180px); }.welcome-header { min-height: 68px; }.welcome-nav { gap: 15px; }.welcome-hero { padding: 48px 0; }.hero-copy h1 { font-size: clamp(35px, 10vw, 48px); }.hero-copy > p:last-of-type { font-size: 14px; }.agent-canvas { min-height: 400px; grid-template-rows: 43px 1fr 40px; }.canvas-body { min-height: 316px; }.agent-node { min-width: 128px; padding: 8px; }.agent-node strong { font-size: 12px; }.node-profile { left: 4%; }.node-retrieval { right: 4%; }.node-generation { left: 4%; }.node-review { right: 4%; }.decision-core { width: 122px; height: 122px; }.decision-core strong { font-size: 16px; }.connection-a { left: 19%; }.connection-b { left: 47%; }.capability-strip { grid-template-columns: 1fr; }.capability-strip article { min-height: auto; border-right: 0; border-bottom: 1px solid var(--line); padding: 18px 0; }.capability-strip article:last-child { border-bottom: 0; }.capability-strip p { margin-top: 3px; }.welcome-footer { padding-top: 20px; } }
@media (max-width: 430px) { .hero-actions { width: 100%; }.hero-actions a { flex: 1; padding: 0 12px; }.agent-canvas { transform: scale(.9); transform-origin: top center; width: 111%; margin-bottom: -38px; }.welcome-brand img { width: 34px; height: 34px; }.welcome-brand strong { font-size: 16px; } }
@media (prefers-reduced-motion: reduce) { .live-indicator i, .connection i, .ring-one, .ring-two { animation: none; }.hero-actions a, .welcome-nav a { transition: none; } }
</style>
