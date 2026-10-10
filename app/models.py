from sqlalchemy import Column, String, Integer, Float, DateTime, func
from .database import Base

class ONUModel(Base):
    __tablename__ = "onus"

    device_id = Column(String(255), primary_key=True, index=True)
    serial_number = Column(String(100), nullable=False, index=True)
    manufacturer = Column(String(100), default="Huawei")
    model = Column(String(100), default="Unknown")
    hardware_software_version = Column(String(100), default="")
    ip_address = Column(String(45), default="")
    mac_address = Column(String(45), default="")
    
    optical_power_rx = Column(Float, default=0.0)
    optical_power_tx = Column(Float, default=0.0)
    cpu_usage = Column(String(20), default="N/A")
    ram_usage = Column(String(20), default="N/A")
    uptime = Column(String(50), default="N/A")
    status = Column(String(20), default="Offline")
    last_inform_timestamp = Column(Integer, default=0)

    # Wi-Fi & PPPoE Credentials
    wifi_ssid = Column(String(100), default="N/A")
    wifi_password = Column(String(100), default="N/A")
    pppoe_username = Column(String(100), default="N/A", index=True)
    pppoe_password = Column(String(100), default="N/A")
    vlan_id = Column(Integer, default=0)

    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SuppressedHost(Base):
    __tablename__ = "suppressed_hosts"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(255), nullable=False, index=True)
    mac_address = Column(String(45), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())