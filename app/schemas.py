from pydantic import BaseModel, Field
from typing import Optional,List

class ONUList(BaseModel):
    device_id: str
    serial_number: str
    manufacturer: str
    model: str
    hardware_software_version: str
    ip_address: str
    mac_address: str
    optical_power_rx: float
    optical_power_tx: float
    last_inform_timestamp: int
    status: str
    pppoe_username: Optional[str] = "" 
    cpu_usage: str  
    ram_usage: str  
    uptime: str

class ONUDetails(BaseModel):
    device_summary: dict
    lan_status: dict
    wan_ip_pppoe: dict
    optical_pon_stats: dict
    wifi_configuration: dict

class WANConfig(BaseModel):
    username: str
    password: str
    vlan_id: int

class WiFiConfig(BaseModel):
    ssid: str
    password: str
    band: Optional[str] = "2.4GHz"
    status: Optional[str] = "Enabled"

class LANHost(BaseModel):
    hostname: str
    ip_address: str
    mac_address: str

class LANHostResponse(BaseModel):
    total_connected: int
    hosts: List[LANHost]

class PingRequest(BaseModel):
    host: str
    count: int = 4

class PingResponse(BaseModel):
    host: str
    status: str
    packets_sent: int
    packets_received: int
    packets_lost: int
    avg_response_time_ms: float
    min_response_time_ms: float
    max_response_time_ms: float

class TraceRouteHop(BaseModel):
    hop_number: int
    host: str
    host_address: str
    rtt_ms: str

class TraceRouteRequest(BaseModel):
    host: str

class TraceRouteResponse(BaseModel):
    host: str
    status: str
    total_hops: int
    hops: List[TraceRouteHop]

class WiFiUpdateRequest(BaseModel):
    ssid: str
    password: str