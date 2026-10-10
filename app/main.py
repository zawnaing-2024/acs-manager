import time
import asyncio
import urllib.parse
from datetime import datetime
from typing import List, Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings, SettingsConfigDict

from .auth import (
    Token, 
    User, 
    verify_password, 
    create_access_token, 
    get_current_user, 
    DEMO_USERS_DB
)
from .genieacs_client import GenieACSClient, extract_param
from .schemas import (
    ONUList, WANConfig, WiFiConfig, LANHostResponse, LANHost,
    PingRequest, PingResponse, TraceRouteRequest, TraceRouteResponse, 
    WiFiUpdateRequest, WANUpdateRequest
)

load_dotenv()


class Settings(BaseSettings):
    GENIEACS_NBI_URL: str = "http://37.111.50.139:7557"
    API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()

app = FastAPI(title="ISP ACS Management API", version="1.0.0")

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


# --- AUTHENTICATION ENDPOINTS ---

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


# --- PROTECTED ONU MANAGEMENT ENDPOINTS ---

@app.get("/api/v1/onus", response_model=List[ONUList], tags=["ONU List"])
async def get_onu_list(
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    try:
        devices = await client.get_devices()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch devices from GenieACS: {str(e)}"
        )

    onus = []
    for device in devices:
        device_id = str(device.get("_id", ""))
        if not device_id or "DISCOVERYSERVICE" in device_id:
            continue

        # 1. Serial Number
        device_id_meta = device.get("_deviceId", {})
        sn = device_id_meta.get("_SerialNumber") or extract_param(
            device, "InternetGatewayDevice.DeviceInfo.SerialNumber", 
            extract_param(device, "Device.DeviceInfo.SerialNumber", "Unknown")
        )

        # 2. Manufacturer & Model Name
        mfg = device_id_meta.get("_Manufacturer") or extract_param(
            device, "InternetGatewayDevice.DeviceInfo.Manufacturer", "Huawei"
        )
        model = device_id_meta.get("_ProductClass") or extract_param(
            device, "InternetGatewayDevice.DeviceInfo.ModelName", 
            extract_param(device, "Device.DeviceInfo.ModelName", "Unknown")
        )

        # 3. Firmware & Hardware Version
        hw_sw_ver = str(
            extract_param(device, "InternetGatewayDevice.DeviceInfo.HardwareVersion", "") or
            extract_param(device, "InternetGatewayDevice.DeviceInfo.SoftwareVersion", "")
        )

        # 4. Management IP
        ip_address = str(
            device.get("_ip") or 
            extract_param(
                device, 
                "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.ExternalIPAddress"
            ) or 
            extract_param(
                device, 
                "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.3.WANPPPConnection.1.ExternalIPAddress"
            ) or
            extract_param(
                device, 
                "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.2.WANPPPConnection.1.ExternalIPAddress"
            )
        )

        # 5. MAC Address
        mac_address = str(
            extract_param(
                device, 
                "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.1.MACAddress", 
                ""
            )
        )

        # 6. Optical Power (Rx / Tx)
        rx_power_raw = extract_param(device, "InternetGatewayDevice.WANDevice.1.X_GponInterafceConfig.RXPower", None)
        if rx_power_raw is None:
            rx_power_raw = extract_param(device, "InternetGatewayDevice.WANDevice.1.X_HW_PONInterfaceConfig.RxOpticalPower", 0.0)
            
        tx_power_raw = extract_param(device, "InternetGatewayDevice.WANDevice.1.X_GponInterafceConfig.TXPower", None)
        if tx_power_raw is None:
            tx_power_raw = extract_param(device, "InternetGatewayDevice.WANDevice.1.X_HW_PONInterfaceConfig.TxOpticalPower", 0.0)

        try:
            optical_rx = float(rx_power_raw)
        except (ValueError, TypeError):
            optical_rx = 0.0

        try:
            optical_tx = float(tx_power_raw)
        except (ValueError, TypeError):
            optical_tx = 0.0

        # 7. Last Inform Timestamp & Online Status
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

        is_online = (last_inform_ts > 0) and ((time.time() - last_inform_ts) < 300)

        # 8. PPPoE Username (Checking WAN index 1, 2, 3, 4)
        pppoe_user = ""
        for i in ["1", "2", "3", "4"]:
            user_check = extract_param(
                device, f"InternetGatewayDevice.WANDevice.1.WANConnectionDevice.{i}.WANPPPConnection.1.Username"
            )
            if user_check:
                pppoe_user = str(user_check)
                break

        # 9. CPU & RAM Usage
        cpu = extract_param(device, "InternetGatewayDevice.DeviceInfo.X_HW_CpuUsed") or \
              extract_param(device, "InternetGatewayDevice.DeviceInfo.ProcessStatus.CPUUsage")
        cpu_usage = f"{cpu}%" if cpu else "N/A"

        ram = extract_param(device, "InternetGatewayDevice.DeviceInfo.X_HW_MemUsed")
        if ram:
            ram_usage = f"{ram}%"
        else:
            total_mem = extract_param(device, "InternetGatewayDevice.DeviceInfo.MemoryStatus.Total")
            free_mem = extract_param(device, "InternetGatewayDevice.DeviceInfo.MemoryStatus.Free")
            if total_mem and free_mem:
                try:
                    used_pct = ((float(total_mem) - float(free_mem)) / float(total_mem)) * 100
                    ram_usage = f"{int(used_pct)}%"
                except (ValueError, TypeError):
                    ram_usage = "N/A"
            else:
                ram_usage = "N/A"

        # 10. Uptime
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

        onus.append(
            ONUList(
                device_id=device_id,
                serial_number=str(sn),
                manufacturer=str(mfg),
                model=str(model),
                hardware_software_version=hw_sw_ver,
                ip_address=ip_address,
                mac_address=mac_address,
                optical_power_rx=optical_rx,
                optical_power_tx=optical_tx,
                last_inform_timestamp=last_inform_ts,
                status="Online" if is_online else "Offline",
                pppoe_username=pppoe_user,
                cpu_usage=cpu_usage,
                ram_usage=ram_usage,
                uptime=uptime_str
            )
        )

    return onus


@app.get("/api/v1/onus/{device_id:path}/wifi", response_model=WiFiConfig, tags=["Wi-Fi Settings"])
async def get_wifi_settings(
    device_id: str, 
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    try:
        decoded_id = urllib.parse.unquote(device_id)
        data = await client.get_wifi_settings(decoded_id)
        return WiFiConfig(**data)
    except Exception as e:
        return WiFiConfig(ssid="N/A", password="N/A", band="2.4GHz", status="Disabled")


@app.put("/api/v1/onus/{device_id:path}/wifi", tags=["Wi-Fi Settings"])
async def update_wifi_settings(
    device_id: str, 
    req: WiFiUpdateRequest, 
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    try:
        decoded_id = urllib.parse.unquote(device_id)
        return await client.update_wifi_settings(decoded_id, req.ssid, req.password)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update Wi-Fi: {str(e)}")


@app.get("/api/v1/onus/{device_id:path}/wan", response_model=WANConfig, tags=["WAN Configuration"])
async def get_wan_config(
    device_id: str, 
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    try:
        decoded_id = urllib.parse.unquote(device_id)
        data = await client.get_wan_config(decoded_id)
        return WANConfig(**data)
    except Exception as e:
        return WANConfig(username="N/A", password="N/A", vlan_id=0)


@app.put("/api/v1/onus/{device_id:path}/wan", tags=["WAN Configuration"])
async def update_wan_config(
    device_id: str, 
    req: WANUpdateRequest, 
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    try:
        decoded_id = urllib.parse.unquote(device_id)
        return await client.update_wan_settings(decoded_id, req.username, req.password, req.vlan_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update WAN settings: {str(e)}")


@app.get("/api/v1/onus/{device_id:path}/hosts", response_model=LANHostResponse, tags=["LAN Hosts"])
async def get_lan_hosts(
    device_id: str, 
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    try:
        decoded_id = urllib.parse.unquote(device_id)
        try:
            await client.refresh_object(decoded_id, "InternetGatewayDevice.LANDevice.1.Hosts.Host")
            await asyncio.sleep(1.5)
        except Exception:
            pass

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
    except Exception as e:
        return LANHostResponse(total_connected=0, hosts=[])


@app.post("/api/v1/onus/{device_id:path}/diagnostics/ping", response_model=PingResponse, tags=["Diagnostics"])
async def execute_ping(
    device_id: str, 
    req: PingRequest, 
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    try:
        decoded_id = urllib.parse.unquote(device_id)
        result = await client.run_ping(decoded_id, req.host, req.count)
        return PingResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ping diagnostic failed: {str(e)}")


@app.post("/api/v1/onus/{device_id:path}/diagnostics/traceroute", response_model=TraceRouteResponse, tags=["Diagnostics"])
async def execute_traceroute(
    device_id: str, 
    req: TraceRouteRequest, 
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    try:
        decoded_id = urllib.parse.unquote(device_id)
        result = await client.run_traceroute(decoded_id, req.host)
        return TraceRouteResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Traceroute diagnostic failed: {str(e)}")


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
    client: GenieACSClient = Depends(get_genieacs_client),
    current_user: User = Depends(get_current_user)
):
    decoded_id = urllib.parse.unquote(device_id)
    return await client.delete_device(decoded_id)