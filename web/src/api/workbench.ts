export type ApiErrorCode = 401 | 403 | 404 | 409 | 422 | 503

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `请求失败（${status}）`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export interface User {
  id: string
  username: string
  created_at: string
}

export interface Conversation {
  id: string
  title: string | null
  created_at: string
  updated_at: string
}

export interface Task {
  id: string
  conversation_id: string
  domain: 'shopping' | 'travel'
  goal: string
  current_revision: number
  conditions: Conditions
  created_at: string
  updated_at: string
}

export interface Conditions {
  budget?: number
  people?: number
  quantity?: number
  item?: string
}

export interface Run {
  id: string
  task_id: string
  task_revision_id: string
  revision: number
  conditions: Conditions
  execution_type: 'diagnostic' | 'shopping_research' | 'shopping_agent'
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  created_at: string
  started_at: string | null
  finished_at: string | null
  attempt: number
  cancel_requested: boolean
  error_summary: string | null
}

export interface RunResult {
  run_id: string
  answer: string
  source: Record<string, unknown>
  execution_version: string
  created_at: string
  decision_type: 'direct_answer' | 'clarification' | 'delegated_discovery'
  delegated: boolean
  mcp_call_count: number
}

interface Page<T> {
  items: T[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: 'include',
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })

  if (!response.ok) {
    let detail: unknown = undefined
    try {
      const body: unknown = await response.json()
      if (typeof body === 'object' && body !== null && 'detail' in body) {
        detail = body.detail
      }
    } catch {
      detail = undefined
    }
    throw new ApiError(response.status, detail)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  body: JSON.stringify(body),
})

export const api = {
  me: () => request<User>('/me'),
  login: (username: string, password: string) =>
    request<User>('/auth/login', json({ username, password })),
  register: (username: string, password: string) =>
    request<User>('/auth/register', json({ username, password })),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),
  conversations: () => request<Page<Conversation>>('/conversations?limit=100'),
  createConversation: (title: string) =>
    request<Conversation>('/conversations', json({ title })),
  tasks: (conversationId: string) =>
    request<Page<Task>>(`/conversations/${conversationId}/tasks?limit=100`),
  createTask: (conversationId: string, goal: string, conditions: Conditions) =>
    request<Task>(
      `/conversations/${conversationId}/tasks`,
      json({ domain: 'shopping', goal, conditions }),
    ),
  updateTask: (
    taskId: string,
    expectedRevision: number,
    conditions: Conditions,
    changeNote: string,
  ) =>
    request<{ revision: number }>(
      `/tasks/${taskId}/revisions`,
      json({ expected_revision: expectedRevision, conditions, change_note: changeNote || undefined }),
    ),
  getTask: (taskId: string) => request<Task>(`/tasks/${taskId}`),
  runs: (taskId: string) => request<Page<Run>>(`/tasks/${taskId}/runs?limit=100`),
  createRun: (taskId: string, revision: number, idempotencyKey: string) =>
    request<Run>(
      `/tasks/${taskId}/runs`,
      json({ expected_revision: revision, idempotency_key: idempotencyKey, execution_type: 'shopping_agent' }),
    ),
  getRun: (runId: string) => request<Run>(`/runs/${runId}`),
  cancelRun: (runId: string) => request<Run>(`/runs/${runId}/cancel`, { method: 'POST' }),
  result: (runId: string) => request<RunResult>(`/runs/${runId}/result`),
}

export function detailMessage(error: unknown, fallback = '请求没有完成，请稍后再试。') {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : fallback
  if (typeof error.detail === 'object' && error.detail !== null && 'message' in error.detail) {
    return String(error.detail.message)
  }
  if (typeof error.detail === 'string') return error.detail
  if (error.status === 401) return '登录状态已失效，请重新登录。'
  if (error.status === 403) return '请求被安全策略拒绝，请从当前页面重试。'
  if (error.status === 409) return '任务版本已变化，页面正在刷新最新条件。'
  if (error.status === 503) return '服务暂时不可用，请稍后重试。'
  return fallback
}

export function isAuthError(error: unknown) {
  return error instanceof ApiError && error.status === 401
}
