import math
import random
import networkx as nx
from backend.world_model.graph_builder import haversine_distance

class WildfireModule(object):
    def __init__(self, wind_speed_ms: float = 8.0, wind_direction_deg: float = 225.0, moisture_content: float = 0.15):
        """Dedicated Wildfire module using simplified Rothermel ROS.
        All calculations are modeling assumptions.
        """
        self.wind_speed_ms = wind_speed_ms
        self.wind_direction_deg = wind_direction_deg
        self.moisture_content = moisture_content
        self.ignition_lat = None
        self.ignition_lon = None

    def get_fuel_load(self, data: dict) -> float:
        """Assign fuel load based on OSM landuse/natural vegetation attributes."""
        landuse = data.get('landuse', 'residential')
        natural = data.get('natural', '')
        
        if natural in ('wood', 'forest') or landuse == 'forest':
            return 0.85  # Heavy fuel load (Anderson FM 8-10)
        elif natural in ('scrub', 'heath', 'shrubbery'):
            return 0.55  # Medium fuel load (Anderson FM 4-6)
        elif landuse in ('grass', 'meadow') or data.get('node_type') == 'POPULATION_ZONE':
            return 0.25  # Light fuel load (Anderson FM 1-3)
        return 0.05      # Very light urban fuel load

    def generate_prior(self, graph: nx.Graph) -> None:
        """Calculate initial wildfire hazard indices per node based on vegetation fuel loads."""
        for n_id, data in graph.nodes(data=True):
            fuel = self.get_fuel_load(data)
            # Prior hazard maps directly to vegetation abundance
            p_danger = max(0.05, min(0.95, fuel * 0.9))
            
            graph.nodes[n_id]['p_danger'] = p_danger
            graph.nodes[n_id]['fuel_load'] = fuel
            graph.nodes[n_id]['fire_intensity'] = 0.0
            
            if p_danger > 0.8:
                graph.nodes[n_id]['status'] = "DANGER"
            else:
                graph.nodes[n_id]['status'] = "SAFE"

    def get_rate_of_spread(self, fuel_load: float, slope_pct: float = 0.0) -> float:
        """Compute rate of spread (ROS) using simplified Rothermel model formula.
        ROS = fuel_load * (1 + wind_factor) * (1 + slope_factor) * (1 - moisture)
        Returns ROS in meters per minute.
        """
        wind_factor = self.wind_speed_ms * 0.08
        slope_factor = slope_pct * 0.02
        moisture_factor = max(0.1, 1.0 - self.moisture_content)
        
        # Base spread rate equation (assumed modeling behavior)
        ros = 15.0 * fuel_load * (1.0 + wind_factor) * (1.0 + slope_factor) * moisture_factor
        return max(1.0, ros)

    def update_simulation_step(self, graph: nx.Graph, step: int) -> list:
        newly_blocked_edges = []
        
        # 1. Initialize ignition point if not set
        if self.ignition_lat is None or self.ignition_lon is None:
            # Find node with highest fuel load to start fire
            highest_fuel_node = None
            max_fuel = -1.0
            for n_id, data in graph.nodes(data=True):
                fuel = data.get('fuel_load', 0.05)
                if fuel > max_fuel:
                    max_fuel = fuel
                    highest_fuel_node = n_id
            
            if highest_fuel_node:
                self.ignition_lat = graph.nodes[highest_fuel_node].get('lat', 0.0)
                self.ignition_lon = graph.nodes[highest_fuel_node].get('lon', 0.0)
                graph.nodes[highest_fuel_node]['status'] = "FIRE"
                graph.nodes[highest_fuel_node]['p_danger'] = 1.0
                graph.nodes[highest_fuel_node]['fire_intensity'] = 100.0

        # Calculate wind angle components for directional bias (in radians)
        wind_rad = math.radians(self.wind_direction_deg)
        wind_vector = (-math.sin(wind_rad), -math.cos(wind_rad))
 
        # 2. Propagate active fire front to adjacent nodes
        active_fires = [n_id for n_id, data in graph.nodes(data=True) if data.get('status') == 'FIRE']
        
        for fire_node in active_fires:
            lat_u = graph.nodes[fire_node].get('lat', 0.0)
            lon_u = graph.nodes[fire_node].get('lon', 0.0)
            fuel_u = graph.nodes[fire_node].get('fuel_load', 0.05)
            slope_u = graph.nodes[fire_node].get('slope', 0.0)
            
            # Fuel burn down over time
            current_fuel = graph.nodes[fire_node].get('fuel_load', 0.05)
            graph.nodes[fire_node]['fuel_load'] = max(0.0, current_fuel - 0.05)
            if graph.nodes[fire_node]['fuel_load'] <= 0.0:
                # Fire burned out
                graph.nodes[fire_node]['status'] = "SAFE"
                graph.nodes[fire_node]['p_danger'] = 0.2
                graph.nodes[fire_node]['fire_intensity'] = 0.0
                for edge_node in list(graph.neighbors(fire_node)):
                    if graph.has_edge(fire_node, edge_node):
                        graph.edges[fire_node, edge_node]['blocked'] = False
                        graph.edges[fire_node, edge_node]['confidence'] = 1.0
                continue
            
            # Rate of spread scales with slope percentage
            ros = self.get_rate_of_spread(fuel_u, slope_pct=slope_u * 100.0)
            # Map step size to minutes (1 minute timestep)
            spread_dist_m = ros * 1.0
            
            for neighbor in list(graph.neighbors(fire_node)):
                neigh_data = graph.nodes[neighbor]
                if neigh_data.get('status') == 'FIRE':
                     continue
                
                lat_v = neigh_data.get('lat', 0.0)
                lon_v = neigh_data.get('lon', 0.0)
                
                # Direction vector of edge
                dy = lat_v - lat_u
                dx = (lon_v - lon_u) * math.cos(math.radians((lat_u + lat_v) / 2.0))
                dist_degrees = math.hypot(dx, dy)
                if dist_degrees < 1e-9:
                    continue
                
                # Normalize direction
                dir_y = dy / dist_degrees
                dir_x = dx / dist_degrees
                
                # Dot product with wind vector (downwind bias factor)
                dot_prod = dir_x * wind_vector[0] + dir_y * wind_vector[1]
                wind_bias = 1.0 + max(0.0, dot_prod) * 2.0  # 3x boost in downwind direction
                
                effective_spread_dist = spread_dist_m * wind_bias
                # Calculate accurate physical distance using haversine metric (unit: meters)
                actual_dist_m = haversine_distance(lat_u, lon_u, lat_v, lon_v) * 1000.0
                
                # Probability of ignition decays with distance
                ignition_prob = math.exp(-actual_dist_m / max(50.0, effective_spread_dist))
                
                if random.random() < ignition_prob:
                    neigh_data['status'] = "FIRE"
                    neigh_data['p_danger'] = 1.0
                    neigh_data['fire_intensity'] = 100.0
                    
                    # Fire blocks the road
                    for edge_node in list(graph.neighbors(neighbor)):
                        if not graph.has_edge(neighbor, edge_node):
                            continue
                        if not graph.edges[neighbor, edge_node].get('blocked', False):
                            graph.edges[neighbor, edge_node]['blocked'] = True
                            graph.edges[neighbor, edge_node]['confidence'] = 1.0
                            newly_blocked_edges.append((neighbor, edge_node))
                            
        return newly_blocked_edges
