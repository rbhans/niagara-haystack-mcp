"""
Tridium Niagara MCP Server using FastMCP and Haystack API
Supports both local and remote deployment patterns
"""

import os
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from enum import Enum
import httpx
from fastmcp import FastMCP
from pydantic import BaseModel, Field
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("Niagara Haystack MCP")
mcp.add_prompt("niagara_help", "Get help with Niagara BAS operations and Haystack queries")

class DeploymentMode(Enum):
    """Deployment mode for the MCP server"""
    LOCAL = "local"  # Direct connection to Niagara
    RELAY = "relay"  # Connect through remote API gateway
    HYBRID = "hybrid"  # Try local first, fallback to relay

# Configuration model
class NiagaraConfig(BaseModel):
    """Configuration for Niagara connection"""
    # Deployment settings
    mode: DeploymentMode = Field(default=DeploymentMode.LOCAL, description="Deployment mode")
    relay_url: Optional[str] = Field(default=None, description="Remote relay API URL")
    relay_token: Optional[str] = Field(default=None, description="Authentication token for relay")
    
    # Local Niagara settings
    host: str = Field(default="localhost", description="Niagara host address")
    port: int = Field(default=8080, description="Niagara port")
    username: str = Field(default="", description="Niagara username")
    password: str = Field(default="", description="Niagara password")
    haystack_path: str = Field(default="/haystack", description="Haystack API endpoint path")
    use_https: bool = Field(default=False, description="Use HTTPS for connection")
    
    # Connection settings
    timeout: int = Field(default=30, description="Request timeout in seconds")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")

# Load configuration from environment
def load_config() -> NiagaraConfig:
    """Load configuration from environment variables"""
    mode_str = os.getenv("DEPLOYMENT_MODE", "local").lower()
    mode = DeploymentMode(mode_str) if mode_str in ["local", "relay", "hybrid"] else DeploymentMode.LOCAL
    
    return NiagaraConfig(
        mode=mode,
        relay_url=os.getenv("RELAY_URL"),
        relay_token=os.getenv("RELAY_TOKEN"),
        host=os.getenv("NIAGARA_HOST", "localhost"),
        port=int(os.getenv("NIAGARA_PORT", "8080")),
        username=os.getenv("NIAGARA_USERNAME", ""),
        password=os.getenv("NIAGARA_PASSWORD", ""),
        haystack_path=os.getenv("HAYSTACK_PATH", "/haystack"),
        use_https=os.getenv("USE_HTTPS", "false").lower() == "true",
        timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
        verify_ssl=os.getenv("VERIFY_SSL", "true").lower() == "true"
    )

config = load_config()

class HaystackClient:
    """Client for interacting with Haystack API (local or remote)"""
    
    def __init__(self, config: NiagaraConfig):
        self.config = config
        self.base_url = self._get_base_url()
        self.client = self._create_client()
    
    def _get_base_url(self) -> str:
        """Get the appropriate base URL based on deployment mode"""
        if self.config.mode == DeploymentMode.RELAY and self.config.relay_url:
            return self.config.relay_url
        else:
            protocol = 'https' if self.config.use_https else 'http'
            return f"{protocol}://{self.config.host}:{self.config.port}{self.config.haystack_path}"
    
    def _create_client(self) -> httpx.Client:
        """Create HTTP client with appropriate authentication"""
        headers = {}
        auth = None
        
        if self.config.mode == DeploymentMode.RELAY and self.config.relay_token:
            # Use bearer token for relay authentication
            headers["Authorization"] = f"Bearer {self.config.relay_token}"
        elif self.config.username:
            # Use basic auth for direct connection
            auth = (self.config.username, self.config.password)
        
        return httpx.Client(
            auth=auth,
            headers=headers,
            timeout=self.config.timeout,
            verify=self.config.verify_ssl
        )
    
    async def execute_op(self, op: str, params: Optional[Dict] = None) -> Dict:
        """Execute a Haystack operation"""
        try:
            if self.config.mode == DeploymentMode.RELAY:
                # Relay mode: wrap the operation
                url = f"{self.base_url}/haystack"
                payload = {
                    "operation": op,
                    "params": params or {}
                }
            else:
                # Local mode: direct Haystack call
                url = f"{self.base_url}/{op}"
                payload = params or {}
            
            response = self.client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
            
        except httpx.ConnectError as e:
            if self.config.mode == DeploymentMode.HYBRID and self.config.relay_url:
                # Fallback to relay mode
                logger.info("Local connection failed, trying relay mode")
                self.config.mode = DeploymentMode.RELAY
                self.base_url = self._get_base_url()
                self.client = self._create_client()
                return await self.execute_op(op, params)
            else:
                logger.error(f"Connection failed: {e}")
                raise
        except Exception as e:
            logger.error(f"Haystack operation failed: {e}")
            raise
    
    def close(self):
        """Close the HTTP client"""
        self.client.close()

# Initialize Haystack client
haystack = HaystackClient(config)

@mcp.tool()
async def get_connection_info() -> Dict[str, str]:
    """Get current connection configuration and status"""
    try:
        # Try to connect and get system info
        result = await haystack.execute_op("about")
        status = "connected"
        ops = result.get("ops", [])
    except Exception as e:
        status = f"error: {str(e)}"
        ops = []
    
    return {
        "mode": config.mode.value,
        "endpoint": haystack.base_url,
        "status": status,
        "available_ops": ops,
        "using_relay": config.mode == DeploymentMode.RELAY,
        "ssl_enabled": config.use_https or (config.relay_url and config.relay_url.startswith("https"))
    }

@mcp.tool()
async def about() -> str:
    """Get information about available Haystack operations in the Niagara system"""
    try:
        result = await haystack.execute_op("about")
        ops = result.get("ops", [])
        vendor = result.get("vendorName", "Unknown")
        version = result.get("haystackVersion", "Unknown")
        return f"Haystack {version} by {vendor}\nAvailable operations: {', '.join(ops)}"
    except Exception as e:
        return f"Error getting system info: {str(e)}"

@mcp.tool()
async def read_points(
    filter: str = Field(description="Haystack filter expression (e.g., 'point and sensor')"),
    limit: Optional[int] = Field(default=100, description="Maximum number of results")
) -> Dict[str, Any]:
    """
    Read points from Niagara using Haystack filter expressions.
    Examples:
    - 'point and sensor' - all sensor points
    - 'point and temp' - temperature points
    - 'point and zone==101' - points in zone 101
    """
    try:
        params = {"filter": filter}
        if limit:
            params["limit"] = limit
            
        result = await haystack.execute_op("read", params)
        rows = result.get("rows", [])
        
        points = []
        for row in rows:
            point_data = {
                "id": row.get("id", {}).get("_val", "") if isinstance(row.get("id"), dict) else row.get("id", ""),
                "dis": row.get("dis", ""),
                "curVal": row.get("curVal", ""),
                "unit": row.get("unit", ""),
                "tags": [k for k in row.keys() if k not in ["id", "dis", "curVal", "unit"]]
            }
            points.append(point_data)
        
        return {
            "count": len(points),
            "filter": filter,
            "points": points
        }
    except Exception as e:
        return {"error": str(e), "filter": filter}

@mcp.tool()
async def read_history(
    point_id: str = Field(description="Point ID to read history from"),
    range: str = Field(default="today", description="Time range (e.g., 'today', 'yesterday', '2024-01-01,2024-01-07')")
) -> Dict[str, Any]:
    """Read historical data for a specific point"""
    try:
        params = {
            "id": point_id,
            "range": range
        }
        result = await haystack.execute_op("hisRead", params)
        
        rows = result.get("rows", [])
        history = []
        for row in rows:
            ts = row.get("ts", {})
            ts_val = ts.get("_val", "") if isinstance(ts, dict) else ts
            history.append({
                "ts": ts_val,
                "val": row.get("val", "")
            })
        
        return {
            "point_id": point_id,
            "range": range,
            "count": len(history),
            "data": history
        }
    except Exception as e:
        return {"error": str(e), "point_id": point_id}

@mcp.tool()
async def write_point(
    point_id: str = Field(description="Point ID to write to"),
    value: float = Field(description="Value to write"),
    level: int = Field(default=16, description="Priority level (1-17, default 16)"),
    duration: Optional[int] = Field(default=None, description="Duration in minutes (for temporary override)")
) -> Dict[str, Any]:
    """Write a value to a writable point"""
    try:
        params = {
            "id": point_id,
            "level": level,
            "val": value
        }
        
        if duration:
            params["duration"] = f"{duration}min"
        
        result = await haystack.execute_op("pointWrite", params)
        return {
            "success": True,
            "point_id": point_id,
            "value": value,
            "level": level,
            "duration": duration
        }
    except Exception as e:
        return {"error": str(e), "point_id": point_id}

@mcp.tool()
async def watch_subscribe(
    filter: str = Field(description="Haystack filter for points to watch"),
    lease_minutes: int = Field(default=5, description="Lease time in minutes")
) -> Dict[str, Any]:
    """Subscribe to real-time updates for points matching a filter"""
    try:
        params = {
            "filter": filter,
            "lease": f"{lease_minutes}min"
        }
        result = await haystack.execute_op("watchSub", params)
        watch_id = result.get("watchId", "")
        
        return {
            "watch_id": watch_id,
            "filter": filter,
            "lease_minutes": lease_minutes,
            "message": "Watch subscription created. Use watch_poll with this ID to get updates."
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
async def watch_poll(
    watch_id: str = Field(description="Watch ID from watch_subscribe")
) -> Dict[str, Any]:
    """Poll for updates on a watch subscription"""
    try:
        params = {"watchId": watch_id}
        result = await haystack.execute_op("watchPoll", params)
        
        rows = result.get("rows", [])
        updates = []
        for row in rows:
            id_val = row.get("id", {})
            id_str = id_val.get("_val", "") if isinstance(id_val, dict) else id_val
            updates.append({
                "id": id_str,
                "curVal": row.get("curVal", ""),
                "curStatus": row.get("curStatus", "")
            })
        
        return {
            "watch_id": watch_id,
            "updates": updates,
            "count": len(updates)
        }
    except Exception as e:
        return {"error": str(e), "watch_id": watch_id}

@mcp.tool()
async def nav(
    nav_id: Optional[str] = Field(default=None, description="Navigation ID to explore (None for root)")
) -> Dict[str, Any]:
    """Navigate the Niagara station hierarchy"""
    try:
        params = {}
        if nav_id:
            params["navId"] = nav_id
        
        result = await haystack.execute_op("nav", params)
        rows = result.get("rows", [])
        
        items = []
        for row in rows:
            items.append({
                "navId": row.get("navId", ""),
                "dis": row.get("dis", ""),
                "tags": [k for k in row.keys() if k not in ["navId", "dis"]]
            })
        
        return {
            "current_nav_id": nav_id or "root",
            "items": items,
            "count": len(items)
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
async def get_alarms(
    filter: str = Field(default="alarm", description="Filter for alarms"),
    include_acked: bool = Field(default=True, description="Include acknowledged alarms")
) -> Dict[str, Any]:
    """Get current alarms from the system"""
    try:
        # Adjust filter based on include_acked
        if not include_acked:
            filter = f"{filter} and not acked"
        
        result = await haystack.execute_op("read", {"filter": filter})
        rows = result.get("rows", [])
        
        alarms = []
        for row in rows:
            id_val = row.get("id", {})
            id_str = id_val.get("_val", "") if isinstance(id_val, dict) else id_val
            alarm_data = {
                "id": id_str,
                "dis": row.get("dis", ""),
                "alarmClass": row.get("alarmClass", ""),
                "priority": row.get("priority", ""),
                "acked": row.get("acked", False),
                "normalTime": row.get("normalTime", ""),
                "ackTime": row.get("ackTime", ""),
                "equipment": row.get("equipRef", "")
            }
            alarms.append(alarm_data)
        
        # Sort by priority and ack status
        alarms.sort(key=lambda x: (x["acked"], x.get("priority", 999)))
        
        return {
            "count": len(alarms),
            "active_count": sum(1 for a in alarms if not a["acked"]),
            "alarms": alarms
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
async def get_equipment(
    filter: str = Field(default="equip", description="Haystack filter for equipment"),
    include_points: bool = Field(default=True, description="Include associated points")
) -> Dict[str, Any]:
    """Get equipment information with associated points"""
    try:
        # Read equipment
        result = await haystack.execute_op("read", {"filter": filter})
        equipment_rows = result.get("rows", [])
        
        equipment_list = []
        for equip in equipment_rows:
            id_val = equip.get("id", {})
            equip_id = id_val.get("_val", "") if isinstance(id_val, dict) else id_val
            
            equipment_data = {
                "id": equip_id,
                "dis": equip.get("dis", ""),
                "siteRef": equip.get("siteRef", ""),
                "tags": [k for k in equip.keys() if k not in ["id", "dis", "siteRef"]]
            }
            
            # Get points for this equipment if requested
            if include_points and equip_id:
                point_filter = f'point and equipRef==@{equip_id}'
                points_result = await haystack.execute_op("read", {"filter": point_filter, "limit": 10})
                points = points_result.get("rows", [])
                
                equipment_data["point_count"] = len(points)
                equipment_data["points"] = [
                    {
                        "id": p.get("id", {}).get("_val", "") if isinstance(p.get("id"), dict) else p.get("id", ""),
                        "dis": p.get("dis", ""),
                        "curVal": p.get("curVal", "")
                    } for p in points[:5]  # First 5 points as preview
                ]
            
            equipment_list.append(equipment_data)
        
        return {
            "count": len(equipment_list),
            "equipment": equipment_list
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
async def execute_custom_filter(
    filter: str = Field(description="Custom Haystack filter expression"),
    limit: int = Field(default=100, description="Maximum number of results")
) -> Dict[str, Any]:
    """Execute a custom Haystack filter query"""
    try:
        params = {
            "filter": filter,
            "limit": limit
        }
        result = await haystack.execute_op("read", params)
        rows = result.get("rows", [])
        
        return {
            "filter": filter,
            "count": len(rows),
            "results": rows[:limit]
        }
    except Exception as e:
        return {"error": str(e), "filter": filter}

@mcp.tool()
async def batch_read(
    point_ids: List[str] = Field(description="List of point IDs to read")
) -> Dict[str, Any]:
    """Read multiple points in a single request"""
    try:
        if not point_ids:
            return {"error": "No point IDs provided"}
        
        # Create filter for multiple IDs
        id_filters = [f'id==@{pid}' for pid in point_ids]
        filter_str = " or ".join(id_filters)
        
        result = await haystack.execute_op("read", {"filter": filter_str})
        rows = result.get("rows", [])
        
        points = {}
        for row in rows:
            id_val = row.get("id", {})
            point_id = id_val.get("_val", "") if isinstance(id_val, dict) else id_val
            points[point_id] = {
                "dis": row.get("dis", ""),
                "curVal": row.get("curVal", ""),
                "unit": row.get("unit", ""),
                "curStatus": row.get("curStatus", "ok")
            }
        
        return {
            "requested": len(point_ids),
            "found": len(points),
            "points": points
        }
    except Exception as e:
        return {"error": str(e)}

# Resource for storing common Haystack filters
@mcp.resource("file://haystack_filters.json")
async def get_common_filters() -> str:
    """Common Haystack filter expressions for reference"""
    filters = {
        "basic_queries": {
            "all_points": "point",
            "sensor_points": "point and sensor",
            "writable_points": "point and writable",
            "command_points": "point and cmd"
        },
        "sensor_types": {
            "temperature": "point and temp and sensor",
            "humidity": "point and humidity and sensor",
            "pressure": "point and pressure and sensor",
            "co2": "point and co2 and sensor",
            "occupancy": "point and occ and sensor"
        },
        "equipment_types": {
            "all_equipment": "equip",
            "vav_boxes": "equip and vav",
            "ahu_units": "equip and ahu",
            "chillers": "equip and chiller",
            "boilers": "equip and boiler",
            "meters": "equip and meter"
        },
        "hierarchy": {
            "sites": "site",
            "floors": "floor",
            "zones": "space and zone",
            "rooms": "space and room"
        },
        "system_status": {
            "alarms": "alarm",
            "active_alarms": "alarm and not acked",
            "high_priority_alarms": "alarm and priority < 3",
            "faults": "point and fault"
        },
        "setpoints": {
            "zone_temps": "point and sp and temp and zone",
            "ahu_setpoints": "point and sp and ahu",
            "schedule_setpoints": "point and sp and scheduled"
        }
    }
    
    return json.dumps(filters, indent=2)

# Cleanup on shutdown
def cleanup():
    """Cleanup resources on shutdown"""
    haystack.close()
    logger.info("MCP server shutdown complete")

def main():
    """Main entry point for the MCP server"""
    import sys
    
    # Print startup info
    logger.info(f"Starting Niagara MCP Server in {config.mode.value} mode")
    if config.mode in [DeploymentMode.RELAY, DeploymentMode.HYBRID]:
        logger.info(f"Relay URL: {config.relay_url}")
    else:
        logger.info(f"Direct connection to: {config.host}:{config.port}")
    
    try:
        # Run the FastMCP server
        mcp.run()
    except KeyboardInterrupt:
        cleanup()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Server error: {e}")
        cleanup()
        sys.exit(1)

if __name__ == "__main__":
    main()
