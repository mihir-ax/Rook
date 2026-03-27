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

# Global flags
shutdown_flag = False
rook_process = None
post_process = None

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
        logger.info("Post bot module loaded, starting...")
        # Call the run function
        post.run_bot()
    except ImportError as e:
        logger.error(f"Failed to import post module: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Post bot process error: {e}")
        sys.exit(1)

def cleanup_processes():
    """Clean up running processes"""
    global rook_process, post_process
    
    if rook_process and rook_process.is_alive():
        logger.info("Terminating Rook bot...")
        rook_process.terminate()
        rook_process.join(timeout=5)
        if rook_process.is_alive():
            rook_process.kill()
    
    if post_process and post_process.is_alive():
        logger.info("Terminating Post bot...")
        post_process.terminate()
        post_process.join(timeout=5)
        if post_process.is_alive():
            post_process.kill()

def main():
    """Main function to run both bots"""
    global shutdown_flag, rook_process, post_process
    
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
    
    # Wait a bit to avoid any conflicts
    time.sleep(5)
    
    logger.info("Starting Post bot...")
    post_process.start()
    
    # Monitor processes
    try:
        while not shutdown_flag:
            # Check if processes are still alive
            if not rook_process.is_alive() and rook_process.exitcode is not None:
                logger.error("⚠️ Rook bot process died!")
                if not shutdown_flag:
                    logger.info("Restarting Rook bot in 10 seconds...")
                    time.sleep(10)
                    if not shutdown_flag:
                        rook_process = multiprocessing.Process(target=run_rook_bot_process, name="RookBot")
                        rook_process.start()
            
            if not post_process.is_alive() and post_process.exitcode is not None:
                logger.error("⚠️ Post bot process died!")
                if not shutdown_flag:
                    logger.info("Restarting Post bot in 5 seconds...")
                    time.sleep(5)
                    if not shutdown_flag:
                        post_process = multiprocessing.Process(target=run_post_bot_process, name="PostBot")
                        post_process.start()
            
            time.sleep(10)
            
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    finally:
        cleanup_processes()
        logger.info("✅ Shutdown complete")

if __name__ == "__main__":
    main()
