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

# .env load
load_dotenv()

# --- CONFIG ---
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
# Memory for large text and image
user_state = {}

# --- SECURITY ---
def is_authorized(message):
    return message.from_user.id == ALLOWED_USER_ID

# --- IMAGE COMPRESSION ---
def compress_image(image_bytes):
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    output = io.BytesIO()
    # 70% quality = 30% approx compression
    img.save(output, format='JPEG', quality=70, optimize=True)
    return output.getvalue()

# --- HANDLERS ---

@bot.message_handler(commands=['start', 'help', 'cancel'])
def commands_handler(message):
    if not is_authorized(message): return
    
    if message.text == '/cancel':
        user_state.pop(message.chat.id, None)
        bot.reply_to(message, "✅ Process Reset! Nayi image bhejiye.")
    else:
        bot.reply_to(message, "🚀 **DetoxByte Publisher**\n\n1. Photo bhejo\n2. JSON text bhejte raho\n3. Last mein `/done` likho\n(Ya direct .json file bhejo)", parse_mode="Markdown")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if not is_authorized(message): return
    
    chat_id = message.chat.id
    wait_msg = bot.reply_to(message, "⏳ Processing & Compressing Image...")

    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Compress
        final_img = compress_image(downloaded_file)
        
        # Cloudinary
        res = cloudinary.uploader.upload(final_img)
        
        user_state[chat_id] = {
            'coverImage': res['secure_url'],
            'json_buffer': ""
        }
        
        bot.edit_message_text("✅ Image Uploaded! Ab JSON bhejiye. Agar bada hai to parts mein bhej kar last mein `/done` likhiye.", chat_id, wait_msg.message_id)
    except Exception as e:
        bot.reply_to(message, f"❌ Image Error: {str(e)}")

@bot.message_handler(func=lambda m: m.chat.id in user_state, content_types=['text', 'document'])
def handle_json_logic(message):
    chat_id = message.chat.id

    # If it's a file
    if message.document:
        if message.document.file_name.lower().endswith(('.json', '.txt')):
            file_info = bot.get_file(message.document.file_id)
            content = bot.download_file(file_info.file_path).decode('utf-8')
            user_state[chat_id]['json_buffer'] = content
            process_final_post(message)
        else:
            bot.reply_to(message, "❌ Sirf .json ya .txt file bhejien.")
        return

    # If it's text (Multiple parts handling)
    if message.text:
        if message.text == '/done':
            process_final_post(message)
        elif message.text == '/cancel':
            user_state.pop(chat_id, None)
            bot.reply_to(message, "Reset!")
        else:
            # Append parts
            user_state[chat_id]['json_buffer'] += message.text
            bot.reply_to(message, "📥 Buffer mein add ho gaya. Next part bhejien ya `/done` likhien.")

def process_final_post(message):
    chat_id = message.chat.id
    raw_text = user_state[chat_id]['json_buffer'].strip()
    
    if not raw_text:
        bot.reply_to(message, "❌ JSON khali hai!")
        return

    try:
        clean_json = raw_text.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_json)
        
        # MD to HTML
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
        bot.send_message(chat_id, "🚀 Pushing to API...")
        
        api_res = requests.post(API_URL, json=payload, headers=headers)

        if api_res.status_code in [200, 201]:
            url = f"https://detoxbyte.xyz/{payload['category']}/{payload['slug']}"
            bot.send_message(chat_id, f"✅ **Published!**\n\n🔗 [Link]({url})", parse_mode="Markdown")
            user_state.pop(chat_id, None) # Clear memory
        else:
            bot.send_message(chat_id, f"❌ API Error: {api_res.text}")

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}\n\nAap JSON check karke dobara bhej sakte hain.")

# Bot Start
print("🤖 Bot is active...")
bot.infinity_polling(skip_pending=True)
