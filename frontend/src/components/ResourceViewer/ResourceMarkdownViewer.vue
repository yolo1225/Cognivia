<template>
  <article class="markdown-body" v-html="html" />
</template>

<script setup lang="ts">
import { marked } from 'marked'
import { computed } from 'vue'

const props = defineProps<{
  content: string
}>()

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
</script>

<style scoped>
.markdown-body {
  line-height: 1.75;
}

.markdown-body :deep(pre) {
  overflow: auto;
  border-radius: 8px;
  background: #101828;
  color: #f8fafc;
  padding: 14px;
}
</style>
