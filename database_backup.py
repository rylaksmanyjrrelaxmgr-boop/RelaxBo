#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_backup.py - دوال النسخ الاحتياطي والاستعادة (v7.4.7)
================================================================================
BackupMixin:
  - _compress_backup      : ضغط ملف النسخة الاحتياطية بـ gzip
  - _check_tool_exists    : التحقق من وجود أداة (pg_dump, mysqldump, ...)
  - _find_pg_tool         : البحث عن pg_dump/pg_restore مع دعم الإصدارات
  - backup_database       : إنشاء نسخة احتياطية (PostgreSQL/MySQL/SQLite)
  - restore_database      : استعادة نسخة احتياطية
  - vacuum_database       : VACUUM/OPTIMIZE لقاعدة البيانات
  - backup_auto_replies   : نسخ الردود التلقائية إلى JSON

🆕 v7.4.7:
  🔴 FIX: دعم pg_dump/pg_restore بإصدارات متعددة (pg_dump-17/16/15/...)
  🔴 FIX: رسائل خطأ توضح طريقة الإصلاح (تثبيت postgresql-client)
================================================================================
"""

import os
import re
import json
import gzip
import shutil
import sqlite3
import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class BackupMixin:
    """Mixin يحتوي كل دوال النسخ الاحتياطي والاستعادة"""

    # =====================================================================
    # 1) ضغط النسخة الاحتياطية
    # =====================================================================

    async def _compress_backup(self, file_path: Path) -> Optional[Path]:
        try:
            compressed_path = file_path.with_suffix(file_path.suffix + ".gz")
            with open(file_path, "rb") as f_in:
                with gzip.open(compressed_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out, length=65536)
            if compressed_path.exists() and compressed_path.stat().st_size > 0:
                try:
                    with gzip.open(compressed_path, "rb") as f:
                        f.read(1)
                except Exception:
                    logger.error("❌ الملف المضغوط تالف")
                    return None
                return compressed_path
            logger.error("❌ فشل الضغط: الملف الناتج فارغ")
            return None
        except Exception as e:
            logger.error(f"❌ فشل ضغط النسخ الاحتياطي: {e}")
            return None

    # =====================================================================
    # 2) التحقق من وجود أداة
    # =====================================================================

    async def _check_tool_exists(self, tool_name: str) -> bool:
        return shutil.which(tool_name) is not None

    # =====================================================================
    # 2.b) البحث عن pg_dump / pg_restore مع دعم الإصدارات
    # =====================================================================

    async def _find_pg_tool(self, base_name: str) -> Optional[str]:
        """
        يبحث عن pg_dump / pg_restore في عدة إصدارات.
        يُرجع المسار الكامل أو None.
        """
        candidates = (
            base_name,
            f"{base_name}-17",
            f"{base_name}-16",
            f"{base_name}-15",
            f"{base_name}-14",
            f"{base_name}-13",
            f"{base_name}-12",
        )
        for candidate in candidates:
            path = shutil.which(candidate)
            if path:
                return path
        return None

    # =====================================================================
    # 3) إنشاء نسخة احتياطية
    # =====================================================================

    async def backup_database(
        self,
        backup_path: Optional[Path] = None,
        compress: bool = True,
    ) -> bool:
        try:
            if self.USE_POSTGRES:
                pg_dump_path = await self._find_pg_tool("pg_dump")
                if not pg_dump_path:
                    logger.error(
                        "❌ pg_dump غير موجود — تثبيت postgresql-client "
                        "مطلوب. في Dockerfile أضف: postgresql-client"
                    )
                    return False

                backup_file = (
                    backup_path
                    or self.PATHS.BACKUPS
                    / f"backup_{self.TimeUtils.mecca_now().strftime('%Y%m%d_%H%M%S')}.dump"
                )
                backup_file.parent.mkdir(parents=True, exist_ok=True)

                cmd = [
                    pg_dump_path,
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    "--no-privileges",
                    "--file",
                    str(backup_file),
                    self.DATABASE_URL,
                ]
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    logger.error(f"❌ pg_dump فشل: {stderr.decode()}")
                    return False

                if compress:
                    compressed = await self._compress_backup(backup_file)
                    if compressed:
                        backup_file = compressed

                logger.info(
                    f"✅ نسخة احتياطية PostgreSQL: {backup_file.name}"
                )
                return True

            elif self.USE_MYSQL:
                mysqldump_path = await self._find_pg_tool("mysqldump")
                if not mysqldump_path:
                    logger.error(
                        "❌ mysqldump غير موجود — تثبيت mysql-client "
                        "مطلوب."
                    )
                    return False

                pattern = r"mysql(?:\+asyncmy)?://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)"
                match = re.match(pattern, self.DATABASE_URL)
                if not match:
                    logger.error("❌ فشل تحليل DATABASE_URL لـ MySQL")
                    return False

                user, password, host, port, database = match.groups()
                backup_file = (
                    backup_path
                    or self.PATHS.BACKUPS
                    / f"backup_{self.TimeUtils.mecca_now().strftime('%Y%m%d_%H%M%S')}.sql"
                )
                backup_file.parent.mkdir(parents=True, exist_ok=True)

                with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                    f.write(f"[client]\nuser={user}\npassword={password}\n")
                    f.flush()
                    temp_pass_file = f.name

                try:
                    cmd = [
                        mysqldump_path,
                        f"--defaults-extra-file={temp_pass_file}",
                        f"--host={host}",
                        f"--port={port}",
                        "--single-transaction",
                        "--routines",
                        "--triggers",
                        database,
                        "--result-file",
                        str(backup_file),
                    ]
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await process.communicate()

                    if process.returncode != 0:
                        logger.error(f"❌ mysqldump فشل: {stderr.decode()}")
                        return False

                    if compress:
                        compressed = await self._compress_backup(backup_file)
                        if compressed:
                            backup_file = compressed

                    logger.info(
                        f"✅ نسخة احتياطية MySQL: {backup_file.name}"
                    )
                    return True
                finally:
                    try:
                        os.unlink(temp_pass_file)
                    except Exception:
                        pass

            else:
                # SQLite
                backup_file = (
                    backup_path
                    or self.PATHS.BACKUPS
                    / f"backup_{self.TimeUtils.mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
                )
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                if backup_file.exists():
                    backup_file.unlink()

                try:
                    async with self.connection() as conn:
                        await conn.execute(f"VACUUM INTO '{backup_file}'")
                    logger.info(
                        f"✅ نسخ احتياطي SQLite (VACUUM INTO): {backup_file.name}"
                    )
                except Exception as e:
                    logger.warning(
                        f"⚠️ VACUUM INTO فشل ({e})، سيتم النسخ المباشر"
                    )
                    async with self.connection() as conn:
                        await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    shutil.copy2(str(self.PATHS.DB), str(backup_file))

                if compress:
                    compressed = await self._compress_backup(backup_file)
                    if compressed:
                        backup_file = compressed

                return True

        except Exception as e:
            logger.error(f"❌ فشل النسخ الاحتياطي: {e}", exc_info=True)
            return False

    # =====================================================================
    # 4) استعادة نسخة احتياطية
    # =====================================================================

    async def restore_database(
        self,
        backup_path: Path,
        decompress: bool = True,
    ) -> bool:
        try:
            if not backup_path.exists():
                gz_path = backup_path.with_suffix(backup_path.suffix + ".gz")
                if gz_path.exists():
                    backup_path = gz_path
                else:
                    parent = backup_path.parent
                    base = backup_path.stem
                    possible = list(parent.glob(f"{base}*"))
                    if possible:
                        backup_path = possible[0]
                    else:
                        logger.error(
                            f"❌ ملف النسخ الاحتياطي غير موجود: {backup_path}"
                        )
                        return False

            if backup_path.suffix == ".gz" and decompress:
                decompressed_path = backup_path.with_suffix("")
                if not decompressed_path.exists():
                    with gzip.open(backup_path, "rb") as f_in:
                        with open(decompressed_path, "wb") as f_out:
                            f_out.write(f_in.read())
                backup_path = decompressed_path

            if self.USE_POSTGRES:
                pg_restore_path = await self._find_pg_tool("pg_restore")
                if not pg_restore_path:
                    logger.error(
                        "❌ pg_restore غير موجود — تثبيت postgresql-client "
                        "مطلوب."
                    )
                    return False

                cmd = [
                    pg_restore_path,
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    "--no-privileges",
                    "--dbname",
                    self.DATABASE_URL,
                    str(backup_path),
                ]
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    logger.error(f"❌ pg_restore فشل: {stderr.decode()}")
                    return False

                logger.info("✅ استعادة PostgreSQL تمت بنجاح")
                return True

            elif self.USE_MYSQL:
                mysql_path = await self._find_pg_tool("mysql")
                if not mysql_path:
                    logger.error("❌ mysql غير موجود — تثبيت mysql-client مطلوب.")
                    return False

                pattern = r"mysql(?:\+asyncmy)?://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)"
                match = re.match(pattern, self.DATABASE_URL)
                if not match:
                    return False

                user, password, host, port, database = match.groups()
                with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                    f.write(f"[client]\nuser={user}\npassword={password}\n")
                    f.flush()
                    temp_pass_file = f.name

                try:
                    cmd = [
                        mysql_path,
                        f"--defaults-extra-file={temp_pass_file}",
                        f"--host={host}",
                        f"--port={port}",
                        database,
                        "-e",
                        f"source {backup_path}",
                    ]
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await process.communicate()
                    return process.returncode == 0
                finally:
                    try:
                        os.unlink(temp_pass_file)
                    except Exception:
                        pass

            else:
                # SQLite
                await self.close()
                shutil.copy2(backup_path, self.PATHS.DB)
                await self.initialize()

                if (
                    self._secondary_index_task is None
                    or self._secondary_index_task.done()
                ):
                    self._secondary_index_task = asyncio.create_task(
                        self._create_secondary_indexes([])
                    )

                if self.CACHE_AVAILABLE and (
                    self._cache_cleanup_task is None
                    or self._cache_cleanup_task.done()
                ):
                    from database import cache_cleanup_task
                    self._cache_cleanup_task = asyncio.create_task(
                        cache_cleanup_task()
                    )

                logger.info("✅ استعادة SQLite تمت بنجاح")
                return True

        except Exception as e:
            logger.error(f"❌ فشل الاستعادة: {e}", exc_info=True)
            return False

    # =====================================================================
    # 5) VACUUM / OPTIMIZE
    # =====================================================================

    async def vacuum_database(self, analyze: bool = False) -> bool:
        try:
            if self.USE_POSTGRES:
                async with self.connection() as conn:
                    await conn.execute(
                        "VACUUM ANALYZE" if analyze else "VACUUM"
                    )

            elif self.USE_MYSQL:
                async with self.connection() as conn:
                    await conn.execute(
                        "OPTIMIZE TABLE users, user_channels, posts, "
                        "subscriptions, user_penalties, banned_words, "
                        "auto_replies"
                    )

            else:
                async with self.connection() as conn:
                    await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    if analyze:
                        await conn.execute("ANALYZE")

                def _vacuum():
                    conn = sqlite3.connect(str(self.PATHS.DB))
                    try:
                        conn.execute("VACUUM")
                    finally:
                        conn.close()

                await asyncio.to_thread(_vacuum)

            logger.info(f"✅ VACUUM{' ANALYZE' if analyze else ''} تم")
            return True

        except Exception as e:
            logger.error(f"❌ فشل VACUUM/OPTIMIZE: {e}")
            return False

    # =====================================================================
    # 6) نسخ الردود التلقائية إلى JSON
    # =====================================================================

    async def backup_auto_replies(self) -> int:
        replies = await self.fetchall("SELECT * FROM auto_replies")
        if not replies:
            return 0

        timestamp = self.TimeUtils.utc_now().strftime("%Y%m%d_%H%M%S")
        backup_file = (
            self.PATHS.BACKUPS / f"auto_replies_backup_{timestamp}.json"
        )
        backup_file.parent.mkdir(parents=True, exist_ok=True)

        def _write_json():
            with open(backup_file, "w", encoding="utf-8") as f:
                json.dump(replies, f, ensure_ascii=False, indent=2)

        await asyncio.to_thread(_write_json)
        return len(replies)