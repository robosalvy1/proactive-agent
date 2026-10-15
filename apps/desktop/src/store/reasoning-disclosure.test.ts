import { expect, it, vi } from 'vitest'

import { $showReasoning, setShowReasoningFromConfig } from './reasoning-disclosure'

// These config tests use a primary window without starting desktop services.
vi.mock('@/store/windows', () => ({
  isBrowserWindow: () => false,
  isHudWindow: () => false,
  isSecondaryWindow: () => false
}))

it('keeps reasoning hidden before shared config arrives', () => {
  expect($showReasoning.get()).toBe(false)
})

it.each([
  [true, true],
  [1, true],
  ['true', true],
  ['1', true],
  ['yes', true],
  ['on', true],
  ['raw', true],
  ['verbose', true],
  [' YES ', true],
  [' On ', true],
  [false, false],
  [0, false],
  ['false', false],
  ['0', false],
  ['no', false],
  ['off', false],
  ['', false],
  ['unknown', false],
  [null, false],
  [undefined, false]
])('applies display.show_reasoning %j as %s', (value, expected) => {
  setShowReasoningFromConfig(!expected)
  setShowReasoningFromConfig(value)
  expect($showReasoning.get()).toBe(expected)
})
