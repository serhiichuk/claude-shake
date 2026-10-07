import type { SessionMessage } from 'claude-code'
import { expect, test } from 'claude-code/testing'

import { CONFIG, placeholder, preview, replaceResults, selectOld } from '../hooks/shake'

const call = (id: string): SessionMessage => ({
  role: 'assistant',
  text: '',
  toolUses: [{ tool_use_id: id, tool: 'Read', input: { file_path: `/${id}` } }],
  handle: `a-${id}`,
})

const answer = (id: string, text: string, isError = false): SessionMessage => ({
  role: 'user',
  text: '',
  toolUses: [],
  toolResults: [{ tool_use_id: id, text, isError }],
  handle: `u-${id}`,
})

const big = (chars: number) => 'x'.repeat(chars)
const keepChars = CONFIG.keepTokens / CONFIG.tokensPerChar

const session: SessionMessage[] = [
  call('old-big'), answer('old-big', big(30_000), true),
  call('old-small'), answer('old-small', big(CONFIG.minResultChars)),
  call('shaken'), answer('shaken', `<persisted-output>\n${big(5_000)}`),
  call('legacy'), answer('legacy', `[shaken: ${big(5_000)}]`),
  call('truncated'), answer('truncated', `<truncated-output>${big(5_000)}`),
  call('edge'), answer('edge', big(3_000)),
  call('window'), answer('window', big(Math.ceil(keepChars) - 10)),
  call('newest'), answer('newest', big(100)),
]

test('selects only old, large, unshaken results outside the keep window', () => {
  const ids = selectOld(session).map(result => result.tool_use_id)
  expect(ids).toEqual(['old-big', 'edge'])
})

test('the newest result stays even when it alone exceeds the window', () => {
  expect(selectOld([call('a'), answer('a', big(200_000))])).toEqual([])
})

test('a shaken placeholder does not fill the keep window', () => {
  const messages = [
    call('older'), answer('older', big(3_000)),
    call('placeholder'), answer('placeholder', `<persisted-output>\n${big(Math.ceil(keepChars) + 10)}`),
  ]
  expect(selectOld(messages)).toEqual([])
})

test('replacement keeps assistants, unchanged handles, ids and is_error', () => {
  const out = replaceResults(session, new Map([['old-big', '/saved/old-big.txt']]))
  expect(out.length).toBe(session.length)
  session.forEach((message, i) => {
    if (message.role === 'assistant' || i !== 1) expect(out[i]).toEqual(message)
  })
  const changed = out[1]!
  expect(changed.handle).toBeUndefined()
  expect(changed.toolResults?.[0]?.tool_use_id).toBe('old-big')
  expect(changed.toolResults?.[0]?.isError).toBe(true)
  expect(changed.toolResults?.[0]?.text.startsWith('<persisted-output>\nOutput too large (29.3KB). Full output saved to: /saved/old-big.txt\n')).toBe(true)
})

test('preview never splits a surrogate pair', () => {
  const text = `${'a'.repeat(499)}\u{1F600}${'b'.repeat(600)}`
  const cut = preview(text)
  expect(cut.hasMore).toBe(true)
  expect(cut.text).toBe('a'.repeat(499))
  expect(placeholder('/p', text).includes('\uD83D')).toBe(false)
})

test('preview prefers a newline in the second half', () => {
  const text = `${'a'.repeat(400)}\n${'b'.repeat(600)}`
  expect(preview(text).text).toBe('a'.repeat(400))
})
