import math
import os
import urllib.request
import xml.etree.ElementTree as ET
import numpy as np
from datetime import datetime, timezone
from typing import List, Tuple, Dict, Optional, Any, Set

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance in meters between two points on the earth."""
    # Radius of earth in meters
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c

from backend.world_model.node import NodeModel
from backend.world_model.edge import EdgeModel
from backend.config import settings

# Bounding box of simulated area (e.g., center of a city)
LAT_CENTER = 37.7749
LON_CENTER = -122.4194

# Synthetic River Line (Diagonal across bounding box)
RIVER_LINE: List[List[float]] = [
    [LAT_CENTER - 0.015, LON_CENTER - 0.015],
    [LAT_CENTER + 0.015, LON_CENTER + 0.015]
]

# Synthetic Fault Line (Horizontal across center)
FAULT_LINE: List[List[float]] = [
    [LAT_CENTER, LON_CENTER - 0.015],
    [LAT_CENTER, LON_CENTER + 0.015]
]

def calculate_distance_to_line_segment(lat: float, lon: float, p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    # Rough distance in degrees
    y, x = lat, lon
    y1, x1 = p1
    y2, x2 = p2
    
    # Perpendicular distance to line segment
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    
    denom = dx*dx + dy*dy
    t = ((x - x1) * dx + (y - y1) * dy) / denom if denom > 1e-12 else 0.0
    t = max(0.0, min(1.0, t))
    
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    
    from backend.config_params.parameters import params
    return math.hypot(x - proj_x, y - proj_y) * getattr(params, 'degrees_to_meters', 111000.0)

def generate_noise(lat: float, lon: float, scale: float = 100.0) -> float:
    # Simple deterministic noise function
    val = math.sin(lat * scale) * math.cos(lon * scale) + math.sin(lon * scale / 2.0)
    return (val + 2.0) / 4.0  # normalize to [0, 1]

def build_synthetic_graph(center_lat: float = LAT_CENTER, center_lon: float = LON_CENTER, lat_span: Optional[float] = None, lon_span: Optional[float] = None) -> Tuple[List[NodeModel], List[EdgeModel]]:
    """Generates a synthetic grid representing a real-world urban layout for testing/reproducibility."""
    l_span = lat_span if lat_span is not None else settings.GRID_SIZE_LAT / 2.0
    g_span = lon_span if lon_span is not None else settings.GRID_SIZE_LON / 2.0

    global RIVER_LINE, FAULT_LINE
    RIVER_LINE[0][0] = center_lat - l_span / 2.0
    RIVER_LINE[0][1] = center_lon - g_span / 2.0
    RIVER_LINE[1][0] = center_lat + l_span / 2.0
    RIVER_LINE[1][1] = center_lon + g_span / 2.0
    
    FAULT_LINE[0][0] = center_lat
    FAULT_LINE[0][1] = center_lon - g_span / 2.0
    FAULT_LINE[1][0] = center_lat
    FAULT_LINE[1][1] = center_lon + g_span / 2.0

    nodes = []
    edges = []
    
    grid_rows, grid_cols = 6, 6
    lat_step = (l_span * 2.0) / (grid_rows - 1)
    lon_step = (g_span * 2.0) / (grid_cols - 1)
    
    lat_min = center_lat - l_span
    lon_min = center_lon - g_span
    
    # 1. Create nodes in grid
    for r in range(grid_rows):
        for c in range(grid_cols):
            node_id = f"N_{r}_{c}"
            lat = lat_min + r * lat_step
            lon = lon_min + c * lon_step
            
            # Determine Node Type
            # Distribute critical assets
            if r == 1 and c == 1:
                node_type = "HOSPITAL"
                population = 50
                importance = 1.0
            elif r == 4 and c == 4:
                node_type = "HOSPITAL"
                population = 40
                importance = 1.0
            elif r == 0 and c == 3:
                node_type = "ROAD"
                population = 0
                importance = 0.2
            elif r == 5 and c == 2:
                node_type = "ROAD"
                population = 0
                importance = 0.2
            elif (r + c) % 2 == 1:
                node_type = "POPULATION_ZONE"
                # population procedural
                population = int(200 + 300 * generate_noise(lat, lon, 200.0))
                importance = 0.8
            elif (r == 2 and c == 2) or (r == 3 and c == 3):
                # bridges across the river
                node_type = "BRIDGE"
                population = 0
                importance = 0.6
            elif (r == 0 or r == 5 or c == 0 or c == 5):
                node_type = "ROAD"
                population = 0
                importance = 0.3
            else:
                node_type = "JUNCTION"
                population = 0
                importance = 0.2
                
            node = NodeModel(
                id=node_id,
                node_type=node_type,
                lat=lat,
                lon=lon,
                population=population,
                importance=importance,
                p_danger=0.0,
                p_state_correct=1.0,
                status="SAFE",
                last_observed=datetime.now(timezone.utc)
            )
            nodes.append(node)
            
    # 2. Create edges (horizontal and vertical grid connections)
    for r in range(grid_rows):
        for c in range(grid_cols):
            # Horizontal connection
            if c < grid_cols - 1:
                u_id = f"N_{r}_{c}"
                v_id = f"N_{r}_{c+1}"
                
                # Accurate Haversine distance in meters
                lat_avg = lat_min + r * lat_step
                lon_avg = lon_min + c * lon_step
                dist_meters = haversine_distance(lat_avg, lon_avg, lat_avg, lon_avg + lon_step)
                
                # Peripheral roads are primary avenues (faster)
                is_peripheral = (r == 0 or r == grid_rows - 1)
                speed_factor = 1.3 if is_peripheral else 0.8
                
                edge = EdgeModel(
                    id=f"E_{u_id}_{v_id}",
                    source=u_id,
                    target=v_id,
                    distance=dist_meters,
                    confidence=1.0,
                    blocked=False,
                    speed_factor=speed_factor,
                    last_observed=datetime.now(timezone.utc),
                    name=f"Avenue {r+1}"
                )
                edges.append(edge)
                
            # Vertical connection
            if r < grid_rows - 1:
                u_id = f"N_{r}_{c}"
                v_id = f"N_{r+1}_{c}"
                
                # Accurate Haversine distance
                lat_avg = lat_min + r * lat_step
                lon_avg = lon_min + c * lon_step
                dist_meters = haversine_distance(lat_avg, lon_avg, lat_avg + lat_step, lon_avg)
                
                # Peripheral roads are primary avenues (faster)
                is_peripheral = (c == 0 or c == grid_cols - 1)
                speed_factor = 1.3 if is_peripheral else 0.8
                
                edge = EdgeModel(
                    id=f"E_{u_id}_{v_id}",
                    source=u_id,
                    target=v_id,
                    distance=dist_meters,
                    confidence=1.0,
                    blocked=False,
                    speed_factor=speed_factor,
                    last_observed=datetime.now(timezone.utc),
                    name=f"Street {chr(65 + c)}"
                )
                edges.append(edge)
                
    return nodes, edges

def load_osm_xml(file_path: str) -> Tuple[List[NodeModel], List[EdgeModel]]:
    """Loads a real OpenStreetMap XML (.osm) file and parses it into Nodes and Edges."""
    tree = ET.parse(file_path)
    root = tree.getroot()
    
    nodes_map: Dict[str, NodeModel] = {}
    nodes: List[NodeModel] = []
    edges: List[EdgeModel] = []
    
    hospital_count = 0
    shelter_count = 0
    
    # Determine center city to scale population to realistic census figures
    # Mumbai: 1800-4800, Tokyo: 1000-3000, London: 800-2400, SF: 500-1500, Sydney: 400-1200
    # Determine the centroid of the nodes map to map center lat/lon
    c_lats: List[float] = []
    for child in root.findall("node"):
        if "lat" in child.attrib:
            try:
                c_lats.append(float(child.attrib["lat"]))
            except ValueError:
                pass
    c_lat_avg = sum(c_lats) / len(c_lats) if c_lats else 37.7749
    pop_scale = 1.0
    if abs(c_lat_avg - 19.0760) < 1.0: # Mumbai
        pop_scale = 15.0
    elif abs(c_lat_avg - 35.6762) < 1.0: # Tokyo
        pop_scale = 9.0
    elif abs(c_lat_avg - 51.5074) < 1.0: # London
        pop_scale = 7.0
    elif abs(c_lat_avg - 37.7749) < 1.0: # SF
        pop_scale = 4.0
    elif abs(c_lat_avg - -33.8688) < 1.0: # Sydney
        pop_scale = 3.0

    # Cache all node coordinates for hazard parsing
    all_node_coords: Dict[str, Tuple[float, float]] = {}
    for child in root.findall("node"):
        if "lat" in child.attrib and "lon" in child.attrib:
            try:
                all_node_coords[child.attrib.get("id", "")] = (float(child.attrib["lat"]), float(child.attrib["lon"]))
            except ValueError:
                pass
        
    hazard_water: List[Tuple[float, float]] = []
    hazard_coast: List[Tuple[float, float]] = []
    hazard_tall: List[Tuple[float, float]] = []
    
    for child in root.findall("way"):
        tags = {t.attrib["k"]: t.attrib["v"] for t in child.findall("tag")}
        nd_refs = [nd.attrib["ref"] for nd in child.findall("nd")]
        coords = [all_node_coords[ref] for ref in nd_refs if ref in all_node_coords]
        if not coords:
            continue
            
        is_water = (
            tags.get("natural") in ("water", "wetland", "bay", "strait", "coastline", "beach", "shoal") or
            tags.get("waterway") in ("river", "stream", "canal", "drain", "ditch", "tidal", "creek") or
            "water" in tags or
            tags.get("landuse") == "basin"
        )
        if is_water:
            hazard_water.extend(coords)
            
        is_coast = tags.get("natural") in ("coastline", "beach", "bay")
        if is_coast:
            hazard_coast.extend(coords)
        
        levels = tags.get("building:levels", "0")
        try:
            if int(levels) > 4:
                hazard_tall.extend(coords)
        except ValueError:
            pass

    import numpy as np
    from scipy.spatial import cKDTree

    # Build fast KD-Trees for O(log N) proximity lookups (lat/lon to meters approximation)
    def build_tree(coords_list: List[Tuple[float, float]]) -> Optional[Any]:
        if not coords_list:
            return None
        # Quick approx: 1 degree lat = 111km, 1 degree lon = 111km * cos(lat)
        # We can just build the tree in degrees and scale the query distance
        return cKDTree(np.array(coords_list))

    tree_water = build_tree(hazard_water)
    tree_coast = build_tree(hazard_coast)
    tree_tall = build_tree(hazard_tall)
    
    def min_dist_tree(lat: float, lon: float, tree: Optional[Any]) -> float:
        if tree is None:
            return 999999.0
        # Quick scale for lon to approx degrees to meters (we use the node's lat for cos scale)
        dist_deg, _ = tree.query([lat, lon])
        # Very rough fallback distance in meters
        from backend.config_params.parameters import params
        return dist_deg * getattr(params, 'degrees_to_meters', 111000.0)

    for child in root.findall("node"):
        if "lat" not in child.attrib or "lon" not in child.attrib:
            continue
        try:
            lat = float(child.attrib["lat"])
            lon = float(child.attrib["lon"])
        except ValueError:
            continue
        n_id = child.attrib.get("id", "unknown")
        
        # Parse OSM tags
        tags = {t.attrib["k"]: t.attrib["v"] for t in child.findall("tag")}
        
        is_bridge_flag = False
        name = tags.get("name", "").lower()
        if tags.get("highway") == "bridge" or tags.get("bridge") == "yes" or "bridge" in tags or "flyover" in name or "link" in name:
            is_bridge_flag = True
        
        node_type = "ROAD"
        population = 0
        importance = 0.2
        
        if "amenity" in tags:
            if tags["amenity"] == "hospital":
                # Limit to 12 hospitals to prevent dashboard visual clutter
                if hospital_count < 12:
                    node_type = "HOSPITAL"
                    importance = 1.0
                    population = int(50 * pop_scale)
                    hospital_count += 1
            elif tags["amenity"] == "shelter":
                # Start with 0 preplaced shelters (safehouses) based on user configuration
                pass
        elif "highway" in tags:
            if tags["highway"] == "motorway_junction":
                node_type = "JUNCTION"
            elif tags["highway"] == "bridge" or tags.get("bridge") == "yes":
                node_type = "BRIDGE"
                importance = 0.6
        elif "landuse" in tags and tags["landuse"] == "residential":
            node_type = "POPULATION_ZONE"
            population = int(250 * pop_scale)
            importance = 0.8
            
        node = NodeModel(
            id=n_id,
            node_type=node_type,
            lat=lat,
            lon=lon,
            population=population,
            importance=importance,
            p_danger=0.0,
            p_state_correct=1.0,
            status="SAFE",
            last_observed=datetime.now(timezone.utc)
        )
        node.is_bridge = is_bridge_flag
        # Calculate proximity distances (meters)
        node.dist_to_water = min_dist_tree(lat, lon, tree_water)
        node.dist_to_coast = min_dist_tree(lat, lon, tree_coast)
        node.is_coastal = (node.dist_to_coast < 200.0)
        node.is_tall_building_zone = min_dist_tree(lat, lon, tree_tall) < 100.0 # within 100m
        
        nodes_map[n_id] = node
        nodes.append(node)
        
    # Parse ways (roads/edges)
    for child in root.findall("way"):
        w_id = child.attrib["id"]
        tags = {t.attrib["k"]: t.attrib["v"] for t in child.findall("tag")}
        
        # Only parse traversable highways
        if "highway" not in tags:
            continue
            
        highway_type = tags.get("highway", "residential")
        # Filter for major arterial and connected residential roads to cover the full Mumbai peninsula cleanly
        if highway_type not in ("motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link", "residential", "living_street", "unclassified"):
            continue
            
        nd_refs = [nd.attrib["ref"] for nd in child.findall("nd")]
        
        # Mark only the midpoint of a bridge way as BRIDGE node type to avoid cluttering map
        is_bridge = tags.get("bridge") == "yes" or tags.get("highway") == "bridge" or "bridge" in tags
        way_name_raw = tags.get("name", "Unnamed Road")
        way_name = way_name_raw.lower()
        is_coastal_way = "coast" in way_name or "marine" in way_name or "drive" in way_name or "sea" in way_name or "beach" in way_name or "promenade" in way_name or "worli" in way_name or "chowpatty" in way_name
        
        if is_bridge and len(nd_refs) > 0:
            mid_idx = len(nd_refs) // 2
            mid_id = nd_refs[mid_idx]
            if mid_id in nodes_map:
                nodes_map[mid_id].node_type = "BRIDGE"
                nodes_map[mid_id].importance = max(nodes_map[mid_id].importance, 0.6)
                nodes_map[mid_id].is_bridge = True
        
        # Create edges between sequential nodes in the way
        # Also collect all node positions along the way for accurate road-shape geometry
        way_node_positions = [
            [nodes_map[nid].lat, nodes_map[nid].lon]
            for nid in nd_refs if nid in nodes_map
        ]
        
        for i in range(len(nd_refs) - 1):
            u_id = nd_refs[i]
            v_id = nd_refs[i+1]
            
            if u_id in nodes_map and v_id in nodes_map:
                u_node = nodes_map[u_id]
                v_node = nodes_map[v_id]
                
                # Check endpoints for coastal attributes
                is_coastal_edge = is_coastal_way or u_node.is_coastal or v_node.is_coastal
                is_bridge_edge = is_bridge or u_node.is_bridge or v_node.is_bridge
                
                # Fully accurate Haversine distance calculation
                dist = haversine_distance(u_node.lat, u_node.lon, v_node.lat, v_node.lon)
                
                # Filter out unrealistically long edges (like ferry routes over ocean) unless they are bridges
                if dist > 800.0 and not is_bridge_edge:
                    continue
                
                # Determine speed limit based on highway type
                speed_factor = 1.0
                if highway_type in ("motorway", "trunk", "primary"):
                    speed_factor = 1.5
                elif highway_type in ("secondary", "tertiary"):
                    speed_factor = 1.0
                else:
                    speed_factor = 0.6  # narrow streets
                
                is_highway = highway_type in ("motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link")
                
                edge = EdgeModel(
                    id=f"E_{w_id}_{i}",
                    source=u_id,
                    target=v_id,
                    distance=dist,
                    confidence=1.0,
                    blocked=False,
                    speed_factor=speed_factor,
                    last_observed=datetime.now(timezone.utc),
                    name=way_name_raw
                )
                edge.is_highway = is_highway
                # Set highway and elevated attribute on nodes
                u_node.is_highway = is_highway
                v_node.is_highway = is_highway
                if is_highway or is_bridge_edge:
                    u_node.is_elevated = True
                    v_node.is_elevated = True

                edge.is_coastal = is_coastal_edge
                edge.is_bridge = is_bridge_edge
                # Geometry: slice of the way shape from u_id to v_id for accurate road drawing
                try:
                    # Precompute lookup dictionary for O(1) coordinate index lookups
                    nd_ref_index = {ref_id: ref_idx for ref_idx, ref_id in enumerate(nd_refs)}
                    u_pos = nd_ref_index[u_id]
                    v_pos = nd_ref_index[v_id]
                    shape_slice = [
                        [nodes_map[nd_refs[k]].lat, nodes_map[nd_refs[k]].lon]
                        for k in range(min(u_pos, v_pos), max(u_pos, v_pos) + 1)
                        if nd_refs[k] in nodes_map
                    ]
                    edge.geometry = shape_slice if len(shape_slice) >= 2 else [
                        [u_node.lat, u_node.lon], [v_node.lat, v_node.lon]
                    ]
                except (KeyError, IndexError):
                    edge.geometry = [[u_node.lat, u_node.lon], [v_node.lat, v_node.lon]]
                edges.append(edge)
                
    # Build a temp graph to find the largest connected component and simplify it
    import networkx as nx
    g_temp = nx.Graph()
    edge_registry = {}
    for edge in edges:
        u, v = edge.source, edge.target
        if u not in nodes_map or v not in nodes_map:
            continue
        key = tuple(sorted((u, v)))
        if key in edge_registry:
            if edge.distance < edge_registry[key].distance:
                edge_registry[key] = edge
        else:
            edge_registry[key] = edge

    g_temp.add_nodes_from(nodes_map.keys())
    g_temp.add_edges_from((k[0], k[1]) for k in edge_registry.keys())

    components = sorted(nx.connected_components(g_temp), key=len, reverse=True)
    largest_component_nodes = components[0] if components else set()
    g_sub = g_temp.subgraph(largest_component_nodes).copy()

    # Simplify degree-2 nodes (collapse straight lines along streets to keep intersection junctions)
    nodes_to_keep = set()
    for n_id, node in nodes_map.items():
        if node.node_type in ("HOSPITAL", "SHELTER", "POPULATION_ZONE"):
            nodes_to_keep.add(n_id)
            # Set haven capacity — treat as staging areas, not fixed containers
            # Capacity resets every 30 steps as civilians move onward (staging model)
            if node.node_type == "SHELTER":
                setattr(node, "capacity", 8000)
                setattr(node, "occupants", 0)
                setattr(node, "is_staging", True)
            elif node.node_type == "HOSPITAL":
                setattr(node, "capacity", 4000)
                setattr(node, "occupants", 0)
                setattr(node, "is_staging", True)

    deg2_nodes = [n for n in g_sub.nodes() if g_sub.degree(n) == 2 and n not in nodes_to_keep]
    visited = set()
    simplified_edges = []
    nodes_to_remove = set()

    for n in deg2_nodes:
        if n in visited or g_sub.degree(n) != 2:
            continue

        n1, n2 = list(g_sub.neighbors(n))

        # Trace direction 1
        curr = n1
        prev = n
        path_dir1 = []
        while g_sub.degree(curr) == 2 and curr not in nodes_to_keep and curr != n:
            path_dir1.append(curr)
            try:
                nxt = [nbr for nbr in g_sub.neighbors(curr) if nbr != prev][0]
            except IndexError:
                break
            prev = curr
            curr = nxt
        end1 = curr

        # Trace direction 2
        path_dir2 = []
        end2 = n2
        if end1 != n:
            curr = n2
            prev = n
            while g_sub.degree(curr) == 2 and curr not in nodes_to_keep and curr != n:
                path_dir2.append(curr)
                try:
                    nxt = [nbr for nbr in g_sub.neighbors(curr) if nbr != prev][0]
                except IndexError:
                    break
                prev = curr
                curr = nxt
            end2 = curr
        else:
            end2 = end1

        if end1 == end2:
            continue

        full_path = [end1] + list(reversed(path_dir1)) + [n] + path_dir2 + [end2]

        for node in path_dir1 + [n] + path_dir2:
            visited.add(node)
            nodes_to_remove.add(node)

        total_dist = 0.0
        speeds = []
        is_coastal = False
        is_bridge = False
        valid = True

        for i in range(len(full_path) - 1):
            u_p, v_p = full_path[i], full_path[i+1]
            key_p = tuple(sorted((u_p, v_p)))
            if key_p in edge_registry:
                e_p = edge_registry[key_p]
                total_dist += e_p.distance
                speeds.append(e_p.speed_factor)
                if e_p.is_coastal:
                    is_coastal = True
                if e_p.is_bridge:
                    is_bridge = True
            else:
                valid = False
                break

        if valid:
            avg_speed = sum(speeds) / len(speeds) if speeds else 1.0
            
            # Stitch the actual original geometries along full_path
            stitched_geometry = []
            for k in range(len(full_path) - 1):
                u_seg, v_seg = full_path[k], full_path[k+1]
                key_seg = tuple(sorted((u_seg, v_seg)))
                if key_seg in edge_registry:
                    e_seg = edge_registry[key_seg]
                    geom = getattr(e_seg, "geometry", None)
                    if not geom:
                        geom = [[nodes_map[u_seg].lat, nodes_map[u_seg].lon],
                                [nodes_map[v_seg].lat, nodes_map[v_seg].lon]]
                    
                    # Align geometry with traversal direction
                    if e_seg.source == u_seg:
                        coords = geom
                    else:
                        coords = list(reversed(geom))
                    
                    for idx, coord in enumerate(coords):
                        if idx == 0 and stitched_geometry:
                            continue  # avoid duplicating endpoint
                        stitched_geometry.append(coord)
            
            if not stitched_geometry:
                stitched_geometry = [[nodes_map[end1].lat, nodes_map[end1].lon],
                                     [nodes_map[end2].lat, nodes_map[end2].lon]]

            # Collect names from stitched segments to carry over to simplified edges
            segment_names = []
            for k in range(len(full_path) - 1):
                u_seg, v_seg = full_path[k], full_path[k+1]
                key_seg = tuple(sorted((u_seg, v_seg)))
                if key_seg in edge_registry:
                    e_name = edge_registry[key_seg].name
                    if e_name and e_name != "Unnamed Road" and e_name not in segment_names:
                        segment_names.append(e_name)
            
            simp_name = segment_names[0] if segment_names else "Unnamed Road"

            simplified_edge = EdgeModel(
                id=f"E_simp_{end1}_{end2}",
                source=end1,
                target=end2,
                distance=total_dist,
                confidence=1.0,
                blocked=False,
                speed_factor=avg_speed,
                last_observed=datetime.now(timezone.utc),
                name=simp_name
            )
            simplified_edge.is_coastal = is_coastal
            simplified_edge.is_bridge = is_bridge
            simplified_edge.geometry = stitched_geometry
            simplified_edges.append(simplified_edge)

    # Remove simplified nodes and replace with simplified edges
    g_sub.remove_nodes_from(nodes_to_remove)

    final_nodes_map = {n_id: nodes_map[n_id] for n_id in g_sub.nodes() if n_id in nodes_map}
    final_edges = []

    # Add remaining original edges
    for u, v in g_sub.edges():
        key = tuple(sorted((u, v)))
        if key in edge_registry:
            e = edge_registry[key]
            # Keep original way geometry if already set, only fallback if missing.
            if not getattr(e, "geometry", None) or len(e.geometry) < 2:
                e.geometry = [[nodes_map[e.source].lat, nodes_map[e.source].lon],
                              [nodes_map[e.target].lat, nodes_map[e.target].lon]]
            final_edges.append(e)

    # Add simplified edges
    final_edges.extend(simplified_edges)

    nodes = list(final_nodes_map.values())
    edges = final_edges
    largest_nodes = nodes

    # Dynamically position RIVER_LINE and FAULT_LINE across the city bounding box
    if largest_nodes:
        lats = [n.lat for n in largest_nodes]
        lons = [n.lon for n in largest_nodes]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        mid_lat = (min_lat + max_lat) / 2.0
        # mid_lon = (min_lon + max_lon) / 2.0
        
        RIVER_LINE[0] = [min_lat, min_lon]
        RIVER_LINE[1] = [max_lat, max_lon]
        FAULT_LINE[0] = [mid_lat, min_lon]
        FAULT_LINE[1] = [mid_lat, max_lon]

    # Ensure we have enough hospitals (target 8) spread across the city
    # [REMOVED FOR MANUAL DEPLOYMENT]

    # Ensure we have enough shelters (target 6) spread across the city
    # [REMOVED FOR MANUAL DEPLOYMENT]

    # Ensure we have a sufficient number of population zones for the simulation (target 120)
    existing_pop_zones = [n for n in nodes if n.node_type == "POPULATION_ZONE" and n.population > 0]
    if len(existing_pop_zones) < 120:
        import random
        random.seed(42)  # stable seeding
        pop_candidates = [n for n in largest_nodes if n.node_type == "ROAD"]
        
        # Shuffle candidates to get a random spread
        random.shuffle(pop_candidates)
        
        hospitals_and_shelters = [n for n in nodes if n.node_type in ("HOSPITAL", "SHELTER")]
        selected_zones = list(existing_pop_zones)
        for candidate in pop_candidates:
            if len(selected_zones) >= 120:
                break
            
            # Enforce 250m spatial spacing (approx 0.0022 degrees) from other zones
            too_close = False
            for existing in selected_zones:
                from backend.config_params.parameters import params
                threshold_deg = getattr(params, 'spatial_spacing_threshold_deg', 0.0022)
                dist = math.hypot(candidate.lat - existing.lat, candidate.lon - existing.lon)
                if dist < threshold_deg:
                    too_close = True
                    break
            
            if not too_close:
                for existing in hospitals_and_shelters:
                    from backend.config_params.parameters import params
                    threshold_deg = getattr(params, 'spatial_spacing_threshold_deg', 0.0022)
                    dist = math.hypot(candidate.lat - existing.lat, candidate.lon - existing.lon)
                    if dist < threshold_deg:
                        too_close = True
                        break
            
            if not too_close:
                candidate.node_type = "POPULATION_ZONE"
                candidate.population = int((100 + 220 * abs(generate_noise(candidate.lat, candidate.lon, 100.0))) * pop_scale)
                candidate.importance = 0.8
                selected_zones.append(candidate)

    # Note: BRIDGE and JUNCTION nodes are transit-only corridors in all cities.
    # We do not assign stranded populations to them to ensure rescue teams focus
    # exclusively on residential POPULATION_ZONE neighborhoods.
    for n in largest_nodes:
        if n.node_type in ("BRIDGE", "JUNCTION"):
            n.population = 0

    return nodes, edges


def download_osm_data(lat: float, lon: float, filepath: str, span: float = 0.006, lat_span: Optional[float] = None, lon_span: Optional[float] = None) -> None:
    """Downloads a targeted slice of OSM road network XML centered at (lat, lon) using Overpass QL."""
    l_span = lat_span if lat_span is not None else span
    g_span = lon_span if lon_span is not None else span
    left = lon - g_span
    bottom = lat - l_span
    right = lon + g_span
    top = lat + l_span
    
    # Target highways, hospitals, and shelters (remove massive water and building layers to ensure fast, reliable downloads)
    ql_query = f"""[out:xml][timeout:180];
(
  way["highway"]({bottom},{left},{top},{right});
  node["amenity"="hospital"]({bottom},{left},{top},{right});
  node["amenity"="shelter"]({bottom},{left},{top},{right});
);
(._;>;);
out body;"""

    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
    ]
    
    # Ensure parent directories exist
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    import urllib.parse
    import urllib.request
    import time
    post_data = urllib.parse.urlencode({'data': ql_query}).encode('utf-8')
    
    last_exception = None
    for url in endpoints:
        print(f"Downloading filtered city road network from Overpass QL: {url}")
        
        # Query and download with urllib User-Agent to bypass Apache 406 blocks
        req = urllib.request.Request(
            url,
            data=post_data,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            method='POST'
        )
        
        try:
            # 10-second timeout per endpoint for fast fallback if Overpass is busy
            with urllib.request.urlopen(req, timeout=10) as response, open(filepath, 'wb') as out_file:
                out_file.write(response.read())
            print(f"OSM road data successfully cached at {filepath}")
            return  # Success!
        except Exception as e:
            print(f"Failed downloading from {url}: {e}")
            last_exception = e
            time.sleep(2)
            
    # If all endpoints fail, throw the last exception
    raise last_exception

