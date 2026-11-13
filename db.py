"""SQLite: foydalanuvchilar, e'lonlar, vazifalar, statistika."""
import os, sqlite3
import config
D = sqlite3.connect(os.path.join(config.DATA, "postbot.db"), check_same_thread=False); D.row_factory = sqlite3.Row
D.executescript("""
create table if not exists users(uid integer primary key, session text default '', tg_id int);
create table if not exists ads(id integer primary key, user_id int, msg_id int, title text);
create table if not exists jobs(id integer primary key, user_id int, ad_id int, chats text, interval int, active int default 1, next_run real default 0);
create table if not exists sent(id integer primary key, user_id int, ad_id int, chat_id int, chat_title text, msg_id int, ts real);
create table if not exists replies(id integer primary key, user_id int, chat_id int, msg_id int, sender int, ts real);
""")
def q(sql, a=()):
    c = D.execute(sql, a); D.commit(); return [dict(r) for r in c.fetchall()]
