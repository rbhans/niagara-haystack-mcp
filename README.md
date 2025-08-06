# Niagara Haystack MCP Server

An MCP (Model Context Protocol) server that enables AI assistants to interact with Tridium Niagara Building Automation Systems through the Project Haystack API. Supports both local and remote deployment patterns.

## Features

- **Full Haystack API Support**: Read points, write values, query history, manage alarms
- **Equipment Navigation**: Browse sites, equipment, and point hierarchies
- **Real-time Monitoring**: Subscribe to point changes with watch operations
- **Smart Filtering**: Use Haystack tags to find exactly what you need
- **Multiple Deployment Modes**: Local, Remote Relay, or Hybrid
- **Built with FastMCP**: Leverages the latest FastMCP framework

## Deployment Options

### 1. Local Mode (Direct Connection)
Run MCP locally with direct access to Niagara system on your network.

### 2. GitHub-Hosted (No Installation)
Run directly from GitHub using `uvx` or `npx` - no local installation needed.

### 3. Relay Mode (Remote Gateway)
Connect through a remote API gateway for cloud-based access.

### 4. Hybrid Mode
Try local connection first, automatically fallback to relay if unavailable.

### 5. Docker Container
Run in an isolated container environment.

## Quick Start

### Option 1: Run Locally

```bash
# Clone and install
git clone https://github.com/yourusername/niagara-mcp.git
cd niagara-mcp
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your credentials

# Run
python niagara_mcp.py
```

### Option 2: Run from GitHub (No Install)

Add to Claude Desktop config:
```json
{
  "mcpServers": {
    "niagara": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/yourusername/niagara-mcp.git",
        "niagara-mcp"
      ],
      "env": {
        "NIAGARA_HOST": "192.168.1.100",
        "NIAGARA_USERNAME": "admin",
        "NIAGARA_PASSWORD": "password"
      }
    }
  }
}
```

### Option 3: Docker

```bash
# Build and run with Docker
docker build -t niagara-mcp .
docker run --rm -it \
  -e NIAGARA_HOST=192.168.1.100 \
  -e NIAGARA_USERNAME=admin \
  -e NIAGARA_PASSWORD=password \
  niagara-mcp

# Or use docker-compose
docker-compose up
```

## Configuration

### Environment Variables

| Variable | Description | Default | Mode |
|----------|-------------|---------|------|
| `DEPLOYMENT_MODE` | Deployment mode: local, relay, hybrid | local | All |
| `NIAGARA_HOST` | Niagara station host | localhost | Local |
| `NIAGARA_PORT` | Niagara HTTP port | 8080 | Local |
| `NIAGARA_USERNAME` | Niagara username | - | Local |
| `NIAGARA_PASSWORD` | Niagara password | - | Local |
| `RELAY_URL` | Remote API gateway URL | - | Relay |
| `RELAY_TOKEN` | Authentication token for relay | - | Relay |
| `HAYSTACK_PATH` | Haystack servlet path | /haystack | Local |
| `USE_HTTPS` | Use HTTPS for Niagara | false | Local |

### Deployment Mode Details

#### Local Mode
- Direct connection to Niagara on local network
- Requires network access to Niagara station
- Most secure for credentials

```env
DEPLOYMENT_MODE=local
NIAGARA_HOST=192.168.1.100
NIAGARA_PORT=8080
NIAGARA_USERNAME=admin
NIAGARA_PASSWORD=secure_password
```

#### Relay Mode
- Connects through remote API gateway
- Gateway handles Niagara authentication
- Good for cloud deployments

```env
DEPLOYMENT_MODE=relay
RELAY_URL=https://api.yourcompany.com/niagara
RELAY_TOKEN=your-secure-api-token
```

#### Hybrid Mode
- Tries local connection first
- Falls back to relay if local fails
- Best for mobile/laptop users

```env
DEPLOYMENT_MODE=hybrid
NIAGARA_HOST=192.168.1.100
NIAGARA_USERNAME=admin
NIAGARA_PASSWORD=password
RELAY_URL=https://api.yourcompany.com/niagara
RELAY_TOKEN=backup-token
```

## Remote API Gateway Setup

To deploy a relay API gateway for remote access:

1. **Deploy the Relay API** (see `relay_api_example.py`):
```bash
# On your cloud server
pip install fastapi uvicorn httpx
python relay_api_example.py
```

2. **Secure with HTTPS** (use nginx/caddy as reverse proxy)

3. **Configure MCP to use relay**:
```json
{
  "mcpServers": {
    "niagara": {
      "command": "python",
      "args": ["niagara_mcp.py"],
      "env": {
        "DEPLOYMENT_MODE": "relay",
        "RELAY_URL": "https://api.yourcompany.com/niagara",
        "RELAY_TOKEN": "your-token"
      }
    }
  }
}
```

## Prerequisites

Your Niagara station must have:
1. **nhaystack module** installed and configured
2. Haystack servlet enabled (typically at `/haystack`)
3. Proper user permissions for API access

## Available Tools

### Basic Operations
- `get_connection_info()` - Check connection status and mode
- `about()` - Get system information
- `read_points(filter)` - Read points using Haystack filters
- `write_point(point_id, value, level)` - Write values
- `read_history(point_id, range)` - Read historical data
- `batch_read(point_ids)` - Read multiple points at once

### Navigation & Discovery
- `nav(nav_id)` - Navigate station hierarchy
- `get_equipment(filter)` - Get equipment with points
- `get_alarms(filter)` - Query current alarms

### Real-time Monitoring
- `watch_subscribe(filter, lease_minutes)` - Subscribe to updates
- `watch_poll(watch_id)` - Poll for changes

### Advanced
- `execute_custom_filter(filter, limit)` - Custom queries

## Example Haystack Filters

```python
# Temperature sensors
"point and temp and sensor"

# Writable setpoints
"point and sp and writable"

# VAV boxes in alarm
"equip and vav and alarmStatus"

# Points from specific equipment
"point and equipRef==@equipmentId"

# Active alarms
"alarm and not acked"
```

## AI Assistant Usage Examples

Once connected, an AI assistant can:

- "What's the current status of all AHUs?"
- "Show me temperature trends for the conference room"
- "Set zone 101 temperature to 72°F"
- "Which equipment has active alarms?"
- "Monitor all CO2 sensors for the next hour"

## Publishing to GitHub

1. Create a new repository on GitHub
2. Add your code:
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/yourusername/niagara-mcp.git
git push -u origin main
```

3. Create a `pyproject.toml` for `uvx` compatibility:
```toml
[project]
name = "niagara-mcp"
version = "1.0.0"
dependencies = [
    "fastmcp>=0.1.0",
    "httpx>=0.25.0",
    "pydantic>=2.0.0"
]

[project.scripts]
niagara-mcp = "niagara_mcp:main"
```

4. Users can now run directly:
```bash
uvx --from git+https://github.com/yourusername/niagara-mcp.git niagara-mcp
```

## Security Considerations

- **Local Mode**: Credentials stored locally, most secure
- **Relay Mode**: Use HTTPS and strong API tokens
- **Hybrid Mode**: Convenient but stores credentials locally
- **Docker**: Isolates the MCP server from host system
- **Production**: Use secrets management (Vault, AWS Secrets Manager, etc.)

## Troubleshooting

### Connection Issues
- Verify Niagara station is accessible
- Check nhaystack module is installed
- Confirm credentials have API permissions
- Try `get_connection_info()` tool first

### Relay Mode Issues
- Verify relay API is running and accessible
- Check API token is correct
- Ensure relay can reach Niagara system

### Docker Issues
- Use `host.docker.internal` for local Niagara on host
- Check network settings in docker-compose
- View logs: `docker logs niagara-mcp`

## Contributing

Contributions welcome! Please ensure:
- Code follows Python best practices
- All tools include error handling
- Documentation is updated
- Tests are included for new features

## License

MIT License - See LICENSE file for details

## Support

For issues or questions:
1. Check the troubleshooting section
2. Review Haystack documentation at project-haystack.org
3. Open an issue on GitHub
4. Contact your Niagara system administrator
