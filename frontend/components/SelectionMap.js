import { useEffect, useRef, useState } from "react";
import "leaflet/dist/leaflet.css";

export default function SelectionMap({
  centerLat = 19.0760,
  centerLon = 72.8777,
  span = 0.06,
  onChange,
  mapHeight = "160px",
  initialLatSpan = 0.06,
  initialLngSpan = 0.06
}) {
  const mapRef = useRef(null);
  const leafletMap = useRef(null);
  const markerRef = useRef(null);
  const rectangleRef = useRef(null);
  
  // Independent latitude/longitude spans for MS Paint resizing control
  const [latSpan, setLatSpan] = useState(initialLatSpan);
  const [lngSpan, setLngSpan] = useState(initialLngSpan);

  const latSpanRef = useRef(initialLatSpan);
  const lngSpanRef = useRef(initialLngSpan);
  const onChangeRef = useRef(onChange);

  useEffect(() => { latSpanRef.current = latSpan; }, [latSpan]);
  useEffect(() => { lngSpanRef.current = lngSpan; }, [lngSpan]);
  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);

  // Average span for display & parent state syncing
  const currentSpan = (latSpan + lngSpan) / 2.0;

  const updateRectangle = (lat, lon, lSpan, gSpan) => {
    if (rectangleRef.current) {
      rectangleRef.current.setBounds([
        [lat - lSpan, lon - gSpan],
        [lat + lSpan, lon + gSpan]
      ]);
    }
  };

  // ── Initialise map once ───────────────────────────────────────────────────
  useEffect(() => {
    const L = require("leaflet");

    delete L.Icon.Default.prototype._getIconUrl;
    L.Icon.Default.mergeOptions({
      iconRetinaUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png",
      iconUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png",
      shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png",
    });

    if (leafletMap.current) return;

    const map = L.map(mapRef.current, {
      zoomControl: true,
      attributionControl: false,
    }).setView([centerLat, centerLon], 12);

    L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
      maxZoom: 19,
    }).addTo(map);

    leafletMap.current = map;

    const initSpan = latSpanRef.current;

    // ── Crosshair center marker ──────────────────────────────────────────
    const crosshairIcon = L.divIcon({
      className: "",
      html: `<div style="width:28px;height:28px;display:flex;align-items:center;justify-content:center;background:rgba(79,70,229,0.85);border:2px solid #fff;border-radius:50%;box-shadow:0 2px 8px rgba(0,0,0,0.5);cursor:move;font-size:14px;">✛</div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });

    const marker = L.marker([centerLat, centerLon], {
      draggable: true,
      title: "Drag to move box",
      icon: crosshairIcon,
      zIndexOffset: 1000,
    }).addTo(map);
    markerRef.current = marker;

    // ── Bounding box rectangle ──────────────────────────────────────────
    const rectangle = L.rectangle(
      [[centerLat - initialLatSpan, centerLon - initialLngSpan], [centerLat + initialLatSpan, centerLon + initialLngSpan]],
      { color: "#4f46e5", weight: 2, fill: false, dashArray: "6,4", interactive: true }
    ).addTo(map);
    rectangleRef.current = rectangle;

    // ── 8 Resize Handles (4 Edges & 4 Corners) ───────────────────────────
    const handleGroup = L.layerGroup().addTo(map);

    const createHandleIcon = (cursorType) => L.divIcon({
      className: "",
      html: `<div style="width:12px;height:12px;background:#4f46e5;border:2.5px solid #fff;border-radius:3px;box-shadow:0 1.5px 4px rgba(0,0,0,0.4);cursor:${cursorType};"></div>`,
      iconSize: [12, 12],
      iconAnchor: [6, 6]
    });

    const handles = {
      n: L.marker([centerLat + initialLatSpan, centerLon], { draggable: true, icon: createHandleIcon("n-resize") }),
      s: L.marker([centerLat - initialLatSpan, centerLon], { draggable: true, icon: createHandleIcon("s-resize") }),
      e: L.marker([centerLat, centerLon + initialLngSpan], { draggable: true, icon: createHandleIcon("e-resize") }),
      w: L.marker([centerLat, centerLon - initialLngSpan], { draggable: true, icon: createHandleIcon("w-resize") }),
      ne: L.marker([centerLat + initialLatSpan, centerLon + initialLngSpan], { draggable: true, icon: createHandleIcon("ne-resize") }),
      nw: L.marker([centerLat + initialLatSpan, centerLon - initialLngSpan], { draggable: true, icon: createHandleIcon("nw-resize") }),
      se: L.marker([centerLat - initialLatSpan, centerLon + initialLngSpan], { draggable: true, icon: createHandleIcon("se-resize") }),
      sw: L.marker([centerLat - initialLatSpan, centerLon - initialLngSpan], { draggable: true, icon: createHandleIcon("sw-resize") }),
    };

    Object.values(handles).forEach(h => h.addTo(handleGroup));

    const syncHandles = (lat, lon, lSpan, gSpan) => {
      handles.n.setLatLng([lat + lSpan, lon]);
      handles.s.setLatLng([lat - lSpan, lon]);
      handles.e.setLatLng([lat, lon + gSpan]);
      handles.w.setLatLng([lat, lon - gSpan]);
      handles.ne.setLatLng([lat + lSpan, lon + gSpan]);
      handles.nw.setLatLng([lat + lSpan, lon - gSpan]);
      handles.se.setLatLng([lat - lSpan, lon + gSpan]);
      handles.sw.setLatLng([lat - lSpan, lon - gSpan]);
    };

    map.syncHandlesGlobal = syncHandles;
    syncHandles(centerLat, centerLon, initialLatSpan, initialLngSpan);

    const onResizeDrag = (handleKey) => {
      const mPos = marker.getLatLng();
      let lSpan = latSpanRef.current;
      let gSpan = lngSpanRef.current;

      if (handleKey === "n") {
        lSpan = Math.abs(handles.n.getLatLng().lat - mPos.lat);
      } else if (handleKey === "s") {
        lSpan = Math.abs(handles.s.getLatLng().lat - mPos.lat);
      } else if (handleKey === "e") {
        gSpan = Math.abs(handles.e.getLatLng().lng - mPos.lng);
      } else if (handleKey === "w") {
        gSpan = Math.abs(handles.w.getLatLng().lng - mPos.lng);
      } else if (handleKey === "ne") {
        lSpan = Math.abs(handles.ne.getLatLng().lat - mPos.lat);
        gSpan = Math.abs(handles.ne.getLatLng().lng - mPos.lng);
      } else if (handleKey === "nw") {
        lSpan = Math.abs(handles.nw.getLatLng().lat - mPos.lat);
        gSpan = Math.abs(handles.nw.getLatLng().lng - mPos.lng);
      } else if (handleKey === "se") {
        lSpan = Math.abs(handles.se.getLatLng().lat - mPos.lat);
        gSpan = Math.abs(handles.se.getLatLng().lng - mPos.lng);
      } else if (handleKey === "sw") {
        lSpan = Math.abs(handles.sw.getLatLng().lat - mPos.lat);
        gSpan = Math.abs(handles.sw.getLatLng().lng - mPos.lng);
      }

      // Constrain spans to min/max configuration
      lSpan = Math.max(0.015, Math.min(0.12, lSpan));
      gSpan = Math.max(0.015, Math.min(0.12, gSpan));

      rectangle.setBounds([[mPos.lat - lSpan, mPos.lng - gSpan], [mPos.lat + lSpan, mPos.lng + gSpan]]);
      syncHandles(mPos.lat, mPos.lng, lSpan, gSpan);

      latSpanRef.current = lSpan;
      lngSpanRef.current = gSpan;
      setLatSpan(lSpan);
      setLngSpan(gSpan);
    };

    Object.entries(handles).forEach(([key, h]) => {
      h.on("drag", () => onResizeDrag(key));
      h.on("dragend", () => {
        const mPos = marker.getLatLng();
        if (onChangeRef.current) onChangeRef.current(mPos.lat, mPos.lng, latSpanRef.current, lngSpanRef.current);
      });
    });

    // ── Drag rectangle to MOVE entire box ──────────────────────────────
    let isDragging = false;
    let dragStartLatLng = null;
    let dragStartCenter = null;

    rectangle.on("mousedown", (e) => {
      L.DomEvent.stopPropagation(e);
      L.DomEvent.preventDefault(e);
      isDragging = true;
      dragStartLatLng = e.latlng;
      dragStartCenter = marker.getLatLng();
      map.dragging.disable();
      map.getContainer().style.cursor = "grabbing";
    });

    map.on("mousemove", (e) => {
      if (!isDragging) return;
      const lS = latSpanRef.current;
      const gS = lngSpanRef.current;
      const dLat = e.latlng.lat - dragStartLatLng.lat;
      const dLng = e.latlng.lng - dragStartLatLng.lng;
      const newLat = dragStartCenter.lat + dLat;
      const newLng = dragStartCenter.lng + dLng;
      marker.setLatLng([newLat, newLng]);
      rectangle.setBounds([[newLat - lS, newLng - gS], [newLat + lS, newLng + gS]]);
      syncHandles(newLat, newLng, lS, gS);
    });

    map.on("mouseup", () => {
      if (!isDragging) return;
      isDragging = false;
      map.dragging.enable();
      map.getContainer().style.cursor = "";
      const pos = marker.getLatLng();
      if (onChangeRef.current) onChangeRef.current(pos.lat, pos.lng, latSpanRef.current, lngSpanRef.current);
    });

    rectangle.on("mouseover", () => { if (!isDragging) map.getContainer().style.cursor = "grab"; });
    rectangle.on("mouseout", () => { if (!isDragging) map.getContainer().style.cursor = ""; });

    // ── Center marker drag → moves box ─────────────────────────────────
    marker.on("drag", () => {
      const pos = marker.getLatLng();
      const lS = latSpanRef.current;
      const gS = lngSpanRef.current;
      rectangle.setBounds([[pos.lat - lS, pos.lng - gS], [pos.lat + lS, pos.lng + gS]]);
      syncHandles(pos.lat, pos.lng, lS, gS);
    });
  }, []);
  useEffect(() => {
    if (!leafletMap.current || !markerRef.current) return;
    const pos = markerRef.current.getLatLng();
    if (Math.abs(pos.lat - centerLat) > 0.001 || Math.abs(pos.lng - centerLon) > 0.001) {
      const lS = latSpanRef.current;
      const gS = lngSpanRef.current;
      markerRef.current.setLatLng([centerLat, centerLon]);
      leafletMap.current.setView([centerLat, centerLon], 12);
      updateRectangle(centerLat, centerLon, lS, gS);
      // Re-trigger sync handles globally to position border boxes
      const syncFunc = leafletMap.current.syncHandlesGlobal;
      if (syncFunc) syncFunc(centerLat, centerLon, lS, gS);
    }
  }, [centerLat, centerLon]);

  // ── Respond to external span changes (slider) ───────────────────────────
  useEffect(() => {
    if (!leafletMap.current || !markerRef.current) return;
    const currentAvg = (latSpanRef.current + lngSpanRef.current) / 2.0;
    // Only override if the external span value represents a jump or reset
    if (Math.abs(span - currentAvg) > 0.0001) {
      latSpanRef.current = span;
      lngSpanRef.current = span;
      setLatSpan(span);
      setLngSpan(span);
      const pos = markerRef.current.getLatLng();
      updateRectangle(pos.lat, pos.lng, span, span);
      const syncFunc = leafletMap.current.syncHandlesGlobal;
      if (syncFunc) syncFunc(pos.lat, pos.lng, span, span);
    }
  }, [span]);

  // ── Slider change handler ───────────────────────────────────────────────
  const handleSliderChange = (e) => {
    const newSpan = parseFloat(e.target.value);
    latSpanRef.current = newSpan;
    lngSpanRef.current = newSpan;
    setLatSpan(newSpan);
    setLngSpan(newSpan);
    if (markerRef.current) {
      const pos = markerRef.current.getLatLng();
      updateRectangle(pos.lat, pos.lng, newSpan, newSpan);
      if (onChangeRef.current) onChangeRef.current(pos.lat, pos.lng, newSpan, newSpan);
    }
  };

  // ── Search handler ──────────────────────────────────────────────────────
  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(searchQuery)}`);
      const data = await res.json();
      if (data && data.length > 0) {
        const lat = parseFloat(data[0].lat);
        const lon = parseFloat(data[0].lon);
        const lS = latSpanRef.current;
        const gS = lngSpanRef.current;
        leafletMap.current.setView([lat, lon], 12);
        markerRef.current.setLatLng([lat, lon]);
        updateRectangle(lat, lon, lS, gS);
        if (onChangeRef.current) onChangeRef.current(lat, lon, lS, gS);
      } else {
        alert("Location not found.");
      }
    } catch (err) {
      console.error("Search failed:", err);
    } finally {
      setSearching(false);
    }
  };

  const spanInKm = Math.round(currentSpan * 111 * 2);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px", width: "100%" }}>
      <form onSubmit={handleSearch} style={{ display: "flex", gap: "6px" }}>
        <input
          type="text"
          placeholder="🔍 Search city (e.g. Paris, Tokyo, Mumbai)..."
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          className="select-input-sidebar"
          style={{ flex: 1, padding: "5px 10px", fontSize: "0.7rem" }}
          disabled={searching}
        />
        <button
          type="submit"
          className="btn"
          style={{ padding: "5px 10px", fontSize: "0.68rem", background: "rgba(99,102,241,0.15)", borderColor: "#6366f1" }}
          disabled={searching}
        >
          {searching ? "Searching..." : "Go"}
        </button>
      </form>

      <div
        ref={mapRef}
        style={{
          height: mapHeight,
          width: "100%",
          borderRadius: mapHeight === "100%" ? "0" : "8px",
          border: "1px solid rgba(255,255,255,0.08)",
          boxShadow: "inset 0 0 10px rgba(0,0,0,0.5)"
        }}
      />

      <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "0.68rem" }}>
          <span style={{ color: "var(--text-secondary)", fontWeight: "600" }}>TACTICAL AREA DIAMETER</span>
          <span style={{ color: "#6366f1", fontWeight: "700" }}>~{spanInKm} km ({currentSpan.toFixed(3)}°)</span>
        </div>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <span style={{ fontSize: "0.62rem", color: "var(--text-muted)" }}>Narrow</span>
          <input
            type="range"
            min="0.015"
            max="0.12"
            step="0.005"
            value={currentSpan}
            onChange={handleSliderChange}
            style={{ flex: 1, accentColor: "#6366f1", height: "4px" }}
          />
          <span style={{ fontSize: "0.62rem", color: "var(--text-muted)" }}>Metropolitan</span>
        </div>
      </div>
    </div>
  );
}
