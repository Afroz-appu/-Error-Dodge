import test from 'node:test'
import assert from 'node:assert/strict'
import { requestApi } from '../src/apiClient.js'

test('sends credentials in headers and preserves the JSON request', async context => {
  const fetch = context.mock.method(globalThis, 'fetch', async () =>
    Response.json({ status: 'flagged' }, { status: 201 }))
  const body = JSON.stringify({ case_id: 'hallucinated' })
  const response = await requestApi('/runs', {
    method: 'POST', body, headers: { 'Content-Type': 'application/json' },
  }, 'test-fixture')
  const [url, options] = fetch.mock.calls[0].arguments
  assert.equal(url, '/api/runs')
  assert.equal(options.headers.get('Authorization'), 'Bearer test-fixture')
  assert.equal(options.headers.get('Content-Type'), 'application/json')
  assert.equal(options.cache, 'no-store')
  assert.equal(options.body, body)
  assert.equal(response.status, 'flagged')
})

test('surfaces authorization failures and handles non-JSON failures', async context => {
  const fetch = context.mock.method(globalThis, 'fetch', async () =>
    Response.json({ detail: 'Bearer credentials required' }, { status: 401 }))
  await assert.rejects(requestApi('/runs'), /Bearer credentials required/)
  assert.equal(fetch.mock.calls[0].arguments[1].headers.has('Authorization'), false)
  fetch.mock.mockImplementation(async () => new Response('Bad gateway', { status: 502 }))
  await assert.rejects(requestApi('/runs'), /Request failed \(502\)/)
})
