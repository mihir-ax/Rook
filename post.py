import os
import json
import requests
import markdown
import telebot
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
import sys
import logging
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# .env file load karo
load_dotenv()

# ── 1. CONFIGURATION (Environment Variables se aayega) ──
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID")) # Tumhari Telegram ID
API_URL = "https://api.detoxbyte.xyz/posts"
BOT_API_KEY = os.getenv("BOT_API_KEY")

# Cloudinary Setup
cloudinary.config(
  cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"),
  api_key = os.getenv("CLOUDINARY_API_KEY"),
  api_secret = os.getenv("CLOUDINARY_API_SECRET")
)

# Initialize Bot with simple configuration
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Temporary memory to store Cloudinary URL while waiting for JSON
user_state = {}

# ── 2. SECURITY MIDDLEWARE ──
def is_authorized(message):
    if message.from_user.id != ALLOWED_USER_ID:
        bot.reply_to(message, "⛔ Access Denied! You are not authorized to use the DetoxByte Publisher Bot.")
        return False
    return True

# ── 3. BOT COMMANDS & FLOW ──

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if is_authorized(message):
        bot.reply_to(message, "🚀 Welcome to DetoxByte Publisher Bot!\n\nSend /newpost to create a new article, blog, or news update.")

@bot.message_handler(commands=['newpost'])
def new_post_start(message):
    if not is_authorized(message): return

    msg = bot.reply_to(message, "📸 First, send me the **Cover Image** for the post (Compress as photo, not document):", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_image)

def process_image(message):
    if not message.photo:
        msg = bot.reply_to(message, "❌ That's not an image. Please send a valid photo:")
        bot.register_next_step_handler(msg, process_image)
        return

    chat_id = message.chat.id
    bot.reply_to(message, "⏳ Uploading image to Cloudinary...")

    try:
        # Get the highest resolution photo
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # Upload raw bytes directly to Cloudinary
        upload_result = cloudinary.uploader.upload(downloaded_file)
        image_url = upload_result['secure_url']

        # Store the URL in bot memory
        user_state[chat_id] = {'coverImage': image_url}

        json_format = """```json
{
  "title": "Your Title Here",
  "slug": "your-title-here",
  "category": "blog",
  "description": "Short SEO description",
  "tags": ["Tech", "Update"],
  "content": "## Markdown is allowed here!\nThis is **awesome**."
}
```"""
        msg = bot.reply_to(message, f"✅ Image uploaded successfully!\n🔗 URL: {image_url}\n\n📝 Now, send me the **JSON Payload**.\nFormat example:\n{json_format}", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_json)

    except Exception as e:
        logger.error(f"Cloudinary upload error: {e}")
        bot.reply_to(message, f"❌ Cloudinary Upload Failed: {str(e)}")

def process_json(message):
    chat_id = message.chat.id

    # Check if user cancelled
    if message.text.startswith('/'):
        bot.reply_to(message, "🛑 Process cancelled. Send /newpost to start again.")
        user_state.pop(chat_id, None)
        return

    try:
        # Extract JSON from text (in case user added extra spaces or markdown blocks)
        raw_text = message.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw_text)

        # Markdown to HTML conversion
        md_content = data.get('content', '')
        html_content = markdown.markdown(md_content)

        # Build Final Payload for API
        payload = {
            "title": data.get('title'),
            "slug": data.get('slug'),
            "category": data.get('category'), # "blog", "news", or "article"
            "description": data.get('description'),
            "coverImage": user_state[chat_id]['coverImage'], # Picked from previous step
            "tags": data.get('tags', []),
            "content": html_content # Pushing raw HTML
        }

        # Send to DetoxByte Backend with timeout
        headers = {
            "Content-Type": "application/json",
            "x-api-key": BOT_API_KEY
        }

        bot.reply_to(message, "🚀 Pushing post to DetoxByte API...")
        
        # Use requests with explicit timeout
        res = requests.post(API_URL, json=payload, headers=headers, timeout=30)

        if res.status_code == 201:
            post_url = f"https://detoxbyte.xyz/{payload['category']}/{payload['slug']}"
            bot.reply_to(message, f"✅ **SUCCESS! Post Published.**\n\n🔗 Live Link:\n{post_url}", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"❌ **API Error ({res.status_code}):**\n{res.text}", parse_mode="Markdown")

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        msg = bot.reply_to(message, f"❌ Invalid JSON format! Error: {str(e)}\n\nPlease check your commas and quotes, and send the JSON again:")
        bot.register_next_step_handler(msg, process_json)
    except requests.exceptions.Timeout:
        logger.error("API request timeout")
        bot.reply_to(message, "❌ API request timeout! Please try again.")
    except Exception as e:
        logger.error(f"Critical error: {e}")
        bot.reply_to(message, f"❌ Critical Error: {str(e)}")
    finally:
        # Clean up memory
        if chat_id in user_state:
            del user_state[chat_id]

# ── 4. ERROR HANDLER FOR ALL MESSAGES ──
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    if is_authorized(message):
        if not message.text.startswith('/'):
            bot.reply_to(message, "Use /newpost to create a new post!")

# ── 5. MAIN FUNCTION WITH PROPER POLLING ──
def run_bot():
    """Run the bot with proper error handling and retry logic"""
    logger.info("🤖 DetoxByte Publisher Bot is starting...")
    
    # Disable unnecessary features that might cause timeout issues
    try:
        # Remove webhook if exists
        bot.remove_webhook()
    except:
        pass
    
    retry_count = 0
    max_retries = 10
    
    while retry_count < max_retries:
        try:
            logger.info(f"Starting polling (attempt {retry_count + 1}/{max_retries})...")
            
            # Start polling with proper timeout values
            bot.infinity_polling(
                timeout=20,  # Timeout for long polling
                long_polling_timeout=20,
                skip_pending=True,
                allowed_updates=["message", "callback_query"]
            )
            
            # If we get here, polling stopped normally
            logger.info("Polling stopped normally")
            break
            
        except Exception as e:
            retry_count += 1
            logger.error(f"Polling error (attempt {retry_count}/{max_retries}): {e}")
            
            if retry_count < max_retries:
                wait_time = min(30, 5 * retry_count)  # Progressive backoff
                logger.info(f"Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
            else:
                logger.critical("Max retries reached. Bot stopping.")
                raise

# When imported as module, run in background
if __name__ == "__main__":
    run_bot()
else:
    # For module import, start in background thread
    import threading
    import atexit
    
    bot_thread = None
    
    def start_bot_background():
        global bot_thread
        bot_thread = threading.Thread(target=run_bot, name="PostBotThread", daemon=True)
        bot_thread.start()
        logger.info("Post bot started in background thread")
    
    def stop_bot():
        logger.info("Stopping post bot...")
        # TeleBot doesn't have a clean stop method, but we can try
        try:
            bot.stop_polling()
        except:
            pass
    
    # Register cleanup
    atexit.register(stop_bot)
    
    # Start the bot
    start_bot_background()
