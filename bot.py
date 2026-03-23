import os
import uuid
import asyncio
import sys
import time
import io
import json
import re
import pytz
from datetime import datetime
from dotenv import load_dotenv
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from groq import AsyncGroq
from aiohttp import web
import aiohttp
import pyrogram.enums

# Load Environment Variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Configuration
ALERIFY_URL = "https://rapid-x-chi.vercel.app/send"
TARGET_BOTS = {
    "https://spotty-mufi-mafia-bd412381.koyeb.app": "Kristeen & DDLJ",
}
IST = pytz.timezone('Asia/Kolkata')

# Initialize Pyrogram App
app = Client("groq_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Initialize MongoDB
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["GroqBotDB"]
users_col = db["users"]
chats_col = db["chats"]
reminders_col = db["reminders"]
wallets_col = db["wallets"]
transactions_col = db["transactions"]

# Custom Filter for Admin Only
async def is_admin(_, __, message):
    return message.from_user and message.from_user.id == ADMIN_ID
admin_only = filters.create(is_admin)

# -------------------------------------------------------------------
# Helper: Markdown to HTML Parser
# -------------------------------------------------------------------
def markdown_to_html(text):
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text) # Bold
    text = re.sub(r'(?<!\*)\*(?!\*)(.*?)\*', r'<i>\1</i>', text) # Italic
    text = re.sub(r'```(.*?)```', r'<pre><code>\1</code></pre>', text, flags=re.DOTALL) # Code block
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text) # Inline code
    text = re.sub(r'~~(.*?)~~', r'<s>\1</s>', text) # Strikethrough
    return text

# -------------------------------------------------------------------
# Web Server & Alerify Pinger
# -------------------------------------------------------------------
async def health_check(request):
    return web.Response(text="Groq AI Bot is ALIVE and running! 🚀")

async def send_alerify_alert(subject: str, tg_msg: str, email_msg: str):
    payload = {"subject": subject, "tg_html_message": tg_msg, "email_html_message": email_msg}
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(ALERIFY_URL, json=payload)
    except Exception:
        pass

async def send_startup_alert():
    try:
        me = await app.get_me()
        bot_name = me.mention if hasattr(me, 'mention') else me.first_name
        await send_alerify_alert("🚀 Groq Chat Bot Started", f"<b>Groq AI Bot Online!</b>\n\n• {bot_name}", f"<h2>Bot Started</h2><p>{bot_name}</p>")
    except Exception:
        pass

async def check_url(session, url):
    try:
        if not url.startswith(('http://', 'https://')): url = 'https://' + url
        async with session.get(url, timeout=10) as response:
            return url, response.status == 200
    except Exception:
        return url, False

async def ping_other_bot():
    if not TARGET_BOTS: return
    bot_states = {url: True for url in TARGET_BOTS.keys()}
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                tasks = [check_url(session, url) for url in TARGET_BOTS.keys()]
                results = await asyncio.gather(*tasks)
                for url, is_up in results:
                    was_up = bot_states[url]
                    if not is_up and was_up:
                        bot_states[url] = False
                        await send_alerify_alert(f"🚨 URGENT: {TARGET_BOTS[url]} DOWN!", f"❌ <b>{TARGET_BOTS[url]}</b> is DOWN!\n🔗 {url}", "")
                    elif is_up and not was_up:
                        bot_states[url] = True
                        await send_alerify_alert(f"✅ RECOVERED: {TARGET_BOTS[url]} UP!", f"✅ <b>{TARGET_BOTS[url]}</b> is UP!\n🔗 {url}", "")
        except Exception:
            pass
        await asyncio.sleep(60)

# -------------------------------------------------------------------
# Background Task: Reminder Worker
# -------------------------------------------------------------------
async def reminder_worker():
    print("⏰ Reminder Worker Started...")
    while True:
        try:
            now = datetime.now(IST)
            due_reminders = await reminders_col.find({"status": "pending", "remind_time": {"$lte": now}}).to_list(None)
            for r in due_reminders:
                task_html = markdown_to_html(r["task"])
                alert_msg = f"🚨 <b>REMINDER ALARM</b> 🚨\n\n👉 {task_html}\n\n<i>Set by your AI Assistant</i>"
                await app.send_message(r["user_id"], alert_msg, parse_mode=pyrogram.enums.ParseMode.HTML)
                await reminders_col.update_one({"_id": r["_id"]}, {"$set": {"status": "completed"}})
        except Exception as e:
            print(f"Reminder Worker Error: {e}")
        await asyncio.sleep(30)

# -------------------------------------------------------------------
# DB Helpers
# -------------------------------------------------------------------
async def get_user_data(user_id):
    user = await users_col.find_one({"_id": user_id})
    if not user:
        user = {"_id": user_id, "groq_api": None, "model_id": "llama3-8b-8192", "active_chat": None}
        await users_col.insert_one(user)
    return user

async def create_new_chat(user_id):
    chat_id = uuid.uuid4().hex
    chat_data = {"_id": chat_id, "user_id": user_id, "title": f"Chat {datetime.now(IST).strftime('%d-%m %H:%M')}", "system_prompt": None, "history": [], "created_at": datetime.now(IST)}
    await chats_col.insert_one(chat_data)
    await users_col.update_one({"_id": user_id}, {"$set": {"active_chat": chat_id}})
    return chat_id

# -------------------------------------------------------------------
# Commands (Start, Config, Chat Manage)
# -------------------------------------------------------------------
@app.on_message(filters.command("start") & admin_only)
async def start_cmd(client, message):
    await get_user_data(message.from_user.id)
    text = ("🤖 **Welcome to Groq AI Manager!**\n\n"
            "**Commands:**\n"
            "/set_api <api_key> - Set Groq API\n"
            "/set_model <model_id> - Set Model\n"
            "/newchat - Start fresh chat\n"
            "/showchat - Manage chats\n"
            "/history - Full chat history\n"
            "/finance - Dashboard of your wealth\n")
    await message.reply_text(text)

@app.on_message(filters.command("set_api") & admin_only)
async def set_api(client, message):
    if len(message.command) < 2: return await message.reply_text("Bhai API key daal: `/set_api gsk_...`")
    await users_col.update_one({"_id": message.from_user.id}, {"$set": {"groq_api": message.command[1]}}, upsert=True)
    await message.reply_text("✅ Groq API Key set!")

@app.on_message(filters.command("set_model") & admin_only)
async def set_model(client, message):
    if len(message.command) < 2: return await message.reply_text("Bhai Model ID daal: `/set_model llama3-70b-8192`")
    await users_col.update_one({"_id": message.from_user.id}, {"$set": {"model_id": message.command[1]}}, upsert=True)
    await message.reply_text(f"✅ Model ID set to: `{message.command[1]}`")

@app.on_message(filters.command("newchat") & admin_only)
async def new_chat(client, message):
    await create_new_chat(message.from_user.id)
    await message.reply_text("🆕 **Naya chat start ho gaya!**")

@app.on_message(filters.command("finance") & admin_only)
async def finance_dashboard(client, message):
    user_id = message.from_user.id
    wallet = await wallets_col.find_one({"_id": user_id})
    if not wallet or not wallet.get("banks"):
        return await message.reply_text("Bhai bank me kuch nahi hai. AI ko bol 'Mere pass 10,000 Cash hain'.")
    
    banks = wallet.get("banks")
    total = sum(banks.values())
    msg = f"📊 <b>FINANCIAL DASHBOARD</b>\n\n💰 <b>Net Worth:</b> ₹{total:,.2f}\n\n🏦 <b>Accounts:</b>\n"
    for b, bal in banks.items(): msg += f"• {b}: ₹{bal:,.2f}\n"
    
    recent_tx = await transactions_col.find({"user_id": user_id}).sort("date", -1).to_list(10)
    if recent_tx:
        msg += "\n📝 <b>Recent Transactions:</b>\n"
        for tx in recent_tx:
            icon = "🟢" if tx['type'] in ['income', 'setup'] else "🔴"
            dt = tx['date'].strftime("%d %b")
            msg += f"{icon} ₹{tx['amount']} | {tx['bank']} ({tx['category']}) - <i>{dt}</i>\n"
            
    await message.reply_text(msg, parse_mode=pyrogram.enums.ParseMode.HTML)

# -------------------------------------------------------------------
# MAIN AI ENGINE (Jarvis Logic + Tool Calling)
# -------------------------------------------------------------------
@app.on_message(filters.text & ~filters.command(["start", "set_api", "set_model", "newchat", "showchat", "renamechat", "system_prompt", "history", "finance"]) & admin_only)
async def chat_handler(client, message):
    user_id = message.from_user.id
    user = await get_user_data(user_id)
    api_key, model_id = user.get("groq_api"), user.get("model_id")

    if not api_key: return await message.reply_text("Bhai API key set kar le pehle.")

    active_chat_id = user.get("active_chat")
    if not active_chat_id: active_chat_id = await create_new_chat(user_id)

    chat_doc = await chats_col.find_one({"_id": active_chat_id})
    history = chat_doc.get("history", [])
    
    # --- FETCH FINANCE CONTEXT ---
    user_wallet = await wallets_col.find_one({"_id": user_id})
    if not user_wallet:
        user_wallet = {"_id": user_id, "banks": {"Cash": 0}}
        await wallets_col.insert_one(user_wallet)
    current_balances = json.dumps(user_wallet.get("banks", {}))
    
    # Analytics ke liye Last 30 transactions nikalo
    recent_txs = await transactions_col.find({"user_id": user_id}).sort("date", -1).to_list(30)
    tx_history_str = "No recent transactions."
    if recent_txs:
        tx_history_str = "\n".join([f"[{t['date'].strftime('%Y-%m-%d %H:%M')}] {t['type'].upper()} | ₹{t['amount']} | Bank: {t['bank']} | Category: {t['category']} | Note: {t['note']}" for t in recent_txs])

    # --- THE SYSTEM PROMPT ---
    current_time = datetime.now(IST).strftime("%A, %d %B %Y, %I:%M %p")
    sys_prompt = (
        f"You are J.A.R.V.I.S, a highly intelligent Personal Assistant, Task Manager, and Financial Advisor for the user.\n"
        f"Current Date/Time: {current_time} (IST timezone).\n\n"
        
        f"=== FINANCIAL DATA ===\n"
        f"Current Bank Balances: {current_balances}\n"
        f"Recent Transaction History (for analysis):\n{tx_history_str}\n\n"
        
        f"=== INSTRUCTIONS FOR TOOLS ===\n"
        f"If the user asks you to take an ACTION (set reminder or record finance), output exactly the corresponding JSON block at the very end of your response.\n\n"
        
        f"1. **REMINDERS:** To set a reminder, output:\n"
        f"```json\n{{\"action\": \"set_reminder\", \"time\": \"YYYY-MM-DD HH:MM\", \"task\": \"task details\"}}\n```\n\n"
        
        f"2. **FINANCE:** To record spending, income, or setting initial balance, output:\n"
        f"```json\n{{\"action\": \"finance\", \"type\": \"expense|income|setup\", \"bank\": \"Bank Name\", \"amount\": 100, \"category\": \"Food/Shopping/Salary/etc\", \"note\": \"short note\"}}\n```\n"
        f"(Keep amount positive. Use 'Cash' if no bank is mentioned.)\n\n"
        
        f"If the user asks analytical questions like 'Where am I spending the most?' or 'Show my last 5 transactions', use the provided 'Recent Transaction History' to give a detailed, natural language response. You don't need to output JSON for analytical questions.\n"
    )

    groq_messages = [{"role": "system", "content": sys_prompt}]
    groq_messages.extend(history)
    current_msg = {"role": "user", "content": message.text}
    groq_messages.append(current_msg)

    processing_msg = await message.reply_text(" Thinking...")

    try:
        groq_client = AsyncGroq(api_key=api_key)
        chat_completion = await groq_client.chat.completions.create(messages=groq_messages, model=model_id)
        bot_response = chat_completion.choices[0].message.content
        
        # --- PARSE JSON TOOLS ---
        json_matches = re.finditer(r'```json\n(.*?)\n```', bot_response, re.DOTALL)
        for match in json_matches:
            try:
                cmd_data = json.loads(match.group(1))
                action = cmd_data.get("action")
                
                if action == "set_reminder":
                    remind_time_str = cmd_data.get("time")
                    remind_dt = IST.localize(datetime.strptime(remind_time_str, "%Y-%m-%d %H:%M"))
                    await reminders_col.insert_one({"user_id": user_id, "task": cmd_data.get("task"), "remind_time": remind_dt, "status": "pending"})
                    bot_response = bot_response.replace(match.group(0), f"\n\n <i>Reminder saved for {remind_time_str}!</i>")
                
                elif action == "finance":
                    f_type, bank, amount = cmd_data.get("type"), cmd_data.get("bank", "Cash").title(), float(cmd_data.get("amount", 0))
                    wallet = await wallets_col.find_one({"_id": user_id})
                    banks = wallet.get("banks", {})
                    
                    if f_type == "setup":
                        banks[bank] = amount
                        msg_append = f"\n\n <i>{bank} setup with ₹{amount}</i>"
                    elif f_type == "income":
                        banks[bank] = banks.get(bank, 0) + amount
                        msg_append = f"\n\n <i>₹{amount} added to {bank}. New Bal: ₹{banks[bank]}</i>"
                    elif f_type == "expense":
                        banks[bank] = banks.get(bank, 0) - amount
                        msg_append = f"\n\n <i>₹{amount} spent from {bank}. Remaining: ₹{banks[bank]}</i>"
                    
                    await wallets_col.update_one({"_id": user_id}, {"$set": {"banks": banks}})
                    await transactions_col.insert_one({
                        "user_id": user_id, "type": f_type, "bank": bank, "amount": amount,
                        "category": cmd_data.get("category", "General"), "note": cmd_data.get("note", ""),
                        "date": datetime.now(IST)
                    })
                    bot_response = bot_response.replace(match.group(0), msg_append)
            except Exception as e:
                print(f"Tool Error: {e}")

        # Update Chat History
        await chats_col.update_one({"_id": active_chat_id}, {"$push": {"history": {"$each": [current_msg, {"role": "assistant", "content": bot_response}]}}})

        # Send HTML Response
        await processing_msg.edit_text(markdown_to_html(bot_response), parse_mode=pyrogram.enums.ParseMode.HTML)

    except Exception as e:
        await processing_msg.edit_text(f" **Error:**\n`{str(e)}`")

# -------------------------------------------------------------------
# Startup & Main Loop
# -------------------------------------------------------------------
async def check_mongo_connection():
    try:
        await db_client.admin.command('ping')
        print(" MongoDB Connected!")
    except Exception as e:
        print(f" MongoDB FAILED: {e}")
        sys.exit(1)

async def main():
    print(" Starting Bot Services...")
    await check_mongo_connection()
    await app.start()
    await send_startup_alert()

    asyncio.create_task(ping_other_bot())
    asyncio.create_task(reminder_worker())
    
    server = web.Application()
    server.router.add_get("/", health_check)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 8000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    print(f" Bot, Workers & Web Server Running on Port {port}!")
    await idle()
    await runner.cleanup()
    await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
