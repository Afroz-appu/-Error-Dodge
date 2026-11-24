// The caller supplies the in-memory credential. It never enters URLs or storage.
export async function requestApi(path, options, token = '') {
  const headers = new Headers(options?.headers)
  if (token) headers.set('Authorization', 'Bearer ' + token)
  const response = await fetch('/api' + path, { ...options, headers, cache: 'no-store' })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Request failed (' + response.status + ')')
  }
  return response.json()
}
