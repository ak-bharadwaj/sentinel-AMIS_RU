# Complete, time-based environmental states representing historical milestone moments.
# Enriched with comprehensive validation_targets representing recorded real-world EOC baseline results.
HISTORICAL_PRESETS = {
    "FLOOD": {
        "mumbai_2005": {
            "name": "Mumbai 2005 Super-Flood",
            "description": "Catastrophic monsoon surge with 944mm rainfall and blocked drainage gates.",
            "pop_multiplier": 1.5,
            "validation_targets": {
                "historical_survivors_saved_pct": 35.0,
                "historical_manual_saved_count": 1200,
                "historical_area_covered_pct": 45.0,
                "historical_rescue_time_mins": 120.0,
                "eoc_intelligence_level": "Low (Severe dispatch isolation, zero terrain-awareness)"
            },
            "timeline": {
                0: {
                    "temperature_c": 28.0, "humidity_pct": 98.0, "pressure_hpa": 995.0,
                    "wind_speed_kmh": 18.0, "wind_direction_deg": 260.0, "rainfall_mm_hr": 2.5,
                    "cloud_cover_pct": 100.0, "visibility_m": 1500.0, "surge_depth_m": 0.8,
                    "seismic_pga_g": 0.0, "tide_height_m": 4.2, "tide_phase": "HIGH TIDE",
                    "event": "Monsoonal downpour intensifies over Suburban Mumbai."
                },
                120: {
                    "temperature_c": 26.5, "humidity_pct": 100.0, "pressure_hpa": 992.0,
                    "wind_speed_kmh": 22.0, "wind_direction_deg": 265.0, "rainfall_mm_hr": 38.0,
                    "cloud_cover_pct": 100.0, "visibility_m": 800.0, "surge_depth_m": 1.4,
                    "seismic_pga_g": 0.0, "tide_height_m": 4.9, "tide_phase": "HIGH TIDE",
                    "event": "Mithi River overflows, flooding Kurla and Kalina lowlands. Power grids collapse."
                },
                240: {
                    "temperature_c": 25.0, "humidity_pct": 100.0, "pressure_hpa": 989.0,
                    "wind_speed_kmh": 35.0, "wind_direction_deg": 270.0, "rainfall_mm_hr": 45.0,
                    "cloud_cover_pct": 100.0, "visibility_m": 400.0, "surge_depth_m": 2.1,
                    "seismic_pga_g": 0.0, "tide_height_m": 4.7, "tide_phase": "HIGH TIDE",
                    "event": "Widespread telecom blackout. Landlines and mobile grids down."
                },
                360: {
                    "temperature_c": 26.0, "humidity_pct": 98.0, "pressure_hpa": 994.0,
                    "wind_speed_kmh": 25.0, "wind_direction_deg": 260.0, "rainfall_mm_hr": 48.0,
                    "cloud_cover_pct": 100.0, "visibility_m": 1200.0, "surge_depth_m": 2.8,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.8, "tide_phase": "LOW TIDE",
                    "event": "Airport shut down. SV Road and Western Express Highway completely submerged."
                },
                480: {
                    "temperature_c": 27.0, "humidity_pct": 95.0, "pressure_hpa": 998.0,
                    "wind_speed_kmh": 15.0, "wind_direction_deg": 250.0, "rainfall_mm_hr": 35.0,
                    "cloud_cover_pct": 90.0, "visibility_m": 2500.0, "surge_depth_m": 2.4,
                    "seismic_pga_g": 0.0, "tide_height_m": 2.5, "tide_phase": "LOW TIDE",
                    "event": "Water levels stabilize as rainfall intensity drops slightly."
                },
                600: {
                    "temperature_c": 28.0, "humidity_pct": 92.0, "pressure_hpa": 1001.0,
                    "wind_speed_kmh": 12.0, "wind_direction_deg": 240.0, "rainfall_mm_hr": 30.0,
                    "cloud_cover_pct": 85.0, "visibility_m": 3000.0, "surge_depth_m": 1.8,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.5, "tide_phase": "LOW TIDE",
                    "event": "Drainage outfall gates partially open as tide recedes."
                },
                720: {
                    "temperature_c": 27.5, "humidity_pct": 96.0, "pressure_hpa": 997.0,
                    "wind_speed_kmh": 20.0, "wind_direction_deg": 255.0, "rainfall_mm_hr": 38.0,
                    "cloud_cover_pct": 100.0, "visibility_m": 1000.0, "surge_depth_m": 2.2,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.8, "tide_phase": "HIGH TIDE",
                    "event": "Secondary downpour peaks during high tide. Severe waterlogging."
                },
                840: {
                    "temperature_c": 26.0, "humidity_pct": 98.0, "pressure_hpa": 993.0,
                    "wind_speed_kmh": 28.0, "wind_direction_deg": 260.0, "rainfall_mm_hr": 42.0,
                    "cloud_cover_pct": 100.0, "visibility_m": 600.0, "surge_depth_m": 2.6,
                    "seismic_pga_g": 0.0, "tide_height_m": 4.5, "tide_phase": "HIGH TIDE",
                    "event": "Local landslides reported in suburban Saki Naka hills."
                },
                960: {
                    "temperature_c": 26.5, "humidity_pct": 97.0, "pressure_hpa": 996.0,
                    "wind_speed_kmh": 18.0, "wind_direction_deg": 250.0, "rainfall_mm_hr": 30.0,
                    "cloud_cover_pct": 95.0, "visibility_m": 1800.0, "surge_depth_m": 2.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.2, "tide_phase": "LOW TIDE",
                    "event": "Storm cell shifts north. Heavy rain recedes to steady showers."
                },
                1080: {
                    "temperature_c": 27.0, "humidity_pct": 94.0, "pressure_hpa": 1000.0,
                    "wind_speed_kmh": 14.0, "wind_direction_deg": 240.0, "rainfall_mm_hr": 20.0,
                    "cloud_cover_pct": 80.0, "visibility_m": 2800.0, "surge_depth_m": 1.5,
                    "seismic_pga_g": 0.0, "tide_height_m": 2.1, "tide_phase": "LOW TIDE",
                    "event": "Outfalls opened. Water levels begin gradual recedence."
                },
                1200: {
                    "temperature_c": 27.5, "humidity_pct": 90.0, "pressure_hpa": 1003.0,
                    "wind_speed_kmh": 10.0, "wind_direction_deg": 230.0, "rainfall_mm_hr": 15.0,
                    "cloud_cover_pct": 75.0, "visibility_m": 4000.0, "surge_depth_m": 1.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.8, "tide_phase": "LOW TIDE",
                    "event": "EOC sets up emergency shelters in central schools."
                },
                1320: {
                    "temperature_c": 28.0, "humidity_pct": 88.0, "pressure_hpa": 1006.0,
                    "wind_speed_kmh": 8.0, "wind_direction_deg": 220.0, "rainfall_mm_hr": 8.0,
                    "cloud_cover_pct": 60.0, "visibility_m": 5000.0, "surge_depth_m": 0.6,
                    "seismic_pga_g": 0.0, "tide_height_m": 2.8, "tide_phase": "HIGH TIDE",
                    "event": "Flood waters receding from highway corridors."
                },
                1440: {
                    "temperature_c": 28.5, "humidity_pct": 85.0, "pressure_hpa": 1008.0,
                    "wind_speed_kmh": 6.0, "wind_direction_deg": 210.0, "rainfall_mm_hr": 4.0,
                    "cloud_cover_pct": 40.0, "visibility_m": 8000.0, "surge_depth_m": 0.3,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.5, "tide_phase": "HIGH TIDE",
                    "event": "Rainfall ceases. Clear skies return over suburban peninsula."
                }
            }
        },
        "mumbai_2017": {
            "name": "Mumbai 2017 Monsoon Surge",
            "description": "Severe Monsoonal downpour causing widespread street flooding.",
            "pop_multiplier": 1.1,
            "validation_targets": {
                "historical_survivors_saved_pct": 55.0,
                "historical_manual_saved_count": 850,
                "historical_area_covered_pct": 65.0,
                "historical_rescue_time_mins": 90.0,
                "eoc_intelligence_level": "Medium-Low (Basic rain warnings, poor traffic route adjustments)"
            },
            "timeline": {
                0: {
                    "temperature_c": 28.5, "humidity_pct": 95.0, "pressure_hpa": 1002.0,
                    "wind_speed_kmh": 15.0, "wind_direction_deg": 250.0, "rainfall_mm_hr": 1.5,
                    "cloud_cover_pct": 95.0, "visibility_m": 3000.0, "surge_depth_m": 0.4,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.2, "tide_phase": "HIGH TIDE",
                    "event": "Steady monsoon rainfall rates recorded across southern peninsula."
                },
                20: {
                    "temperature_c": 27.0, "humidity_pct": 98.0, "pressure_hpa": 999.0,
                    "wind_speed_kmh": 20.0, "wind_direction_deg": 255.0, "rainfall_mm_hr": 2.2,
                    "cloud_cover_pct": 100.0, "visibility_m": 1500.0, "surge_depth_m": 0.8,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.8, "tide_phase": "HIGH TIDE",
                    "event": "Severe waterlogging reported at Hindmata and Parel junctions."
                },
                40: {
                    "temperature_c": 27.5, "humidity_pct": 96.0, "pressure_hpa": 1001.0,
                    "wind_speed_kmh": 14.0, "wind_direction_deg": 245.0, "rainfall_mm_hr": 1.8,
                    "cloud_cover_pct": 98.0, "visibility_m": 2200.0, "surge_depth_m": 0.5,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.5, "tide_phase": "LOW TIDE",
                    "event": "Tide shifts to low phase; municipal pumps activated."
                },
                60: {
                    "temperature_c": 28.0, "humidity_pct": 92.0, "pressure_hpa": 1004.0,
                    "wind_speed_kmh": 10.0, "wind_direction_deg": 230.0, "rainfall_mm_hr": 0.8,
                    "cloud_cover_pct": 80.0, "visibility_m": 4000.0, "surge_depth_m": 0.2,
                    "seismic_pga_g": 0.0, "tide_height_m": 2.0, "tide_phase": "LOW TIDE",
                    "event": "Precipitation rates decline; road clearance under way."
                }
            }
        },
        "mumbai_2020": {
            "name": "Mumbai 2020 Urban Deluge",
            "description": "Monsoon rainfall coupled with high tide locks local transit loops.",
            "pop_multiplier": 1.0,
            "validation_targets": {
                "historical_survivors_saved_pct": 70.0,
                "historical_manual_saved_count": 600,
                "historical_area_covered_pct": 80.0,
                "historical_rescue_time_mins": 60.0,
                "eoc_intelligence_level": "Medium (SMS weather alerts, static high-water truck dispatch)"
            },
            "timeline": {
                0: {
                    "temperature_c": 27.5, "humidity_pct": 96.0, "pressure_hpa": 1004.0,
                    "wind_speed_kmh": 12.0, "wind_direction_deg": 240.0, "rainfall_mm_hr": 1.0,
                    "cloud_cover_pct": 90.0, "visibility_m": 4000.0, "surge_depth_m": 0.3,
                    "seismic_pga_g": 0.0, "tide_height_m": 2.8, "tide_phase": "LOW TIDE",
                    "event": "Runoff levels rise slowly on major arterial streets."
                },
                20: {
                    "temperature_c": 26.0, "humidity_pct": 99.0, "pressure_hpa": 1001.0,
                    "wind_speed_kmh": 18.0, "wind_direction_deg": 250.0, "rainfall_mm_hr": 2.5,
                    "cloud_cover_pct": 100.0, "visibility_m": 1200.0, "surge_depth_m": 0.7,
                    "seismic_pga_g": 0.0, "tide_height_m": 4.1, "tide_phase": "HIGH TIDE",
                    "event": "High tide combined with heavy runoff floods Marine Drive promenade."
                },
                40: {
                    "temperature_c": 26.8, "humidity_pct": 97.0, "pressure_hpa": 1003.0,
                    "wind_speed_kmh": 12.0, "wind_direction_deg": 240.0, "rainfall_mm_hr": 1.5,
                    "cloud_cover_pct": 95.0, "visibility_m": 2500.0, "surge_depth_m": 0.5,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.6, "tide_phase": "HIGH TIDE",
                    "event": "Precipitation rates stabilize; minor drainage clearing starts."
                },
                60: {
                    "temperature_c": 27.2, "humidity_pct": 94.0, "pressure_hpa": 1005.0,
                    "wind_speed_kmh": 8.0, "wind_direction_deg": 220.0, "rainfall_mm_hr": 0.5,
                    "cloud_cover_pct": 85.0, "visibility_m": 5000.0, "surge_depth_m": 0.2,
                    "seismic_pga_g": 0.0, "tide_height_m": 2.5, "tide_phase": "LOW TIDE",
                    "event": "Floodwaters begin receding as tide moves to low phase."
                }
            }
        },
        "chennai_2015": {
            "name": "Chennai 2015 Historic Flood",
            "description": "Extreme urban flooding driven by record reservoir discharge.",
            "pop_multiplier": 1.3,
            "validation_targets": {
                "historical_survivors_saved_pct": 42.0,
                "historical_manual_saved_count": 1500,
                "historical_area_covered_pct": 50.0,
                "historical_rescue_time_mins": 110.0,
                "eoc_intelligence_level": "Low (Communication networks down, uncoordinated boat deployments)"
            },
            "timeline": {
                0: {
                    "temperature_c": 26.0, "humidity_pct": 99.0, "pressure_hpa": 998.0,
                    "wind_speed_kmh": 18.0, "wind_direction_deg": 90.0, "rainfall_mm_hr": 2.0,
                    "cloud_cover_pct": 100.0, "visibility_m": 2000.0, "surge_depth_m": 0.6,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.5, "tide_phase": "HIGH TIDE",
                    "event": "Chembarambakkam reservoir outflow increases to 25,000 cusecs."
                },
                20: {
                    "temperature_c": 25.2, "humidity_pct": 100.0, "pressure_hpa": 994.0,
                    "wind_speed_kmh": 25.0, "wind_direction_deg": 95.0, "rainfall_mm_hr": 3.6,
                    "cloud_cover_pct": 100.0, "visibility_m": 600.0, "surge_depth_m": 1.1,
                    "seismic_pga_g": 0.0, "tide_height_m": 4.0, "tide_phase": "HIGH TIDE",
                    "event": "Adyar River breaches banks, inundating South Chennai roads."
                },
                40: {
                    "temperature_c": 25.8, "humidity_pct": 100.0, "pressure_hpa": 996.0,
                    "wind_speed_kmh": 15.0, "wind_direction_deg": 85.0, "rainfall_mm_hr": 2.5,
                    "cloud_cover_pct": 100.0, "visibility_m": 1200.0, "surge_depth_m": 0.9,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.2, "tide_phase": "LOW TIDE",
                    "event": "Airport runway flooded; communications network heavily degraded."
                },
                60: {
                    "temperature_c": 26.5, "humidity_pct": 98.0, "pressure_hpa": 1000.0,
                    "wind_speed_kmh": 10.0, "wind_direction_deg": 80.0, "rainfall_mm_hr": 1.2,
                    "cloud_cover_pct": 95.0, "visibility_m": 3000.0, "surge_depth_m": 0.4,
                    "seismic_pga_g": 0.0, "tide_height_m": 2.2, "tide_phase": "LOW TIDE",
                    "event": "Discharge rates reduced; water levels slowly stabilizing."
                }
            }
        }
    },
    "CYCLONE": {
        "nisarga_2020": {
            "name": "Cyclone Nisarga (2020)",
            "description": "Severe cyclonic storm making landfall near Alibaug/Mumbai south.",
            "pop_multiplier": 1.0,
            "windspeed": 120.0,
            "central_pressure_hpa": 980.0,
            "validation_targets": {
                "historical_survivors_saved_pct": 85.0,
                "historical_manual_saved_count": 2400,
                "historical_area_covered_pct": 90.0,
                "historical_rescue_time_mins": 45.0,
                "eoc_intelligence_level": "High (Pre-emptive warnings, successful early land-side relocation)"
            },
            "timeline": {
                0: {
                    "temperature_c": 26.5, "humidity_pct": 95.0, "pressure_hpa": 990.0,
                    "wind_speed_kmh": 90.0, "wind_direction_deg": 180.0, "rainfall_mm_hr": 1.2,
                    "cloud_cover_pct": 100.0, "visibility_m": 2000.0, "surge_depth_m": 0.8,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.8, "tide_phase": "HIGH TIDE",
                    "event": "Outer rainbands reach Mumbai; coastal evacuations ordered."
                },
                20: {
                    "temperature_c": 25.0, "humidity_pct": 100.0, "pressure_hpa": 982.0,
                    "wind_speed_kmh": 120.0, "wind_direction_deg": 195.0, "rainfall_mm_hr": 2.0,
                    "cloud_cover_pct": 100.0, "visibility_m": 500.0, "surge_depth_m": 1.5,
                    "seismic_pga_g": 0.0, "tide_height_m": 4.5, "tide_phase": "HIGH TIDE",
                    "event": "Landfall near Alibaug; severe coastal storm surge inundates low-lying fisher colonies."
                },
                40: {
                    "temperature_c": 25.5, "humidity_pct": 99.0, "pressure_hpa": 988.0,
                    "wind_speed_kmh": 95.0, "wind_direction_deg": 210.0, "rainfall_mm_hr": 1.5,
                    "cloud_cover_pct": 100.0, "visibility_m": 1200.0, "surge_depth_m": 1.1,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.9, "tide_phase": "LOW TIDE",
                    "event": "Cyclone eye passes; wind speeds begin slow decay."
                },
                60: {
                    "temperature_c": 26.2, "humidity_pct": 96.0, "pressure_hpa": 995.0,
                    "wind_speed_kmh": 60.0, "wind_direction_deg": 225.0, "rainfall_mm_hr": 0.8,
                    "cloud_cover_pct": 98.0, "visibility_m": 3000.0, "surge_depth_m": 0.5,
                    "seismic_pga_g": 0.0, "tide_height_m": 2.8, "tide_phase": "LOW TIDE",
                    "event": "Cyclone system tracks inland and weakens; core gales subside."
                }
            }
        },
        "tauktae_2021": {
            "name": "Cyclone Tauktae (2021)",
            "description": "Extremely severe cyclonic storm bringing massive coastal surge and heavy rains.",
            "pop_multiplier": 1.1,
            "validation_targets": {
                "historical_survivors_saved_pct": 65.0,
                "historical_manual_saved_count": 1800,
                "historical_area_covered_pct": 70.0,
                "historical_rescue_time_mins": 75.0,
                "eoc_intelligence_level": "Medium (Coastal warnings, high wind speeds blocked ground responder progress)"
            },
            "timeline": {
                0: {
                    "temperature_c": 26.0, "humidity_pct": 97.0, "pressure_hpa": 984.0,
                    "wind_speed_kmh": 110.0, "wind_direction_deg": 160.0, "rainfall_mm_hr": 1.8,
                    "cloud_cover_pct": 100.0, "visibility_m": 1200.0, "surge_depth_m": 1.2,
                    "seismic_pga_g": 0.0, "tide_height_m": 4.0, "tide_phase": "HIGH TIDE",
                    "event": "Gale-force winds pick up along coastal roads."
                },
                20: {
                    "temperature_c": 24.5, "humidity_pct": 100.0, "pressure_hpa": 975.0,
                    "wind_speed_kmh": 165.0, "wind_direction_deg": 180.0, "rainfall_mm_hr": 2.8,
                    "cloud_cover_pct": 100.0, "visibility_m": 300.0, "surge_depth_m": 2.1,
                    "seismic_pga_g": 0.0, "tide_height_m": 4.9, "tide_phase": "HIGH TIDE",
                    "event": "Peak intensity near Mumbai coast; Bandra-Worli Sea Link closed due to crosswinds."
                },
                40: {
                    "temperature_c": 25.0, "humidity_pct": 99.0, "pressure_hpa": 981.0,
                    "wind_speed_kmh": 130.0, "wind_direction_deg": 200.0, "rainfall_mm_hr": 2.0,
                    "cloud_cover_pct": 100.0, "visibility_m": 800.0, "surge_depth_m": 1.6,
                    "seismic_pga_g": 0.0, "tide_height_m": 4.2, "tide_phase": "LOW TIDE",
                    "event": "Cyclone moves northward towards Gujarat; rain intensity decreases."
                },
                60: {
                    "temperature_c": 25.8, "humidity_pct": 95.0, "pressure_hpa": 990.0,
                    "wind_speed_kmh": 85.0, "wind_direction_deg": 220.0, "rainfall_mm_hr": 1.0,
                    "cloud_cover_pct": 95.0, "visibility_m": 2500.0, "surge_depth_m": 0.9,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.0, "tide_phase": "LOW TIDE",
                    "event": "Storm center departs city limits; structural cleanup crews dispatched."
                }
            }
        },
        "hudhud_2014": {
            "name": "Cyclone Hudhud (2014)",
            "description": "Very severe cyclonic storm causing catastrophic coastal damage.",
            "pop_multiplier": 1.2,
            "validation_targets": {
                "historical_survivors_saved_pct": 80.0,
                "historical_manual_saved_count": 3200,
                "historical_area_covered_pct": 85.0,
                "historical_rescue_time_mins": 50.0,
                "eoc_intelligence_level": "Medium-High (Good early warnings, but ground infrastructure collapses isolated teams)"
            },
            "timeline": {
                0: {
                    "temperature_c": 27.0, "humidity_pct": 96.0, "pressure_hpa": 982.0,
                    "wind_speed_kmh": 120.0, "wind_direction_deg": 130.0, "rainfall_mm_hr": 1.5,
                    "cloud_cover_pct": 100.0, "visibility_m": 1500.0, "surge_depth_m": 1.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.6, "tide_phase": "HIGH TIDE",
                    "event": "Storm surge warnings activated across Andhra coast."
                },
                20: {
                    "temperature_c": 25.0, "humidity_pct": 100.0, "pressure_hpa": 970.0,
                    "wind_speed_kmh": 180.0, "wind_direction_deg": 145.0, "rainfall_mm_hr": 2.5,
                    "cloud_cover_pct": 100.0, "visibility_m": 400.0, "surge_depth_m": 1.8,
                    "seismic_pga_g": 0.0, "tide_height_m": 4.4, "tide_phase": "HIGH TIDE",
                    "event": "Landfall near Visakhapatnam; extreme structural damage to power and telecom poles."
                },
                40: {
                    "temperature_c": 25.8, "humidity_pct": 99.0, "pressure_hpa": 978.0,
                    "wind_speed_kmh": 140.0, "wind_direction_deg": 160.0, "rainfall_mm_hr": 1.8,
                    "cloud_cover_pct": 100.0, "visibility_m": 1000.0, "surge_depth_m": 1.3,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.8, "tide_phase": "LOW TIDE",
                    "event": "System moves inland, weakening into a cyclonic storm."
                },
                60: {
                    "temperature_c": 26.5, "humidity_pct": 94.0, "pressure_hpa": 988.0,
                    "wind_speed_kmh": 90.0, "wind_direction_deg": 180.0, "rainfall_mm_hr": 0.8,
                    "cloud_cover_pct": 90.0, "visibility_m": 3000.0, "surge_depth_m": 0.6,
                    "seismic_pga_g": 0.0, "tide_height_m": 2.6, "tide_phase": "LOW TIDE",
                    "event": "Severe gales drop below critical thresholds; relief staging activated."
                }
            }
        },
        "phailin_2013": {
            "name": "Cyclone Phailin (2013)",
            "description": "Extremely intense cyclone triggering massive storm tides.",
            "pop_multiplier": 1.3,
            "validation_targets": {
                "historical_survivors_saved_pct": 92.0,
                "historical_manual_saved_count": 9500,
                "historical_area_covered_pct": 95.0,
                "historical_rescue_time_mins": 30.0,
                "eoc_intelligence_level": "High (Successful record evacuation of 1.1 million citizens prior to landfall)"
            },
            "timeline": {
                0: {
                    "temperature_c": 26.8, "humidity_pct": 98.0, "pressure_hpa": 978.0,
                    "wind_speed_kmh": 140.0, "wind_direction_deg": 150.0, "rainfall_mm_hr": 2.0,
                    "cloud_cover_pct": 100.0, "visibility_m": 1000.0, "surge_depth_m": 1.5,
                    "seismic_pga_g": 0.0, "tide_height_m": 4.1, "tide_phase": "HIGH TIDE",
                    "event": "Heavy precipitation and rough seas trigger red alert warning."
                },
                20: {
                    "temperature_c": 24.8, "humidity_pct": 100.0, "pressure_hpa": 962.0,
                    "wind_speed_kmh": 215.0, "wind_direction_deg": 170.0, "rainfall_mm_hr": 3.2,
                    "cloud_cover_pct": 100.0, "visibility_m": 200.0, "surge_depth_m": 2.5,
                    "seismic_pga_g": 0.0, "tide_height_m": 5.1, "tide_phase": "HIGH TIDE",
                    "event": "Landfall at Gopalpur; massive coastal inundation up to 1km inland."
                },
                40: {
                    "temperature_c": 25.5, "humidity_pct": 99.0, "pressure_hpa": 972.0,
                    "wind_speed_kmh": 160.0, "wind_direction_deg": 190.0, "rainfall_mm_hr": 2.2,
                    "cloud_cover_pct": 100.0, "visibility_m": 600.0, "surge_depth_m": 1.8,
                    "seismic_pga_g": 0.0, "tide_height_m": 4.5, "tide_phase": "LOW TIDE",
                    "event": "Tide drops; storm starts fast decay over land."
                },
                60: {
                    "temperature_c": 26.2, "humidity_pct": 96.0, "pressure_hpa": 985.0,
                    "wind_speed_kmh": 100.0, "wind_direction_deg": 210.0, "rainfall_mm_hr": 1.0,
                    "cloud_cover_pct": 95.0, "visibility_m": 2000.0, "surge_depth_m": 1.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 3.0, "tide_phase": "LOW TIDE",
                    "event": "System downgraded to deep depression; major evacuation completed."
                }
            }
        }
    },
    "EARTHQUAKE": {
        "bhuj_2001": {
            "name": "Bhuj 2001 (7.7 Mw)",
            "description": "Devastating intraplate earthquake with severe infrastructure collapse.",
            "pop_multiplier": 1.2,
            "magnitude_mw": 7.7,
            "magnitude": 7.7,
            "validation_targets": {
                "historical_survivors_saved_pct": 20.0,
                "historical_manual_saved_count": 800,
                "historical_area_covered_pct": 25.0,
                "historical_rescue_time_mins": 180.0,
                "eoc_intelligence_level": "Low (Complete telecommunication collapse, roads blocked by massive masonry debris)"
            },
            "timeline": {
                0: {
                    "temperature_c": 22.0, "humidity_pct": 45.0, "pressure_hpa": 1014.0,
                    "wind_speed_kmh": 12.0, "wind_direction_deg": 320.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 10.0, "visibility_m": 10000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.55, "tide_height_m": 1.8, "tide_phase": "LOW TIDE",
                    "event": "Primary seismic rupture (7.7 Mw); severe shaking damages masonry and bridges."
                },
                15: {
                    "temperature_c": 22.2, "humidity_pct": 45.0, "pressure_hpa": 1014.0,
                    "wind_speed_kmh": 15.0, "wind_direction_deg": 310.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 15.0, "visibility_m": 8000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.15, "tide_height_m": 1.8, "tide_phase": "LOW TIDE",
                    "event": "Major aftershock (5.6 Mw); additional structural collapses reported."
                },
                30: {
                    "temperature_c": 22.5, "humidity_pct": 42.0, "pressure_hpa": 1013.0,
                    "wind_speed_kmh": 10.0, "wind_direction_deg": 300.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 20.0, "visibility_m": 6000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.05, "tide_height_m": 1.9, "tide_phase": "LOW TIDE",
                    "event": "Ground tremors subside; search and rescue teams deploy to collapsed areas."
                },
                60: {
                    "temperature_c": 23.5, "humidity_pct": 38.0, "pressure_hpa": 1012.0,
                    "wind_speed_kmh": 8.0, "wind_direction_deg": 280.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 10.0, "visibility_m": 8000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.01, "tide_height_m": 2.0, "tide_phase": "LOW TIDE",
                    "event": "Static seismic decay profile; structural assessment loops continue."
                }
            }
        },
        "latur_1993": {
            "name": "Latur 1993 (6.2 Mw)",
            "description": "Moderate earthquake causing localized structural blockages.",
            "pop_multiplier": 1.0,
            "validation_targets": {
                "historical_survivors_saved_pct": 25.0,
                "historical_manual_saved_count": 450,
                "historical_area_covered_pct": 30.0,
                "historical_rescue_time_mins": 150.0,
                "eoc_intelligence_level": "Low (Remote village coordinates, delayed notification limits first hour saves)"
            },
            "timeline": {
                0: {
                    "temperature_c": 24.0, "humidity_pct": 50.0, "pressure_hpa": 1012.0,
                    "wind_speed_kmh": 10.0, "wind_direction_deg": 270.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 30.0, "visibility_m": 8000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.42, "tide_height_m": 1.5, "tide_phase": "LOW TIDE",
                    "event": "Seismic shock (6.2 Mw) hits intraplate fault zone; high structural collapses in stone houses."
                },
                20: {
                    "temperature_c": 24.5, "humidity_pct": 48.0, "pressure_hpa": 1011.0,
                    "wind_speed_kmh": 12.0, "wind_direction_deg": 260.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 25.0, "visibility_m": 7000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.10, "tide_height_m": 1.6, "tide_phase": "LOW TIDE",
                    "event": "First major aftershock; road blockages by debris."
                },
                40: {
                    "temperature_c": 25.0, "humidity_pct": 45.0, "pressure_hpa": 1011.0,
                    "wind_speed_kmh": 8.0, "wind_direction_deg": 250.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 20.0, "visibility_m": 8000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.03, "tide_height_m": 1.6, "tide_phase": "LOW TIDE",
                    "event": "Tremors stabilize; emergency response base established."
                },
                60: {
                    "temperature_c": 25.5, "humidity_pct": 40.0, "pressure_hpa": 1012.0,
                    "wind_speed_kmh": 6.0, "wind_direction_deg": 240.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 15.0, "visibility_m": 9000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.005, "tide_height_m": 1.7, "tide_phase": "LOW TIDE",
                    "event": "Rescue operations proceed; critical node clearing in progress."
                }
            }
        },
        "sikkim_2011": {
            "name": "Sikkim 2011 (6.9 Mw)",
            "description": "Himalayan seismic event triggering secondary rockfalls.",
            "pop_multiplier": 1.0,
            "validation_targets": {
                "historical_survivors_saved_pct": 30.0,
                "historical_manual_saved_count": 300,
                "historical_area_covered_pct": 35.0,
                "historical_rescue_time_mins": 240.0,
                "eoc_intelligence_level": "Low-Medium (Mountain passes blocked, lack of aerial targeting delayed rescue)"
            },
            "timeline": {
                0: {
                    "temperature_c": 15.0, "humidity_pct": 75.0, "pressure_hpa": 1008.0,
                    "wind_speed_kmh": 15.0, "wind_direction_deg": 45.0, "rainfall_mm_hr": 0.5,
                    "cloud_cover_pct": 80.0, "visibility_m": 5000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.35, "tide_height_m": 1.0, "tide_phase": "LOW TIDE",
                    "event": "Rupture (6.9 Mw) in Himalayas; widespread landslides block major transit routes."
                },
                20: {
                    "temperature_c": 14.5, "humidity_pct": 80.0, "pressure_hpa": 1007.0,
                    "wind_speed_kmh": 18.0, "wind_direction_deg": 50.0, "rainfall_mm_hr": 0.8,
                    "cloud_cover_pct": 90.0, "visibility_m": 3000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.08, "tide_height_m": 1.0, "tide_phase": "LOW TIDE",
                    "event": "Aftershocks trigger secondary rockfalls; roads to epicentre cut off."
                },
                40: {
                    "temperature_c": 14.8, "humidity_pct": 78.0, "pressure_hpa": 1007.0,
                    "wind_speed_kmh": 12.0, "wind_direction_deg": 40.0, "rainfall_mm_hr": 0.4,
                    "cloud_cover_pct": 85.0, "visibility_m": 4000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.02, "tide_height_m": 1.1, "tide_phase": "LOW TIDE",
                    "event": "Seismic activity decays; aerial reconnaissance initialized."
                },
                60: {
                    "temperature_c": 15.2, "humidity_pct": 72.0, "pressure_hpa": 1009.0,
                    "wind_speed_kmh": 8.0, "wind_direction_deg": 30.0, "rainfall_mm_hr": 0.1,
                    "cloud_cover_pct": 60.0, "visibility_m": 6000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.002, "tide_height_m": 1.1, "tide_phase": "LOW TIDE",
                    "event": "Helicopter scoping flights resume as visibility improves."
                }
            }
        },
        "nepal_2015": {
            "name": "Nepal 2015 (7.8 Mw)",
            "description": "Severe thrust earthquake collapsing historic structures.",
            "pop_multiplier": 1.3,
            "validation_targets": {
                "historical_survivors_saved_pct": 15.0,
                "historical_manual_saved_count": 1100,
                "historical_area_covered_pct": 20.0,
                "historical_rescue_time_mins": 200.0,
                "eoc_intelligence_level": "Low (Katastrophe scale, poor tracking of trapped victims in valley zones)"
            },
            "timeline": {
                0: {
                    "temperature_c": 18.0, "humidity_pct": 60.0, "pressure_hpa": 1010.0,
                    "wind_speed_kmh": 10.0, "wind_direction_deg": 180.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 40.0, "visibility_m": 8000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.48, "tide_height_m": 1.2, "tide_phase": "LOW TIDE",
                    "event": "Massive thrust rupture (7.8 Mw); high-intensity shaking collapse monuments and heritage bridges."
                },
                20: {
                    "temperature_c": 17.5, "humidity_pct": 65.0, "pressure_hpa": 1009.0,
                    "wind_speed_kmh": 14.0, "wind_direction_deg": 190.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 50.0, "visibility_m": 5000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.12, "tide_height_m": 1.2, "tide_phase": "LOW TIDE",
                    "event": "Strong aftershock (6.6 Mw) triggers avalanches and communications failures."
                },
                40: {
                    "temperature_c": 18.2, "humidity_pct": 58.0, "pressure_hpa": 1010.0,
                    "wind_speed_kmh": 10.0, "wind_direction_deg": 170.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 30.0, "visibility_m": 7000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.04, "tide_height_m": 1.3, "tide_phase": "LOW TIDE",
                    "event": "Heli-borne medical evacuations begin in remote regions."
                },
                60: {
                    "temperature_c": 19.0, "humidity_pct": 52.0, "pressure_hpa": 1012.0,
                    "wind_speed_kmh": 8.0, "wind_direction_deg": 160.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 20.0, "visibility_m": 9000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.008, "tide_height_m": 1.3, "tide_phase": "LOW TIDE",
                    "event": "Regional coordination centers established; international aid arrives."
                }
            }
        }
    },
    "WILDFIRE": {
        "aarey_2018": {
            "name": "Aarey Forest Fire (2018)",
            "description": "Active forest fire in Aarey Colony with rapid wind-driven spread.",
            "pop_multiplier": 1.0,
            "windspeed": 35.0,
            "moisture_content": 0.10,
            "validation_targets": {
                "historical_survivors_saved_pct": 60.0,
                "historical_manual_saved_count": 250,
                "historical_area_covered_pct": 70.0,
                "historical_rescue_time_mins": 80.0,
                "eoc_intelligence_level": "Medium-Low (Delayed containment line creation, visual scoping only)"
            },
            "timeline": {
                0: {
                    "temperature_c": 34.0, "humidity_pct": 25.0, "pressure_hpa": 1008.0,
                    "wind_speed_kmh": 25.0, "wind_direction_deg": 225.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 10.0, "visibility_m": 4000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.6, "tide_phase": "LOW TIDE",
                    "event": "Arson triggers canopy fire in dry deciduous forest near Film City."
                },
                20: {
                    "temperature_c": 35.5, "humidity_pct": 20.0, "pressure_hpa": 1006.0,
                    "wind_speed_kmh": 35.0, "wind_direction_deg": 230.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 30.0, "visibility_m": 1200.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.6, "tide_phase": "LOW TIDE",
                    "event": "High winds push fire front towards residential tribal hamlets."
                },
                40: {
                    "temperature_c": 33.8, "humidity_pct": 28.0, "pressure_hpa": 1007.0,
                    "wind_speed_kmh": 20.0, "wind_direction_deg": 220.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 45.0, "visibility_m": 2000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.6, "tide_phase": "LOW TIDE",
                    "event": "Wind speed decreases slightly; containment lines holding."
                },
                60: {
                    "temperature_c": 31.0, "humidity_pct": 35.0, "pressure_hpa": 1009.0,
                    "wind_speed_kmh": 12.0, "wind_direction_deg": 210.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 20.0, "visibility_m": 5000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.6, "tide_phase": "LOW TIDE",
                    "event": "Active front contained; emergency watch loop continues."
                }
            }
        },
        "aarey_2020": {
            "name": "Aarey Brush Fire (2020)",
            "description": "Localized brush fire spreading under moderate winds.",
            "pop_multiplier": 1.0,
            "validation_targets": {
                "historical_survivors_saved_pct": 75.0,
                "historical_manual_saved_count": 180,
                "historical_area_covered_pct": 85.0,
                "historical_rescue_time_mins": 55.0,
                "eoc_intelligence_level": "Medium (Clear coordination between rail operators and local dispatch)"
            },
            "timeline": {
                0: {
                    "temperature_c": 32.0, "humidity_pct": 35.0, "pressure_hpa": 1010.0,
                    "wind_speed_kmh": 15.0, "wind_direction_deg": 240.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 20.0, "visibility_m": 5000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.4, "tide_phase": "LOW TIDE",
                    "event": "Grass fire starts near suburban rail boundary; smoke plumes visible."
                },
                20: {
                    "temperature_c": 33.0, "humidity_pct": 30.0, "pressure_hpa": 1009.0,
                    "wind_speed_kmh": 20.0, "wind_direction_deg": 250.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 40.0, "visibility_m": 2500.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.4, "tide_phase": "LOW TIDE",
                    "event": "Dry grass fire spreads along pipeline corridors; low smoke visibility."
                },
                40: {
                    "temperature_c": 31.5, "humidity_pct": 38.0, "pressure_hpa": 1010.0,
                    "wind_speed_kmh": 12.0, "wind_direction_deg": 235.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 25.0, "visibility_m": 4000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.5, "tide_phase": "LOW TIDE",
                    "event": "Wind turns north-west; firefighting crews coordinate containment."
                },
                60: {
                    "temperature_c": 29.5, "humidity_pct": 45.0, "pressure_hpa": 1012.0,
                    "wind_speed_kmh": 8.0, "wind_direction_deg": 220.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 10.0, "visibility_m": 7000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.5, "tide_phase": "LOW TIDE",
                    "event": "Smoke clearing; rail traffic resumed."
                }
            }
        },
        "uttarakhand_2016": {
            "name": "Uttarakhand Forest Fire (2016)",
            "description": "Pine forest fires across Garhwal hills under extreme dry conditions.",
            "pop_multiplier": 1.1,
            "validation_targets": {
                "historical_survivors_saved_pct": 40.0,
                "historical_manual_saved_count": 90,
                "historical_area_covered_pct": 45.0,
                "historical_rescue_time_mins": 160.0,
                "eoc_intelligence_level": "Low (Mountainous terrain restricted heavy fire engines; communications dropped)"
            },
            "timeline": {
                0: {
                    "temperature_c": 36.0, "humidity_pct": 12.0, "pressure_hpa": 1006.0,
                    "wind_speed_kmh": 20.0, "wind_direction_deg": 210.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 5.0, "visibility_m": 3000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.0, "tide_phase": "LOW TIDE",
                    "event": "Pine forests ignite across Garhwal hills under extreme dry conditions."
                },
                20: {
                    "temperature_c": 37.8, "humidity_pct": 8.0, "pressure_hpa": 1004.0,
                    "wind_speed_kmh": 30.0, "wind_direction_deg": 220.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 20.0, "visibility_m": 800.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.0, "tide_phase": "LOW TIDE",
                    "event": "Crown fire spreads rapidly; thick smoke grounds aerial drone scanning."
                },
                40: {
                    "temperature_c": 35.5, "humidity_pct": 14.0, "pressure_hpa": 1005.0,
                    "wind_speed_kmh": 15.0, "wind_direction_deg": 200.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 35.0, "visibility_m": 1500.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.1, "tide_phase": "LOW TIDE",
                    "event": "Ground-level fires expand; community volunteers reinforce firewall lines."
                },
                60: {
                    "temperature_c": 32.0, "humidity_pct": 25.0, "pressure_hpa": 1008.0,
                    "wind_speed_kmh": 10.0, "wind_direction_deg": 180.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 15.0, "visibility_m": 4000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.1, "tide_phase": "LOW TIDE",
                    "event": "Helicopter water droppers successfully contain southern ridge sector."
                }
            }
        },
        "simlipal_2021": {
            "name": "Simlipal Biosphere Fire (2021)",
            "description": "Leaf litter fires threatening biosphere zones.",
            "pop_multiplier": 1.0,
            "validation_targets": {
                "historical_survivors_saved_pct": 50.0,
                "historical_manual_saved_count": 150,
                "historical_area_covered_pct": 55.0,
                "historical_rescue_time_mins": 120.0,
                "eoc_intelligence_level": "Low-Medium (Remote biosphere limits vehicular access, delayed fire reporting)"
            },
            "timeline": {
                0: {
                    "temperature_c": 33.0, "humidity_pct": 18.0, "pressure_hpa": 1010.0,
                    "wind_speed_kmh": 18.0, "wind_direction_deg": 190.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 10.0, "visibility_m": 4000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.2, "tide_phase": "LOW TIDE",
                    "event": "Dry conditions ignite leaf litter fires inside Simlipal biosphere."
                },
                20: {
                    "temperature_c": 34.5, "humidity_pct": 12.0, "pressure_hpa": 1008.0,
                    "wind_speed_kmh": 24.0, "wind_direction_deg": 200.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 25.0, "visibility_m": 1500.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.2, "tide_phase": "LOW TIDE",
                    "event": "Deciduous leaf litter fires threaten core tiger reserve zones."
                },
                40: {
                    "temperature_c": 32.2, "humidity_pct": 22.0, "pressure_hpa": 1009.0,
                    "wind_speed_kmh": 12.0, "wind_direction_deg": 190.0, "rainfall_mm_hr": 0.0,
                    "cloud_cover_pct": 40.0, "visibility_m": 2500.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.3, "tide_phase": "LOW TIDE",
                    "event": "Local rainfall forecast; wind gusts decrease."
                },
                60: {
                    "temperature_c": 29.0, "humidity_pct": 45.0, "pressure_hpa": 1012.0,
                    "wind_speed_kmh": 8.0, "wind_direction_deg": 170.0, "rainfall_mm_hr": 0.2,
                    "cloud_cover_pct": 60.0, "visibility_m": 5000.0, "surge_depth_m": 0.0,
                    "seismic_pga_g": 0.0, "tide_height_m": 1.3, "tide_phase": "LOW TIDE",
                    "event": "Light showers assist containment crews; fire activity severely reduced."
                }
            }
        }
    }
}
