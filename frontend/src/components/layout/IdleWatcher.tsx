import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { env } from '@/config/env'
import { useAuth } from '@/contexts/AuthContext'
import { refreshSession } from '@/services/api/apiClient'
import { Modal } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

const WARN_BEFORE_MS = 2 * 60_000

/** Mirrors the server idle timeout: warns two minutes before expiry and offers "Stay signed in". */
export function IdleWatcher() {
  const { logout } = useAuth()
  const nav = useNavigate()
  const last = useRef(Date.now())
  const [warn, setWarn] = useState(false)
  const idleMs = env.sessionIdleMinutes * 60_000

  useEffect(() => {
    const bump = () => { if (!warn) last.current = Date.now() }
    const evts = ['pointerdown', 'keydown', 'scroll'] as const
    evts.forEach((e) => window.addEventListener(e, bump, { passive: true }))
    const t = setInterval(() => {
      const idle = Date.now() - last.current
      if (idle >= idleMs) { void logout('You were signed out after a period of inactivity.').then(() => nav('/login', { replace: true })) }
      else if (idle >= idleMs - WARN_BEFORE_MS) setWarn(true)
    }, 10_000)
    return () => { evts.forEach((e) => window.removeEventListener(e, bump)); clearInterval(t) }
  }, [idleMs, logout, nav, warn])

  return (
    <Modal open={warn} onOpenChange={() => undefined} dismissible={false} size="sm" title="Still there?"
      description="You will be signed out soon because of inactivity."
      footer={<>
        <Button variant="secondary" onClick={() => { void logout().then(() => nav('/login', { replace: true })) }}>Sign out</Button>
        <Button onClick={async () => { await refreshSession(); last.current = Date.now(); setWarn(false) }}>Stay signed in</Button>
      </>}>
      <p>For your security, sessions end after {env.sessionIdleMinutes} minutes without activity.</p>
    </Modal>
  )
}
