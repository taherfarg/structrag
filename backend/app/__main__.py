"""`python -m app`: serve the API. Sets the selector event loop psycopg needs on Windows."""

import asyncio
import os
import sys

import uvicorn

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

config = uvicorn.Config("app.main:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")),
                        loop="none", proxy_headers=True, log_config=None)
asyncio.run(uvicorn.Server(config).serve())
