import asyncio
import threading
import os
import sys
import signal
import logging
from pyrogram import Client
import telebot
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global flags for graceful shutdown
shutdown_flag = False

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global shutdown_flag
    logger.info(f"Received signal {signum}, shutting down...")
    shutdown_flag = True

def run_rook_bot():
    """Run the Groq AI bot (Pyrogram)"""
    try:
        import rook
        logger.info("✅ Rook bot (Groq AI) started successfully")
        # The rook bot will run its own event loop
        # We need to run it in a separate thread since it's async
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def start_rook():
            await rook.main()
        
        loop.run_until_complete(start_rook())
    except ImportError as e:
        logger.error(f"Failed to import rook module: {e}")
    except Exception as e:
        logger.error(f"Rook bot error: {e}")

def run_post_bot():
    """Run the DetoxByte Publisher Bot (Telebot)"""
    try:
        import post
        logger.info("✅ Post bot (DetoxByte Publisher) started successfully")
        # The post bot uses telebot.infinity_polling() which blocks
        # So we run it directly in this thread
        post.bot.infinity_polling(skip_pending=True)
    except ImportError as e:
        logger.error(f"Failed to import post module: {e}")
    except Exception as e:
        logger.error(f"Post bot error: {e}")

def main():
    """Main function to run both bots"""
    global shutdown_flag
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("🚀 Starting Bot Launcher...")
    logger.info("=" * 50)
    logger.info("This will run both bots simultaneously:")
    logger.info("1. Rook Bot - Groq AI Assistant with Finance features")
    logger.info("2. Post Bot - DetoxByte Publisher Bot")
    logger.info("=" * 50)
    
    # Check for required environment variables
    required_vars = [
        'BOT_TOKEN', 'API_ID', 'API_HASH', 'MONGO_URI', 'ADMIN_ID',
        'TELEGRAM_BOT_TOKEN', 'ALLOWED_USER_ID', 'BOT_API_KEY',
        'CLOUDINARY_CLOUD_NAME', 'CLOUDINARY_API_KEY', 'CLOUDINARY_API_SECRET'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"❌ Missing environment variables: {', '.join(missing_vars)}")
        logger.error("Please check your .env file")
        sys.exit(1)
    
    # Create threads for both bots
    rook_thread = threading.Thread(target=run_rook_bot, name="RookBot")
    post_thread = threading.Thread(target=run_post_bot, name="PostBot")
    
    # Start both threads
    logger.info("Starting Rook Bot thread...")
    rook_thread.start()
    
    # Wait a bit to avoid any port conflicts
    logger.info("Waiting 3 seconds before starting Post Bot...")
    import time
    time.sleep(3)
    
    logger.info("Starting Post Bot thread...")
    post_thread.start()
    
    # Keep the main thread alive
    try:
        while not shutdown_flag:
            # Check if threads are still alive
            if not rook_thread.is_alive():
                logger.error("⚠️ Rook bot thread died!")
                if not shutdown_flag:
                    logger.info("Attempting to restart Rook bot...")
                    rook_thread = threading.Thread(target=run_rook_bot, name="RookBot")
                    rook_thread.start()
            
            if not post_thread.is_alive():
                logger.error("⚠️ Post bot thread died!")
                if not shutdown_flag:
                    logger.info("Attempting to restart Post bot...")
                    post_thread = threading.Thread(target=run_post_bot, name="PostBot")
                    post_thread.start()
            
            time.sleep(5)
            
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    finally:
        logger.info("Shutting down bots...")
        # Let threads finish gracefully
        time.sleep(2)
        logger.info("✅ Shutdown complete")

if __name__ == "__main__":
    main()
