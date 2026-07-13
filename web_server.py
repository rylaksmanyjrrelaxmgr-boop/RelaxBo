#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
خادم الويب - ريلاكس مانيجر
الإصدار: 19.3.1
"""

import os
import json
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

# ===================== استيراد المكتبات =====================
try:
    from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    from pydantic import BaseModel  # ✅ هذا السطر المفقود
    import uvicorn
    from contextlib import asynccontextmanager
    import psutil
except ImportError as e:
    print(f"⚠️ بعض المكتبات غير مثبتة: {e}")

logger = logging.getLogger(__name__)

# ===================== المسارات =====================
BASE_PATH = Path(__file__).parent.resolve()
TEMPLATES_PATH = BASE_PATH / "templates"
STATIC_PATH = BASE_PATH / "static"

TEMPLATES_PATH.mkdir(parents=True, exist_ok=True)
STATIC_PATH.mkdir(parents=True, exist_ok=True)

# ===================== WebSocket Manager =====================
class WebSocketManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except:
                pass

    @property
    def connection_count(self) -> int:
        return len(self.active_connections)

ws_manager = WebSocketManager()

# ===================== النماذج =====================
class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    timestamp: str = ""

# ===================== التطبيق =====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 بدء تشغيل خادم الويب...")
    yield
    logger.info("🛑 إيقاف خادم الويب...")

app = FastAPI(
    title="ريلاكس مانيجر - لوحة التحكم",
    version="19.3.1",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory=str(TEMPLATES_PATH))
app.mount("/static", StaticFiles(directory=str(STATIC_PATH)), name="static")

# ===================== دوال مساعدة =====================
def get_bot_stats():
    try:
        import sqlite3
        db_path = BASE_PATH / "data" / "bot_data.db"
        if not db_path.exists():
            return {'users_count': 0, 'groups_count': 0, 'channels_count': 0, 'posts_count': 0}
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM bot_groups")
        groups = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM user_channels")
        channels = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM posts")
        posts = cursor.fetchone()[0]
        conn.close()
        return {'users_count': users, 'groups_count': groups, 'channels_count': channels, 'posts_count': posts}
    except Exception as e:
        logger.error(f"خطأ في جلب الإحصائيات: {e}")
        return {'users_count': 0, 'groups_count': 0, 'channels_count': 0, 'posts_count': 0}

def get_system_stats():
    try:
        memory = psutil.virtual_memory()
        return {
            'memory_usage': memory.percent,
            'cpu_usage': psutil.cpu_percent(interval=0.5),
            'uptime_seconds': asyncio.get_event_loop().time()
        }
    except Exception as e:
        logger.error(f"خطأ في جلب إحصائيات النظام: {e}")
        return {'memory_usage': 0, 'cpu_usage': 0, 'uptime_seconds': 0}

# ===================== نقاط النهاية =====================
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    stats = get_bot_stats()
    system = get_system_stats()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "ريلاكس مانيجر - لوحة التحكم",
            "version": "19.3.1",
            "stats": stats,
            "system": system,
            "ws_manager": ws_manager
        }
    )

@app.get("/api/health")
async def health_check():
    return JSONResponse({
        "success": True,
        "message": "الخادم يعمل بشكل طبيعي",
        "timestamp": datetime.now().isoformat()
    })

@app.get("/api/stats")
async def get_stats():
    stats = get_bot_stats()
    system = get_system_stats()
    return JSONResponse({
        "success": True,
        "data": {
            "bot": stats,
            "system": system,
            "websocket_connections": ws_manager.connection_count
        },
        "timestamp": datetime.now().isoformat()
    })

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                elif message.get("type") == "get_stats":
                    stats = get_bot_stats()
                    system = get_system_stats()
                    await websocket.send_text(json.dumps({
                        "type": "stats",
                        "data": {"bot": stats, "system": system},
                        "timestamp": datetime.now().isoformat()
                    }))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)

# ===================== تشغيل الخادم =====================
async def start_web_server():
    try:
        port = int(os.getenv("PORT", 8000))
        host = os.getenv("HOST", "0.0.0.0")
        logger.info(f"🌐 خادم الويب على http://{host}:{port}")
        config = uvicorn.Config(app, host=host, port=port, log_level="info", workers=1)
        server = uvicorn.Server(config)
        await server.serve()
    except Exception as e:
        logger.error(f"❌ فشل تشغيل خادم الويب: {e}")
        raise

# ===================== الصادرات =====================
__all__ = ['app', 'ws_manager', 'start_web_server', 'health_check', 'websocket_endpoint']
