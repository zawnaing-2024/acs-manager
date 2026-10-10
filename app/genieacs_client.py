import httpx
import urllib.parse
import json
import asyncio
from typing import Optional, List, Dict, Any


def extract_param(device_data: dict, path: str, default: Any = "") -> Any:
    """Helper to safely extract primitive values or inner '_value' fields from GenieACS JSON trees."""
    if not device_data or not isinstance(device_data, dict):
        return default

    keys = path.split(".")
    curr = device_data

    for key in keys:
        if isinstance(curr, dict) and key in curr:
            curr = curr[key]
        else:
            return default

    if isinstance(curr, dict):
        if "_value" in curr:
            val = curr["_value"]
            return val if val is not None else default
        return default

    return curr if curr is not None else default


class GenieACSClient:
    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    async def get_devices(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/devices"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers, timeout=10.0)
            response.raise_for_status()
            return response.json()

    async def get_device(self, device_id: str) -> Dict[str, Any]:
        query = urllib.parse.quote(json.dumps({"_id": device_id}))
        url = f"{self.base_url}/devices/?query={query}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers, timeout=10.0)
            response.raise_for_status()
            devices = response.json()
            if not devices:
                raise httpx.HTTPStatusError("Device not found", request=response.request, response=response)
            return devices[0]

    async def refresh_object(self, device_id: str, object_name: str):
        """Force GenieACS to pull live data from physical router."""
        encoded_id = urllib.parse.quote(device_id)
        url = f"{self.base_url}/devices/{encoded_id}/tasks?connection_request"
        payload = {
            "name": "refreshObject",
            "objectName": object_name
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=self.headers, timeout=10.0)
            response.raise_for_status()
            return response.json()

    async def reboot_device(self, device_id: str):
        """Send TR-069 reboot command to the router."""
        encoded_id = urllib.parse.quote(device_id)
        url = f"{self.base_url}/devices/{encoded_id}/tasks?connection_request"
        payload = {"name": "reboot"}
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=self.headers, timeout=10.0)
            if response.status_code >= 400:
                fallback_url = f"{self.base_url}/tasks?connection_request"
                fallback_payload = {"name": "reboot", "device": device_id}
                response = await client.post(fallback_url, json=fallback_payload, headers=self.headers, timeout=10.0)
                
            response.raise_for_status()
            return {"status": "success", "message": "Reboot queued"}

    async def delete_device(self, device_id: str):
        """Delete device from GenieACS using official REST NBI specs."""
        encoded_id = urllib.parse.quote(device_id, safe='')
        
        async with httpx.AsyncClient() as client:
            try:
                task_query = urllib.parse.quote(json.dumps({"device": device_id}))
                await client.delete(f"{self.base_url}/tasks/{task_query}", headers=self.headers, timeout=5.0)
            except Exception as e:
                print(f"[Backend] Task purge warning: {e}")

            delete_url = f"{self.base_url}/devices/{encoded_id}"
            response = await client.delete(delete_url, headers=self.headers, timeout=10.0)

            if response.status_code not in [200, 204, 404]:
                response.raise_for_status()

            return {"status": "success", "message": "Device deleted"}

    async def run_ping(self, device_id: str, host: str, count: int = 4) -> Dict[str, Any]:
        """Trigger Ping diagnostic supporting both TR-098 and TR-181 trees."""
        encoded_id = urllib.parse.quote(device_id)
        device = await self.get_device(device_id)

        # 1. Detect active WAN Interface path for binding
        wan_iface = ""
        for i in ["1", "2", "3"]:
            base = f"InternetGatewayDevice.WANDevice.1.WANConnectionDevice.{i}.WANPPPConnection.1"
            if extract_param(device, f"{base}.Username"):
                wan_iface = base
                break

        # 2. Determine Data Model Root (TR-098 vs TR-181)
        is_tr181 = "Device" in device and "InternetGatewayDevice" not in device
        
        if not is_tr181:
            params = [
                ["InternetGatewayDevice.IPPingDiagnostics.Host", host, "xsd:string"],
                ["InternetGatewayDevice.IPPingDiagnostics.NumberOfRepetitions", count, "xsd:unsignedInt"],
                ["InternetGatewayDevice.IPPingDiagnostics.Timeout", 2000, "xsd:unsignedInt"],
                ["InternetGatewayDevice.IPPingDiagnostics.DiagnosticsState", "Requested", "xsd:string"]
            ]
            if wan_iface:
                params.append(["InternetGatewayDevice.IPPingDiagnostics.Interface", wan_iface, "xsd:string"])
            refresh_path = "InternetGatewayDevice.IPPingDiagnostics"
        else:
            params = [
                ["Device.IP.Diagnostics.IPPing.Host", host, "xsd:string"],
                ["Device.IP.Diagnostics.IPPing.NumberOfRepetitions", count, "xsd:unsignedInt"],
                ["Device.IP.Diagnostics.IPPing.Timeout", 2000, "xsd:unsignedInt"],
                ["Device.IP.Diagnostics.IPPing.DiagnosticsState", "Requested", "xsd:string"]
            ]
            refresh_path = "Device.IP.Diagnostics.IPPing"

        # 3. Post Task to ONU
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/devices/{encoded_id}/tasks?connection_request"
            res = await client.post(url, json={"name": "setParameterValues", "parameterValues": params}, headers=self.headers, timeout=10.0)
            res.raise_for_status()

            # Adaptive Wait Loop
            status_str = "Requested"
            diag_tree = {}
            for _ in range(4):
                await asyncio.sleep(2)
                try:
                    await self.refresh_object(device_id, refresh_path)
                except Exception:
                    pass
                
                updated_dev = await self.get_device(device_id)
                diag_tree = updated_dev.get("Device", {}).get("IP", {}).get("Diagnostics", {}).get("IPPing", {}) if is_tr181 else updated_dev.get("InternetGatewayDevice", {}).get("IPPingDiagnostics", {})
                
                status_str = str(extract_param(diag_tree, "DiagnosticsState", "None"))
                if status_str in ["Complete", "Error_CannotResolveHostName", "Error_Internal"]:
                    break

            # 4. Extract Results
            sent = int(extract_param(diag_tree, "NumberOfRepetitions", count))
            received = int(extract_param(diag_tree, "SuccessCount", 0))
            avg_rt = float(extract_param(diag_tree, "AverageResponseTime", 0.0))
            min_rt = float(extract_param(diag_tree, "MinimumResponseTime", 0.0))
            max_rt = float(extract_param(diag_tree, "MaximumResponseTime", 0.0))

            return {
                "host": host,
                "status": status_str,
                "packets_sent": sent,
                "packets_received": received,
                "packets_lost": max(0, sent - received),
                "avg_response_time_ms": avg_rt,
                "min_response_time_ms": min_rt,
                "max_response_time_ms": max_rt
            }

    async def run_traceroute(self, device_id: str, host: str) -> Dict[str, Any]:
        """Trigger TraceRoute diagnostic with WAN binding and adaptive wait polling."""
        encoded_id = urllib.parse.quote(device_id)
        device = await self.get_device(device_id)

        # 1. Detect WAN Interface
        wan_iface = ""
        for i in ["1", "2", "3"]:
            base = f"InternetGatewayDevice.WANDevice.1.WANConnectionDevice.{i}.WANPPPConnection.1"
            if extract_param(device, f"{base}.Username"):
                wan_iface = base
                break

        is_tr181 = "Device" in device and "InternetGatewayDevice" not in device

        if not is_tr181:
            params = [
                ["InternetGatewayDevice.TraceRouteDiagnostics.Host", host, "xsd:string"],
                ["InternetGatewayDevice.TraceRouteDiagnostics.MaxHopCount", 15, "xsd:unsignedInt"],
                ["InternetGatewayDevice.TraceRouteDiagnostics.Timeout", 2000, "xsd:unsignedInt"],
                ["InternetGatewayDevice.TraceRouteDiagnostics.DiagnosticsState", "Requested", "xsd:string"]
            ]
            if wan_iface:
                params.append(["InternetGatewayDevice.TraceRouteDiagnostics.Interface", wan_iface, "xsd:string"])
            refresh_path = "InternetGatewayDevice.TraceRouteDiagnostics"
        else:
            params = [
                ["Device.IP.Diagnostics.TraceRoute.Host", host, "xsd:string"],
                ["Device.IP.Diagnostics.TraceRoute.MaxHopCount", 15, "xsd:unsignedInt"],
                ["Device.IP.Diagnostics.TraceRoute.Timeout", 2000, "xsd:unsignedInt"],
                ["Device.IP.Diagnostics.TraceRoute.DiagnosticsState", "Requested", "xsd:string"]
            ]
            refresh_path = "Device.IP.Diagnostics.TraceRoute"

        # 2. Post Task
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/devices/{encoded_id}/tasks?connection_request"
            res = await client.post(url, json={"name": "setParameterValues", "parameterValues": params}, headers=self.headers, timeout=10.0)
            res.raise_for_status()

            # 3. Adaptive Wait Loop
            status_str = "Requested"
            diag_tree = {}
            for _ in range(4):
                await asyncio.sleep(3)
                try:
                    await self.refresh_object(device_id, refresh_path)
                except Exception:
                    pass

                updated_dev = await self.get_device(device_id)
                diag_tree = updated_dev.get("Device", {}).get("IP", {}).get("Diagnostics", {}).get("TraceRoute", {}) if is_tr181 else updated_dev.get("InternetGatewayDevice", {}).get("TraceRouteDiagnostics", {})

                status_str = str(extract_param(diag_tree, "DiagnosticsState", "None"))
                if status_str in ["Complete", "Error_CannotResolveHostName", "Error_Internal"]:
                    break

            # 4. Universal Hop Parser
            hops = []
            route_hops = diag_tree.get("RouteHops", {})
            if isinstance(route_hops, dict):
                for key, hop_data in route_hops.items():
                    if not str(key).isdigit() or not isinstance(hop_data, dict):
                        continue
                    
                    hop_num = int(key)
                    h_host = extract_param(hop_data, "HopHost", "*")
                    h_addr = extract_param(hop_data, "HopHostAddress", "*")
                    h_rtt = extract_param(hop_data, "HopRTTimes", "*")

                    display_addr = h_addr if h_addr != "*" else h_host

                    hops.append({
                        "hop_number": hop_num,
                        "host": str(h_host),
                        "host_address": str(display_addr),
                        "rtt_ms": str(h_rtt)
                    })

            hops.sort(key=lambda x: x["hop_number"])

            return {
                "host": host,
                "status": status_str,
                "total_hops": len(hops),
                "hops": hops
            }

    async def update_wifi_settings(self, device_id: str, ssid: str, password: str):
        """Update Wi-Fi settings safely to eliminate TR-069 Fault 9002."""
        encoded_id = urllib.parse.quote(device_id)

        # 1. Try standard TR-098 WLANConfiguration.1 paths
        payload_standard = {
            "name": "setParameterValues",
            "parameterValues": [
                ["InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.SSID", ssid, "xsd:string"],
                ["InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.PreSharedKey.1.PreSharedKey", password, "xsd:string"]
            ]
        }

        async with httpx.AsyncClient() as client:
            try:
                # Send standard task
                url = f"{self.base_url}/devices/{encoded_id}/tasks?connection_request"
                res = await client.post(url, json=payload_standard, headers=self.headers, timeout=12.0)
                
                # Check if GenieACS returned a TR-069 fault response
                if res.status_code >= 400 or "fault" in res.text.lower():
                    raise ValueError(f"Standard TR-098 failed: {res.text}")

            except Exception as err:
                print(f"[Backend] Standard update failed ({err}). Trying Huawei vendor extension paths...")

                # 2. Fallback to Huawei X_HW vendor paths (Fixes HG8546M / EG8145V5 9002 Fault)
                payload_huawei = {
                    "name": "setParameterValues",
                    "parameterValues": [
                        ["InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.X_HW_SSID", ssid, "xsd:string"],
                        ["InternetGatewayDevice.LANDevice.1.WLANConfiguration.1.X_HW_WPAKey", password, "xsd:string"]
                    ]
                }
                res = await client.post(url, json=payload_huawei, headers=self.headers, timeout=12.0)
                res.raise_for_status()

            # Refresh parameters in GenieACS after write
            await asyncio.sleep(2)
            try:
                await self.refresh_object(device_id, "InternetGatewayDevice.LANDevice.1.WLANConfiguration.1")
            except Exception:
                pass

            return {
                "status": "success",
                "message": "Wi-Fi updated successfully",
                "ssid": ssid,
                "password": password
            }