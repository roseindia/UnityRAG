import { Component, type ErrorInfo, type ReactNode } from 'react'
import { lastReference } from '@/services/api/apiClient'
import { CopyButton } from '@/components/common/CopyButton'
import { Button } from '@/components/ui/button'

interface Props { children: ReactNode; /** Smaller inline fallback for a single panel. */ panel?: boolean; name?: string }
interface State { failed: boolean }

/** Render-error boundary. Shows a non-technical page and the last correlation id (NFR-094). */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }
  static getDerivedStateFromError(): State { return { failed: true } }
  componentDidCatch(_e: Error, info: ErrorInfo) {
    // Telemetry carries route templates and component names only, never content (Design Document 18).
    if (import.meta.env.DEV) console.error('Render error in', this.props.name ?? 'app', info.componentStack)
  }
  render() {
    if (!this.state.failed) return this.props.children
    if (this.props.panel) {
      return (
        <div role="alert" className="rounded-card border border-danger/30 bg-danger-bg p-4 text-sm">
          <p className="font-medium">This section couldn't be displayed.</p>
          <Button variant="secondary" size="sm" className="mt-2" onClick={() => this.setState({ failed: false })}>Try again</Button>
        </div>
      )
    }
    return (
      <div role="alert" className="mx-auto mt-24 max-w-md px-4 text-center">
        <h1>Something went wrong</h1>
        <p className="mt-1 text-ink-muted">The page could not be displayed. Reloading usually fixes this.</p>
        {lastReference.id && <p className="mt-2 flex items-center justify-center gap-1 text-xs text-ink-muted">Reference: <code className="font-mono">{lastReference.id.slice(0, 8)}…</code><CopyButton text={lastReference.id} label="Copy reference" /></p>}
        <Button className="mt-4" onClick={() => window.location.assign('/')}>Reload</Button>
      </div>
    )
  }
}
