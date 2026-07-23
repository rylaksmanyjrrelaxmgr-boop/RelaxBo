#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
خادم الويب - ريلاكس مانيجر
الإصدار: 19.3.1
"""

import os
import sys
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
    from pydantic import BaseModel
    import uvicorn
    from contextlib import asynccontextmanager
    import psutil
except ImportError as e:
    print(f"⚠️ بعض المكتبات غير مثبتة: {e}")
    print("📌 قم بتثبيتها: pip install fastapi uvicorn psutil plotly aiofiles markdown pydantic")

logger = logging.getLogger(__name__)

# ===================== المسارات =====================
BASE_PATH = Path(__file__).parent.resolve()
TEMPLATES_PATH = BASE_PATH / "templates"
STATIC_PATH = BASE_PATH / "static"

TEMPLATES_PATH.mkdir(parents=True, exist_ok=True)
STATIC_PATH.mkdir(parents=True, exist_ok=True)

# ===================== النماذج =====================
class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    timestamp: str = ""

class BotStatus(BaseModel):
    status: str
    uptime: float
    users_count: int
    groups_count: int
    channels_count: int
    posts_count: int
    memory_usage: float
    cpu_usage: float
    version: str = "19.3.1"

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

# ===================== التطبيق =====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 بدء تشغيل خادم الويب...")
    yield
    logger.info("🛑 إيقاف خادم الويب...")

app = FastAPI(
    title="ريلاكس مانيجر - لوحة التحكم",
    description="API لإدارة البوت",
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
            'memory_used_mb': memory.used / (1024 * 1024),
            'memory_total_mb': memory.total / (1024 * 1024),
            'cpu_usage': psutil.cpu_percent(interval=0.5),
            'uptime_seconds': asyncio.get_event_loop().time()
        }
    except Exception as e:
        logger.error(f"خطأ في جلب إحصائيات النظام: {e}")
        return {'memory_usage': 0, 'memory_used_mb': 0, 'memory_total_mb': 0, 'cpu_usage': 0, 'uptime_seconds': 0}

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

@app.get("/api/health", response_model=ApiResponse)
async def health_check():
    system = get_system_stats()
    return ApiResponse(
        success=True,
        message="الخادم يعمل بشكل طبيعي",
        data={
            "status": "healthy",
            "uptime": system['uptime_seconds'],
            "version": "19.3.1"
        },
        timestamp=datetime.now().isoformat()
    )

@app.get("/api/stats", response_model=ApiResponse)
async def get_stats():
    stats = get_bot_stats()
    system = get_system_stats()
    return ApiResponse(
        success=True,
        message="تم جلب الإحصائيات بنجاح",
        data={
            "bot": stats,
            "system": system,
            "websocket_connections": ws_manager.connection_count
        },
        timestamp=datetime.now().isoformat()
    )

@app.get("/api/users", response_model=ApiResponse)
async def get_users():
    try:
        import sqlite3
        db_path = BASE_PATH / "data" / "bot_data.db"
        if not db_path.exists():
            return ApiResponse(
                success=False,
                message="قاعدة البيانات غير موجودة",
                timestamp=datetime.now().isoformat()
            )
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.user_id, 
                   COALESCE(uc.username, 'user_' || u.user_id) as username,
                   COALESCE(uc.first_name, '') as first_name,
                   u.subscription_end,
                   u.banned,
                   u.trial_used,
                   (SELECT COUNT(*) FROM user_channels WHERE user_id = u.user_id) as channels_count,
                   (SELECT COUNT(*) FROM posts p JOIN user_channels uc2 ON p.channel_db_id = uc2.id WHERE uc2.user_id = u.user_id) as posts_count
            FROM users u
            LEFT JOIN users_cache uc ON u.user_id = uc.user_id
            ORDER BY u.user_id
            LIMIT 100
        """)
        rows = cursor.fetchall()
        conn.close()
        
        users = []
        for row in rows:
            user_id = row[0]
            username = row[1] or f"user_{user_id}"
            first_name = row[2] or ""
            subscription_end = row[3]
            is_subscribed = False
            days_left = 0
            
            if subscription_end:
                try:
                    end_date = datetime.fromisoformat(subscription_end)
                    now = datetime.now()
                    if end_date > now:
                        is_subscribed = True
                        days_left = (end_date - now).days
                except:
                    pass
            
            users.append({
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "is_subscribed": is_subscribed,
                "subscription_days_left": days_left,
                "is_banned": bool(row[4]),
                "has_used_trial": bool(row[5]),
                "channels_count": row[6] or 0,
                "posts_count": row[7] or 0
            })
        
        return ApiResponse(
            success=True,
            message=f"تم جلب {len(users)} مستخدم",
            data={"users": users, "total": len(users)},
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        return ApiResponse(
            success=False,
            message=f"فشل جلب المستخدمين: {str(e)}",
            timestamp=datetime.now().isoformat()
        )

@app.get("/api/channels/{user_id}", response_model=ApiResponse)
async def get_user_channels(user_id: int):
    try:
        import sqlite3
        db_path = BASE_PATH / "data" / "bot_data.db"
        if not db_path.exists():
            return ApiResponse(
                success=False,
                message="قاعدة البيانات غير موجودة",
                timestamp=datetime.now().isoformat()
            )
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, channel_id, channel_name, created_at, banned 
            FROM user_channels 
            WHERE user_id = ?
            ORDER BY id
        """, (user_id,))
        rows = cursor.fetchall()
        conn.close()
        
        channels = [
            {
                "id": row[0],
                "channel_id": row[1],
                "channel_name": row[2] or row[1],
                "created_at": row[3],
                "is_banned": bool(row[4]) if len(row) > 4 else False
            }
            for row in rows
        ]
        
        return ApiResponse(
            success=True,
            message=f"تم جلب {len(channels)} قناة",
            data={"channels": channels},
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        return ApiResponse(
            success=False,
            message=f"فشل جلب القنوات: {str(e)}",
            timestamp=datetime.now().isoformat()
        )

@app.get("/api/groups/{user_id}", response_model=ApiResponse)
async def get_user_groups(user_id: int):
    try:
        import sqlite3
        db_path = BASE_PATH / "data" / "bot_data.db"
        if not db_path.exists():
            return ApiResponse(
                success=False,
                message="قاعدة البيانات غير موجودة",
                timestamp=datetime.now().isoformat()
            )
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT chat_id, chat_name, username, added_at, banned
            FROM bot_groups 
            WHERE added_by = ?
               OR EXISTS (SELECT 1 FROM hidden_owner_groups hog WHERE hog.chat_id = bot_groups.chat_id AND hog.owner_id = ?)
               OR EXISTS (SELECT 1 FROM hidden_admins ha WHERE ha.chat_id = bot_groups.chat_id AND ha.admin_id = ?)
            ORDER BY chat_name
        """, (user_id, user_id, user_id))
        rows = cursor.fetchall()
        conn.close()
        
        groups = [
            {
                "chat_id": row[0],
                "chat_name": row[1],
                "username": row[2],
                "added_at": row[3],
                "is_banned": bool(row[4]) if len(row) > 4 else False
            }
            for row in rows
        ]
        
        return ApiResponse(
            success=True,
            message=f"تم جلب {len(groups)} مجموعة",
            data={"groups": groups},
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        return ApiResponse(
            success=False,
            message=f"فشل جلب المجموعات: {str(e)}",
            timestamp=datetime.now().isoformat()
        )

@app.get("/api/posts/{channel_id}", response_model=ApiResponse)
async def get_channel_posts(channel_id: int, limit: int = 50):
    try:
        import sqlite3
        db_path = BASE_PATH / "data" / "bot_data.db"
        if not db_path.exists():
            return ApiResponse(
                success=False,
                message="قاعدة البيانات غير موجودة",
                timestamp=datetime.now().isoformat()
            )
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, text, media_type, published, created_at, views_count
            FROM posts 
            WHERE channel_db_id = ? 
            ORDER BY id DESC 
            LIMIT ?
        """, (channel_id, limit))
        rows = cursor.fetchall()
        conn.close()
        
        posts = [
            {
                "id": row[0],
                "text": row[1][:200] + "..." if row[1] and len(row[1]) > 200 else row[1],
                "media_type": row[2] or "text",
                "is_published": bool(row[3]),
                "created_at": row[4],
                "views_count": row[5] or 0
            }
            for row in rows
        ]
        
        return ApiResponse(
            success=True,
            message=f"تم جلب {len(posts)} منشور",
            data={"posts": posts},
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        return ApiResponse(
            success=False,
            message=f"فشل جلب المنشورات: {str(e)}",
            timestamp=datetime.now().isoformat()
        )

@app.get("/api/subscription/{user_id}", response_model=ApiResponse)
async def get_user_subscription(user_id: int):
    try:
        import sqlite3
        db_path = BASE_PATH / "data" / "bot_data.db"
        if not db_path.exists():
            return ApiResponse(
                success=False,
                message="قاعدة البيانات غير موجودة",
                timestamp=datetime.now().isoformat()
            )
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT subscription_end, trial_used 
            FROM users 
            WHERE user_id = ?
        """, (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return ApiResponse(
                success=False,
                message="المستخدم غير موجود",
                timestamp=datetime.now().isoformat()
            )
        
        subscription_end = row[0]
        is_subscribed = False
        days_left = 0
        
        if subscription_end:
            try:
                end_date = datetime.fromisoformat(subscription_end)
                now = datetime.now()
                if end_date > now:
                    is_subscribed = True
                    days_left = (end_date - now).days
            except:
                pass
        
        return ApiResponse(
            success=True,
            message="تم جلب معلومات الاشتراك",
            data={
                "is_subscribed": is_subscribed,
                "days_left": days_left,
                "has_used_trial": bool(row[1]),
                "subscription_end": subscription_end
            },
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        return ApiResponse(
            success=False,
            message=f"فشل جلب الاشتراك: {str(e)}",
            timestamp=datetime.now().isoformat()
        )

# ===================== WebSocket =====================
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
                elif message.get("type") == "get_users":
                    # يمكن إضافة جلب المستخدمين هنا
                    await websocket.send_text(json.dumps({
                        "type": "users",
                        "data": {"message": "جاري تحميل المستخدمين..."},
                        "timestamp": datetime.now().isoformat()
                    }))
                else:
                    await websocket.send_text(json.dumps({
                        "type": "echo",
                        "data": message,
                        "timestamp": datetime.now().isoformat()
                    }))
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "رسالة غير صالحة",
                    "timestamp": datetime.now().isoformat()
                }))
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)

# ===================== الصفحة الرئيسية =====================
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
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

# ===================== صفحة 404 =====================
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception):
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>404 - الصفحة غير موجودة</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
                color: white;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                text-align: center;
            }
            .container {
                max-width: 600px;
                padding: 40px;
            }
            h1 { font-size: 72px; margin: 0; color: #e94560; }
            h2 { font-size: 24px; margin: 20px 0; }
            p { color: #a8a8b3; line-height: 1.6; }
            a {
                color: #e94560;
                text-decoration: none;
                border: 2px solid #e94560;
                padding: 10px 30px;
                border-radius: 25px;
                display: inline-block;
                margin-top: 20px;
                transition: all 0.3s;
            }
            a:hover {
                background: #e94560;
                color: white;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>404</h1>
            <h2>الصفحة غير موجودة</h2>
            <p>عذراً، الصفحة التي تبحث عنها غير موجودة أو تم نقلها.</p>
            <a href="/">العودة إلى الصفحة الرئيسية</a>
        </div>
    </body>
    </html>
    """, status_code=404)

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
web_app = app  # ✅ هذا السطر مهم للاستيراد في bot.py

__all__ = [
    'app',
    'web_app',
    'ws_manager',
    'start_web_server',
    'health_check',
    'dashboard',
    'websocket_endpoint'
]

# ===================== تشغيل مباشر =====================
if __name__ == "__main__":
    import asyncio
    asyncio.run(start_web_server())
# تحديث: Thu Jul 23 03:23:39 +03 2026
