<template>
  <section class="page">
    <div class="head">
      <div><h1>诊断与画像</h1></div>
      <div class="actions">
        <button class="btn" @click="showProfile = !showProfile">{{ showProfile ? '返回诊断题' : '查看画像结果' }}</button>
        <button class="btn primary" @click="startSession" :disabled="creatingSession">{{ creatingSession ? '创建中...' : session ? '继续答题' : '创建 10 题测评' }}</button>
      </div>
    </div>

    <!-- No Session -->
    <div v-if="!session && !showProfile" class="panel" style="text-align:center;padding:60px">
      <div class="upload-icon" style="margin:auto">◎</div>
      <strong style="display:block;margin-top:14px">尚未创建诊断测评</strong>
      <p class="sub">点击"创建 10 题测评"开始诊断，系统将从题库中抽取 {{ domainCode }} 领域的题目。</p>
      <button class="btn primary" style="margin-top:16px" @click="startSession" :disabled="creatingSession">{{ creatingSession ? '创建中...' : '创建 10 题测评' }}</button>
    </div>

    <!-- Test View -->
    <div v-if="session && !showProfile" class="diag">
      <aside class="panel">
        <h2>{{ session.domain_code }} 诊断</h2>
        <p class="sub">{{ session.question_count }} 题 · 会话 {{ session.session_id?.slice(0,8) }}</p>
        <div class="qnav">
          <button v-for="(q,i) in session.questions" :key="q.question_id" class="q"
            :class="{ done: answers[i], current: i === currentIdx }">{{ i+1 }}</button>
        </div>
        <p class="sub" style="margin-top:18px">状态：{{ session.status }}</p>
        <button class="btn primary" style="width:100%;margin-top:12px" @click="submitAll" :disabled="submitting">{{ submitting ? '提交中...' : '提交全部答案' }}</button>
      </aside>
      <article v-if="currentQuestion" class="panel">
        <div class="meta">
          <span class="tag">{{ currentQuestion.question_type === 'single_choice' ? '单选题' : '简答题' }}</span>
          <span class="tag">难度 {{ currentQuestion.difficulty }}/5</span>
        </div>
        <h2 class="question">{{ currentQuestion.stem }}</h2>
        <div v-if="currentQuestion.question_type === 'single_choice'" class="options">
          <label v-for="(opt, i) in currentQuestion.options" :key="i" class="option">
            <input type="radio" :name="'q'+currentIdx" :value="i" v-model="answers[currentIdx]" />{{ String.fromCharCode(65+i) }}. {{ opt }}
          </label>
        </div>
        <textarea v-else v-model="answers[currentIdx]" placeholder="请输入答案..." style="margin-top:14px;min-height:100px"></textarea>
        <div class="actions" style="margin-top:22px;justify-content:flex-end">
          <button class="btn" @click="currentIdx = Math.max(0, currentIdx-1)" :disabled="currentIdx===0">上一题</button>
          <button class="btn primary" @click="currentIdx = Math.min(session.questions.length-1, currentIdx+1)" :disabled="currentIdx>=session.questions.length-1">下一题</button>
        </div>
      </article>
    </div>

    <!-- Profile View -->
    <div v-if="showProfile && result" class="profile">
      <div class="panel"><div class="panel-head"><h2>五维能力画像</h2><span class="tag">{{ result.profile_type }}</span></div>
        <div class="radar"><svg viewBox="0 0 240 240"><g fill="none" stroke="#dce3ed"><polygon points="120,20 215,89 179,201 61,201 25,89"/><polygon points="120,45 191,97 164,181 76,181 49,97"/></g><polygon points="120,52 181,100 151,164 77,179 56,99" fill="rgba(49,95,206,.2)" stroke="#315fce" stroke-width="2"/></svg></div>
      </div>
      <div class="panel">
        <div class="panel-head"><h2>诊断结论</h2><span class="status ok">得分 {{ result.score }}/{{ result.question_count }}</span></div>
        <div class="insight"><strong>诊断完成</strong><br>正确率 {{ result.correct_count }}/{{ result.question_count }}。下一步：生成个性化学习资源。</div>
        <div class="mastery">
          <div v-for="w in result.weak_knowledge?.slice(0,4)" :key="w.knowledge_id"><span>薄弱点</span><strong>{{ w.name }}</strong></div>
        </div>
        <div class="actions" style="margin-top:14px"><button class="btn primary" @click="router.push('/resources')">生成学习资源</button></div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import { createDiagnosticSession, submitDiagnosticSession, type DiagnosticSession, type DiagnosticResult } from '@/api/diagnostics'

const router = useRouter()
const { showToast } = useToast()
const domainCode = 'ai_app_dev'

const creatingSession = ref(false)
const submitting = ref(false)
const showProfile = ref(false)
const currentIdx = ref(0)
const session = ref<DiagnosticSession | null>(null)
const result = ref<DiagnosticResult | null>(null)
const answers = ref<Record<number, string>>({})

const currentQuestion = computed(() => session.value?.questions[currentIdx.value] || null)

async function startSession() {
  creatingSession.value = true
  try {
    session.value = await createDiagnosticSession('learner_001')
    answers.value = {}
    showToast('已创建 10 题诊断测评')
  } catch { showToast('创建测评失败') }
  finally { creatingSession.value = false }
}

async function submitAll() {
  if (!session.value) return
  submitting.value = true
  try {
    const list = Object.entries(answers.value).map(([idx, answer]) => ({
      question_id: session.value!.questions[Number(idx)].question_id,
      answer,
    }))
    result.value = await submitDiagnosticSession(session.value.session_id, list, 'learner_001')
    showProfile.value = true
    showToast(`诊断完成！得分 ${result.value.score}`)
  } catch { showToast('提交失败') }
  finally { submitting.value = false }
}
</script>
