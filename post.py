import os
import json
import requests
import markdown
import telebot
import cloudinary
import cloudinary.uploader
import io
from PIL import Image
from dotenv import load_dotenv

# .env file load karo
load_dotenv()

# ── 1. CONFIGURATION ──
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID"))
API_URL = "https://api.detoxbyte.xyz/posts"
BOT_API_KEY = os.getenv("BOT_API_KEY")

cloudinary.config(
  cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"),
  api_key = os.getenv("CLOUDINARY_API_KEY"),
  api_secret = os.getenv("CLOUDINARY_API_SECRET")
)

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# User state to store data temporarily
# Structure: { chat_id: { 'coverImage': url, 'json_buffer': "" } }
user_state = {}

# ── 2. HELPERS ──

def is_authorized(message):
    if message.from_user.id != ALLOWED_USER_ID:
        bot.reply_to(message, "⛔ Access Denied!")
        return False
    return True

def compress_image(image_bytes):
    """Image ko compress karta hai (Quality 70% = 30% reduction approx)"""
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    
    output = io.BytesIO()
    img.save(output, format='JPEG', quality=70, optimize=True)
    return output.getvalue()

# ── 3. BOT LOGIC ──

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if is_authorized(message):
        help_text = (
            "🚀 **DetoxByte Publisher Pro**\n\n"
            "1️⃣ **Photo Bhejo**: Direct cover image upload karo.\n"
            "2️⃣ **JSON Bhejo**: Text paste karo ya `.json`/`.txt` file bhejo.\n"
            "   - Agar content bada hai, to parts mein bhej kar last mein `/done` likho.\n"
            "3️⃣ **Cancel**: `/cancel` likho reset karne ke liye."
        )
        bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['cancel'])
def cancel_process(message):
    user_state.pop(message.chat.id, None)
    bot.reply_to(message, "✅ Process reset ho gaya hai. Nayi image bhej sakte hain.")

# --- STEP 1: Handle Image ---
@bot.message_handler(content_types=['photo'])
def handle_image(message):
    if not is_authorized(message): return
    
    chat_id = message.chat.id
    msg = bot.reply_to(message, "⏳ Image compress aur upload ho rahi hai...")

    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # Compression
        compressed_file = compress_image(downloaded_file)

        # Upload to Cloudinary
        upload_result = cloudinary.uploader.upload(compressed_file)
        image_url = upload_result['secure_url']

        # Initializing state for this user
        user_state[chat_id] = {
            'coverImage': image_url,
            'json_buffer': ""
        }

        instruction = (
            "✅ **Image Uploaded!**\n\n"
            "📝 Ab **JSON Payload** bhejo.\n"
            "💡 *Note:* Agar JSON bada hai, to use multi-parts mein bhej sakte ho. Jab poora paste ho jaye, tab `/done` likho.\n"
            "Ya fir direct `.json` file upload karo."
        )
        bot.edit_message_text(instruction, chat_id, msg.message_id, parse_mode="Markdown")
        
    except Exception as e:
        bot.reply_to(message, f"❌ Image Error: {str(e)}")

# --- STEP 2: Handle JSON Text (Multi-part) or Files ---
@bot.message_handler(func=lambda m: m.chat.id in user_state, content_types=['text', 'document'])
def handle_json_input(message):
    chat_id = message.chat.id

    # If it's a command, ignore this handler
    if message.text and message.text.startswith('/'):
        if message.text == '/done':
            process_final_payload(message)
        elif message.text == '/cancel':
            cancel_process(message)
        return

    # Handle Document (File)
    if message.document:
        file_name = message.document.file_name.lower()
        if file_name.endswith(('.json', '.txt')):
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            user_state[chat_id]['json_buffer'] = downloaded_file.decode('utf-8')
            bot.reply_to(message, "📄 File received! Processing now...")
            process_final_payload(message)
        else:
            bot.reply_to(message, "❌ Sirf .json ya .txt file bhejien.")
        return

    # Handle Text (Append to buffer for multi-part messages)
    if message.text:
        user_state[chat_id]['json_buffer'] += message.text
        bot.reply_to(message, "📥 Part received. Aur bhejien ya `/done` likhein.", parse_mode="Markdown")

# --- STEP 3: Final Process & API Call ---
def process_final_payload(message):
    chat_id = message.chat.id
    raw_data = user_state[chat_id]['json_buffer'].strip()

    if not raw_data:
        bot.reply_to(message, "❌ Buffer khali hai. JSON bhejien pehle.")
        return

    try:
        # Clean JSON string
        clean_json = raw_data.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_json)

        # Markdown to HTML
        html_content = markdown.markdown(data.get('content', ''))

        payload = {
            "title": data.get('title'),
            "slug": data.get('slug'),
            "category": data.get('category', 'blog'),
            "description": data.get('description'),
            "coverImage": user_state[chat_id]['coverImage'],
            "tags": data.get('tags', []),
            "content": html_content
        }

        headers = {"Content-Type": "application/json", "x-api-key": BOT_API_KEY}
        bot.send_message(chat_id, "🚀 Posting to DetoxByte API...")
        
        res = requests.post(API_URL, json=payload, headers=headers)

        if res.status_code in [200, 201]:
            post_url = f"https://detoxbyte.xyz/{payload['category']}/{payload['slug']}"
            bot.send_message(chat_id, f"✅ **SUCCESS!**\n\n🔗 [Live Link]({post_url})", parse_mode="Markdown", disable_web_page_preview=False)
            user_state.pop(chat_id, None) # Clear memory after success
        else:
            bot.send_message(chat_id, f"❌ **API Error ({res.status_code}):**\n{res.text}")
            # Hum yahan clear nahi kar rahe taaki user JSON theek karke `/done` firse bol sake

    except json.JSONDecodeError as e:
        bot.reply_to(message, f"❌ **Invalid JSON:**\nCheck quotes or commas. Error: {str(e)}\n\n"
                              "Aap poora JSON firse bhej sakte hain (buffer reset karne ke liye `/cancel` karein).")
    except Exception as e:
        bot.reply_to(message, f"❌ Critical Error: {str(e)}")

# START BOT
print("🤖 DetoxByte Multi-Part Publisher Bot is running...")
bot.infinity_polling()
