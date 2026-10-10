import time
import asyncio
import urllib.parse
from datetime import datetime
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .auth import (
    Token, 
    User, 
    verify_password, 
    create_access_token, 
    get_current_user, 
    DEMO_USERS_DB
)
from .genieacs_client import GenieACSClient, extract_param
from .database import get_db, init_db
from .models import ONUModel
from .schemas import (
    ONUList, WANConfig, WiFiConfig, LANHostResponse, LANHost,
    PingRequest, PingResponse, TraceRouteRequest, TraceRouteResponse, 
    WiFiUpdateRequest, WANUpdateRequest
)

load_dotenv()


class Settings(BaseSettings):
    GENIEACS_NBI_URL: str = "http://37.111.50.139:7557"
    API_KEY: Optional[str] = None
    
    # Database Settings
    DB_USER: str = "oneacs"
    DB_PASSWORD: str = "One@2026"
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_NAME: str = "acs_manager"

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore"  # Instructs Pydantic to ignore any unlisted env variables
    )


settings = Settings()

app = FastAPI(title="ISP ACS Management API - Phase 2", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)


def get_genieacs_client():
    return GenieACSClient(settings.GENIEACS_NBI_URL, settings.API_KEY)


@app.on_event("startup")
async def on_startup():
    await init_db()


# --- AUTHENTICATION ---

@app.post("/api/v1/auth/login", response_model=Token, tags=["Auth"])
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user_dict = DEMO_USERS_DB.get(form_data.username)
    if not user_dict or not verify_password(form_data.password, user_dict["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user_dict["username"]})
    return Token(
        access_token=access_token,
        token_type="bearer",
        username=user_dict["username"],
        full_name=user_dict["full_name"]
    )


@app.get("/api/v1/auth/me", response_model=User, tags=["Auth"])
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user


# --- SYNC HELPER: GenieACS -> MySQL ---

async def sync_genieacs_to_db(db: AsyncSession, client: GenieACSClient):
    """Imports devices from GenieACS, extracts multi-vendor VLAN IDs, and updates MySQL records."""
    try:
        devices = await client.get_devices()
        current_time_sec = int(time.time())

        for device in devices:
            device_id = str(device.get("_id", ""))
            if not device_id or "DISCOVERYSERVICE" in device_id:
                continue

            device_id_meta = device.get("_deviceId", {})
            sn = str(device_id_meta.get("_SerialNumber") or extract_param(
                device, "InternetGatewayDevice.DeviceInfo.SerialNumber", "Unknown"
            ))
            mfg = str(device_id_meta.get("_Manufacturer") or "Huawei")
            model = str(device_id_meta.get("_ProductClass") or extract_param(
                device, "InternetGatewayDevice.DeviceInfo.ModelName", "Unknown"
            ))
            hw_sw_ver = str(
                extract_param(device, "InternetGatewayDevice.DeviceInfo.HardwareVersion", "") or
                extract_param(device, "InternetGatewayDevice.DeviceInfo.SoftwareVersion", "")
            )

            ip_address = str(
                device.get("_ip") or 
                extract_param(device, "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.ExternalIPAddress", "")
            )
            mac_address = str(
                extract_param(device, "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.MACAddress", "")
            )

            # Optical Power
            rx_power_raw = extract_param(device, "InternetGatewayDevice.WANDevice.1.X_GponInterafceConfig.RXPower", 
                           extract_param(device, "InternetGatewayDevice.WANDevice.1.X_HW_PONInterfaceConfig.RxOpticalPower", 0.0))
            tx_power_raw = extract_param(device, "InternetGatewayDevice.WANDevice.1.X_GponInterafceConfig.TXPower", 
                           extract_param(device, "InternetGatewayDevice.WANDevice.1.X_HW_PONInterfaceConfig.TxOpticalPower", 0.0))

            try:
                rx_power = float(rx_power_raw)
            except (ValueError, TypeError):
                rx_power = 0.0

            try:
                tx_power = float(tx_power_raw)
            except (ValueError, TypeError):
                tx_power = 0.0

            # CPU & RAM Usage
            cpu_val = extract_param(device, "InternetGatewayDevice.DeviceInfo.X_HW_CpuUsed") or \
                      extract_param(device, "InternetGatewayDevice.DeviceInfo.ProcessStatus.CPUUsage")
            cpu_str = f"{cpu_val}%" if cpu_val is not None and str(cpu_val) not in ["None", ""] else "N/A"

            ram_val = extract_param(device, "InternetGatewayDevice.DeviceInfo.X_HW_MemUsed")
            if ram_val is not None and str(ram_val) not in ["None", ""]:
                ram_str = f"{ram_val}%"
            else:
                total_mem = extract_param(device, "InternetGatewayDevice.DeviceInfo.MemoryStatus.Total")
                free_mem = extract_param(device, "InternetGatewayDevice.DeviceInfo.MemoryStatus.Free")
                if total_mem and free_mem:
                    try:
                        used_pct = ((float(total_mem) - float(free_mem)) / float(total_mem)) * 100
                        ram_str = f"{int(used_pct)}%"
                    except (ValueError, TypeError):
                        ram_str = "N/A"
                else:
                    ram_str = "N/A"

            # Uptime
            uptime_raw = extract_param(device, "InternetGatewayDevice.DeviceInfo.UpTime") or \
                         extract_param(device, "Device.DeviceInfo.UpTime")
            if uptime_raw:
                try:
                    seconds = int(uptime_raw)
                    days = seconds // 86400
                    hours = (seconds % 86400) // 3600
                    minutes = (seconds % 3600) // 60
                    uptime_str = f"{days}d {hours}h {minutes}m" if days > 0 else f"{hours}h {minutes}m"
                except (ValueError, TypeError):
                    uptime_str = "N/A"
            else:
                uptime_str = "N/A"

            # Last Inform & Online Status
            last_inform_raw = device.get("_lastInform")
            last_inform_ts = 0

            if last_inform_raw:
                if isinstance(last_inform_raw, (int, float)):
                    last_inform_ts = int(last_inform_raw / 1000) if last_inform_raw > 1e11 else int(last_inform_raw)
                elif isinstance(last_inform_raw, str):
                    try:
                        clean_time_str = last_inform_raw.replace('Z', '+00:00')
                        dt = datetime.fromisoformat(clean_time_str)
                        last_inform_ts = int(dt.timestamp())
                    except ValueError:
                        last_inform_ts = 0

            is_online = (last_inform_ts > 0) and ((current_time_sec - last_inform_ts) < 300)
            status_str = "Online" if is_online else "Offline"

            # Comprehensive Multi-Vendor PPPoE & VLAN Extraction across indices 1 to 4
            pppoe_user, pppoe_pass, vlan_id = "N/A", "N/A", 0
            for i in ["1", "2", "3", "4"]:
                base = f"InternetGatewayDevice.WANDevice.1.WANConnectionDevice.{i}.WANPPPConnection.1"
                u_val = extract_param(device, f"{base}.Username")
                if u_val and str(u_val) not in ["None", "", "{}"]:
                    pppoe_user = str(u_val)
                    p_val = extract_param(device, f"{base}.Password", extract_param(device, f"{base}.X_HW_Password", "N/A"))
                    pppoe_pass = str(p_val) if p_val and str(p_val) not in ["None", "", "{}"] else "N/A"
                    
                    # Multi-vendor VLAN Parameter Lookups
                    v_val = (
                        extract_param(device, f"{base}.X_HW_VLAN") or
                        extract_param(device, f"{base}.VLANID") or
                        extract_param(device, f"{base}.VLANIDMark") or
                        extract_param(device, f"InternetGatewayDevice.WANDevice.1.WANConnectionDevice.{i}.X_HW_VLAN") 
            
                    )
                    try:
                        vlan_id = int(v_val)
                    except (ValueError, TypeError):
                        vlan_id = 0
                    break

            ssid = str(extract_param(device, "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID", "N/A"))
            wifi_pass = str(extract_param(device, "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.PreSharedKey.1.PreSharedKey", "N/A"))

            # Check existing DB record
            result = await db.execute(select(ONUModel).where(ONUModel.device_id == device_id))
            onu_db = result.scalar_one_or_none()

            if not onu_db:
                onu_db = ONUModel(
                    device_id=device_id,
                    serial_number=sn,
                    manufacturer=mfg,
                    model=model,
                    hardware_software_version=hw_sw_ver,
                    ip_address=ip_address,
                    mac_address=mac_address,
                    optical_power_rx=rx_power,
                    optical_power_tx=tx_power,
                    cpu_usage=cpu_str,
                    ram_usage=ram_str,
                    uptime=uptime_str,
                    status=status_str,
                    last_inform_timestamp=last_inform_ts,
                    wifi_ssid=ssid,
                    wifi_password=wifi_pass,
                    pppoe_username=pppoe_user,
                    pppoe_password=pppoe_pass,
                    vlan_id=vlan_id
                )
                db.add(onu_db)
            else:
                # Update all fields on existing DB records
                onu_db.ip_address = ip_address
                onu_db.optical_power_rx = rx_power
                onu_db.optical_power_tx = tx_power
                onu_db.cpu_usage = cpu_str
                onu_db.ram_usage = ram_str
                onu_db.uptime = uptime_str
                onu_db.status = status_str
                onu_db.last_inform_timestamp = last_inform_ts
                
                # Update VLAN and credentials if found in GenieACS and currently default
                if pppoe_user != "N/A":
                    onu_db.pppoe_username = pppoe_user
                if pppoe_pass != "N/A":
                    onu_db.pppoe_password = pppoe_pass
                if vlan_id > 0:
                    onu_db.vlan_id = vlan_id

        await db.commit()
    except Exception as e:
        print(f"[DB Sync Warning] {e}")


# --- ONU API ENDPOINTS ---

@app.get("/api/v1/onus", response_model=List[ONUList], tags=["ONU List"])
async def get_onu_list(
    db: AsyncSession = Depends(get_db),
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    # Perform background sync & return fast DB result
    asyncio.create_task(sync_genieacs_to_db(db, client))

    result = await db.execute(select(ONUModel))
    db_onus = result.scalars().all()

    response_list = []
    for onu in db_onus:
        response_list.append(
            ONUList(
                device_id=onu.device_id,
                serial_number=onu.serial_number,
                manufacturer=onu.manufacturer,
                model=onu.model,
                hardware_software_version=onu.hardware_software_version,
                ip_address=onu.ip_address,
                mac_address=onu.mac_address,
                optical_power_rx=onu.optical_power_rx,
                optical_power_tx=onu.optical_power_tx,
                last_inform_timestamp=onu.last_inform_timestamp,
                status=onu.status,
                pppoe_username=onu.pppoe_username,
                cpu_usage=onu.cpu_usage or "N/A",
                ram_usage=onu.ram_usage or "N/A",
                uptime=onu.uptime or "N/A"
            )
        )
    return response_list


@app.get("/api/v1/onus/{device_id:path}/wifi", response_model=WiFiConfig, tags=["Wi-Fi Settings"])
async def get_wifi_settings(
    device_id: str, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    decoded_id = urllib.parse.unquote(device_id)
    result = await db.execute(select(ONUModel).where(ONUModel.device_id == decoded_id))
    onu = result.scalar_one_or_none()

    if onu:
        return WiFiConfig(
            ssid=onu.wifi_ssid,
            password=onu.wifi_password,
            band="2.4GHz",
            status="Enabled"
        )
    return WiFiConfig(ssid="N/A", password="N/A", band="2.4GHz", status="Disabled")


@app.put("/api/v1/onus/{device_id:path}/wifi", tags=["Wi-Fi Settings"])
async def update_wifi_settings(
    device_id: str, 
    req: WiFiUpdateRequest, 
    db: AsyncSession = Depends(get_db),
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    decoded_id = urllib.parse.unquote(device_id)
    
    # 1. TR-069 Push to router
    await client.update_wifi_settings(decoded_id, req.ssid, req.password)

    # 2. Save in MySQL
    result = await db.execute(select(ONUModel).where(ONUModel.device_id == decoded_id))
    onu = result.scalar_one_or_none()
    if onu:
        onu.wifi_ssid = req.ssid
        onu.wifi_password = req.password
        await db.commit()

    return {"status": "success", "message": "Wi-Fi updated on router & saved in Database"}


@app.get("/api/v1/onus/{device_id:path}/wan", response_model=WANConfig, tags=["WAN Configuration"])
async def get_wan_config(
    device_id: str, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    decoded_id = urllib.parse.unquote(device_id)
    result = await db.execute(select(ONUModel).where(ONUModel.device_id == decoded_id))
    onu = result.scalar_one_or_none()

    if onu:
        return WANConfig(
            username=onu.pppoe_username,
            password=onu.pppoe_password,
            vlan_id=onu.vlan_id
        )
    return WANConfig(username="N/A", password="N/A", vlan_id=0)


@app.put("/api/v1/onus/{device_id:path}/wan", tags=["WAN Configuration"])
async def update_wan_config(
    device_id: str, 
    req: WANUpdateRequest, 
    db: AsyncSession = Depends(get_db),
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    decoded_id = urllib.parse.unquote(device_id)

    # 1. TR-069 Push to router
    await client.update_wan_settings(decoded_id, req.username, req.password, req.vlan_id)

    # 2. Save in MySQL
    result = await db.execute(select(ONUModel).where(ONUModel.device_id == decoded_id))
    onu = result.scalar_one_or_none()
    if onu:
        onu.pppoe_username = req.username
        onu.pppoe_password = req.password
        onu.vlan_id = req.vlan_id
        await db.commit()

    return {"status": "success", "message": "WAN updated on router & saved in Database"}


@app.get("/api/v1/onus/{device_id:path}/hosts", response_model=LANHostResponse, tags=["LAN Hosts"])
async def get_lan_hosts(
    device_id: str, 
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    try:
        decoded_id = urllib.parse.unquote(device_id)
        device = await client.get_device(decoded_id)
        hosts_dict = device.get("InternetGatewayDevice", {}).get("LANDevice", {}).get("1", {}).get("Hosts", {}).get("Host", {})

        active_hosts = []
        if isinstance(hosts_dict, dict):
            for host_id, host_data in hosts_dict.items():
                if not str(host_id).isdigit():
                    continue

                hostname = extract_param(host_data, "HostName", "Unknown Device")
                ip_address = extract_param(host_data, "IPAddress", "0.0.0.0")
                mac_address = extract_param(host_data, "MACAddress", "Unknown MAC")

                if ip_address and ip_address != "0.0.0.0":
                    active_hosts.append(LANHost(
                        hostname=str(hostname),
                        ip_address=str(ip_address),
                        mac_address=str(mac_address)
                    ))

        return LANHostResponse(total_connected=len(active_hosts), hosts=active_hosts)
    except Exception:
        return LANHostResponse(total_connected=0, hosts=[])


@app.post("/api/v1/onus/{device_id:path}/diagnostics/ping", response_model=PingResponse, tags=["Diagnostics"])
async def execute_ping(
    device_id: str, 
    req: PingRequest, 
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    decoded_id = urllib.parse.unquote(device_id)
    result = await client.run_ping(decoded_id, req.host, req.count)
    return PingResponse(**result)


@app.post("/api/v1/onus/{device_id:path}/diagnostics/traceroute", response_model=TraceRouteResponse, tags=["Diagnostics"])
async def execute_traceroute(
    device_id: str, 
    req: TraceRouteRequest, 
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    decoded_id = urllib.parse.unquote(device_id)
    result = await client.run_traceroute(decoded_id, req.host)
    return TraceRouteResponse(**result)


@app.post("/api/v1/onus/{device_id:path}/reboot", tags=["Actions"])
async def reboot_onu(
    device_id: str, 
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    decoded_id = urllib.parse.unquote(device_id)
    return await client.reboot_device(decoded_id)


@app.delete("/api/v1/onus/{device_id:path}", tags=["Actions"])
async def delete_onu(
    device_id: str, 
    db: AsyncSession = Depends(get_db),
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    decoded_id = urllib.parse.unquote(device_id)
    await client.delete_device(decoded_id)

    # Remove from DB
    result = await db.execute(select(ONUModel).where(ONUModel.device_id == decoded_id))
    onu = result.scalar_one_or_none()
    if onu:
        await db.delete(onu)
        await db.commit()

    return {"status": "success", "message": "Device deleted from GenieACS and Database"}