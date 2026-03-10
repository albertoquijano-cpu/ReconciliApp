import subprocess, sys, os, time, webbrowser
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print("\n╔══════════════════════════════════════════╗")
print("║          ReconciliApp v1.0               ║")
print("╚══════════════════════════════════════════╝\n")
print("▸ Servidor en http://127.0.0.1:8080")
print("▸ Presiona Ctrl+C para detener\n")
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "backend.main:app",
     "--host", "127.0.0.1", "--port", "8080", "--reload"],
    stdout=sys.stdout, stderr=sys.stderr
)
time.sleep(2)
webbrowser.open("http://127.0.0.1:8080/docs")
proc.wait()
