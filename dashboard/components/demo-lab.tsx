"use client";

import { useMemo, useState } from "react";

import { demoModules, demoScenarios, type DemoProfile } from "../lib/demo";
import type { Snapshot } from "../lib/types";

export type DemoMode = "simulation" | "live";
type LiveAction = "lights" | "automation" | "notification";
type ActionFeedback = { tone: "success" | "error"; message: string } | null;

type SimulationState = {
  lightsOn: boolean;
  automation: "ready" | "completed";
  notificationSent: boolean;
  activity: string[];
};

const initialSimulation: SimulationState = {
  lightsOn: true,
  automation: "ready",
  notificationSent: false,
  activity: ["Demo environment loaded. No request was sent to your home."],
};

function displayStatus(status: string) {
  return status.replaceAll("-", " ");
}

function statusTone(status: string) {
  return status === "online" || status === "healthy" || status === "completed" ? "good" : status === "offline" ? "bad" : "calm";
}

export function DemoLab({
  mode,
  profile,
  isLiveUnlocked,
  snapshot,
  busy,
  actionFeedback,
  onModeChange,
  onProfileChange,
  onUnlockLive,
  onRefreshLive,
  onLiveAction,
}: {
  mode: DemoMode;
  profile: DemoProfile;
  isLiveUnlocked: boolean;
  snapshot: Snapshot;
  busy: string | null;
  actionFeedback: ActionFeedback;
  onModeChange: (mode: DemoMode) => void;
  onProfileChange: (profile: DemoProfile) => void;
  onUnlockLive: () => void;
  onRefreshLive: () => void;
  onLiveAction: (action: LiveAction) => void;
}) {
  const [simulation, setSimulation] = useState<SimulationState>(initialSimulation);
  const [showLiveConfirmation, setShowLiveConfirmation] = useState(false);
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null);
  const scenario = demoScenarios[profile];
  const livePiNodes = useMemo(() => snapshot.nodes.filter((node) => {
    const capabilities = node.capabilities.capabilities;
    return node.id.includes("pi") || node.name.toLowerCase().includes("pi") || Array.isArray(capabilities) && capabilities.includes("kiosk");
  }), [snapshot.nodes]);
  const liveMedia = useMemo(() => snapshot.providers.filter((provider) => {
    return provider.service_id.includes("brio") || provider.service_id.includes("media") || Boolean(provider.capabilities["private-media-stream"]);
  }), [snapshot.providers]);

  const selectMode = (nextMode: DemoMode) => {
    if (nextMode === "simulation") {
      onModeChange("simulation");
      return;
    }
    if (isLiveUnlocked) {
      onModeChange("live");
      return;
    }
    setShowLiveConfirmation(true);
  };

  const runSimulation = (action: LiveAction) => {
    setSimulation((current) => {
      if (action === "lights") {
        const lightsOn = !current.lightsOn;
        return { ...current, lightsOn, activity: [`Simulated living room lights ${lightsOn ? "on" : "off"}. No request was sent to Home Assistant.`, ...current.activity] };
      }
      if (action === "automation") {
        return { ...current, automation: "completed", activity: ["Simulated Safe Test Automation completed all staged checks.", ...current.activity] };
      }
      return { ...current, notificationSent: true, activity: ["Simulated Mac notification delivered to the Demo Lab timeline.", ...current.activity] };
    });
  };

  const copy = async (label: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopyFeedback(`${label} copied`);
    } catch {
      setCopyFeedback("Copy is unavailable here; select the text to copy it.");
    }
  };

  return (
    <section className="demo-lab" aria-labelledby="demo-lab-title">
      <header className="demo-hero">
        <div>
          <p className="eyebrow">Guided sandbox</p>
          <h1 id="demo-lab-title">See Home Platform in motion</h1>
          <p>Explore a realistic home-lab stack on a Mac or Pi before deciding which services should be live in your home.</p>
        </div>
        <div className="mode-switch" aria-label="Demo mode">
          <button className={mode === "simulation" ? "mode-button active" : "mode-button"} aria-pressed={mode === "simulation"} onClick={() => selectMode("simulation")}>Simulation</button>
          <button className={mode === "live" ? "mode-button active live" : "mode-button live"} aria-pressed={mode === "live"} onClick={() => selectMode("live")}>Live controls</button>
        </div>
      </header>

      {showLiveConfirmation && !isLiveUnlocked && <aside className="live-confirmation" aria-live="polite">
        <div><strong>Unlock live controls for this browser session?</strong><p>This can toggle the configured lights, run the Safe Test Automation, and send a Mac notification. Pi kiosk and webcam controls stay read-only.</p></div>
        <div className="confirmation-actions"><button className="secondary" onClick={() => setShowLiveConfirmation(false)}>Keep simulating</button><button onClick={() => { onUnlockLive(); onModeChange("live"); setShowLiveConfirmation(false); }}>Unlock live controls</button></div>
      </aside>}

      <section className="demo-section profile-section" aria-labelledby="profile-title">
        <div className="section-heading"><div><p className="eyebrow">Choose a host</p><h2 id="profile-title">Two profiles, one Control Plane</h2></div><span className="profile-chip">{mode === "live" ? `Detected: ${snapshot.runtime?.hardware_profile ?? "waiting for snapshot"}` : `${scenario.profile} profile`}</span></div>
        <div className="profile-picker" role="group" aria-label="Demo host profile">
          {(Object.keys(demoScenarios) as DemoProfile[]).map((candidate) => <button key={candidate} className={profile === candidate ? "profile-card selected" : "profile-card"} onClick={() => { onProfileChange(candidate); setSimulation(initialSimulation); }}><span>{candidate === "mac" ? "MAC" : "PI"}</span><strong>{demoScenarios[candidate].label}</strong><small>{demoScenarios[candidate].profile}</small></button>)}
        </div>
        {mode === "simulation" ? <div className="scenario-grid">
          <article className="scenario-summary"><p className="eyebrow">{scenario.label}</p><h3>{scenario.headline}</h3><p>{scenario.summary}</p><div className="mini-stats"><span><strong>{scenario.nodes.filter((node) => node.status === "online").length}</strong> active nodes</span><span><strong>{scenario.services.length}</strong> services in view</span></div></article>
          <article className="telemetry-card"><p className="eyebrow">{scenario.telemetryTitle}</p><h3>Clear ownership boundaries</h3><p>{scenario.telemetryDetail}</p><span className="telemetry-safe">Simulation never contacts hardware or APIs.</span></article>
        </div> : <div className="scenario-grid">
          <article className="scenario-summary"><p className="eyebrow">Live snapshot</p><h3>{snapshot.runtime?.node_name ?? "Connecting to the Control Plane"}</h3><p>{snapshot.runtime ? `${snapshot.runtime.node_id} is reporting the ${snapshot.runtime.hardware_profile} profile.` : "Live data will appear when the Control Plane responds."}</p><button className="secondary" onClick={onRefreshLive}>Refresh live data</button></article>
          <article className="telemetry-card"><p className="eyebrow">Safety boundary</p><h3>Pi hardware is observational</h3><p>Live Demo Lab displays kiosk and media health without sending physical-device commands.</p><span className="telemetry-safe">Only the three approved live actions are available below.</span></article>
        </div>}
      </section>

      <section className="demo-section" aria-labelledby="flow-title">
        <div className="section-heading"><div><p className="eyebrow">Architecture tour</p><h2 id="flow-title">How a home event travels</h2></div></div>
        <div className="flow-map" aria-label="Dashboard connects to the Control Plane, which persists state and sends MQTT messages to Mac, Pi, Home Assistant, and media modules">
          <div className="flow-node primary"><strong>Dashboard</strong><span>Private browser UI</span></div><span className="flow-arrow">→</span><div className="flow-node primary"><strong>Control Plane</strong><span>API + durable state</span></div><span className="flow-arrow">→</span><div className="flow-node bus"><strong>MQTT bus</strong><span>State + commands</span></div><span className="flow-arrow">→</span><div className="flow-destinations"><span>Mac Node</span><span>Pi hardware</span><span>Home Assistant</span><span>Private media</span></div>
        </div>
      </section>

      <section className="demo-section demo-operations" aria-labelledby="operations-title">
        <div className="section-heading"><div><p className="eyebrow">Try the workflow</p><h2 id="operations-title">{mode === "simulation" ? "Safe, local simulation" : "Approved live controls"}</h2></div><span className={mode === "simulation" ? "mode-badge sim" : "mode-badge live"}>{mode === "simulation" ? "No network requests" : "Live session unlocked"}</span></div>
        <div className="action-grid">
          <article className="action-card"><span className="action-icon">◐</span><h3>Living Room Lights</h3><p>{mode === "simulation" ? `Simulated state: ${simulation.lightsOn ? "on" : "off"}` : "Uses the configured Home Assistant light group."}</p><button disabled={busy !== null} onClick={() => mode === "simulation" ? runSimulation("lights") : onLiveAction("lights")}>{mode === "simulation" ? `Turn simulated lights ${simulation.lightsOn ? "off" : "on"}` : busy === "demo-lights" ? "Sending…" : "Toggle live lights"}</button></article>
          <article className="action-card"><span className="action-icon">✓</span><h3>Safe Test Automation</h3><p>{mode === "simulation" ? simulation.automation === "completed" ? "Simulated stages completed." : "Walk through a durable staged run." : "Queues the existing safe test run."}</p><button disabled={busy !== null} onClick={() => mode === "simulation" ? runSimulation("automation") : onLiveAction("automation")}>{mode === "simulation" ? "Run simulated automation" : busy === "demo-automation" ? "Starting…" : "Run live safe test"}</button></article>
          <article className="action-card"><span className="action-icon">⌁</span><h3>Mac Notification</h3><p>{mode === "simulation" ? simulation.notificationSent ? "Simulated notification delivered." : "Send an event through the demo timeline." : "Queues an allowlisted macOS notification."}</p><button disabled={busy !== null} onClick={() => mode === "simulation" ? runSimulation("notification") : onLiveAction("notification")}>{mode === "simulation" ? "Simulate notification" : busy === "demo-notification" ? "Sending…" : "Send live notification"}</button></article>
        </div>
        {mode === "simulation" ? <div className="activity-log" aria-live="polite"><strong>Demo timeline</strong>{simulation.activity.slice(0, 3).map((activity) => <p key={activity}>{activity}</p>)}</div> : actionFeedback && <div className={`action-feedback ${actionFeedback.tone}`} role="status">{actionFeedback.message}</div>}
      </section>

      <section className="demo-section" aria-labelledby="telemetry-title">
        <div className="section-heading"><div><p className="eyebrow">Read-only hardware telemetry</p><h2 id="telemetry-title">Pi kiosk and private media</h2></div><span className="read-only">Read only</span></div>
        {mode === "simulation" ? <div className="telemetry-grid">{scenario.nodes.map((node) => <article className="telemetry-item" key={node.name}><span className={`status-indicator ${statusTone(node.status)}`} /><div><strong>{node.name}</strong><p>{node.role} · {node.detail}</p></div><span className="pill">{displayStatus(node.status)}</span></article>)}{scenario.services.map((service) => <article className="telemetry-item" key={service.name}><span className={`status-indicator ${statusTone(service.status)}`} /><div><strong>{service.name}</strong><p>{service.capability}</p></div><span className="pill">{displayStatus(service.status)}</span></article>)}</div> : <div className="telemetry-grid">{livePiNodes.map((node) => <article className="telemetry-item" key={node.id}><span className={`status-indicator ${statusTone(node.status)}`} /><div><strong>{node.name}</strong><p>{node.health} · {node.id}</p></div><span className="pill">{displayStatus(node.status)}</span></article>)}{liveMedia.map((provider) => <article className="telemetry-item" key={provider.id}><span className={`status-indicator ${statusTone(provider.health)}`} /><div><strong>{provider.service_id}</strong><p>{provider.node_id} · private media telemetry</p></div><span className="pill">{displayStatus(provider.health)}</span></article>)}{!livePiNodes.length && !liveMedia.length && <p className="empty telemetry-empty">No Pi kiosk or media telemetry is reporting in this live snapshot.</p>}</div>}
      </section>

      <section className="demo-section" aria-labelledby="module-title">
        <div className="section-heading"><div><p className="eyebrow">Build your own</p><h2 id="module-title">Working module patterns</h2></div></div>
        <div className="module-grid">{demoModules.map((module) => <article className="module-card" key={module.title}><span className="module-label">{module.label}</span><h3>{module.title}</h3><p>{module.summary}</p><dl><div><dt>Flow</dt><dd>{module.flow}</dd></div><div><dt>Add one like it</dt><dd>{module.add}</dd></div></dl><div className="file-list">{module.files.map((file) => <code key={file}>{file}</code>)}</div></article>)}</div>
      </section>

      <section className="demo-section setup-guide" aria-labelledby="setup-title">
        <div className="section-heading"><div><p className="eyebrow">Run it yourself</p><h2 id="setup-title">{scenario.label} setup guide</h2></div><span className="profile-chip">{scenario.profile}</span></div>
        <p className="setup-intro">These steps select the host profile at deployment time. The Dashboard cannot and should not change host settings for you.</p>
        <div className="setup-grid"><article><h3>Before you start</h3><ul>{scenario.prerequisites.map((item) => <li key={item}>{item}</li>)}</ul></article><article><div className="code-heading"><h3>Environment</h3><button className="copy-button" onClick={() => void copy("Environment", scenario.environment)}>Copy</button></div><pre><code>{scenario.environment}</code></pre></article><article><div className="code-heading"><h3>Start the profile</h3><button className="copy-button" onClick={() => void copy("Launch command", scenario.launch)}>Copy</button></div><pre><code>{scenario.launch}</code></pre><div className="code-heading"><h3>Verify private access</h3><button className="copy-button" onClick={() => void copy("Verification commands", scenario.verify)}>Copy</button></div><pre><code>{scenario.verify}</code></pre></article></div>
        {scenario.warning && <p className="setup-warning">{scenario.warning}</p>}
        {copyFeedback && <p className="copy-feedback" aria-live="polite">{copyFeedback}</p>}
      </section>
    </section>
  );
}
