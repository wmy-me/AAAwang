export type ApiErrorCode = 401 | 403 | 404 | 409 | 422 | 502 | 503 | 504

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
  goal_conflicts: Array<Record<string, unknown>> | null
  goal_resolution: string | null
  goal_legacy: boolean
  created_at: string
  updated_at: string
}

export interface Conditions {
  budget?: number
  people?: number
  quantity?: number
  item?: string
  color?: string
  use_case?: string
  destination?: string
  start_date?: string
  end_date?: string
  activity_types?: string[]
}

export interface FormField {
  id: string
  control: 'short_text' | 'number' | 'money' | 'date' | 'single_select' | 'multi_select' | 'location'
  label: string
  reason: string
  required: boolean
  unit?: string | null
  options?: string[] | null
  min_value?: number | null
  max_value?: number | null
}

export interface DynamicFormProposal {
  id: string
  task_id: string
  task_revision_id: string
  revision: number
  schema: FormField[]
  source: string
  status: 'pending' | 'confirmed'
  confirmed_values: Record<string, unknown> | null
  created_at: string
  confirmed_at: string | null
}

export interface Run {
  id: string
  task_id: string
  task_revision_id: string
  revision: number
  conditions: Conditions
  execution_type: 'diagnostic' | 'capability_decision' | 'direct_answer' | 'shopping_research' | 'shopping_agent' | 'map_places' | 'weather' | 'web_search' | 'capability_router'
  capability_ids: string[] | null
  decision: Record<string, unknown> | null
  budget: Record<string, unknown> | null
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

export interface ShoppingCandidate {
  id: string
  product_id: string
  name: string
  unit_price: string
  currency: string
  unit: string
  distributable_units: number
  source_type: string
  source_service: string
  simulated: boolean
  availability: string
  quoted_at: string | null
  queried_at: string
}

export interface ShoppingPlan {
  run_id: string
  revision: number
  status: string
  people: number
  covered_people: number
  budget: string
  total: string
  remaining: string
  currency: string
  unknown_fees: boolean
  note: string
  created_at: string
  items: Array<{
    candidate_id: string
    package_quantity: number
    covered_people: number
    subtotal: string
    candidate: ShoppingCandidate
  }>
}

export interface ShoppingArtifacts {
  candidates: ShoppingCandidate[]
  plan: ShoppingPlan | null
}

export interface MapPlace {
  id: string
  run_id: string
  revision: number
  name: string
  address: string | null
  location: string | null
  phone: string | null
  url: string | null
  query: string
  city: string
  source_service: string
  source_tool: string
  observed_at: string
}

export interface WeatherSnapshot {
  run_id: string
  revision: number
  city: string
  source_service: string
  source_tool: string
  queried_at: string
  forecasts: Array<{
    date: string | null
    week: string | null
    day_weather: string | null
    night_weather: string | null
    day_temperature: string | null
    night_temperature: string | null
    day_wind: string | null
    night_wind: string | null
    day_wind_power: string | null
    night_wind_power: string | null
  }>
}

export interface WebSearchResult {
  id: string
  run_id: string
  revision: number
  title: string
  url: string
  summary: string | null
  published_at: string | null
  source_service: string
  source_tool: string
  observed_at: string
}

export interface ShoppingAdjustment {
  id: string
  owner_id: string
  task_id: string
  task_revision_id: string
  base_run_id: string
  version: number
  client_request_id: string
  source: string
  status: string
  is_current: boolean
  people: number
  covered_people: number
  budget: string
  total: string
  remaining: string
  currency: string
  unknown_fees: boolean
  note: string
  created_at: string
  items: Array<{
    candidate_id: string
    package_quantity: number
    covered_people: number
    subtotal: string
    candidate: ShoppingCandidate
  }>
}

export interface ShoppingAdjustmentList {
  items: ShoppingAdjustment[]
  current_version: number
}

export interface Message {
  id: string
  conversation_id: string
  client_message_id: string
  role: 'user' | 'assistant'
  content: string
  task_id: string | null
  run_id: string | null
  created_at: string
}

export interface ChatTurnResponse {
  message: Message
  run: Run
  task: Task
  assistant_message: Message | null
}

export interface FormSubmitResponse {
  message: Message
  run: Run
  task: Task
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
  messages: (conversationId: string) =>
    request<Page<Message>>(`/conversations/${conversationId}/messages?limit=100`),
  createTask: (conversationId: string, goal: string, conditions: Conditions) =>
    request<Task>(
      `/conversations/${conversationId}/tasks`,
      json({ domain: 'shopping', goal, conditions }),
    ),
  updateTask: (
    taskId: string,
    expectedRevision: number,
    goal: string,
    conditions: Conditions,
    changeNote: string,
    confirmGoalConflict: boolean,
  ) =>
    request<{ revision: number }>(
      `/tasks/${taskId}/revisions`,
      json({ expected_revision: expectedRevision, goal, conditions, change_note: changeNote || undefined, confirm_goal_conflict: confirmGoalConflict }),
    ),
  getTask: (taskId: string) => request<Task>(`/tasks/${taskId}`),
  getDynamicForm: (taskId: string) => request<DynamicFormProposal>(`/tasks/${taskId}/form`),
  submitDynamicForm: (
    taskId: string,
    proposalId: string,
    expectedRevision: number,
    values: Record<string, unknown>,
  ) => request<FormSubmitResponse>(
    `/tasks/${taskId}/form/submit`,
    json({
      proposal_id: proposalId,
      expected_revision: expectedRevision,
      client_request_id: crypto.randomUUID(),
      values,
    }),
  ),
  runs: (taskId: string) => request<Page<Run>>(`/tasks/${taskId}/runs?limit=100`),
  createRun: (taskId: string, revision: number, idempotencyKey: string) =>
    request<Run>(
      `/tasks/${taskId}/runs`,
      json({ expected_revision: revision, idempotency_key: idempotencyKey, execution_type: 'shopping_agent' }),
    ),
  getRun: (runId: string) => request<Run>(`/runs/${runId}`),
  cancelRun: (runId: string) => request<Run>(`/runs/${runId}/cancel`, { method: 'POST' }),
  result: (runId: string) => request<RunResult>(`/runs/${runId}/result`),
  shoppingArtifacts: (runId: string) =>
    request<ShoppingArtifacts>(`/runs/${runId}/shopping-artifacts`),
  mapPlaces: (runId: string) => request<MapPlace[]>(`/runs/${runId}/map-places`),
  weather: (runId: string) => request<WeatherSnapshot>(`/runs/${runId}/weather`),
  webSearch: (runId: string) => request<WebSearchResult[]>(`/runs/${runId}/web-search`),
  shoppingAdjustments: (taskId: string) =>
    request<ShoppingAdjustmentList>(`/tasks/${taskId}/shopping-adjustments`),
  createShoppingAdjustment: (
    taskId: string,
    baseRunId: string,
    revision: number,
    expectedVersion: number,
    items: Array<{ candidate_id: string; package_quantity: number }>,
  ) =>
    request<ShoppingAdjustment>(
      `/tasks/${taskId}/shopping-adjustments`,
      json({
        base_run_id: baseRunId,
        expected_revision: revision,
        expected_adjustment_version: expectedVersion,
        client_request_id: crypto.randomUUID(),
        items,
      }),
    ),
  submitTurn: (
    conversationId: string,
    taskId: string,
    clientTurnId: string,
    content: string,
    expectedRevision: number,
  ) =>
    request<ChatTurnResponse>(
      `/conversations/${conversationId}/tasks/${taskId}/turns`,
      json({ client_turn_id: clientTurnId, content, task_id: taskId, expected_revision: expectedRevision }),
    ),
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
