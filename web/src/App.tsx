import { useEffect, useRef, useState } from 'react'
import { ApiError, api, detailMessage, isAuthError, type Conditions, type Conversation, type Message, type Run, type RunResult, type Task, type User } from './api/workbench'
import './App.css'

type AuthMode = 'login' | 'register'

function App() {
  const [user, setUser] = useState<User | null>(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [authMode, setAuthMode] = useState<AuthMode>('login')
  const [authError, setAuthError] = useState('')
  const [busy, setBusy] = useState(false)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [conversationId, setConversationId] = useState('')
  const [, setTasks] = useState<Task[]>([])
  const [task, setTask] = useState<Task | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [selectedRunId, setSelectedRunId] = useState('')
  const [result, setResult] = useState<RunResult | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [chatInput, setChatInput] = useState('')
  const [turnSubmitting, setTurnSubmitting] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [showTaskForm, setShowTaskForm] = useState(false)
  const eventSource = useRef<EventSource | null>(null)
  const stopWatcher = useRef<(() => void) | null>(null)
  const runSubmitting = useRef(false)
  const selectedRunIdRef = useRef('')
  const watchGeneration = useRef(0)

  useEffect(() => {
    api.me().then(setUser).catch(() => undefined).finally(() => setAuthChecked(true))
  }, [])

  useEffect(() => {
    if (!user) return
    void refreshWorkspace()
    return () => stopWatcher.current?.()
  }, [user])

  useEffect(() => {
    if (!conversationId) return
    api.tasks(conversationId).then((page) => {
      setTasks(page.items)
      setTask((current) => page.items.find((item) => item.id === current?.id) ?? page.items[0] ?? null)
    }).catch(handleError)
  }, [conversationId])

  useEffect(() => {
    if (!task) return
    api.runs(task.id).then((page) => {
      setRuns(page.items)
      const active = page.items.find((run) => run.id === selectedRunIdRef.current) ?? page.items[0]
      if (active) selectRun(active)
    }).catch(handleError)
  }, [task])

  useEffect(() => {
    if (!task) { setMessages([]); return }
    void refreshTaskMessages(task.conversation_id, task.id)
  }, [task])

  function handleError(value: unknown) {
    if (isAuthError(value)) {
      setUser(null); setConversations([]); setTasks([]); setTask(null); setRuns([]); setResult(null); setMessages([])
      setError('登录状态已失效，请重新登录。')
      return
    }
    setError(detailMessage(value))
  }

  async function refreshWorkspace() {
    try {
      const page = await api.conversations()
      setConversations(page.items)
      setConversationId((current) => page.items.some((item) => item.id === current) ? current : page.items[0]?.id ?? '')
      setError('')
    } catch (value) { handleError(value) }
  }

  async function handleAuth(username: string, password: string) {
    setBusy(true); setAuthError('')
    try {
      if (authMode === 'login') {
        setUser(await api.login(username, password))
      } else {
        await api.register(username, password)
        setUser(await api.login(username, password))
      }
    }
    catch (value) { setAuthError(detailMessage(value, authMode === 'login' ? '登录失败，请检查用户名和密码。' : '注册失败，请检查输入。')) }
    finally { setBusy(false) }
  }

  async function handleLogout() {
    try { await api.logout() } catch { /* clear private UI even if server is unavailable */ }
    stopWatcher.current?.(); setUser(null); setConversations([]); setTasks([]); setTask(null); setRuns([]); setResult(null); setMessages([]); setConversationId(''); setNotice('已退出当前账号。')
  }

  async function createConversation() {
    setBusy(true)
    try { const created = await api.createConversation('我的购物清单'); setConversations((items) => [created, ...items]); setConversationId(created.id); setTask(null); setNotice('已创建新的私有对话。') }
    catch (value) { handleError(value) } finally { setBusy(false) }
  }

  async function createTask(goal: string, conditions: Conditions) {
    if (!conversationId) return
    setBusy(true)
    try { const created = await api.createTask(conversationId, goal, conditions); setTasks((items) => [created, ...items]); setTask(created); setShowTaskForm(false); setRuns([]); setResult(null); setMessages([]); setNotice('任务已保存，可以开始一次 Agent Run。') }
    catch (value) { handleError(value) } finally { setBusy(false) }
  }

  async function updateConditions(conditions: Conditions, note: string) {
    if (!task) return
    setBusy(true)
    try { await api.updateTask(task.id, task.current_revision, conditions, note); const fresh = await api.getTask(task.id); setTask(fresh); setTasks((items) => items.map((item) => item.id === fresh.id ? fresh : item)); setNotice(`条件已更新到第 ${fresh.current_revision} 版。`) }
    catch (value) {
      if (value instanceof ApiError && value.status === 409) { const fresh = await api.getTask(task.id); setTask(fresh); setNotice('检测到版本冲突，已加载服务器上的最新条件。') }
      else handleError(value)
    } finally { setBusy(false) }
  }

  async function createRun() {
    if (!task || busy || runSubmitting.current) return
    runSubmitting.current = true
    setBusy(true); setResult(null)
    try { const run = await api.createRun(task.id, task.current_revision, crypto.randomUUID()); setRuns((items) => [run, ...items.filter((item) => item.id !== run.id)]); selectRun(run); setNotice('Run 已进入队列，正在等待 Worker。') }
    catch (value) {
      if (value instanceof ApiError && value.status === 409) { const fresh = await api.getTask(task.id); setTask(fresh); setNotice('任务条件版本已变化，已刷新；请确认后重新运行。') }
      else handleError(value)
    } finally { runSubmitting.current = false; setBusy(false) }
  }

  async function refreshTaskMessages(conversation: string, taskId: string) {
    try {
      const page = await api.messages(conversation)
      setMessages(page.items.filter((message) => message.task_id === taskId))
    } catch (value) { handleError(value) }
  }

  async function submitChatTurn() {
    const content = chatInput.trim()
    if (!task || !conversationId || !content || turnSubmitting) return
    setTurnSubmitting(true); setError('')
    try {
      const turn = await api.submitTurn(conversationId, task.id, crypto.randomUUID(), content, task.current_revision)
      setChatInput('')
      setMessages((items) => [...items.filter((item) => item.id !== turn.message.id), turn.message, ...(turn.assistant_message ? [turn.assistant_message] : [])])
      setTask(turn.task); setRuns((items) => [turn.run, ...items.filter((item) => item.id !== turn.run.id)]); selectRun(turn.run)
      setNotice('本轮消息已保存，Run 正在处理。')
    } catch (value) {
      if (value instanceof ApiError && value.status === 409 && task) {
        const fresh = await api.getTask(task.id); setTask(fresh); setNotice('任务版本已变化，已刷新最新条件；请重新发送本轮消息。')
      } else handleError(value)
    } finally { setTurnSubmitting(false) }
  }

  function selectRun(run: Run) {
    selectedRunIdRef.current = run.id
    stopWatcher.current?.()
    setSelectedRunId(run.id); setResult(null); watchGeneration.current += 1
    if (run.status === 'completed') void loadResult(run.id)
    if (run.status === 'queued' || run.status === 'running') watchRun(run)
  }

  async function loadResult(runId: string) {
    try { setResult(await api.result(runId)); if (task) void refreshTaskMessages(task.conversation_id, task.id) }
    catch (value) { if (!(value instanceof ApiError && value.status === 404)) handleError(value) }
  }

  function watchRun(initial: Run) {
    const generation = watchGeneration.current
    let cursor = 0
    let source: EventSource | null = null
    let reconnectTimer: number | undefined
    let pollTimer: number | undefined
    let stopped = false
    const cleanup = () => {
      stopped = true
      source?.close()
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
      if (pollTimer) window.clearTimeout(pollTimer)
      if (stopWatcher.current === cleanup) stopWatcher.current = null
      if (eventSource.current === source) eventSource.current = null
    }
    stopWatcher.current = cleanup
    const connect = () => {
      if (stopped || generation !== watchGeneration.current) return
      source = new EventSource(`/api/runs/${initial.id}/events/stream?after=${cursor}`)
      eventSource.current = source
      ;['run.queued', 'run.running', 'run.cancel_requested', 'run.completed', 'run.failed', 'run.cancelled'].forEach((name) => source?.addEventListener(name, onEvent))
      source.onerror = () => { source?.close(); void sync(); if (!stopped && generation === watchGeneration.current) reconnectTimer = window.setTimeout(connect, 2000) }
    }
    const sync = async () => {
      if (stopped || generation !== watchGeneration.current) return
      try {
        const current = await api.getRun(initial.id)
        if (stopped || generation !== watchGeneration.current) return
        setRuns((items) => items.map((item) => item.id === current.id ? current : item))
        if (current.status === 'completed') { await loadResult(current.id); cleanup() }
        if (current.status === 'queued' || current.status === 'running') pollTimer = window.setTimeout(sync, 1600)
      } catch (value) { handleError(value) }
    }
    const onEvent = (event: Event) => { const lastEventId = (event as MessageEvent).lastEventId; if (lastEventId) cursor = Number(lastEventId); void sync() }
    connect()
    void sync()
  }

  if (!authChecked) return <div className="loading-screen"><span className="pulse-dot" />正在恢复安全会话…</div>
  if (!user) return <AuthScreen mode={authMode} busy={busy} error={authError} onModeChange={setAuthMode} onSubmit={handleAuth} />

  const selectedRun = runs.find((run) => run.id === selectedRunId) ?? runs[0] ?? null
  return <main className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark">采</span><span>生活采买 <small>WORKBENCH</small></span></div><div className="topbar-actions"><span className="identity">{user.username}</span><button className="button button-quiet" onClick={handleLogout}>退出</button></div></header>
    <div className="workspace">
      <aside className="sidebar"><div className="sidebar-heading"><div><span className="eyebrow">PRIVATE SPACE</span><h2>我的对话</h2></div><button className="icon-button" onClick={createConversation} disabled={busy} aria-label="新建对话">＋</button></div><div className="conversation-list">{conversations.map((conversation) => <button className={`conversation-item ${conversation.id === conversationId ? 'is-selected' : ''}`} key={conversation.id} onClick={() => { setConversationId(conversation.id); setTask(null); setResult(null) }}><span className="conversation-dot" /><span>{conversation.title || '未命名对话'}</span></button>)}{!conversations.length && <div className="empty-sidebar">还没有对话。<br />从右上角创建一个新的购物空间。</div>}</div><div className="sidebar-foot"><span className="status-led" />数据只来自当前账号</div></aside>
      <section className="content"><div className="content-head"><div><span className="eyebrow">SHOPPING AGENT / 014</span><h1>把一次采购，<em>说清楚。</em></h1><p className="intro">先固定目标和条件，再让 Agent 在当前版本上执行一次可追溯的查询。</p></div><div className="head-note"><span>当前用户</span><strong>{user.username}</strong></div></div>
        {error && <div className="alert alert-error" role="alert">{error}<button onClick={() => setError('')} aria-label="关闭错误">×</button></div>}{notice && <div className="alert alert-note" role="status">{notice}<button onClick={() => setNotice('')} aria-label="关闭提示">×</button></div>}
        {!conversationId ? <EmptyWorkspace onCreate={createConversation} disabled={busy} /> : <><section className="task-section"><div className="section-bar"><div><span className="eyebrow">01 / TASK BRIEF</span><h2>购物任务</h2></div>{task && <span className="revision-chip">REV {task.current_revision}</span>}</div>{!task && !showTaskForm && <div className="empty-panel"><div className="empty-icon">＋</div><div><h3>先建立一个明确的目标</h3><p>例如：为两个人买一盒彩色铅笔，预算不超过 15 元。</p></div><button className="button button-primary" onClick={() => setShowTaskForm(true)}>创建任务</button></div>}{showTaskForm && <TaskForm busy={busy} onCancel={() => setShowTaskForm(false)} onSubmit={createTask} />}{task && <TaskCard task={task} busy={busy} onUpdate={updateConditions} onRun={createRun} />}</section>{task && <section className="run-section"><div className="section-bar"><div><span className="eyebrow">02 / RUN HISTORY</span><h2>执行记录</h2></div><span className="section-meta">{runs.length} 次运行</span></div>{runs.length ? <div className="run-layout"><div className="run-list">{runs.map((run) => <button key={run.id} className={`run-item ${run.id === selectedRun?.id ? 'is-selected' : ''}`} onClick={() => selectRun(run)}><span className={`run-status-dot run-status-${run.status}`} /><span className="run-main"><strong>Shopping Agent</strong><small>第 {run.revision} 版 · {formatDate(run.created_at)}</small></span><span className={`status-label status-${run.status}`}>{statusText(run.status)}</span></button>)}</div><RunDetail run={selectedRun} result={result} onCancel={async () => { if (!selectedRun) return; try { const updated = await api.cancelRun(selectedRun.id); setRuns((items) => items.map((item) => item.id === updated.id ? updated : item)); setNotice('已发送取消请求。') } catch (value) { handleError(value) } }} /></div> : <div className="run-empty">还没有运行记录。确认任务条件后，点击“运行 Agent”。</div>}</section>}</>}
        {task && <TaskChat messages={messages} input={chatInput} busy={turnSubmitting} onInput={setChatInput} onSubmit={submitChatTurn} />}<footer className="page-foot"><span>本工作台不自动识别自然语言意图，也不代表真实下单。</span><span>条件、Run 与结果均由服务端保存。</span></footer>
      </section>
    </div>
  </main>
}

function TaskChat({ messages, input, busy, onInput, onSubmit }: { messages: Message[]; input: string; busy: boolean; onInput: (value: string) => void; onSubmit: () => void }) { return <section className="chat-section"><div className="section-bar"><div><span className="eyebrow">02 / TASK CHAT</span><h2>继续补充条件</h2></div><span className="section-meta">消息会绑定当前任务</span></div><div className="chat-history">{messages.length ? messages.map((message) => <div className={`chat-message chat-${message.role}`} key={message.id}><span>{message.role === 'assistant' ? '助手' : '你'}</span><p>{message.content}</p></div>) : <div className="chat-empty">告诉助手还缺什么条件，例如“25 人”。</div>}</div><form className="chat-composer" onSubmit={(event) => { event.preventDefault(); onSubmit() }}><input value={input} onChange={(event) => onInput(event.target.value)} placeholder="补充人数、预算、数量或物品" maxLength={2000} disabled={busy} /><button type="button" className="button button-primary" onClick={onSubmit} disabled={busy || !input.trim()}>{busy ? '发送中…' : '发送'}</button></form></section> }

function AuthScreen({ mode, busy, error, onModeChange, onSubmit }: { mode: AuthMode; busy: boolean; error: string; onModeChange: (mode: AuthMode) => void; onSubmit: (username: string, password: string) => void }) { const [username, setUsername] = useState(''); const [password, setPassword] = useState(''); return <main className="auth-screen"><div className="auth-aside"><span className="brand-mark">采</span><span className="eyebrow">LIFE BUY / 013</span><h1>从一个明确的<br /><em>目标</em>开始。</h1><p>把购物目标、条件和每次 Agent Run 留在同一个可信空间里。</p><div className="signal-list"><span><i />服务端会话</span><span><i />版本化条件</span><span><i />可追溯结果</span></div></div><form className="auth-card" onSubmit={(event) => { event.preventDefault(); onSubmit(username, password) }}><span className="eyebrow">{mode === 'login' ? 'WELCOME BACK' : 'NEW WORKSPACE'}</span><h2>{mode === 'login' ? '登录工作台' : '创建账号'}</h2><p>{mode === 'login' ? '继续你的私有购物任务。' : '创建一个仅属于你的采购空间。'}</p><label>用户名<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required minLength={3} maxLength={64} /></label><label>密码<input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} required minLength={12} maxLength={128} /></label>{error && <div className="form-error" role="alert">{error}</div>}<button className="button button-primary auth-submit" disabled={busy}>{busy ? '处理中…' : mode === 'login' ? '进入工作台' : '创建并登录'}</button><button type="button" className="switch-auth" onClick={() => onModeChange(mode === 'login' ? 'register' : 'login')}>{mode === 'login' ? '还没有账号？创建一个' : '已有账号？返回登录'}</button></form></main> }

function EmptyWorkspace({ onCreate, disabled }: { onCreate: () => void; disabled: boolean }) { return <div className="welcome-panel"><span className="eyebrow">A QUIET PLACE TO PLAN</span><h2>从你的第一个<br /><em>购物任务</em>开始。</h2><p>新建一个对话，保存目标和条件。每次运行都会绑定当前版本，结果不会悄悄漂移。</p><button className="button button-primary" onClick={onCreate} disabled={disabled}>新建购物空间 <span>→</span></button></div> }

function TaskForm({ busy, onCancel, onSubmit }: { busy: boolean; onCancel: () => void; onSubmit: (goal: string, conditions: Conditions) => void }) { const [goal, setGoal] = useState(''); const [item, setItem] = useState(''); const [budget, setBudget] = useState(''); const [people, setPeople] = useState(''); const [quantity, setQuantity] = useState(''); function submit(event: React.FormEvent) { event.preventDefault(); onSubmit(goal, { item: item || undefined, budget: budget ? Number(budget) : undefined, people: people ? Number(people) : undefined, quantity: quantity ? Number(quantity) : undefined }) } return <form className="task-form" onSubmit={submit}><div className="form-grid"><label className="wide">任务目标<input value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="例如：给孩子买一盒彩色铅笔" required maxLength={500} /></label><label>物品<input value={item} onChange={(event) => setItem(event.target.value)} placeholder="彩色铅笔" maxLength={200} /></label><label>预算（元）<input value={budget} onChange={(event) => setBudget(event.target.value)} type="number" min="0.01" step="0.01" placeholder="未设置" /></label><label>人数<input value={people} onChange={(event) => setPeople(event.target.value)} type="number" min="1" step="1" placeholder="未设置" /></label><label>数量<input value={quantity} onChange={(event) => setQuantity(event.target.value)} type="number" min="1" step="1" placeholder="未设置" /></label></div><p className="form-hint">未知条件保持缺失，不会被自动填成 0。</p><div className="form-actions"><button type="button" className="button button-quiet" onClick={onCancel}>取消</button><button className="button button-primary" disabled={busy}>保存任务</button></div></form> }

function TaskCard({ task, busy, onUpdate, onRun }: { task: Task; busy: boolean; onUpdate: (conditions: Conditions, note: string) => void; onRun: () => void }) { const [editing, setEditing] = useState(false); const [budget, setBudget] = useState(task.conditions.budget?.toString() ?? ''); const [quantity, setQuantity] = useState(task.conditions.quantity?.toString() ?? ''); function save() { onUpdate({ ...task.conditions, budget: budget ? Number(budget) : undefined, quantity: quantity ? Number(quantity) : undefined }, '从工作台更新条件'); setEditing(false) } return <div className="task-card"><div className="task-summary"><span className="task-icon">买</span><div><h3>{task.goal}</h3><div className="condition-row">{task.conditions.item && <span>{task.conditions.item}</span>}{task.conditions.budget && <span>预算 ¥{task.conditions.budget}</span>}{task.conditions.people && <span>{task.conditions.people} 人</span>}{task.conditions.quantity && <span>{task.conditions.quantity} 件</span>}{!Object.keys(task.conditions).length && <span className="muted">条件待补充</span>}</div></div></div><div className="task-actions"><button className="button button-quiet" onClick={() => setEditing(!editing)}>{editing ? '收起' : '编辑条件'}</button><button className="button button-primary" onClick={onRun} disabled={busy}>{busy ? '处理中…' : '运行 Agent'} <span>↗</span></button></div>{editing && <div className="inline-edit"><label>预算（元）<input value={budget} onChange={(event) => setBudget(event.target.value)} type="number" min="0.01" step="0.01" /></label><label>数量<input value={quantity} onChange={(event) => setQuantity(event.target.value)} type="number" min="1" step="1" /></label><button className="button button-dark" onClick={save} disabled={busy}>提交第 {task.current_revision + 1} 版</button></div>}</div> }

function RunDetail({ run, result, onCancel }: { run: Run | null; result: RunResult | null; onCancel: () => void }) { if (!run) return <div className="run-detail empty-detail">选择左侧的一次运行查看结果。</div>; return <div className="run-detail"><div className="detail-top"><div><span className="eyebrow">RUN DETAIL</span><h3>{statusText(run.status)}</h3></div>{(run.status === 'queued' || run.status === 'running') && <button className="button button-quiet" onClick={onCancel}>取消运行</button>}</div><div className="run-facts"><span><small>版本</small><strong>REV {run.revision}</strong></span><span><small>状态</small><strong>{statusText(run.status)}</strong></span><span><small>尝试</small><strong>{run.attempt}</strong></span></div>{run.status === 'queued' || run.status === 'running' ? <div className="progress-copy"><span className="pulse-dot" />Worker 正在处理，页面会持续同步状态…</div> : run.status === 'failed' ? <div className="result-error">{run.error_summary || '本次运行失败，请创建新的 Run 重试。'}</div> : run.status === 'cancelled' ? <div className="result-empty">本次运行已取消，没有生成结果。</div> : result ? <ResultView result={result} /> : <div className="result-empty">结果尚未读回，正在重试…</div>}</div> }

function ResultView({ result }: { result: RunResult }) { const source = result.source; return <div className="result-view"><div className="result-label"><span>AGENT RESPONSE</span><span className="decision-chip">{decisionText(result.decision_type)}</span></div><p className="answer">{result.answer}</p><div className="result-meta"><span>委派：{result.delegated ? '是' : '否'}</span><span>MCP 调用：{result.mcp_call_count} 次</span>{source.simulated === true && <span className="simulated-chip">模拟商品数据</span>}</div></div> }
function statusText(status: Run['status']) { return ({ queued: '排队中', running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消' })[status] }
function decisionText(decision: RunResult['decision_type']) { return ({ direct_answer: '直接回答', clarification: '需要补充条件', delegated_discovery: '已委派信息发现' })[decision] }
function formatDate(value: string) { return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) }

export default App
