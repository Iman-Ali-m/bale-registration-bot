import asyncio
import aiohttp
import time
import os
import json
import re
from datetime import datetime
from typing import Optional,List,Dict,Any,Tuple
from bale_database import Database
from TOKEN_BOT import BOT_TOKEN
from bale_courses import COURSES

BASE_URL=f"https://tapi.bale.ai/bot{BOT_TOKEN}"
POLLING_INTERVAL=3
AUTO_BACKUP_INTERVAL=86400
DATABASE_NAME="bale_bot.db"

class Message:
    def __init__(self,data:Dict[str,Any]):
        self.message_id=str(data.get("message_id",""))
        self.text=data.get("text","")
        self.chat_id=str(data.get("chat",{}).get("id",""))
        self.sender_id=str(data.get("from",{}).get("id",""))
        self.sender_name=data.get("from",{}).get("first_name","کاربر")
        self.date=data.get("date",0)

class CallbackQuery:
    def __init__(self,data:Dict[str,Any]):
        self.id=data.get("id","")
        self.data=data.get("data","")
        self.chat_id=str(data.get("message",{}).get("chat",{}).get("id",""))
        self.message_id=str(data.get("message",{}).get("message_id",""))
        self.sender_id=str(data.get("from",{}).get("id",""))

class BaleBot:
    def __init__(self):
        self.db=Database(DATABASE_NAME)
        self.session=None
        self.is_running=False
        self.start_time=int(time.time())
        self.session_stats={"new_users":0,"returning_users":0,"messages_processed":0,"profiles_completed":0,"errors":0,"blocked":0}
        self.user_activity={}
        self.blocked_users={}
        self.INACTIVE_TIMEOUT=600
        self.MAX_PER_MINUTE=20
        self.BLOCK_TIME=3600
        self.menu_buttons=[
            [{"text":"📝 ثبت نام"},{"text":"📚 دوره‌ها"}],
            [{"text":"👤 پروفایل"},{"text":"♻ راه اندازی مجدد"}],
            [{"text":"📝 راهنما"},{"text":"ℹ️ ارتباط با ما"}]
        ]
        self.courses_buttons=[
            [{"text":"پایتون","callback_data":"python"},{"text":"ربات روبیکا","callback_data":"rubika"}],
            [{"text":"فرانت","callback_data":"front"},{"text":"کنفرانس","callback_data":"conference"}],
            [{"text":"🔙 بازگشت","callback_data":"back_to_main"}]
        ]
        print("BaleBot ready")

    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            self.session=aiohttp.ClientSession()

    def is_blocked(self,user_id):
        if user_id in self.blocked_users:
            if time.time()-self.blocked_users[user_id]<self.BLOCK_TIME:
                return True
            del self.blocked_users[user_id]
        return False

    def check_rate(self,user_id):
        if self.is_blocked(user_id):
            return False
        now=time.time()
        if user_id not in self.user_activity:
            self.user_activity[user_id]=[]
        self.user_activity[user_id]=[t for t in self.user_activity[user_id] if now-t<60]
        if len(self.user_activity[user_id])>=self.MAX_PER_MINUTE:
            self.blocked_users[user_id]=now
            return False
        self.user_activity[user_id].append(now)
        return True

    async def _api_request(self,method:str,data:Dict)->Optional[Dict]:
        await self._ensure_session()
        url=f"{BASE_URL}/{method}"
        try:
            async with self.session.post(url,json=data,timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status==200:
                    return await resp.json()
                return None
        except:
            return None

    async def send_message(self,chat_id:str,text:str,reply_markup:Optional[Dict]=None)->Optional[str]:
        if not chat_id or not text:
            return None
        data={"chat_id":chat_id,"text":text}
        if reply_markup:
            data["reply_markup"]=reply_markup
        result=await self._api_request("sendMessage",data)
        if result and result.get("ok"):
            return str(result.get("result",{}).get("message_id",""))
        return None

    async def send_photo(self,chat_id:str,photo_path:str,caption:str="")->Optional[str]:
        await self._ensure_session()
        if not os.path.exists(photo_path):
            return None
        data={"chat_id":chat_id}
        if caption:
            data["caption"]=caption
        try:
            with open(photo_path,'rb') as f:
                form=aiohttp.FormData()
                form.add_field('chat_id',chat_id)
                if caption:
                    form.add_field('caption',caption)
                form.add_field('photo',f,filename=os.path.basename(photo_path))
                url=f"{BASE_URL}/sendPhoto"
                async with self.session.post(url,data=form) as resp:
                    result=await resp.json()
                    if result.get("ok"):
                        return str(result.get("result",{}).get("message_id",""))
        except:
            pass
        return None

    async def send_media_group(self,chat_id:str,photo_paths:List[str],caption:str="")->Optional[str]:
        await self._ensure_session()
        valid_paths=[p for p in photo_paths if os.path.exists(p)]
        if not valid_paths:
            return None
        if len(valid_paths)==1:
            return await self.send_photo(chat_id,valid_paths[0],caption)
        media=[]
        form=aiohttp.FormData()
        form.add_field('chat_id',chat_id)
        for i,path in enumerate(valid_paths):
            media.append({"type":"photo","media":f"attach://photo{i}","caption":caption if i==0 else ""})
            form.add_field(f'photo{i}',open(path,'rb'),filename=os.path.basename(path))
        form.add_field('media',json.dumps(media))
        try:
            url=f"{BASE_URL}/sendMediaGroup"
            async with self.session.post(url,data=form) as resp:
                result=await resp.json()
                if result.get("ok"):
                    return str(result.get("result",{}).get("message_id",""))
        except:
            pass
        return None

    async def answer_callback(self,callback_id:str,text:str=""):
        data={"callback_query_id":callback_id}
        if text:
            data["text"]=text
        await self._api_request("answerCallbackQuery",data)

    async def edit_message(self,chat_id:str,message_id:str,text:str,reply_markup:Optional[Dict]=None):
        data={"chat_id":chat_id,"message_id":message_id,"text":text}
        if reply_markup:
            data["reply_markup"]=reply_markup
        await self._api_request("editMessageText",data)

    def main_keyboard(self):
        return {"keyboard":self.menu_buttons,"resize_keyboard":True,"one_time_keyboard":False}

    def courses_keyboard(self):
        return {"inline_keyboard":self.courses_buttons}

    async def get_updates(self,offset:Optional[int]=None)->List[Dict]:
        await self._ensure_session()
        params={"timeout":30}
        if offset:
            params["offset"]=offset
        try:
            url=f"{BASE_URL}/getUpdates"
            async with self.session.get(url,params=params,timeout=aiohttp.ClientTimeout(total=35)) as resp:
                if resp.status==200:
                    data=await resp.json()
                    if data.get("ok"):
                        return data.get("result",[])
        except asyncio.CancelledError:
            raise
        except:
            pass
        return []

    async def handle_user(self,message:Message):
        user_id=message.sender_id
        is_new=await self.db.register_user(user_id,message.sender_name)
        if is_new:
            self.session_stats["new_users"]+=1
        else:
            self.session_stats["returning_users"]+=1
        return is_new

    async def send_welcome(self,chat_id:str,message:Message):
        await self.handle_user(message)
        info=await self.db.get_user_info(message.sender_id)
        if info and info.get("is_profile_complete",0)==1:
            summary=await self.get_profile_summary(message.sender_id)
            text="👋 سلام خوش آمدید\n\n"+summary
        else:
            text=f"""🌟 سلام {message.sender_name} خوش آمدید
🎉 من یک ربات هوشمند هستم
📅 تاریخ عضویت: {datetime.now().strftime('%Y/%m/%d')}
💡 برای ثبت‌نام گزینه ثبت نام را بزنید"""
        await self.send_message(chat_id,text,self.main_keyboard())

    async def get_profile_summary(self,user_id:str):
        info=await self.db.get_user_info(user_id)
        if not info:
            return "❌ کاربر یافت نشد"
        return f"""👤 پروفایل شما
📛 نام: {info.get('first_name','نامشخص')}
📛 نام خانوادگی: {info.get('last_name','نامشخص')}
📞 شماره: {await self.db.decrypt_phone(info.get('phone_number_encrypted','')) or 'وارد نشده'}
🎓 مقطع: {info.get('education_level','نامشخص')}
📚 رشته: {info.get('field_of_study','نامشخص')}"""

    async def process_message(self,message:Message):
        user_id=message.sender_id
        if not self.check_rate(user_id):
            self.session_stats["blocked"]+=1
            return
        self.session_stats["messages_processed"]+=1
        await self.db.update_last_seen(user_id)
        text=message.text.strip()
        if text=="/start":
            await self.send_welcome(message.chat_id,message)
            return
        if text in["📝 ثبت نام","📚 دوره‌ها","👤 پروفایل","♻ راه اندازی مجدد","📝 راهنما","ℹ️ ارتباط با ما"]:
            await self.handle_menu(message.chat_id,text,message)
            return
        current_step=await self.db.get_registration_step(user_id)
        is_complete=await self.db.is_profile_complete(user_id)
        if not is_complete and current_step!="start":
            _,response=await self.process_registration(user_id,text)
            await self.send_message(message.chat_id,response)
            return
        await self.send_message(message.chat_id,"از منو استفاده کنید")

    async def handle_menu(self,chat_id:str,text:str,message:Message):
        user_id=message.sender_id
        if text=="📝 ثبت نام":
            await self.db.reset_registration(user_id)
            await self.send_message(chat_id,"📝 ثبت‌نام شروع شد\n📛 نام خود را وارد کنید:")
        elif text=="📚 دوره‌ها":
            await self.send_message(chat_id,"📚 دوره‌های آموزشی",self.courses_keyboard())
        elif text=="👤 پروفایل":
            await self.send_message(chat_id,await self.get_profile_summary(user_id))
        elif text=="♻ راه اندازی مجدد":
            await self.send_message(chat_id,"منوی اصلی",self.main_keyboard())
        elif text=="📝 راهنما":
            await self.send_message(chat_id,"راهنما:\nثبت نام کنید و دوره‌ها را ببینید")
        elif text=="ℹ️ ارتباط با ما":
            await self.send_message(chat_id,"@Pyton_lerning")

    async def process_registration(self,user_id:str,text:str):
        step=await self.db.get_registration_step(user_id)
        if step=="first_name":
            if len(text)<2:
                return False,"نام باید حداقل ۲ حرف باشد"
            await self.db.update_profile(user_id,"first_name",text)
            return True,"✅ نام ثبت شد\n📛 نام خانوادگی:"
        elif step=="last_name":
            if len(text)<2:
                return False,"نام خانوادگی باید حداقل ۲ حرف باشد"
            await self.db.update_profile(user_id,"last_name",text)
            return True,"✅ نام خانوادگی ثبت شد\n📞 شماره تماس:"
        elif step=="phone_number":
            clean=re.sub(r'\D','',text)
            if len(clean)<10:
                return False,"شماره نامعتبر"
            await self.db.update_profile(user_id,"phone_number",text)
            return True,"✅ شماره ثبت شد\n🎓 مقطع (۱=کارشناسی ۲=ارشد ۳=دکتری ۴=دیپلم ۵=فوق):"
        elif step=="education_level":
            levels={"1":"کارشناسی","2":"کارشناسی ارشد","3":"دکتری","4":"دیپلم","5":"فوق دیپلم"}
            if text not in levels:
                return False,"مقطع نامعتبر"
            await self.db.update_profile(user_id,"education_level",levels[text])
            return True,"✅ مقطع ثبت شد\n📚 رشته:"
        elif step=="field_of_study":
            await self.db.update_profile(user_id,"field_of_study",text)
            await self.db.complete_profile(user_id)
            self.session_stats["profiles_completed"]+=1
            return True,await self.get_profile_summary(user_id)
        return False,"خطا"

    async def handle_callback(self,query:CallbackQuery):
        data=query.data
        await self.answer_callback(query.id)
        if data=="back_to_main":
            await self.edit_message(query.chat_id,query.message_id,"منوی اصلی",self.main_keyboard())
            return
        if data in COURSES:
            course=COURSES[data]
            # ⬅️ حذف دکمه‌های شیشه‌ای
            await self.edit_message(query.chat_id,query.message_id,course["title"])
            # ارسال عکس و متن
            if course["photos"]:
                await self.send_media_group(query.chat_id,course["photos"],course["caption"])
            else:
                await self.send_message(query.chat_id,course["caption"])

    async def cleanup_inactive(self):
        now=time.time()
        for uid in list(self.user_activity.keys()):
            if now-max(self.user_activity[uid])>self.INACTIVE_TIMEOUT:
                del self.user_activity[uid]

    async def start(self):
        await self.db.connect()
        self.is_running=True
        print("Bot started")
        offset=None
        last_cleanup=time.time()
        last_backup=time.time()
        try:
            while self.is_running:
                try:
                    updates=await self.get_updates(offset)
                    for update in updates:
                        offset=update["update_id"]+1
                        if "message" in update and "text" in update["message"]:
                            msg=Message(update["message"])
                            if msg.date>=self.start_time:
                                await self.process_message(msg)
                        elif "callback_query" in update:
                            q=CallbackQuery(update["callback_query"])
                            await self.handle_callback(q)
                    if time.time()-last_cleanup>300:
                        await self.cleanup_inactive()
                        last_cleanup=time.time()
                    if time.time()-last_backup>AUTO_BACKUP_INTERVAL:
                        await self.db.backup()
                        last_backup=time.time()
                except asyncio.CancelledError:
                    break
                except:
                    self.session_stats["errors"]+=1
                    await asyncio.sleep(5)
                await asyncio.sleep(POLLING_INTERVAL)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self):
        self.is_running=False
        if self.session and not self.session.closed:
            await self.session.close()
        await self.db.close()
        print("Bot stopped")


bot=BaleBot()
try:
    asyncio.run(bot.start())
except KeyboardInterrupt:
    pass