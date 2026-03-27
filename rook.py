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
loans_col = db["loans"]
goals_col = db["goals"]

# Custom Filter for Admin Only
async def is_admin(_, __, message):
    return message.from_user and message.from_user.id == ADMIN_ID
admin_only = filters.create(is_admin)

# -------------------------------------------------------------------
# Helper: Markdown to HTML Parser
# -------------------------------------------------------------------
def markdown_to_html(text):
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.*?)\*', r'<i>\1</i>', text)
    text = re.sub(r'```(.*?)```', r'<pre><code>\1</code></pre>', text, flags=re.DOTALL)
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
    text = re.sub(r'~~(.*?)~~', r'<s>\1</s>', text)
    return text

# -------------------------------------------------------------------
# Background Tasks (Web Server, Pinger, Reminders)
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
        bot_name = me.mention if hasattr(me, 'mention') else f"@{me.username}" if me.username else me.first_name
        await send_alerify_alert("🚀 Groq Chat Bot Started", f"<b>Groq AI Bot is now online!</b>\n\n• {bot_name}", f"<h2>Bot Started</h2><p>{bot_name}</p>")
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
        except Exception: pass
        await asyncio.sleep(60)

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
# DB Helpers for Users & Chats
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
        "_id": chat_id, "user_id": user_id,
        "title": f"Chat {datetime.now(IST).strftime('%d-%m %H:%M')}",
        "system_prompt": None, "history": [], "created_at": datetime.now(IST)
    }
    await chats_col.insert_one(chat_data)
    await users_col.update_one({"_id": user_id}, {"$set": {"active_chat": chat_id}})
    return chat_id

# -------------------------------------------------------------------
# ALL COMMANDS (Chat Management + Finance)
# -------------------------------------------------------------------
@app.on_message(filters.command("start") & admin_only)
async def start_cmd(client, message):
    await get_user_data(message.from_user.id)
    text = (
        "🤖 **Welcome to the Ultimate JARVIS!**\n\n"
        "**Setup:**\n"
        "/set_api <api_key> | /set_model <model_id>\n\n"
        "**Chat Management:**\n"
        "/newchat - Start fresh chat\n"
        "/showchat - Manage & Delete chats\n"
        "/renamechat <name> - Rename active chat\n"
        "/system_prompt <text> - Set prompt for this chat\n"
        "/history - Show full chat history\n\n"
        "**Finance & Tools:**\n"
        "/finance - Dashboard of Wealth, Udhaar & Goals"
    )
    await message.reply_text(text)

@app.on_message(filters.command("set_api") & admin_only)
async def set_api(client, message):
    if len(message.command) < 2: return await message.reply_text("Bhai API key daal: `/set_api gsk_xxx...`")
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
    await message.reply_text("🆕 **Naya chat start ho gaya!** Ab jo bhejoge fresh context hoga.")

@app.on_message(filters.command("renamechat") & admin_only)
async def rename_chat(client, message):
    user = await get_user_data(message.from_user.id)
    active_chat = user.get("active_chat")
    if not active_chat: return await message.reply_text("Bhai koi active chat nahi hai.")
    if len(message.command) < 2: return await message.reply_text("Naya naam daal: `/renamechat Project Alpha`")
    new_title = message.text.split(" ", 1)[1]
    await chats_col.update_one({"_id": active_chat}, {"$set": {"title": new_title}})
    await message.reply_text(f"✅ Active chat renamed to: **{new_title}**")

@app.on_message(filters.command("system_prompt") & admin_only)
async def sys_prompt(client, message):
    user = await get_user_data(message.from_user.id)
    active_chat = user.get("active_chat")
    if not active_chat: return await message.reply_text("Pehle `/newchat` kar bhai!")
    if len(message.command) < 2:
        chat = await chats_col.find_one({"_id": active_chat})
        return await message.reply_text(f"📝 **Current Prompt:**\n`{chat.get('system_prompt', 'None')}`")
    prompt_text = message.text.split(" ", 1)[1]
    if prompt_text.lower() == "delete":
        await chats_col.update_one({"_id": active_chat}, {"$set": {"system_prompt": None}})
        return await message.reply_text("🗑 System prompt deleted.")
    await chats_col.update_one({"_id": active_chat}, {"$set": {"system_prompt": prompt_text}})
    await message.reply_text(f"✅ System Prompt set!")

@app.on_message(filters.command("showchat") & admin_only)
async def show_chats(client, message):
    chats = await chats_col.find({"user_id": message.from_user.id}).sort("created_at", -1).to_list(10)
    if not chats: return await message.reply_text("Koi history nahi hai bro.")
    user = await get_user_data(message.from_user.id)
    active_chat = user.get("active_chat")
    buttons = []
    for chat in chats:
        title = f"🟢 {chat['title']} (Active)" if chat['_id'] == active_chat else f"📁 {chat['title']}"
        buttons.append([InlineKeyboardButton(title, callback_data=f"select_{chat['_id']}")])
        buttons.append([InlineKeyboardButton("❌ Delete", callback_data=f"del_{chat['_id']}")])
    await message.reply_text("👇 **Manage your chats:**", reply_markup=InlineKeyboardMarkup(buttons))

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
    if not active_chat: return await message.reply_text("❌ Koi active chat nahi hai.")
    chat = await chats_col.find_one({"_id": active_chat})
    if not chat: return await message.reply_text("❌ Chat nahi mila.")
    
    history = chat.get("history", [])
    if not history: return await message.reply_text("📭 Chat empty hai.")
    
    lines = [f"**Chat Title:** {chat['title']}\n\n**💬 Conversation:**\n"]
    for msg in history:
        lines.append(f"**{msg['role'].capitalize()}:** {msg['content']}\n")
    
    full_text = "\n".join(lines)
    if len(full_text) <= 4096:
        await message.reply_text(full_text)
    else:
        file_data = io.BytesIO(full_text.encode('utf-8'))
        file_data.name = f"chat_history.txt"
        await message.reply_document(document=file_data, caption="📜 **Poori baatcheet**")

@app.on_message(filters.command("finance") & admin_only)
async def finance_dashboard(client, message):
    user_id = message.from_user.id
    wallet = await wallets_col.find_one({"_id": user_id})
    if not wallet: return await message.reply_text("Kuch data nahi hai bhai.")
    
    banks = wallet.get("banks", {})
    total = sum(banks.values())
    msg = f"📊 <b>ULTIMATE FINANCE DASHBOARD</b>\n\n💰 <b>Liquid Net Worth:</b> ₹{total:,.2f}\n\n🏦 <b>Accounts:</b>\n"
    for b, bal in banks.items(): msg += f"• {b}: ₹{bal:,.2f}\n"
    
    loans = await loans_col.find({"user_id": user_id}).to_list(None)
    if loans:
        msg += "\n🤝 <b>Udhaar / Karza:</b>\n"
        for l in loans:
            if l['amount'] > 0: msg += f"🟢 {l['person']} owes you: ₹{l['amount']}\n"
            elif l['amount'] < 0: msg += f"🔴 You owe {l['person']}: ₹{abs(l['amount'])}\n"

    goals = await goals_col.find({"user_id": user_id}).to_list(None)
    if goals:
        msg += "\n🎯 <b>Active Goals:</b>\n"
        for g in goals:
            pct = (g['saved'] / g['target']) * 100 if g['target'] > 0 else 0
            msg += f"• {g['name']}: ₹{g['saved']} / ₹{g['target']} ({pct:.1f}%)\n"
            
    await message.reply_text(msg, parse_mode=pyrogram.enums.ParseMode.HTML)

# -------------------------------------------------------------------
# MAIN AI ENGINE (Jarvis + Tools)
# -------------------------------------------------------------------
@app.on_message(filters.text & ~filters.command(["start", "set_api", "set_model", "newchat", "showchat", "renamechat", "system_prompt", "history", "finance"]) & admin_only)
async def chat_handler(client, message):
    user_id = message.from_user.id
    user = await get_user_data(user_id)
    api_key, model_id = user.get("groq_api"), user.get("model_id")

    if not api_key: return await message.reply_text("Bhai API key set kar le pehle: `/set_api KEY`")

    active_chat_id = user.get("active_chat")
    if not active_chat_id: active_chat_id = await create_new_chat(user_id)

    chat_doc = await chats_col.find_one({"_id": active_chat_id})
    history = chat_doc.get("history", [])
    user_sys_prompt = chat_doc.get("system_prompt", "")
    
    # --- FINANCE AGGREGATION FOR AI CONTEXT ---
    now = datetime.now(IST)
    user_wallet = await wallets_col.find_one({"_id": user_id}) or {"banks": {"Cash": 0}}
    current_balances = json.dumps(user_wallet.get("banks", {}))
    
    loans = await loans_col.find({"user_id": user_id, "amount": {"$ne": 0}}).to_list(None)
    loans_str = json.dumps([{l['person']: l['amount']} for l in loans])
    
    goals = await goals_col.find({"user_id": user_id}).to_list(None)
    goals_str = json.dumps([{g['name']: f"Saved: {g['saved']}/{g['target']}"} for g in goals])

    all_txs = await transactions_col.find({"user_id": user_id}).sort("date", -1).to_list(2000)
    this_month_inc, this_month_exp = 0, 0
    biz_pnl = {}
    
    for t in all_txs:
        if t['date'].month == now.month and t['date'].year == now.year:
            if t['type'] == 'income': this_month_inc += t['amount']
            elif t['type'] == 'expense': this_month_exp += t['amount']
        
        biz = t.get('source_or_business', 'General')
        if biz != 'General':
            if biz not in biz_pnl: biz_pnl[biz] = {"income": 0, "expense": 0}
            if t['type'] == 'income': biz_pnl[biz]["income"] += t['amount']
            elif t['type'] == 'expense': biz_pnl[biz]["expense"] += t['amount']

    biz_pnl_str = json.dumps({b: v["income"] - v["expense"] for b, v in biz_pnl.items()})
    recent_tx_str = "\n".join([f"[{t['date'].strftime('%Y-%m-%d')}] {t['type'].upper()} | ₹{t['amount']} | Biz: {t.get('source_or_business','None')} | Cat: {t['category']}" for t in all_txs[:50]])

    # --- THE SYSTEM PROMPT ---
    current_time = now.strftime("%A, %d %B %Y, %I:%M %p")
    sys_prompt = (
        f"You are J.A.R.V.I.S, an elite AI Assistant & Financial Manager.\n"
        f"Current Date/Time: {current_time} (IST timezone).\n\n"
        
        f"=== LIVE FINANCIAL REPORT ===\n"
        f"Bank Balances: {current_balances}\n"
        f"Udhaar/Loans (Positive=Owes me, Negative=I owe them): {loans_str}\n"
        f"Active Goals: {goals_str}\n"
        f"This Month -> Income: {this_month_inc}, Expense: {this_month_exp}\n"
        f"Business/Project Lifetime PnL: {biz_pnl_str}\n"
        f"Last 50 Transactions:\n{recent_tx_str}\n\n"
        
        f"=== USER CHAT SYSTEM PROMPT ===\n"
        f"{user_sys_prompt}\n\n"
        
        f"=== ACTION TOOLS (JSON OUTPUTS) ===\n"
        f"If the user commands an action, output EXACTLY the relevant JSON block at the very end of your reply. Only output JSON if an action is required.\n\n"
        
        f"1. **Reminder:**\n```json\n{{\"action\": \"reminder\", \"time\": \"YYYY-MM-DD HH:MM\", \"task\": \"details\"}}\n```\n"
        f"2. **Finance:**\n```json\n{{\"action\": \"finance\", \"type\": \"expense|income|setup\", \"amount\": 100, \"bank\": \"HDFC\", \"category\": \"Food\", \"source_or_business\": \"General\", \"note\": \"...\"}}\n```\n"
        f"3. **Udhaar/Loan:**\n```json\n{{\"action\": \"loan\", \"type\": \"give|take|receive_repay|pay_repay\", \"person\": \"Raju\", \"amount\": 500, \"bank\": \"Cash\"}}\n```\n"
        f"4. **Goals:**\n```json\n{{\"action\": \"goal\", \"type\": \"create|add_fund\", \"goal_name\": \"Macbook\", \"amount\": 1000, \"target\": 100000, \"bank\": \"HDFC\"}}\n```\n"
    )

    groq_messages = [{"role": "system", "content": sys_prompt}]
    groq_messages.extend(history[-15:]) # Keep last 15 messages for context
    current_msg = {"role": "user", "content": message.text}
    groq_messages.append(current_msg)

    processing_msg = await message.reply_text("⏳ Processing...")

    try:
        groq_client = AsyncGroq(api_key=api_key)
        chat_completion = await groq_client.chat.completions.create(messages=groq_messages, model=model_id)
        bot_response = chat_completion.choices[0].message.content
        
        # --- TOOL EXECUTOR ---
        json_matches = list(re.finditer(r'```json\n(.*?)\n```', bot_response, re.DOTALL))
        for match in json_matches:
            try:
                cmd = json.loads(match.group(1))
                action = cmd.get("action")
                msg_append = ""
                
                wallet = await wallets_col.find_one({"_id": user_id}) or {"_id": user_id, "banks": {"Cash": 0}}
                banks = wallet.get("banks", {})
                
                if action == "reminder":
                    dt = IST.localize(datetime.strptime(cmd.get("time"), "%Y-%m-%d %H:%M"))
                    await reminders_col.insert_one({"user_id": user_id, "task": cmd.get("task"), "remind_time": dt, "status": "pending"})
                    msg_append = f"\n\n⏰ <i>Reminder set!</i>"
                
                elif action == "finance":
                    f_type, bank, amt = cmd.get("type"), cmd.get("bank", "Cash").title(), float(cmd.get("amount", 0))
                    biz = cmd.get("source_or_business", "General")
                    
                    if f_type == "setup": banks[bank] = amt
                    elif f_type == "income": banks[bank] = banks.get(bank, 0) + amt
                    elif f_type == "expense": banks[bank] = banks.get(bank, 0) - amt
                    
                    await transactions_col.insert_one({
                        "user_id": user_id, "type": f_type, "bank": bank, "amount": amt,
                        "category": cmd.get("category", "General"), "source_or_business": biz,
                        "note": cmd.get("note", ""), "date": datetime.now(IST)
                    })
                    msg_append = f"\n\n💸 <i>Finance logged in {bank}</i>"

                elif action == "loan":
                    l_type, person, amt, bank = cmd.get("type"), cmd.get("person").title(), float(cmd.get("amount", 0)), cmd.get("bank", "Cash").title()
                    
                    if l_type in ["give", "pay_repay"]: banks[bank] = banks.get(bank, 0) - amt
                    elif l_type in ["take", "receive_repay"]: banks[bank] = banks.get(bank, 0) + amt
                    
                    loan_doc = await loans_col.find_one({"user_id": user_id, "person": person}) or {"person": person, "amount": 0}
                    curr_loan = loan_doc.get("amount", 0)
                    
                    if l_type in ["give", "receive_repay"]: curr_loan += amt  
                    elif l_type in ["take", "pay_repay"]: curr_loan -= amt    
                    
                    await loans_col.update_one({"user_id": user_id, "person": person}, {"$set": {"amount": curr_loan}}, upsert=True)
                    msg_append = f"\n\n🤝 <i>Udhaar updated for {person}</i>"

                elif action == "goal":
                    g_type, name, bank = cmd.get("type"), cmd.get("goal_name").title(), cmd.get("bank", "Cash").title()
                    if g_type == "create":
                        await goals_col.insert_one({"user_id": user_id, "name": name, "target": float(cmd.get("target", 0)), "saved": 0})
                        msg_append = f"\n\n🎯 <i>Goal '{name}' created!</i>"
                    elif g_type == "add_fund":
                        amt = float(cmd.get("amount", 0))
                        banks[bank] = banks.get(bank, 0) - amt
                        await goals_col.update_one({"user_id": user_id, "name": name}, {"$inc": {"saved": amt}})
                        msg_append = f"\n\n📈 <i>₹{amt} added to '{name}'</i>"

                if action in ["finance", "loan", "goal"]:
                    await wallets_col.update_one({"_id": user_id}, {"$set": {"banks": banks}}, upsert=True)

                bot_response = bot_response.replace(match.group(0), msg_append)
            except Exception as e: print(f"Tool Error: {e}")

        # Remove extra blank lines generated by stripping JSON
        bot_response = bot_response.strip()

        # Save Chat History
        await chats_col.update_one({"_id": active_chat_id}, {"$push": {"history": {"$each": [current_msg, {"role": "assistant", "content": bot_response}]}}})
        
        # Send Reply
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
    print(" Booting Up...")
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
    
    print(f" Running on Port {port}!")
    await idle()
    await runner.cleanup()
    await app.stop()

# if __name__ == "__main__":
#     loop = asyncio.get_event_loop()
#     loop.run_until_complete(main())
