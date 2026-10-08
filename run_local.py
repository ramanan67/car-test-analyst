"""
run_local.py
Local launcher for the Automotive Prototype Testing Analytics Platform.
"""
import sys
from pathlib import Path

# Add current folder to sys.path so 'app' and 'main' can be discovered by child processes
current_dir = str(Path(__file__).resolve().parent)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import uvicorn

if __name__ == "__main__":
    print("=" * 60)
    print(" Automotive Prototype Testing Analytics Platform")
    print(" Starting Local API Server...")
    print(" Swagger UI : http://127.0.0.1:8000/docs")
    print(" Health API : http://127.0.0.1:8000/health")
    print("=" * 60)
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
