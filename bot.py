import multiprocessing
import os
import sys
import time
import logging
from dotenv import load_dotenv
import signal

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global flag for shutdown
shutdown_flag = False

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    global shutdown_flag
    logger.info(f"Received signal {signum}, initiating shutdown...")
    shutdown_flag = True

def run_rook_bot_process():
    """Run rook bot in separate process"""
    try:
        import asyncio
        import rook
        
        async def run():
            try:
                await rook.main()
            except Exception as e:
                logger.error(f"Rook bot error in main: {e}")
                raise
        
        # Run the async main
        asyncio.run(run())
    except ImportError as e:
        logger.error(f"Failed to import rook module: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Rook bot process error: {e}")
        sys.exit(1)

def run_post_bot_process():
    """Run post bot in separate process"""
    try:
        import post
        logger.info("Post bot module loaded")
        # The post bot will run its own polling loop
        post.run_bot()
    except ImportError as e:
        logger.error(f"Failed to import post module: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Post bot process error: {e}")
        sys.exit(1)

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
    required_vars_rook = ['BOT_TOKEN', 'API_ID', 'API_HASH', 'MONGO_URI', 'ADMIN_ID']
    required_vars_post = ['TELEGRAM_BOT_TOKEN', 'ALLOWED_USER_ID', 'BOT_API_KEY',
                          'CLOUDINARY_CLOUD_NAME', 'CLOUDINARY_API_KEY', 'CLOUDINARY_API_SECRET']
    
    missing_vars = []
    for var in required_vars_rook + required_vars_post:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"❌ Missing environment variables: {', '.join(missing_vars)}")
        logger.error("Please check your .env file")
        sys.exit(1)
    
    # Create processes
    logger.info("Creating Rook bot process...")
    rook_process = multiprocessing.Process(target=run_rook_bot_process, name="RookBot")
    
    logger.info("Creating Post bot process...")
    post_process = multiprocessing.Process(target=run_post_bot_process, name="PostBot")
    
    # Start processes
    logger.info("Starting Rook bot...")
    rook_process.start()
    
    # Wait a bit to avoid any port conflicts
    time.sleep(3)
    
    logger.info("Starting Post bot...")
    post_process.start()
    
    # Monitor processes
    try:
        while not shutdown_flag:
            # Check if processes are still alive
            if not rook_process.is_alive():
                logger.error("⚠️ Rook bot process died!")
                if not shutdown_flag:
                    logger.info("Attempting to restart Rook bot...")
                    rook_process = multiprocessing.Process(target=run_rook_bot_process, name="RookBot")
                    rook_process.start()
            
            if not post_process.is_alive():
                logger.error("⚠️ Post bot process died!")
                if not shutdown_flag:
                    logger.info("Attempting to restart Post bot...")
                    post_process = multiprocessing.Process(target=run_post_bot_process, name="PostBot")
                    post_process.start()
            
            time.sleep(10)
            
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    finally:
        logger.info("Shutting down processes...")
        rook_process.terminate()
        post_process.terminate()
        
        # Wait for processes to finish
        rook_process.join(timeout=10)
        post_process.join(timeout=10)
        
        # Force kill if still alive
        if rook_process.is_alive():
            rook_process.kill()
        if post_process.is_alive():
            post_process.kill()
        
        logger.info("✅ Shutdown complete")

if __name__ == "__main__":
    main()
