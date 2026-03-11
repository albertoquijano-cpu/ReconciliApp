import sys, os, time, threading, webbrowser, socket
from dotenv import load_dotenv

if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
    APP_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR = BASE_DIR

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

load_dotenv(os.path.join(APP_DIR, ".env"))

if not os.environ.get("DATABASE_URL"):
    DATA_DIR = os.path.join(APP_DIR, "ReconciliApp_Data")
    DB_PATH = os.path.join(DATA_DIR, "reconciliapp.db")
    for d in [DATA_DIR, os.path.join(DATA_DIR, "exports"), os.path.join(DATA_DIR, "downloads")]:
        os.makedirs(d, exist_ok=True)
    os.environ["RECONCILI_DB_PATH"] = DB_PATH

HOST = "127.0.0.1"
PORT = 8080
URL = f"http://{HOST}:{PORT}"

def puerto_ocupado():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((HOST, PORT)) == 0

def abrir_browser():
    time.sleep(3)
    webbrowser.open(URL)

def main():
    # Si el servidor ya está corriendo, solo abrir el browser
    if puerto_ocupado():
        webbrowser.open(URL)
        return

    t = threading.Thread(target=abrir_browser, daemon=True)
    t.start()

    import uvicorn
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=False, log_level="warning")

if __name__ == "__main__":
    main()
