import type { HomeActionResult } from '@hermes/shared/gateway-events'

import type { SlashCommand } from '../types.js'

export const homeCommands: SlashCommand[] = [
  {
    help: 'open Home or manage cross-chat recall',
    name: 'home',
    usage: '/home [status | overview | share | exclude | off | on | dream [on|off|now|status|notes|clear]]',
    run: (arg, ctx) => {
      if (ctx.session.guardBusySessionSwitch('opening Home')) {
        return
      }

      ctx.gateway
        .rpc<HomeActionResult>('home.action', { session_id: ctx.sid, action: arg.trim().toLowerCase() })
        .then(
          ctx.guarded<HomeActionResult>(result => {
            ctx.transcript.sys(result.output)

            if (result.session_id) {
              void Promise.resolve(ctx.session.resumeById(result.session_id)).catch(ctx.guardedErr)
            }
          })
        )
        .catch(ctx.guardedErr)
    }
  }
]
