import subprocess
import sys

def main():
    print("Starting rook.py and post.py...")
    
    process_rook = subprocess.Popen([sys.executable, "rook.py"])
    process_post = subprocess.Popen([sys.executable, "post.py"])
    
    try:
        process_rook.wait()
        process_post.wait()
    except KeyboardInterrupt:
        print("\nStopping bots...")
        process_rook.terminate()
        process_post.terminate()
        process_rook.wait()
        process_post.wait()
        print("Bots stopped.")

if __name__ == "__main__":
    main()
