import os
import uuid
import asyncio
import sys
import time
import io
import re
import pytz
from datetime import datetime
from dotenv import load_dotenv
from pyrogram import Client, filters, idle, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from groq import AsyncGroq
from aiohttp import web
import aiohttp

# Load Environment Variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Alerify aur Target Bots ke liye config
ALERIFY_URL = "https://rapid-x-chi.vercel.app/send"
TARGET_BOTS = {
    "https://spotty-mufi-mafia-bd412381.koyeb.app": "Kristeen & DDLJ",
}

# Initialize Pyrogram App
app = Client("groq_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Initialize MongoDB
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["GroqBotDB"]
users_col = db["users"]
chats_col = db["chats"]
reminders_col = db["reminders"]
todos_col = db["todos"]

ist_tz = pytz.timezone("Asia/Kolkata")

# Custom Filter for Admin Only
async def is_admin(_, __, message):
    return message.from_user and message.from_user.id == ADMIN_ID

admin_only = filters.create(is_admin)

# -------------------------------------------------------------------
# Helper: Markdown to Telegram HTML Parser
# -------------------------------------------------------------------
def md_to_tg_html(text: str) -> str:
    # Headers ### to Bold
    text = re.sub(r'###\s+(.*)', r'<b>\1</b>', text)
    text = re.sub(r'##\s+(.*)', r'<b>\1</b>', text)
    text = re.sub(r'#\s+(.*)', r'<b>\1</b>', text)
    # Bold **text**
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    # Italic *text*
    text = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    # Code Blocks
    text = re.sub(r'```(?:.*?)\n(.*?)```', r'<pre>\1</pre>', text, flags=re.DOTALL)
    # Inline Code
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
    # Unordered Lists - to •
    text = re.sub(r'^\s*-\s+', r'• ', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\*\s+', r'• ', text, flags=re.MULTILINE)
    
    # Escape accidental unclosed tags if necessary (Basic protection)
    text = text.replace("<br>", "\n")
    return text

# -------------------------------------------------------------------
# Web Server – Health Check
# -------------------------------------------------------------------
async def health_check(request):
    return web.Response(text="Groq AI Bot PRO is ALIVE and running! 🚀")

# -------------------------------------------------------------------
# Alerify Alert Sender
# -------------------------------------------------------------------
async def send_alerify_alert(subject: str, tg_msg: str, email_msg: str):
    payload = {
        "subject": subject,
        "tg_html_message": tg_msg,
        "email_html_message": email_msg
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(ALERIFY_URL, json=payload) as resp:
                if resp.status == 200:
                    print(f"✅ Alert Sent: {subject}")
                else:
                    print(f"⚠️ Alerify API Failed with status {resp.status}")
    except Exception as e:
        print(f"❌ Failed to connect to Alerify API: {e}")

# -------------------------------------------------------------------
# Startup Alert
# -------------------------------------------------------------------
async def send_startup_alert():
    try:
        me = await app.get_me()
        bot_name = me.mention if hasattr(me, 'mention') else f"@{me.username}" if me.username else me.first_name
        subject = "🚀 Groq Chat Bot PRO Started"
        tg_msg = f"<b>Groq AI Bot is now online!</b>\n\n• {bot_name}"
        email_msg = f"<h2>Bot Started</h2><p>{bot_name}</p>"
        await send_alerify_alert(subject, tg_msg, email_msg)
    except Exception as e:
        print(f"⚠️ Could not send startup alert: {e}")

# -------------------------------------------------------------------
# URL Checker Helper (for Pinger)
# -------------------------------------------------------------------
async def check_url(session, url):
    try:
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        async with session.get(url, timeout=10) as response:
            return url, response.status == 200
    except Exception:
        return url, False

# -------------------------------------------------------------------
# Pinger Task
# -------------------------------------------------------------------
async def ping_other_bot():
    if not TARGET_BOTS:
        return

    print(f"🔄 Advanced Pinger started for {len(TARGET_BOTS)} Bots...")
    bot_states = {url: True for url in TARGET_BOTS.keys()}
    last_hourly_report_time = time.time()

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                tasks = [check_url(session, url) for url in TARGET_BOTS.keys()]
                results = await asyncio.gather(*tasks)

                for url, is_up in results:
                    bot_name = TARGET_BOTS[url]
                    was_up = bot_states[url]

                    if not is_up and was_up:
                        bot_states[url] = False
                        subject = f"🚨 URGENT: {bot_name} is DOWN!"
                        tg_msg = f"<b>Bot Alert!</b>\n\n❌ <b>{bot_name}</b> respond nahi kar raha.\n🔗 URL: {url}\n⏳ Status: <b>DOWN</b>"
                        email_msg = f"<h2>Bot Down Alert</h2><p><b>{bot_name}</b> is offline.</p><p>URL: {url}</p>"
                        await send_alerify_alert(subject, tg_msg, email_msg)

                    elif is_up and not was_up:
                        bot_states[url] = True
                        subject = f"✅ RECOVERED: {bot_name} is UP!"
                        tg_msg = f"<b>Bot Recovery</b>\n\n✅ <b>{bot_name}</b> wapas online aa gaya!\n🔗 URL: {url}\n⏳ Status: <b>UP</b>"
                        email_msg = f"<h2>Bot Recovery</h2><p><b>{bot_name}</b> is back online.</p><p>URL: {url}</p>"
                        await send_alerify_alert(subject, tg_msg, email_msg)

            current_time = time.time()
            if current_time - last_hourly_report_time >= 3600:
                last_hourly_report_time = current_time

                report_tg = "<b>Hourly Bot Status Report 📊</b>\n\n"
                report_email = "<h2>Hourly Bot Status Report 📊</h2><ul>"
                all_good = True

                for url, state in bot_states.items():
                    b_name = TARGET_BOTS[url]
                    status_icon = "🟢 UP" if state else "🔴 DOWN"
                    if not state:
                        all_good = False
                    report_tg += f"• {b_name}: <b>{status_icon}</b>\n"
                    report_email += f"<li>{b_name}: {status_icon}</li>"

                report_email += "</ul>"
                subject = "🟢 All Systems Nominal" if all_good else "⚠️ System Status Report (Issues Detected)"
                await send_alerify_alert(subject, report_tg, report_email)

        except Exception as e:
            print(f"Pinger Core Error: {e}")

        await asyncio.sleep(20)

# -------------------------------------------------------------------
# Helper Functions for DB
# -------------------------------------------------------------------
async def get_user_data(user_id):
    user = await users_col.find_one({"_id": user_id})
    if not user:
        user = {"_id": user_id, "groq_api": None, "model_id": "llama3-8b-8192", "active_chat": None}
        await users_col.insert_one(user)
    return user

async def create_new_chat(user_id):
    chat_id = uuid.uuid4().hex
    
    # SYSTEM PROMPT INJECTION
    sys_prompt = (
        "You are an advanced Telegram Personal Assistant.\n"
        "You have superpowers to execute commands by outputting specific tags in your response. "
        "These tags will be processed by the system and hidden from the user.\n\n"
        "1. To set a reminder, output EXACTLY this format anywhere in text:\n"
        "[REMINDER: YYYY-MM-DD HH:MM:SS | Your reminder message]\n"
        "2. To create a Telegram Poll, output EXACTLY this:\n"
        "[POLL: Question | Option1, Option2, Option3 | is_anonymous(True/False)]\n"
        "3. To add a task to To-Do list:\n"
        "[TODO_ADD: Task details]\n"
        "4. To mark a task done:\n"
        "[TODO_DONE: Task details]\n\n"
        "Always use the Indian Standard Time (IST) provided to you for calculating reminder dates. "
        "Be helpful, concise, and smart."
    )
    
    chat_data = {
        "_id": chat_id,
        "user_id": user_id,
        "title": f"Chat {datetime.now(ist_tz).strftime('%d-%m %H:%M')}",
        "system_prompt": sys_prompt,
        "history": [],
        "created_at": datetime.now(ist_tz)
    }
    await chats_col.insert_one(chat_data)
    await users_col.update_one({"_id": user_id}, {"$set": {"active_chat": chat_id}})
    return chat_id

# -------------------------------------------------------------------
# System Background Workers (Reminders)
# -------------------------------------------------------------------
async def reminder_worker():
    print("⏰ Auto-Reminder system started...")
    while True:
        try:
            now = datetime.now(ist_tz)
            due_reminders = await reminders_col.find({"time": {"$lte": now}}).to_list(None)
            
            for r in due_reminders:
                await app.send_message(
                    r["user_id"], 
                    f"⏰ **AUTO REMINDER ALARM!**\n\n📌 {r['message']}\n\n_Set by AI at your request._",
                )
                await reminders_col.delete_one({"_id": r["_id"]})
                
        except Exception as e:
            pass
        
        await asyncio.sleep(20)

# -------------------------------------------------------------------
# Telegram Commands
# -------------------------------------------------------------------
@app.on_message(filters.command("start") & admin_only)
async def start_cmd(client, message):
    await get_user_data(message.from_user.id)
    text = (
        "🤖 **Welcome to Groq AI Bot PRO!**\n\n"
        "I am now an advanced Assistant. I can set reminders, create polls, and manage your to-dos.\n\n"
        "**Setup Commands:**\n"
        "/set_api <api_key> - Set apna Groq API\n"
        "/set_model <model_id> - Set Model (default: llama3-8b-8192)\n\n"
        "**Chat Commands:**\n"
        "/newchat - Start fresh chat\n"
        "/showchat - Manage chats\n"
        "/renamechat <name> - Rename chat\n"
        "/history - Get full chat text\n"
        "/todo - View pending tasks\n"
    )
    await message.reply_text(text)

@app.on_message(filters.command("set_api") & admin_only)
async def set_api(client, message):
    if len(message.command) < 2:
        return await message.reply_text("Bhai API key bhi toh daal: `/set_api gsk_xxx...`")

    api_key = message.command[1]
    await users_col.update_one({"_id": message.from_user.id}, {"$set": {"groq_api": api_key}}, upsert=True)
    await message.reply_text("✅ Groq API Key set ho gayi!")

@app.on_message(filters.command("set_model") & admin_only)
async def set_model(client, message):
    if len(message.command) < 2:
        return await message.reply_text("Bhai Model ID daal: `/set_model llama3-70b-8192`")

    model_id = message.command[1]
    await users_col.update_one({"_id": message.from_user.id}, {"$set": {"model_id": model_id}}, upsert=True)
    await message.reply_text(f"✅ Model ID set to: `{model_id}`")

@app.on_message(filters.command("newchat") & admin_only)
async def new_chat(client, message):
    chat_id = await create_new_chat(message.from_user.id)
    await message.reply_text("🆕 **Naya chat start ho gaya!** Ab jo bhejoge fresh context hoga.")

@app.on_message(filters.command("renamechat") & admin_only)
async def rename_chat(client, message):
    user = await get_user_data(message.from_user.id)
    active_chat = user.get("active_chat")

    if not active_chat:
        return await message.reply_text("Bhai koi active chat nahi hai.")

    if len(message.command) < 2:
        return await message.reply_text("Bhai naya naam bhi toh daal:\n**Example:** `/renamechat Python Project`")

    new_title = message.text.split(" ", 1)[1]
    await chats_col.update_one({"_id": active_chat}, {"$set": {"title": new_title}})
    await message.reply_text(f"✅ Active chat ka naam update ho gaya!\nNaya naam: **{new_title}**")

@app.on_message(filters.command("todo") & admin_only)
async def todo_cmd(client, message):
    todos = await todos_col.find({"user_id": message.from_user.id, "status": "pending"}).to_list(None)
    if not todos:
        return await message.reply_text("🎉 Koi pending task nahi hai bhai! Chill kar.")
    
    text = "📝 **Your Pending To-Do List:**\n\n"
    for i, t in enumerate(todos, 1):
        text += f"{i}. {t['task']}\n"
    
    text += "\n_(AI ko bol kar add ya complete kara sakte ho)_"
    await message.reply_text(text)

@app.on_message(filters.command("showchat") & admin_only)
async def show_chats(client, message):
    chats = await chats_col.find({"user_id": message.from_user.id}).sort("created_at", -1).to_list(10)
    if not chats:
        return await message.reply_text("Koi history nahi hai bro.")

    user = await get_user_data(message.from_user.id)
    active_chat = user.get("active_chat")

    buttons = []
    for chat in chats:
        title = chat['title']
        if chat['_id'] == active_chat:
            title = f"🟢 {title} (Active)"
        else:
            title = f"📁 {title}"

        buttons.append([InlineKeyboardButton(title, callback_data=f"select_{chat['_id']}")])
        buttons.append([InlineKeyboardButton("❌ Delete", callback_data=f"del_{chat['_id']}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    await message.reply_text("👇 **Apne chats select ya delete karo:**", reply_markup=reply_markup)

@app.on_callback_query(filters.regex(r"^(select|del)_"))
async def handle_chat_buttons(client, callback_query):
    action, chat_id = callback_query.data.split("_")
    user_id = callback_query.from_user.id

    if action == "select":
        await users_col.update_one({"_id": user_id}, {"$set": {"active_chat": chat_id}})
        await callback_query.answer("Chat switch ho gaya!", show_alert=True)
        await callback_query.message.delete()
        await client.send_message(user_id, "✅ **Chat Switched!** Purana context wapas load ho gaya.")

    elif action == "del":
        await chats_col.delete_one({"_id": chat_id})
        user = await get_user_data(user_id)
        if user.get("active_chat") == chat_id:
            await users_col.update_one({"_id": user_id}, {"$set": {"active_chat": None}})
        await callback_query.answer("Chat Deleted!", show_alert=True)
        await callback_query.message.delete()

@app.on_message(filters.command("history") & admin_only)
async def history_cmd(client, message):
    user = await get_user_data(message.from_user.id)
    active_chat = user.get("active_chat")

    if not active_chat:
        return await message.reply_text("❌ Koi active chat nahi hai.")

    chat = await chats_col.find_one({"_id": active_chat})
    if not chat:
        return await message.reply_text("❌ Active chat database me nahi mila.")
    
    history = chat.get("history", [])
    if not history:
        return await message.reply_text("📭 Is chat mein abhi koi baat nahi hui hai.")

    lines = []
    lines.append(f"**Chat Title:** {chat['title']}\n")
    lines.append("**💬 Conversation:**\n")

    for msg in history:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "user":
            lines.append(f"👤 **User:** {content}\n")
        elif role == "assistant":
            # Remove system tags from history file for clean reading
            clean_content = re.sub(r'\[REMINDER:.*?\]', '', content)
            clean_content = re.sub(r'\[POLL:.*?\]', '', clean_content)
            clean_content = re.sub(r'\[TODO_ADD:.*?\]', '', clean_content)
            clean_content = re.sub(r'\[TODO_DONE:.*?\]', '', clean_content)
            lines.append(f"🤖 **Assistant:** {clean_content.strip()}\n")

    full_text = "\n".join(lines)

    if len(full_text) <= 4096:
        await message.reply_text(full_text)
    else:
        file_data = io.BytesIO(full_text.encode('utf-8'))
        file_data.name = f"chat_history_{active_chat[:8]}.txt"
        await message.reply_document(
            document=file_data,
            caption=f"📜 **Poori baatcheet**\nChat: {chat['title']}"
        )

# -------------------------------------------------------------------
# AI Chat Handler & Tag Parser
# -------------------------------------------------------------------
@app.on_message(filters.text & ~filters.command(["start", "set_api", "set_model", "newchat", "showchat", "renamechat", "system_prompt", "history", "todo"]) & admin_only)
async def chat_handler(client, message):
    user_id = message.from_user.id
    user = await get_user_data(user_id)

    api_key = user.get("groq_api")
    if not api_key:
        return await message.reply_text("Bhai API key set kar: `/set_api YOUR_KEY`")

    active_chat_id = user.get("active_chat")
    if not active_chat_id:
        active_chat_id = await create_new_chat(user_id)

    chat_doc = await chats_col.find_one({"_id": active_chat_id})
    history = chat_doc.get("history", [])
    system_prompt = chat_doc.get("system_prompt", "")

    # 1. TIME INJECTION
    current_time = datetime.now(ist_tz).strftime('%Y-%m-%d %H:%M:%S IST')
    time_context = f"\n[System Info - Current IST Time: {current_time}]\n"
    
    groq_messages = []
    if system_prompt:
        groq_messages.append({"role": "system", "content": system_prompt + time_context})
    
    groq_messages.extend(history)
    current_msg = {"role": "user", "content": message.text}
    groq_messages.append(current_msg)

    # Typing Action Start
    await app.send_chat_action(message.chat.id, enums.ChatAction.TYPING)
    processing_msg = await message.reply_text("⏳ Thinking...")

    try:
        groq_client = AsyncGroq(api_key=api_key)
        chat_completion = await groq_client.chat.completions.create(
            messages=groq_messages,
            model=user.get("model_id", "llama3-8b-8192"),
        )

        bot_response = chat_completion.choices[0].message.content

        # -----------------------------------------------------
        # 2. PARSE AI ACTION TAGS
        # -----------------------------------------------------
        clean_response = bot_response
        actions_taken = []

        # A) REMINDER
        reminder_match = re.search(r'\[REMINDER:\s*(.*?)\s*\|\s*(.*?)\]', clean_response)
        if reminder_match:
            try:
                dt_str = reminder_match.group(1).strip()
                msg_str = reminder_match.group(2).strip()
                rem_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                rem_time = ist_tz.localize(rem_time) 
                
                await reminders_col.insert_one({"user_id": user_id, "time": rem_time, "message": msg_str})
                actions_taken.append(f"⏰ Reminder set for {dt_str}")
            except Exception as e:
                print(f"Failed to parse reminder: {e}")
            clean_response = re.sub(r'\[REMINDER:.*?\]', '', clean_response)

        # B) POLL
        poll_match = re.search(r'\[POLL:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\]', clean_response)
        if poll_match:
            try:
                question = poll_match.group(1).strip()
                options = [opt.strip() for opt in poll_match.group(2).split(",")]
                is_anon = poll_match.group(3).strip().lower() == "true"
                
                await app.send_poll(
                    chat_id=message.chat.id,
                    question=question,
                    options=options[:10],
                    is_anonymous=is_anon
                )
                actions_taken.append("📊 Poll created.")
            except Exception as e:
                print(f"Failed to create poll: {e}")
            clean_response = re.sub(r'\[POLL:.*?\]', '', clean_response)

        # C) TODO ADD
        todo_add_match = re.search(r'\[TODO_ADD:\s*(.*?)\]', clean_response)
        if todo_add_match:
            task = todo_add_match.group(1).strip()
            await todos_col.insert_one({"user_id": user_id, "task": task, "status": "pending"})
            actions_taken.append(f"📝 Added to Todo: {task}")
            clean_response = re.sub(r'\[TODO_ADD:.*?\]', '', clean_response)

        # D) TODO DONE
        todo_done_match = re.search(r'\[TODO_DONE:\s*(.*?)\]', clean_response)
        if todo_done_match:
            task = todo_done_match.group(1).strip()
            await todos_col.update_one({"user_id": user_id, "task": {"$regex": task, "$options": "i"}}, {"$set": {"status": "completed"}})
            actions_taken.append(f"✅ Marked done: {task}")
            clean_response = re.sub(r'\[TODO_DONE:.*?\]', '', clean_response)

        action_text = "\n\n".join([f"_{a}_" for a in actions_taken])
        if action_text:
            action_text = f"\n\n{action_text}"

        # -----------------------------------------------------
        # 3. HTML PARSING & SENDING
        # -----------------------------------------------------
        final_text = md_to_tg_html(clean_response.strip()) + action_text

        # Update DB History
        await chats_col.update_one(
            {"_id": active_chat_id},
            {"$push": {
                "history": {
                    "$each": [
                        current_msg,
                        {"role": "assistant", "content": bot_response} 
                    ]
                }
            }}
        )

        try:
            await processing_msg.edit_text(final_text, parse_mode=enums.ParseMode.HTML)
        except Exception:
            # Fallback if HTML parser fails
            await processing_msg.edit_text(clean_response.strip() + action_text)

    except Exception as e:
        await processing_msg.edit_text(f"❌ **Error aagaya bhai:**\n`{str(e)}`")


# -------------------------------------------------------------------
# MongoDB Connection Check
# -------------------------------------------------------------------
async def check_mongo_connection():
    print("🔄 Checking MongoDB Connection...")
    try:
        await db_client.admin.command('ping')
        print("✅ MongoDB Connected Successfully!")
        return True
    except Exception as e:
        print(f"❌ MongoDB Connection FAILED! Error: {e}")
        sys.exit(1)

# -------------------------------------------------------------------
# Main entry point
# -------------------------------------------------------------------
async def main():
    print("🚀 Starting Bot, Web Server & Pinger...")
    
    await check_mongo_connection()
    
    await app.start()
    print("✅ Telegram Bot is Online!")

    await send_startup_alert()

    # Start Background Tasks
    asyncio.create_task(ping_other_bot())
    asyncio.create_task(reminder_worker())

    server = web.Application()
    server.router.add_get("/", health_check)
    runner = web.AppRunner(server)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Web Server is running on port {port}!")

    try:
        await idle()
    except asyncio.CancelledError:
        pass
    finally:
        print("🛑 Stopping services...")
        await runner.cleanup()
        await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("🛑 Bot stopped by user (Ctrl+C).")
