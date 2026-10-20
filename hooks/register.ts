import type { EngineInterface, Register, Timer } from 'claude-code'

import { CONFIG, type Config, freedTokens, placeholder, selectOld } from './shake'

type Trigger = 'manual' | 'threshold' | 'idle'

const DEFAULT_CACHE_TTL_MINUTES = 60
// Waits past the TTL with a margin, as omp does (90 min for the 1 h TTL): a shake on a still-warm cache pays a full cache write.
const CACHE_EXPIRY_MARGIN = 1.5

const runHelper = async ($: EngineInterface, args: string[], stdin?: string) =>
  $.process.run(['python3', `${$.plugin.root}/bin/shake_io.py`, ...args], { stdin, timeoutMs: 60_000 })

const runJson = async <T>($: EngineInterface, args: string[], stdin: unknown): Promise<T> => {
  const run = await runHelper($, args, JSON.stringify(stdin))
  if (run.exitCode !== 0) throw new Error(`shake_io ${args[0]} exit ${run.exitCode}: ${run.stdout.trim()}`)
  return JSON.parse(run.stdout) as T
}

let writing: Promise<void> | undefined
let retryAboveTokens = 0
let idleShake: Timer | undefined
let idleArmings = 0

const plural = (count: number, noun: string): string => `${count} ${noun}${count === 1 ? '' : 's'}`

// Rewrites the tool results in the session file; the live process sends them only after the queued /resume reloads it.
const shake = async ($: EngineInterface, config: Config, trigger: Trigger): Promise<void> => {
  const old = selectOld(await $.session.messages())
  if (old.length === 0) {
    if (trigger === 'manual') $.ui.log('Nothing to shake.')
    return
  }
  if (trigger === 'threshold') {
    const tokens = (await $.session.usage()).context.tokens ?? 0
    if (tokens < config.thresholdTokens || tokens < retryAboveTokens) return
    // Also stops a retry each turn when the reload fails (headless): the next try waits until the context grows.
    retryAboveTokens = tokens * (1 + config.floorShare)
    if (freedTokens(old) < config.floorShare * tokens) return
  }
  const id = await $.session.id()
  const write = (async () => {
    const items = old.map(result => ({ id: result.tool_use_id, text: result.text }))
    const saved = await runJson<Record<string, string>>($, ['save', id], { items })
    const replacements = Object.fromEntries(
      old.filter(result => saved[result.tool_use_id]).map(r => [r.tool_use_id, placeholder(saved[r.tool_use_id]!, r.text)]),
    )
    return runJson<{ replaced: string[] }>($, ['shake', id], replacements)
  })()
  writing = write.then(() => undefined, () => undefined)
  const { replaced } = await write.finally(() => {
    writing = undefined
  })
  if (replaced.length === 0) {
    if (trigger === 'manual') $.ui.log('Nothing to shake.')
    return
  }
  await $.command.run({ command: 'resume', args: id })
  retryAboveTokens = 0
  // An id repeats in the list for each row it was replaced in (copies from before a compaction boundary).
  const shaken = old.filter(result => replaced.includes(result.tool_use_id))
  $.ui.log(`Shook ${plural(shaken.length, 'tool result')} (~${Math.round(freedTokens(shaken))} tokens freed).`)
}

let shaking: Promise<void> | undefined

const startShake = ($: EngineInterface, config: Config, trigger: Trigger): void => {
  shaking ??= shake($, config, trigger)
    .catch(error => $.ui.log(`${trigger} shake failed: ${String(error)}`, { to: 'debug' }))
    .finally(() => {
      shaking = undefined
    })
}

type CacheState = { lastRequestMs: number | null; ttlMinutes: number | null }

const readCache = async ($: EngineInterface): Promise<CacheState> => {
  const run = await runHelper($, ['cache', await $.session.id()])
  if (run.exitCode !== 0) throw new Error('shake could not read the session cache state', { cause: run })
  return JSON.parse(run.stdout) as CacheState
}

// Fires when the prompt cache expires: then the next request writes it whole anyway, so a shake is free.
const armIdleShake = async ($: EngineInterface, config: Config, lastRequestMs?: number): Promise<void> => {
  const arming = ++idleArmings
  idleShake?.cancel()
  if (!config.idleShake) return
  const cache = await readCache($)
  const since = lastRequestMs ?? cache.lastRequestMs
  if (since === null) return
  const ttlMinutes = config.cacheTtlMinutes || cache.ttlMinutes || DEFAULT_CACHE_TTL_MINUTES
  const delay = Math.max(0, since + ttlMinutes * CACHE_EXPIRY_MARGIN * 60_000 - (await $.clock.now()))
  if (arming !== idleArmings) return
  idleShake = $.clock.after(delay, () => startShake($, config, 'idle'))
}

const logIdleError = ($: EngineInterface) => (error: unknown) =>
  $.ui.log(`idle shake timer failed: ${String(error)}`, { to: 'debug' })

export const register: Register = (on, options) => {
  const config = { ...CONFIG, ...options } as Config

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'shake', description: 'shake: replace old tool results now' })
    void armIdleShake($, config).catch(logIdleError($))
    return next(e)
  })

  on('command.run', { command: 'shake' }, async $ => {
    // The engine refuses a command run from inside the running command's own hook.
    $.clock.after(0, () => startShake($, config, 'manual'))
    return {}
  })

  on('prompt.submit', async (_, e, next) => {
    idleArmings += 1
    idleShake?.cancel()
    // Waits for the file rewrite only: the queued /resume runs after this turn.
    if (!e.turnId && writing) await writing
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const completed = await next(e)
    if (e.agentId) return completed
    void (async () => armIdleShake($, config, await $.clock.now()))().catch(logIdleError($))
    if (e.reason === 'answer') startShake($, config, 'threshold')
    return completed
  })
}
