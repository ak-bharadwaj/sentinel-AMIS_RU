import os

class Settings:
    # Database Configuration
    DB_ENGINE: str = os.getenv("DB_ENGINE", "sqlite")  # "sqlite" or "postgres"
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "sqlite:///./sentinel.db" if DB_ENGINE == "sqlite" else "postgresql://postgres:postgres@localhost:5432/sentinel"
    )
    
    # Simulation Parameters
    TIMESTEP_DURATION: int = 60  # seconds (1 minute)
    SURVIVAL_DECAY_RATE: float = 0.0005  # gamma, decay rate of survivors in danger zones per minute
    OBSERVATION_RELIABILITY: float = 0.9  # eta, reliability of scout reports
    KNOWLEDGE_DECAY_RATE: float = 0.05  # lambda, knowledge decay rate per step
    
    # Agent Parameters
    SCOUT_SPEED: float = 15.0  # m/s (54 km/h)
    RESCUE_SPEED: float = 10.0  # m/s (36 km/h)
    
    # Grid/Procedural Generation parameters
    GRID_SIZE_LAT: float = 0.02  # span of latitude for procedural graph
    GRID_SIZE_LON: float = 0.02  # span of longitude for procedural graph

settings = Settings()
