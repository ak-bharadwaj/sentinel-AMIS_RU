from fastapi import APIRouter
from backend.simulation.engine import simulation_engine

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/metrics")
def get_metrics():
    """Returns the time-series logs of the currently running simulation."""
    return {
        "active_baseline": simulation_engine.active_baseline,
        "total_survivors_saved": simulation_engine.total_survivors_saved,
        "initial_population": simulation_engine.initial_total_population,
        "simulation_time": simulation_engine.simulation_time,
        "tide_phase": getattr(simulation_engine, "tide_phase", "LOW TIDE"),
        "disaster_type": simulation_engine.disaster_type,
        "weather": getattr(simulation_engine, "weather", None),
        "history": simulation_engine.history,
        "briefing": getattr(simulation_engine, "latest_briefing", None),
        "telemetry": {
            "rainfall_rate_mm_hr": getattr(simulation_engine, "sensor_rainfall_rate", 0.0),
            "water_level_m": getattr(simulation_engine, "sensor_water_level_m", 0.0),
            "wind_speed_kmh": getattr(simulation_engine, "sensor_wind_speed_kmh", 0.0),
            "surge_depth_m": getattr(simulation_engine, "sensor_surge_depth_m", 0.0),
            "seismic_pga_g": getattr(simulation_engine, "sensor_seismic_pga_g", 0.0)
        }
    }

@router.get("/export_csv")
def export_aar():
    """Generates an After-Action Report (CSV) of the mission event logs."""
    import io
    from fastapi.responses import StreamingResponse
    import csv

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Mission_Time_Mins", "Operation_Mode", "Weather_Condition", "Survivors_Rescued", "Total_Population", "Map_Coverage_Pct"])
    
    for record in simulation_engine.history:
        writer.writerow([
            record.get("step") or 0,
            simulation_engine.active_baseline,
            getattr(simulation_engine.weather, "value", str(simulation_engine.weather)) if simulation_engine.weather else "CLEAR",
            record.get("survivors_saved") or 0,
            record.get("initial_population") or 0,
            round((record.get("map_confidence") or 0) * 100, 2)
        ])
        
    output.seek(0)
    
    headers = {
        'Content-Disposition': 'attachment; filename="NDMA_AAR_Report.csv"'
    }
    
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)
