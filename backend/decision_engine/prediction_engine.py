import math
import networkx as nx
from typing import Dict, Any, List
from datetime import datetime
from backend.disaster.cyclone import CycloneModule
from backend.disaster.earthquake import bssa14_pga

class PredictionEngine:
    """
    Forecasts disaster hazards (flood water levels, wind speed damage,
    and earthquake aftershock decay models) at T+15, T+30, and T+60 minutes.
    Propagates uncertainty using mean, variance, confidence, and source attribution.
    """
    _forecast_cache = {}

    @staticmethod
    def forecast_flood(belief_graph: nx.Graph, rainfall: float, duration_minutes: float) -> Dict[str, Dict[str, float]]:
        """
        Forecasts water levels at nodes after duration_minutes.
        Uses a simplified accumulation and gravity-driven hydrologic spread.
        Propagates uncertainty: variance increases with time, confidence decays.
        """
        forecasted_data = {}
        steps = int(math.ceil(duration_minutes / 10.0))  # 10-minute simulation steps
        
        # Clone current water levels
        water_levels = {n_id: data.get("water_level", 0.0) for n_id, data in belief_graph.nodes(data=True)}
        
        # Run steps
        for _ in range(steps):
            new_levels = {}
            for n_id, data in belief_graph.nodes(data=True):
                eff_elev = data.get("effective_elevation", data.get("elevation", 10.0))
                is_tunnel = data.get("is_tunnel", False)
                is_coastal = data.get("is_coastal", False)
                coastal_mult = 2.5 if is_coastal else 1.0
                tunnel_mult = 2.5 if is_tunnel else 1.0
                twi_factor = data.get("drainage_accumulation_rate", 1.0)
                drain_capacity = data.get("drain_capacity", 0.05)
                
                accum_rate = max(0.05, 1.0 - (eff_elev / 120.0)) * coastal_mult * tunnel_mult
                water_gain = accum_rate * twi_factor * rainfall * 1.8 * (10.0 / 60.0) # Scaled for 10m step
                drainage_loss = drain_capacity * (10.0 / 60.0) if rainfall < 2.0 else 0.0
                new_levels[n_id] = max(0.0, water_levels[n_id] + water_gain - drainage_loss)

            # Gravity spread
            outflows = {n_id: [] for n_id in belief_graph.nodes}
            for u, v in belief_graph.edges:
                u_data = belief_graph.nodes[u]
                v_data = belief_graph.nodes[v]
                w_u = new_levels[u]
                w_v = new_levels[v]
                elev_u = u_data.get("effective_elevation", u_data.get("elevation", 10.0))
                elev_v = v_data.get("effective_elevation", v_data.get("elevation", 10.0))
                
                head_u = elev_u + w_u
                head_v = elev_v + w_v
                head_diff = head_u - head_v
                
                if head_diff > 0.0 and w_u > 0.0:
                    outflows[u].append((v, head_diff * 0.05))
                elif head_diff < 0.0 and w_v > 0.0:
                    outflows[v].append((u, -head_diff * 0.05))
            
            deltas = {n_id: 0.0 for n_id in belief_graph.nodes}
            for u, flows in outflows.items():
                if not flows:
                    continue
                total_outflow = sum(f[1] for f in flows)
                w_u = new_levels[u]
                scale = 1.0
                if total_outflow > w_u:
                    scale = w_u / total_outflow
                for v, flow in flows:
                    scaled_flow = flow * scale
                    deltas[u] -= scaled_flow
                    deltas[v] += scaled_flow
            
            for n_id, delta in deltas.items():
                new_levels[n_id] += delta
            
            water_levels = new_levels

        # Calculate statistics
        for n_id, data in belief_graph.nodes(data=True):
            mean_wl = max(0.0, water_levels[n_id])
            init_conf = data.get("p_state_correct", 1.0)
            
            # Uncertainty propagates: variance grows linearly with duration
            base_var = 0.02 * (1.0 - init_conf)
            variance = base_var + 0.005 * duration_minutes
            
            # Confidence decays over time
            decayed_conf = init_conf * math.exp(-0.012 * duration_minutes)
            
            forecasted_data[n_id] = {
                "mean": mean_wl,
                "variance": variance,
                "confidence": max(0.05, min(1.0, decayed_conf))
            }

        return forecasted_data

    @staticmethod
    def forecast_cyclone(
        belief_graph: nx.Graph,
        cyclone_module: CycloneModule,
        duration_minutes: float
    ) -> Dict[str, Dict[str, Any]]:
        """
        Forecasts cyclone wind speeds and damage probabilities at nodes after duration_minutes.
        """
        res = {}
        hours = duration_minutes / 60.0
        
        # Calculate eye movement
        dist_moved = cyclone_module.track_speed_kmh * hours
        heading_rad = math.radians(cyclone_module.track_heading_deg)
        
        eye_lat = cyclone_module.eye_lat or 0.0
        eye_lon = cyclone_module.eye_lon or 0.0
        
        forecast_eye_lat = eye_lat + (dist_moved * math.cos(heading_rad)) / 111.0
        forecast_eye_lon = eye_lon + (dist_moved * math.sin(heading_rad)) / (111.0 * max(0.01, math.cos(math.radians(forecast_eye_lat))))
        
        from backend.world_model.graph_builder import haversine_distance
        
        for n_id, data in belief_graph.nodes(data=True):
            lat = data.get("lat")
            lon = data.get("lon")
            if lat is None or lon is None:
                continue
            
            dist_km = haversine_distance(lat, lon, forecast_eye_lat, forecast_eye_lon)
            wind_speed = cyclone_module.get_holland_wind(dist_km, lat)
            
            dist_to_coast_m = data.get("dist_to_coast")
            if dist_to_coast_m is not None and dist_to_coast_m > 0:
                dist_to_coast_km = dist_to_coast_m / 1000.0
                inland_decay = math.exp(-0.08 * dist_to_coast_km)
                wind_speed *= inland_decay

            # Estimated danger progression
            gust_chance = max(0.0, min(1.0, wind_speed / 1000.0))
            current_danger = data.get("p_danger", 0.0)
            time_factor = duration_minutes / 10.0
            forecast_danger = min(1.0, current_danger + (gust_chance * current_danger * 0.1 * time_factor))
            
            # Propagate uncertainty
            init_conf = data.get("p_state_correct", 1.0)
            base_var = 0.01 * (1.0 - init_conf)
            # Wind speed forecasting uncertainty grows
            wind_variance = base_var * 100.0 + 2.0 * duration_minutes
            danger_variance = base_var + 0.003 * duration_minutes
            decayed_conf = init_conf * math.exp(-0.01 * duration_minutes)

            res[n_id] = {
                "wind_speed_mean": wind_speed,
                "wind_speed_variance": wind_variance,
                "p_danger_mean": forecast_danger,
                "p_danger_variance": danger_variance,
                "confidence": max(0.05, min(1.0, decayed_conf))
            }
        return res

    @staticmethod
    def forecast_earthquake_aftershocks(
        belief_graph: nx.Graph,
        magnitude_mw: float,
        epicenter_lat: float,
        epicenter_lon: float,
        time_since_mainshock_minutes: float,
        forecast_offset_minutes: float
    ) -> Dict[str, Dict[str, Any]]:
        """
        Forecasts earthquake aftershock damage probability using Omori's Law decay.
        """
        c_param = 1.0  # shift parameter
        p_param = 1.1  # decay exponent
        
        # Aftershock rate factor
        rate_t0 = 1.0 / ((time_since_mainshock_minutes + c_param) ** p_param)
        rate_t_future = 1.0 / ((time_since_mainshock_minutes + forecast_offset_minutes + c_param) ** p_param)
        
        decay_multiplier = rate_t_future / max(1e-6, rate_t0)
        
        forecasted_data = {}
        
        for n_id, data in belief_graph.nodes(data=True):
            current_danger = data.get("p_danger", 0.0)
            forecasted_danger = max(0.05, current_danger * decay_multiplier)
            
            # Propagate uncertainty
            init_conf = data.get("p_state_correct", 1.0)
            base_var = 0.015 * (1.0 - init_conf)
            danger_variance = base_var + 0.004 * forecast_offset_minutes
            decayed_conf = init_conf * math.exp(-0.015 * forecast_offset_minutes)

            forecasted_data[n_id] = {
                "p_danger_mean": forecasted_danger,
                "p_danger_variance": danger_variance,
                "confidence": max(0.05, min(1.0, decayed_conf))
            }
            
        return forecasted_data

    @classmethod
    def get_forecasts(
        cls,
        belief_graph: nx.Graph,
        disaster_type: str,
        disaster_module: Any,
        time_since_start_minutes: float = 0.0
    ) -> Dict[Any, Dict[str, Any]]:
        """
        Generates forecasts at T+15, T+30, and T+60 minutes.
        Returns a dict mapping interval_minutes -> node_id -> forecast_data.
        Supports both integer keys (15, 30, 60) and string keys ('t15', 't30', 't60') for EGL compatibility.
        """
        cache_key = (disaster_type, int(time_since_start_minutes) // 5)
        if cache_key in cls._forecast_cache:
            return cls._forecast_cache[cache_key]

        intervals = [15, 30, 60]
        forecasts = {}
        
        for interval in intervals:
            forecasts[interval] = {}
            # Double-map to string keys to resolve EGL/DAP key mismatch!
            forecasts[f"t{interval}"] = forecasts[interval]
            
            if disaster_type.upper() == "FLOOD":
                rainfall = getattr(disaster_module, "rainfall", 0.7)
                flood_forecasts = cls.forecast_flood(belief_graph, rainfall, interval)
                for n_id in belief_graph.nodes:
                    node_data = flood_forecasts.get(n_id, {"mean": 0.0, "variance": 0.0, "confidence": 1.0})
                    forecasts[interval][n_id] = {
                        "water_level": node_data["mean"],
                        "mean": node_data["mean"],
                        "variance": node_data["variance"],
                        "confidence": node_data["confidence"],
                        "status": "FLOODED" if node_data["mean"] > 1.2 else "SAFE",
                        "prediction_source": "Gravity-Hydrologic Flow Model"
                    }
                    
            elif disaster_type.upper() in ("CYCLONE", "WIND"):
                cyclone_data = cls.forecast_cyclone(belief_graph, disaster_module, interval)
                for n_id in belief_graph.nodes:
                    node_data = cyclone_data.get(n_id, {
                        "wind_speed_mean": 0.0,
                        "wind_speed_variance": 0.0,
                        "p_danger_mean": 0.0,
                        "p_danger_variance": 0.0,
                        "confidence": 1.0
                    })
                    forecasts[interval][n_id] = {
                        "wind_speed": node_data["wind_speed_mean"],
                        "wind_speed_mean": node_data["wind_speed_mean"],
                        "wind_speed_variance": node_data["wind_speed_variance"],
                        "p_danger": node_data["p_danger_mean"],
                        "mean": node_data["p_danger_mean"],
                        "variance": node_data["p_danger_variance"],
                        "confidence": node_data["confidence"],
                        "status": "DANGER" if node_data["p_danger_mean"] > 0.85 else "SAFE",
                        "prediction_source": "Holland Wind-Decay Model"
                    }
                    
            elif disaster_type.upper() == "EARTHQUAKE":
                mag = getattr(disaster_module, "magnitude_mw", 6.5)
                epi_lat = getattr(disaster_module, "epicenter_lat", 0.0) or 0.0
                epi_lon = getattr(disaster_module, "epicenter_lon", 0.0) or 0.0
                eq_forecasts = cls.forecast_earthquake_aftershocks(
                    belief_graph, mag, epi_lat, epi_lon, time_since_start_minutes, interval
                )
                for n_id in belief_graph.nodes:
                    node_data = eq_forecasts.get(n_id, {"p_danger_mean": 0.0, "p_danger_variance": 0.0, "confidence": 1.0})
                    forecasts[interval][n_id] = {
                        "p_danger": node_data["p_danger_mean"],
                        "mean": node_data["p_danger_mean"],
                        "variance": node_data["p_danger_variance"],
                        "confidence": node_data["confidence"],
                        "status": "DANGER" if node_data["p_danger_mean"] > 0.8 else "SAFE",
                        "prediction_source": "Omori Aftershock Decay Model"
                    }
            else:
                # Fallback for unrecognized disaster type
                for n_id, data in belief_graph.nodes(data=True):
                    init_conf = data.get("p_state_correct", 1.0)
                    decayed_conf = init_conf * math.exp(-0.01 * interval)
                    forecasts[interval][n_id] = {
                        "p_danger": data.get("p_danger", 0.0),
                        "mean": data.get("p_danger", 0.0),
                        "variance": 0.02 * (1.0 - init_conf) + 0.005 * interval,
                        "confidence": max(0.05, min(1.0, decayed_conf)),
                        "status": data.get("status", "SAFE"),
                        "prediction_source": "Static Extrapolation Model"
                    }
        cls._forecast_cache[cache_key] = forecasts
        return forecasts
