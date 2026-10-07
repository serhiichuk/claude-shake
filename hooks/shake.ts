import type { SessionMessage, ToolResultSummary } from 'claude-code'

export const CONFIG = {
  thresholdPercent: 60,
  keepTokens: 16_000,
  tokensPerChar: 0.34,
  minResultChars: 2_000,
  floorShare: 0.15,
}

export type Config = typeof CONFIG

export const SHAKE_INSTRUCTIONS = 'shake'

const PREVIEW_CHARS = 500
const PLACEHOLDER_OVERHEAD_CHARS = PREVIEW_CHARS + 300
const SHAKEN_PREFIXES = ['[shaken:', '<persisted-output>', '<truncated-output>']

export const isShaken = (text: string): boolean => {
  const head = text.trimStart()
  return SHAKEN_PREFIXES.some(prefix => head.startsWith(prefix))
}

const resultsOf = (messages: readonly SessionMessage[]): ToolResultSummary[] =>
  messages.flatMap(message => message.toolResults ?? [])

export const selectOld = (messages: readonly SessionMessage[], config: Config = CONFIG): ToolResultSummary[] => {
  const keepChars = config.keepTokens / config.tokensPerChar
  const old: ToolResultSummary[] = []
  let newerChars = 0
  for (const result of resultsOf(messages).reverse()) {
    if (isShaken(result.text)) continue
    const isInKeepWindow = newerChars < keepChars
    newerChars += result.text.length
    if (!isInKeepWindow && result.text.length > config.minResultChars) old.push(result)
  }
  return old.reverse()
}

export const freedTokens = (old: readonly ToolResultSummary[], config: Config = CONFIG): number =>
  old.reduce((sum, result) => sum + Math.max(0, result.text.length - PLACEHOLDER_OVERHEAD_CHARS), 0) * config.tokensPerChar

export const estimatedTokens = (messages: readonly SessionMessage[], config: Config = CONFIG): number =>
  messages.reduce(
    (sum, message) =>
      sum +
      message.text.length +
      message.toolUses.reduce((n, use) => n + JSON.stringify(use.input).length, 0) +
      (message.toolResults ?? []).reduce((n, result) => n + result.text.length, 0),
    0,
  ) * config.tokensPerChar

const isHighSurrogate = (code: number): boolean => code >= 0xd800 && code <= 0xdbff

export const preview = (text: string, maxChars: number = PREVIEW_CHARS): { text: string; hasMore: boolean } => {
  if (text.length <= maxChars) return { text, hasMore: false }
  const newline = text.lastIndexOf('\n', maxChars - 1)
  let cut = newline > maxChars / 2 ? newline : maxChars
  if (isHighSurrogate(text.charCodeAt(cut - 1))) cut -= 1
  return { text: text.slice(0, cut), hasMore: true }
}

const formatSize = (chars: number): string => {
  if (chars < 1024) return `${chars} bytes`
  if (chars < 1024 * 1024) return `${Number((chars / 1024).toFixed(1))}KB`
  return `${Number((chars / (1024 * 1024)).toFixed(1))}MB`
}

export const placeholder = (path: string, text: string): string => {
  const cut = preview(text)
  return (
    `<persisted-output>\nOutput too large (${formatSize(text.length)}). Full output saved to: ${path}\n\n` +
    `Preview (first ${formatSize(PREVIEW_CHARS)}):\n${cut.text}${cut.hasMore ? '\n...\n' : '\n'}</persisted-output>`
  )
}

export const replaceResults = (
  messages: readonly SessionMessage[],
  savedPaths: ReadonlyMap<string, string>,
): SessionMessage[] =>
  messages.map(message => {
    if (!message.toolResults?.some(result => savedPaths.has(result.tool_use_id))) return message
    const { handle: _handle, ...rest } = message
    return {
      ...rest,
      toolResults: message.toolResults.map(result => {
        const path = savedPaths.get(result.tool_use_id)
        if (path === undefined) return result
        return { tool_use_id: result.tool_use_id, text: placeholder(path, result.text), isError: result.isError }
      }),
    }
  })
