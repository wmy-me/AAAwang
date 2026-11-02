export interface HealthResponse {
  status: string
  service: string
}

const HEALTH_ENDPOINT = '/api/health'

/**
 * Ask the Python API whether its process is responding.
 * In development this goes through the Vite proxy to 127.0.0.1:8000.
 */
export async function checkHealth(
  signal?: AbortSignal,
): Promise<HealthResponse> {
  const response = await fetch(HEALTH_ENDPOINT, {
    headers: { Accept: 'application/json' },
    signal,
  })

  if (!response.ok) {
    throw new Error(`后端返回 HTTP ${response.status}`)
  }

  const data: unknown = await response.json()

  if (
    typeof data !== 'object' ||
    data === null ||
    !('status' in data) ||
    typeof data.status !== 'string'
  ) {
    throw new Error('后端返回了无法识别的健康检查结果')
  }

  return data as HealthResponse
}
