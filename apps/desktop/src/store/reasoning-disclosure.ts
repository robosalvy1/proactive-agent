import { atom } from 'nanostores'

import { persistBoolean, storedBoolean } from '@/lib/storage'
import { modeBound } from '@/store/interface-mode'

const REASONING_COLLAPSED_BY_DEFAULT_STORAGE_KEY = 'hermes.desktop.reasoning.collapsedByDefault'

/** Desktop-local presentation preference; shared backend config must not be changed by a single window.
 *  Simple mode rests reasoning collapsed without touching this preference. */
const $reasoningCollapsedByDefaultPref = atom(storedBoolean(REASONING_COLLAPSED_BY_DEFAULT_STORAGE_KEY, false))

$reasoningCollapsedByDefaultPref.subscribe(value => persistBoolean(REASONING_COLLAPSED_BY_DEFAULT_STORAGE_KEY, value))

export const $reasoningCollapsedByDefault = modeBound(
  'reasoningCollapsedByDefault',
  $reasoningCollapsedByDefaultPref,
  value => $reasoningCollapsedByDefaultPref.set(value)
)

export function setReasoningCollapsedByDefault(value: boolean) {
  $reasoningCollapsedByDefault.set(value)
}

// Mirrors `display.show_reasoning` (Settings → Chat → Reasoning Blocks).
// Off by default; explicit enabled values follow the shared display-config contract.
export const $showReasoning = atom(false)

export function setShowReasoningFromConfig(value: unknown): void {
  const normalized = typeof value === 'string' ? value.trim().toLowerCase() : value

  $showReasoning.set(
    normalized === true ||
      normalized === 1 ||
      (typeof normalized === 'string' && ['true', '1', 'yes', 'on', 'raw', 'verbose'].includes(normalized))
  )
}
