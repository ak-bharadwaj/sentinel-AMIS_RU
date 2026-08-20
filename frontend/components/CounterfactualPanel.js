"use client";
import React, { useState, useCallback, useRef } from "react";

const API = "http://localhost:8000/api/v1";

const PRESETS = [
  { id: "bridge_collapse",  label: "Bridge Collapse",  icon: "🌉", description: "Primary bridge collapses blocking main route",      color: "#ef4444", params: { bridge_collapse: true } },
  { id: "rainfall_surge",   label: "+30% Rainfall",    icon: "🌧️", description: "Rainfall intensity increases 30%, raising flood levels", color: "#38bdf8", params: { rainfall_multiplier: 1.3 } },
  { id: "comms_failure",    label: "Comms Failure",    icon: "📵", description: "50% of communication nodes go dark",                color: "#f59e0b", params: { comms_decay_factor: 0.5, comms_failure: true } },
  { id: "heli_grounded",   label: "No Helicopters",   icon: "🚁", description: "All helicopter assets grounded (weather)",          color: "#a78bfa", params: { helicopter_grounded: true } },
  { id: "mass_casualty",   label: "Mass Casualty",    icon: "🏥", description: "Hospital capacity exceeded — triage overload",     color: "#f97316", params: { mass_casualty: true, triage_scale: 2.0 } },
  { id: "aftershock",      label: "Aftershock +6.5",  icon: "🌍", description: "Secondary earthquake magnitude 6.5 strikes",       color: "#dc2626", params: { aftershock: true, aftershock_magnitude: 6.5 } },
];

const TAB_ACCENT_MAP = {
  situation: "rgba(56,189,248,0.18)",
  telemetry: "rgba(99,102,241,0.18)",
  analytics: "rgba(99,102,241,0.18)",
  xai:       "rgba(168,85,247,0.18)",
  counterfactual: "rgba(245,158,11,0.18)",
  experiments: "rgba(99,102,241,0.18)",
};

function ScenarioCard({ preset, selected, onSelect }) {
  const isSelected = selected === preset.id;
  return (
    <div
      className="cf-scenario-card"
      onClick={() => onSelect(isSelected ? null : preset.id)}
      role="button"
      aria-pressed={isSelected}
      style={{
        border: `1px solid ${isSelected ? preset.color : "rgba(255,255,255,0.08)"}`,
        background: isSelected ? `${preset.color}14` : "rgba(255,255,255,0.02)",
        boxShadow: isSelected ? `0 0 8px ${preset.color}30` : "none",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "2px" }}>
        <span style={{ fontSize: "0.85rem" }}>{preset.icon}</span>
        <span style={{ fontSize: "0.6rem", fontWeight: 700, color: isSelected ? preset.color : "#94a3b8" }}>
          {preset.label}
        </span>
        {isSelected && (
          <span style={{ marginLeft: "auto", width: "6px", height: "6px", borderRadius: "50%", background: preset.color, boxShadow: `0 0 4px ${preset.color}` }} />
        )}
      </div>
      <div style={{ fontSize: "0.54rem", color: "#475569", lineHeight: 1.3 }}>{preset.description}</div>
    </div>
  );
}

function ResultCard({ title, data, color }) {
  if (!data) return null;
  return (
    <div className="cf-result-card" style={{ border: `1px solid ${color}40`, background: `${color}08` }}>
      <div style={{ fontSize: "0.55rem", fontWeight: 700, color, textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: "5px" }}>
        {title}
      </div>
      {typeof data === "string" ? (
        <div style={{ fontSize: "0.6rem", color: "#94a3b8", lineHeight: 1.4 }}>{data}</div>
      ) : typeof data === "object" ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "3px" }}>
          {Object.entries(data).filter(([k]) => !["feasible"].includes(k)).map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: "0.55rem", color: "#64748b" }}>{k.replace(/_/g, " ")}</span>
              <span style={{
                fontSize: "0.58rem", fontWeight: 700,
                fontFamily: "'IBM Plex Mono', monospace",
                color: typeof v === "boolean" ? (v ? "#10b981" : "#ef4444") : "#e2e8f0"
              }}>
                {typeof v === "boolean" ? (v ? "YES" : "NO") : typeof v === "number" ? v.toFixed(2) : String(v)}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function CounterfactualPanel({ agents }) {
  const [selectedScenario, setSelectedScenario] = useState(null);
  const [loading, setLoading]   = useState(false);
  const [results, setResults]   = useState(null);
  const [delayMins, setDelayMins] = useState(30);
  const abortRef = useRef(null);

  const runAnalysis = useCallback(async () => {
    if (!selectedScenario) return;

    // Cancel any previous in-flight request
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setResults(null);

    try {
      const preset = PRESETS.find(p => p.id === selectedScenario);
      const body = { ...preset.params, delay_minutes: delayMins };

      const res = await fetch(`http://127.0.0.1:8000/api/simulation/counterfactual`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (res.ok) {
        const data = await res.json();
        setResults(data);
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch (e) {
      if (e.name === "AbortError") return; // user cancelled — don't update state
      // Graceful local fallback
      const preset = PRESETS.find(p => p.id === selectedScenario);
      setResults({
        scenario: preset.label,
        impact_summary: `Offline estimate for "${preset.label}". Start a simulation to get live analysis.`,
        delay_penalty: {
          delay_minutes: delayMins,
          expected_deceased: Math.round(delayMins * 0.4),
          expected_surviving_immediate: Math.round(50 - delayMins * 0.4),
          summary: `A ${delayMins}-minute delay yields ~${Math.round(delayMins * 0.4)} additional fatalities`
        }
      });
    } finally {
      setLoading(false);
    }
  }, [selectedScenario, delayMins]);

  const preset = selectedScenario ? PRESETS.find(p => p.id === selectedScenario) : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div className="section-header section-header-amber" style={{ marginBottom: 0, border: "none" }}>
          COUNTERFACTUAL / WHAT-IF
        </div>
        <span style={{ fontSize: "0.5rem", color: "#64748b" }}>Sensitivity Analysis</span>
      </div>

      {/* Scenario grid */}
      <div style={{ fontSize: "0.55rem", color: "#475569", textTransform: "uppercase", letterSpacing: "0.8px", fontWeight: 700 }}>
        Select Scenario
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "5px" }}>
        {PRESETS.map(p => (
          <ScenarioCard key={p.id} preset={p} selected={selectedScenario} onSelect={setSelectedScenario} />
        ))}
      </div>

      {/* Delay slider */}
      <div style={{ padding: "8px 10px", borderRadius: "7px", background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.07)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.55rem", color: "#64748b", marginBottom: "5px" }}>
          <span style={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px" }}>⏱ Delay Penalty</span>
          <span style={{ color: "#f59e0b", fontFamily: "'IBM Plex Mono', monospace", fontWeight: 700 }}>{delayMins} min</span>
        </div>
        <input
          type="range"
          min={0} max={120} step={5}
          value={delayMins}
          onChange={e => setDelayMins(parseInt(e.target.value))}
          aria-label="Delay penalty in minutes"
          style={{ width: "100%", accentColor: "#f59e0b", cursor: "pointer" }}
        />
        <div style={{ fontSize: "0.52rem", color: "#334155", marginTop: "3px" }}>
          Estimated fatalities from delay: ~{Math.round(delayMins * 0.4)} additional
        </div>
      </div>

      {/* Run button — uses CSS classes */}
      <button
        onClick={runAnalysis}
        disabled={!selectedScenario || loading}
        className={`cf-run-btn ${selectedScenario && !loading ? "enabled" : "disabled-state"}`}
      >
        {loading ? (
          <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}>
            <span className="cf-spinner" />
            Simulating...
          </span>
        ) : (
          `▶ Run ${preset ? preset.label : "Scenario"} Analysis`
        )}
      </button>

      {/* Results */}
      {results && (
        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
          <div style={{ fontSize: "0.55rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.8px", fontWeight: 700 }}>
            Analysis Results
          </div>

          {results.error ? (
            <div style={{ padding: "8px 10px", borderRadius: "6px", background: "rgba(239,68,68,0.06)", border: "1px solid rgba(239,68,68,0.2)", fontSize: "0.6rem", color: "#ef4444" }}>
              {results.error}
            </div>
          ) : (
            <div style={{ maxHeight: "250px", overflowY: "auto" }}>
              {results.impact_summary && (
                <div style={{ padding: "7px 10px", marginBottom: "6px", borderRadius: "6px", background: "rgba(56,189,248,0.06)", border: "1px solid rgba(56,189,248,0.15)", fontSize: "0.6rem", color: "#93c5fd", lineHeight: 1.4 }}>
                  {results.impact_summary}
                </div>
              )}
              <ResultCard title="🌉 Bridge Collapse"    data={results.bridge_collapse}       color="#ef4444" />
              <ResultCard title="🌧️ Rainfall Surge"     data={results.rainfall_sensitivity}  color="#38bdf8" />
              <ResultCard title="📡 Comms Outage"       data={results.comms_failure}         color="#f59e0b" />
              <ResultCard title="🚁 Helicopter Grounded" data={results.helicopter_grounded}  color="#a78bfa" />
              <ResultCard title="⏱️ Delay Impact"       data={results.delay_penalty}         color="#f97316" />
              {Object.entries(results)
                .filter(([k]) => !["error","impact_summary","scenario","parameters","bridge_collapse","rainfall_sensitivity","comms_failure","helicopter_grounded","delay_penalty"].includes(k))
                .map(([k, v]) => (
                  <ResultCard key={k} title={k.replace(/_/g, " ").toUpperCase()} data={v} color="#64748b" />
                ))
              }
            </div>
          )}
        </div>
      )}
    </div>
  );
}
