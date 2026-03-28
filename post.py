import os
import json
import re
import requests
import markdown
import telebot
import cloudinary
import cloudinary.uploader
import io
import time
from PIL import Image
from dotenv import load_dotenv
from telebot import apihelper

# .env load
load_dotenv()

# --- CONFIG ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID"))
API_URL = "https://api.detoxbyte.xyz/posts"
BOT_API_KEY = os.getenv("BOT_API_KEY")

# Cloudinary Setup
cloudinary.config(
  cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"),
  api_key = os.getenv("CLOUDINARY_API_KEY"),
  api_secret = os.getenv("CLOUDINARY_API_SECRET")
)

# Bot Initialize
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
user_state = {}

# --- SECURITY ---
def is_authorized(message):
    return message.from_user.id == ALLOWED_USER_ID

# --- IMAGE COMPRESSION (30% Reduction) ---
def compress_image(image_bytes):
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    output = io.BytesIO()
    img.save(output, format='JPEG', quality=70, optimize=True)
    return output.getvalue()

# --- AUTO SLUG GENERATOR ---
def create_slug(title):
    return re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')

# --- HANDLERS ---

@bot.message_handler(commands=['start', 'help', 'cancel', 'noimage'])
def handle_commands(message):
    if not is_authorized(message): return
    
    chat_id = message.chat.id
    cmd = message.text.split()[0]

    if cmd == '/cancel':
        user_state.pop(chat_id, None)
        bot.reply_to(message, "🔄 Process Reset! Nayi image, JSON, ya /noimage bhejiye.")
    
    elif cmd == '/noimage':
        user_state[chat_id] = {
            'coverImage': 'https://res.cloudinary.com/dax71u26t/image/upload/v1774632078/logo_1_mocton.jpg', # 🚀 Default Logo Fallback
            'json_buffer': ""
        }
        bot.reply_to(message, "⏩ Image Skipped (Default logo use hoga).\n\nAb JSON bhejien. Agar pura JSON ek message me aa gaya to automatically publish ho jayega. Bada ho to parts me bhej kar `/done` likhna.")
    
    else:
        text = ("🚀 **DetoxByte Publisher Pro**\n\n"
                "1️⃣ **Photo Bhejo**: Direct cover image ke liye.\n"
                "   *(Ya `/noimage` likho skip karne ke liye)*\n"
                "2️⃣ **JSON Bhejo**: Text paste karo (bada hai to parts mein bhej kar `/done` likho) ya `.json` file bhejo.\n\n"
                "💡 *Markdown Tables & Auto-slug supported!*")
        bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if not is_authorized(message): return
    
    chat_id = message.chat.id
    status = bot.reply_to(message, "⏳ Processing & Compressing Image...")

    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Compress logic
        compressed_data = compress_image(downloaded_file)
        
        # Cloudinary upload
        upload_res = cloudinary.uploader.upload(compressed_data)
        
        user_state[chat_id] = {
            'coverImage': upload_res['secure_url'],
            'json_buffer': ""
        }
        
        bot.edit_message_text("✅ **Image Ready!**\n\nAb JSON bhejien. Agar pura JSON ek message me aagya to automatic publish ho jayega. Kat gaya to next part bhej kar `/done` likhna.", chat_id, status.message_id, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Photo Error: {str(e)}")

@bot.message_handler(func=lambda m: m.chat.id in user_state, content_types=['text', 'document'])
def handle_json_input(message):
    chat_id = message.chat.id

    # Case 1: File Upload (.json or .txt)
    if message.document:
        if message.document.file_name.lower().endswith(('.json', '.txt')):
            file_info = bot.get_file(message.document.file_id)
            content = bot.download_file(file_info.file_path).decode('utf-8')
            user_state[chat_id]['json_buffer'] = content
            bot.reply_to(message, "📄 File detected! Processing...")
            submit_post(message)
        else:
            bot.reply_to(message, "❌ Sirf .json ya .txt file bhejien.")
        return

    # Case 2: Multi-part Text & Smart Detection
    if message.text:
        if message.text == '/done':
            submit_post(message)
        elif message.text == '/cancel':
            user_state.pop(chat_id, None)
            bot.reply_to(message, "Reset done.")
        elif not message.text.startswith('/'):
            user_state[chat_id]['json_buffer'] += message.text
            
            # 🚀 SMART JSON DETECTION
            try:
                raw_test = user_state[chat_id]['json_buffer'].strip()
                clean_test = raw_test.replace('```json', '').replace('```', '').strip()
                json.loads(clean_test) # If this doesn't throw error, JSON is complete!
                
                bot.reply_to(message, "✅ Complete JSON detected! Publishing now...")
                submit_post(message)
            except json.JSONDecodeError:
                # Still incomplete, wait for next part
                bot.reply_to(message, "📥 Added to buffer (JSON is incomplete). Next part bhejien ya `/done` likhien.")

def submit_post(message):
    chat_id = message.chat.id
    raw_json = user_state[chat_id]['json_buffer'].strip()
    
    if not raw_json:
        bot.reply_to(message, "❌ Error: JSON content khali hai!")
        return

    try:
        # Clean markdown code blocks
        clean_json = raw_json.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_json)
        
        # 🚀 FIX: Markdown to HTML conversion WITH TABLES SUPPORT
        md_content = data.get('content', '')
        html_body = markdown.markdown(md_content, extensions=['tables', 'fenced_code', 'nl2br'])

        # 🚀 FIX: Auto-slug if missing
        title = data.get('title', 'Untitled')
        slug = data.get('slug')
        if not slug:
            slug = create_slug(title)

        payload = {
            "title": title,
            "slug": slug,
            "category": data.get('category', 'blog'),
            "description": data.get('description'),
            "coverImage": user_state[chat_id]['coverImage'],
            "tags": data.get('tags', []),
            "content": html_body
        }

        headers = {"Content-Type": "application/json", "x-api-key": BOT_API_KEY}
        bot.send_message(chat_id, "🚀 Pushing to DetoxByte API...")
        
        resp = requests.post(API_URL, json=payload, headers=headers)

        if resp.status_code in [200, 201]:
            final_url = f"https://detoxbyte.xyz/{payload['category']}/{payload['slug']}"
            bot.send_message(chat_id, f"✅ **SUCCESSFULLY PUBLISHED!**\n\n🔗 [View Article]({final_url})", parse_mode="Markdown")
            user_state.pop(chat_id, None) # Success ke baad memory clear
        else:
            bot.send_message(chat_id, f"❌ **API Error ({resp.status_code}):**\n`{resp.text}`", parse_mode="Markdown")

    except json.JSONDecodeError as e:
        bot.reply_to(message, f"❌ JSON Syntax Error:\n`{str(e)}`\n\nCheck formatting and try again, or `/cancel`.", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Critical Error: {str(e)}")

# --- ANTI-CONFLICT POLLING ---
print("🤖 DetoxByte Publisher Bot is running...")

while True:
    try:
        # skip_pending=True purane latke hue messages ko ignore karega
        bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
    except apihelper.ApiTelegramException as e:
        if e.error_code == 409:
            print("⚠️ Conflict (409) detected. Waiting for old instance to die...")
            time.sleep(10) # 10 second wait karega
        else:
            print(f"❌ Telegram API Error: {e}")
            time.sleep(5)
    except Exception as e:
        print(f"❌ Critical Error: {e}")
        time.sleep(5)
