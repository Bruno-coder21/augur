/**
 * Augur status chip for Hermes Desktop.
 *
 * "🧭 Hackathons · 62% on goals" in the status bar; click for the week at a glance.
 * Data comes from the Python half: RPC `plugin.augur.status` on load and focus
 * change, and the session event `plugin.augur.status.changed` after every
 * classified request. Plain ESM, no build step, SDK surface only.
 */

import {
  atom, cn, host, Popover, PopoverContent, PopoverTrigger, STATUSBAR_AREAS, Tip, usePluginI18n, useValue
} from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'augur'
// The same goal colors as the terminal panel and the PNG report (color-blind safe).
const GOAL_COLORS = { 1: '#3B82F6', 2: '#F59E0B', 3: '#A855F7', 0: '#6B7280' }

const EN = {
  onGoals: pct => `${pct}% on goals`,
  noGoals: 'Set your goals',
  tip: 'Augur: where your requests went this week',
  week: 'Last 7 days',
  detours: 'Detours',
  planned: planned => `planned ${planned}%`,
  queue: n => `Queue: ${n} parked`,
  hidden: (theme, count) => `Hidden priority: ${theme} (${count} requests)`,
  setup: 'Type /augur goals in the chat to set your 3 goals.',
  more: 'Full panel: /augur · report: /augur report',
  demo: 'includes demo data'
}
const PT = {
  onGoals: pct => `${pct}% nas metas`,
  noGoals: 'Defina suas metas',
  tip: 'Augur: para onde foram seus pedidos nesta semana',
  week: 'Últimos 7 dias',
  detours: 'Desvios',
  planned: planned => `planejado ${planned}%`,
  queue: n => `Fila: ${n} estacionados`,
  hidden: (theme, count) => `Prioridade oculta: ${theme} (${count} pedidos)`,
  setup: 'Digite /augur goals no chat para definir suas 3 metas.',
  more: 'Painel completo: /augur · relatório: /augur report',
  demo: 'inclui dados de demonstração'
}

function Bar({ row, t }) {
  const color = GOAL_COLORS[row.slot] || GOAL_COLORS[0]
  return jsxs('div', { className: 'flex flex-col gap-1', children: [
    jsxs('div', { className: 'flex items-baseline justify-between gap-3 text-xs', children: [
      jsx('span', { className: 'font-medium text-foreground', children: row.name }),
      jsx('span', { className: 'text-(--ui-text-tertiary)', children: row.slot === 0
        ? `${row.pct}%`
        : `${row.pct}% · ${t('planned', row.planned)}` })
    ] }),
    jsxs('div', { className: 'relative h-2 w-full overflow-hidden rounded-full bg-(--ui-surface-sunken)', children: [
      row.planned ? jsx('div', { className: 'absolute inset-y-0 left-0 rounded-full', style: { width: `${row.planned}%`, background: color, opacity: 0.25 } }) : null,
      jsx('div', { className: 'absolute inset-y-0 left-0 rounded-full', style: { width: `${row.pct}%`, background: color } })
    ] })
  ] })
}

function Panel({ status, t }) {
  if (!status || !status.has_goals) {
    return jsx('div', { className: 'p-3 text-xs text-(--ui-text-secondary)', children: t('setup') })
  }
  return jsxs('div', { className: 'flex w-72 flex-col gap-3 p-3', children: [
    jsxs('div', { className: 'flex items-center justify-between text-xs text-(--ui-text-tertiary)', children: [
      jsx('span', { children: `🧭 ${t('week')}` }),
      status.has_demo ? jsx('span', { children: t('demo') }) : null
    ] }),
    ...status.rows.map(row => jsx(Bar, { row: row.slot === 0 ? { ...row, name: t('detours') } : row, t }, row.slot)),
    jsx('div', { className: 'text-xs text-(--ui-text-secondary)', children: t('queue', status.parked) }),
    status.hidden
      ? jsx('div', { className: 'rounded-md border border-(--ui-border) px-2 py-1.5 text-xs text-foreground',
          children: t('hidden', status.hidden.theme, status.hidden.count) })
      : null,
    jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: t('more') })
  ] })
}

function Chip({ store }) {
  const status = useValue(store)
  const lang = status && status.language === 'pt' ? 'pt' : 'en'
  const t = usePluginI18n(ID)
  const tr = (key, ...args) => {
    const table = lang === 'pt' ? PT : EN
    const value = table[key]
    return typeof value === 'function' ? value(...args) : (value || t(key))
  }
  const label = !status || !status.has_goals
    ? `🧭 ${tr('noGoals')}`
    : `🧭 ${status.current_goal ? `${status.current_goal} · ` : ''}${status.on_goals_pct == null ? '–' : tr('onGoals', status.on_goals_pct)}`
  return jsxs(Popover, { children: [
    jsx(Tip, { label: tr('tip'), children: jsx(PopoverTrigger, { asChild: true, children: jsx('button', {
      type: 'button',
      className: cn(
        'inline-flex h-full items-center gap-1 px-1.5 text-[0.6875rem] transition-colors',
        'text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground'
      ),
      children: label
    }) }) }),
    jsx(PopoverContent, { side: 'top', align: 'end', children: jsx(Panel, { status, t: tr }) })
  ] })
}

export default {
  id: ID,
  name: 'Augur',
  description: 'Your week against your 3 goals, in the status bar.',
  register(ctx) {
    ctx.i18n.register({ en: { tip: EN.tip, noGoals: EN.noGoals }, pt: { tip: PT.tip, noGoals: PT.noGoals } })
    const store = atom(null)

    const refresh = async () => {
      try {
        const session_id = host.state.focusedSessionId.get()
        const status = await host.request('plugin.augur.status', session_id ? { session_id } : {})
        if (status && typeof status === 'object') store.set(status)
      } catch {
        // gateway without plugin RPC, or Augur disabled: keep the last value
      }
    }

    ctx.onEvent('plugin.augur.status.changed', event => {
      const payload = event && event.payload
      if (payload && typeof payload === 'object') store.set(payload)
    })
    ctx.onDispose(host.state.focusedSessionId.listen(() => { void refresh() }))
    ctx.setInterval(() => { void refresh() }, 60000)
    void refresh()

    ctx.register({ id: 'chip', area: STATUSBAR_AREAS.right, order: 120, render: () => jsx(Chip, { store }) })
  }
}
