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
user_state = {}

# ── 2. HELPERS ──

def is_authorized(message):
    if message.from_user.id != ALLOWED_USER_ID:
        bot.reply_to(message, "⛔ Access Denied!")
        return False
    return True

def compress_image(image_bytes):
    """Image ko compress karta hai (approx 30% reduction)"""
    img = Image.open(io.BytesIO(image_bytes))
    # Convert to RGB if necessary (to save as JPEG)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    
    output = io.BytesIO()
    # Quality 70 matlab 30% compression
    img.save(output, format='JPEG', quality=70, optimize=True)
    return output.getvalue()

# ── 3. BOT LOGIC ──

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if is_authorized(message):
        bot.reply_to(message, "🚀 **DetoxByte Publisher Pro**\n\n"
                              "1. Direct photo bhejo cover image ke liye.\n"
                              "2. Uske baad JSON text ya file (.json/.txt) bhejo.\n"
                              "3. /cancel likho reset karne ke liye.", parse_mode="Markdown")

@bot.message_handler(commands=['cancel'])
def cancel(message):
    user_state.pop(message.chat.id, None)
    bot.reply_to(message, "✅ Process cancelled. Nayi image bhejiye.")

# Direct image handle karne ke liye (ya /newpost ke baad)
@bot.message_handler(content_types=['photo'])
def handle_image(message):
    if not is_authorized(message): return
    
    chat_id = message.chat.id
    msg = bot.reply_to(message, "⏳ Processing & Compressing image...")

    try:
        # Get high res photo
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # Compression
        compressed_file = compress_image(downloaded_file)

        # Upload to Cloudinary
        upload_result = cloudinary.uploader.upload(compressed_file)
        image_url = upload_result['secure_url']

        user_state[chat_id] = {'coverImage': image_url}

        help_text = ("✅ **Image Uploaded & Compressed!**\n\n"
                     "📝 Ab **JSON Payload** bhejo (Text likho ya `.json` / `.txt` file upload karo).")
        
        bot.edit_message_text(help_text, chat_id, msg.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(message, process_json_input)

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

def process_json_input(message):
    chat_id = message.chat.id
    
    if message.text == '/cancel':
        cancel(message)
        return

    raw_json = ""

    try:
        # Check if it's a file
        if message.document:
            file_name = message.document.file_name.lower()
            if file_name.endswith(('.json', '.txt')):
                file_info = bot.get_file(message.document.file_id)
                downloaded_file = bot.download_file(file_info.file_path)
                raw_json = downloaded_file.decode('utf-8')
            else:
                bot.reply_to(message, "❌ Sirf .json ya .txt file allow hai. Phir se try karein.")
                bot.register_next_step_handler(message, process_json_input)
                return
        elif message.text:
            raw_json = message.text
        else:
            bot.reply_to(message, "❌ Invalid input. Please send JSON text or a file.")
            bot.register_next_step_handler(message, process_json_input)
            return

        # Clean JSON string (remove markdown code blocks if present)
        clean_json = raw_json.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_json)

        # Markdown conversion
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

        # API Call
        headers = {"Content-Type": "application/json", "x-api-key": BOT_API_KEY}
        bot.reply_to(message, "🚀 Pushing to DetoxByte...")
        
        res = requests.post(API_URL, json=payload, headers=headers)

        if res.status_code in [200, 201]:
            post_url = f"https://detoxbyte.xyz/{payload['category']}/{payload['slug']}"
            bot.reply_to(message, f"✅ **SUCCESS!**\n\n🔗 [View Post]({post_url})", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"❌ **API Error:** {res.text}")

    except json.JSONDecodeError:
        bot.reply_to(message, "❌ JSON format sahi nahi hai. Check karke firse file ya text bhejein:")
        bot.register_next_step_handler(message, process_json_input)
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")
    finally:
        # Clear state only on success or critical failure, not on JSON retry
        if 'res' in locals() and (res.status_code in [200, 201]):
            user_state.pop(chat_id, None)

print("🤖 DetoxByte Pro Bot is running...")
bot.infinity_polling()            "category": data.get('category'), # "blog", "news", or "article"
            "description": data.get('description'),
            "coverImage": user_state[chat_id]['coverImage'], # Picked from previous step
            "tags": data.get('tags', []),
            "content": html_content # Pushing raw HTML
        }

        # Send to DetoxByte Backend
        headers = {
            "Content-Type": "application/json",
            "x-api-key": BOT_API_KEY
        }

        bot.reply_to(message, "🚀 Pushing post to DetoxByte API...")
        res = requests.post(API_URL, json=payload, headers=headers)

        if res.status_code == 201:
            post_url = f"https://detoxbyte.xyz/{payload['category']}/{payload['slug']}"
            bot.reply_to(message, f"✅ **SUCCESS! Post Published.**\n\n🔗 Live Link:\n{post_url}", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"❌ **API Error ({res.status_code}):**\n{res.text}", parse_mode="Markdown")

    except json.JSONDecodeError:
        msg = bot.reply_to(message, "❌ Invalid JSON format! Please check your commas and quotes, and send the JSON again:")
        bot.register_next_step_handler(msg, process_json)
    except Exception as e:
        bot.reply_to(message, f"❌ Critical Error: {str(e)}")
    finally:
        # Clean up memory
        if chat_id in user_state:
            del user_state[chat_id]

print("🤖 DetoxByte Publisher Bot is running...")
bot.infinity_polling()
