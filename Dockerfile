# Dockerfile for Niagara MCP Server
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the MCP server
COPY niagara_mcp.py .
COPY mcp.json .

# Create non-root user
RUN useradd -m -u 1000 mcp && chown -R mcp:mcp /app
USER mcp

# Set environment variables defaults
ENV DEPLOYMENT_MODE=local
ENV NIAGARA_HOST=localhost
ENV NIAGARA_PORT=8080
ENV PYTHONUNBUFFERED=1

# Run the MCP server
CMD ["python", "niagara_mcp.py"]
