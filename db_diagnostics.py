#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_diagnostics.py — تشخيص قاعدة البيانات عبر البوت
================================================================================
الاستخدام:
    from db_diagnostics import diagnose_db
    # في أي handler:
    result = await diagnose_db()
    await send_message(result)
================================================================================
"""

async def diagnose_db() -> str:
    """يُعيد تقريراً عن حالة قاعدة البيانات."""
    from database import DB
    
    report = []
    report.append("🔬 <b>تشخيص قاعدة البيانات</b>")
    report.append("━━━━━━━━━━━━━━━━━━━━━━")
    
    # ═══════════════════════════════════════════════════════════════
    # 1. Dead Tuples
    # ═══════════════════════════════════════════════════════════════
    report.append("\n📊 <b>1. Dead Tuples (سبب البطء):</b>\n")
    try:
        rows = await DB.fetchall("""
            SELECT 
                relname AS table_name,
                n_live_tup AS live_rows,
                n_dead_tup AS dead_rows,
                ROUND(100.0 * n_dead_tup / 
                    NULLIF(n_live_tup + n_dead_tup, 0), 1) AS dead_pct
            FROM pg_stat_user_tables
            WHERE n_dead_tup > 100
            ORDER BY n_dead_tup DESC
            LIMIT 10
        """)
        if not rows:
            report.append("✅ لا يوجد dead tuples — ممتاز!")
        else:
            for r in rows:
                pct = r.get('dead_pct') or 0
                emoji = "🔴" if pct > 30 else ("🟡" if pct > 15 else "🟢")
                report.append(
                    f"{emoji} <code>{r['table_name']:<18}</code> "
                    f"live={r['live_rows']:>6} "
                    f"dead={r['dead_rows']:>6} "
                    f"({pct}%)"
                )
    except Exception as e:
        report.append(f"❌ خطأ: {e}")
    
    # ═══════════════════════════════════════════════════════════════
    # 2. أحجام الجداول
    # ═══════════════════════════════════════════════════════════════
    report.append("\n📦 <b>2. أحجام الجداول:</b>\n")
    try:
        rows = await DB.fetchall("""
            SELECT 
                relname AS table_name,
                pg_size_pretty(pg_total_relation_size(relid)) AS total_size
            FROM pg_catalog.pg_statio_user_tables 
            ORDER BY pg_total_relation_size(relid) DESC
            LIMIT 10
        """)
        for r in rows:
            report.append(
                f"  <code>{r['table_name']:<20}</code> {r['total_size']}"
            )
    except Exception as e:
        report.append(f"❌ خطأ: {e}")
    
    # ═══════════════════════════════════════════════════════════════
    # 3. الفهارس على الجداول الحرجة
    # ═══════════════════════════════════════════════════════════════
    report.append("\n🗂️ <b>3. فهارس الجداول الحرجة:</b>\n")
    try:
        rows = await DB.fetchall("""
            SELECT 
                tablename,
                indexname
            FROM pg_indexes
            WHERE tablename IN ('posts', 'banned_words', 'bot_groups')
            ORDER BY tablename, indexname
        """)
        from collections import defaultdict
        by_table = defaultdict(list)
        for r in rows:
            by_table[r['tablename']].append(r['indexname'])
        
        for table in ('posts', 'banned_words', 'bot_groups'):
            indexes = by_table.get(table, [])
            report.append(f"\n<b>{table}</b> ({len(indexes)} فهرس):")
            for idx in indexes[:8]:
                report.append(f"  • <code>{idx}</code>")
            if len(indexes) > 8:
                report.append(f"  ... و{len(indexes) - 8} أكثر")
    except Exception as e:
        report.append(f"❌ خطأ: {e}")
    
    # ═══════════════════════════════════════════════════════════════
    # 4. Autovacuum settings
    # ═══════════════════════════════════════════════════════════════
    report.append("\n⚙️ <b>4. إعدادات Autovacuum:</b>\n")
    try:
        rows = await DB.fetchall("""
            SELECT name, setting 
            FROM pg_settings 
            WHERE name IN (
                'autovacuum',
                'autovacuum_vacuum_scale_factor',
                'autovacuum_analyze_scale_factor',
                'autovacuum_naptime'
            )
        """)
        for r in rows:
            report.append(f"  <code>{r['name']}</code> = {r['setting']}")
    except Exception as e:
        report.append(f"❌ خطأ: {e}")
    
    report.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    report.append("✅ <b>اكتمل التشخيص</b>")
    
    return "\n".join(report)


async def vacuum_analyze_tables() -> str:
    """يُنظّف الجداول الحرجة — آمن، لا يقفل."""
    from database import DB
    
    tables = ['posts', 'banned_words', 'user_penalties', 
              'subscriptions', 'user_channels', 'bot_groups']
    results = ["🧹 <b>VACUUM ANALYZE</b>\n━━━━━━━━━━━━━━━━━━━━━━\n"]
    
    for table in tables:
        try:
            # نستخدم connection مباشر لأن VACUUM لا يعمل في transaction
            async with DB.connection() as conn:
                await conn.execute(f"VACUUM ANALYZE {table}")
            results.append(f"✅ <code>{table}</code>")
        except Exception as e:
            results.append(f"❌ <code>{table}</code>: {e}")
    
    results.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    results.append("✅ <b>تم التنظيف</b> — راقب الأداء")
    
    return "\n".join(results)