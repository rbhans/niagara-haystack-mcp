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
import re

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("Niagara Haystack MCP")

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
        headers = {
            "Accept": "text/zinc, application/json, text/plain",
            "User-Agent": "Niagara-MCP/1.0"
        }
        auth = None
        
        if self.config.mode == DeploymentMode.RELAY and self.config.relay_token:
            headers["Authorization"] = f"Bearer {self.config.relay_token}"
        elif self.config.username:
            auth = (self.config.username, self.config.password)
        
        return httpx.Client(
            auth=auth,
            headers=headers,
            timeout=self.config.timeout,
            verify=self.config.verify_ssl,
            follow_redirects=True  # Important for nhaystack
        )
    
    def parse_zinc_value(self, value: str) -> Any:
        """Parse a single Zinc value to Python type"""
        if not value or value == 'N':
            return None
        
        # Remove surrounding quotes for strings
        if value.startswith('"') and value.endswith('"'):
            return value[1:-1]
        
        # Handle URIs (backtick delimited)
        if value.startswith('`') and value.endswith('`'):
            return value[1:-1]
        
        # Handle references
        if value.startswith('r:'):
            return value
        
        # Handle markers
        if value == 'm:' or value == '✓':
            return True
        
        # Handle numbers with units
        if value.startswith('n:'):
            parts = value[2:].split(' ', 1)
            try:
                num_val = float(parts[0])
                unit = parts[1] if len(parts) > 1 else None
                return {"val": num_val, "unit": unit} if unit else num_val
            except:
                return value
        
        # Handle dates/times
        if value.startswith('d:') or value.startswith('t:') or value.startswith('ts:'):
            return value[2:]
        
        # Handle strings
        if value.startswith('s:'):
            return value[2:]
        
        # Default return as-is
        return value
    
    def parse_zinc_response(self, text: str) -> Dict:
        """Parse Zinc format response to dictionary"""
        lines = text.strip().split('\n')
        if len(lines) < 2:
            return {"error": "Invalid Zinc response", "raw": text}
        
        # First line is version (e.g., ver:"3.0")
        version_line = lines[0]
        
        # Second line is column headers
        header_line = lines[1]
        # Parse headers carefully - they can contain commas in quoted strings
        headers = []
        current_header = ""
        in_quotes = False
        
        for char in header_line:
            if char == '"':
                in_quotes = not in_quotes
            elif char == ',' and not in_quotes:
                headers.append(current_header.strip())
                current_header = ""
            else:
                current_header += char
        if current_header:
            headers.append(current_header.strip())
        
        # Parse data rows
        rows = []
        for line in lines[2:]:
            if not line.strip():
                continue
                
            # Parse row values - also handle commas in quotes
            values = []
            current_value = ""
            in_quotes = False
            in_backticks = False
            
            for char in line:
                if char == '"' and not in_backticks:
                    in_quotes = not in_quotes
                    current_value += char
                elif char == '`' and not in_quotes:
                    in_backticks = not in_backticks
                    current_value += char
                elif char == ',' and not in_quotes and not in_backticks:
                    values.append(current_value.strip())
                    current_value = ""
                else:
                    current_value += char
            if current_value:
                values.append(current_value.strip())
            
            # Create row dictionary
            row = {}
            for i, header in enumerate(headers):
                if i < len(values):
                    row[header] = self.parse_zinc_value(values[i])
                else:
                    row[header] = None
            rows.append(row)
        
        return {
            "meta": {"ver": version_line},
            "cols": headers,
            "rows": rows
        }
    
    async def execute_op(self, op: str, params: Optional[Dict] = None) -> Dict:
        """Execute a Haystack operation"""
        try:
            url = f"{self.base_url}/{op}"
            
            logger.info(f"Executing Haystack operation: {op}")
            if params:
                logger.debug(f"Parameters: {params}")
            
            # nhaystack uses GET requests with query parameters for most operations
            if op == "about":
                # Simple GET with no parameters
                response = self.client.get(url)
                
            elif op == "ops":
                # List available operations
                response = self.client.get(url)
                
            elif op == "formats":
                # List supported formats
                response = self.client.get(url)
                
            elif op == "read":
                # Read operation with filter
                if params and "filter" in params:
                    # Filter should be passed as query parameter
                    query_params = {"filter": params["filter"]}
                    if "limit" in params:
                        query_params["limit"] = str(params["limit"])
                    response = self.client.get(url, params=query_params)
                else:
                    # Read all
                    response = self.client.get(url)
                    
            elif op == "hisRead":
                # History read - needs id and range
                if params:
                    query_params = {}
                    if "id" in params:
                        query_params["id"] = params["id"]
                    if "range" in params:
                        query_params["range"] = params["range"]
                    response = self.client.get(url, params=query_params)
                else:
                    raise ValueError("hisRead requires id and range parameters")
                    
            elif op == "nav":
                # Navigation
                if params and "navId" in params:
                    response = self.client.get(url, params={"navId": params["navId"]})
                else:
                    # Root navigation
                    response = self.client.get(url)
                    
            elif op in ["watchSub", "watchPoll", "watchUnsub", "pointWrite"]:
                # These operations typically need POST with form data
                # But nhaystack might accept GET with parameters
                if params:
                    response = self.client.get(url, params=params)
                    if response.status_code == 405:  # Method not allowed
                        # Try POST with form data
                        headers = {"Content-Type": "application/x-www-form-urlencoded"}
                        response = self.client.post(url, data=params, headers=headers)
                else:
                    response = self.client.get(url)
            else:
                # Default: GET with query parameters
                if params:
                    response = self.client.get(url, params=params)
                else:
                    response = self.client.get(url)
            
            # Check for errors
            if response.status_code == 415:
                logger.error(f"415 Unsupported Media Type - check request format")
                raise Exception("Server expects different content type")
            
            response.raise_for_status()
            
            # Parse response based on content type
            content_type = response.headers.get("content-type", "").lower()
            
            if "application/json" in content_type:
                return response.json()
            elif "text/zinc" in content_type or response.text.startswith('ver:'):
                # Parse Zinc format
                parsed = self.parse_zinc_response(response.text)
                logger.debug(f"Parsed Zinc response with {len(parsed.get('rows', []))} rows")
                return parsed
            else:
                # Try to parse as Zinc anyway
                if response.text.startswith('ver:'):
                    return self.parse_zinc_response(response.text)
                else:
                    logger.warning(f"Unknown response format: {content_type}")
                    return {"response": response.text, "format": "unknown"}
            
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code}: {e.response.text}")
            raise Exception(f"HTTP {e.response.status_code}: {e.response.text}")
        except Exception as e:
            logger.error(f"Haystack operation '{op}' failed: {e}")
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
        
        # Extract ops if available
        ops = []
        if "rows" in result and len(result["rows"]) > 0:
            # Try to get ops list
            try:
                ops_result = await haystack.execute_op("ops")
                if "rows" in ops_result:
                    ops = [row.get("name", "") for row in ops_result["rows"] if row.get("name")]
            except:
                pass
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
        
        # Handle Zinc format response
        if "rows" in result and len(result["rows"]) > 0:
            info = result["rows"][0]
            server_name = info.get("serverName", "Unknown")
            product_name = info.get("productName", "Unknown") 
            haystack_ver = info.get("haystackVersion", "Unknown")
            module_ver = info.get("moduleVersion", "Unknown")
            return f"{product_name} {server_name}\nHaystack {haystack_ver}, nhaystack {module_ver}"
        else:
            return f"Haystack server information: {result}"
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
    - 'point' - all points
    - 'point and sensor' - all sensor points  
    - 'point and temp' - temperature points
    - 'point and zone' - zone points
    - 'equip' - all equipment
    """
    try:
        params = {"filter": filter}
        if limit:
            params["limit"] = limit
            
        result = await haystack.execute_op("read", params)
        
        # Handle Zinc format response
        if "rows" in result:
            points = []
            for row in result["rows"]:
                # Extract key fields
                point_data = {
                    "id": row.get("id", ""),
                    "dis": row.get("dis", ""),
                    "navName": row.get("navName", ""),
                    "curVal": row.get("curVal", ""),
                    "curStatus": row.get("curStatus", ""),
                    "kind": row.get("kind", ""),
                    "unit": row.get("unit", ""),
                    "equipRef": row.get("equipRef", ""),
                    "siteRef": row.get("siteRef", ""),
                    "writable": row.get("writable", False) is not None,
                    "point": row.get("point", False) is not None,
                    "sensor": row.get("sensor", False) is not None,
                    "cmd": row.get("cmd", False) is not None,
                    "sp": row.get("sp", False) is not None
                }
                
                # Add any other tags present
                for key, value in row.items():
                    if key not in point_data and value is not None:
                        point_data[f"tag_{key}"] = value is not None if value == True else value
                        
                points.append(point_data)
            
            return {
                "success": True,
                "count": len(points),
                "filter": filter,
                "points": points
            }
        else:
            return {
                "success": False,
                "error": "Unexpected response format",
                "raw": result
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "filter": filter
        }

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
        
        if "rows" in result:
            history = []
            for row in result["rows"]:
                history.append({
                    "ts": row.get("ts", ""),
                    "val": row.get("val", "")
                })
            
            return {
                "success": True,
                "point_id": point_id,
                "range": range,
                "count": len(history),
                "data": history
            }
        else:
            return {
                "success": False,
                "error": "Unexpected response format",
                "raw": result
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "point_id": point_id
        }

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
            "duration": duration,
            "response": result
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "point_id": point_id
        }

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
        
        watch_id = ""
        if "rows" in result and len(result["rows"]) > 0:
            watch_id = result["rows"][0].get("watchId", "")
        
        return {
            "success": True,
            "watch_id": watch_id,
            "filter": filter,
            "lease_minutes": lease_minutes,
            "message": "Watch subscription created. Use watch_poll with this ID to get updates."
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool()
async def watch_poll(
    watch_id: str = Field(description="Watch ID from watch_subscribe")
) -> Dict[str, Any]:
    """Poll for updates on a watch subscription"""
    try:
        params = {"watchId": watch_id}
        result = await haystack.execute_op("watchPoll", params)
        
        if "rows" in result:
            updates = []
            for row in result["rows"]:
                updates.append({
                    "id": row.get("id", ""),
                    "curVal": row.get("curVal", ""),
                    "curStatus": row.get("curStatus", "")
                })
            
            return {
                "success": True,
                "watch_id": watch_id,
                "updates": updates,
                "count": len(updates)
            }
        else:
            return {
                "success": False,
                "error": "Unexpected response format",
                "raw": result
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "watch_id": watch_id
        }

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
        
        if "rows" in result:
            items = []
            for row in result["rows"]:
                item = {
                    "navId": row.get("navId", ""),
                    "dis": row.get("dis", ""),
                    "id": row.get("id", "")
                }
                
                # Add any marker tags
                tags = []
                for key, value in row.items():
                    if key not in ["navId", "dis", "id"] and value is not None:
                        if value == True or value == "m:":
                            tags.append(key)
                        else:
                            item[key] = value
                if tags:
                    item["tags"] = tags
                    
                items.append(item)
            
            return {
                "success": True,
                "current_nav_id": nav_id or "root",
                "items": items,
                "count": len(items)
            }
        else:
            return {
                "success": False,
                "error": "Unexpected response format",
                "raw": result
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

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
        
        if "rows" in result:
            alarms = []
            for row in result["rows"]:
                alarm_data = {
                    "id": row.get("id", ""),
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
                "success": True,
                "count": len(alarms),
                "active_count": sum(1 for a in alarms if not a["acked"]),
                "alarms": alarms
            }
        else:
            return {
                "success": False,
                "error": "No alarms found or unexpected response format",
                "raw": result
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool()
async def get_equipment(
    filter: str = Field(default="equip", description="Haystack filter for equipment"),
    include_points: bool = Field(default=False, description="Include associated points")
) -> Dict[str, Any]:
    """Get equipment information from the system"""
    try:
        # Read equipment
        result = await haystack.execute_op("read", {"filter": filter})
        
        if "rows" in result:
            equipment_list = []
            for equip in result["rows"]:
                equipment_data = {
                    "id": equip.get("id", ""),
                    "dis": equip.get("dis", ""),
                    "navName": equip.get("navName", ""),
                    "siteRef": equip.get("siteRef", ""),
                    "equip": True,
                    "tags": []
                }
                
                # Collect all marker tags
                for key, value in equip.items():
                    if key not in ["id", "dis", "navName", "siteRef"] and value is not None:
                        if value == True or value == "m:":  # Marker tag
                            equipment_data["tags"].append(key)
                        else:
                            equipment_data[key] = value
                
                # Get points for this equipment if requested
                if include_points and equipment_data["id"]:
                    point_filter = f'point and equipRef=={equipment_data["id"]}'
                    try:
                        points_result = await haystack.execute_op("read", {"filter": point_filter, "limit": 10})
                        if "rows" in points_result:
                            equipment_data["points"] = [
                                {
                                    "id": p.get("id", ""),
                                    "dis": p.get("dis", ""),
                                    "curVal": p.get("curVal", ""),
                                    "kind": p.get("kind", "")
                                } for p in points_result["rows"]
                            ]
                            equipment_data["point_count"] = len(points_result["rows"])
                    except:
                        equipment_data["points"] = []
                        equipment_data["point_count"] = 0
                
                equipment_list.append(equipment_data)
            
            return {
                "success": True,
                "count": len(equipment_list),
                "equipment": equipment_list
            }
        else:
            return {
                "success": False,
                "error": "No equipment found or unexpected response format",
                "raw": result
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

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
        
        if "rows" in result:
            return {
                "success": True,
                "filter": filter,
                "count": len(result["rows"]),
                "results": result["rows"][:limit]
            }
        else:
            return {
                "success": False,
                "error": "Unexpected response format",
                "raw": result
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "filter": filter
        }

@mcp.tool()
async def batch_read(
    point_ids: List[str] = Field(description="List of point IDs to read")
) -> Dict[str, Any]:
    """Read multiple points in a single request"""
    try:
        if not point_ids:
            return {"success": False, "error": "No point IDs provided"}
        
        # Create filter for multiple IDs
        id_filters = [f'id=={pid}' for pid in point_ids]
        filter_str = " or ".join(id_filters)
        
        result = await haystack.execute_op("read", {"filter": filter_str})
        
        if "rows" in result:
            points = {}
            for row in result["rows"]:
                point_id = row.get("id", "")
                points[point_id] = {
                    "dis": row.get("dis", ""),
                    "curVal": row.get("curVal", ""),
                    "unit": row.get("unit", ""),
                    "curStatus": row.get("curStatus", "ok")
                }
            
            return {
                "success": True,
                "requested": len(point_ids),
                "found": len(points),
                "points": points
            }
        else:
            return {
                "success": False,
                "error": "Unexpected response format",
                "raw": result
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

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
