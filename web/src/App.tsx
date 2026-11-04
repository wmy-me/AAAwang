import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  api,
  detailMessage,
  isAuthError,
  type Conditions,
  type Conversation,
  type DynamicFormProposal,
  type Message,
  type MapPlace,
  type Run,
  type RunResult,
  type ShoppingAdjustment,
  type ShoppingArtifacts,
  type Task,
  type User,
} from "./api/workbench";
import "./App.css";

type AuthMode = "login" | "register";

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [authError, setAuthError] = useState("");
  const [busy, setBusy] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState("");
  const [, setTasks] = useState<Task[]>([]);
  const [task, setTask] = useState<Task | null>(null);
  const [dynamicForm, setDynamicForm] = useState<DynamicFormProposal | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [result, setResult] = useState<RunResult | null>(null);
  const [artifacts, setArtifacts] = useState<ShoppingArtifacts | null>(null);
  const [adjustments, setAdjustments] = useState<ShoppingAdjustment[]>([]);
  const [adjustmentVersion, setAdjustmentVersion] = useState(0);
  const [messages, setMessages] = useState<Message[]>([]);
  const [mapPlaces, setMapPlaces] = useState<MapPlace[]>([]);
  const [mapQuery, setMapQuery] = useState("");
  const [mapCity, setMapCity] = useState("");
  const [mapBusy, setMapBusy] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [turnSubmitting, setTurnSubmitting] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [showTaskForm, setShowTaskForm] = useState(false);
  const eventSource = useRef<EventSource | null>(null);
  const stopWatcher = useRef<(() => void) | null>(null);
  const runSubmitting = useRef(false);
  const selectedRunIdRef = useRef("");
  const watchGeneration = useRef(0);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => undefined)
      .finally(() => setAuthChecked(true));
  }, []);

  useEffect(() => {
    if (!user) return;
    void refreshWorkspace();
    return () => stopWatcher.current?.();
  }, [user]);

  useEffect(() => {
    if (!conversationId) return;
    api
      .tasks(conversationId)
      .then((page) => {
        setTasks(page.items);
        setTask(
          (current) =>
            page.items.find((item) => item.id === current?.id) ??
            page.items[0] ??
            null,
        );
      })
      .catch(handleError);
    setDynamicForm(null);
  }, [conversationId]);

  useEffect(() => {
    if (!task) return;
    void api.getDynamicForm(task.id).then(setDynamicForm).catch(handleError);
    api
      .runs(task.id)
      .then((page) => {
        setRuns(page.items);
        const active =
          page.items.find((run) => run.id === selectedRunIdRef.current) ??
          page.items[0];
        if (active) selectRun(active);
      })
      .catch(handleError);
  }, [task]);

  useEffect(() => {
    if (!task) {
      setMessages([]);
      return;
    }
    void refreshTaskMessages(task.conversation_id, task.id);
  }, [task]);

  function handleError(value: unknown) {
    if (isAuthError(value)) {
      setUser(null);
      setConversations([]);
      setTasks([]);
      setTask(null);
      setDynamicForm(null);
      setRuns([]);
      setResult(null);
      setArtifacts(null);
      setMapPlaces([]);
      setMessages([]);
      setError("登录状态已失效，请重新登录。");
      return;
    }
    setError(detailMessage(value));
  }

  async function refreshWorkspace() {
    try {
      const page = await api.conversations();
      setConversations(page.items);
      setConversationId((current) =>
        page.items.some((item) => item.id === current)
          ? current
          : (page.items[0]?.id ?? ""),
      );
      setError("");
    } catch (value) {
      handleError(value);
    }
  }

  async function handleAuth(username: string, password: string) {
    setBusy(true);
    setAuthError("");
    try {
      if (authMode === "login") {
        setUser(await api.login(username, password));
      } else {
        await api.register(username, password);
        setUser(await api.login(username, password));
      }
    } catch (value) {
      setAuthError(
        detailMessage(
          value,
          authMode === "login"
            ? "登录失败，请检查用户名和密码。"
            : "注册失败，请检查输入。",
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout() {
    try {
      await api.logout();
    } catch {
      /* clear private UI even if server is unavailable */
    }
    stopWatcher.current?.();
    setUser(null);
    setConversations([]);
    setTasks([]);
    setTask(null);
    setDynamicForm(null);
    setRuns([]);
    setResult(null);
    setArtifacts(null);
    setMapPlaces([]);
    setMessages([]);
    setConversationId("");
    setNotice("已退出当前账号。");
  }

  async function createConversation() {
    setBusy(true);
    try {
      const created = await api.createConversation("我的购物清单");
      setConversations((items) => [created, ...items]);
      setConversationId(created.id);
      setTask(null);
      setNotice("已创建新的私有对话。");
    } catch (value) {
      handleError(value);
    } finally {
      setBusy(false);
    }
  }

  async function createTask(goal: string, conditions: Conditions) {
    if (!conversationId) return;
    setBusy(true);
    try {
      const created = await api.createTask(conversationId, goal, conditions);
      setTasks((items) => [created, ...items]);
      setTask(created);
      setDynamicForm(null);
      setShowTaskForm(false);
      setRuns([]);
      setResult(null);
      setMessages([]);
      setNotice("任务已保存，可以开始一次 Agent Run。");
    } catch (value) {
      handleError(value);
    } finally {
      setBusy(false);
    }
  }

  async function updateConditions(
    goalOrConditions: string | Conditions,
    conditionsOrNote: Conditions | string,
    noteOrConfirm?: string | boolean,
    confirmGoalConflict = false,
  ) {
    if (!task) return;
    const goal =
      typeof goalOrConditions === "string" ? goalOrConditions : task.goal;
    const conditions =
      typeof goalOrConditions === "string"
        ? (conditionsOrNote as Conditions)
        : goalOrConditions;
    const note =
      typeof goalOrConditions === "string"
        ? (noteOrConfirm as string)
        : (conditionsOrNote as string);
    const confirmed =
      typeof goalOrConditions === "string" && typeof noteOrConfirm === "boolean"
        ? noteOrConfirm
        : confirmGoalConflict;
    setBusy(true);
    try {
      await api.updateTask(
        task.id,
        task.current_revision,
        goal,
        conditions,
        note,
        confirmed,
      );
      const fresh = await api.getTask(task.id);
      setTask(fresh);
      const proposal = await api.getDynamicForm(fresh.id);
      setDynamicForm(proposal);
      setTasks((items) =>
        items.map((item) => (item.id === fresh.id ? fresh : item)),
      );
      setNotice(`任务已更新到第 ${fresh.current_revision} 版。`);
    } catch (value) {
      if (value instanceof ApiError && value.status === 409) {
        const fresh = await api.getTask(task.id);
        setTask(fresh);
        setNotice("检测到版本冲突，已加载服务器上的最新条件。");
      } else handleError(value);
    } finally {
      setBusy(false);
    }
  }

  async function createRun() {
    if (!task || busy || runSubmitting.current) return;
    runSubmitting.current = true;
    setBusy(true);
    setResult(null);
    try {
      const run = await api.createRun(
        task.id,
        task.current_revision,
        crypto.randomUUID(),
      );
      setRuns((items) => [run, ...items.filter((item) => item.id !== run.id)]);
      selectRun(run);
      setNotice("Run 已进入队列，正在等待 Worker。");
    } catch (value) {
      if (value instanceof ApiError && value.status === 409) {
        const fresh = await api.getTask(task.id);
        setTask(fresh);
        setNotice("任务条件版本已变化，已刷新；请确认后重新运行。");
      } else handleError(value);
    } finally {
      runSubmitting.current = false;
      setBusy(false);
    }
  }

  async function refreshTaskMessages(conversation: string, taskId: string) {
    try {
      const page = await api.messages(conversation);
      setMessages(page.items.filter((message) => message.task_id === taskId));
    } catch (value) {
      handleError(value);
    }
  }

  async function submitChatTurn() {
    const content = chatInput.trim();
    if (!task || !conversationId || !content || turnSubmitting) return;
    setTurnSubmitting(true);
    setError("");
    try {
      const turn = await api.submitTurn(
        conversationId,
        task.id,
        crypto.randomUUID(),
        content,
        task.current_revision,
      );
      setChatInput("");
      setMessages((items) => [
        ...items.filter((item) => item.id !== turn.message.id),
        turn.message,
        ...(turn.assistant_message ? [turn.assistant_message] : []),
      ]);
      setTask(turn.task);
      void api.getDynamicForm(turn.task.id).then(setDynamicForm).catch(handleError);
      setRuns((items) => [
        turn.run,
        ...items.filter((item) => item.id !== turn.run.id),
      ]);
      selectRun(turn.run);
      setNotice("本轮消息已保存，Run 正在处理。");
    } catch (value) {
      if (value instanceof ApiError && value.status === 409 && task) {
        const fresh = await api.getTask(task.id);
        setTask(fresh);
        setNotice("任务版本已变化，已刷新最新条件；请重新发送本轮消息。");
      } else handleError(value);
    } finally {
      setTurnSubmitting(false);
    }
  }

  function selectRun(run: Run) {
    selectedRunIdRef.current = run.id;
    stopWatcher.current?.();
    setSelectedRunId(run.id);
    setResult(null);
    setArtifacts(null);
    setMapPlaces([]);
    watchGeneration.current += 1;
    if (run.status === "completed") void loadResult(run.id, run);
    if (run.status === "queued" || run.status === "running") watchRun(run);
  }

  async function loadResult(runId: string, runOverride?: Run) {
    try {
      const currentRun = runOverride ?? runs.find((item) => item.id === runId);
      const nextResult = await api.result(runId);
      setResult(nextResult);
      const isMapRun =
        currentRun?.execution_type === "map_places" ||
        currentRun?.execution_type === "capability_router";
      const isShoppingRun =
        currentRun?.execution_type === "capability_router" ||
        currentRun?.execution_type === "shopping_agent" ||
        currentRun?.execution_type === "shopping_research";
      setMapPlaces(isMapRun ? await api.mapPlaces(runId) : []);
      setArtifacts(isShoppingRun ? await api.shoppingArtifacts(runId) : null);
      if (task) {
        const history = await api.shoppingAdjustments(task.id);
        setAdjustments(history.items);
        setAdjustmentVersion(history.current_version);
        void refreshTaskMessages(task.conversation_id, task.id);
      }
    } catch (value) {
      if (!(value instanceof ApiError && value.status === 404))
        handleError(value);
    }
  }

  async function submitMapSearch() {
    if (!task || !mapQuery.trim() || !mapCity.trim() || mapBusy) return;
    setMapBusy(true);
    setError("");
    try {
      const turn = await api.submitTurn(
        conversationId,
        task.id,
        crypto.randomUUID(),
        `在${mapCity.trim()}，查询${mapQuery.trim()}地点`,
        task.current_revision,
      );
      setMapQuery("");
      setMapPlaces([]);
      setTask(turn.task);
      setRuns((items) => [turn.run, ...items.filter((item) => item.id !== turn.run.id)]);
      selectRun(turn.run);
      setNotice("地点查询已进入队列，结果会绑定当前任务版本。");
    } catch (value) {
      handleError(value);
    } finally {
      setMapBusy(false);
    }
  }

  function watchRun(initial: Run) {
    const generation = watchGeneration.current;
    let cursor = 0;
    let source: EventSource | null = null;
    let reconnectTimer: number | undefined;
    let pollTimer: number | undefined;
    let stopped = false;
    const cleanup = () => {
      stopped = true;
      source?.close();
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      if (pollTimer) window.clearTimeout(pollTimer);
      if (stopWatcher.current === cleanup) stopWatcher.current = null;
      if (eventSource.current === source) eventSource.current = null;
    };
    stopWatcher.current = cleanup;
    const connect = () => {
      if (stopped || generation !== watchGeneration.current) return;
      source = new EventSource(
        `/api/runs/${initial.id}/events/stream?after=${cursor}`,
      );
      eventSource.current = source;
      [
        "run.queued",
        "run.running",
        "run.cancel_requested",
        "run.completed",
        "run.failed",
        "run.cancelled",
      ].forEach((name) => source?.addEventListener(name, onEvent));
      source.onerror = () => {
        source?.close();
        void sync();
        if (!stopped && generation === watchGeneration.current)
          reconnectTimer = window.setTimeout(connect, 2000);
      };
    };
    const sync = async () => {
      if (stopped || generation !== watchGeneration.current) return;
      try {
        const current = await api.getRun(initial.id);
        if (stopped || generation !== watchGeneration.current) return;
        setRuns((items) =>
          items.map((item) => (item.id === current.id ? current : item)),
        );
        if (current.status === "completed") {
          await loadResult(current.id, current);
          cleanup();
        }
        if (current.status === "queued" || current.status === "running")
          pollTimer = window.setTimeout(sync, 1600);
      } catch (value) {
        handleError(value);
      }
    };
    const onEvent = (event: Event) => {
      const lastEventId = (event as MessageEvent).lastEventId;
      if (lastEventId) cursor = Number(lastEventId);
      void sync();
    };
    connect();
    void sync();
  }

  if (!authChecked)
    return (
      <div className="loading-screen">
        <span className="pulse-dot" />
        正在恢复安全会话…
      </div>
    );
  if (!user)
    return (
      <AuthScreen
        mode={authMode}
        busy={busy}
        error={authError}
        onModeChange={setAuthMode}
        onSubmit={handleAuth}
      />
    );

  const selectedRun =
    runs.find((run) => run.id === selectedRunId) ?? runs[0] ?? null;
  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">采</span>
          <span>
            生活采买 <small>WORKBENCH</small>
          </span>
        </div>
        <div className="topbar-actions">
          <span className="identity">{user.username}</span>
          <button className="button button-quiet" onClick={handleLogout}>
            退出
          </button>
        </div>
      </header>
      <div className="workspace">
        <aside className="sidebar">
          <div className="sidebar-heading">
            <div>
              <span className="eyebrow">PRIVATE SPACE</span>
              <h2>我的对话</h2>
            </div>
            <button
              className="icon-button"
              onClick={createConversation}
              disabled={busy}
              aria-label="新建对话"
            >
              ＋
            </button>
          </div>
          <div className="conversation-list">
            {conversations.map((conversation) => (
              <button
                className={`conversation-item ${conversation.id === conversationId ? "is-selected" : ""}`}
                key={conversation.id}
                onClick={() => {
                  setConversationId(conversation.id);
                  setTask(null);
                  setResult(null);
                }}
              >
                <span className="conversation-dot" />
                <span>{conversation.title || "未命名对话"}</span>
              </button>
            ))}
            {!conversations.length && (
              <div className="empty-sidebar">
                还没有对话。
                <br />
                从右上角创建一个新的购物空间。
              </div>
            )}
          </div>
          <div className="sidebar-foot">
            <span className="status-led" />
            数据只来自当前账号
          </div>
        </aside>
        <section className="content">
          <div className="content-head">
            <div>
              <span className="eyebrow">SHOPPING AGENT / 014</span>
              <h1>
                把一次采购，<em>说清楚。</em>
              </h1>
              <p className="intro">
                先固定目标和条件，再让 Agent 在当前版本上执行一次可追溯的查询。
              </p>
            </div>
            <div className="head-note">
              <span>当前用户</span>
              <strong>{user.username}</strong>
            </div>
          </div>
          {error && (
            <div className="alert alert-error" role="alert">
              {error}
              <button onClick={() => setError("")} aria-label="关闭错误">
                ×
              </button>
            </div>
          )}
          {notice && (
            <div className="alert alert-note" role="status">
              {notice}
              <button onClick={() => setNotice("")} aria-label="关闭提示">
                ×
              </button>
            </div>
          )}
          {!conversationId ? (
            <EmptyWorkspace onCreate={createConversation} disabled={busy} />
          ) : (
            <>
              <section className="task-section">
                <div className="section-bar">
                  <div>
                    <span className="eyebrow">01 / TASK BRIEF</span>
                    <h2>购物任务</h2>
                  </div>
                  {task && (
                    <span className="revision-chip">
                      REV {task.current_revision}
                    </span>
                  )}
                </div>
                {!task && !showTaskForm && (
                  <div className="empty-panel">
                    <div className="empty-icon">＋</div>
                    <div>
                      <h3>先建立一个明确的目标</h3>
                      <p>例如：为两个人买一盒彩色铅笔，预算不超过 15 元。</p>
                    </div>
                    <button
                      className="button button-primary"
                      onClick={() => setShowTaskForm(true)}
                    >
                      创建任务
                    </button>
                  </div>
                )}
                {showTaskForm && (
                  <TaskForm
                    busy={busy}
                    onCancel={() => setShowTaskForm(false)}
                    onSubmit={createTask}
                  />
                )}
                {task && (
                  <TaskCard
                    key={`${task.id}-${task.current_revision}`}
                    task={task}
                    busy={busy}
                    onUpdate={updateConditions}
                    onRun={createRun}
                  />
                )}
                {task && dynamicForm && dynamicForm.task_id === task.id
                  && dynamicForm.status === "pending" && dynamicForm.schema.length > 0 && (
                  <DynamicFormPanel
                    key={dynamicForm.id}
                    proposal={dynamicForm}
                    task={task}
                    busy={busy}
                    onSubmit={async (values) => {
                      setBusy(true);
                      try {
                        const submitted = await api.submitDynamicForm(
                          task.id,
                          dynamicForm.id,
                          task.current_revision,
                          values,
                        );
                        setMessages((items) => [
                          ...items.filter((item) => item.id !== submitted.message.id),
                          submitted.message,
                        ]);
                        setTask(submitted.task);
                        setRuns((items) => [
                          submitted.run,
                          ...items.filter((item) => item.id !== submitted.run.id),
                        ]);
                        selectRun(submitted.run);
                        setDynamicForm(await api.getDynamicForm(submitted.task.id));
                        setNotice(`已确认动态字段，任务进入第 ${submitted.task.current_revision} 版。`);
                      } catch (value) {
                        handleError(value);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  />
                )}
              </section>
              {task && (
                <section className="run-section">
                  <div className="section-bar">
                    <div>
                      <span className="eyebrow">02 / RUN HISTORY</span>
                      <h2>执行记录</h2>
                    </div>
                    <span className="section-meta">{runs.length} 次运行</span>
                  </div>
                  {runs.length ? (
                    <div className="run-layout">
                      <div className="run-list">
                        {runs.map((run) => (
                          <button
                            key={run.id}
                            className={`run-item ${run.id === selectedRun?.id ? "is-selected" : ""}`}
                            onClick={() => selectRun(run)}
                          >
                            <span
                              className={`run-status-dot run-status-${run.status}`}
                            />
                            <span className="run-main">
                              <strong>Shopping Agent</strong>
                              <small>
                                第 {run.revision} 版 ·{" "}
                                {formatDate(run.created_at)}
                              </small>
                            </span>
                            <span
                              className={`status-label status-${run.status}`}
                            >
                              {statusText(run.status)}
                            </span>
                          </button>
                        ))}
                      </div>
                      <RunDetail
                        run={selectedRun}
                        result={result}
                        onCancel={async () => {
                          if (!selectedRun) return;
                          try {
                            const updated = await api.cancelRun(selectedRun.id);
                            setRuns((items) =>
                              items.map((item) =>
                                item.id === updated.id ? updated : item,
                              ),
                            );
                            setNotice("已发送取消请求。");
                          } catch (value) {
                            handleError(value);
                          }
                        }}
                      />
                    </div>
                  ) : (
                    <div className="run-empty">
                      还没有运行记录。确认任务条件后，点击“运行 Agent”。
                    </div>
                  )}
                </section>
              )}
            </>
          )}
          {task && (
            <TaskChat
              messages={messages}
              input={chatInput}
              busy={turnSubmitting}
              onInput={setChatInput}
              onSubmit={submitChatTurn}
            />
          )}
          {task && (
            <MapSearch
              city={mapCity}
              query={mapQuery}
              busy={mapBusy}
              places={mapPlaces}
              onCity={setMapCity}
              onQuery={setMapQuery}
              onSubmit={submitMapSearch}
            />
          )}
          {artifacts && selectedRun && task && (
            <ShoppingArtifactsPanel
              artifacts={artifacts}
              task={task}
              run={selectedRun}
              adjustments={adjustments}
              adjustmentVersion={adjustmentVersion}
              onAdjusted={(adjustment) => {
                setAdjustments((items) => [
                  adjustment,
                  ...items.map((item) => ({ ...item, is_current: false })),
                ]);
                setAdjustmentVersion(adjustment.version);
                setNotice(`已保存手动方案第 ${adjustment.version} 版。`);
              }}
            />
          )}
          <footer className="page-foot">
            <span>本工作台只按受控能力路由执行，也不代表真实下单。</span>
            <span>条件、Run 与结果均由服务端保存。</span>
          </footer>
        </section>
      </div>
    </main>
  );
}

function MapSearch({
  city,
  query,
  busy,
  places,
  onCity,
  onQuery,
  onSubmit,
}: {
  city: string;
  query: string;
  busy: boolean;
  places: MapPlace[];
  onCity: (value: string) => void;
  onQuery: (value: string) => void;
  onSubmit: () => void;
}) {
  return (
    <section className="chat-section">
      <div className="section-bar">
        <div>
          <span className="eyebrow">03 / MAP SEARCH</span>
          <h2>查找附近地点</h2>
        </div>
        <span className="section-meta">只读地点查询</span>
      </div>
      <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
        <input value={city} onChange={(event) => onCity(event.target.value)} placeholder="城市或位置，例如上海" maxLength={120} disabled={busy} />
        <input value={query} onChange={(event) => onQuery(event.target.value)} placeholder="关键词，例如礼品店" maxLength={120} disabled={busy} />
        <button className="button button-primary" disabled={busy || !city.trim() || !query.trim()}>{busy ? "查询中…" : "查询地点"}</button>
      </form>
      {places.length > 0 && (
        <div className="chat-history">
          {places.map((place) => (
            <div className="chat-message chat-assistant" key={place.id}>
              <span>地点</span>
              <p><strong>{place.name}</strong>{place.address ? ` · ${place.address}` : ""}<br /><small>{place.source_service} / {place.source_tool} · {formatDate(place.observed_at)}</small></p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function TaskChat({
  messages,
  input,
  busy,
  onInput,
  onSubmit,
}: {
  messages: Message[];
  input: string;
  busy: boolean;
  onInput: (value: string) => void;
  onSubmit: () => void;
}) {
  return (
    <section className="chat-section">
      <div className="section-bar">
        <div>
          <span className="eyebrow">02 / TASK CHAT</span>
          <h2>继续补充条件</h2>
        </div>
        <span className="section-meta">消息会绑定当前任务</span>
      </div>
      <div className="chat-history">
        {messages.length ? (
          messages.map((message) => (
            <div
              className={`chat-message chat-${message.role}`}
              key={message.id}
            >
              <span>{message.role === "assistant" ? "助手" : "你"}</span>
              <p>{message.content}</p>
            </div>
          ))
        ) : (
          <div className="chat-empty">告诉助手还缺什么条件，例如“25 人”。</div>
        )}
      </div>
      <form
        className="chat-composer"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <input
          value={input}
          onChange={(event) => onInput(event.target.value)}
          placeholder="补充人数、预算、数量或物品"
          maxLength={2000}
          disabled={busy}
        />
        <button
          type="button"
          className="button button-primary"
          onClick={onSubmit}
          disabled={busy || !input.trim()}
        >
          {busy ? "发送中…" : "发送"}
        </button>
      </form>
    </section>
  );
}

function AuthScreen({
  mode,
  busy,
  error,
  onModeChange,
  onSubmit,
}: {
  mode: AuthMode;
  busy: boolean;
  error: string;
  onModeChange: (mode: AuthMode) => void;
  onSubmit: (username: string, password: string) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  return (
    <main className="auth-screen">
      <div className="auth-aside">
        <span className="brand-mark">采</span>
        <span className="eyebrow">LIFE BUY / 013</span>
        <h1>
          从一个明确的
          <br />
          <em>目标</em>开始。
        </h1>
        <p>把购物目标、条件和每次 Agent Run 留在同一个可信空间里。</p>
        <div className="signal-list">
          <span>
            <i />
            服务端会话
          </span>
          <span>
            <i />
            版本化条件
          </span>
          <span>
            <i />
            可追溯结果
          </span>
        </div>
      </div>
      <form
        className="auth-card"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit(username, password);
        }}
      >
        <span className="eyebrow">
          {mode === "login" ? "WELCOME BACK" : "NEW WORKSPACE"}
        </span>
        <h2>{mode === "login" ? "登录工作台" : "创建账号"}</h2>
        <p>
          {mode === "login"
            ? "继续你的私有购物任务。"
            : "创建一个仅属于你的采购空间。"}
        </p>
        <label>
          用户名
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            required
            minLength={3}
            maxLength={64}
          />
        </label>
        <label>
          密码
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            autoComplete={
              mode === "login" ? "current-password" : "new-password"
            }
            required
            minLength={12}
            maxLength={128}
          />
        </label>
        {error && (
          <div className="form-error" role="alert">
            {error}
          </div>
        )}
        <button className="button button-primary auth-submit" disabled={busy}>
          {busy ? "处理中…" : mode === "login" ? "进入工作台" : "创建并登录"}
        </button>
        <button
          type="button"
          className="switch-auth"
          onClick={() => onModeChange(mode === "login" ? "register" : "login")}
        >
          {mode === "login" ? "还没有账号？创建一个" : "已有账号？返回登录"}
        </button>
      </form>
    </main>
  );
}

function EmptyWorkspace({
  onCreate,
  disabled,
}: {
  onCreate: () => void;
  disabled: boolean;
}) {
  return (
    <div className="welcome-panel">
      <span className="eyebrow">A QUIET PLACE TO PLAN</span>
      <h2>
        从你的第一个
        <br />
        <em>购物任务</em>开始。
      </h2>
      <p>
        新建一个对话，保存目标和条件。每次运行都会绑定当前版本，结果不会悄悄漂移。
      </p>
      <button
        className="button button-primary"
        onClick={onCreate}
        disabled={disabled}
      >
        新建购物空间 <span>→</span>
      </button>
    </div>
  );
}

function TaskForm({
  busy,
  onCancel,
  onSubmit,
}: {
  busy: boolean;
  onCancel: () => void;
  onSubmit: (goal: string, conditions: Conditions) => void;
}) {
  const [goal, setGoal] = useState("");
  const [item, setItem] = useState("");
  const [budget, setBudget] = useState("");
  const [people, setPeople] = useState("");
  const [quantity, setQuantity] = useState("");
  function submit(event: React.FormEvent) {
    event.preventDefault();
    onSubmit(goal, {
      item: item || undefined,
      budget: budget ? Number(budget) : undefined,
      people: people ? Number(people) : undefined,
      quantity: quantity ? Number(quantity) : undefined,
    });
  }
  return (
    <form className="task-form" onSubmit={submit}>
      <div className="form-grid">
        <label className="wide">
          任务目标
          <input
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            placeholder="例如：给孩子买一盒彩色铅笔"
            required
            maxLength={500}
          />
        </label>
        <label>
          物品
          <input
            value={item}
            onChange={(event) => setItem(event.target.value)}
            placeholder="彩色铅笔"
            maxLength={200}
          />
        </label>
        <label>
          预算（元）
          <input
            value={budget}
            onChange={(event) => setBudget(event.target.value)}
            type="number"
            min="0.01"
            step="0.01"
            placeholder="未设置"
          />
        </label>
        <label>
          人数
          <input
            value={people}
            onChange={(event) => setPeople(event.target.value)}
            type="number"
            min="1"
            step="1"
            placeholder="未设置"
          />
        </label>
        <label>
          数量
          <input
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            type="number"
            min="1"
            step="1"
            placeholder="未设置"
          />
        </label>
      </div>
      <p className="form-hint">未知条件保持缺失，不会被自动填成 0。</p>
      <div className="form-actions">
        <button
          type="button"
          className="button button-quiet"
          onClick={onCancel}
        >
          取消
        </button>
        <button className="button button-primary" disabled={busy}>
          保存任务
        </button>
      </div>
    </form>
  );
}

function DynamicFormPanel({
  proposal,
  task,
  busy,
  onSubmit,
}: {
  proposal: DynamicFormProposal;
  task: Task;
  busy: boolean;
  onSubmit: (values: Record<string, unknown>) => void;
}) {
  const [values, setValues] = useState<Record<string, unknown>>({});

  function updateValue(field: DynamicFormProposal["schema"][number], value: string) {
    setValues((current) => {
      const next = { ...current };
      if (value === "") {
        delete next[field.id];
      } else {
        next[field.id] = field.control === "number" || field.control === "money"
          ? Number(value)
          : value;
      }
      return next;
    });
  }

  return (
    <form
      className="dynamic-form-panel"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(values);
      }}
    >
      <div className="dynamic-form-heading">
        <div>
          <span className="eyebrow">ADAPTIVE INPUT</span>
          <h3>补充当前目标需要的条件</h3>
        </div>
        <span className="section-meta">REV {task.current_revision}</span>
      </div>
      <p className="form-hint">这些字段是本轮建议，不会在确认前写入任务条件。</p>
      <div className="dynamic-form-grid">
        {proposal.schema.map((field) => (
          <label key={field.id}>
            <span>{field.label}{field.required ? " *" : ""}</span>
            <input
              type={field.control === "number" || field.control === "money" ? "number" : "text"}
              min={field.min_value ?? undefined}
              max={field.max_value ?? undefined}
              step={field.control === "money" ? "0.01" : field.control === "number" ? "1" : undefined}
              placeholder={field.unit ? `单位：${field.unit}` : "可选"}
              value={String(values[field.id] ?? "")}
              onChange={(event) => updateValue(field, event.target.value)}
              required={field.required}
              disabled={busy}
            />
            <small>{field.reason}</small>
          </label>
        ))}
      </div>
      <button className="button button-dark" disabled={busy || !Object.keys(values).length}>
        {busy ? "确认中…" : "确认并生成新版本"}
      </button>
    </form>
  );
}

function TaskCard({
  task,
  busy,
  onUpdate,
  onRun,
}: {
  task: Task;
  busy: boolean;
  onUpdate: (
    goal: string,
    conditions: Conditions,
    note: string,
    confirmGoalConflict: boolean,
  ) => void;
  onRun: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [goal, setGoal] = useState(task.goal);
  const [budget, setBudget] = useState(
    task.conditions.budget?.toString() ?? "",
  );
  const [people, setPeople] = useState(
    task.conditions.people?.toString() ?? "",
  );
  const [quantity, setQuantity] = useState(
    task.conditions.quantity?.toString() ?? "",
  );
  const [confirmGoalConflict, setConfirmGoalConflict] = useState(false);
  const hasConflicts = Boolean(task.goal_conflicts?.length);
  function save() {
    onUpdate(
      goal,
      {
        ...task.conditions,
        budget: budget ? Number(budget) : undefined,
        people: people ? Number(people) : undefined,
        quantity: quantity ? Number(quantity) : undefined,
      },
      "从工作台更新目标与条件",
      confirmGoalConflict,
    );
    setEditing(false);
  }
  return (
    <div className="task-card">
      <div className="task-summary">
        <span className="task-icon">买</span>
        <div>
          <h3>{task.goal}</h3>
          <div className="condition-row">
            {task.conditions.item && <span>{task.conditions.item}</span>}
            {task.conditions.budget && (
              <span>预算 ¥{task.conditions.budget}</span>
            )}
            {task.conditions.people && <span>{task.conditions.people} 人</span>}
            {task.conditions.quantity && (
              <span>{task.conditions.quantity} 件</span>
            )}
            {!Object.keys(task.conditions).length && (
              <span className="muted">条件待补充</span>
            )}
          </div>
          {task.goal_conflicts?.map((conflict, index) => (
            <div
              className="conflict-note"
              key={`${String(conflict.field)}-${index}`}
            >
              目标中的 {String(conflict.field)} 为 {String(conflict.goal_value)}
              ，当前条件为 {String(conflict.condition_value)}
              ；请修正目标或确认以结构化条件为准。
            </div>
          ))}
          {task.goal_resolution && (
            <div className="form-hint">当前决议：{task.goal_resolution}</div>
          )}
        </div>
      </div>
      <div className="task-actions">
        <button
          className="button button-quiet"
          onClick={() => setEditing(!editing)}
        >
          {editing ? "收起" : "编辑目标与条件"}
        </button>
        <button
          className="button button-primary"
          onClick={onRun}
          disabled={busy || hasConflicts}
        >
          {busy ? "处理中…" : hasConflicts ? "先处理目标冲突" : "运行 Agent"}{" "}
          <span>↗</span>
        </button>
      </div>
      {editing && (
        <div className="inline-edit">
          <label className="wide">
            任务目标
            <input
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              maxLength={500}
            />
          </label>
          <label>
            预算（元）
            <input
              value={budget}
              onChange={(event) => setBudget(event.target.value)}
              type="number"
              min="0.01"
              step="0.01"
            />
          </label>
          <label>
            人数
            <input
              value={people}
              onChange={(event) => setPeople(event.target.value)}
              type="number"
              min="1"
              step="1"
            />
          </label>
          <label>
            数量
            <input
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              type="number"
              min="1"
              step="1"
            />
          </label>
          <label>
            <input
              type="checkbox"
              checked={confirmGoalConflict}
              onChange={(event) => setConfirmGoalConflict(event.target.checked)}
            />
            确认以结构化条件为准
          </label>
          <button className="button button-dark" onClick={save} disabled={busy}>
            提交第 {task.current_revision + 1} 版
          </button>
        </div>
      )}
    </div>
  );
}

function RunDetail({
  run,
  result,
  artifacts = null,
  onCancel,
}: {
  run: Run | null;
  result: RunResult | null;
  artifacts?: ShoppingArtifacts | null;
  onCancel: () => void;
}) {
  if (!run)
    return (
      <div className="run-detail empty-detail">
        选择左侧的一次运行查看结果。
      </div>
    );
  return (
    <div className="run-detail">
      <div className="detail-top">
        <div>
          <span className="eyebrow">RUN DETAIL</span>
          <h3>{statusText(run.status)}</h3>
        </div>
        {(run.status === "queued" || run.status === "running") && (
          <button className="button button-quiet" onClick={onCancel}>
            取消运行
          </button>
        )}
      </div>
      <div className="run-facts">
        <span>
          <small>版本</small>
          <strong>REV {run.revision}</strong>
        </span>
        <span>
          <small>状态</small>
          <strong>{statusText(run.status)}</strong>
        </span>
        <span>
          <small>尝试</small>
          <strong>{run.attempt}</strong>
        </span>
      </div>
      <RunExecutionSummary run={run} />
      {run.status === "queued" || run.status === "running" ? (
        <div className="progress-copy">
          <span className="pulse-dot" />
          Worker 正在处理，页面会持续同步状态…
        </div>
      ) : run.status === "failed" ? (
        <div className="result-error">
          {run.error_summary || "本次运行失败，请创建新的 Run 重试。"}
        </div>
      ) : run.status === "cancelled" ? (
        <div className="result-empty">本次运行已取消，没有生成结果。</div>
      ) : result ? (
        <ResultView result={result} artifacts={artifacts} />
      ) : (
        <div className="result-empty">结果尚未读回，正在重试…</div>
      )}
    </div>
  );
}

function RunExecutionSummary({ run }: { run: Run }) {
  const budget = run.budget;
  const decision = run.decision;
  const termination = typeof budget?.termination_reason === "string"
    ? budget.termination_reason
    : null;
  return (
    <div className="run-summary">
      <div>
        <small>决策</small>
        <strong>{decisionKindText(decision?.kind)}{decision?.decision_source ? " · 模型" : ""}</strong>
      </div>
      <div>
        <small>能力快照</small>
        <strong>{run.capability_ids?.length ? run.capability_ids.join(" + ") : "无工具"}</strong>
      </div>
      {budget && (
        <div>
          <small>预算</small>
          <strong>
            模型 {String(budget.model_requests ?? 0)} · MCP {String(budget.mcp_attempts ?? 0)} · 远端 {String(budget.remote_calls ?? 0)}
          </strong>
        </div>
      )}
      {termination && <div className="run-termination">终止：{terminationText(termination)}</div>}
    </div>
  );
}

function ResultView({
  result,
  artifacts,
}: {
  result: RunResult;
  artifacts: ShoppingArtifacts | null;
}) {
  const source = result.source;
  const plan = artifacts?.plan;
  return (
    <div className="result-view">
      <div className="result-label">
        <span>AGENT RESPONSE</span>
        <span className="decision-chip">
          {decisionText(result.decision_type)}
        </span>
      </div>
      <p className="answer">{result.answer}</p>
      <div className="result-meta">
        <span>委派：{result.delegated ? "是" : "否"}</span>
        <span>MCP 调用：{result.mcp_call_count} 次</span>
        {source.simulated === true && (
          <span className="simulated-chip">模拟商品数据</span>
        )}
      </div>
      {artifacts && (
        <div className="candidate-list">
          {artifacts.candidates.map((candidate) => (
            <div className="candidate-row" key={candidate.id}>
              <div>
                <strong>{candidate.name}</strong>
                <small>
                  {candidate.unit} · 每包可分 {candidate.distributable_units} 份
                  · {candidate.availability}
                </small>
              </div>
              <span>¥{candidate.unit_price}</span>
            </div>
          ))}
          {!artifacts.candidates.length && (
            <div className="result-empty">本次查询没有可保存的候选。</div>
          )}
        </div>
      )}
      {plan && (
        <div className="plan-summary">
          <div className="result-label">
            <span>VALIDATED PLAN / REV {plan.revision}</span>
            <span className="simulated-chip">模拟方案</span>
          </div>
          {plan.items.map((item) => (
            <p key={item.candidate_id}>
              {item.candidate.name} × {item.package_quantity} 包，覆盖{" "}
              {item.covered_people} 人，小计 ¥{item.subtotal}
            </p>
          ))}
          <div className="plan-totals">
            <span>预算 ¥{plan.budget}</span>
            <strong>合计 ¥{plan.total}</strong>
            <span>余量 ¥{plan.remaining}</span>
          </div>
          {plan.unknown_fees && <small className="fee-note">{plan.note}</small>}
        </div>
      )}
    </div>
  );
}
function ShoppingArtifactsPanel({
  artifacts,
  task,
  run,
  adjustments,
  adjustmentVersion,
  onAdjusted,
}: {
  artifacts: ShoppingArtifacts;
  task: Task;
  run: Run;
  adjustments: ShoppingAdjustment[];
  adjustmentVersion: number;
  onAdjusted: (adjustment: ShoppingAdjustment) => void;
}) {
  const plan = artifacts.plan;
  const [selected, setSelected] = useState<Record<string, number>>(() =>
    Object.fromEntries(
      plan?.items.map((item) => [item.candidate_id, item.package_quantity]) ??
        [],
    ),
  );
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  async function submit() {
    const items = Object.entries(selected).map(
      ([candidate_id, package_quantity]) => ({
        candidate_id,
        package_quantity,
      }),
    );
    if (!items.length) return;
    setSubmitting(true);
    setMessage("");
    try {
      onAdjusted(
        await api.createShoppingAdjustment(
          task.id,
          run.id,
          run.revision,
          adjustmentVersion,
          items,
        ),
      );
    } catch (value) {
      setMessage(detailMessage(value, "方案保存失败，请刷新后重试。"));
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <section className="artifacts-section">
      <div className="section-bar">
        <div>
          <span className="eyebrow">04 / CANDIDATES & PLAN</span>
          <h2>候选与采买方案</h2>
        </div>
        <span className="simulated-chip">模拟商品</span>
      </div>
      <div className="candidate-list">
        {artifacts.candidates.map((candidate) => (
          <label className="candidate-row" key={candidate.id}>
            <input
              type="checkbox"
              checked={candidate.id in selected}
              onChange={(event) =>
                setSelected((items) => {
                  const next = { ...items };
                  if (event.target.checked) next[candidate.id] = 1;
                  else delete next[candidate.id];
                  return next;
                })
              }
            />
            <div>
              <strong>{candidate.name}</strong>
              <small>
                {candidate.unit} · 每包可分 {candidate.distributable_units} 份 ·{" "}
                {candidate.availability}
              </small>
            </div>
            <span>
              ¥{candidate.unit_price}
              {candidate.id in selected && (
                <input
                  className="quantity-input"
                  type="number"
                  min="1"
                  step="1"
                  value={selected[candidate.id]}
                  onChange={(event) =>
                    setSelected((items) => ({
                      ...items,
                      [candidate.id]: Math.max(
                        1,
                        Number(event.target.value) || 1,
                      ),
                    }))
                  }
                  aria-label={`${candidate.name} 包装数量`}
                />
              )}
            </span>
          </label>
        ))}
        {!artifacts.candidates.length && (
          <div className="result-empty">本次查询没有可保存的候选。</div>
        )}
      </div>
      <div className="adjustment-actions">
        <button
          className="button button-primary"
          onClick={submit}
          disabled={submitting || !Object.keys(selected).length}
        >
          {submitting ? "保存中…" : "保存手动方案"}
        </button>
        {message && <span className="form-error">{message}</span>}
      </div>
      {plan ? (
        <div className="plan-summary">
          <div className="result-label">
            <span>VALIDATED PLAN / REV {plan.revision}</span>
            <span>
              覆盖 {plan.covered_people}/{plan.people} 人
            </span>
          </div>
          {plan.items.map((item) => (
            <p key={item.candidate_id}>
              {item.candidate.name} × {item.package_quantity} 包，小计 ¥
              {item.subtotal}
            </p>
          ))}
          <div className="plan-totals">
            <span>预算 ¥{plan.budget}</span>
            <strong>合计 ¥{plan.total}</strong>
            <span>余量 ¥{plan.remaining}</span>
          </div>
          {plan.unknown_fees && <small className="fee-note">{plan.note}</small>}
        </div>
      ) : (
        <div className="result-empty">
          当前候选无法在已确认人数和预算内形成有效方案。
        </div>
      )}
      {adjustments.length > 0 && (
        <div className="adjustment-history">
          <strong>手动版本</strong>
          {adjustments.map((adjustment) => (
            <span key={adjustment.id}>
              V{adjustment.version} · ¥{adjustment.total}
              {adjustment.is_current ? " · 当前" : ""}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
function statusText(status: Run["status"]) {
  return {
    queued: "排队中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  }[status];
}
function decisionText(decision: RunResult["decision_type"]) {
  return {
    direct_answer: "直接回答",
    clarification: "需要补充条件",
    delegated_discovery: "已委派信息发现",
  }[decision];
}

function decisionKindText(kind: unknown) {
  if (kind === "capabilities") return "能力执行";
  if (kind === "clarification") return "追问";
  if (kind === "direct") return "直接回答";
  if (kind === "pending") return "等待决策";
  return "未记录";
}

function terminationText(reason: string) {
  const labels: Record<string, string> = {
    cancelled: "已取消",
    timeout: "超时",
    lease_lost: "租约丢失",
    lease_expired: "租约过期",
    model_budget_exhausted: "模型预算耗尽",
    delegation_budget_exhausted: "委派预算耗尽",
    mcp_budget_exhausted: "MCP 预算耗尽",
    remote_budget_exhausted: "远端调用预算耗尽",
    failed: "执行失败",
  };
  return labels[reason] ?? reason;
}
function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export default App;
