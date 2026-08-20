import math
import random
import networkx as nx
from backend.world_model.graph_builder import haversine_distance

class CycloneModule(object):
    def __init__(
        self,
        wind_speed: float = 120.0,
        track_heading_deg: float = 270.0,
        track_speed_kmh: float = 25.0,
        rmax_km: float = 30.0,
        central_pressure_hPa: float = 950.0
    ):
        self.wind_speed = wind_speed  # Vmax in km/h
        self.track_heading_deg = track_heading_deg
        self.track_speed_kmh = track_speed_kmh
        self.rmax_km = rmax_km
        self.central_pressure_hPa = central_pressure_hPa
        self.eye_lat = None
        self.eye_lon = None

    def generate_prior(self, graph: nx.Graph) -> None:
        """Assign cyclone hazard priors based on coastal proximity."""
        max_dist = 1.0
        distances = []
        for n_id, data in graph.nodes(data=True):
            d = data.get('dist_to_coast')
            if d is None:
                d = 999999.0
            if d < 100000.0:
                distances.append(d)
                
        if distances:
            max_dist = max(distances)
            
        for n_id, data in graph.nodes(data=True):
            dist_to_coast = data.get('dist_to_coast')
            if dist_to_coast is None:
                dist_to_coast = 999999.0
            
            if dist_to_coast > 100000.0:
                coast_risk = 0.5
            else:
                coast_risk = 1.0 - (dist_to_coast / max(1.0, max_dist))
                
            cyclone_risk = 0.6 * coast_risk + 0.4 * (self.wind_speed / 200.0)
            p_danger = max(0.05, min(0.95, cyclone_risk))
            p_wind = max(0.0, min(1.0, (self.wind_speed * coast_risk) / 100.0))
            
            graph.nodes[n_id]['p_wind'] = p_wind
            graph.nodes[n_id]['wind_speed'] = self.wind_speed * coast_risk
            graph.nodes[n_id]['p_danger'] = p_danger
            if p_danger > 0.8:
                graph.nodes[n_id]['status'] = "DANGER"
            else:
                graph.nodes[n_id]['status'] = "SAFE"

    def get_holland_wind(self, r_km: float, lat_deg: float) -> float:
        """Holland 1980 parametric surface wind model.
        Returns surface wind speed in km/h at radial distance r_km.
        """
        if r_km < 0.5:
            return self.wind_speed * 0.1
            
        rho_air = 1.15  # kg/m³
        e = math.e
        # Pressure deficit in Pa (1013 - central_pressure), clamped for stability
        delta_P_Pa = max(100.0, (1013.0 - self.central_pressure_hPa) * 100.0)
        
        # Holland B shape factor (bounded 1.0 to 2.5)
        Vmax_ms = self.wind_speed / 3.6
        B = max(1.0, min(2.5, (Vmax_ms**2 * rho_air * e) / delta_P_Pa))
        
        # Coriolis parameter
        f = 2.0 * 7.2921e-5 * math.sin(math.radians(abs(lat_deg)))
        
        r_m = r_km * 1000.0
        Rmax_m = self.rmax_km * 1000.0
        ratio = (Rmax_m / r_m) ** B
        
        term1 = (B / rho_air) * delta_P_Pa * ratio * math.exp(-ratio)
        term2 = (r_m * f / 2.0) ** 2
        Vg = math.sqrt(max(0.0, term1 + term2)) - (r_m * f / 2.0)
        
        # Surface wind reduction factor: 0.75
        return Vg * 0.75 * 3.6

    def update_simulation_step(self, graph: nx.Graph, step: int) -> list:
        newly_blocked_edges = []
        
        # 1. Initialize eye coordinates to graph center if not set
        if self.eye_lat is None or self.eye_lon is None:
            lats = [d.get('lat') for _, d in graph.nodes(data=True) if d.get('lat')]
            lons = [d.get('lon') for _, d in graph.nodes(data=True) if d.get('lon')]
            if lats and lons:
                self.eye_lat = sum(lats) / len(lats)
                self.eye_lon = sum(lons) / len(lons)
            else:
                self.eye_lat = 0.0
                self.eye_lon = 0.0
        else:
            # Move storm eye coordinates along track trajectory
            # 1 degree lat ≈ 111km. Speed is in km/h.
            # Assuming step represents 1 minute of real time
            step_hours = 1.0 / 60.0
            dist_moved = self.track_speed_kmh * step_hours
            heading_rad = math.radians(self.track_heading_deg)
            self.eye_lat += (dist_moved * math.cos(heading_rad)) / 111.0
            self.eye_lon += (dist_moved * math.sin(heading_rad)) / (111.0 * max(0.01, math.cos(math.radians(self.eye_lat))))

        for n_id, data in graph.nodes(data=True):
            lat = data.get('y', data.get('lat'))
            lon = data.get('x', data.get('lon'))
            if lat is None or lon is None:
                continue

            # Calculate distance to storm eye in kilometers using haversine metric
            dist_km = haversine_distance(lat, lon, self.eye_lat, self.eye_lon) / 1000.0
            
            # Holland B gradient wind speed
            local_wind = self.get_holland_wind(dist_km, lat)
            
            # Inland wind decay multiplier: NWS guidance (loses ~8% wind speed per km inland)
            dist_to_coast_m = float(data.get('dist_to_coast', 0.0) or 0.0)
            if dist_to_coast_m > 0:
                dist_to_coast_km = dist_to_coast_m / 1000.0
                inland_decay = math.exp(-0.08 * dist_to_coast_km)
                local_wind *= inland_decay
                
            # Compute p_wind from local wind speed: gusts >80 km/h push p_wind & p_danger past 0.8
            p_wind = max(0.0, min(1.0, local_wind / 100.0))
            data['p_wind'] = p_wind
            data['wind_speed'] = local_wind

            # Scale p_danger so gusts >80 km/h push p_danger past 0.8
            current_danger = data.get('p_danger', 0.0)
            next_danger = max(current_danger, p_wind)
            data['p_danger'] = next_danger

            # Storm surge — only inundates nodes if surge depth EXCEEDS effective elevation
            if 0 < dist_to_coast_m <= 10000.0:  # within 10 km of coast
                Vmax_ms = self.wind_speed / 3.6
                peak_surge = 0.0023 * Vmax_ms**2 * (50.0 / 30.0)
                dist_coast_km = dist_to_coast_m / 1000.0
                surge_depth = peak_surge * math.exp(-0.07 * dist_coast_km)

                # Effective elevation check: surge only reaches above-ground if it
                # exceeds the road surface height (terrain + structural offset)
                eff_elev = float(data.get('effective_elevation', data.get('elevation', 5.0)))
                water_above_road = surge_depth - eff_elev

                if water_above_road > 0:
                    # Water reaches this road surface
                    data['water_level'] = max(data.get('water_level', 0.0), water_above_road)
                # else: elevated node — surge doesn't reach road surface

            if next_danger > 0.80 and data.get('status') != "DANGER" and data.get('node_type') not in ("HOSPITAL", "SHELTER"):
                data['status'] = "DANGER"
                for neighbor in list(graph.neighbors(n_id)):
                    if not graph.has_edge(n_id, neighbor):
                        continue
                    if not graph.edges[n_id, neighbor].get('blocked', False):
                        graph.edges[n_id, neighbor]['blocked'] = True
                        graph.edges[n_id, neighbor]['confidence'] = 1.0
                        newly_blocked_edges.append((n_id, neighbor))
            elif local_wind < 40.0 and data.get('status') == "DANGER" and data.get('node_type') not in ("HOSPITAL", "SHELTER"):
                if data.get('water_level', 0.0) <= 0.3:
                    data['status'] = "SAFE"
                    data['p_danger'] = p_wind
                    for neighbor in list(graph.neighbors(n_id)):
                        if graph.has_edge(n_id, neighbor):
                            graph.edges[n_id, neighbor]['blocked'] = False
                            graph.edges[n_id, neighbor]['confidence'] = 1.0
                            
        return newly_blocked_edges

