from pydantic import BaseModel, Field

class CustomLocation(BaseModel):
    lat: float
    lon: float
    label: str = ""

class SimulationStartSchema(BaseModel):
    baseline_type: str = "AMIS-RU"  # "AMIS-RU", "SGA-RA", "PSA-RA"
    disaster_type: str = "FLOOD"  # "FLOOD" or "EARTHQUAKE"
    corruption_level: float = 0.6  # 0.3, 0.6, 0.9
    center_lat: float = 37.7749
    center_lon: float = -122.4194
    span: float = 0.06  # Bounding box span
    lat_span: float = 0.06
    lon_span: float = 0.06
    map_mode: str = "REAL"  # "REAL" or "SYNTHETIC"
    num_scouts: int = 3
    num_rescues: int = 3
    num_zodiacs: int = 0
    num_helicopters: int = 0
    num_trucks: int = 0
    num_cars: int = 0
    magnitude_mw: float = 6.5  # Seismic / meteorological intensity parameters
    env_mode: str = "LIVE"  # "LIVE" or "HISTORICAL"
    historical_preset: str | None = None
    custom_shelters: list[CustomLocation] = Field(default_factory=list)   # [{"lat":..., "lon":..., "label":"..."}]
    custom_hospitals: list[CustomLocation] = Field(default_factory=list)  # [{"lat":..., "lon":..., "label":"..."}]

class AirdropRequest(BaseModel):
    node_id: str
    amount: float = 50.0

