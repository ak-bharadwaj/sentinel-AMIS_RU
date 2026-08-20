"""
Flood Module — Terrain-Aware Version
======================================
Uses the Terrain Intelligence Layer for physically correct flood modelling.

Key improvements over the flat-elevation version:
  - Flood threshold is based on water depth ABOVE road surface
    (effective_elevation = terrain_elevation + structural_offset)
  - Motorway flyovers (+10 m) are nearly immune to surface flooding
  - Coastal roads at 0–2 m elevation flood at realistic surge depths
  - Tunnels fill FASTER (negative effective_elevation = below ground)
  - Water accumulation rate now scales with TWI (Topographic Wetness Index)
    High-TWI nodes (drainage basins) accumulate water 2.5× faster
  - Gravity-driven flow accounts for effective head (terrain + water)
"""
from __future__ import annotations

import math
import networkx as nx
from backend.world_model.graph_builder import RIVER_LINE, calculate_distance_to_line_segment, generate_noise

# ---------------------------------------------------------------------------
# FloodModule
# ---------------------------------------------------------------------------
class FloodModule(object):
    def __init__(self, rainfall: float = 0.7):
        self.rainfall = rainfall   # [0, 1] dimensionless intensity

    # ------------------------------------------------------------------
    # Helper: effective elevation of a node
    # ------------------------------------------------------------------
    @staticmethod
    def _eff_elev(data: dict) -> float:
        """Return effective elevation in metres (terrain + structural offset).
        Falls back to 'elevation' if terrain data not yet enriched.
        """
        return float(data.get("effective_elevation", data.get("elevation", 10.0)))

    # ------------------------------------------------------------------
    # generate_prior
    # ------------------------------------------------------------------
    def generate_prior(self, graph: nx.Graph) -> None:
        """Assign flood danger priors using terrain intelligence.
        Uses TWI + effective_elevation for physically motivated risk.
        Runs before simulation starts.
        """
        distances = {}
        elevations = {}

        for n_id, data in graph.nodes(data=True):
            lat = data["lat"]
            lon = data["lon"]

            dist_to_water = data.get("dist_to_water")
            dist_to_coast = data.get("dist_to_coast")
            min_osm_dist = min(
                dist_to_water if dist_to_water is not None else 999999.0,
                dist_to_coast if dist_to_coast is not None else 999999.0
            )
            if min_osm_dist > 50000.0:
                min_osm_dist = calculate_distance_to_line_segment(
                    lat, lon, RIVER_LINE[0], RIVER_LINE[1]
                )

            distances[n_id] = min_osm_dist
            # Use effective_elevation so bridges/flyovers get credit
            elevations[n_id] = max(0.5, self._eff_elev(data))

        max_dist = max(1.0, max(distances.values())) if distances else 1.0
        max_elev = max(elevations.values()) if elevations else 1.0

        for n_id in graph.nodes:
            data = graph.nodes[n_id]
            dist = distances[n_id]
            eff_elev = elevations[n_id]

            # Terrain class + TWI modify water risk
            twi = data.get("twi", 5.0)
            drainage_class = data.get("terrain_class", "SLOPE")
            # TWI contribution: higher TWI = more water pooling risk
            twi_risk = min(1.0, twi / 12.0)

            water_proximity_risk = 1.0 - (dist / max_dist)
            elevation_risk = max(0.0, 1.0 - (eff_elev / max(max_elev, 80.0)))

            # Effective elevation above 10 m → dramatically reduced flood risk
            if eff_elev > 15.0:
                elevation_risk *= 0.2    # elevated flyover/bridge — very low risk
            elif eff_elev > 8.0:
                elevation_risk *= 0.5

            flood_risk = (
                0.45 * water_proximity_risk +
                0.30 * elevation_risk +
                0.15 * twi_risk +
                0.10 * self.rainfall
            )
            p_danger = max(0.05, min(0.95, flood_risk))

            data["p_danger"] = p_danger
            data["elevation"] = eff_elev
            data["water_level"] = 0.0
            if p_danger > 0.8:
                data["status"] = "DANGER"
            else:
                data["status"] = "SAFE"

    # ------------------------------------------------------------------
    # update_simulation_step
    # ------------------------------------------------------------------
    def update_simulation_step(self, graph: nx.Graph, step: int) -> list:
        newly_blocked_edges = []

        # 1. Rainfall accumulation — scaled by drainage_accumulation_rate (TWI)
        for n_id, data in graph.nodes(data=True):
            is_coastal = data.get("is_coastal", False)
            coastal_multiplier = 2.5 if is_coastal else 1.0

            eff_elev = self._eff_elev(data)
            is_tunnel = data.get("is_tunnel", False)

            # Tunnels fill much faster than surface roads (below-grade catchment)
            tunnel_multiplier = 2.5 if is_tunnel else 1.0

            # TWI-based drainage accumulation
            drain_rate = data.get("drainage_accumulation_rate", 1.0)

            # Base accumulation: lower terrain + high TWI + rainfall
            accumulation_rate = max(0.05, 1.0 - (eff_elev / 30.0)) * coastal_multiplier * tunnel_multiplier
            water_gain = accumulation_rate * drain_rate * self.rainfall * 1.8

            data["water_level"] = data.get("water_level", 0.0) + water_gain

        # 2. Gravity-driven hydrological spread using effective head
        # We track outflows first to prevent generating water out of nothing (violating mass conservation)
        outflows = {n_id: [] for n_id in graph.nodes}
        for u, v, edata in graph.edges(data=True):
            u_data = graph.nodes[u]
            v_data = graph.nodes[v]

            w_u = u_data.get("water_level", 0.0)
            w_v = v_data.get("water_level", 0.0)
            if w_u <= 0.001 and w_v <= 0.001:
                continue

            elev_u = self._eff_elev(u_data)
            elev_v = self._eff_elev(v_data)

            head_u = elev_u + w_u
            head_v = elev_v + w_v
            head_diff = head_u - head_v

            if head_diff > 0.0 and w_u > 0.0:
                outflows[u].append((v, head_diff * 0.12))
            elif head_diff < 0.0 and w_v > 0.0:
                outflows[v].append((u, -head_diff * 0.12))

        water_diffs = {n_id: 0.0 for n_id in graph.nodes}
        for u, flows in outflows.items():
            if not flows:
                continue
            total_potential_outflow = sum(f[1] for f in flows)
            w_u = graph.nodes[u].get("water_level", 0.0)
            scale = 1.0
            if total_potential_outflow > w_u:
                scale = w_u / total_potential_outflow
            for v, flow in flows:
                scaled_flow = flow * scale
                water_diffs[u] -= scaled_flow
                water_diffs[v] += scaled_flow

        for n_id, diff in water_diffs.items():
            graph.nodes[n_id]["water_level"] = max(0.0, graph.nodes[n_id].get("water_level", 0.0) + diff)


        # 3. Node blockage: water_depth_above_road = water_level - effective_elevation
        #    (negative for elevated roads → they never flood until water truly rises above them)
        from backend.config_params.parameters import params
        for n_id, data in graph.nodes(data=True):
            water_level = data.get("water_level", 0.0)
            eff_elev = self._eff_elev(data)
            node_type = data.get("node_type", "ROAD")
            current_status = data.get("status", "SAFE")

            # Depth of water ABOVE the road surface (key change from v0)
            water_above_road = water_level - eff_elev

            if water_above_road > params.flood_car_blocked_m and current_status not in ("FLOODED", "COMPROMISED"):
                if node_type in ("HOSPITAL", "SHELTER"):
                    data["status"] = "COMPROMISED"
                    data["p_danger"] = min(1.0, data.get("p_danger", 0.5) + 0.4)
                else:
                    data["status"] = "FLOODED"
                    data["p_danger"] = 1.0
                    for neighbor in list(graph.neighbors(n_id)):
                        if not graph.has_edge(n_id, neighbor):
                            continue
                        if not graph.edges[n_id, neighbor].get("blocked", False):
                            graph.edges[n_id, neighbor]["blocked"] = True
                            graph.edges[n_id, neighbor]["confidence"] = 1.0
                            newly_blocked_edges.append((n_id, neighbor))
            elif water_above_road <= params.flood_car_blocked_m and current_status == "FLOODED":
                data["status"] = "SAFE"
                data["p_danger"] = max(0.05, data.get("p_danger", 1.0) - 0.5)
                for neighbor in list(graph.neighbors(n_id)):
                    if not graph.has_edge(n_id, neighbor):
                        continue
                    neighbor_status = graph.nodes[neighbor].get("status", "SAFE")
                    if neighbor_status == "SAFE":
                        graph.edges[n_id, neighbor]["blocked"] = False
                        graph.edges[n_id, neighbor]["confidence"] = 1.0

        # 4. Bridge closures — checks effective head vs bridge effective_elevation
        for u, v, edge_data in graph.edges(data=True):
            if not edge_data.get("is_bridge"):
                continue
            wl_u = graph.nodes[u].get("water_level", 0.0)
            wl_v = graph.nodes[v].get("water_level", 0.0)
            eff_elev_edge = edge_data.get("effective_elevation",
                (self._eff_elev(graph.nodes[u]) + self._eff_elev(graph.nodes[v])) / 2.0)
            max_wl = max(wl_u, wl_v)
            # Bridge closes when total water head exceeds bridge clearance
            if max_wl - eff_elev_edge > params.flood_bridge_blocked_m:
                if not edge_data.get("blocked"):
                    edge_data["blocked"] = True
                    edge_data["confidence"] = 1.0
                    newly_blocked_edges.append((u, v))
            elif edge_data.get("blocked"):
                edge_data["blocked"] = False
                edge_data["confidence"] = 1.0

        return newly_blocked_edges
