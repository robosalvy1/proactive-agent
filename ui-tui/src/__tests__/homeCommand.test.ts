import { expect, it, vi } from 'vitest'

import { homeCommands } from '../app/slash/commands/home.js'

function context() {
  return {
    sid: 'side-chat',
    gateway: { rpc: vi.fn(async () => ({ output: 'Home is ready.', session_id: 'home-chat' })) },
    session: { guardBusySessionSwitch: vi.fn(() => false), resumeById: vi.fn(async () => {}) },
    transcript: { sys: vi.fn() },
    guarded: (fn: (result: unknown) => void) => fn,
    guardedErr: vi.fn()
  }
}

it('resolves Home through the owner and resumes through the existing session flow', async () => {
  const ctx = context()
  homeCommands[0]!.run('', ctx as any, 'home')
  await vi.waitFor(() => expect(ctx.session.resumeById).toHaveBeenCalledWith('home-chat'))
  expect(ctx.gateway.rpc).toHaveBeenCalledWith('home.action', { session_id: 'side-chat', action: '' })
})

it('does not navigate away from a busy chat', () => {
  const ctx = context()
  ctx.session.guardBusySessionSwitch.mockReturnValue(true)
  homeCommands[0]!.run('', ctx as any, 'home')
  expect(ctx.gateway.rpc).not.toHaveBeenCalled()
})

it('changes dreaming through the owner without switching chats', async () => {
  const ctx = context()
  ctx.gateway.rpc.mockResolvedValue({ output: 'Dreaming is on.' } as any)
  homeCommands[0]!.run('dream on', ctx as any, 'home')
  await vi.waitFor(() => expect(ctx.transcript.sys).toHaveBeenCalledWith('Dreaming is on.'))
  expect(ctx.gateway.rpc).toHaveBeenCalledWith('home.action', { session_id: 'side-chat', action: 'dream on' })
  expect(ctx.session.resumeById).not.toHaveBeenCalled()
})

it('does not apply a delayed Home result after the user switched chats', async () => {
  const ctx = context()

  ctx.guarded = () => () => {}

  homeCommands[0]!.run('', ctx as any, 'home')

  await Promise.resolve()
  expect(ctx.session.resumeById).not.toHaveBeenCalled()
})
