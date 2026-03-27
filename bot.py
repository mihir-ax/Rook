import asyncio
import threading
import os
import sys
import signal
import logging
import time
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
rook_bot_task = None
post_bot_running = True

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global shutdown_flag, post_bot_running
    logger.info(f"Received signal {signum}, shutting down...")
    shutdown_flag = True
    post_bot_running = False

def run_post_bot():
    """Run the DetoxByte Publisher Bot (Telebot)"""
    global post_bot_running
    
    try:
        import post
        logger.info("✅ Post bot (DetoxByte Publisher) started successfully")
        
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run the bot in a thread-safe way
        while post_bot_running:
            try:
                # Run infinity polling in a non-blocking way
                import threading
                polling_thread = threading.Thread(target=post.bot.infinity_polling, args=(True,))
                polling_thread.daemon = True
                polling_thread.start()
                
                # Keep the thread alive
                while post_bot_running and polling_thread.is_alive():
                    time.sleep(1)
                
                if post_bot_running and not polling_thread.is_alive():
                    logger.warning("Post bot polling thread died, restarting...")
                    time.sleep(5)
                    
            except Exception as e:
                logger.error(f"Post bot error: {e}")
                if post_bot_running:
                    time.sleep(10)
                    
    except ImportError as e:
        logger.error(f"Failed to import post module: {e}")
    except Exception as e:
        logger.error(f"Post bot critical error: {e}")

async def run_rook_bot_async():
    """Run the Rook bot asynchronously"""
    try:
        import rook
        logger.info("✅ Rook bot (Groq AI) started successfully")
        
        # Call the main function from rook
        await rook.main()
        
    except ImportError as e:
        logger.error(f"Failed to import rook module: {e}")
    except Exception as e:
        logger.error(f"Rook bot error: {e}")

async def main_async():
    """Main async function to run both bots"""
    global rook_bot_task
    
    # Create task for rook bot
    rook_bot_task = asyncio.create_task(run_rook_bot_async())
    
    # Run post bot in a separate thread
    post_thread = threading.Thread(target=run_post_bot, name="PostBot")
    post_thread.daemon = True
    post_thread.start()
    
    logger.info("Both bots are now running...")
    
    try:
        # Wait for rook bot task
        await rook_bot_task
    except asyncio.CancelledError:
        logger.info("Rook bot task cancelled")
    except Exception as e:
        logger.error(f"Error in main async: {e}")

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
    
    # Run the main async function
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("Shutting down...")
        time.sleep(2)
        logger.info("✅ Shutdown complete")

if __name__ == "__main__":
    main()
