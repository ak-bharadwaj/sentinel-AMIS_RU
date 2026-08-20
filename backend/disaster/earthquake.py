"""
Earthquake Module — Terrain-Aware Version
==========================================
Uses TerrainProcessor outputs (vs30_terrain, bridge_amplification, effective_elevation)
for physically improved seismic risk modelling.

Key improvements over V0:
  - Vs30 now comes from terrain class (PEAK → rock, BASIN → soft sediment)
    with low-elevation Class E correction (reclaimed coastal land)
  - Bridge amplification factor from structural_offsets.py
    (elevated bridges resonate with lateral seismic waves)
  - Landuse heuristic retained as final fallback (priority 3)
"""
import math
import networkx as nx
from backend.world_model.graph_builder import FAULT_LINE, calculate_distance_to_line_segment, haversine_distance
from backend.config_params.parameters import params


def bssa14_pga(Mw: float, Rjb_km: float, Vs30: float = 360.0) -> float:
    """BSSA14 NGA-West2 Peak Ground Acceleration (PGA) attenuation backbone.
    Returns PGA in g units. Assumes modeling parameters.
    """
    Mh = 6.2  # Hinge magnitude
    if Mw <= 5.5:
        F_E = 0.4873 + 1.0596 * (Mw - Mh)
    elif Mw <= 6.2:
        F_E = 0.4873 + 1.0596 * (Mw - Mh) - 0.0149 * (Mw - Mh) ** 2
    else:
        F_E = 0.4873 - 0.0351 * (Mw - 6.2)

    R = math.sqrt(Rjb_km ** 2 + 4.5 ** 2)
    F_P = -1.5765 * math.log(R / 1.0) - 0.00701 * (R - 1.0)

    Vref = 760.0
    Vs30_clamped = max(100.0, Vs30)
    F_S = 0.0 if Vs30_clamped >= Vref else -0.596 * math.log(Vs30_clamped / Vref)

    ln_PGA = F_E + F_P + F_S
    return math.exp(ln_PGA)


class EarthquakeModule(object):
    def __init__(self, epicenter_lat=None, epicenter_lon=None, magnitude_mw: float = 6.5):
        self.epicenter_lat = epicenter_lat
        self.epicenter_lon = epicenter_lon
        self.magnitude_mw = magnitude_mw

    def get_vs30(self, data: dict) -> float:
        """Assign Vs30 (shear-wave velocity) in m/s.

        Priority:
          1. Official geological dataset (vs30_geological tag)
          2. TerrainProcessor computed value (vs30_terrain) — preferred in V1
          3. Landuse heuristic fallback
        """
        # 1. Official geological data
        if 'vs30_geological' in data:
            return float(data['vs30_geological'])

        # 2. Terrain Intelligence Vs30
        if 'vs30_terrain' in data:
            vs30 = float(data['vs30_terrain'])
            eff_elev = float(data.get('effective_elevation', data.get('elevation', 10.0)))
            if eff_elev < 3.0:
                vs30 = min(vs30, 180.0)   # Class E — very soft sediment
            elif eff_elev < 8.0:
                vs30 = min(vs30, 220.0)   # Class D/E boundary
            return vs30

        # 3. Landuse heuristic fallback
        landuse = data.get('landuse', 'residential')
        if landuse in ('quarry', 'rock', 'mountain'):
            return 760.0
        elif landuse in ('industrial', 'commercial', 'retail'):
            return 360.0
        elif landuse in ('park', 'grass', 'forest'):
            return 270.0
        elif landuse in ('reclaimed', 'waterfront', 'marsh'):
            return 180.0
        return 300.0

    def generate_prior(self, graph: nx.Graph) -> None:
        distances = {}
        soils = {}
        for n_id, data in graph.nodes(data=True):
            lat = data['lat']
            lon = data['lon']
            dist_to_fault = calculate_distance_to_line_segment(lat, lon, FAULT_LINE[0], FAULT_LINE[1])
            distances[n_id] = dist_to_fault
            vs30 = self.get_vs30(data)
            soils[n_id] = 1.0 + max(0.0, (760.0 - vs30) / 400.0)

        max_fault_dist = max(1.0, max(distances.values())) if distances else 1.0

        for n_id, data in graph.nodes(data=True):
            dist = distances[n_id]
            soil_factor = soils[n_id]

            node_type = data.get('node_type', 'ROAD')
            if node_type == "HOSPITAL":
                vulnerability = 0.1
            elif node_type == "SHELTER":
                vulnerability = 0.1
            elif node_type == "POPULATION_ZONE":
                vulnerability = 0.6
            elif node_type == "BRIDGE":
                vulnerability = 0.5
            else:
                vulnerability = 0.2

            if data.get("is_tall_building_zone", False):
                vulnerability = min(1.0, vulnerability * 1.5)

            fault_proximity = 1.0 - (dist / max_fault_dist)
            risk = 0.5 * vulnerability + 0.3 * fault_proximity + 0.2 * (soil_factor - 1.0)
            p_danger = max(0.05, min(0.95, risk))

            graph.nodes[n_id]['p_danger'] = p_danger
            if p_danger > 0.8:
                graph.nodes[n_id]['status'] = "DANGER"
            else:
                graph.nodes[n_id]['status'] = "SAFE"

    def update_simulation_step(self, graph: nx.Graph, step: int) -> list:
        newly_blocked_edges = []

        if not self.epicenter_lat or not self.epicenter_lon:
            self.epicenter_lat = (FAULT_LINE[0][0] + FAULT_LINE[1][0]) / 2.0
            self.epicenter_lon = (FAULT_LINE[0][1] + FAULT_LINE[1][1]) / 2.0

        shockwave_radius_m = (0.003 + (step * 0.004)) * 111000.0

        for n_id, data in graph.nodes(data=True):
            lat = data.get('y', data.get('lat'))
            lon = data.get('x', data.get('lon'))
            if lat is None or lon is None:
                continue

            dist_to_epicenter_m = haversine_distance(lat, lon, self.epicenter_lat, self.epicenter_lon)

            if dist_to_epicenter_m <= shockwave_radius_m:
                vulnerability = 0.2
                ntype = data.get('node_type', 'ROAD')
                if ntype == "BRIDGE":
                    vulnerability = 0.8
                elif ntype == "POPULATION_ZONE":
                    vulnerability = 0.6

                if data.get("is_tall_building_zone", False):
                    vulnerability = min(1.0, vulnerability * 1.5)

                dist_km = dist_to_epicenter_m / 1000.0
                vs30 = self.get_vs30(data)
                pga = bssa14_pga(self.magnitude_mw, dist_km, vs30)

                # Bridge amplification from TerrainProcessor structural offsets
                bridge_amp = float(data.get('bridge_amplification', 1.0))

                structural_damage = vulnerability * pga * 1.2 * bridge_amp

                current_danger = data.get('p_danger', 0.0)
                next_danger = min(1.0, current_danger + structural_damage)
                data['p_danger'] = next_danger

                if next_danger > 0.88 and data.get('status') != "DANGER" and data.get('node_type') not in ("HOSPITAL", "SHELTER"):
                    data['status'] = "DANGER"
                    for neighbor in list(graph.neighbors(n_id)):
                        if not graph.has_edge(n_id, neighbor):
                            continue
                        if not graph.edges[n_id, neighbor].get('blocked', False):
                            graph.edges[n_id, neighbor]['blocked'] = True
                            graph.edges[n_id, neighbor]['confidence'] = 1.0
                            newly_blocked_edges.append((n_id, neighbor))
            elif dist_to_epicenter_m > shockwave_radius_m and data.get('status') == "DANGER" and data.get('node_type') not in ("HOSPITAL", "SHELTER"):
                # Natural attenuation of minor dust/debris post-shockwave
                if data.get('p_danger', 0.0) < 0.90:
                    data['status'] = "SAFE"
                    data['p_danger'] = max(0.1, data.get('p_danger', 0.8) - 0.2)
                    for neighbor in list(graph.neighbors(n_id)):
                        if graph.has_edge(n_id, neighbor) and graph.nodes[neighbor].get('status') == 'SAFE':
                            graph.edges[n_id, neighbor]['blocked'] = False
                            graph.edges[n_id, neighbor]['confidence'] = 1.0

        return newly_blocked_edges
