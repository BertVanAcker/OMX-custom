import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  Bot,
  CircleStop,
  Gauge,
  Hand,
  ListRestart,
  Minus,
  Play,
  Plus,
  Power,
  Radio,
  RotateCcw,
  Save,
  SlidersHorizontal,
  Trash2
} from "lucide-react";
import "./styles.css";

type Joint = {
  name: string;
  motorId: number;
  minDegrees: number;
  maxDegrees: number;
  homeDegrees: number;
  namedPositions: Record<string, number>;
  controllerClass: string;
};

type TeachPoint = {
  label: string;
  positions: Record<string, number>;
  created_at: number;
};

type AppState = {
  teaching: boolean;
  playing: boolean;
  playbackLoop: boolean;
  positions: Record<string, number | null>;
  sequence: TeachPoint[];
};

type PlaybackSettings = {
  maxStepDegrees: number;
  stepSeconds: number;
  delaySeconds: number;
};

type Page = "manual" | "teach";

const api = async <T,>(path: string, options: RequestInit = {}): Promise<T> => {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });
  const body = await response.json();
  if (!response.ok || body.ok === false) {
    throw new Error(body.error || `Request failed: ${response.status}`);
  }
  return body as T;
};

const formatAngle = (value: number | null | undefined) => (value == null ? "--" : `${value.toFixed(1)} deg`);

const jointBounds = (joint: Joint) => ({
  min: Math.min(joint.minDegrees, joint.maxDegrees),
  max: Math.max(joint.minDegrees, joint.maxDegrees)
});

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

function RobotIllustration({ positions }: { positions: Record<string, number | null> }) {
  const base = positions.base ?? 180;
  const joint1 = positions.joint1 ?? 78;
  const joint2 = positions.joint2 ?? 278;
  const joint3 = positions.joint3 ?? 266;
  const gripper = positions.gripper ?? 250;
  const shoulder = -42 + (joint1 - 78) * 0.12;
  const elbow = 32 - ((joint2 + 360) % 360) * 0.04;
  const wrist = -24 + (joint3 - 266) * 0.16;
  const clawGap = Math.max(8, Math.min(34, gripper - 160));

  return (
    <div className="robot-stage" aria-label="Robot pose visualization">
      <svg viewBox="0 0 760 420" role="img">
        <rect x="278" y="330" width="210" height="54" rx="10" className="robot-base" />
        <ellipse cx="382" cy="330" rx="116" ry="26" className="robot-shadow" />
        <g transform={`translate(383 320) rotate(${(base - 180) * 0.12})`}>
          <path d="M-30 8 L18 -8 L72 8 L24 26 Z" className="robot-platform" />
          <rect x="-20" y="-64" width="42" height="90" rx="18" className="robot-white" />
          <circle cx="0" cy="-65" r="28" className="joint-disc" />
          <g transform={`translate(0 -68) rotate(${shoulder})`}>
            <rect x="-12" y="-134" width="24" height="150" rx="12" className="robot-link-light" />
            <rect x="20" y="-126" width="22" height="142" rx="11" className="robot-link-dark" />
            <circle cx="30" cy="-132" r="25" className="joint-disc" />
            <g transform={`translate(30 -132) rotate(${elbow})`}>
              <rect x="-126" y="-12" width="146" height="24" rx="12" className="robot-link-dark" />
              <rect x="-124" y="24" width="142" height="20" rx="10" className="robot-link-light" />
              <circle cx="-130" cy="6" r="20" className="joint-disc" />
              <g transform={`translate(-130 6) rotate(${wrist})`}>
                <rect x="-82" y="-10" width="86" height="20" rx="10" className="robot-link-dark" />
                <rect x="-125" y="-28" width="46" height="56" rx="8" className="robot-tool" />
                <path d={`M-126 -18 L-${156 + clawGap} -38`} className="claw-line" />
                <path d={`M-126 18 L-${156 + clawGap} 38`} className="claw-line" />
              </g>
            </g>
          </g>
        </g>
      </svg>
      <div className="stage-caption">
        <Bot size={18} />
        <span>Live joint pose</span>
      </div>
    </div>
  );
}

function Header({
  page,
  setPage,
  connected,
  message,
  onRelease,
  onEnable
}: {
  page: Page;
  setPage: (page: Page) => void;
  connected: boolean;
  message: string;
  onRelease: () => void;
  onEnable: () => void;
}) {
  return (
    <header className="app-header">
      <div className="status-cluster">
        <Radio className={connected ? "ok" : "warn"} />
        <span className={connected ? "status-pill ok" : "status-pill warn"}>{connected ? "API online" : "API offline"}</span>
      </div>
      <nav className="page-tabs" aria-label="Control pages">
        <button className={page === "manual" ? "active" : ""} onClick={() => setPage("manual")}>
          <SlidersHorizontal size={18} />
          Manual
        </button>
        <button className={page === "teach" ? "active" : ""} onClick={() => setPage("teach")}>
          <Save size={18} />
          Teach & Play
        </button>
      </nav>
      <div className="header-actions">
        <span className="log-text">{message || "Ready"}</span>
        <button className="icon-button" onClick={onRelease} title="Release all servos">
          <CircleStop size={22} />
        </button>
        <button className="icon-button" onClick={onEnable} title="Enable all servos">
          <Power size={22} />
        </button>
      </div>
    </header>
  );
}

function ManualPage({
  joints,
  positions,
  onMove
}: {
  joints: Joint[];
  positions: Record<string, number | null>;
  onMove: (joint: string, angle: number) => void;
}) {
  const ordered = useMemo(() => joints.filter((joint) => joint.name !== "gripper"), [joints]);
  const gripper = joints.find((joint) => joint.name === "gripper");

  return (
    <main className="work-area">
      <section className="visual-column">
        <RobotIllustration positions={positions} />
        <div className="metric-strip">
          {joints.map((joint) => (
            <div key={joint.name} className="metric">
              <span>{joint.name}</span>
              <strong>{formatAngle(positions[joint.name] ?? joint.homeDegrees)}</strong>
            </div>
          ))}
        </div>
      </section>
      <section className="control-panel">
        <div className="panel-title">
          <Gauge />
          <h2>Manual Joint Control</h2>
        </div>
        <div className="joint-grid">
          {ordered.map((joint) => (
            <JointControl key={joint.name} joint={joint} value={positions[joint.name] ?? joint.homeDegrees} onMove={onMove} />
          ))}
        </div>
        <JogControl joints={ordered} positions={positions} onMove={onMove} />
        {gripper && (
          <div className="gripper-band">
            <div>
              <h3>Gripper</h3>
              <span>{formatAngle(positions.gripper ?? gripper.homeDegrees)}</span>
            </div>
            <div className="gripper-buttons">
              {Object.entries(gripper.namedPositions).map(([name, angle]) => (
                <button key={name} onClick={() => onMove(gripper.name, angle)}>
                  <Hand size={18} />
                  {name}
                </button>
              ))}
            </div>
          </div>
        )}
      </section>
    </main>
  );
}

function JogControl({
  joints,
  positions,
  onMove
}: {
  joints: Joint[];
  positions: Record<string, number | null>;
  onMove: (joint: string, angle: number) => void;
}) {
  const [stepDegrees, setStepDegrees] = useState(5);

  const moveBy = (joint: Joint, delta: number) => {
    const { min, max } = jointBounds(joint);
    const current = positions[joint.name] ?? joint.homeDegrees;
    onMove(joint.name, clamp(current + delta, min, max));
  };

  return (
    <div className="jog-panel">
      <div className="jog-header">
        <div>
          <h3>Button Control</h3>
          <span>{stepDegrees} deg step</span>
        </div>
        <label className="step-control">
          <span>Step</span>
          <input
            type="range"
            min="1"
            max="20"
            value={stepDegrees}
            onChange={(event) => setStepDegrees(Number(event.target.value))}
          />
        </label>
      </div>
      <div className="jog-pad">
        {joints.map((joint) => {
          const value = positions[joint.name] ?? joint.homeDegrees;
          const { min, max } = jointBounds(joint);
          return (
            <div className="jog-row" key={joint.name}>
              <button
                className="jog-button"
                onClick={() => moveBy(joint, -stepDegrees)}
                disabled={value <= min}
                title={`${joint.name} down`}
              >
                <Minus size={18} />
              </button>
              <div className="jog-readout">
                <strong>{joint.name}</strong>
                <span>{formatAngle(value)}</span>
              </div>
              <button
                className="jog-button"
                onClick={() => moveBy(joint, stepDegrees)}
                disabled={value >= max}
                title={`${joint.name} up`}
              >
                <Plus size={18} />
              </button>
              <button className="jog-home" onClick={() => onMove(joint.name, joint.homeDegrees)} title={`${joint.name} home`}>
                <RotateCcw size={17} />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function JointControl({
  joint,
  value,
  onMove
}: {
  joint: Joint;
  value: number;
  onMove: (joint: string, angle: number) => void;
}) {
  const [draft, setDraft] = useState(value);
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    if (!editing) {
      setDraft(value);
    }
  }, [editing, value]);

  const { min, max } = jointBounds(joint);

  return (
    <div className="joint-row">
      <div className="joint-meta">
        <strong>{joint.name}</strong>
        <span>ID {joint.motorId} · {joint.controllerClass.replace("PyController", "")}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        value={draft}
        onChange={(event) => {
          setEditing(true);
          setDraft(Number(event.target.value));
        }}
        onPointerDown={() => setEditing(true)}
        onPointerUp={() => {
          setEditing(false);
          onMove(joint.name, draft);
        }}
      />
      <label>
        <span>{draft.toFixed(0)}</span>
        <input
          type="number"
          value={Math.round(draft)}
          onChange={(event) => {
            setEditing(true);
            setDraft(Number(event.target.value));
          }}
          onBlur={() => {
            setEditing(false);
            onMove(joint.name, draft);
          }}
        />
      </label>
      <div className="joint-buttons">
        <button onClick={() => onMove(joint.name, joint.homeDegrees)}>Home</button>
        <button onClick={() => onMove(joint.name, joint.minDegrees)}>Min</button>
        <button onClick={() => onMove(joint.name, joint.maxDegrees)}>Max</button>
        <button className="primary-mini" onClick={() => onMove(joint.name, draft)}>Move</button>
      </div>
    </div>
  );
}

function TeachingPage({
  joints,
  state,
  playback,
  playLoop,
  onPlaybackChange,
  onPlayLoopChange,
  onEnter,
  onExit,
  onCapture,
  onDeletePoint,
  onClear,
  onPlay,
  onStop
}: {
  joints: Joint[];
  state: AppState;
  playback: PlaybackSettings;
  playLoop: boolean;
  onPlaybackChange: (key: keyof PlaybackSettings, value: number) => void;
  onPlayLoopChange: (value: boolean) => void;
  onEnter: () => void;
  onExit: () => void;
  onCapture: () => void;
  onDeletePoint: (index: number) => void;
  onClear: () => void;
  onPlay: () => void;
  onStop: () => void;
}) {
  return (
    <main className="work-area">
      <section className="visual-column">
        <RobotIllustration positions={state.positions} />
        <div className={state.teaching ? "teaching-banner active" : "teaching-banner"}>
          <AlertTriangle size={18} />
          {state.teaching ? "Teaching mode active: servos released" : "Enter teaching mode to release servos and position the arm by hand"}
        </div>
        {state.playing && (
          <div className="teaching-banner active">
            <Play size={18} />
            {state.playbackLoop ? "Playback running in continuous loop" : "Playback running"}
          </div>
        )}
      </section>
      <section className="control-panel teach-panel">
        <div className="panel-title">
          <Activity />
          <h2>Teaching & Playback</h2>
        </div>
        <div className="playback-settings" aria-label="Playback parameters">
          <label>
            <span>Max step (deg)</span>
            <input
              type="number"
              min="0.1"
              step="0.1"
              value={playback.maxStepDegrees}
              onChange={(event) => onPlaybackChange("maxStepDegrees", Number(event.target.value))}
            />
          </label>
          <label>
            <span>Step seconds</span>
            <input
              type="number"
              min="0"
              step="0.01"
              value={playback.stepSeconds}
              onChange={(event) => onPlaybackChange("stepSeconds", Number(event.target.value))}
            />
          </label>
          <label>
            <span>Delay seconds</span>
            <input
              type="number"
              min="0"
              step="0.01"
              value={playback.delaySeconds}
              onChange={(event) => onPlaybackChange("delaySeconds", Number(event.target.value))}
            />
          </label>
        </div>
        <label className="loop-toggle">
          <input type="checkbox" checked={playLoop} onChange={(event) => onPlayLoopChange(event.target.checked)} />
          <span>Continuous loop</span>
        </label>
        <div className="teach-actions">
          <button className="primary" onClick={onEnter}>Enter teaching mode</button>
          <button onClick={onExit}>Exit teaching</button>
          <button onClick={onCapture} disabled={!state.teaching}>
            <Save size={18} />
            Store position
          </button>
          <button onClick={onPlay} disabled={state.sequence.length === 0 || state.playing}>
            <Play size={18} />
            Play sequence
          </button>
          <button onClick={onStop} disabled={!state.playing}>
            <CircleStop size={18} />
            Stop playback
          </button>
          <button className="danger" onClick={onClear}>
            <Trash2 size={18} />
            Clear
          </button>
        </div>
        <div className="joint-table">
          {joints.map((joint) => (
            <div key={joint.name} className="table-row">
              <span>{joint.name}</span>
              <strong>{formatAngle(state.positions[joint.name])}</strong>
              <small>{joint.minDegrees}..{joint.maxDegrees}</small>
            </div>
          ))}
        </div>
        <div className="sequence-list">
          <div className="subhead">
            <ListRestart size={18} />
            <h3>Taught sequence</h3>
          </div>
          {state.sequence.length === 0 ? (
            <p className="empty">No positions stored yet.</p>
          ) : (
            state.sequence.map((point, index) => (
              <div key={`${point.created_at}-${index}`} className="sequence-point">
                <div className="sequence-point-head">
                  <strong>{index + 1}. {point.label}</strong>
                  <button className="danger ghost" onClick={() => onDeletePoint(index)} disabled={state.playing}>
                    <Trash2 size={16} />
                    Delete
                  </button>
                </div>
                <span>{Object.entries(point.positions).map(([name, angle]) => `${name} ${angle.toFixed(0)} deg`).join(" · ")}</span>
              </div>
            ))
          )}
        </div>
      </section>
    </main>
  );
}

function App() {
  const [page, setPage] = useState<Page>("manual");
  const [joints, setJoints] = useState<Joint[]>([]);
  const [state, setState] = useState<AppState>({ teaching: false, playing: false, playbackLoop: false, positions: {}, sequence: [] });
  const [connected, setConnected] = useState(false);
  const [message, setMessage] = useState("");
  const [playLoop, setPlayLoop] = useState(false);
  const [playback, setPlayback] = useState<PlaybackSettings>({
    maxStepDegrees: 4,
    stepSeconds: 0.04,
    delaySeconds: 0.35
  });

  const updatePlaybackSetting = (key: keyof PlaybackSettings, value: number) => {
    if (!Number.isFinite(value)) {
      return;
    }
    setPlayback((previous) => ({
      ...previous,
      [key]: value
    }));
  };

  const refreshState = async () => {
    const next = await api<{
      teaching: boolean;
      playing: boolean;
      playbackLoop: boolean;
      positions: Record<string, number | null>;
      sequence: TeachPoint[];
    }>("/api/state");
    setState({
      teaching: next.teaching,
      playing: next.playing,
      playbackLoop: next.playbackLoop,
      positions: next.positions,
      sequence: next.sequence
    });
  };

  useEffect(() => {
    const load = async () => {
      try {
        const config = await api<{ joints: Joint[] }>("/api/config");
        setJoints(config.joints);
        await refreshState();
        setConnected(true);
        setMessage("Robot API connected");
      } catch (error) {
        setConnected(false);
        setMessage(error instanceof Error ? error.message : "Robot API unavailable");
      }
    };
    void load();
    const timer = window.setInterval(() => void refreshState().catch(() => setConnected(false)), 2500);
    return () => window.clearInterval(timer);
  }, []);

  const runAction = async (label: string, action: () => Promise<unknown>) => {
    try {
      setMessage(label);
      await action();
      await refreshState();
      setConnected(true);
      setMessage("Done");
    } catch (error) {
      setConnected(false);
      setMessage(error instanceof Error ? error.message : "Action failed");
    }
  };

  return (
    <div className="app-shell">
      <Header
        page={page}
        setPage={setPage}
        connected={connected}
        message={message}
        onRelease={() => runAction("Releasing servos", () => api("/api/torque", { method: "POST", body: JSON.stringify({ enabled: false }) }))}
        onEnable={() => runAction("Enabling servos", () => api("/api/torque", { method: "POST", body: JSON.stringify({ enabled: true }) }))}
      />
      {page === "manual" ? (
        <ManualPage
          joints={joints}
          positions={state.positions}
          onMove={(joint, angle) => runAction(`Moving ${joint}`, () => api("/api/manual/move", { method: "POST", body: JSON.stringify({ joint, angle }) }))}
        />
      ) : (
        <TeachingPage
          joints={joints}
          state={state}
          playback={playback}
          playLoop={playLoop}
          onPlaybackChange={updatePlaybackSetting}
          onPlayLoopChange={setPlayLoop}
          onEnter={() => runAction("Entering teaching mode", () => api("/api/teaching/enter", { method: "POST" }))}
          onExit={() => runAction("Exiting teaching mode", () => api("/api/teaching/exit", { method: "POST" }))}
          onCapture={() => runAction("Capturing point", () => api("/api/teaching/capture", { method: "POST", body: JSON.stringify({}) }))}
          onDeletePoint={(index) =>
            runAction(`Deleting point ${index + 1}`, () =>
              api("/api/teaching/delete", { method: "POST", body: JSON.stringify({ index }) })
            )
          }
          onClear={() => runAction("Clearing sequence", () => api("/api/teaching/clear", { method: "POST" }))}
          onPlay={() =>
            runAction(playLoop ? "Starting loop playback" : "Playing sequence", () =>
              api("/api/teaching/play", {
                method: "POST",
                body: JSON.stringify({ ...playback, loop: playLoop })
              })
            )
          }
          onStop={() => runAction("Stopping playback", () => api("/api/teaching/stop", { method: "POST" }))}
        />
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
