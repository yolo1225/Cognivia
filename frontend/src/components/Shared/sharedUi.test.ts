import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { describe, expect, it } from 'vitest'
import PageHeader from './PageHeader.vue'
import PageState from './PageState.vue'
import StatusBadge from './StatusBadge.vue'

async function render(component: object, props: Record<string, unknown> = {}, slots: Record<string, () => unknown> = {}) {
  return renderToString(createSSRApp({ render: () => h(component, props, slots) }))
}

describe('shared UI patterns', () => {
  it('renders a consistent page heading and actions', async () => {
    const html = await render(PageHeader, { title: '领域管理', description: '管理领域知识资产' }, {
      actions: () => h('button', { type: 'button' }, '刷新'),
    })
    expect(html).toContain('<h1>领域管理</h1>')
    expect(html).toContain('管理领域知识资产')
    expect(html).toContain('>刷新</button>')
  })

  it.each([
    ['success', 'ok'], ['warning', 'wait'], ['danger', 'error'], ['info', 'info'],
    ['neutral', 'neutral'], ['ok', 'ok'], ['wait', 'wait'], ['error', 'error'],
  ] as const)('maps %s status to %s styling', async (type, expectedClass) => {
    const html = await render(StatusBadge, { label: '状态', type })
    expect(html).toContain(`class="status ${expectedClass}"`)
  })

  it('marks error states as alerts and exposes retry content', async () => {
    const html = await render(PageState, { type: 'error', title: '加载失败', description: '请稍后重试' }, {
      default: () => h('button', { type: 'button' }, '重新加载'),
    })
    expect(html).toContain('role="alert"')
    expect(html).toContain('<h2>加载失败</h2>')
    expect(html).toContain('重新加载')
  })

  it('marks loading states as busy', async () => {
    const html = await render(PageState, { type: 'loading' })
    expect(html).toContain('aria-busy="true"')
  })
})
