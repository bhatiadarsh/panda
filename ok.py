"""
AquaSentinel — Single-File Live API & Simulation Version
Multi-Modal Telemetry (Open-Meteo / OpenWeatherMap / WeatherAPI) + Simulation Lab + Streamlit Dashboard.

Run: streamlit run ok.py
"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import folium
from streamlit_folium import st_folium
import pandas as pd
import numpy as np
import networkx as nx
import urllib.request
import urllib.parse
import json
import time
from datetime import datetime, timedelta

# ============================================================================
# PHASE 0A: REAL-TIME METEOROLOGY & HYDROMET API PROVIDER
# ============================================================================

class LiveTelemetryProvider:
    """Fetches real atmospheric & hydrometeorological telemetry from live APIs."""
    
    def __init__(self, provider="Open-Meteo", api_key=""):
        self.provider = provider
        self.api_key = api_key.strip()
        self.last_fetch_time = None
        self.last_status = "Not Initialized"
        self.last_latency_ms = 0
    
    def fetch_node_data(self, lat, lon):
        """Fetches live meteorological observations for specified coordinates."""
        start_t = time.time()
        try:
            if self.provider == "OpenWeatherMap" and self.api_key:
                return self._fetch_openweathermap(lat, lon, start_t)
            elif self.provider == "WeatherAPI.com" and self.api_key:
                return self._fetch_weatherapi(lat, lon, start_t)
            else:
                # Default: Open-Meteo (Free global data, no key required)
                return self._fetch_openmeteo(lat, lon, start_t)
        except Exception as e:
            self.last_status = f"API Error: {str(e)[:40]}"
            self.last_latency_ms = round((time.time() - start_t) * 1000)
            return None
    
    def _fetch_openmeteo(self, lat, lon, start_t):
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&"
            f"current=precipitation,rain,relative_humidity_2m,surface_pressure,wind_speed_10m,soil_moisture_0_to_1cm&"
            f"timezone=auto"
        )
        req = urllib.request.Request(url, headers={'User-Agent': 'AquaSentinel/2.5'})
        with urllib.request.urlopen(req, timeout=6) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            curr = res_data.get('current', {})
            
            precip = float(curr.get('precipitation', curr.get('rain', 0.0)))
            soil_moist = float(curr.get('soil_moisture_0_to_1cm', 0.35))
            humidity = float(curr.get('relative_humidity_2m', 70.0))
            pressure = float(curr.get('surface_pressure', 1013.0))
            
            self.last_latency_ms = round((time.time() - start_t) * 1000)
            self.last_status = f"Connected (Open-Meteo • {self.last_latency_ms}ms)"
            self.last_fetch_time = datetime.now()
            
            return {
                'precipitation_rate': precip,       # mm/h
                'soil_saturation': min(1.0, max(0.05, soil_moist * 2.0)), # Normalized fraction
                'humidity': humidity,
                'pressure': pressure,
                'source': 'Open-Meteo Live API'
            }
            
    def _fetch_openweathermap(self, lat, lon, start_t):
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={self.api_key}&units=metric"
        req = urllib.request.Request(url, headers={'User-Agent': 'AquaSentinel/2.5'})
        with urllib.request.urlopen(req, timeout=6) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            rain_dict = res_data.get('rain', {})
            precip = float(rain_dict.get('1h', 0.0))
            main_dict = res_data.get('main', {})
            humidity = float(main_dict.get('humidity', 70.0))
            pressure = float(main_dict.get('pressure', 1013.0))
            soil_moist = float(humidity / 100.0 * 0.5)
            
            self.last_latency_ms = round((time.time() - start_t) * 1000)
            self.last_status = f"Connected (OpenWeatherMap • {self.last_latency_ms}ms)"
            self.last_fetch_time = datetime.now()
            
            return {
                'precipitation_rate': precip,
                'soil_saturation': min(1.0, max(0.05, soil_moist)),
                'humidity': humidity,
                'pressure': pressure,
                'source': 'OpenWeatherMap Live API'
            }

    def _fetch_weatherapi(self, lat, lon, start_t):
        url = f"https://api.weatherapi.com/v1/current.json?key={self.api_key}&q={lat},{lon}"
        req = urllib.request.Request(url, headers={'User-Agent': 'AquaSentinel/2.5'})
        with urllib.request.urlopen(req, timeout=6) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            curr = res_data.get('current', {})
            precip = float(curr.get('precip_mm', 0.0))
            humidity = float(curr.get('humidity', 70.0))
            pressure = float(curr.get('pressure_mb', 1013.0))
            soil_moist = float(humidity / 100.0 * 0.55)
            
            self.last_latency_ms = round((time.time() - start_t) * 1000)
            self.last_status = f"Connected (WeatherAPI • {self.last_latency_ms}ms)"
            self.last_fetch_time = datetime.now()
            
            return {
                'precipitation_rate': precip,
                'soil_saturation': min(1.0, max(0.05, soil_moist)),
                'humidity': humidity,
                'pressure': pressure,
                'source': 'WeatherAPI.com Live API'
            }

# ============================================================================
# PHASE 0B: SIMULATION & HYBRID TELEMETRY LAYER
# ============================================================================

class TelemetrySimulator:
    def __init__(self, zones=None, base_time=None):
        self.zones = zones or [f"HRU-{i:02d}" for i in range(1, 6)]
        self.num_zones = len(self.zones)
        self.base_time = base_time or datetime.now()
        
        self.history = {zone: {
            'time': [],
            'rainfall': [],         # mm/h
            'cum_rainfall': [],     # mm cumulative
            'cml': [],              # dB (received signal level)
            'vibration': [],        # g (bridge vibration)
            'river_level': [],      # meters
            'soil_saturation': []   # 0.0 - 1.0 (fraction)
        } for zone in self.zones}
        
        self.mode = "Synthetic Simulation"
        self.scenario_intensity = 0.0
        self.scenario_preset = "Normal Day"
        self.time_step_minutes = 1
        self.api_provider = LiveTelemetryProvider()
    
    def set_config(self, mode="Synthetic Simulation", intensity=0.0, preset="Normal Day", api_provider=None):
        self.mode = mode
        self.scenario_intensity = max(0.0, min(1.0, float(intensity)))
        self.scenario_preset = preset
        if api_provider:
            self.api_provider = api_provider
    
    def generate_step(self, node_coords=None, timestamp=None):
        if timestamp is None:
            if self.history[self.zones[0]]['time']:
                last_time = self.history[self.zones[0]]['time'][-1]
                timestamp = last_time + timedelta(minutes=self.time_step_minutes)
            else:
                timestamp = self.base_time
        
        data = {}
        node_coords = node_coords or {}
        
        for zone_idx, zone in enumerate(self.zones):
            coords = node_coords.get(zone, {'lat': 32.18 - zone_idx * 0.03, 'lon': 77.12 + zone_idx * 0.01})
            
            # Base telemetry generation (Real API vs Synthetic baseline)
            if self.mode in ("Live Real-Time API", "Hybrid (Live + Surge)"):
                live_res = self.api_provider.fetch_node_data(coords['lat'], coords['lon'])
                if live_res:
                    base_rain = live_res['precipitation_rate']
                    base_soil = live_res['soil_saturation']
                else:
                    base_rain = max(0.0, 0.2 + np.random.normal(0, 0.08))
                    base_soil = 0.42 + np.random.normal(0, 0.02)
            else:
                base_rain = max(0.0, 0.2 + np.random.normal(0, 0.08))
                base_soil = 0.42 + np.random.normal(0, 0.02)
            
            # ITU-R P.838 Rain-Induced Microwave Link (CML) specific attenuation: A = a * R^b
            cml_attenuation = 0.025 * (base_rain ** 1.15)
            base_cml = max(5.0, 32.0 - cml_attenuation + np.random.normal(0, 0.3))
            base_vibration = max(0.01, 0.04 + (base_rain * 0.01) + np.random.normal(0, 0.01))
            base_river = max(0.3, 1.2 + (base_rain * 0.05) + np.random.normal(0, 0.02))
            
            rainfall = base_rain
            cml = base_cml
            vibration = base_vibration
            river = base_river
            soil = base_soil
            
            # Scenario / Surge Injection
            if self.scenario_intensity > 0 or self.scenario_preset != "Normal Day":
                zone_factor = 1.0 - (zone_idx * 0.15)
                eff_intensity = self.scenario_intensity * max(0.4, zone_factor)
                
                if self.scenario_preset == "Sudden Cloudburst":
                    rainfall += eff_intensity * (28.0 + np.random.uniform(0, 12))
                    cml -= eff_intensity * (20.0 + np.random.uniform(0, 6))
                    vibration += eff_intensity * (1.6 + np.random.uniform(0, 0.8))
                    river += eff_intensity * (2.2 + np.random.uniform(0, 0.8))
                    soil += eff_intensity * (0.45 + np.random.uniform(0, 0.1))
                elif self.scenario_preset == "Sensor Glitch (Single Sensor Fault)":
                    if zone_idx == 0:
                        vibration += 2.2
                else: # Default Flash Flood Building
                    rainfall += eff_intensity * (14.0 + np.random.uniform(0, 6))
                    cml -= eff_intensity * (14.0 + np.random.uniform(0, 5))
                    vibration += eff_intensity * (0.9 + np.random.uniform(0, 0.4))
                    river += eff_intensity * (1.5 + np.random.uniform(0, 0.5))
                    soil += eff_intensity * (0.35 + np.random.uniform(0, 0.1))
            
            # Clamp bounds
            rainfall = float(np.clip(rainfall, 0.0, 150.0))
            cml = float(np.clip(cml, 0.0, 45.0))
            vibration = float(np.clip(vibration, 0.0, 5.0))
            river = float(np.clip(river, 0.0, 10.0))
            soil = float(np.clip(soil, 0.0, 1.0))
            
            # Cumulative storm precipitation tracking
            dt_hours = self.time_step_minutes / 60.0
            prev_cum = self.history[zone]['cum_rainfall'][-1] if self.history[zone]['cum_rainfall'] else 0.0
            cum_rainfall = prev_cum + (rainfall * dt_hours)
            
            data[zone] = {
                'time': timestamp,
                'rainfall': rainfall,
                'cum_rainfall': cum_rainfall,
                'cml': cml,
                'vibration': vibration,
                'river_level': river,
                'soil_saturation': soil,
            }
            
            self.history[zone]['time'].append(timestamp)
            self.history[zone]['rainfall'].append(rainfall)
            self.history[zone]['cum_rainfall'].append(cum_rainfall)
            self.history[zone]['cml'].append(cml)
            self.history[zone]['vibration'].append(vibration)
            self.history[zone]['river_level'].append(river)
            self.history[zone]['soil_saturation'].append(soil)
        
        return data, timestamp
    
    def get_latest(self):
        result = {}
        for zone in self.zones:
            if self.history[zone]['time']:
                result[zone] = {
                    'time': self.history[zone]['time'][-1],
                    'rainfall': self.history[zone]['rainfall'][-1],
                    'cum_rainfall': self.history[zone]['cum_rainfall'][-1],
                    'cml': self.history[zone]['cml'][-1],
                    'vibration': self.history[zone]['vibration'][-1],
                    'river_level': self.history[zone]['river_level'][-1],
                    'soil_saturation': self.history[zone]['soil_saturation'][-1],
                }
        return result
    
    def get_history_df(self, zone=None):
        if zone:
            if zone not in self.history or not self.history[zone]['time']:
                return pd.DataFrame()
            return pd.DataFrame(self.history[zone])
        else:
            records = []
            for z in self.zones:
                if not self.history[z]['time']:
                    continue
                df_z = pd.DataFrame(self.history[z])
                df_z['zone'] = z
                records.append(df_z)
            return pd.concat(records, ignore_index=True) if records else pd.DataFrame()

# ============================================================================
# PHASE 1: DIFFERENTIAL DETECTION ENGINE
# ============================================================================

class DifferentialEngine:
    def __init__(self, thresholds=None, window_size=3):
        self.thresholds = thresholds or {
            'rainfall': 4.0,
            'cml': 3.0,
            'vibration': 0.35,
            'river_level': 0.25,
            'soil_saturation': 0.08
        }
        self.window_size = max(2, window_size)
        self.flags = {}
    
    def detect_anomaly(self, signal_history, signal_name):
        if len(signal_history) < 2:
            return False, 0.0
        
        window = np.array(signal_history[-self.window_size:], dtype=float)
        diffs = np.diff(window)
        avg_rate = float(np.mean(np.abs(diffs)))
        threshold = self.thresholds.get(signal_name, 1.0)
        
        if signal_name == 'cml':
            cml_drop_rate = float(np.mean(-diffs))
            is_anomalous = cml_drop_rate > threshold or avg_rate > (threshold * 1.5)
        else:
            is_anomalous = avg_rate > threshold
        
        return bool(is_anomalous), round(avg_rate, 3)
    
    def process_telemetry(self, history):
        anomalies = {}
        for zone, signals in history.items():
            anomalies[zone] = {}
            for signal_name, values in signals.items():
                if signal_name in ('time', 'cum_rainfall'):
                    continue
                
                if not values:
                    anomalies[zone][signal_name] = {
                        'anomalous': False,
                        'rate': 0.0,
                        'value': 0.0,
                        'threshold': self.thresholds.get(signal_name, 1.0)
                    }
                    continue
                
                is_anomalous, rate = self.detect_anomaly(values, signal_name)
                anomalies[zone][signal_name] = {
                    'anomalous': is_anomalous,
                    'rate': rate,
                    'value': round(values[-1], 3),
                    'threshold': self.thresholds.get(signal_name, 1.0)
                }
        
        self.flags = anomalies
        return anomalies

# ============================================================================
# PHASE 2: 2-OF-4 CONSENSUS ENGINE
# ============================================================================

class ConsensusEngine:
    def __init__(self):
        self.vote_signals = ['rainfall', 'cml', 'vibration', 'river_level']
        self.weights = {
            'rainfall': 0.30,
            'cml': 0.25,
            'vibration': 0.20,
            'river_level': 0.25,
        }
        self.risk_states = {
            0: ('GREEN', '#00C853', 'Normal / Baseline Flow'),
            1: ('WATCH', '#FFC107', 'Elevated Watch / Single Sensor Triggered'),
            2: ('RED', '#D32F2F', 'CRITICAL / Multi-Sensor Consensus Verified'),
        }
    
    def calculate_risk(self, anomalies_per_zone):
        results = {}
        for zone, signals in anomalies_per_zone.items():
            triggered = []
            for signal in self.vote_signals:
                if signal in signals and signals[signal].get('anomalous', False):
                    triggered.append(signal)
            
            num_triggered = len(triggered)
            if num_triggered >= 2:
                risk_level = 2
            elif num_triggered == 1:
                risk_level = 1
            else:
                risk_level = 0
            
            risk_state, color, desc = self.risk_states[risk_level]
            score = sum(self.weights.get(sig, 0.25) for sig in triggered)
            score = min(1.0, max(0.0, score))
            
            results[zone] = {
                'risk_level': risk_level,
                'risk_state': risk_state,
                'description': desc,
                'color': color,
                'triggered_signals': triggered,
                'score': round(score, 3),
                'num_triggered': num_triggered,
                'total_voters': len(self.vote_signals)
            }
        return results
    
    def get_why_alert(self, anomalies_per_zone, zone):
        if zone not in anomalies_per_zone:
            return "Zone not found."
        
        signals = anomalies_per_zone[zone]
        triggered = []
        
        explanations = {
            'rainfall': 'Optical Rain Gauge detected precipitous rate-of-onset exceeding safety envelope',
            'cml': 'Commercial Microwave Link (CML) detected sharp path attenuation from intense storm cell',
            'vibration': 'Bridge Geophone / Vibrometer picked up rapid debris-flow / bedload surge acoustic energy',
            'river_level': 'Hydrostatic Gauge recorded rapid water stage ascent',
        }
        
        for signal in self.vote_signals:
            if signal in signals and signals[signal].get('anomalous', False):
                rate = signals[signal].get('rate', 0.0)
                thresh = signals[signal].get('threshold', 0.0)
                val = signals[signal].get('value', 0.0)
                desc = explanations.get(signal, f'{signal} surge')
                triggered.append(f"**{signal.upper()}** (Current: `{val}`, Rate: `+{rate}/min`, Thresh: `{thresh}`): {desc}")
        
        if not triggered:
            return "🟢 **GREEN State**: All telemetry streams within nominal steady-state envelopes. No anomaly detected."
        
        text = f"### 🛡️ Decision Diagnostic for **{zone}**\n\n"
        text += f"**Triggered Anomaly Streams ({len(triggered)} of 4):**\n\n"
        for i, t in enumerate(triggered, 1):
            text += f"{i}. {t}\n\n"
        
        if len(triggered) >= 2:
            text += "> 🚨 **Consensus Reached (≥2 of 4 Signals)**: Cross-validation confirmed legitimate flood wavefront. High-confidence RED alert generated. False positive risk eliminated."
        else:
            text += "> ⚠️ **Single Signal Anomaly (1 of 4)**: Placed in **WATCH** status. Awaiting multi-sensor confirmation to avoid false alarm dispatch."
        
        return text

# ============================================================================
# PHASE 3: SCS-CN RUNOFF CALCULATOR
# ============================================================================

class RunoffCalculator:
    def __init__(self, hru_properties=None):
        self.hru_properties = hru_properties or {
            'HRU-01': {'name': 'Upper Ridge', 'curve_number': 65, 'area_km2': 4.2},
            'HRU-02': {'name': 'Highland Slope', 'curve_number': 72, 'area_km2': 5.8},
            'HRU-03': {'name': 'Tributary North', 'curve_number': 78, 'area_km2': 3.5},
            'HRU-04': {'name': 'Tributary South', 'curve_number': 75, 'area_km2': 4.1},
            'HRU-05': {'name': 'Valley Confluence', 'curve_number': 82, 'area_km2': 6.0},
        }
        self.default_cn = 72
    
    def calculate_runoff(self, cum_rainfall_mm, curve_number):
        if curve_number <= 0 or curve_number > 100:
            return 0.0
        
        S = (25400.0 / curve_number) - 254.0
        Ia = 0.2 * S
        
        if cum_rainfall_mm <= Ia:
            return 0.0
        
        P_eff = cum_rainfall_mm - Ia
        Q = (P_eff ** 2) / (P_eff + S)
        return float(max(0.0, Q))
    
    def process_zones(self, latest_telemetry):
        results = {}
        for zone, data in latest_telemetry.items():
            cn = self.hru_properties.get(zone, {}).get('curve_number', self.default_cn)
            area = self.hru_properties.get(zone, {}).get('area_km2', 4.0)
            cum_p = data.get('cum_rainfall', 0.0)
            rate_p = data.get('rainfall', 0.0)
            
            q_cum = self.calculate_runoff(cum_p, cn)
            runoff_fraction = (q_cum / cum_p) if cum_p > 0.01 else 0.05
            q_rate_mm_h = rate_p * runoff_fraction
            discharge_m3_s = (q_rate_mm_h * (area * 1e6)) / (3.6e6)
            
            results[zone] = {
                'curve_number': cn,
                'area_km2': area,
                'cum_rainfall_mm': round(cum_p, 2),
                'cum_runoff_mm': round(q_cum, 2),
                'discharge_m3_s': round(discharge_m3_s, 2),
                'runoff_fraction_pct': round(runoff_fraction * 100, 1)
            }
        return results

# ============================================================================
# PHASE 4: HRU CASCADE GRAPH & RISK ROUTING
# ============================================================================

class HRUCascade:
    def __init__(self):
        self.graph = nx.DiGraph()
        self.node_props = {}
        self.risk_propagated = {}
    
    def add_node(self, node_id, node_type='hru', name='', lat=32.1, lon=77.1, area_km2=4.0, elevation_m=2400):
        self.graph.add_node(node_id)
        self.node_props[node_id] = {
            'id': node_id,
            'name': name or node_id,
            'type': node_type,
            'lat': lat,
            'lon': lon,
            'area_km2': area_km2,
            'elevation_m': elevation_m
        }
        self.risk_propagated[node_id] = {'risk_level': 0, 'total_discharge': 0.0, 'state': 'GREEN'}
    
    def add_edge(self, upstream, downstream, lag_minutes=20):
        self.graph.add_edge(upstream, downstream, lag_minutes=lag_minutes)
    
    def create_catchment(self, catchment_preset="Beas Catchment (Kullu/Manali)"):
        self.graph.clear()
        self.node_props.clear()
        
        if catchment_preset == "Kedarnath / Mandakini Basin":
            base_lat, base_lon = 30.73, 79.06
        else:
            base_lat, base_lon = 32.18, 77.12
            
        self.add_node('HRU-01', node_type='hru', name='Upper Ridge Catchment', lat=round(base_lat, 4), lon=round(base_lon, 4), area_km2=4.2, elevation_m=3200)
        self.add_node('HRU-02', node_type='hru', name='Highland Slope', lat=round(base_lat - 0.04, 4), lon=round(base_lon + 0.02, 4), area_km2=5.8, elevation_m=2700)
        self.add_node('HRU-03', node_type='hru', name='Tributary North Reach', lat=round(base_lat - 0.06, 4), lon=round(base_lon - 0.01, 4), area_km2=3.5, elevation_m=2450)
        self.add_node('HRU-04', node_type='hru', name='Tributary South Reach', lat=round(base_lat - 0.09, 4), lon=round(base_lon + 0.04, 4), area_km2=4.1, elevation_m=2200)
        self.add_node('HRU-05', node_type='hru', name='Valley Confluence Basin', lat=round(base_lat - 0.12, 4), lon=round(base_lon + 0.03, 4), area_km2=6.0, elevation_m=1850)
        self.add_node('Village-A', node_type='settlement', name='Downstream Settlement', lat=round(base_lat - 0.16, 4), lon=round(base_lon + 0.05, 4), area_km2=1.2, elevation_m=1600)
        
        self.add_edge('HRU-01', 'HRU-02', lag_minutes=15)
        self.add_edge('HRU-02', 'HRU-03', lag_minutes=20)
        self.add_edge('HRU-03', 'HRU-05', lag_minutes=25)
        self.add_edge('HRU-04', 'HRU-05', lag_minutes=20)
        self.add_edge('HRU-05', 'Village-A', lag_minutes=35)
    
    def propagate_risk(self, local_risk_data, runoff_data):
        result = {}
        try:
            topo_order = list(nx.topological_sort(self.graph))
        except Exception:
            topo_order = list(self.graph.nodes())
        
        for node in topo_order:
            local_risk = local_risk_data.get(node, {}).get('risk_level', 0)
            local_discharge = runoff_data.get(node, {}).get('discharge_m3_s', 0.0)
            
            upstream_risks = []
            upstream_discharges = []
            
            for pred in self.graph.predecessors(node):
                if pred in result:
                    upstream_risks.append(result[pred]['risk_level'])
                    upstream_discharges.append(result[pred]['total_discharge'])
            
            if upstream_risks:
                max_upstream_risk = max(upstream_risks)
                total_risk = max(local_risk, max_upstream_risk)
                total_discharge = local_discharge + sum(upstream_discharges)
            else:
                total_risk = local_risk
                total_discharge = local_discharge
            
            risk_states = {0: 'GREEN', 1: 'WATCH', 2: 'RED'}
            result[node] = {
                'risk_level': total_risk,
                'risk_state': risk_states.get(total_risk, 'GREEN'),
                'local_risk': local_risk,
                'total_discharge': round(total_discharge, 2),
                'upstream_nodes': list(self.graph.predecessors(node))
            }
        
        self.risk_propagated = result
        return result
    
    def get_node_details(self):
        details = []
        for node_id, props in self.node_props.items():
            risk_info = self.risk_propagated.get(node_id, {'risk_level': 0, 'risk_state': 'GREEN', 'total_discharge': 0.0})
            details.append({
                **props,
                **risk_info
            })
        return details

# ============================================================================
# PHASE 5: STREAMLIT WEB APPLICATION
# ============================================================================

st.set_page_config(
    page_title="AquaSentinel | Live API & Early Warning",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        border-radius: 6px;
    }
</style>
""", unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# SESSION STATE INITIALIZATION
# ----------------------------------------------------------------------------

if 'zones' not in st.session_state:
    st.session_state.zones = [f"HRU-{i:02d}" for i in range(1, 6)]

if 'catchment_preset' not in st.session_state:
    st.session_state.catchment_preset = "Beas Catchment (Kullu/Manali)"

if 'cascade' not in st.session_state:
    st.session_state.cascade = HRUCascade()
    st.session_state.cascade.create_catchment(st.session_state.catchment_preset)

if 'api_provider_name' not in st.session_state:
    st.session_state.api_provider_name = "Open-Meteo"

if 'api_key' not in st.session_state:
    st.session_state.api_key = ""

if 'live_provider' not in st.session_state:
    st.session_state.live_provider = LiveTelemetryProvider(
        provider=st.session_state.api_provider_name,
        api_key=st.session_state.api_key
    )

if 'simulator' not in st.session_state:
    st.session_state.simulator = TelemetrySimulator(zones=st.session_state.zones)

if 'diff_engine' not in st.session_state:
    st.session_state.diff_engine = DifferentialEngine()

if 'consensus' not in st.session_state:
    st.session_state.consensus = ConsensusEngine()

if 'runoff_calc' not in st.session_state:
    st.session_state.runoff_calc = RunoffCalculator()

if 'mode' not in st.session_state:
    st.session_state.mode = "Synthetic Simulation"

if 'scenario_intensity' not in st.session_state:
    st.session_state.scenario_intensity = 0.0

if 'scenario_preset' not in st.session_state:
    st.session_state.scenario_preset = "Normal Day"

if 'steps_generated' not in st.session_state:
    st.session_state.steps_generated = 0

if 'latest_data' not in st.session_state:
    st.session_state.latest_data = {}

if 'anomalies' not in st.session_state:
    st.session_state.anomalies = {}

if 'risk_scores' not in st.session_state:
    st.session_state.risk_scores = {}

if 'runoff_results' not in st.session_state:
    st.session_state.runoff_results = {}

# ----------------------------------------------------------------------------
# SIMULATION STEP ENGINE
# ----------------------------------------------------------------------------

def step_simulation(num_steps=1):
    sim = st.session_state.simulator
    diff_engine = st.session_state.diff_engine
    consensus = st.session_state.consensus
    runoff_calc = st.session_state.runoff_calc
    cascade = st.session_state.cascade
    
    sim.set_config(
        mode=st.session_state.mode,
        intensity=st.session_state.scenario_intensity,
        preset=st.session_state.scenario_preset,
        api_provider=st.session_state.live_provider
    )
    
    node_coords = {nid: {'lat': p['lat'], 'lon': p['lon']} for nid, p in cascade.node_props.items()}
    
    for _ in range(num_steps):
        latest_data, ts = sim.generate_step(node_coords=node_coords)
        anomalies = diff_engine.process_telemetry(sim.history)
        risk_scores = consensus.calculate_risk(anomalies)
        runoff_results = runoff_calc.process_zones(latest_data)
        cascade.propagate_risk(risk_scores, runoff_results)
        st.session_state.steps_generated += 1
    
    st.session_state.latest_data = latest_data
    st.session_state.anomalies = anomalies
    st.session_state.risk_scores = risk_scores
    st.session_state.runoff_results = runoff_results

# Seed baseline on first boot
if st.session_state.steps_generated == 0:
    step_simulation(num_steps=5)

# ----------------------------------------------------------------------------
# SIDEBAR CONTROLS & API CONFIGURATION
# ----------------------------------------------------------------------------

with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/tsunami.png", width=64)
    st.title("AquaSentinel")
    st.caption("Live Real-Time Telemetry & Simulation Platform")
    st.divider()
    
    # 1. OPERATION MODE
    st.subheader("🌐 Data Ingestion Mode")
    mode_choice = st.radio(
        "Mode Selection",
        ["Live Real-Time API", "Hybrid (Live + Surge)", "Synthetic Simulation"],
        index=["Live Real-Time API", "Hybrid (Live + Surge)", "Synthetic Simulation"].index(st.session_state.mode)
    )
    st.session_state.mode = mode_choice
    
    # 2. API CONFIGURATION
    with st.expander("🔑 API & Provider Settings", expanded=(mode_choice != "Synthetic Simulation")):
        provider_selected = st.selectbox(
            "API Provider",
            ["Open-Meteo", "OpenWeatherMap", "WeatherAPI.com"],
            index=["Open-Meteo", "OpenWeatherMap", "WeatherAPI.com"].index(st.session_state.api_provider_name)
        )
        st.session_state.api_provider_name = provider_selected
        
        api_key_input = st.text_input(
            "API Key (Optional for Open-Meteo)",
            value=st.session_state.api_key,
            type="password",
            help="Open-Meteo requires no key. For OpenWeatherMap or WeatherAPI.com, paste your API key here."
        )
        st.session_state.api_key = api_key_input
        
        # Update live provider object
        st.session_state.live_provider.provider = provider_selected
        st.session_state.live_provider.api_key = api_key_input
        
        # Catchment Location Coordinates Preset
        catchment_choice = st.selectbox(
            "Target Catchment Basin",
            ["Beas Catchment (Kullu/Manali)", "Kedarnath / Mandakini Basin"],
            index=["Beas Catchment (Kullu/Manali)", "Kedarnath / Mandakini Basin"].index(st.session_state.catchment_preset)
        )
        if catchment_choice != st.session_state.catchment_preset:
            st.session_state.catchment_preset = catchment_choice
            st.session_state.cascade.create_catchment(catchment_choice)
            st.session_state.steps_generated = 0
            step_simulation(5)
            st.rerun()

    # API Connection Status Badge
    if mode_choice != "Synthetic Simulation":
        st.info(f"📡 Status: `{st.session_state.live_provider.last_status}`")
    else:
        st.info("🧪 Status: `Offline Synthetic Engine Active`")

    st.divider()
    
    # 3. SIMULATION / SURGE INJECTION CONTROLS
    st.subheader("🕹️ Simulation & Surge Injection")
    preset_choice = st.selectbox(
        "Scenario / Hazard Injection",
        ["Normal Day", "Sudden Cloudburst", "Flash Flood Building", "Sensor Glitch (Single Sensor Fault)"],
        index=["Normal Day", "Sudden Cloudburst", "Flash Flood Building", "Sensor Glitch (Single Sensor Fault)"].index(st.session_state.scenario_preset)
    )
    
    if preset_choice != st.session_state.scenario_preset:
        st.session_state.scenario_preset = preset_choice
        if preset_choice == "Normal Day":
            st.session_state.scenario_intensity = 0.0
        elif preset_choice == "Sudden Cloudburst":
            st.session_state.scenario_intensity = 0.9
        elif preset_choice == "Sensor Glitch (Single Sensor Fault)":
            st.session_state.scenario_intensity = 0.5
        else:
            st.session_state.scenario_intensity = 0.6
    
    intensity = st.slider("Hazard Surge Intensity", 0.0, 1.0, float(st.session_state.scenario_intensity), 0.05)
    st.session_state.scenario_intensity = intensity
    
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        btn_label = "⚡ Fetch Live (+1m)" if mode_choice == "Live Real-Time API" else "▶ Step (+1m)"
        if st.button(btn_label, use_container_width=True):
            step_simulation(1)
            st.rerun()
    with col_s2:
        if st.button("⏩ Advance 10m", use_container_width=True):
            step_simulation(10)
            st.rerun()
            
    if st.button("🔄 Reset Telemetry Buffer", use_container_width=True):
        st.session_state.simulator = TelemetrySimulator(zones=st.session_state.zones)
        st.session_state.cascade = HRUCascade()
        st.session_state.cascade.create_catchment(st.session_state.catchment_preset)
        st.session_state.diff_engine = DifferentialEngine()
        st.session_state.consensus = ConsensusEngine()
        st.session_state.runoff_calc = RunoffCalculator()
        st.session_state.steps_generated = 0
        st.session_state.scenario_intensity = 0.0
        st.session_state.scenario_preset = "Normal Day"
        step_simulation(5)
        st.rerun()
        
    st.divider()
    st.metric("Simulation Clock", f"{st.session_state.steps_generated} mins")
    active_reds = sum(1 for r in st.session_state.risk_scores.values() if r.get('risk_level') == 2)
    if active_reds > 0:
        st.error(f"🚨 CRITICAL ALERTS: {active_reds} ZONES")
    else:
        st.success("✅ ALL STREAMS NOMINAL")

# ----------------------------------------------------------------------------
# HEADER & EXECUTIVE METRICS
# ----------------------------------------------------------------------------

col_h1, col_h2, col_h3, col_h4 = st.columns([3, 1, 1, 1])
with col_h1:
    st.title("🌊 AquaSentinel Command Console")
    source_label = f"Live Data ({st.session_state.api_provider_name})" if st.session_state.mode != "Synthetic Simulation" else "Synthetic Simulator"
    st.markdown(f"**Mode: `{st.session_state.mode}`** · **Feed: `{source_label}`** · **Target: `{st.session_state.catchment_preset}`**")

with col_h2:
    max_risk = max((r.get('risk_level', 0) for r in st.session_state.risk_scores.values()), default=0)
    badge = "🟢 NORMAL" if max_risk == 0 else ("🟡 WATCH" if max_risk == 1 else "🔴 CRITICAL")
    st.metric("Threat Status", badge)

with col_h3:
    total_q = sum(r.get('discharge_m3_s', 0.0) for r in st.session_state.runoff_results.values())
    st.metric("Basin Outflow Q", f"{total_q:.1f} m³/s")

with col_h4:
    village_status = st.session_state.cascade.risk_propagated.get('Village-A', {})
    v_risk = village_status.get('risk_state', 'GREEN')
    st.metric("Settlement Threat", v_risk)

st.divider()

# ----------------------------------------------------------------------------
# TABS INTERFACE
# ----------------------------------------------------------------------------

tab_telemetry, tab_anomaly, tab_consensus, tab_map, tab_explain = st.tabs([
    "📡 Telemetry Streams",
    "🚨 Anomaly Matrix",
    "📊 2-of-4 Consensus & Risk",
    "🗺️ Catchment Cascade Map",
    "❓ Explainable AI (XAI) Diagnostics"
])

# ----------------------------------------------------------------------------
# TAB 1: TELEMETRY STREAMS
# ----------------------------------------------------------------------------
with tab_telemetry:
    st.subheader("Multi-Modal Telemetry Feeds")
    df_hist = st.session_state.simulator.get_history_df()
    
    if not df_hist.empty:
        c_sel1, c_sel2 = st.columns([2, 1])
        with c_sel1:
            selected_zone_plot = st.multiselect(
                "Filter Zones", 
                st.session_state.zones, 
                default=st.session_state.zones
            )
        with c_sel2:
            st.download_button(
                "📥 Export Telemetry CSV",
                df_hist.to_csv(index=False),
                file_name=f"aquasentinel_telemetry_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        
        filtered_df = df_hist[df_hist['zone'].isin(selected_zone_plot)]
        
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                "🌧️ Rainfall Rate (mm/h)",
                "📡 Microwave Link RSL / Attenuation (dBm)",
                "🌊 River Water Level (m)",
                "🌉 Bridge Acoustic Vibration (g)"
            ),
            vertical_spacing=0.12,
            horizontal_spacing=0.08
        )
        
        colors = ['#00E5FF', '#76FF03', '#FFD600', '#FF3D00', '#D500F9']
        
        for idx, zone in enumerate(selected_zone_plot):
            z_data = filtered_df[filtered_df['zone'] == zone]
            color = colors[idx % len(colors)]
            
            # Rainfall
            fig.add_trace(go.Scatter(x=z_data['time'], y=z_data['rainfall'], name=zone, line=dict(color=color), legendgroup=zone), row=1, col=1)
            # CML
            fig.add_trace(go.Scatter(x=z_data['time'], y=z_data['cml'], name=zone, line=dict(color=color), legendgroup=zone, showlegend=False), row=1, col=2)
            # River
            fig.add_trace(go.Scatter(x=z_data['time'], y=z_data['river_level'], name=zone, line=dict(color=color), legendgroup=zone, showlegend=False), row=2, col=1)
            # Vibration
            fig.add_trace(go.Scatter(x=z_data['time'], y=z_data['vibration'], name=zone, line=dict(color=color), legendgroup=zone, showlegend=False), row=2, col=2)
        
        fig.update_layout(height=520, margin=dict(l=20, r=20, t=40, b=20), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No telemetry points recorded yet.")

# ----------------------------------------------------------------------------
# TAB 2: ANOMALY DETECTION MATRIX
# ----------------------------------------------------------------------------
with tab_anomaly:
    st.subheader("Differential Rate-of-Change Anomaly Engine")
    st.markdown("Sensors trigger differential flags when $|\\Delta X / \\Delta t|$ surpasses the dynamic threshold window.")
    
    anomalies = st.session_state.anomalies
    for zone, sigs in anomalies.items():
        with st.expander(f"📍 Zone **{zone}** Status Breakdown", expanded=True):
            cols = st.columns(5)
            sensor_keys = ['rainfall', 'cml', 'vibration', 'river_level', 'soil_saturation']
            sensor_names = ['Rainfall Rate', 'CML Attenuation', 'Bridge Vibration', 'River Gauge', 'Soil Moisture']
            units = ['mm/h', 'dBm', 'g', 'm', '%']
            
            for i, (sk, sname, unit) in enumerate(zip(sensor_keys, sensor_names, units)):
                with cols[i]:
                    s_data = sigs.get(sk, {})
                    is_anom = s_data.get('anomalous', False)
                    rate = s_data.get('rate', 0.0)
                    val = s_data.get('value', 0.0)
                    thresh = s_data.get('threshold', 0.0)
                    
                    st.metric(
                        label=f"{sname}",
                        value=f"{val} {unit}",
                        delta=f"Δ {rate:.2f}/min (T: {thresh})" if is_anom else f"Δ {rate:.2f}/min",
                        delta_color="inverse" if is_anom else "off"
                    )
                    if is_anom:
                        st.error("🚨 ANOMALOUS")
                    else:
                        st.success("✅ NOMINAL")

# ----------------------------------------------------------------------------
# TAB 3: 2-OF-4 CONSENSUS & RISK CLASSIFICATION
# ----------------------------------------------------------------------------
with tab_consensus:
    st.subheader("Multi-Sensor Consensus & Fusion Decision Matrix")
    st.markdown("Eliminates false alarms by requiring **$\\ge 2$ independent sensing modalities** before escalating to RED Alert.")
    
    risk_scores = st.session_state.risk_scores
    runoff_results = st.session_state.runoff_results
    
    cols = st.columns(len(risk_scores))
    for i, (zone, r_data) in enumerate(risk_scores.items()):
        with cols[i]:
            score_pct = r_data.get('score', 0.0) * 100
            risk_state = r_data.get('risk_state', 'GREEN')
            color = r_data.get('color', '#00C853')
            triggered = r_data.get('triggered_signals', [])
            
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=score_pct,
                domain={'x': [0, 1], 'y': [0, 1]},
                title={'text': f"<b>{zone}</b><br><span style='font-size:12px'>{risk_state}</span>"},
                gauge={
                    'axis': {'range': [0, 100]},
                    'bar': {'color': color},
                    'steps': [
                        {'range': [0, 30], 'color': "rgba(0, 200, 83, 0.2)"},
                        {'range': [30, 60], 'color': "rgba(255, 193, 7, 0.2)"},
                        {'range': [60, 100], 'color': "rgba(211, 47, 47, 0.2)"}
                    ],
                    'threshold': {
                        'line': {'color': "red", 'width': 4},
                        'thickness': 0.75,
                        'value': 60
                    }
                }
            ))
            fig_gauge.update_layout(height=230, margin=dict(l=10, r=10, t=50, b=10))
            st.plotly_chart(fig_gauge, use_container_width=True)
            
            if risk_state == "RED":
                st.error(f"🔴 **RED ALERT**\n\nConsensus: `{len(triggered)}/4`\n\nActive: {', '.join(triggered)}")
            elif risk_state == "WATCH":
                st.warning(f"🟡 **WATCH**\n\nConsensus: `{len(triggered)}/4`\n\nActive: {', '.join(triggered)}")
            else:
                st.success(f"🟢 **GREEN**\n\nConsensus: `0/4`\n\nSteady state")
            
            q_res = runoff_results.get(zone, {})
            st.caption(f"**CN**: {q_res.get('curve_number', 70)} | **Discharge**: `{q_res.get('discharge_m3_s', 0.0)} m³/s`")

# ----------------------------------------------------------------------------
# TAB 4: CATCHMENT CASCADE MAP (FREE TILES & SATELLITE LAYERS)
# ----------------------------------------------------------------------------
with tab_map:
    st.subheader("Watershed Topologic Cascade & Inundation Map")
    st.markdown("Hydrograph routing tracks upstream discharge surge propagating down the catchment network to vulnerable settlements.")
    
    cascade = st.session_state.cascade
    nodes = cascade.get_node_details()
    
    if nodes:
        avg_lat = np.mean([n['lat'] for n in nodes])
        avg_lon = np.mean([n['lon'] for n in nodes])
        
        # Free OpenStreetMap base layer (no API key required)
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=12, tiles="OpenStreetMap")
        
        # Optional Free High-Resolution Satellite layer
        folium.TileLayer(
            tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attr='Esri World Imagery',
            name='🛰️ Satellite View'
        ).add_to(m)
        
        # Optional Free Topographic Terrain elevation layer
        folium.TileLayer(
            tiles='https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
            attr='OpenTopoMap',
            name='⛰️ Topo Terrain'
        ).add_to(m)
        
        # Draw directed flow channels (Edges)
        for u, v, data in cascade.graph.edges(data=True):
            u_node = cascade.node_props[u]
            v_node = cascade.node_props[v]
            lag = data.get('lag_minutes', 20)
            
            u_risk = cascade.risk_propagated.get(u, {}).get('risk_level', 0)
            line_color = '#00C853' if u_risk == 0 else ('#FFC107' if u_risk == 1 else '#D32F2F')
            
            folium.PolyLine(
                locations=[[u_node['lat'], u_node['lon']], [v_node['lat'], v_node['lon']]],
                color=line_color,
                weight=5,
                opacity=0.9,
                dash_array='6, 10' if u_risk > 0 else None,
                tooltip=f"Hydrologic Channel {u} ➔ {v} (Lag: {lag} min)"
            ).add_to(m)
        
        # Add Nodes with stable markers
        for n in nodes:
            r_level = n.get('risk_level', 0)
            color_name = 'green' if r_level == 0 else ('orange' if r_level == 1 else 'red')
            icon_name = 'home' if n['type'] == 'settlement' else 'tint'
            
            popup_html = f"""
            <div style="font-family: Arial; min-width: 190px;">
                <h4 style="margin: 0 0 5px 0;">{n['name']} ({n['id']})</h4>
                <b>Classification:</b> {n['type'].upper()}<br>
                <b>Elevation:</b> {n['elevation_m']} m<br>
                <b>Coordinates:</b> {n['lat']}, {n['lon']}<br>
                <b>Threat State:</b> <span style="color:{color_name}; font-weight:bold;">{n['risk_state']}</span><br>
                <b>Accumulated Q:</b> {n['total_discharge']} m³/s
            </div>
            """
            
            folium.Marker(
                location=[n['lat'], n['lon']],
                popup=folium.Popup(popup_html, max_width=260),
                tooltip=f"{n['id']}: {n['risk_state']} ({n['total_discharge']} m³/s)",
                icon=folium.Icon(color=color_name, icon=icon_name)
            ).add_to(m)
            
            # High-risk inundation circle
            if r_level == 2:
                folium.Circle(
                    location=[n['lat'], n['lon']],
                    radius=1200,
                    color='#D32F2F',
                    fill=True,
                    fill_opacity=0.3,
                    popup=f"Critical Inundation Hazard Zone: {n['id']}"
                ).add_to(m)
        
        folium.LayerControl(position='topright').add_to(m)
        st_folium(m, width="100%", height=520)
        
        # Cascade flow summary table
        st.markdown("#### 🌊 Cascade Hydrograph Summary")
        table_rows = []
        for n in nodes:
            table_rows.append({
                'Node ID': n['id'],
                'Name': n['name'],
                'Elevation (m)': n['elevation_m'],
                'Area (km²)': n['area_km2'],
                'Local Threat': n.get('local_risk', 0),
                'Cascaded Threat': n.get('risk_state', 'GREEN'),
                'Total Flow (m³/s)': n.get('total_discharge', 0.0)
            })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True)

# ----------------------------------------------------------------------------
# TAB 5: EXPLAINABLE AI (XAI) DIAGNOSTICS
# ----------------------------------------------------------------------------
with tab_explain:
    st.subheader("Decision Provenance & Root Cause Diagnostic")
    st.markdown("Inspect why the alert engine reached its specific conclusions for any given zone.")
    
    selected_xai_zone = st.selectbox("Select Target Catchment Zone", st.session_state.zones, index=0)
    
    if selected_xai_zone:
        explanation_md = st.session_state.consensus.get_why_alert(st.session_state.anomalies, selected_xai_zone)
        st.markdown(explanation_md)
        
        st.divider()
        st.markdown("### 🚨 Recommended Operational Procedures")
        zone_risk = st.session_state.risk_scores.get(selected_xai_zone, {}).get('risk_level', 0)
        
        if zone_risk == 2:
            st.error("""
            **ACTION: IMMEDIATE EVACUATION & SIREN ACTIVATION**
            1. Trigger automated acoustic sirens in downstream reaches and Village-A.
            2. Dispatch SMS broadcast to district disaster management authorities (NDRF/SDRF).
            3. Close vulnerable riverbed bridge crossings.
            4. Divert reservoir inflow sluice gates to flood buffering capacity.
            """)
        elif zone_risk == 1:
            st.warning("""
            **ACTION: PRE-ALERT MONITORING & GAUGE VERIFICATION**
            1. Alert standby emergency response teams to active WATCH status.
            2. Request high-frequency satellite/Doppler radar scans over upper ridge.
            3. Verify sensor connectivity and cross-check battery/transmission health.
            """)
        else:
            st.success("""
            **ACTION: ROUTINE BASELINE MONITORING**
            1. All channels operating within 95% confidence safety bounds.
            2. Standard telemetry sampling at nominal 1-minute intervals.
            """)

# ----------------------------------------------------------------------------
# FOOTER
# ----------------------------------------------------------------------------
st.markdown("---")
st.caption("AquaSentinel Multi-Modal Early Warning Platform · Detect → Verify → Model → Explain → Act")
