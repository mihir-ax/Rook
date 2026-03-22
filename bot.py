import os
import uuid
import asyncio
import sys
import time
import io
import re
import pytz
from datetime import datetime, timedelta
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

# Initialize Pyrogram App
app = Client("groq_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Initialize MongoDB
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["GroqBotDB"]
users_col = db["users"]
chats_col = db["chats"]
reminders_col = db["reminders"]
todos_col = db["todos"]
polls_col = db["polls"] # For tracking active polls

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
    
    # SYSTEM PROMPT INJECTION (The Secret Sauce)
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
            # Find due reminders
            due_reminders = await reminders_col.find({"time": {"$lte": now}}).to_list(None)
            
            for r in due_reminders:
                # Send alert to user
                await app.send_message(
                    r["user_id"], 
                    f"⏰ **AUTO REMINDER ALARM!**\n\n📌 {r['message']}\n\n_Set by AI at your request._",
                    parse_mode=enums.ParseMode.MARKDOWN
                )
                # Delete after sending
                await reminders_col.delete_one({"_id": r["_id"]})
                
        except Exception as e:
            print(f"Reminder loop error: {e}")
        
        await asyncio.sleep(20) # Check every 20 seconds

# -------------------------------------------------------------------
# Telegram Commands (Setup, Chat, Todo)
# -------------------------------------------------------------------
@app.on_message(filters.command("start") & admin_only)
async def start_cmd(client, message):
    await get_user_data(message.from_user.id)
    text = (
        "🤖 **Welcome to Groq AI Bot PRO!**\n\n"
        "I am now an advanced Assistant. I can set reminders, create polls, and manage your to-dos.\n\n"
        "**Commands:**\n"
        "/set_api <api_key> - Set Groq API\n"
        "/newchat - Start fresh chat\n"
        "/showchat - Manage chats\n"
        "/todo - View your pending tasks\n"
        "/history - Get full chat text\n"
    )
    await message.reply_text(text)

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

# (Keeping standard commands minimal here for space, assume /set_api, /newchat, /showchat exist as before)
@app.on_message(filters.command("newchat") & admin_only)
async def new_chat(client, message):
    chat_id = await create_new_chat(message.from_user.id)
    await message.reply_text("🆕 **Naya chat start ho gaya!** Context reset.")

# -------------------------------------------------------------------
# Handle Poll Votes (Feedback to AI)
# -------------------------------------------------------------------
@app.on_poll_answer()
async def handle_poll_vote(client, poll_answer):
    # Only works for non-anonymous polls
    poll_id = poll_answer.poll_id
    user_id = poll_answer.user.id
    
    db_poll = await polls_col.find_one({"poll_id": poll_id})
    if not db_poll:
        return

    selected_option_idx = poll_answer.option_ids[0]
    option_text = db_poll["options"][selected_option_idx]

    user = await get_user_data(user_id)
    active_chat = user.get("active_chat")
    
    if active_chat:
        # Silently inject the user's vote into the AI's context
        system_injection = {
            "role": "system", 
            "content": f"[SYSTEM ALERT: The user voted '{option_text}' in the poll '{db_poll['question']}']"
        }
        await chats_col.update_one(
            {"_id": active_chat},
            {"$push": {"history": system_injection}}
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
                # Assuming AI returns YYYY-MM-DD HH:MM:SS
                rem_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                rem_time = ist_tz.localize(rem_time) # Convert to IST aware
                
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
                
                # Send Poll
                sent_poll = await app.send_poll(
                    chat_id=message.chat.id,
                    question=question,
                    options=options[:10], # Max 10 options in telegram
                    is_anonymous=is_anon
                )
                # Track poll in DB
                await polls_col.insert_one({
                    "poll_id": sent_poll.poll.id, 
                    "question": question, 
                    "options": options[:10]
                })
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
            # Find closest matching task and mark complete
            await todos_col.update_one({"user_id": user_id, "task": {"$regex": task, "$options": "i"}}, {"$set": {"status": "completed"}})
            actions_taken.append(f"✅ Marked done: {task}")
            clean_response = re.sub(r'\[TODO_DONE:.*?\]', '', clean_response)

        # Format Actions Info for User
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
                        {"role": "assistant", "content": bot_response} # Save original so AI remembers tags
                    ]
                }
            }}
        )

        try:
            await processing_msg.edit_text(final_text, parse_mode=enums.ParseMode.HTML)
        except Exception:
            # Fallback if HTML parser fails (due to unclosed tags by AI)
            await processing_msg.edit_text(clean_response.strip() + action_text)

    except Exception as e:
        await processing_msg.edit_text(f"❌ **Error aagaya bhai:**\n`{str(e)}`")


# -------------------------------------------------------------------
# Web Server (Health Check)
# -------------------------------------------------------------------
async def health_check(request):
    return web.Response(text="Groq AI Bot PRO is ALIVE and running! 🚀")

# -------------------------------------------------------------------
# Main entry point
# -------------------------------------------------------------------
async def main():
    print("🚀 Starting Bot, Web Server & Reminder Loops...")
    
    await app.start()
    print("✅ Telegram Bot is Online!")

    # Start Auto Reminder Background Task
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
