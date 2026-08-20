"use client";
import { useEffect, useRef, useState } from "react";
import "leaflet/dist/leaflet.css";

// ── Bearing helper (pure math, no deps) ─────────────────────────────────────
function getBearing(from, to) {
  const φ1 = from[0] * Math.PI / 180;
  const φ2 = to[0]  * Math.PI / 180;
  const Δλ = (to[1] - from[1]) * Math.PI / 180;
  const y  = Math.sin(Δλ) * Math.cos(φ2);
  const x  = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
  return ((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360;
}

export default function MapView({
  nodes = [],
  edges = [],
  agents = [],
  coordinates = {},
  nodeNames = {},
  simulationTime = 0,
  centerLat = 37.7749,
  centerLon = -122.4194,
  onDesignateShelter,
  selectedAgentId,
  onDispatchAgent,
  onToggleBlockage,
  onRequestAirdrop,
  onRefreshState,
  isSelectingRegion = false,
  span = 0.06,
  latSpan = 0.06,
  lngSpan = 0.06,
  onChangeRegion,
  isDeploying = false,
  onMapClick,
  deploymentMarkers = { havens: [], hospitals: [], scouts: [], rescues: [] },
  activeDisasterType = "FLOOD",
  forecastHorizon = 0,
  forecasts = {}
}) {
  const mapRef    = useRef(null);
  const leafletMap = useRef(null);
  const [isLayersPanelOpen, setIsLayersPanelOpen] = useState(true);

  const [showBlockedRoads,  setShowBlockedRoads]  = useState(true);
  const [showBlindspots,    setShowBlindspots]    = useState(true);
  const [showActiveRoutes,  setShowActiveRoutes]  = useState(true);
  const [showThreatZones,   setShowThreatZones]   = useState(true);
  const [zoomLevel,         setZoomLevel]         = useState(14);

  const layersRef = useRef({
    nodes: null, edges: null, agents: null, deploymentLayer: null,
    blockedEndMarkers: null   // ⊗ markers layer
  });

  // ── Persistent marker registries ────────────────────────────────────────────
  const agentMarkersRef  = useRef(new Map()); // id  → { marker, routeLayers[], lastSeen }
  const deployMarkersRef = useRef(new Map()); // key → L.Marker

  useEffect(() => {
    window.isDeployingMapMode = isDeploying;
    window.onMapClickCb = onMapClick;

    // Dynamically change cursor state to a high-visibility target crosshair on deploy mode
    if (leafletMap.current) {
      const container = leafletMap.current.getContainer();
      if (isDeploying) {
        container.classList.add("deploy-aim-mode");
      } else {
        container.classList.remove("deploy-aim-mode");
      }
    }
  }, [isDeploying, onMapClick]);

  useEffect(() => {
    window.onDesignateShelter = (nodeId, nodeType) => { if (onDesignateShelter) onDesignateShelter(nodeId, nodeType); };
    window.onDispatchAgent    = (nodeId) =>            { if (onDispatchAgent)    onDispatchAgent(nodeId); };
    window.onToggleBlockage   = (source, target) =>    { if (onToggleBlockage)   onToggleBlockage(source, target); };
    window.onRequestAirdrop   = (nodeId) =>            { if (onRequestAirdrop)   onRequestAirdrop(nodeId); };
  }, [onDesignateShelter, onDispatchAgent, onToggleBlockage, onRequestAirdrop]);

  // ── Map initialisation (runs once) ─────────────────────────────────────────
  useEffect(() => {
    const L = require("leaflet");
    require("leaflet-rotatedmarker");

    if (!leafletMap.current) {
      const map = L.map(mapRef.current, {
        zoomControl: false,
        attributionControl: false,
        preferCanvas: true,
        zoomAnimation: true,
        fadeAnimation: true,
        markerZoomAnimation: true
      }).setView([centerLat, centerLon], 14);

      L.control.zoom({ position: "bottomright" }).addTo(map);

      // ── Google Maps Street Tiles ──
      // Uses the standard Google Maps tile CDN (mt0–mt3).
      // Employs a URL-encoded apistyle query parameter to hide Point of Interest (POI) types:
      // s.t:33 -> poi.business (supermarkets, hotels)
      // s.t:38 -> poi.place_of_worship (churches, temples)
      // s.t:2  -> general POIs
      // p.v:off -> visibility off
      const googleStyleParams = [
        "s.t:33|p.v:off",  // Hide POI businesses (hotels, supermarkets)
        "s.t:38|p.v:off",  // Hide POI places of worship (churches, temples)
        "s.t:2|p.v:off"    // Hide general POIs
      ].join(",");

      L.tileLayer(`https://{s}.google.com/vt/lyrs=m&x={x}&y={y}&z={z}&apistyle=${encodeURIComponent(googleStyleParams)}`, {
        maxZoom: 20,
        subdomains: ["mt0", "mt1", "mt2", "mt3"],
        attribution: '© Google Maps',
        updateWhenIdle: false,
        keepBuffer: 12,
        updateWhenZooming: true
      }).addTo(map);

      // ── Named panes for correct z-ordering ──────────────────────────────────
      map.createPane("routePane").style.zIndex   = "350";
      map.createPane("hazardPane").style.zIndex  = "360";
      map.createPane("agentPane").style.zIndex   = "450";

      leafletMap.current = map;

      map.on("click", (e) => {
        if (window.onMapClickCb) window.onMapClickCb(e.latlng.lat, e.latlng.lng);
      });

      map.on("zoomend", () => {
        const z = map.getZoom();
        setZoomLevel(z);
        // Show/hide permanent tooltips based on zoom
        agentMarkersRef.current.forEach(({ marker }) => {
          if (marker.getTooltip) {
            if (z >= 13) { marker.openTooltip && marker.openTooltip(); }
            else         { marker.closeTooltip && marker.closeTooltip(); }
          }
        });
      });

      layersRef.current.edges              = L.layerGroup().addTo(map);
      layersRef.current.blockedEndMarkers  = L.layerGroup().addTo(map);
      layersRef.current.nodes              = L.layerGroup().addTo(map);
      layersRef.current.agents             = L.layerGroup().addTo(map);
      layersRef.current.deploymentLayer    = L.layerGroup().addTo(map);

      // ── Expose flyTo for sidebar → map linking ───────────────────────────────
      window.panToAgent = (id) => {
        const entry = agentMarkersRef.current.get(id);
        if (entry && leafletMap.current) {
          leafletMap.current.flyTo(entry.marker.getLatLng(), 16, { duration: 1.2, easeLinearity: 0.25 });
        }
      };
    }

    const map = leafletMap.current;

    // ── Task 3: Dynamically inject custom SVG pattern definitions into the Map root ──
    if (map && !map._hasCustomPatterns) {
      const svgElement = map.getContainer().querySelector("svg");
      if (svgElement) {
        // Create defs element if it does not exist
        let defs = svgElement.querySelector("defs");
        if (!defs) {
          defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
          svgElement.insertBefore(defs, svgElement.firstChild);
        }
        
        // Add flood-hatch pattern definition
        const floodPattern = document.createElementNS("http://www.w3.org/2000/svg", "pattern");
        floodPattern.setAttribute("id", "flood-hatch");
        floodPattern.setAttribute("width", "12");
        floodPattern.setAttribute("height", "12");
        floodPattern.setAttribute("patternUnits", "userSpaceOnUse");
        floodPattern.setAttribute("patternTransform", "rotate(45)");
        
        const floodLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
        floodLine.setAttribute("x1", "0");
        floodLine.setAttribute("y1", "0");
        floodLine.setAttribute("x2", "0");
        floodLine.setAttribute("y2", "12");
        floodLine.setAttribute("stroke", "#3b82f6");
        floodLine.setAttribute("stroke-width", "3");
        floodLine.setAttribute("opacity", "0.4");
        
        floodPattern.appendChild(floodLine);
        defs.appendChild(floodPattern);

        // Add danger-hatch pattern definition
        const dangerPattern = document.createElementNS("http://www.w3.org/2000/svg", "pattern");
        dangerPattern.setAttribute("id", "danger-hatch");
        dangerPattern.setAttribute("width", "10");
        dangerPattern.setAttribute("height", "10");
        dangerPattern.setAttribute("patternUnits", "userSpaceOnUse");
        dangerPattern.setAttribute("patternTransform", "rotate(135)");
        
        const dangerLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
        dangerLine.setAttribute("x1", "0");
        dangerLine.setAttribute("y1", "0");
        dangerLine.setAttribute("x2", "0");
        dangerLine.setAttribute("y2", "10");
        dangerLine.setAttribute("stroke", "#ef4444");
        dangerLine.setAttribute("stroke-width", "4");
        dangerLine.setAttribute("opacity", "0.35");
        
        dangerPattern.appendChild(dangerLine);
        defs.appendChild(dangerPattern);

        map._hasCustomPatterns = true;
      }
    }

    if (nodes.length > 0 && simulationTime === 0 && !map._hasAutoZoomed) {
      const bounds = L.latLngBounds(nodes.map(n => [n.lat, n.lon]));
      map.fitBounds(bounds, { padding: [60, 60], maxZoom: 14 });
      map._hasAutoZoomed = true;
    }

    const { nodes: nodeLayer, edges: edgeLayer, agents: agentLayer, deploymentLayer, blockedEndMarkers } = layersRef.current;

    nodeLayer.clearLayers();
    edgeLayer.clearLayers();
    blockedEndMarkers.clearLayers();

    if (isSelectingRegion) return;

    const left   = centerLon - lngSpan;
    const bottom = centerLat - latSpan;
    const right  = centerLon + lngSpan;
    const top    = centerLat + latSpan;

    const borderBounds = [[bottom, left], [top, right]];
    const boundaryRect = L.rectangle(borderBounds, {
      color: "#3b82f6", weight: 2, dashArray: "5, 5",
      fill: false, interactive: false
    });
    deploymentLayer.addLayer(boundaryRect);

    const coordMap = { ...coordinates };
    nodes.forEach(n => { coordMap[n.id] = [n.lat, n.lon]; });

    const lineScale = Math.pow(1.5, zoomLevel - 14);
    const iconScale = Math.pow(1.15, zoomLevel - 14);

    // ── Draw Edges ─────────────────────────────────────────────────────────────
    edges.forEach(edge => {
      // If showBlockedRoads is checked, display blocked roads. If not checked, we hide blocked roads
      if (!showBlockedRoads && edge.blocked) return;

      const p1 = coordMap[edge.source];
      const p2 = coordMap[edge.target];
      if (!p1 || !p2) return;

        const inside1 = p1[0] >= bottom && p1[0] <= top && p1[1] >= left && p1[1] <= right;
        const inside2 = p2[0] >= bottom && p2[0] <= top && p2[1] >= left && p2[1] <= right;
        if (!inside1 && !inside2) return;

        const geom = edge.geometry && edge.geometry.length >= 2 ? edge.geometry : [p1, p2];

        // Get endpoints risk properties to dynamically highlight high threat roads in red
        let uNode = nodes.find(n => n.id === edge.source);
        let vNode = nodes.find(n => n.id === edge.target);
        
        // Dynamic time-travel forecast override logic
        if (forecastHorizon > 0 && forecasts && forecasts[forecastHorizon]) {
          const fc = forecasts[forecastHorizon];
          if (uNode && fc[edge.source]) {
            uNode = { ...uNode, p_danger: fc[edge.source].p_danger ?? uNode.p_danger, status: fc[edge.source].status ?? uNode.status, water_level: fc[edge.source].water_level ?? uNode.water_level };
          }
          if (vNode && fc[edge.target]) {
            vNode = { ...vNode, p_danger: fc[edge.target].p_danger ?? vNode.p_danger, status: fc[edge.target].status ?? vNode.status, water_level: fc[edge.target].water_level ?? vNode.water_level };
          }
        }
        
        const disasterType = (activeDisasterType || "FLOOD").toUpperCase();
        let isHighRisk = false;
        
        if (uNode && vNode) {
          // A road is a main road if it is a major highway/expressway/freeway/flyover or major marine arterial link (e.g. Bandra-Worli Sea Link Flyover)
          // We also use speed_factor >= 1.3 to capture unnamed highways or major arterials from OSM data.
          // We exclude small local street links or local connector roads from isMainRoad so they can be blocked.
          const nameLower = (edge.name || "").toLowerCase();
          const isMainRoad = edge.is_bridge || (edge.speed_factor && edge.speed_factor >= 1.3) || (edge.name && (
            nameLower.includes("freeway") || 
            nameLower.includes("expressway") ||
            nameLower.includes("highway") ||
            nameLower.includes("sea link") ||
            nameLower.includes("sealink") ||
            nameLower.includes("flyover") ||
            nameLower.includes("bandra-worli") ||
            (nameLower.includes("bypass") && !nameLower.includes("local"))
          ));

          if (!isMainRoad) {
            if (disasterType === "FLOOD") {
              // High risk: immediately next to a water body (river or coast) or drainages within 180 meters
              const uNearWater = (uNode.dist_to_water < 180.0 && uNode.dist_to_water > 0.1) || (uNode.dist_to_coast < 180.0 && uNode.dist_to_coast > 0.1);
              const vNearWater = (vNode.dist_to_water < 180.0 && vNode.dist_to_water > 0.1) || (vNode.dist_to_coast < 180.0 && vNode.dist_to_coast > 0.1);
              if (uNearWater || vNearWater) isHighRisk = true;
            } else if (disasterType === "EARTHQUAKE") {
              // High risk: adjacent to tall building collapse zones, or inside high-density residential structures (slums / narrow street grids)
              const isDenseSlumGrid = uNode.population > 200 || vNode.population > 200;
              const nearTallBuilding = uNode.is_tall_building_zone || vNode.is_tall_building_zone;
              if (nearTallBuilding || isDenseSlumGrid) isHighRisk = true;
            } else if (disasterType === "CYCLONE") {
              // High risk: immediately adjacent to sea-shore within 220 meters, or high-exposure local paths
              const uNearCoast = uNode.dist_to_coast < 220.0 && uNode.dist_to_coast > 0.1;
              const vNearCoast = vNode.dist_to_coast < 220.0 && vNode.dist_to_coast > 0.1;
              if (uNearCoast || vNearCoast) isHighRisk = true;
            }
          }
        }

        let isBlocked = edge.blocked || isHighRisk;

        let color     = isBlocked ? "#ff3333" : (edge.cleared ? "#22c55e" : "#94a3b8");
        // Apply custom confidence overlays color tiering if available
        if (edge.confidence_color === "green") {
          color = "#22c55e"; // Known safe / clear
        } else if (edge.confidence_color === "yellow") {
          color = "#eab308"; // Partially known / unverified risk
        } else if (edge.confidence_color === "red") {
          color = "#ef4444"; // High risk / suspected blocked
        } else if (edge.confidence_color === "grey") {
          color = "#64748b"; // No observations / blindspot
        }
        
        let baseWeight = isBlocked ? 1.8       : (edge.cleared ? 2.5       : 2);
        if (isBlocked && edge.hvt) { color = "#ea580c"; baseWeight = 4.0; }

        const weight    = Math.max(0.5, baseWeight * lineScale);
        const dashArray = isBlocked ? "6,12" : null; // Dotted segments for suspected or verified blocked roads
        const opacity   = isBlocked ? 0.95  : (edge.cleared ? 0.75 : 0.65);

        // No continuous red casing overlay underneath the dashed line
        const poly = L.polyline(geom, { color, weight, opacity, dashArray, pane: "routePane" });

        if (isBlocked && edge.hvt && edge.hvt_priority > 200) {
          edgeLayer.addLayer(L.polyline(geom, { color: "#fbbf24", weight: weight + 5, opacity: 0.25, pane: "routePane" }));
        }

        if (edge.blocked) {
          let blockageType = "COMPROMISED";
          let actionLabel  = "Clear Road";
          const disaster   = (window.activeDisasterType || "FLOOD").toUpperCase();

          if (disaster === "EARTHQUAKE")     { blockageType = "⛔ STRUCTURAL RUBBLE";      actionLabel = "🛠️ Clear Rubble"; }
          else if (disaster === "CYCLONE")   { blockageType = "⛔ CYCLONE DEBRIS / TREES"; actionLabel = "🪓 Clear Debris";  }
          else                               { blockageType = "⛔ FLOOD SUBMERGED";         actionLabel = "🌊 Drain / Clear"; }

          const streetName = edge.name && edge.name !== "Unnamed Road" ? edge.name : null;
          const srcName    = nodeNames[edge.source] || edge.source;
          const tgtName    = nodeNames[edge.target] || edge.target;
          const roadLabel  = streetName
            ? `<b>${streetName}</b> <span style="color:#94a3b8;font-size:0.65rem">(${srcName} ↔ ${tgtName})</span>`
            : `${srcName} ↔ ${tgtName}`;

          const hvtPriority = edge.hvt_priority || 0;
          const hvtBadge    = edge.hvt
            ? `<div style="background:${hvtPriority > 200 ? '#dc2626' : '#ea580c'};color:#fff;padding:4px;border-radius:4px;font-size:0.65rem;font-weight:bold;margin-bottom:6px;text-align:center;box-shadow:0 0 6px rgba(234,88,12,0.7);">⚡ HIGH-VALUE TARGET &nbsp;·&nbsp; Priority: ${hvtPriority > 500 ? '🔴 Critical' : hvtPriority > 200 ? '🟠 High' : '🟡 Medium'}</div>`
            : "";

          poly.bindPopup(`
            <div style="font-family:monospace;font-size:0.75rem;min-width:200px">
              ${hvtBadge}
              <b>Road:</b> ${roadLabel}<br/>
              <b>Status:</b> <span style="color:#ef4444;font-weight:bold;">${blockageType}</span><br/>
              <button onclick="window.onToggleBlockage('${edge.source}', '${edge.target}')" style="cursor:pointer;background:#10b981;color:#fff;border:none;padding:5px;border-radius:4px;width:100%;margin-top:6px;font-weight:bold;">${actionLabel}</button>
            </div>
          `);

        }

        poly.on("click", (e) => {
          if (window.onMapClickCb) window.onMapClickCb(e.latlng.lat, e.latlng.lng);
        });

        edgeLayer.addLayer(poly);
      });

    // ── Draw Nodes ─────────────────────────────────────────────────────────────
    nodes.forEach(rawNode => {
      let node = { ...rawNode };
      
      // Dynamic time-travel forecast override logic for nodes
      if (forecastHorizon > 0 && forecasts && forecasts[forecastHorizon] && forecasts[forecastHorizon][node.id]) {
        const fc = forecasts[forecastHorizon][node.id];
        node.p_danger = fc.p_danger ?? node.p_danger;
        node.status = fc.status ?? node.status;
        node.water_level = fc.water_level ?? node.water_level;
      }

      // ── Task 3: Render custom SVG diagonal pattern hatch layers for flooded / danger zones ──
      const insideNode = node.lat >= bottom && node.lat <= top && node.lon >= left && node.lon <= right;
      if (!insideNode) return;

      const coord = [node.lat, node.lon];

      if (node.node_type === "POPULATION_ZONE" && showThreatZones) {
        // High threat zone (e.g. danger > 75%) or Evacuation block
        if (node.p_danger > 0.75) {
          const circleHatch = L.circle(coord, {
            radius: 180, // 180 meters radius
            stroke: true,
            color: "#ef4444",
            weight: 1.5,
            fillColor: "#ef4444",
            fillOpacity: 0.12,
            interactive: false,
            pane: "hazardPane"
          });
          nodeLayer.addLayer(circleHatch);
        } else if (node.status === "FLOODED" || node.p_danger > 0.40) {
          // Moderate threat or flooded area
          const circleHatch = L.circle(coord, {
            radius: 150,
            stroke: true,
            color: "#3b82f6",
            weight: 1.5,
            fillColor: "#3b82f6",
            fillOpacity: 0.1,
            interactive: false,
            pane: "hazardPane"
          });
          nodeLayer.addLayer(circleHatch);
        }

        // Unverified Blindspots scan radius (if showBlindspots is checked and certainty is low)
        if (showBlindspots && node.p_state_correct < 0.65) {
          const blindspotOverlay = L.circle(coord, {
            radius: 200,
            color: "#6b7280", // Gray border
            weight: 1.5,
            dashArray: "4,4",
            fillColor: "#f97316", // High visibility orange warning fill
            fillOpacity: 0.14, // Solid, semi-transparent overlay
            interactive: false,
            pane: "hazardPane"
          });
          nodeLayer.addLayer(blindspotOverlay);
        }
      }

      const isSafeZone = (node.node_type === "HOSPITAL" || node.node_type === "SHELTER");
      if (!isSafeZone) return;

      const isCompromised = node.status === "COMPROMISED" || node.status === "FLOODED";

      let color   = "#10b981";
      let svgIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:100%;height:100%;"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`;

      if (node.node_type === "HOSPITAL") {
        color   = "#3b82f6";
        svgIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" style="width:100%;height:100%;"><path d="M22 20a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2z"/><path d="M12 8v8"/><path d="M8 12h8"/></svg>`;
      } else if (node.node_type === "SHELTER") {
        color   = "#f59e0b";
        svgIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:100%;height:100%;"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`;
      }

      const scaleGently  = Math.pow(1.08, zoomLevel - 14);
      const size         = Math.max(12, Math.round(16 * scaleGently));
      const borderRadius = Math.max(3,  Math.round(4  * scaleGently));
      const padding      = Math.max(2,  Math.round(3  * scaleGently));

      const iconHtml   = `<div style="background:${color};border-radius:${borderRadius}px;padding:${padding}px;border:1.5px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,0.35);display:flex;align-items:center;justify-content:center;width:${size}px;height:${size}px;box-sizing:border-box;">${zoomLevel >= 13 ? svgIcon : ""}</div>`;
      const customIcon = L.divIcon({ html: iconHtml, className: "", iconSize: [size, size], iconAnchor: [size/2, size/2] });
      const marker     = L.marker(coord, { icon: customIcon });

      let actions = "";
      if (node.node_type !== "HOSPITAL" && node.node_type !== "SHELTER") {
        actions = `
          <div style="margin-top:10px; display:flex; gap:6px;">
            <button onclick="window.onDesignateShelter('${node.id}', 'SHELTER')" style="flex:1; background:#3b82f6; color:#fff; border:none; padding:4px; border-radius:4px;">🛡️ Shelter</button>
            <button onclick="window.onDesignateShelter('${node.id}', 'HOSPITAL')" style="flex:1; background:#ec4899; color:#fff; border:none; padding:4px; border-radius:4px;">🏥 Hospital</button>
          </div>
        `;
      } else {
        actions = `<button onclick="window.onRequestAirdrop('${node.id}')" style="width:100%; background:#f59e0b; color:#fff; border:none; padding:4px; border-radius:4px; margin-top:8px;">🛩️ Supply Drop</button>`;
      }

      marker.bindPopup(`
        <div style="font-family:monospace;font-size:0.75rem;min-width:180px">
          <b>${node.id}</b><br/>
          Type: ${node.node_type}<br/>
          Status: ${isCompromised ? '⛔ DANGER' : '✓ CLEAR'}<br/>
          ${node.population > 0 ? `Stranded: ${node.population}<br/>` : ''}
          ${actions}
        </div>
      `);

      marker.on("click", (e) => {
        if (window.onMapClickCb) window.onMapClickCb(e.latlng.lat, e.latlng.lng);
      });

      nodeLayer.addLayer(marker);
    });

    // ── Agent Icon Builder (Phase A2 + A3) ──────────────────────────────────────
    const buildAgentIconHtml = (agent, zoom) => {
      // SVG icons per vehicle type
      const svgHeli   = `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:100%;height:100%;"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>`;
      const svgBoat   = `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:100%;height:100%;"><path d="M2 12h20"/><path d="M4 12v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/><path d="M12 12V4L8 8"/></svg>`;
      const svgScout  = `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:100%;height:100%;"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>`;
      const svgRescue = `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:100%;height:100%;"><path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a4 4 0 0 0-1.17-2.83l-1.5-1.52H14v9h1"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/></svg>`;

      // NAPSG-aligned unit type colors
      let bgColor = "#db2777"; // default rescue pink
      let svgIcon = svgRescue;
      if (agent.vehicle_type === "HELICOPTER")                                        { bgColor = "#a855f7"; svgIcon = svgHeli;   }
      else if (agent.vehicle_type === "ZODIAC_BOAT" || agent.vehicle_type === "ZODIAC") { bgColor = "#0288D1"; svgIcon = svgBoat;   }
      else if (agent.agent_type  === "SCOUT")                                         { bgColor = "#1d4ed8"; svgIcon = svgScout;  }
      else if (agent.vehicle_type === "HIGH_WATER_TRUCK")                             { bgColor = "#E65100"; svgIcon = svgRescue; }

      // Status dot color (IBM Carbon tokens)
      const statusDotColor = {
        "AVAILABLE": "#42be65",
        "IDLE":      "#42be65",
        "MOVING":    "#4589ff",
        "OBSERVING": "#f1c21b",
        "RESCUING":  "#ff8389",
        "RETURNING": "#00bcd4",
        "STANDBY":   "#8d8d8d",
      }[agent.status] || "#8d8d8d";

      const isEmergency = agent.status === "EMERGENCY";

      const scaleAgent = Math.pow(1.08, zoom - 14);
      const size       = Math.max(18, Math.round(24 * scaleAgent));  // larger base (was 18)
      const padding    = Math.max(2,  Math.round(3  * scaleAgent));
      const dotSize    = Math.max(5, Math.round(7 * scaleAgent));

      return {
        html: `
          <div style="position:relative;width:${size}px;height:${size}px;box-sizing:border-box;will-change:transform;transition:transform 0.8s ease;${isEmergency ? 'animation:sentinel-blink 0.5s step-end infinite;' : ''}">
            <div style="position:relative;background:${bgColor};border-radius:6px;padding:${padding}px;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,0.6);border:2px solid rgba(255,255,255,0.8);width:${size}px;height:${size}px;z-index:10;box-sizing:border-box;">
              ${svgIcon}
            </div>
            <div style="position:absolute;bottom:-1px;right:-1px;width:${dotSize}px;height:${dotSize}px;border-radius:50%;background:${statusDotColor};border:1.5px solid #0f172a;z-index:20;box-shadow:0 0 4px ${statusDotColor};"></div>
          </div>
        `,
        size,
        color: bgColor
      };
    };

    // ── Route Builder (Phase A4 + A5 / Fix 2: Pure CSS active route) ────────────
    const buildRouteLayers = (agent, coordMap) => {
      const layers = [];
      if (!agent.full_planned_route || agent.full_planned_route.length < 2) return layers;

      const fullPlanned = agent.full_planned_route;
      const currentIdx  = fullPlanned.indexOf(agent.current_node);
      if (currentIdx === -1) return layers;

      // Completed segment — faded green (0.55 opacity, industry standard)
      const completedCoords = fullPlanned.slice(0, currentIdx + 1).map(nid => coordMap[nid]).filter(Boolean);
      if (completedCoords.length >= 2) {
        // Casing shadow
        layers.push(L.polyline(completedCoords, { color: "rgba(0,0,0,0.35)", weight: 7, opacity: 1, interactive: false, pane: "routePane" }));
        // Main completed line — faded green
        layers.push(L.polyline(completedCoords, { color: "#388E3C", weight: 4, opacity: 0.55, lineCap: "round", lineJoin: "round", pane: "routePane" }));
      }

      // Remaining / planned segment — amber active flow (Fix 2: pure CSS route)
      const remainingCoords = fullPlanned.slice(currentIdx).map(nid => coordMap[nid]).filter(Boolean);
      if (remainingCoords.length >= 2) {
        // Casing shadow
        layers.push(L.polyline(remainingCoords, { color: "rgba(0,0,0,0.35)", weight: 9, opacity: 1, interactive: false, pane: "routePane" }));
        // Glow halo
        layers.push(L.polyline(remainingCoords, { color: "#FFC107", weight: 10, opacity: 0.15, pane: "routePane" }));

        // ── Fix 2: Highly optimized hardware-accelerated pure CSS route polyline ──
        const activeRoute = L.polyline(remainingCoords, {
          color: "#FFC107",
          weight: 4,
          opacity: 0.92,
          className: "sentinel-active-route",
          lineCap: "round",
          lineJoin: "round",
          pane: "routePane"
        });
        layers.push(activeRoute);

        // Waypoint dots along remaining route (Phase A — industry standard)
        if (zoomLevel >= 14) {
          remainingCoords.forEach((coord, i) => {
            if (i === 0 || i === remainingCoords.length - 1) return; // skip endpoints
            const wpDot = L.circleMarker(coord, {
              radius: 3,
              color: "#fff",
              weight: 1.5,
              fillColor: "#FFC107",
              fillOpacity: 0.9,
              interactive: false,
              pane: "routePane"
            });
            layers.push(wpDot);
          });
        }
      }

      return layers;
    };

    // ── Build position map with jitter for co-located units (Phase A7) ─────────
    const nodeOccupancy = {};   // node_id → count of agents at that node so far
    const jitteredCoords = {}; // agent.id → [lat, lon] (possibly offset)

    agents.forEach(agent => {
      const base = coordMap[agent.current_node];
      if (!base) return;

      const key   = agent.current_node;
      const count = nodeOccupancy[key] || 0;
      nodeOccupancy[key] = count + 1;

      if (count === 0) {
        jitteredCoords[agent.id] = base;
      } else {
        // 3×3 spiral offset pattern (5m ≈ 0.000045 deg latitude)
        const col = count % 3;
        const row = Math.floor(count / 3);
        const offsetLat = (row - 1) * 0.000038;
        const offsetLon = (col - 1) * 0.000048;
        jitteredCoords[agent.id] = [base[0] + offsetLat, base[1] + offsetLon];
      }
    });

    // ── Remove stale agents ─────────────────────────────────────────────────────
    const currentAgentIds = new Set(agents.map(a => a.id));
    for (const [id, entry] of agentMarkersRef.current.entries()) {
      if (!currentAgentIds.has(id)) {
        entry.routeLayers.forEach(l => agentLayer.removeLayer(l));
        agentLayer.removeLayer(entry.marker);
        agentMarkersRef.current.delete(id);
      }
    }

    // ── Fix 3: Custom requestAnimationFrame Smooth sliding marker animation ──
    const slideMarker = (marker, fromLatLng, toLatLng, durationMs = 850) => {
      if (!fromLatLng || !toLatLng) return;
      const start = performance.now();
      
      const step = (now) => {
        const elapsed = now - start;
        const t = Math.min(elapsed / durationMs, 1);
        // Cubic Easing for premium feel
        const ease = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
        
        const nextLat = fromLatLng[0] + (toLatLng[0] - fromLatLng[0]) * ease;
        const nextLon = fromLatLng[1] + (toLatLng[1] - fromLatLng[1]) * ease;
        
        marker.setLatLng([nextLat, nextLon]);
        
        if (t < 1) {
          requestAnimationFrame(step);
        }
      };
      requestAnimationFrame(step);
    };

    // ── Update or create agent markers ─────────────────────────────────────────
    agents.forEach(agent => {
      const coord = jitteredCoords[agent.id];
      if (!coord) return;

      const { html, size } = buildAgentIconHtml(agent, zoomLevel);
      const customIcon     = L.divIcon({ html, className: "", iconSize: [size, size], iconAnchor: [size/2, size/2] });

      const popupHtml = `
        <div style="font-family:monospace;font-size:0.75rem;">
          <b>Agent: ${agent.id}</b><br/>
          Type: ${agent.agent_type}<br/>
          Status: ${agent.status}<br/>
          ${agent.survivors_onboard > 0 ? `Survivors: ${agent.survivors_onboard}<br/>` : ''}
        </div>
      `;

      // Compute bearing to next waypoint for rotation
      let bearingDeg = 0;
      if (agent.full_planned_route && agent.full_planned_route.length >= 2) {
        const idx  = agent.full_planned_route.indexOf(agent.current_node);
        const next = agent.full_planned_route[idx + 1];
        if (next && coordMap[next]) {
          bearingDeg = getBearing(coord, coordMap[next]);
        }
      }

      if (agentMarkersRef.current.has(agent.id)) {
        // ── Update existing marker (no DOM destroy) ───────────────────────────
        const entry = agentMarkersRef.current.get(agent.id);

        // Smooth position slide using requestAnimationFrame (Fix 3)
        const prevLatLng = entry.prevLatLng || entry.marker.getLatLng();
        const fromPos = [prevLatLng.lat || prevLatLng[0], prevLatLng.lng || prevLatLng[1]];
        
        // Only animate if the coordinates changed significantly
        if (Math.abs(fromPos[0] - coord[0]) > 0.00001 || Math.abs(fromPos[1] - coord[1]) > 0.00001) {
          slideMarker(entry.marker, fromPos, coord, 850);
        } else {
          entry.marker.setLatLng(coord);
        }
        
        entry.prevLatLng = coord; // Update stored coords for next render pass
        entry.marker.setIcon(customIcon);
        entry.marker.setPopupContent(popupHtml);

        // Apply heading rotation (leaflet-rotatedmarker)
        if (agent.status === "MOVING" && entry.marker.setRotationAngle) {
          entry.marker.setRotationAngle(bearingDeg);
          entry.marker.setRotationOrigin("center center");
        } else if (entry.marker.setRotationAngle) {
          entry.marker.setRotationAngle(0);
        }

        // Update tooltip to show current status
        if (entry.marker.getTooltip()) {
          entry.marker.setTooltipContent(`<span style="color:#f1c21b">${agent.id}</span>`);
        }

        // Stale data desaturation (> 90s since last update)
        entry.lastSeen = Date.now();
        const el = entry.marker.getElement && entry.marker.getElement();
        if (el) el.style.filter = "";

        // Refresh route polylines
        entry.routeLayers.forEach(l => agentLayer.removeLayer(l));
        const newRouteLayers = buildRouteLayers(agent, coordMap);
        newRouteLayers.forEach(l => agentLayer.addLayer(l));
        entry.routeLayers = newRouteLayers;

      } else {
        // ── Create new marker ─────────────────────────────────────────────────
        const routeLayers = buildRouteLayers(agent, coordMap);
        routeLayers.forEach(l => agentLayer.addLayer(l));

        const marker = L.marker(coord, { icon: customIcon, draggable: true, pane: "agentPane" });

        // Apply rotation immediately on creation
        if (agent.status === "MOVING" && marker.setRotationAngle) {
          marker.setRotationAngle(bearingDeg);
          marker.setRotationOrigin("center center");
        }

        marker.on("dragend", (e) => {
          const newLat = e.target.getLatLng().lat;
          const newLng = e.target.getLatLng().lng;
          if (window.onUnitMoveCb) window.onUnitMoveCb(agent.id, "agent", newLat, newLng);
        });

        // ── Permanent callsign tooltip (Phase A1) ─────────────────────────────
        marker.bindTooltip(
          `<span style="color:#f1c21b">${agent.id}</span>`,
          { permanent: zoomLevel >= 13, direction: "top", className: "sentinel-unit-tooltip" }
        );

        // ── Map → Sidebar linking: fire callback on click (Phase B4) ─────────
        marker.on("click", (e) => {
          if (window.onAgentSelectCb) window.onAgentSelectCb(agent.id);
          if (window.onMapClickCb)    window.onMapClickCb(e.latlng.lat, e.latlng.lng);
        });

        marker.bindPopup(popupHtml);
        agentLayer.addLayer(marker);

        agentMarkersRef.current.set(agent.id, { marker, routeLayers, lastSeen: Date.now(), prevLatLng: coord });
      }
    });

    // ── Stale marker desaturation pass ─────────────────────────────────────────
    const now = Date.now();
    agentMarkersRef.current.forEach((entry) => {
      const el = entry.marker.getElement && entry.marker.getElement();
      if (!el) return;
      const age = now - (entry.lastSeen || now);
      if (age > 90000) {
        el.style.filter = "grayscale(80%) opacity(0.5)";
      }
    });

    // ── Deployment preview markers ──────────────────────────────────────────────
    const buildDeployHtml = (color, svgIconStr, scale) => {
      const size = Math.round(28 * scale);
      return {
        html: `<div style="background:${color};border-radius:${8*scale}px;padding:${4*scale}px;border:${2*scale}px dashed #fff;opacity:0.9;display:flex;align-items:center;justify-content:center;width:${size}px;height:${size}px;will-change:transform;transition:transform 0.6s ease;">${svgIconStr}</div>`,
        size
      };
    };

    const svgShelter   = `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`;
    const svgHospital  = `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;"><path d="M22 20a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2z"/><path d="M12 8v8"/><path d="M8 12h8"/></svg>`;
    const svgScoutIcon  = `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>`;
    const svgRescueIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;"><path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a4 4 0 0 0-1.17-2.83l-1.5-1.52H14v9h1"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/></svg>`;

    const deployGroups = [
      { list: deploymentMarkers?.havens    || [], color: "#6366f1", title: "Safehouse", svg: svgShelter,    prefix: "haven"    },
      { list: deploymentMarkers?.hospitals || [], color: "#3b82f6", title: "Hospital",  svg: svgHospital,   prefix: "hospital" },
      { list: deploymentMarkers?.scouts    || [], color: "#22d3ee", title: "Scout",     svg: svgScoutIcon,  prefix: "scout"    },
      { list: deploymentMarkers?.rescues   || [], color: "#f59e0b", title: "Rescue",    svg: svgRescueIcon, prefix: "rescue"   },
    ];

    const wantedDeployKeys = new Set();
    deployGroups.forEach(({ list, color, title, svg, prefix }) => {
      list.forEach((m, idx) => {
        const key = `${prefix}_${idx}`;
        wantedDeployKeys.add(key);

        const { html, size } = buildDeployHtml(color, svg, iconScale);
        const icon = L.divIcon({ html, className: "", iconSize: [size, size], iconAnchor: [size/2, size/2] });

        if (deployMarkersRef.current.has(key)) {
          const dm = deployMarkersRef.current.get(key);
          dm.setLatLng([m.lat, m.lon]);
          dm.setIcon(icon);
        } else {
          const dm = L.marker([m.lat, m.lon], { icon });
          dm.bindTooltip(`${title} (Pending Drop)`, { permanent: true, direction: "top" });
          deploymentLayer.addLayer(dm);
          deployMarkersRef.current.set(key, dm);
        }
      });
    });

    for (const [key, dm] of deployMarkersRef.current.entries()) {
      if (!wantedDeployKeys.has(key)) {
        deploymentLayer.removeLayer(dm);
        deployMarkersRef.current.delete(key);
      }
    }

  }, [nodes, edges, agents, coordinates, centerLat, centerLon, showBlockedRoads, showBlindspots, showActiveRoutes, isSelectingRegion, deploymentMarkers, zoomLevel]);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <style>{`
        /* ── Keyframes ─────────────────────────────────────────────────────── */
        @keyframes map-pulse {
          0%   { transform: scale(1);    opacity: 0.8; }
          50%  { transform: scale(1.45); opacity: 0.3; }
          100% { transform: scale(1);    opacity: 0.8; }
        }
        @keyframes sentinel-blink {
          50% { opacity: 0; }
        }

        /* Leaflet marker base — let inner div drive transitions */
        .leaflet-marker-icon { transition: none !important; }

        /* ── Unit callsign tooltip (Phase A1 / C2) ─────────────────────────── */
        .sentinel-unit-tooltip {
          background: rgba(8, 12, 28, 0.92) !important;
          border: 1px solid rgba(255,255,255,0.18) !important;
          border-radius: 4px !important;
          color: #f4f4f4 !important;
          font-family: 'IBM Plex Mono', 'Roboto Mono', monospace !important;
          font-size: 10px !important;
          font-weight: 600 !important;
          padding: 2px 7px !important;
          white-space: nowrap !important;
          box-shadow: 0 2px 10px rgba(0,0,0,0.7) !important;
          text-shadow: 0 0 4px rgba(0,0,0,0.95) !important;
          backdrop-filter: blur(4px) !important;
        }
        .sentinel-unit-tooltip::before { display: none !important; }

        /* High-visibility cursor for deployment target mode */
        .deploy-aim-mode, .deploy-aim-mode * {
          cursor: cell !important; /* fallback high-contrast crosshair targeting cursor style */
        }
      `}</style>
      <div ref={mapRef} className="map-container" style={{ width: "100%", height: "100%" }} />

      <div style={{ pointerEvents: "none" }}>
        {/* Tactical Map Layers Toggle */}
        <div style={{
          position: "absolute", top: "16px", left: "50%", transform: "translateX(-50%)",
          zIndex: 1000, background: "rgba(10, 15, 30, 0.65)", backdropFilter: "blur(12px)",
          border: "1px solid rgba(255, 255, 255, 0.1)", borderRadius: "10px", padding: "12px",
          fontFamily: "'Inter', sans-serif", color: "#f8fafc", pointerEvents: "auto",
          boxShadow: "0 8px 32px rgba(0,0,0,0.5)", display: "flex", flexDirection: "column", gap: "8px",
          minWidth: isLayersPanelOpen ? "200px" : "auto", transition: "all 0.3s ease"
        }}>
          <div onClick={() => setIsLayersPanelOpen(!isLayersPanelOpen)} style={{ fontSize: "0.8rem", fontWeight: "bold", borderBottom: isLayersPanelOpen ? "1px solid rgba(255,255,255,0.15)" : "none", paddingBottom: isLayersPanelOpen ? "6px" : "0", color: "#f1f5f9", display: "flex", justifyContent: "space-between", cursor: "pointer", textTransform: "uppercase", letterSpacing: "1px" }}>
            <span>TACTICAL MAP LAYERS</span>
            <span>{isLayersPanelOpen ? "−" : "+"}</span>
          </div>

          {isLayersPanelOpen && (
            <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginTop: "4px" }}>
              <label style={{ fontSize: "0.8rem", display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", color: "#e2e8f0" }}>
                <input type="checkbox" checked={showBlockedRoads} onChange={e => setShowBlockedRoads(e.target.checked)} style={{accentColor: "#3b82f6"}} />
                Blocked Roads
              </label>
              <label style={{ fontSize: "0.8rem", display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", color: "#e2e8f0" }}>
                <input type="checkbox" checked={showThreatZones} onChange={e => setShowThreatZones(e.target.checked)} style={{accentColor: "#3b82f6"}} />
                Threat Zones
              </label>
              <label style={{ fontSize: "0.8rem", display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", color: "#e2e8f0" }}>
                <input type="checkbox" checked={showBlindspots} onChange={e => setShowBlindspots(e.target.checked)} style={{accentColor: "#3b82f6"}} />
                Unverified Zones
              </label>
              <label style={{ fontSize: "0.8rem", display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", color: "#e2e8f0" }}>
                <input type="checkbox" checked={showActiveRoutes} onChange={e => setShowActiveRoutes(e.target.checked)} style={{accentColor: "#3b82f6"}} />
                Active Routes
              </label>

              {/* Route Legend */}
              <div style={{ borderTop: "1px solid rgba(255,255,255,0.1)", paddingTop: "8px", display: "flex", flexDirection: "column", gap: "5px" }}>
                <div style={{ fontSize: "0.65rem", color: "#94a3b8", fontWeight: "600", letterSpacing: "0.5px" }}>ROUTE KEY</div>
                <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.65rem", color: "#e2e8f0" }}>
                  <div style={{ width: "20px", height: "3px", background: "#FFC107", borderRadius: "2px" }}></div>
                  <span>Planned Route</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.65rem", color: "#e2e8f0" }}>
                  <div style={{ width: "20px", height: "3px", background: "#388E3C", opacity: 0.55, borderRadius: "2px" }}></div>
                  <span>Completed</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.65rem", color: "#e2e8f0" }}>
                  <div style={{ width: "20px", height: "3px", background: "#ff3333", borderRadius: "2px" }}></div>
                  <span>Blocked Road</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
