"use client";
import React, { useState, useEffect, useCallback } from "react";

// ── Tree Node ────────────────────────────────────────────────────────────────
function TreeNode({ node, depth = 0, isResearch = false }) {
  const [expanded, setExpanded] = useState(depth < 2);
  const hasChildren = node.children && node.children.length > 0;

  const conf  = node.confidence ?? node.weight ?? 1.0;
  const confPct = Math.round(conf * 100);
  const confColor = conf >= 0.75 ? "#10b981" : conf >= 0.5 ? "#f59e0b" : "#ef4444";

  const typeIcon = {
    root: "🎯", objective: "🏁", assessment: "📊", threat: "⚠️",
    action: "⚡", resource: "🚁", uncertainty: "❓", constraint: "🔒",
    outcome: "✅", counterfactual: "🔀", sensor: "📡", belief: "🧠", forecast: "🔭",
  }[node.type?.toLowerCase()] ?? "◆";

  const nodeClass = [
    "xai-node",
    hasChildren ? "xai-node-clickable" : "",
    depth === 0 ? "xai-node-root" : ""
  ].filter(Boolean).join(" ");

  return (
    <div style={{ marginLeft: depth > 0 ? `${Math.min(depth * 12, 48)}px` : "0" }}>
      <div
        className={nodeClass}
        onClick={() => hasChildren && setExpanded(e => !e)}
        role={hasChildren ? "button" : undefined}
        aria-expanded={hasChildren ? expanded : undefined}
      >
        {hasChildren && (
          <span style={{
            fontSize: "0.55rem", color: "#38bdf8", marginTop: "1px",
            width: "10px", flexShrink: 0, transition: "transform 0.2s",
            transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
            display: "inline-block"
          }}>▶</span>
        )}
        {!hasChildren && <span style={{ width: "10px", flexShrink: 0 }} />}

        <span style={{ fontSize: "0.7rem", flexShrink: 0 }}>{typeIcon}</span>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "5px", flexWrap: "wrap" }}>
            {node.type && (
              <span style={{
                fontSize: "0.48rem", fontWeight: 700, color: "#475569",
                textTransform: "uppercase", letterSpacing: "0.8px",
                background: "rgba(255,255,255,0.04)", padding: "1px 4px", borderRadius: "2px"
              }}>{node.type}</span>
            )}
            <span style={{
              fontSize: "0.62rem", fontWeight: 600,
              color: depth === 0 ? "#38bdf8" : "#cbd5e1", lineHeight: 1.3
            }}>
              {node.label || node.name || node.title || "(unlabeled)"}
            </span>
          </div>

          {(node.confidence !== undefined || node.weight !== undefined) && (
            <div style={{ display: "flex", alignItems: "center", gap: "4px", marginTop: "2px" }}>
              <div style={{ height: "2px", width: "40px", background: "rgba(255,255,255,0.06)", borderRadius: "1px", overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${confPct}%`, background: confColor, boxShadow: `0 0 3px ${confColor}` }} />
              </div>
              <span style={{ fontSize: "0.5rem", color: confColor, fontFamily: "'IBM Plex Mono', monospace" }}>{confPct}%</span>
            </div>
          )}

          {node.value !== undefined && (
            <div style={{ fontSize: "0.58rem", color: "#64748b", marginTop: "1px" }}>→ {String(node.value)}</div>
          )}

          {node.rationale && (
            <div style={{
              fontSize: "0.57rem", color: "#475569", marginTop: "2px",
              lineHeight: 1.4, fontStyle: "italic",
              borderLeft: "2px solid rgba(56,189,248,0.2)", paddingLeft: "5px"
            }}>{node.rationale}</div>
          )}

          {isResearch && node.equation && (
            <div className="xai-equation">{node.equation}</div>
          )}

          {isResearch && node.parameters && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "3px", marginTop: "2px" }}>
              {Object.entries(node.parameters).map(([k, v]) => (
                <span key={k} style={{
                  fontSize: "0.5rem", color: "#7c3aed",
                  fontFamily: "'IBM Plex Mono', monospace",
                  background: "rgba(124,58,237,0.08)", padding: "1px 4px", borderRadius: "2px"
                }}>
                  {k}={typeof v === "number" ? v.toFixed(3) : String(v)}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {expanded && hasChildren && (
        <div className="xai-tree-children">
          {node.children.map((child, idx) => (
            <TreeNode key={idx} node={child} depth={depth + 1} isResearch={isResearch} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Filter helpers ───────────────────────────────────────────────────────────
function nodeMatchesSearch(node, query) {
  if (!query) return true;
  const q = query.toLowerCase();
  const text = [node.label, node.name, node.title, node.type, node.rationale, node.value]
    .filter(Boolean).join(" ").toLowerCase();
  if (text.includes(q)) return true;
  if (node.children) return node.children.some(c => nodeMatchesSearch(c, query));
  return false;
}

function filterTree(nodes, query) {
  if (!query) return nodes;
  return nodes
    .filter(n => nodeMatchesSearch(n, query))
    .map(n => ({
      ...n,
      children: n.children ? filterTree(n.children, query) : undefined
    }));
}

// ── Main Component ───────────────────────────────────────────────────────────
export default function ExplainabilityPanel({ reasoningTree, latestDecision, isResearch }) {
  const [search, setSearch] = useState("");

  const rootNodes = (() => {
    if (!reasoningTree) return [];
    if (Array.isArray(reasoningTree)) return reasoningTree;
    if (typeof reasoningTree === "object") {
      if (Array.isArray(reasoningTree.tree))     return reasoningTree.tree;
      if (Array.isArray(reasoningTree.children)) return [reasoningTree];
      return [{ label: "Decision Analysis", type: "root", children: Object.entries(reasoningTree).map(([k, v]) => ({
        label: k, value: typeof v === "object" ? JSON.stringify(v) : v, type: "assessment"
      })) }];
    }
    return [];
  })();

  const visibleNodes = filterTree(rootNodes, search.trim());
  const hasData = rootNodes.length > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div className="section-header section-header-purple" style={{ marginBottom: 0, border: "none" }}>
          EXPLAINABILITY / XAI
        </div>
        {isResearch && (
          <span style={{
            fontSize: "0.5rem", padding: "2px 6px", borderRadius: "3px",
            background: "rgba(168,85,247,0.12)", color: "#a855f7",
            border: "1px solid rgba(168,85,247,0.3)", fontWeight: 700
          }}>RESEARCH MODE</span>
        )}
      </div>

      {/* Last decision context */}
      {latestDecision && (
        <div className="xai-last-decision">
          <div style={{ fontSize: "0.55rem", color: "#38bdf8", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: "3px" }}>
            Last AI Decision
          </div>
          <div style={{ fontSize: "0.63rem", color: "#cbd5e1", lineHeight: 1.4 }}>
            {latestDecision.action || latestDecision.description || "Awaiting decision…"}
          </div>
          {latestDecision.confidence !== undefined && (
            <div style={{ fontSize: "0.55rem", color: "#64748b", marginTop: "2px" }}>
              Confidence: <span style={{ color: "#a78bfa", fontWeight: 700, fontFamily: "'IBM Plex Mono', monospace" }}>
                {Math.round(latestDecision.confidence * 100)}%
              </span>
            </div>
          )}
        </div>
      )}

      {/* Search — functional filter */}
      {hasData && (
        <input
          type="text"
          placeholder="Search reasoning nodes…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          aria-label="Search reasoning tree nodes"
          style={{
            background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: "5px", padding: "5px 8px", color: "#e2e8f0",
            fontSize: "0.58rem", outline: "none", width: "100%", boxSizing: "border-box"
          }}
        />
      )}

      {/* Tree */}
      <div style={{ maxHeight: "380px", overflowY: "auto", paddingRight: "4px" }}>
        {!hasData ? (
          <div className="xai-empty-state">
            <div style={{ fontSize: "1.5rem", marginBottom: "8px" }}>🧠</div>
            <div style={{ fontWeight: 700, color: "#475569" }}>Awaiting Decision Cycle</div>
            <div style={{ fontSize: "0.55rem", marginTop: "4px" }}>
              The AI reasoning tree will appear here when a mission phase is active.
            </div>
          </div>
        ) : visibleNodes.length === 0 ? (
          <div className="xai-empty-state">
            <div style={{ fontWeight: 700, color: "#475569" }}>No nodes match "{search}"</div>
          </div>
        ) : (
          visibleNodes.map((node, i) => (
            <TreeNode key={i} node={node} depth={0} isResearch={isResearch} />
          ))
        )}
      </div>

      {/* Legend */}
      <div style={{
        display: "flex", flexWrap: "wrap", gap: "6px", padding: "6px 8px",
        borderRadius: "6px", background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.05)"
      }}>
        {[["🎯","Root"],["📊","Assessment"],["⚡","Action"],["🔀","Alternative"],["❓","Uncertainty"]].map(([icon, label]) => (
          <span key={label} style={{ display: "flex", alignItems: "center", gap: "3px", fontSize: "0.5rem", color: "#475569" }}>
            <span>{icon}</span><span>{label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
