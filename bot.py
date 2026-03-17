import os
import uuid
import asyncio
import sys  
from datetime import datetime
from dotenv import load_dotenv
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from groq import AsyncGroq
from aiohttp import web  # Web server ke liye import

# Load Environment Variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

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

# --- Web Server (Render & Pinger ko khush karne ke liye) ---
async def health_check(request):
    return web.Response(text="Groq AI Bot is ALIVE and running! 🚀")

# --- Helper Functions ---

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

# --- Commands ---

@app.on_message(filters.command("start") & admin_only)
async def start_cmd(client, message):
    await get_user_data(message.from_user.id)
    text = (
        "🤖 **Welcome to Groq AI Bot!**\n\n"
        "Sirf Admin (Aap) mujhe use kar sakte hain.\n\n"
        "**Setup Commands:**\n"
        "`/set_api <api_key>` - Set apna Groq API\n"
        "`/set_model <model_id>` - Set Model (default: llama3-8b-8192)\n\n"
        "**Chat Commands:**\n"
        "`/newchat` - Start fresh chat\n"
        "`/showchat` - Manage chats (Select/Delete)\n"
        "`/system_prompt <text>` - Set system prompt for current chat\n"
        "`/renamechat <name>` - Active chat ka naam change karein\n"
        "`/system_prompt delete` - Remove system prompt\n"
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
        return await message.reply_text("Bhai koi active chat nahi hai. Pehle `/newchat` kar ya `/showchat` se select kar!")

    if len(message.command) < 2:
        return await message.reply_text("Bhai naya naam bhi toh daal:\n**Example:** `/renamechat Python Project`")

    new_title = message.text.split(" ", 1)[1]
    await chats_col.update_one({"_id": active_chat}, {"$set": {"title": new_title}})
    await message.reply_text(f"✅ Active chat ka naam update ho gaya!\nNaya naam: **{new_title}**")

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

# --- Main AI Chat Handler ---

@app.on_message(filters.text & ~filters.command(["start", "set_api", "set_model", "newchat", "showchat", "renamechat", "system_prompt"]) & admin_only)
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

async def check_mongo_connection():
    print("🔄 Checking MongoDB Connection...")
    try:
        # Pinging the database
        await db_client.admin.command('ping')
        print("✅ MongoDB Connected Successfully! (IP is Whitelisted)")
        return True
    except Exception as e:
        print(f"❌ MongoDB Connection FAILED!")
        print(f"⚠️ Error: {e}")
        print("👉 Hint: Apna MONGO_URI check kar aur MongoDB Atlas me Network Access -> '0.0.0.0/0' (Allow Anywhere) set kar.")
        sys.exit(1)  # Agar DB connect nahi hua toh script yahin rok dega

# --- DUAL RUNNER (Telegram + Web Server) ---
async def main():
    print("🚀 Starting Bot & Web Server...")
    
    # Sabse pehle MongoDB check karega
    await check_mongo_connection()
    
    # 1. Start Telegram Bot
    await app.start()
    print("✅ Telegram Bot is Online!")

    # 2. Start Web Server (Render ke liye + Tere dusre bot ke Pinger ke liye)
    server = web.Application()
    server.router.add_get("/", health_check)
    runner = web.AppRunner(server)
    await runner.setup()
    
    # Render PORT environment variable deta hai, varna 8000 pe run hoga
    port = int(os.environ.get("PORT", 8000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Web Server is running on port {port}!")

    try:
        # 3. Idle rakhna taaki script band na ho
        await idle()
    except Exception as e:
        print(f"⚠️ Bot crashed: {e}")
    finally:
        # 4. Stop properly if script is killed
        print("🛑 Stopping services...")
        await app.stop()
        await runner.cleanup()
        print("✅ Gracefully shut down.")

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(main())
