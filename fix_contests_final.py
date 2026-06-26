import re

with open('reelax_bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# ============================================================
# 1. دوال قاعدة البيانات - يجب أن تكون أولاً
# ============================================================

# إصلاح دالة db_create_contest
old_db_create = r'async def db_create_contest\(.*?\):.*?(?=\n\nasync def db_get_contest|\Z)'
new_db_create = '''async def db_create_contest(creator_id: int, title: str, description: str, prize: str, end_date: datetime) -> int:
    """إنشاء مسابقة جديدة في قاعدة البيانات."""
    try:
        async def _create(conn):
            if not isinstance(end_date, datetime):
                raise ValueError("end_date must be datetime object")
            end_date_str = end_date.isoformat()
            created_at_str = utc_now_iso()
            cur = await conn.execute(
                """INSERT INTO contests (creator_id, title, description, prize, end_date, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'active', ?) RETURNING id""",
                (creator_id, title, description, prize, end_date_str, created_at_str)
            )
            row = await cur.fetchone()
            await conn.commit()
            return row[0] if row else None
        contest_id = await execute_db(_create)
        if contest_id:
            logger.info(f"✅ تم إنشاء مسابقة جديدة (ID: {contest_id}) بواسطة المستخدم {creator_id}")
        else:
            logger.warning(f"⚠️ فشل إنشاء المسابقة، لم يتم إرجاع ID للمستخدم {creator_id}")
        return contest_id
    except Exception as e:
        logger.error(f"❌ خطأ في db_create_contest: {e}")
        raise'''

# إصلاح دالة db_get_active_contests_with_participants
old_db_get = r'async def db_get_active_contests_with_participants\(.*?\):.*?(?=\n\nasync def db_create_contest|\Z)'
new_db_get = '''async def db_get_active_contests_with_participants(limit: int = 10) -> list:
    """جلب المسابقات النشطة مع عدد المشاركين (نسخة آمنة)."""
    try:
        async def _get(conn):
            now = utc_now().isoformat()
            try:
                cur = await conn.execute(
                    """SELECT c.id, c.title, c.description, c.prize, c.end_date,
                              COALESCE((SELECT COUNT(*) FROM contest_participants cp WHERE cp.contest_id = c.id), 0) as participants
                       FROM contests c
                       WHERE c.status = 'active' AND c.end_date > ?
                       ORDER BY c.end_date ASC LIMIT ?""",
                    (now, limit)
                )
                rows = await cur.fetchall()
                result = []
                for row in rows:
                    try:
                        if hasattr(row, 'keys'):
                            result.append((
                                row['id'],
                                row['title'],
                                row['description'],
                                row['prize'],
                                row['end_date'],
                                row['participants']
                            ))
                        else:
                            result.append((row[0], row[1], row[2], row[3], row[4], row[5] if len(row) > 5 else 0))
                    except:
                        continue
                return result
            except Exception as e:
                logger.error(f"خطأ في تنفيذ الاستعلام: {e}")
                return []
        return await execute_db(_get)
    except Exception as e:
        logger.error(f"خطأ في db_get_active_contests_with_participants: {e}")
        return []'''

# ============================================================
# 2. دوال المعالجات - يجب أن تكون ثانياً
# ============================================================

# دالة معالج المسابقات الرئيسي (مصحح)
old_contests_handler = r'async def contests_command_handler\(.*?\):.*?(?=\n\nasync def contest_join_callback|\Z)'
new_contests_handler = '''async def contests_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة المسابقات النشطة (نسخة آمنة بالكامل)."""
    try:
        if not update or not update.effective_user:
            logger.error("update أو effective_user غير موجود")
            return
        
        user_id = update.effective_user.id
        
        # جلب المسابقات النشطة
        contests = []
        try:
            contests = await db_get_active_contests_with_participants(limit=10)
        except Exception as e:
            logger.error(f"خطأ في جلب المسابقات: {e}")
            contests = []
        
        # إذا لم توجد مسابقات
        if not contests:
            text = get_text(user_id, 'no_contests')
            if update.callback_query:
                try:
                    await safe_edit_markdown(update.callback_query, text)
                except:
                    await update.callback_query.edit_message_text(text)
            else:
                await safe_send_markdown(context.bot, user_id, text)
            return
        
        # بناء الرسالة
        text = get_text(user_id, 'contests_active').format("")
        keyboard = []
        
        for contest in contests:
            try:
                if len(contest) < 6:
                    continue
                cid, title, desc, prize, end_date, participants = contest
                
                # حساب الوقت المتبقي
                try:
                    end_dt = datetime.fromisoformat(end_date)
                    days_left = (end_dt - utc_now()).days
                    if days_left > 0:
                        time_left = get_text(user_id, 'contest_time_left').format(days_left)
                    else:
                        time_left = get_text(user_id, 'contest_expired_label')
                except:
                    time_left = "📅 تاريخ غير صحيح"
                    days_left = 0
                
                # التحقق من مشاركة المستخدم
                try:
                    participated = await db_get_user_participation(user_id, cid)
                except Exception as e:
                    logger.error(f"خطأ في db_get_user_participation للمستخدم {user_id} والمسابقة {cid}: {e}")
                    participated = None
                
                status_icon = "✅" if participated else "📝"
                
                # إضافة المسابقة إلى النص
                text += f"📌 **{title or 'بدون عنوان'}**\n"
                text += f"📝 {(desc or '')[:100]}{'...' if len(desc or '') > 100 else ''}\n"
                text += f"🎁 الجائزة: {prize or 'غير محددة'}\n"
                text += f"👥 المشاركون: {participants or 0}\n"
                text += f"🕐 {time_left}\n"
                text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
                
                # زر المشاركة إذا كانت المسابقة نشطة ولم يشارك المستخدم
                if not participated and days_left > 0:
                    keyboard.append([InlineKeyboardButton(
                        f"{status_icon} شارك في {title[:20]}",
                        callback_data=f"{CallbackData.CONTEST_JOIN_PREFIX}{cid}"
                    )])
            except Exception as e:
                logger.error(f"خطأ في معالجة مسابقة: {e}")
                continue
        
        # أزرار إضافية
        keyboard.append([InlineKeyboardButton("🏆 الفائزون السابقون", callback_data=CallbackData.CONTEST_WINNERS)])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
        
        # إرسال الرسالة
        if update.callback_query:
            try:
                await safe_edit_markdown(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard))
            except:
                await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=InlineKeyboardMarkup(keyboard))
            
    except Exception as e:
        error_id = log_error(e, {
            'user_id': update.effective_user.id if update and update.effective_user else None,
            'chat_id': update.effective_chat.id if update and update.effective_chat else None,
        })
        msg = f"❌ حدث خطأ أثناء تحميل المسابقات (الرمز: `{error_id}`).\nيرجى المحاولة مرة أخرى لاحقاً."
        try:
            if update.callback_query:
                await safe_edit_markdown(update.callback_query, msg)
            else:
                await safe_send_markdown(context.bot, user_id, msg)
        except:
            try:
                if update.callback_query:
                    await update.callback_query.edit_message_text("❌ حدث خطأ أثناء تحميل المسابقات.")
                else:
                    await context.bot.send_message(chat_id=user_id, text="❌ حدث خطأ أثناء تحميل المسابقات.")
            except:
                pass'''

# دالة المشاركة في مسابقة (مصححة)
old_join = r'async def contest_join_callback\(.*?\):.*?(?=\n\nasync def contest_winners_callback|\Z)'
new_join = '''async def contest_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج زر المشاركة في مسابقة (نسخة آمنة)."""
    query = update.callback_query
    if not query:
        return
    
    try:
        await query.answer()
    except:
        pass
    
    user_id = update.effective_user.id
    
    try:
        contest_id = int(query.data.split(":")[-1])
    except (ValueError, IndexError):
        try:
            await query.edit_message_text("❌ بيانات غير صالحة.")
        except:
            pass
        return
    
    try:
        # التحقق من وجود المسابقة
        contest = await db_get_contest(contest_id)
        if not contest:
            try:
                await query.edit_message_text("❌ المسابقة غير موجودة.")
            except:
                pass
            return
        
        # التحقق من أن المسابقة نشطة
        if contest['status'] != 'active':
            try:
                await query.edit_message_text("❌ هذه المسابقة غير متاحة حالياً.")
            except:
                pass
            return
        
        # التحقق من انتهاء المسابقة
        try:
            end_date = datetime.fromisoformat(contest['end_date'])
            if end_date < utc_now():
                try:
                    await query.edit_message_text("❌ هذه المسابقة قد انتهت.")
                except:
                    pass
                return
        except:
            pass
        
        # التحقق من مشاركة المستخدم مسبقاً
        participation = await db_get_user_participation(user_id, contest_id)
        if participation:
            try:
                await query.edit_message_text(get_text(user_id, 'contest_participated'))
            except:
                pass
            return
        
        # طلب الإجابة
        context.user_data['contest_join_id'] = contest_id
        context.user_data['state'] = UserState.WAITING_CONTEST_ANSWER
        
        msg = (
            f"📝 **المشاركة في المسابقة: {contest['title']}**\n\n"
            f"📌 أرسل إجابتك (نص) أو اضغط /skip للمشاركة بدون إجابة.\n"
            f"⏳ يمكنك تعديل إجابتك قبل انتهاء المسابقة."
        )
        try:
            await query.edit_message_text(msg, parse_mode="MarkdownV2")
        except:
            await query.edit_message_text(msg)
            
    except Exception as e:
        error_id = log_error(e, {'user_id': user_id, 'contest_id': contest_id})
        try:
            await query.edit_message_text(f"❌ حدث خطأ أثناء المشاركة (الرمز: `{error_id}`).")
        except:
            pass'''

# دوال الأدمن المصححة (نسخة مستقرة)
new_admin_create = '''async def admin_create_contest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج زر إنشاء مسابقة من لوحة الأدمن (نسخة مستقرة)."""
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except:
            pass
    
    user_id = update.effective_user.id
    
    # التحقق من الصلاحيات
    if user_id != MAIN_ADMIN_ID and not await is_bot_admin(user_id):
        if query:
            try:
                await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
            except:
                pass
        return
    
    # تعيين الحالة
    context.user_data['state'] = UserState.WAITING_CONTEST_TITLE
    msg = "📝 **إنشاء مسابقة جديدة**\\n\\nأرسل **عنوان** المسابقة:"
    
    if query:
        try:
            await query.edit_message_text(msg, parse_mode="MarkdownV2")
        except:
            try:
                await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
            except:
                pass
    else:
        try:
            await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
        except:
            pass'''

new_admin_declare = '''async def admin_declare_winner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج زر إعلان فائز من لوحة الأدمن (نسخة مستقرة)."""
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except:
            pass
    
    user_id = update.effective_user.id
    
    # التحقق من الصلاحيات
    if user_id != MAIN_ADMIN_ID and not await is_bot_admin(user_id):
        if query:
            try:
                await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
            except:
                pass
        return
    
    msg = "📝 **إعلان فائز في مسابقة**\\n\\nاستخدم الأمر:\\n`/declare_winner معرف_المسابقة معرف_المستخدم`\\n\\nمثال: `/declare_winner 5 123456789`\\n\\n📌 لعرض المسابقات النشطة استخدم `/contests`"
    
    if query:
        try:
            await query.edit_message_text(msg, parse_mode="MarkdownV2")
        except:
            try:
                await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
            except:
                pass
    else:
        try:
            await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
        except:
            pass'''

# ============================================================
# 3. تطبيق التصحيحات على الملف
# ============================================================

# استبدال الدوال
content = re.sub(old_db_create, new_db_create, content, flags=re.DOTALL)
content = re.sub(old_db_get, new_db_get, content, flags=re.DOTALL)
content = re.sub(old_contests_handler, new_contests_handler, content, flags=re.DOTALL)
content = re.sub(old_join, new_join, content, flags=re.DOTALL)

# حذف الدوال القديمة وإضافة الجديدة
# البحث عن الدوال القديمة وحذفها
pattern = r'async def admin_create_contest_callback\([^)]*\).*?(?=\n\nasync def admin_declare_winner_callback|\Z)'
content = re.sub(pattern, '', content, flags=re.DOTALL)

pattern = r'async def admin_declare_winner_callback\([^)]*\).*?(?=\n\nasync def |\Z)'
content = re.sub(pattern, '', content, flags=re.DOTALL)

# إضافة الدوال الجديدة قبل if __name__
content = content.replace(
    'if __name__ == "__main__":',
    new_admin_create + '\n\n' + new_admin_declare + '\n\nif __name__ == "__main__":'
)

# حفظ الملف
with open('reelax_bot.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ تم إصلاح وترتيب جميع دوال نظام المسابقات!")
print("""
📋 التغييرات التي تمت:
1. إصلاح دالة db_create_contest - معالجة أفضل للأخطاء
2. إصلاح دالة db_get_active_contests_with_participants - استخدام SUBQUERY بدلاً من LEFT JOIN
3. إصلاح دالة contests_command_handler - معالجة أفضل للأخطاء
4. إصلاح دالة contest_join_callback - تحقق أفضل من حالة المسابقة
5. إصلاح دوال admin_create_contest_callback و admin_declare_winner_callback
6. ترتيب الدوال بشكل منطقي (قاعدة بيانات ← معالجات ← أدمن)
""")
