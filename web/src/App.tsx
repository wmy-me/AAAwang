import { useState } from 'react'
import { checkHealth, type HealthResponse } from './api/health'
import './App.css'

type ConnectionState =
  | { status: 'idle' }
  | { status: 'checking' }
  | { status: 'ok'; result: HealthResponse }
  | { status: 'error'; message: string }

function App() {
  const [connection, setConnection] = useState<ConnectionState>({
    status: 'idle',
  })

  async function handleCheck() {
    setConnection({ status: 'checking' })

    try {
      const result = await checkHealth()
      setConnection({ status: 'ok', result })
    } catch (error) {
      const message = error instanceof Error ? error.message : '未知错误'
      setConnection({ status: 'error', message })
    }
  }

  const isChecking = connection.status === 'checking'

  return (
    <main className="page">
      <section className="card" aria-labelledby="project-title">
        <span className="mark" aria-hidden="true">
          采
        </span>

        <h1 id="project-title">生活采买智能体</h1>
        <p className="lede">项目框架已初始化，业务功能尚未开发</p>

        <button type="button" onClick={handleCheck} disabled={isChecking}>
          {isChecking ? '正在检查…' : '检查后端连接'}
        </button>

        <p
          className={`status status--${connection.status}`}
          role="status"
          aria-live="polite"
        >
          {connection.status === 'idle' && '尚未检查 Python API 连接。'}
          {connection.status === 'checking' && '正在请求 /api/health …'}
          {connection.status === 'ok' &&
            `连接成功：${connection.result.service}（${connection.result.status}）`}
          {connection.status === 'error' && `连接失败：${connection.message}`}
        </p>
      </section>
    </main>
  )
}

export default App
