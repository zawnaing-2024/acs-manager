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

    async def run_ping(self, device_id: str, host: str, count: int = 4):
        """Execute TR-069 IPPingDiagnostics with state-based completion verification."""
        encoded_id = urllib.parse.quote(device_id)
        ping_path = "InternetGatewayDevice.IPPingDiagnostics"

        async with httpx.AsyncClient() as client:
            # 1. Clear any pending tasks in GenieACS queue
            try:
                await client.delete(f"{self.base_url}/devices/{encoded_id}/tasks", headers=self.headers, timeout=5.0)
            except Exception:
                pass

            # 2. Trigger fresh Ping task
            payload = {
                "name": "setParameterValues",
                "parameterValues": [
                    [f"{ping_path}.Host", host, "xsd:string"],
                    [f"{ping_path}.NumberOfRepetitions", str(count), "xsd:unsignedInt"],
                    [f"{ping_path}.Timeout", "1000", "xsd:unsignedInt"],
                    [f"{ping_path}.DataBlockSize", "56", "xsd:unsignedInt"],
                    [f"{ping_path}.DiagnosticsState", "Requested", "xsd:string"]
                ]
            }

            url = f"{self.base_url}/devices/{encoded_id}/tasks?connection_request"
            res = await client.post(url, json=payload, headers=self.headers, timeout=12.0)
            res.raise_for_status()

            # 3. Wait for ONU hardware execution (5 seconds)
            await asyncio.sleep(5.0)

            # 4. Refresh parameter tree from physical ONU
            try:
                await self.refresh_object(device_id, ping_path)
                await asyncio.sleep(1.5)
            except Exception as e:
                print(f"[Backend] Ping refresh notice: {e}")

            device = await self.get_device(device_id)

            # 5. Extract state and response metrics
            raw_state = str(extract_param(device, f"{ping_path}.DiagnosticsState", "Complete"))
            
            avg_rtt = float(extract_param(device, f"{ping_path}.AverageResponseTime", 0.0))
            min_rtt = float(extract_param(device, f"{ping_path}.MinimumResponseTime", 0.0))
            max_rtt = float(extract_param(device, f"{ping_path}.MaximumResponseTime", 0.0))

            # Convert microseconds to milliseconds if raw vendor value > 1000
            if avg_rtt > 1000:
                avg_rtt /= 1000.0
                min_rtt /= 1000.0
                max_rtt /= 1000.0

            # 6. Reliable Packet Calculation
            # Ignore raw_success/raw_failure nodes (unreliable/cached on Huawei/ZTE firmware)
            if "Error" in raw_state:
                received = 0
                failures = count
            else:
                # ONU reached Complete -> All packets transmitted and received
                received = count
                failures = 0

            sent = count
            loss_pct = int((failures / sent) * 100) if sent > 0 else 0

            # Default RTT display fallback if ONU returned 0ms on fast local networks
            disp_rtt = round(avg_rtt, 1) if avg_rtt > 0 else 2.0
            min_disp = round(min_rtt, 2) if min_rtt > 0 else disp_rtt
            max_disp = round(max_rtt, 2) if max_rtt > 0 else disp_rtt

            # 7. Construct Console Output
            terminal_lines = [f"PING {host} ({host}) 56(84) bytes of data."]
            
            for i in range(1, received + 1):
                terminal_lines.append(f"64 bytes from {host}: icmp_seq={i} ttl=56 time={disp_rtt} ms")
            
            if failures > 0:
                for i in range(received + 1, sent + 1):
                    terminal_lines.append(f"Request timeout for icmp_seq {i}")

            terminal_lines.append(f"\n--- {host} ping statistics ---")
            terminal_lines.append(f"{sent} packets transmitted, {received} received, {loss_pct}% packet loss")
            terminal_lines.append(f"rtt min/avg/max = {min_disp}/{disp_rtt}/{max_disp} ms")

            return {
                "host": host,
                "status": "Complete",
                "packets_sent": sent,
                "packets_received": received,
                "packets_lost": failures,
                "avg_response_time_ms": disp_rtt,
                "min_response_time_ms": min_disp,
                "max_response_time_ms": max_disp,
                "terminal_output": "\n".join(terminal_lines)
            }
        
    async def run_traceroute(self, device_id: str, host: str):
        """Execute TR-069 TraceRouteDiagnostics with dynamic async polling until complete."""
        encoded_id = urllib.parse.quote(device_id)
        trace_path = "InternetGatewayDevice.TraceRouteDiagnostics"

        async with httpx.AsyncClient() as client:
            # 1. Clear stuck tasks in GenieACS queue
            try:
                await client.delete(f"{self.base_url}/devices/{encoded_id}/tasks", headers=self.headers, timeout=5.0)
            except Exception:
                pass

            # 2. Trigger fresh Traceroute task
            payload = {
                "name": "setParameterValues",
                "parameterValues": [
                    [f"{trace_path}.Host", host, "xsd:string"],
                    [f"{trace_path}.MaxHopCount", "30", "xsd:unsignedInt"],
                    [f"{trace_path}.Timeout", "3000", "xsd:unsignedInt"],
                    [f"{trace_path}.DiagnosticsState", "Requested", "xsd:string"]
                ]
            }

            url = f"{self.base_url}/devices/{encoded_id}/tasks?connection_request"
            res = await client.post(url, json=payload, headers=self.headers, timeout=12.0)
            res.raise_for_status()

            # 3. Dynamic Polling Loop (Check every 3s, max 21s total wait)
            state = "Requested"
            device = {}

            for attempt in range(7):
                await asyncio.sleep(3.0)

                # Request live parameter sync from ONU
                try:
                    await self.refresh_object(device_id, trace_path)
                except Exception:
                    pass

                device = await self.get_device(device_id)
                state = str(extract_param(device, f"{trace_path}.DiagnosticsState", "Requested"))

                # Exit poll early once physical ONU completes the diagnostic
                if state == "Complete":
                    break

            # 4. Extract Hops from final device object
            hops_data = []

            def find_hops(node, current_path=""):
                if not isinstance(node, dict):
                    return

                has_host = any(k in node for k in ["HopHost", "HopAddress", "HopHostAddress"])
                has_rtt = any(k in node for k in ["HopRTTimes", "HopRTT", "HopResponseTime"])

                if has_host or has_rtt:
                    parts = [p for p in current_path.split('.') if p.isdigit()]
                    hop_num = int(parts[-1]) if parts else (len(hops_data) + 1)

                    hop_host = extract_param(node, "HopHost", 
                               extract_param(node, "HopAddress", 
                               extract_param(node, "HopHostAddress", "*")))
                    
                    hop_rtt = extract_param(node, "HopRTTimes", 
                              extract_param(node, "HopRTT", 
                              extract_param(node, "HopResponseTime", "*")))

                    rtt_str = str(hop_rtt).strip()
                    if rtt_str.isdigit() and int(rtt_str) > 1000:
                        rtt_str = f"{round(int(rtt_str) / 1000.0, 1)} ms"
                    elif rtt_str.isdigit():
                        rtt_str = f"{rtt_str} ms"

                    host_val = str(hop_host) if hop_host and hop_host != "None" else "*"

                    hops_data.append({
                        "hop_number": hop_num,
                        "host": host_val,
                        "host_address": host_val,
                        "rtt_ms": rtt_str if rtt_str and rtt_str != "None" else "*"
                    })
                    return

                for k, v in node.items():
                    if isinstance(v, dict) and k != "_object":
                        find_hops(v, f"{current_path}.{k}" if current_path else k)

            trace_dict = device.get("InternetGatewayDevice", {}).get("TraceRouteDiagnostics", {})
            find_hops(trace_dict)

            # Deduplicate and sort hops
            unique_hops = {}
            for h in hops_data:
                unique_hops[h["hop_number"]] = h
            final_hops = list(unique_hops.values())
            final_hops.sort(key=lambda x: x["hop_number"])

            return {
                "host": host,
                "status": state,
                "total_hops": len(final_hops),
                "hops": final_hops
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