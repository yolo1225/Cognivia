<template>
  <main class="landing">
    <header class="landing-nav">
      <div class="brand-lockup">
        <span class="brand-mark" aria-hidden="true">云</span>
        <div class="brand-text">
          <span>云川智汇</span>
          <small>Cognivia · 多智能体个性化知识生成系统</small>
        </div>
      </div>
      <nav class="nav-actions" aria-label="页面导航">
        <button type="button" class="nav-link" @click="scrollToFeatures">平台能力</button>
        <button type="button" class="nav-cta" @click="goLogin">登录 / 注册</button>
      </nav>
    </header>

    <section class="hero" aria-labelledby="landing-title">
      <div class="hero-decor" aria-hidden="true">
        <span class="decor-ring r1"></span>
        <span class="decor-ring r2"></span>
        <span class="decor-ring r3"></span>
        <span class="decor-dot d1"></span>
        <span class="decor-dot d2"></span>
        <span class="decor-dot d3"></span>
        <span class="decor-dot d4"></span>
      </div>

      <div class="hero-inner">
        <p class="hero-eyebrow">人工智能应用开发实训 · 多智能体协同</p>
        <h1 id="landing-title">让每一次学习，<br />都有可追溯的下一步</h1>
        <p class="hero-tagline">
          从诊断、知识检索到资源生成、审核与反馈调整，为每位学习者生成可解释、可追溯的个性化实训路径。
        </p>
        <div class="hero-cta">
          <button type="button" class="cta-primary" @click="goLogin">
            登录 / 注册<span aria-hidden="true">→</span>
          </button>
          <button type="button" class="cta-secondary" @click="scrollToFeatures">
            了解平台能力
          </button>
        </div>
        <div class="hero-loop" aria-hidden="true">
          <span>诊断</span><i>→</i><span>画像</span><i>→</i><span>生成</span><i>→</i><span>审核</span><i>→</i><span>反馈</span>
        </div>
      </div>
    </section>

    <section id="features" class="features" aria-labelledby="features-title">
      <div class="features-head">
        <p class="section-kicker">平台能力</p>
        <h2 id="features-title">一套可解释、可追溯的个性化学习闭环</h2>
      </div>

      <div class="feature-grid">
        <article class="feature-card">
          <span class="feature-icon" aria-hidden="true">诊</span>
          <h3>认知诊断与能力画像</h3>
          <p>完成诊断测评后，自动分析作答与知识点掌握情况，生成能力画像与个性化学习路线。</p>
        </article>
        <article class="feature-card">
          <span class="feature-icon" aria-hidden="true">生</span>
          <h3>知识检索与资源生成</h3>
          <p>基于 Candidate RAG 检索领域知识，多智能体协同生成讲义、练习指南与分阶测验三类资源。</p>
        </article>
        <article class="feature-card">
          <span class="feature-icon" aria-hidden="true">审</span>
          <h3>双模型审核与反馈闭环</h3>
          <p>双模型交叉审核、自动局部修订后原子发布，学习反馈持续用于调整资源与后续路线。</p>
        </article>
      </div>
    </section>

    <footer class="landing-footer">
      <p>云川智汇 Cognivia · 领域知识个性化生成与多智能体协同决策系统</p>
    </footer>
  </main>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()

function goLogin() {
  router.push('/login')
}

function scrollToFeatures() {
  document.getElementById('features')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<style scoped>
.landing {
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto 1fr auto;
  background: var(--bg);
}

/* 顶部导航 */
.landing-nav {
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px clamp(20px, 5vw, 56px);
  background: rgb(17 32 66 / .72);
  backdrop-filter: blur(12px);
}
.brand-lockup { display: flex; align-items: center; gap: 12px; }
.brand-mark {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 10px;
  background: #7da7ff;
  color: #10254b;
  font-size: 13px;
  font-weight: 800;
  box-shadow: 0 4px 14px rgb(0 0 0 / .22);
}
.brand-text { display: grid; gap: 2px; color: #f8fbff; }
.brand-text span { font-size: 16px; font-weight: 760; letter-spacing: .01em; }
.brand-text small { color: #93a9d6; font-size: 11px; letter-spacing: .04em; }

.nav-actions { display: flex; align-items: center; gap: 10px; }
.nav-link {
  border: 0;
  background: transparent;
  color: #c9d8f5;
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 650;
}
.nav-link:hover { color: #fff; }
.nav-cta {
  min-height: 38px;
  border: 0;
  border-radius: 9px;
  background: #7da7ff;
  color: #10254b;
  padding: 0 16px;
  font-size: 13px;
  font-weight: 760;
  box-shadow: 0 4px 14px rgb(0 0 0 / .2);
  transition: transform var(--transition-fast), filter var(--transition-fast);
}
.nav-cta:hover { filter: brightness(1.06); transform: translateY(-1px); }

/* Hero */
.hero {
  position: relative;
  display: grid;
  place-items: center;
  padding: clamp(56px, 9vw, 120px) clamp(20px, 5vw, 56px);
  color: #f8fbff;
  background:
    radial-gradient(1100px 560px at 88% -8%, rgb(125 167 255 / .3), transparent 60%),
    radial-gradient(760px 480px at -6% 108%, rgb(99 102 241 / .42), transparent 55%),
    linear-gradient(158deg, #14264e 0%, #1d3a7a 46%, #26317f 74%, #16305f 100%);
  overflow: hidden;
}
.hero::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgb(255 255 255 / .03) 1px, transparent 1px),
    linear-gradient(90deg, rgb(255 255 255 / .03) 1px, transparent 1px);
  background-size: 52px 52px;
  mask-image: linear-gradient(180deg, rgb(0 0 0 / .55), transparent 78%);
  pointer-events: none;
}
.hero-decor { position: absolute; right: -150px; bottom: -90px; width: 540px; height: 540px; pointer-events: none; }
.decor-ring { position: absolute; border-radius: 50%; }
.decor-ring.r1 { inset: 0; border: 1px solid rgb(143 177 255 / .16); }
.decor-ring.r2 { inset: 74px; border: 1px dashed rgb(143 177 255 / .24); }
.decor-ring.r3 { inset: 152px; background: radial-gradient(circle, rgb(125 167 255 / .16), transparent 70%); border: 1px solid rgb(143 177 255 / .12); }
.decor-dot { position: absolute; width: 9px; height: 9px; border-radius: 50%; background: #8fb1ff; box-shadow: 0 0 18px rgb(125 167 255 / .95); }
.decor-dot.d1 { top: 30px; right: 138px; }
.decor-dot.d2 { bottom: 50px; left: 32px; }
.decor-dot.d3 { top: 168px; left: -8px; width: 6px; height: 6px; box-shadow: 0 0 12px rgb(125 167 255 / .8); }
.decor-dot.d4 { bottom: 140px; right: 46px; width: 6px; height: 6px; box-shadow: 0 0 12px rgb(125 167 255 / .8); }

.hero-inner {
  position: relative;
  z-index: 1;
  max-width: 760px;
  text-align: center;
}
.hero-eyebrow { margin: 0 0 18px; color: #a9c2fa; font-size: 13px; font-weight: 700; letter-spacing: .04em; }
.hero-inner h1 {
  margin: 0;
  font-size: clamp(34px, 5vw, 60px);
  line-height: 1.14;
  letter-spacing: -.03em;
  text-wrap: balance;
}
.hero-tagline { max-width: 560px; margin: 22px auto 0; color: #c3d0e9; font-size: 15px; line-height: 1.85; }
.hero-cta { display: flex; justify-content: center; gap: 12px; flex-wrap: wrap; margin-top: 34px; }
.cta-primary {
  min-height: 50px;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  border: 0;
  border-radius: 11px;
  background: #7da7ff;
  color: #10254b;
  padding: 0 24px;
  font-size: 15px;
  font-weight: 760;
  box-shadow: 0 8px 24px rgb(0 0 0 / .28);
  transition: transform var(--transition-fast), filter var(--transition-fast), box-shadow var(--transition-fast);
}
.cta-primary:hover { filter: brightness(1.06); transform: translateY(-2px); box-shadow: 0 12px 30px rgb(0 0 0 / .32); }
.cta-secondary {
  min-height: 50px;
  border: 1px solid rgb(143 177 255 / .4);
  border-radius: 11px;
  background: rgb(125 167 255 / .08);
  color: #dbe5f7;
  padding: 0 22px;
  font-size: 14px;
  font-weight: 650;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}
.cta-secondary:hover { background: rgb(125 167 255 / .16); border-color: rgb(143 177 255 / .6); }

.hero-loop { display: flex; flex-wrap: wrap; justify-content: center; align-items: center; gap: 8px; margin-top: 42px; }
.hero-loop span { border: 1px solid rgb(143 177 255 / .3); border-radius: 999px; background: rgb(125 167 255 / .1); color: #c9d8f5; padding: 5px 13px; font-size: 12px; }
.hero-loop i { color: #6f8fd0; font-style: normal; font-size: 13px; }

/* 功能卡片 */
.features {
  padding: clamp(56px, 8vw, 96px) clamp(20px, 6vw, 72px);
  background: var(--bg);
}
.features-head { max-width: 760px; margin: 0 auto 40px; text-align: center; }
.section-kicker { margin: 0 0 12px; color: var(--blue); font-size: 13px; font-weight: 700; letter-spacing: .04em; }
.features-head h2 { margin: 0; color: var(--ink); font-size: clamp(24px, 3vw, 34px); letter-spacing: -.02em; text-wrap: balance; }

.feature-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  max-width: 1080px;
  margin: 0 auto;
}
.feature-card {
  border: 1px solid var(--line);
  border-radius: var(--radius-panel);
  background: var(--panel);
  padding: 28px 26px;
  transition: transform var(--transition-fast), box-shadow var(--transition-fast), border-color var(--transition-fast);
}
.feature-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-hover); border-color: var(--line-strong); }
.feature-icon {
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  background: var(--blue2);
  color: var(--blue);
  font-size: 19px;
  font-weight: 800;
}
.feature-card h3 { margin: 18px 0 10px; color: var(--ink); font-size: 17px; letter-spacing: -.01em; }
.feature-card p { margin: 0; color: var(--muted); font-size: 13.5px; line-height: 1.8; }

/* 页脚 */
.landing-footer {
  border-top: 1px solid var(--line);
  background: var(--panel);
  padding: 26px clamp(20px, 5vw, 56px);
  text-align: center;
}
.landing-footer p { margin: 0; color: var(--muted); font-size: 12.5px; letter-spacing: .02em; }

@media (max-width: 820px) {
  .feature-grid { grid-template-columns: 1fr; gap: 14px; }
  .hero-decor { opacity: .5; }
}
@media (max-width: 560px) {
  .brand-text small { display: none; }
  .hero-cta { flex-direction: column; align-items: stretch; }
  .cta-primary, .cta-secondary { justify-content: center; }
}
</style>
