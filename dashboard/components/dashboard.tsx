"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { DemoLab, type DemoMode } from "./demo-lab";
import type { DemoProfile } from "../lib/demo";
import type { AlertRecord, Snapshot } from "../lib/types";

const views = ["Overview", "Demo Lab"] as const;

const emptySnapshot: Snapshot = { nodes: [], providers: [], alerts: [], runs: [], led: {} };

function label(status: string) {
  return status.replaceAll("-", " ");
}

function shortTime(value: string | null) {
  return value ? new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(value)) : "Not reported";
}

export function Dashboard({ platformName }: { platformName: string }) {
  const [snapshot, setSnapshot] = useState<Snapshot>(emptySnapshot);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<(typeof views)[number]>("Overview");
  const [demoMode, setDemoMode] = useState<DemoMode>("simulation");
  const [demoProfile, setDemoProfile] = useState<DemoProfile>("mac");
  const [liveUnlocked, setLiveUnlocked] = useState(false);
  const [actionFeedback, setActionFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(null);
  const [workspaceStatus, setWorkspaceStatus] = useState<Record<string, any> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/v1/system/snapshot", { cache: "no-store" });
      if (!response.ok) throw new Error(`Control Plane returned ${response.status}`);
      setSnapshot(await response.json());
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to reach the Control Plane");
    }
  }, []);

  const shouldConnect = activeView === "Overview" || demoMode === "live";

  useEffect(() => {
    if (!shouldConnect) return;
    void refresh();
    let fallback: number | undefined;
    let retry: number | undefined;
    let socket: WebSocket | undefined;
    let disposed = false;

    const startFallback = () => {
      if (!fallback) fallback = window.setInterval(() => void refresh(), 5000);
    };
    const stopFallback = () => {
      if (fallback) window.clearInterval(fallback);
      fallback = undefined;
    };
    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${protocol}//${window.location.host}/api/v1/live`);
      socket.onopen = stopFallback;
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as { type?: string; data?: Snapshot };
          if (message.type === "system.snapshot" && message.data) {
            setSnapshot(message.data);
            setError(null);
          }
        } catch {
          // A malformed live frame must not disrupt the dashboard.
        }
      };
      socket.onerror = startFallback;
      socket.onclose = () => {
        startFallback();
        if (!disposed) retry = window.setTimeout(connect, 3000);
      };
    };

    connect();
    return () => {
      disposed = true;
      stopFallback();
      if (retry) window.clearTimeout(retry);
      socket?.close();
    };
  }, [refresh, shouldConnect]);

  useEffect(() => {
    let cancelled = false;
    const readStatus = async () => {
      try {
        const response = await fetch("/api/v1/storage/status", { cache: "no-store" });
        if (response.ok && !cancelled) setWorkspaceStatus(await response.json());
      } catch {
        // The primary dashboard remains useful if the sibling storage service is unavailable.
      }
    };
    void readStatus();
    const interval = window.setInterval(() => void readStatus(), 5000);
    return () => { cancelled = true; window.clearInterval(interval); };
  }, []);

  const invoke = useCallback(async (key: string, path: string, body?: object, successMessage = "Action accepted by the Control Plane") => {
    setBusy(key);
    try {
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!response.ok) {
        const message = await response.json().catch(() => ({}));
        throw new Error(message.detail ?? `Request failed with ${response.status}`);
      }
      await refresh();
      setActionFeedback({ tone: "success", message: successMessage });
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Action failed";
      setError(message);
      setActionFeedback({ tone: "error", message });
    } finally {
      setBusy(null);
    }
  }, [refresh]);

  const activeRun = useMemo(() => snapshot.runs.find((run) => run.status === "running") ?? snapshot.runs[0], [snapshot.runs]);
  const runtime = snapshot.runtime ?? { node_id: "control-plane", node_name: "Control Plane host", hardware_profile: "standard" as const };

  const runDemoLiveAction = useCallback((action: "lights" | "automation" | "notification") => {
    if (action === "lights") {
      void invoke("demo-lights", "/api/v1/devices/living-room-lights/light-action", { action: "toggle" }, "Live light toggle sent to Home Assistant.");
      return;
    }
    if (action === "automation") {
      void invoke("demo-automation", "/api/v1/automations/safe-test/runs", { trigger: "manual" }, "Safe Test Automation queued.");
      return;
    }
    void invoke("demo-notification", "/api/v1/commands", { node_id: "macbook", command_type: "notification.show", payload: { title: "Home Platform", message: "Demo Lab live command acknowledged." } }, "Live Mac notification queued.");
  }, [invoke]);

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">HP</span><span>{platformName}</span></div>
        <nav aria-label="Platform views">{views.map((view) => (
          <button key={view} className={activeView === view ? "nav-item active" : "nav-item"} onClick={() => setActiveView(view)}>{view}</button>
        ))}</nav>
        <p className="privacy">Private · Tailscale only</p>
      </aside>

      <section className="content">
        {activeView === "Demo Lab" ? <DemoLab
          key={demoProfile}
          mode={demoMode}
          profile={demoProfile}
          isLiveUnlocked={liveUnlocked}
          snapshot={snapshot}
          busy={busy}
          actionFeedback={actionFeedback}
          onModeChange={setDemoMode}
          onProfileChange={setDemoProfile}
          onUnlockLive={() => setLiveUnlocked(true)}
          onRefreshLive={() => void refresh()}
          onLiveAction={runDemoLiveAction}
        /> : <>
        <header className="topbar">
          <div><p className="eyebrow">Home Platform</p><h1>Operational overview</h1></div>
          <button className="secondary" onClick={() => void refresh()}>Refresh</button>
        </header>

        {error && <div className="notice error"><span>{error}</span><button onClick={() => setError(null)}>Dismiss</button></div>}

        <section className="status-grid" aria-label="System state">
          <article className="card emphasis"><p>Control Plane</p><strong>Online</strong><span>{runtime.node_name} · {runtime.hardware_profile === "pi-hardware" ? "hardware profile" : "standard profile"}</span></article>
          <article className="card"><p>Nodes</p><strong>{snapshot.nodes.filter((node) => node.status === "online").length}/{Math.max(snapshot.nodes.length, 2)}</strong><span>Online Nodes</span></article>
          <article className="card"><p>Attention</p><strong>{snapshot.alerts.length}</strong><span>Active messages</span></article>
          <article className="card"><p>Status indicators</p><strong>{Object.values(snapshot.led).filter((led) => led.mode !== "off").length}</strong><span>Active physical LEDs</span></article>
        </section>

        <section className="panel">
          <div className="panel-heading"><div><p className="eyebrow">Workspace Sync</p><h2>Backup protection</h2></div></div>
          {workspaceStatus ? <div className="list">
            <article className="list-row"><span className={`status-dot ${workspaceStatus.backup?.state === "completed" || workspaceStatus.backup?.state === "running" ? "online" : "offline"}`} /><div><strong>{workspaceStatus.backup?.active ? "Backup active" : workspaceStatus.backup?.state === "completed" ? "Last backup completed" : "Backup not confirmed"}</strong><p>{workspaceStatus.backup?.stage ?? "waiting"}{workspaceStatus.backup?.percent_done != null ? ` · ${(workspaceStatus.backup.percent_done * 100).toFixed(0)}%` : ""}</p></div><span className="pill">{workspaceStatus.storage?.storage_health ?? "unknown"}</span></article>
            <p className="description">HDD: {workspaceStatus.storage?.storage_health_detail ?? "unknown"}. {workspaceStatus.backup?.warning ?? workspaceStatus.backup?.error ?? ""}</p>
          </div> : <p className="empty">Reading Workspace Sync status…</p>}
        </section>

        <div className="column-grid">
          <section className="panel">
            <div className="panel-heading"><div><p className="eyebrow">Nodes</p><h2>Connected systems</h2></div></div>
            <div className="list">{snapshot.nodes.length ? snapshot.nodes.map((node) => (
              <article className="list-row" key={node.id}><span className={`status-dot ${node.status}`} /><div><strong>{node.name}</strong><p>{node.health} · last seen {shortTime(node.last_seen_at)}</p></div><span className="pill">{label(node.status)}</span></article>
            )) : <p className="empty">Waiting for Nodes to report Actual State.</p>}</div>
          </section>

          <section className="panel">
            <div className="panel-heading"><div><p className="eyebrow">Lighting</p><h2>Living Room</h2></div><span className="pill">Home Assistant</span></div>
            <p className="description">Configured target: <code>light.living_room_living_room</code></p>
            <div className="control-grid">
              <button disabled={busy !== null} onClick={() => void invoke("light-toggle", "/api/v1/devices/living-room-lights/light-action", { action: "toggle" })}>Toggle</button>
              <button disabled={busy !== null} onClick={() => void invoke("light-up", "/api/v1/devices/living-room-lights/light-action", { action: "brightness", step: 5 })}>Brightness +</button>
              <button disabled={busy !== null} onClick={() => void invoke("light-down", "/api/v1/devices/living-room-lights/light-action", { action: "brightness", step: -5 })}>Brightness −</button>
              <button disabled={busy !== null} onClick={() => void invoke("light-warm", "/api/v1/devices/living-room-lights/light-action", { action: "color_temperature", step: -150 })}>Warmer</button>
              <button disabled={busy !== null} onClick={() => void invoke("light-cool", "/api/v1/devices/living-room-lights/light-action", { action: "color_temperature", step: 150 })}>Cooler</button>
            </div>
          </section>
        </div>

        <div className="column-grid">
          <section className="panel">
            <div className="panel-heading"><div><p className="eyebrow">Automations</p><h2>Safe Test Automation</h2></div><button disabled={busy !== null} onClick={() => void invoke("safe-run", "/api/v1/automations/safe-test/runs", { trigger: "manual" })}>{busy === "safe-run" ? "Starting…" : "Run now"}</button></div>
            {activeRun ? <ol className="stages">{activeRun.stages.length ? activeRun.stages.map((stage) => <li key={stage.position} className={stage.status}><span>{stage.status === "completed" ? "✓" : stage.status === "running" ? "●" : "○"}</span>{stage.name}</li>) : <li className="queued"><span>○</span>Waiting for Automation Controller</li>}</ol> : <p className="empty">No recent safe test Run.</p>}
          </section>

          <section className="panel">
            <div className="panel-heading"><div><p className="eyebrow">Mac Node</p><h2>Command test</h2></div></div>
            <p className="description">Queue a persisted, allowlisted macOS notification command.</p>
            <button disabled={busy !== null} onClick={() => void invoke("notify", "/api/v1/commands", { node_id: "macbook", command_type: "notification.show", payload: { title: "Home Platform", message: "Dashboard command acknowledged." } })}>{busy === "notify" ? "Sending…" : "Send test notification"}</button>
          </section>
        </div>

        <section className="panel">
          <div className="panel-heading"><div><p className="eyebrow">Attention</p><h2>Why the LEDs are active</h2></div></div>
          <div className="list">{snapshot.alerts.length ? snapshot.alerts.map((alert: AlertRecord) => <article className="alert-row" key={alert.id}><span className={`severity ${alert.severity}`} /><div><strong>{alert.title}</strong><p>{alert.detail || alert.kind}</p></div>{alert.dismissible && <button className="secondary" disabled={busy !== null} onClick={() => void invoke(`dismiss-${alert.id}`, `/api/v1/alerts/${alert.id}/dismiss`)}>Dismiss</button>}</article>) : <p className="empty">No action is required. Physical status LEDs are off.</p>}</div>
        </section>
        </>}
      </section>
    </main>
  );
}
