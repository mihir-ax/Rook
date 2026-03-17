import os
import uuid
import asyncio
import sys
import time
import io  # <-- for file sending
from datetime import datetime
from dotenv import load_dotenv
from pyrogram import Client, filters, idle
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
    "spotty-mufi-mafia-bd412381.koyeb.app/": "Kristeen & DDLJ",
    # Future me aur URLs yahan add kar dena
}

# Initialize Pyrogram App
app = Client("groq_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Initialize MongoDB (Async)
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["GroqBotDB"]
users_col = db["users"]
chats_col = db["chats"]

# Custom Filter for Admin Only
async def is_admin(_, __, message):
    return message.from_user and message.from_user.id == ADMIN_ID

admin_only = filters.create(is_admin)

# -------------------------------------------------------------------
# Web Server – Health Check
# -------------------------------------------------------------------
async def health_check(request):
    return web.Response(text="Groq AI Bot is ALIVE and running! 🚀")

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
        me = app.me
        bot_name = me.mention if hasattr(me, 'mention') else f"@{me.username}" if me.username else me.first_name
        subject = "🚀 Groq Chat Bot Started"
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
        print("⚠️ TARGET_BOTS empty hai. Pinger start nahi hua.")
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
# Helper Functions for User/Chat Management
# -------------------------------------------------------------------
async def get_user_data(user_id):
    user = await users_col.find_one({"_id": user_id})
    if not user:
        user = {"_id": user_id, "groq_api": None, "model_id": "llama3-8b-8192", "active_chat": None}
        await users_col.insert_one(user)
    return user

async def create_new_chat(user_id):
    chat_id = uuid.uuid4().hex
    chat_data = {
        "_id": chat_id,
        "user_id": user_id,
        "title": f"Chat {datetime.now().strftime('%d-%m %H:%M')}",
        "system_prompt": None,
        "history": [],
        "created_at": datetime.now()
    }
    await chats_col.insert_one(chat_data)
    await users_col.update_one({"_id": user_id}, {"$set": {"active_chat": chat_id}})
    return chat_id

# -------------------------------------------------------------------
# Command: /start
# -------------------------------------------------------------------
@app.on_message(filters.command("start") & admin_only)
async def start_cmd(client, message):
    await get_user_data(message.from_user.id)
    text = (
        "🤖 **Welcome to Groq AI Bot!**\n\n"
        "Sirf Admin (Aap) mujhe use kar sakte hain.\n\n"
        "**Setup Commands:**\n"
        "/set_api <api_key> - Set apna Groq API\n"
        "/set_model <model_id> - Set Model (default: llama3-8b-8192)\n\n"
        "**Chat Commands:**\n"
        "/newchat - Start fresh chat\n"
        "/showchat - Manage chats (Select/Delete)\n"
        "/system_prompt <text> - Set system prompt for current chat\n"
        "/renamechat <name> - Active chat ka naam change karein\n"
        "/history - Active chat ki poori baatcheet dikhao\n"
        "/system_prompt delete - Remove system prompt\n"
    )
    await message.reply_text(text)

# -------------------------------------------------------------------
# Command: /set_api
# -------------------------------------------------------------------
@app.on_message(filters.command("set_api") & admin_only)
async def set_api(client, message):
    if len(message.command) < 2:
        return await message.reply_text("Bhai API key bhi toh daal: `/set_api gsk_xxx...`")

    api_key = message.command[1]
    await users_col.update_one({"_id": message.from_user.id}, {"$set": {"groq_api": api_key}}, upsert=True)
    await message.reply_text("✅ Groq API Key set ho gayi!")

# -------------------------------------------------------------------
# Command: /set_model
# -------------------------------------------------------------------
@app.on_message(filters.command("set_model") & admin_only)
async def set_model(client, message):
    if len(message.command) < 2:
        return await message.reply_text("Bhai Model ID daal: `/set_model llama3-70b-8192`")

    model_id = message.command[1]
    await users_col.update_one({"_id": message.from_user.id}, {"$set": {"model_id": model_id}}, upsert=True)
    await message.reply_text(f"✅ Model ID set to: `{model_id}`")

# -------------------------------------------------------------------
# Command: /newchat
# -------------------------------------------------------------------
@app.on_message(filters.command("newchat") & admin_only)
async def new_chat(client, message):
    chat_id = await create_new_chat(message.from_user.id)
    await message.reply_text("🆕 **Naya chat start ho gaya!** Ab jo bhejoge fresh context hoga.")

# -------------------------------------------------------------------
# Command: /renamechat
# -------------------------------------------------------------------
@app.on_message(filters.command("renamechat") & admin_only)
async def rename_chat(client, message):
    user = await get_user_data(message.from_user.id)
    active_chat = user.get("active_chat")

    if not active_chat:
        return await message.reply_text("Bhai koi active chat nahi hai. Pehle `/newchat` kar ya `/showchat` se select kar!")

    if len(message.command) < 2:
        return await message.reply_text("Bhai naya naam bhi toh daal:\n**Example:** `/renamechat Python Project`")

    new_title = message.text.split(" ", 1)[1]
    await chats_col.update_one({"_id": active_chat}, {"$set": {"title": new_title}})
    await message.reply_text(f"✅ Active chat ka naam update ho gaya!\nNaya naam: **{new_title}**")

# -------------------------------------------------------------------
# Command: /system_prompt
# -------------------------------------------------------------------
@app.on_message(filters.command("system_prompt") & admin_only)
async def sys_prompt(client, message):
    user = await get_user_data(message.from_user.id)
    active_chat = user.get("active_chat")

    if not active_chat:
        return await message.reply_text("Pehle `/newchat` kar bhai!")

    if len(message.command) < 2:
        chat = await chats_col.find_one({"_id": active_chat})
        curr_prompt = chat.get("system_prompt", "Koi prompt nahi hai.")
        return await message.reply_text(f"📝 **Current System Prompt:**\n`{curr_prompt}`")

    prompt_text = message.text.split(" ", 1)[1]

    if prompt_text.lower() == "delete":
        await chats_col.update_one({"_id": active_chat}, {"$set": {"system_prompt": None}})
        return await message.reply_text("🗑 System prompt delete kar diya.")

    await chats_col.update_one({"_id": active_chat}, {"$set": {"system_prompt": prompt_text}})
    await message.reply_text(f"✅ System Prompt set ho gaya:\n`{prompt_text}`")

# -------------------------------------------------------------------
# Command: /showchat (with inline buttons)
# -------------------------------------------------------------------
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

# -------------------------------------------------------------------
# NEW COMMAND: /history - Show full conversation of active chat
# -------------------------------------------------------------------
@app.on_message(filters.command("history") & admin_only)
async def history_cmd(client, message):
    user = await get_user_data(message.from_user.id)
    active_chat = user.get("active_chat")

    if not active_chat:
        return await message.reply_text("❌ Koi active chat nahi hai. Pehle `/newchat` start karo ya `/showchat` se select karo.")

    chat = await chats_col.find_one({"_id": active_chat})
    if not chat:
        return await message.reply_text("❌ Active chat database me nahi mila. Shayad delete ho gaya?")
    
    history = chat.get("history", [])
    system_prompt = chat.get("system_prompt")

    if not history and not system_prompt:
        return await message.reply_text("📭 Is chat mein abhi koi baat nahi hui hai.")

    # Format the conversation
    lines = []
    lines.append(f"**Chat Title:** {chat['title']}\n")
    if system_prompt:
        lines.append("**📌 System Prompt:**")
        lines.append(f"`{system_prompt}`\n")
    lines.append("**💬 Conversation:**\n")

    for msg in history:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "user":
            lines.append(f"👤 **User:** {content}\n")
        elif role == "assistant":
            lines.append(f"🤖 **Assistant:** {content}\n")
        else:
            lines.append(f"**{role}:** {content}\n")

    full_text = "\n".join(lines)

    # Telegram message limit is 4096 characters
    if len(full_text) <= 4096:
        await message.reply_text(full_text)
    else:
        # Send as a text file
        file_data = io.BytesIO(full_text.encode('utf-8'))
        file_data.name = f"chat_history_{active_chat[:8]}.txt"
        await message.reply_document(
            document=file_data,
            caption=f"📜 **Poori baatcheet** (Character count: {len(full_text)})\nChat: {chat['title']}"
        )

# -------------------------------------------------------------------
# Main AI Chat Handler
# -------------------------------------------------------------------
@app.on_message(filters.text & ~filters.command(["start", "set_api", "set_model", "newchat", "showchat", "renamechat", "system_prompt", "history"]) & admin_only)
async def chat_handler(client, message):
    user = await get_user_data(message.from_user.id)

    api_key = user.get("groq_api")
    model_id = user.get("model_id")

    if not api_key:
        return await message.reply_text("Bhai pehle API key set kar: `/set_api YOUR_KEY`")

    active_chat_id = user.get("active_chat")
    if not active_chat_id:
        active_chat_id = await create_new_chat(message.from_user.id)

    # Fetch Chat Context
    chat_doc = await chats_col.find_one({"_id": active_chat_id})
    history = chat_doc.get("history", [])
    system_prompt = chat_doc.get("system_prompt")

    # Prepare Groq Messages
    groq_messages = []
    if system_prompt:
        groq_messages.append({"role": "system", "content": system_prompt})

    # Append past history to keep context
    groq_messages.extend(history)

    # Append current message
    current_msg = {"role": "user", "content": message.text}
    groq_messages.append(current_msg)

    processing_msg = await message.reply_text("⏳ Thinking...")

    try:
        groq_client = AsyncGroq(api_key=api_key)
        chat_completion = await groq_client.chat.completions.create(
            messages=groq_messages,
            model=model_id,
        )

        bot_response = chat_completion.choices[0].message.content

        # Save to MongoDB to maintain context
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

        await processing_msg.edit_text(bot_response)

    except Exception as e:
        await processing_msg.edit_text(f"❌ **Error aagaya bhai:**\n`{str(e)}`")

# -------------------------------------------------------------------
# MongoDB Connection Check
# -------------------------------------------------------------------
async def check_mongo_connection():
    print("🔄 Checking MongoDB Connection...")
    try:
        await db_client.admin.command('ping')
        print("✅ MongoDB Connected Successfully! (IP is Whitelisted)")
        return True
    except Exception as e:
        print(f"❌ MongoDB Connection FAILED!")
        print(f"⚠️ Error: {e}")
        print("👉 Hint: Apna MONGO_URI check kar aur MongoDB Atlas me Network Access -> '0.0.0.0/0' (Allow Anywhere) set kar.")
        sys.exit(1)

# -------------------------------------------------------------------
# Main entry point (Telegram + Web Server + Pinger)
# -------------------------------------------------------------------
async def main():
    print("🚀 Starting Bot, Web Server & Pinger...")
    
    await check_mongo_connection()
    
    await app.start()
    print("✅ Telegram Bot is Online!")

    await send_startup_alert()

    asyncio.create_task(ping_other_bot())
    print("🔄 Pinger background task started.")

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
    except Exception as e:
        print(f"⚠️ Bot crashed: {e}")
    finally:
        print("🛑 Stopping services...")
        await runner.cleanup()
        await app.stop()
        print("✅ Gracefully shut down.")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("🛑 Bot stopped by user (Ctrl+C).")
