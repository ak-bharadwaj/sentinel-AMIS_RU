"use client";
import React, { useState, useEffect, useRef } from "react";

// ── Helpers ──────────────────────────────────────────────────────────────────
function getLevel(value, criticalAbove, warningAbove, invertScale = false) {
  if (invertScale) {
    if (value < (100 - criticalAbove)) return "critical";
    if (value < (100 - warningAbove))  return "warning";
    return "good";
  }
  if (value >= criticalAbove) return "critical";
  if (value >= warningAbove)  return "warning";
  return "good";
}

const LEVEL_COLORS = {
  critical: "#ef4444",
  warning:  "#f59e0b",
  good:     "#10b981",
  info:     "#38bdf8",
  neutral:  "#64748b",
};

function KpiCard({ icon, label, value, unit, level, trend, subtitle, barValue }) {
  const color = LEVEL_COLORS[level] || LEVEL_COLORS.neutral;
  return (
    <div className={`kpi-card kpi-card-${level || "neutral"}`}>
      {/* Background radial glow */}
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        background: `radial-gradient(circle at 80% 20%, ${color}20, transparent 60%)`
      }} />

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", position: "relative" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "5px" }}>
          <span style={{ fontSize: "0.78rem" }}>{icon}</span>
          <span className="kpi-label">{label}</span>
        </div>
        {trend && (
          <span style={{
            fontSize: "0.55rem", fontWeight: 700,
            color: trend === "up" ? "#ef4444" : trend === "down" ? "#10b981" : "#94a3b8",
            padding: "1px 4px", borderRadius: "3px",
            background: trend === "up" ? "rgba(239,68,68,0.12)" : trend === "down" ? "rgba(16,185,129,0.12)" : "transparent"
          }}>
            {trend === "up" ? "▲" : trend === "down" ? "▼" : "─"}
          </span>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: "4px", position: "relative" }}>
        <span className="kpi-value" style={{ color }}>{value}</span>
        {unit && <span style={{ fontSize: "0.6rem", color: "#64748b", fontWeight: 600 }}>{unit}</span>}
      </div>

      {barValue !== undefined && (
        <div className="kpi-bar-track">
          <div className="kpi-bar-fill" style={{
            width: `${Math.max(0, Math.min(100, barValue))}%`,
            background: color,
            boxShadow: `0 0 4px ${color}`
          }} />
        </div>
      )}

      {subtitle && <div className="kpi-subtitle">{subtitle}</div>}
    </div>
  );
}

export default function SituationDashboard({ situationAssessment, metrics, telemetry, disasterType, agents }) {
  // Live clock — updates every second
  const [clockStr, setClockStr] = useState("");
  useEffect(() => {
    const tick = () => setClockStr(new Date().toLocaleTimeString());
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  // Track previous values for trend arrows
  const prevRef = useRef({});

  const sa  = situationAssessment || {};
  const sim = metrics || {};

  const severityPct  = Math.round((sa.severity_index || 0) * 100);
  const medDemand    = (sa.active_demands?.medical || 0).toFixed(1);
  const infraDamage  = Math.round((sa.damage_ratios?.infrastructure_damage || 0) * 100);
  const commsHealth  = Math.round(sa.communication_coverage_index ?? (telemetry?.belief?.communication_health ?? 100));
  const decisionStab = Math.round(sa.decision_stability_index ?? 100);
  const popAtRisk    = Math.round((sa.damage_ratios?.affected_population || 0) * 100);
  const savedCount   = sim.total_survivors_saved || 0;
  const missionTime  = sim.simulation_time || 0;

  // Compute per-agent resource stress
  const resourceStress = (() => {
    const list = agents || [];
    if (!list.length) return 0;
    const avgFuel = list.reduce((acc, a) => acc + (a.fuel ?? 100), 0) / list.length;
    return Math.round(100 - avgFuel);
  })();

  // Determine trend (compare to previous render)
  function getTrend(key, current) {
    const prev = prevRef.current[key];
    let t = null;
    if (prev !== undefined) {
      if (current > prev + 1) t = "up";
      else if (current < prev - 1) t = "down";
    }
    prevRef.current[key] = current;
    return t;
  }

  const disasterPhase = (() => {
    if (!sa.severity_index) return "STANDBY";
    if (sa.severity_index >= 0.8) return "CRITICAL PHASE";
    if (sa.severity_index >= 0.6) return "ACUTE RESPONSE";
    if (sa.severity_index >= 0.35) return "ACTIVE RESPONSE";
    return "MONITORING";
  })();

  const kpis = [
    {
      icon: "🔴", label: "Severity Index",
      value: `${severityPct}`, unit: "%",
      level: getLevel(severityPct, 70, 40),
      barValue: severityPct,
      subtitle: disasterPhase,
      trend: getTrend("severity", severityPct)
    },
    {
      icon: "🏥", label: "Medical Demand",
      value: medDemand, unit: "pts",
      level: getLevel(parseFloat(medDemand), 5, 2),
      subtitle: "Immediate triage load",
      trend: getTrend("med", parseFloat(medDemand))
    },
    {
      icon: "🏗️", label: "Infra Damage",
      value: `${infraDamage}`, unit: "%",
      level: getLevel(infraDamage, 60, 30),
      barValue: infraDamage,
      subtitle: "Roads & bridges",
      trend: getTrend("infra", infraDamage)
    },
    {
      icon: "📡", label: "Comms Health",
      value: `${commsHealth}`, unit: "%",
      level: getLevel(commsHealth, 100 - 30, 100 - 60, true),
      barValue: commsHealth,
      subtitle: "Network coverage",
      trend: getTrend("comms", commsHealth)
    },
    {
      icon: "⚡", label: "Resource Stress",
      value: `${resourceStress}`, unit: "%",
      level: getLevel(resourceStress, 70, 40),
      barValue: resourceStress,
      subtitle: "Fleet fuel depletion",
      trend: getTrend("stress", resourceStress)
    },
    {
      icon: "🧠", label: "Decision Stab.",
      value: `${decisionStab}`, unit: "%",
      level: getLevel(decisionStab, 100 - 40, 100 - 70, true),
      barValue: decisionStab,
      subtitle: "AI confidence score",
      trend: getTrend("stability", decisionStab)
    },
    {
      icon: "👥", label: "Pop at Risk",
      value: `${popAtRisk}`, unit: "%",
      level: getLevel(popAtRisk, 50, 20),
      barValue: popAtRisk,
      subtitle: "Of initial population",
      trend: getTrend("pop", popAtRisk)
    },
    {
      icon: "🚨", label: "Phase",
      value: disasterPhase.split(" ")[0],
      unit: "",
      level: disasterPhase === "CRITICAL PHASE" ? "critical" : disasterPhase === "ACUTE RESPONSE" ? "warning" : "info",
      subtitle: `T+${missionTime}m · ${savedCount} rescued`
    }
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
        <div className="section-header section-header-cyan" style={{ marginBottom: 0, border: "none" }}>
          SITUATION DASHBOARD
        </div>
        <span style={{
          fontSize: "0.52rem", color: "#334155",
          fontFamily: "'IBM Plex Mono', monospace"
        }}>
          LIVE · {clockStr}
        </span>
      </div>

      <div className="kpi-grid">
        {kpis.map((kpi, i) => <KpiCard key={i} {...kpi} />)}
      </div>
    </div>
  );
}
