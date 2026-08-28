import aiosqlite
import time
import base64
import os
from datetime import datetime
from typing import Optional,List,Dict,Any
from cryptography.fernet import Fernet
from pathlib import Path

DATABASE_NAME="bale_bot.db"
KEY_FILE=Path(__file__).parent/"encryption_key.key"

if KEY_FILE.exists():
    with open(KEY_FILE,'rb') as f:
        ENCRYPTION_KEY=f.read()
else:
    ENCRYPTION_KEY=Fernet.generate_key()
    with open(KEY_FILE,'wb') as f:
        f.write(ENCRYPTION_KEY)
cipher=Fernet(ENCRYPTION_KEY)

class Database:
    def __init__(self,db_name:str=DATABASE_NAME):
        self.db_name=db_name
        self.conn=None

    async def connect(self):
        self.conn=await aiosqlite.connect(self.db_name)
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA busy_timeout=10000")
        await self.conn.execute("PRAGMA synchronous=NORMAL")
        await self.create_tables()

    async def create_tables(self):
        await self.conn.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id TEXT PRIMARY KEY,
            username TEXT,
            first_seen INTEGER,
            last_seen INTEGER,
            is_profile_complete INTEGER DEFAULT 0,
            is_blocked INTEGER DEFAULT 0,
            created_at INTEGER)""")
        await self.conn.execute("""CREATE TABLE IF NOT EXISTS profiles(
            profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE,
            first_name TEXT,
            last_name TEXT,
            phone_number_encrypted TEXT,
            education_level TEXT,
            field_of_study TEXT,
            registration_step TEXT DEFAULT 'start',
            created_at INTEGER,
            updated_at INTEGER)""")
        await self.conn.execute("""CREATE TABLE IF NOT EXISTS user_messages(
            message_id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_uid TEXT UNIQUE,
            user_id TEXT,
            chat_id TEXT,
            text TEXT,
            message_type TEXT DEFAULT 'text',
            timestamp INTEGER)""")
        await self.conn.execute("""CREATE TABLE IF NOT EXISTS conversations(
            conv_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            chat_id TEXT,
            bot_message TEXT,
            user_message TEXT,
            message_direction TEXT,
            timestamp INTEGER)""")
        await self.conn.execute("""CREATE TABLE IF NOT EXISTS error_logs(
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_type TEXT,
            error_message TEXT,
            user_id TEXT,
            timestamp INTEGER)""")
        await self.conn.commit()

    def encrypt_phone(self,phone:str)->str:
        if not phone:
            return ""
        return base64.b64encode(cipher.encrypt(phone.encode())).decode()

    async def decrypt_phone(self,encrypted_phone:str)->str:
        if not encrypted_phone:
            return ""
        try:
            return cipher.decrypt(base64.b64decode(str(encrypted_phone))).decode()
        except:
            return ""

    async def register_user(self,user_id:str,username:Optional[str]=None)->bool:
        current_time=int(time.time())
        cur=await self.conn.execute("SELECT 1 FROM users WHERE user_id=?",(user_id,))
        if await cur.fetchone():
            await self.conn.execute("UPDATE users SET last_seen=?,username=COALESCE(?,username) WHERE user_id=?",(current_time,username,user_id))
            await self.conn.commit()
            return False
        await self.conn.execute("INSERT INTO users(user_id,username,first_seen,last_seen,is_profile_complete,created_at) VALUES(?,?,?,?,0,?)",(user_id,username,current_time,current_time,current_time))
        await self.conn.execute("INSERT INTO profiles(user_id,registration_step,created_at,updated_at) VALUES(?,'start',?,?)",(user_id,current_time,current_time))
        await self.conn.commit()
        return True

    async def update_last_seen(self,user_id:str):
        await self.conn.execute("UPDATE users SET last_seen=? WHERE user_id=?",(int(time.time()),user_id))
        await self.conn.commit()

    async def get_user_info(self,user_id:str)->Optional[Dict[str,Any]]:
        cur=await self.conn.execute("SELECT u.*,p.* FROM users u LEFT JOIN profiles p ON u.user_id=p.user_id WHERE u.user_id=?",(user_id,))
        row=await cur.fetchone()
        if not row:
            return None
        cols=[d[0] for d in cur.description]
        return dict(zip(cols,row))

    async def update_profile(self,user_id:str,field:str,value:str)->bool:
        if field=="phone_number":
            value=self.encrypt_phone(value)
            db_field="phone_number_encrypted"
        else:
            db_field=field
        current_time=int(time.time())
        await self.conn.execute(f"UPDATE profiles SET {db_field}=?,updated_at=? WHERE user_id=?",(value,current_time,user_id))
        step_map={"first_name":"last_name","last_name":"phone_number","phone_number":"education_level","education_level":"field_of_study","field_of_study":"complete"}
        next_step=step_map.get(field,"complete")
        await self.conn.execute("UPDATE profiles SET registration_step=? WHERE user_id=?",(next_step,user_id))
        if next_step=="complete":
            await self.conn.execute("UPDATE users SET is_profile_complete=1 WHERE user_id=?",(user_id,))
        await self.conn.commit()
        return True

    async def get_registration_step(self,user_id:str)->str:
        cur=await self.conn.execute("SELECT registration_step FROM profiles WHERE user_id=?",(user_id,))
        row=await cur.fetchone()
        return row[0] if row else "start"

    async def is_profile_complete(self,user_id:str)->bool:
        cur=await self.conn.execute("SELECT is_profile_complete FROM users WHERE user_id=?",(user_id,))
        row=await cur.fetchone()
        return bool(row[0]) if row else False

    async def reset_registration(self,user_id:str):
        await self.conn.execute("UPDATE profiles SET registration_step='first_name' WHERE user_id=?",(user_id,))
        await self.conn.execute("UPDATE users SET is_profile_complete=0 WHERE user_id=?",(user_id,))
        await self.conn.commit()

    async def complete_profile(self,user_id:str):
        await self.conn.execute("UPDATE profiles SET registration_step='complete' WHERE user_id=?",(user_id,))
        await self.conn.execute("UPDATE users SET is_profile_complete=1 WHERE user_id=?",(user_id,))
        await self.conn.commit()

    async def save_user_message(self,message_uid:str,user_id:str,chat_id:str,text:str):
        await self.conn.execute("INSERT OR IGNORE INTO user_messages(message_uid,user_id,chat_id,text,timestamp) VALUES(?,?,?,?,?)",(message_uid,user_id,chat_id,text,int(time.time())))
        await self.conn.commit()

    async def save_conversation(self,user_id:str,chat_id:str,bot_message:str,user_message:str=None):
        await self.conn.execute("INSERT INTO conversations(user_id,chat_id,bot_message,user_message,message_direction,timestamp) VALUES(?,?,?,?,'outgoing',?)",(user_id,chat_id,bot_message,user_message,int(time.time())))
        await self.conn.commit()

    async def log_error(self,error_type:str,error_message:str,user_id:Optional[str]=None):
        await self.conn.execute("INSERT INTO error_logs(error_type,error_message,user_id,timestamp) VALUES(?,?,?,?)",(error_type,error_message,user_id,int(time.time())))
        await self.conn.commit()

    async def backup(self):
        import shutil
        backup_dir=Path("bale_backups")
        backup_dir.mkdir(exist_ok=True)
        timestamp=datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(self.db_name,backup_dir/f"backup_{timestamp}.db")

    async def close(self):
        if self.conn:
            await self.conn.close()