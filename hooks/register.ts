import type { EngineInterface, Register, Timer, ToolResultSummary } from 'claude-code'

import {
  AUTO_SHAKE_INSTRUCTIONS,
  CONFIG,
  type Config,
  IDLE_SHAKE_INSTRUCTIONS,
  SHAKE_INSTRUCTIONS,
  estimatedTokens,
  freedTokens,
  replaceResults,
  selectOld,
} from './shake'

type RepairExpectation = { since: number; toolIds: string[] }

const REPAIR_TIMEOUT_SECONDS = 3
const REPAIR_TIMEOUT_RETRIES = 1

const runHelper = async ($: EngineInterface, args: string[], stdin?: string) =>
  $.process.run(['python3', `${$.plugin.root}/bin/shake_io.py`, ...args], { stdin, timeoutMs: 60_000 })

const saveOriginals = async (
  $: EngineInterface,
  since: number,
  results: readonly ToolResultSummary[],
): Promise<Map<string, string>> => {
  const items = results.map(result => ({ id: result.tool_use_id, text: result.text }))
  const run = await runHelper($, ['save', await $.session.id()], JSON.stringify({ since, items }))
  if (run.exitCode !== 0) throw new Error('shake could not save the original tool results', { cause: run })
  return new Map(Object.entries(JSON.parse(run.stdout) as Record<string, string>))
}

let isCompacting = false
let isRepairPending = true
let expectation: RepairExpectation | undefined
let repairing: Promise<void> | undefined
let retryAboveTokens = 0
let timeoutRetries = 0
let idleShake: Timer | undefined

const settleRepair = ($: EngineInterface, exitCode: number): void => {
  if (exitCode === 2 && timeoutRetries < REPAIR_TIMEOUT_RETRIES) {
    timeoutRetries += 1
    return
  }
  isRepairPending = false
  expectation = undefined
  timeoutRetries = 0
  if (exitCode !== 0) $.ui.toast('shake: anchor repair gave up; a resume may load duplicates (see the debug log)')
}

const runRepair = async ($: EngineInterface): Promise<void> => {
  const expected = expectation
  const args = ['repair', await $.session.id(), '--timeout', String(REPAIR_TIMEOUT_SECONDS)]
  if (expected) args.push('--expect', JSON.stringify(expected))
  const run = await runHelper($, args).catch(error => {
    $.ui.log(`repair helper failed: ${String(error)}`, { to: 'debug' })
    return undefined
  })
  if (run) $.ui.log(`repair exit ${run.exitCode}: ${run.stdout.trim()} ${run.stderr.trim()}`, { to: 'debug' })
  if (expectation === expected) settleRepair($, run?.exitCode ?? 3)
}

const repair = ($: EngineInterface): Promise<void> =>
  (repairing ??= runRepair($)
    .catch(() => settleRepair($, 3))
    .finally(() => {
      repairing = undefined
    }))

// $.session.compact() skips this plugin's own session.compact hook; a queued /compact reaches it.
const queueShake = ($: EngineInterface, instructions: string): Promise<unknown> =>
  $.command.run({ command: 'compact', args: instructions })

export const register: Register = (on, options) => {
  const config = { ...CONFIG, ...options } as Config

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'shake-repair',
      description: 'shake: write anchors on the last shake boundary in the session file',
    })
    await $.command.register({ name: 'shake', description: 'shake: replace old tool results now' })
    return next(e)
  })

  on('command.run', { command: 'shake-repair' }, async $ => {
    await repair($)
    return { text: '' }
  })

  on('command.run', { command: 'shake' }, async $ => {
    // The engine refuses a command run from inside the running command's own hook.
    $.clock.after(0, () => {
      void queueShake($, SHAKE_INSTRUCTIONS).catch(error =>
        $.ui.log(`shake command failed: ${String(error)}`, { to: 'debug' }),
      )
    })
    return {}
  })

  on('prompt.submit', async ($, e, next) => {
    idleShake?.cancel()
    if (!e.turnId && (isRepairPending || repairing)) await repair($)
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const completed = await next(e)
    if (e.agentId) return completed
    idleShake?.cancel()
    if (config.cacheTtlMinutes > 0) {
      idleShake = $.clock.after(config.cacheTtlMinutes * 60_000, () => {
        void (async () => {
          if (selectOld(await $.session.messages()).length > 0) await queueShake($, IDLE_SHAKE_INSTRUCTIONS)
        })().catch(error => $.ui.log(`idle shake failed: ${String(error)}`, { to: 'debug' }))
      })
    }
    if (e.reason !== 'answer' || isCompacting) return completed
    isCompacting = true
    void (async () => {
      const tokens = (await $.session.usage()).context.tokens ?? 0
      if (tokens < config.thresholdTokens || tokens < retryAboveTokens) return
      await queueShake($, AUTO_SHAKE_INSTRUCTIONS)
    })()
      .catch(error => $.ui.log(`auto shake failed: ${String(error)}`, { to: 'debug' }))
      .finally(() => {
        isCompacting = false
      })
    return completed
  })

  on('session.compact', async ($, e, next) => {
    const isAuto = e.instructions === AUTO_SHAKE_INSTRUCTIONS
    const isOurs = isAuto || e.instructions === SHAKE_INSTRUCTIONS || e.instructions === IDLE_SHAKE_INSTRUCTIONS
    if (e.agentId || e.trigger === 'precompute' || !(isOurs || e.trigger === 'auto')) return next(e)
    const since = await $.clock.now()
    const old = selectOld(e.messages)
    const used = (await $.session.usage()).context.tokens ?? estimatedTokens(e.messages)
    const freed = freedTokens(old)
    if (isAuto) retryAboveTokens = used * (1 + config.floorShare)
    if ((isAuto || e.trigger !== 'manual') && freed < config.floorShare * used) {
      if (!isOurs) return next(e)
      return { skip: `shake: a shake frees about ${Math.round(freed)} tokens, below the floor` }
    }
    const savedPaths = await saveOriginals($, since, old)
    if (savedPaths.size === 0) return isOurs ? { skip: 'shake: no tool result could be saved' } : next(e)
    const messages = replaceResults(e.messages, savedPaths)
    expectation = {
      since,
      toolIds: messages.flatMap(message => (message.toolResults ?? []).map(result => result.tool_use_id)),
    }
    isRepairPending = true
    timeoutRetries = 0
    retryAboveTokens = 0
    void $.command.run({ command: 'shake-repair' }).catch(() => {
      isRepairPending = true
    })
    $.ui.toast(`shake: replaced ${savedPaths.size} old tool results`)
    return { messages }
  })
}
