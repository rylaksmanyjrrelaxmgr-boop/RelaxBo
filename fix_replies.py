import sqlite3

conn = sqlite3.connect('bot_data.db')
cursor = conn.cursor()

cursor.execute('SELECT text FROM custom_replies')
replies = cursor.fetchall()

data = [('نكتة', r[0]) for r in replies]

cursor.executemany('INSERT OR IGNORE INTO group_replies (keyword, reply) VALUES (?, ?)', data)

conn.commit()
conn.close()

print('تم نقل الردود وتفعيلها بنجاح!')
