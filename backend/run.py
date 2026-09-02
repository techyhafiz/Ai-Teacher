"""Run the AI Teacher backend.

    cd backend
    python run.py            (needs .env with GEMINI_API_KEY)
"""
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )
