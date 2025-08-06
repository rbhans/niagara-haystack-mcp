"""
Example Remote API Gateway for Niagara Haystack
This would run on a cloud server to relay requests to your Niagara system
"""

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
import httpx
from typing import Dict, Any, Optional
import os
from pydantic import BaseModel

app = FastAPI(title="Niagara Haystack Relay API")
security = HTTPBearer()

# Configure CORS for web access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
NIAGARA_HOST = os.getenv("NIAGARA_HOST", "localhost")
NIAGARA_PORT = os.getenv("NIAGARA_PORT", "8080")
NIAGARA_USERNAME = os.getenv("NIAGARA_USERNAME")
NIAGARA_PASSWORD = os.getenv("NIAGARA_PASSWORD")
HAYSTACK_PATH = os.getenv("HAYSTACK_PATH", "/haystack")
API_TOKENS = set(os.getenv("API_TOKENS", "").split(","))  # Comma-separated valid tokens
USE_HTTPS = os.getenv("USE_HTTPS", "false").lower() == "true"

class HaystackRequest(BaseModel):
    """Request model for Haystack operations"""
    operation: str
    params: Optional[Dict[str, Any]] = None

class HaystackResponse(BaseModel):
    """Response model for Haystack operations"""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
    """Verify the API token"""
    token = credentials.credentials
    if token not in API_TOKENS:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    return True

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "Niagara Haystack Relay"}

@app.post("/haystack", response_model=HaystackResponse)
async def relay_haystack(
    request: HaystackRequest,
    authenticated: bool = Depends(verify_token)
):
    """
    Relay Haystack operations to Niagara system
    """
    try:
        # Build the URL for the Niagara system
        protocol = "https" if USE_HTTPS else "http"
        base_url = f"{protocol}://{NIAGARA_HOST}:{NIAGARA_PORT}{HAYSTACK_PATH}"
        url = f"{base_url}/{request.operation}"

        # Create HTTP client with authentication
        async with httpx.AsyncClient(
            auth=(NIAGARA_USERNAME, NIAGARA_PASSWORD) if NIAGARA_USERNAME else None,
            timeout=30.0
        ) as client:
            # Forward the request to Niagara
            response = await client.post(url, json=request.params or {})
            response.raise_for_status()

            # Return the response
            return HaystackResponse(
                success=True,
                data=response.json()
            )

    except httpx.HTTPStatusError as e:
        return HaystackResponse(
            success=False,
            error=f"Niagara returned error: {e.response.status_code}"
        )
    except Exception as e:
        return HaystackResponse(
            success=False,
            error=str(e)
        )

@app.post("/batch", response_model=Dict[str, Any])
async def batch_operations(
    operations: list[HaystackRequest],
    authenticated: bool = Depends(verify_token)
):
    """
    Execute multiple Haystack operations in a single request
    """
    results = []
    for op in operations:
        result = await relay_haystack(op, authenticated)
        results.append(result.dict())

    return {
        "count": len(results),
        "results": results
    }

@app.get("/cache/points")
async def get_cached_points(
    authenticated: bool = Depends(verify_token)
):
    """
    Get cached point list (implement caching as needed)
    """
    # This is where you could implement caching logic
    # to reduce load on the Niagara system
    return {"message": "Caching not implemented in this example"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
