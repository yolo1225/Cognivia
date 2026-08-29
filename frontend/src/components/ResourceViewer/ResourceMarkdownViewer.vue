<template>
  <article ref="root" class="markdown-body" v-html="html" />
</template>

<script setup lang="ts">
import { marked } from 'marked'
import { computed, nextTick, onMounted, ref, watch } from 'vue'

interface HeadingItem {
  level: number
  text: string
  id: string
}

const props = defineProps<{
  content: string
  collapsible?: boolean
  openHeadings?: number
}>()

const emit = defineEmits<{
  headings: [HeadingItem[]]
}>()

const root = ref<HTMLElement | null>(null)

const html = computed(() => {
  const raw = marked.parse(props.content, { gfm: true, breaks: true, async: false }) as string
  if (typeof DOMParser === 'undefined') return raw
  const document = new DOMParser().parseFromString(raw, 'text/html')
  document.querySelectorAll('script, style, iframe, object, embed, form').forEach(node => node.remove())
  document.querySelectorAll('*').forEach(node => {
    for (const attribute of [...node.attributes]) {
      const value = attribute.value.trim().toLowerCase()
      if (attribute.name.startsWith('on') || attribute.name === 'style' || (attribute.name === 'href' && value && !value.startsWith('http://') && !value.startsWith('https://') && !value.startsWith('mailto:'))) node.removeAttribute(attribute.name)
    }
    if (node.tagName === 'A') { node.setAttribute('target', '_blank'); node.setAttribute('rel', 'noopener noreferrer') }
  })
  return document.body.innerHTML
})

function slugify(text: string): string {
  return (
    text
      .trim()
      .toLowerCase()
      .replace(/[^\p{L}\p{N}\s-]/gu, '')
      .replace(/\s+/g, '-')
      .replace(/-{2,}/g, '-')
      .replace(/^-+|-+$/g, '') || 'section'
  )
}

function copyText(text: string): void {
  if (navigator.clipboard?.writeText) {
    void navigator.clipboard.writeText(text)
    return
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  document.body.removeChild(textarea)
}

function decorate(): void {
  const article = root.value
  if (!article) return

  // 标题锚点 + 目录
  const seen = new Map<string, number>()
  const headings: HeadingItem[] = []
  article.querySelectorAll('h1, h2, h3, h4').forEach(heading => {
    const base = slugify(heading.textContent || '')
    const count = (seen.get(base) ?? 0) + 1
    seen.set(base, count)
    const id = count === 1 ? base : `${base}-${count}`
    heading.id = id
    headings.push({ level: Number(heading.tagName[1]), text: heading.textContent?.trim() || '', id })
  })

  // 代码块复制按钮
  article.querySelectorAll('pre').forEach(pre => {
    if (pre.querySelector('.code-copy')) return
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'code-copy'
    button.setAttribute('aria-label', '复制代码')
    button.textContent = '复制'
    button.addEventListener('click', () => {
      const code = pre.querySelector('code')?.textContent ?? pre.textContent ?? ''
      copyText(code)
      button.textContent = '已复制'
      window.setTimeout(() => { button.textContent = '复制' }, 1500)
    })
    pre.appendChild(button)
  })

  // 分章节折叠：把每个 h2 章节包进 <details>，默认展开前 N 个
  if (props.collapsible) {
    let opened = 0
    article.querySelectorAll('h2').forEach(h2 => {
      const details = document.createElement('details')
      const summary = document.createElement('summary')
      summary.textContent = h2.textContent?.trim() || ''
      details.className = 'md-section'
      details.id = h2.id
      details.open = opened < (props.openHeadings ?? 2)
      opened += 1
      const group: Element[] = []
      let node = h2.nextElementSibling
      while (node && node.tagName !== 'H2') {
        const next = node.nextElementSibling
        group.push(node)
        node = next
      }
      h2.replaceWith(details)
      details.appendChild(summary)
      group.forEach(n => details.appendChild(n))
    })
  }

  emit('headings', headings)
}

onMounted(() => nextTick(decorate))
watch(html, () => nextTick(decorate))
</script>

<style scoped>
.markdown-body {
  color: var(--body);
  font-size: 13.5px;
  line-height: 1.8;
  overflow-wrap: anywhere;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  scroll-margin-top: 84px;
  color: var(--ink);
  font-weight: 700;
  line-height: 1.4;
}

.markdown-body :deep(h1) { margin: 0 0 14px; font-size: 22px; }
.markdown-body :deep(h2) { margin: 26px 0 10px; padding-bottom: 8px; border-bottom: 1px solid var(--line); font-size: 17px; }
.markdown-body :deep(h3) { margin: 20px 0 8px; font-size: 15px; }
.markdown-body :deep(h4) { margin: 16px 0 6px; font-size: 14px; }
.markdown-body :deep(p) { margin: 10px 0; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) { margin: 10px 0; padding-left: 22px; }
.markdown-body :deep(li) { margin: 4px 0; }
.markdown-body :deep(a) { color: var(--blue); text-decoration: none; }
.markdown-body :deep(a:hover) { text-decoration: underline; }
.markdown-body :deep(blockquote) {
  margin: 12px 0;
  padding: 8px 14px;
  border-left: 3px solid var(--blue);
  border-radius: 0 6px 6px 0;
  background: var(--blue2);
  color: var(--body);
}
.markdown-body :deep(code) {
  padding: 2px 5px;
  border-radius: 4px;
  background: var(--soft);
  color: var(--text-danger-strong);
  font-family: Consolas, "SF Mono", "Cascadia Mono", monospace;
  font-size: 12px;
}
.markdown-body :deep(pre) {
  position: relative;
  overflow: auto;
  border-radius: 8px;
  background: #101828;
  color: #f8fafc;
  padding: 14px;
  line-height: 1.7;
}
.markdown-body :deep(pre code) { background: transparent; color: inherit; padding: 0; font-size: 12px; }
.markdown-body :deep(table) { border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 12.5px; }
.markdown-body :deep(th),
.markdown-body :deep(td) { border: 1px solid var(--line); padding: 8px 10px; text-align: left; }
.markdown-body :deep(th) { background: var(--soft); font-weight: 700; }
.markdown-body :deep(hr) { border: 0; border-top: 1px solid var(--line); margin: 18px 0; }
.markdown-body :deep(img) { max-width: 100%; }

.markdown-body :deep(details.md-section) {
  margin: 0 0 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
  box-shadow: var(--shadow-card);
  overflow: hidden;
  scroll-margin-top: 84px;
  transition: box-shadow 0.15s ease, border-color 0.15s ease;
}
.markdown-body :deep(details.md-section[open]) { box-shadow: var(--shadow-hover); }
.markdown-body :deep(details.md-section > summary) {
  cursor: pointer;
  list-style: none;
  padding: 13px 16px;
  font-weight: 700;
  color: var(--ink);
  font-size: 15px;
  background: var(--soft);
  box-shadow: inset 3px 0 0 var(--blue);
  user-select: none;
}
.markdown-body :deep(details.md-section > summary):hover { background: var(--soft); }
.markdown-body :deep(details.md-section > summary)::-webkit-details-marker { display: none; }
.markdown-body :deep(details.md-section > summary)::before {
  content: '▸';
  display: inline-block;
  margin-right: 8px;
  color: var(--muted);
  transition: transform 0.15s ease;
}
.markdown-body :deep(details.md-section[open] > summary)::before { content: '▾'; }
.markdown-body :deep(details.md-section[open] > h3),
.markdown-body :deep(details.md-section[open] > p),
.markdown-body :deep(details.md-section[open] > ul),
.markdown-body :deep(details.md-section[open] > ol),
.markdown-body :deep(details.md-section[open] > blockquote),
.markdown-body :deep(details.md-section[open] > table) { margin-left: 14px; margin-right: 14px; }
.markdown-body :deep(details.md-section[open] > pre) { margin: 12px 14px; }
</style>

<style>
.markdown-body .code-copy {
  position: absolute;
  top: 8px;
  right: 8px;
  border: 1px solid var(--chart-line);
  border-radius: 6px;
  background: var(--chart-tooltip);
  color: var(--chart-tooltip-text);
  padding: 3px 8px;
  font-size: 11px;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.markdown-body pre:hover .code-copy { opacity: 1; }
</style>
