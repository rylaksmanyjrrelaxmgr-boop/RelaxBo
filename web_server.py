#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
خادم الويب - ريلاكس مانيجر
الإصدار: 19.3.1
المطور: @RelaxMgr
"""

import os
import sys
import json
import logging
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable, Awaitable
import secrets

# ===================== استيراد المكتبات =====================
try:
    from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect, Depends
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    from pydantic import BaseModel
    import uvicorn
    from contextlib import asynccontextmanager
    import psutil
    import plotly.graph_objects as go
    import plotly.utils
    import json as json_module
    import aiofiles
    import markdown
    from datetime import datetime, timezone
    import base64
    import hashlib
    import hmac
    import time
except ImportError as e:
    print(f"⚠️ بعض المكتبات غير مثبتة: {e}")
    print("📌 قم بتثبيتها: pip install fastapi uvicorn psutil plotly aiofiles markdown")

# ===================== إعدادات التسجيل =====================
logger = logging.getLogger(__name__)

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

class ChannelStats(BaseModel):
    channel_id: str
    channel_name: str
    total_posts: int
    published_posts: int
    unpublished_posts: int
    total_views: int
    avg_views: float

class UserStats(BaseModel):
    user_id: int
    username: str
    first_name: str
    is_subscribed: bool
    subscription_days_left: int
    total_posts: int
    total_channels: int
    total_groups: int

# ===================== الأمان =====================
security = HTTPBearer()
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", secrets.token_urlsafe(32))
START_TIME = time.time()

# ===================== مدير WebSocket =====================
class WebSocketManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()
        self._clients: Dict[str, WebSocket] = {}
        self._broadcast_tasks: Dict[str, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket, client_id: str = None):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
            if client_id:
                self._clients[client_id] = websocket
        logger.info(f"🔌 WebSocket متصل: {client_id or 'unknown'}")
        await self.broadcast({"type": "connection", "status": "connected", "client_id": client_id})

    async def disconnect(self, websocket: WebSocket, client_id: str = None):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
            if client_id and client_id in self._clients:
                del self._clients[client_id]
        logger.info(f"🔌 WebSocket مفصول: {client_id or 'unknown'}")

    async def send_message(self, websocket: WebSocket, message: dict):
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"❌ فشل إرسال رسالة WebSocket: {e}")

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                disconnected.append(connection)
        
        async with self._lock:
            for connection in disconnected:
                if connection in self.active_connections:
                    self.active_connections.remove(connection)

    async def send_to_client(self, client_id: str, message: dict):
        if client_id in self._clients:
            await self.send_message(self._clients[client_id], message)
            return True
        return False

    @property
    def connection_count(self) -> int:
        return len(self.active_connections)

ws_manager = WebSocketManager()

# ===================== دورة حياة التطبيق =====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """إدارة دورة حياة التطبيق"""
    logger.info("🚀 بدء تشغيل خادم الويب...")
    
    # بدء مهام الخلفية
    asyncio.create_task(background_stats_updater())
    asyncio.create_task(background_cleanup())
    
    yield
    
    logger.info("🛑 إيقاف خادم الويب...")
    # إغلاق الاتصالات
    for ws in ws_manager.active_connections:
        try:
            await ws.close()
        except:
            pass
    ws_manager.active_connections.clear()

# ===================== التطبيق الرئيسي =====================
app = FastAPI(
    title="ريلاكس مانيجر - لوحة التحكم",
    description="API لإدارة البوت",
    version="19.3.1",
    lifespan=lifespan
)

# ===================== إعدادات CORS =====================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================== المسارات =====================
BASE_PATH = Path(__file__).parent.resolve()
TEMPLATES_PATH = BASE_PATH / "templates"
STATIC_PATH = BASE_PATH / "static"

# إنشاء المجلدات إذا لم تكن موجودة
TEMPLATES_PATH.mkdir(parents=True, exist_ok=True)
STATIC_PATH.mkdir(parents=True, exist_ok=True)

# ===================== قوالب Jinja2 =====================
templates = Jinja2Templates(directory=str(TEMPLATES_PATH))

# ===================== ملفات ثابتة =====================
app.mount("/static", StaticFiles(directory=str(STATIC_PATH)), name="static")

# ===================== دوال مساعدة =====================
def get_bot_stats() -> dict:
    """جلب إحصائيات البوت"""
    try:
        # محاولة جلب الإحصائيات من قاعدة البيانات
        import sqlite3
        db_path = BASE_PATH / "data" / "bot_data.db"
        
        if not db_path.exists():
            return {
                'users_count': 0,
                'groups_count': 0,
                'channels_count': 0,
                'posts_count': 0
            }
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        users_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM bot_groups")
        groups_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM user_channels")
        channels_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM posts")
        posts_count = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'users_count': users_count,
            'groups_count': groups_count,
            'channels_count': channels_count,
            'posts_count': posts_count
        }
    except Exception as e:
        logger.error(f"❌ فشل جلب الإحصائيات: {e}")
        return {
            'users_count': 0,
            'groups_count': 0,
            'channels_count': 0,
            'posts_count': 0
        }

def get_system_stats() -> dict:
    """جلب إحصائيات النظام"""
    try:
        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=0.5)
        
        return {
            'memory_usage': memory.percent,
            'memory_used_mb': memory.used / (1024 * 1024),
            'memory_total_mb': memory.total / (1024 * 1024),
            'cpu_usage': cpu_percent,
            'uptime_seconds': time.time() - START_TIME
        }
    except Exception as e:
        logger.error(f"❌ فشل جلب إحصائيات النظام: {e}")
        return {
            'memory_usage': 0,
            'memory_used_mb': 0,
            'memory_total_mb': 0,
            'cpu_usage': 0,
            'uptime_seconds': 0
        }

def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
    """التحقق من مفتاح API"""
    if credentials.credentials == ADMIN_API_KEY:
        return True
    raise HTTPException(status_code=401, detail="مفتاح API غير صالح")

# ===================== نقاط النهاية (Endpoints) =====================

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """الصفحة الرئيسية"""
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "ريلاكس مانيجر - لوحة التحكم",
            "version": "19.3.1"
        }
    )

@app.get("/api/health", response_model=ApiResponse)
async def health_check():
    """فحص صحة الخادم"""
    stats = get_bot_stats()
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
async def get_stats(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """الحصول على إحصائيات البوت"""
    try:
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
    except Exception as e:
        return ApiResponse(
            success=False,
            message=f"فشل جلب الإحصائيات: {str(e)}",
            timestamp=datetime.now().isoformat()
        )

@app.get("/api/channels/{user_id}", response_model=ApiResponse)
async def get_user_channels(user_id: int):
    """الحصول على قنوات المستخدم"""
    try:
        # محاولة جلب القنوات من قاعدة البيانات
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
        cursor.execute("SELECT id, channel_id, channel_name, created_at FROM user_channels WHERE user_id = ?", (user_id,))
        rows = cursor.fetchall()
        conn.close()
        
        channels = [
            {
                "id": row[0],
                "channel_id": row[1],
                "channel_name": row[2] or row[1],
                "created_at": row[3]
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
    """الحصول على مجموعات المستخدم"""
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
            SELECT chat_id, chat_name, username, added_at 
            FROM bot_groups 
            WHERE added_by = ?
            ORDER BY chat_name
        """, (user_id,))
        rows = cursor.fetchall()
        conn.close()
        
        groups = [
            {
                "chat_id": row[0],
                "chat_name": row[1],
                "username": row[2],
                "added_at": row[3]
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

@app.get("/api/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """لوحة التحكم الرئيسية"""
    stats = get_bot_stats()
    system = get_system_stats()
    
    # إنشاء رسوم بيانية
    try:
        # رسم بياني للنشاط
        fig = go.Figure()
        
        # بيانات وهمية للرسم البياني (يمكن استبدالها ببيانات حقيقية)
        dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7, -1, -1)]
        posts_data = [random.randint(5, 30) for _ in range(8)]
        users_data = [random.randint(10, 50) for _ in range(8)]
        
        fig.add_trace(go.Scatter(x=dates, y=posts_data, name="المنشورات", mode="lines+markers"))
        fig.add_trace(go.Scatter(x=dates, y=users_data, name="المستخدمين", mode="lines+markers"))
        
        fig.update_layout(
            title="نشاط البوت",
            xaxis_title="التاريخ",
            yaxis_title="العدد",
            template="plotly_dark"
        )
        
        chart_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
    except Exception as e:
        chart_json = "{}"
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "ريلاكس مانيجر - لوحة التحكم",
            "version": "19.3.1",
            "stats": stats,
            "system": system,
            "chart": chart_json,
            "websocket_url": "/ws"
        }
    )

@app.get("/api/users", response_model=ApiResponse)
async def get_users(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """الحصول على قائمة المستخدمين"""
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
        
        # الحصول على المستخدمين مع معلومات الاشتراك
        cursor.execute("""
            SELECT u.user_id, uc.username, uc.first_name, 
                   u.subscription_end, u.banned, u.trial_used,
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

@app.get("/api/posts/{channel_id}")
async def get_channel_posts(channel_id: int, limit: int = 50):
    """الحصول على منشورات القناة"""
    try:
        import sqlite3
        db_path = BASE_PATH / "data" / "bot_data.db"
        
        if not db_path.exists():
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "قاعدة البيانات غير موجودة"}
            )
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, text, media_type, published, created_at 
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
                "created_at": row[4]
            }
            for row in rows
        ]
        
        return JSONResponse(content={
            "success": True,
            "data": {"posts": posts},
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"فشل جلب المنشورات: {str(e)}"}
        )

@app.get("/api/subscription/{user_id}")
async def get_user_subscription(user_id: int):
    """الحصول على معلومات اشتراك المستخدم"""
    try:
        import sqlite3
        db_path = BASE_PATH / "data" / "bot_data.db"
        
        if not db_path.exists():
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "قاعدة البيانات غير موجودة"}
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
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "المستخدم غير موجود"}
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
        
        return JSONResponse(content={
            "success": True,
            "data": {
                "is_subscribed": is_subscribed,
                "days_left": days_left,
                "has_used_trial": bool(row[1]),
                "subscription_end": subscription_end
            },
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"فشل جلب الاشتراك: {str(e)}"}
        )

# ===================== WebSocket =====================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """نقطة اتصال WebSocket"""
    client_id = None
    try:
        # قبول الاتصال
        await ws_manager.connect(websocket)
        client_id = secrets.token_hex(8)
        
        # إرسال رسالة ترحيب
        await ws_manager.send_message(websocket, {
            "type": "welcome",
            "client_id": client_id,
            "message": "مرحباً بك في لوحة تحكم ريلاكس مانيجر",
            "timestamp": datetime.now().isoformat()
        })
        
        # حلقة استماع
        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)
                
                # معالجة الرسائل المختلفة
                if message.get("type") == "ping":
                    await ws_manager.send_message(websocket, {
                        "type": "pong",
                        "timestamp": datetime.now().isoformat()
                    })
                elif message.get("type") == "get_stats":
                    stats = get_bot_stats()
                    system = get_system_stats()
                    await ws_manager.send_message(websocket, {
                        "type": "stats",
                        "data": {
                            "bot": stats,
                            "system": system
                        },
                        "timestamp": datetime.now().isoformat()
                    })
                elif message.get("type") == "get_users":
                    # يمكن إضافة جلب المستخدمين هنا
                    await ws_manager.send_message(websocket, {
                        "type": "users",
                        "data": {"message": "جاري تحميل المستخدمين..."},
                        "timestamp": datetime.now().isoformat()
                    })
                else:
                    await ws_manager.send_message(websocket, {
                        "type": "echo",
                        "data": message,
                        "timestamp": datetime.now().isoformat()
                    })
                    
            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await ws_manager.send_message(websocket, {
                    "type": "error",
                    "message": "رسالة غير صالحة",
                    "timestamp": datetime.now().isoformat()
                })
                
    except Exception as e:
        logger.error(f"❌ خطأ في WebSocket: {e}")
    finally:
        await ws_manager.disconnect(websocket, client_id)

# ===================== مهام الخلفية =====================
async def background_stats_updater():
    """تحديث الإحصائيات في الخلفية"""
    while True:
        try:
            await asyncio.sleep(30)  # كل 30 ثانية
            stats = get_bot_stats()
            system = get_system_stats()
            
            # بث الإحصائيات لجميع الاتصالات
            await ws_manager.broadcast({
                "type": "stats_update",
                "data": {
                    "bot": stats,
                    "system": system,
                    "timestamp": datetime.now().isoformat()
                }
            })
        except Exception as e:
            logger.error(f"❌ خطأ في تحديث الإحصائيات: {e}")
        await asyncio.sleep(30)

async def background_cleanup():
    """تنظيف الخلفية"""
    while True:
        try:
            await asyncio.sleep(3600)  # كل ساعة
            
            # تنظيف الاتصالات الميتة
            dead_connections = []
            for ws in ws_manager.active_connections:
                try:
                    await ws.send_text(json.dumps({"type": "ping"}))
                except:
                    dead_connections.append(ws)
            
            for ws in dead_connections:
                if ws in ws_manager.active_connections:
                    ws_manager.active_connections.remove(ws)
            
            if dead_connections:
                logger.info(f"🧹 تم تنظيف {len(dead_connections)} اتصال ميت")
                
        except Exception as e:
            logger.error(f"❌ خطأ في التنظيف: {e}")
        await asyncio.sleep(3600)

# ===================== صفحة 404 =====================
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
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
    """بدء تشغيل خادم الويب"""
    try:
        port = int(os.getenv("PORT", 8000))
        host = os.getenv("HOST", "0.0.0.0")
        
        logger.info(f"🌐 بدء خادم الويب على http://{host}:{port}")
        
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info",
            access_log=False,
            workers=1
        )
        
        server = uvicorn.Server(config)
        await server.serve()
        
    except Exception as e:
        logger.error(f"❌ فشل بدء خادم الويب: {e}")
        raise

# ===================== نقاط تصدير =====================
__all__ = [
    'app',
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
