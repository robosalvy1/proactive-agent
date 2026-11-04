// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { HomeChatButton } from './HomeChatButton'

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const { fetchJSON } = vi.hoisted(() => ({ fetchJSON: vi.fn() }))
vi.mock('@/lib/api', () => ({ fetchJSON }))
vi.mock('@/i18n', () => ({ useI18n: () => ({ t: { common: { loading: 'Loading', error: 'Error' }, sessions: { homeChat: 'Home' } } }) }))
vi.mock('@nous-research/ui/ui/components/button', () => ({
  Button: ({ children, onClick, disabled }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button type="button" onClick={onClick} disabled={disabled}>{children}</button>
  )
}))

let container: HTMLDivElement
let root: Root
beforeEach(() => {
  fetchJSON.mockReset()
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

it('opens the persistent destination in the selected profile', async () => {
  const onOpen = vi.fn()
  fetchJSON.mockResolvedValue({ session_id: 'persistent-home' })
  await act(async () => root.render(<HomeChatButton profile="work" onOpen={onOpen} />))
  await act(async () => container.querySelector('button')!.click())
  expect(fetchJSON).toHaveBeenCalledWith('/api/home/open?profile=work', expect.objectContaining({ method: 'POST' }))
  expect(onOpen).toHaveBeenCalledWith('persistent-home')
})

it('shows an actionable failure and allows retry without removing other chat controls', async () => {
  fetchJSON.mockRejectedValueOnce(new Error('Home unavailable')).mockResolvedValueOnce({ session_id: 'home' })
  const onOpen = vi.fn()
  await act(async () => root.render(<HomeChatButton profile="work" onOpen={onOpen} />))
  await act(async () => container.querySelector('button')!.click())
  expect(container.querySelector('[role=alert]')!.textContent).toBe('Home unavailable')
  await act(async () => container.querySelector('button')!.click())
  expect(onOpen).toHaveBeenCalledWith('home')
})

it('does not navigate to the old profile when its pending request completes late', async () => {
  let finish!: (value: { session_id: string }) => void
  fetchJSON.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const onOpen = vi.fn()
  await act(async () => root.render(<HomeChatButton key="work" profile="work" onOpen={onOpen} />))
  await act(async () => container.querySelector('button')!.click())
  await act(async () => root.render(<HomeChatButton key="personal" profile="personal" onOpen={onOpen} />))
  await act(async () => finish({ session_id: 'work-home' }))
  expect(onOpen).not.toHaveBeenCalled()
})
