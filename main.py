"""OnlyCat Dashboard — cat activity monitor."""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from onlycat_client import OnlyCatClient

load_dotenv()
logging.basicConfig(level=logging.INFO)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# Connected browser WebSockets
browser_clients: set[WebSocket] = set()
client: OnlyCatClient | None = None


async def broadcast_update():
    """Push state to all connected browsers."""
    if client is None:
        return
    payload = json.dumps(await client.serialize_state())
    for ws in list(browser_clients):
        try:
            await ws.send_text(payload)
        except Exception:
            browser_clients.discard(ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    token = os.environ.get("ONLYCAT_TOKEN")
    if not token:
        logging.error("ONLYCAT_TOKEN not set. Create a .env file with your token.")
        yield
        return

    client = OnlyCatClient(token, on_update=broadcast_update)
    task = asyncio.create_task(client.start())
    yield
    await client.stop()
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    state = (await client.serialize_state()) if client else {
        "devices": [], "events": [], "pets": [], "connected": False, "charts": None
    }
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "initial_state": state},
    )


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    browser_clients.add(ws)
    # Send current state immediately
    if client:
        await ws.send_text(json.dumps(await client.serialize_state()))
    try:
        while True:
            await ws.receive_text()  # keep alive
    except WebSocketDisconnect:
        pass
    finally:
        browser_clients.discard(ws)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
