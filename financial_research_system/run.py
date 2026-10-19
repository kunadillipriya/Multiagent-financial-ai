"""
run.py
------
Double-click-friendly launcher. Non-technical users just run:
    python run.py
and then open the link it prints in a web browser.
"""
import uvicorn

if __name__ == "__main__":
    print("\nStarting Multi-Agent Financial Research System...")
    print("Once it says 'Application startup complete', open one of these in your browser:")
    print("   http://127.0.0.1:8000/       <- Chat-style Research Agent interface (start here)")
    print("   http://127.0.0.1:8000/docs   <- API control panel (all milestones)\n")
    import os
    import uvicorn

    if __name__ == "__main__": 
     port = int(os.environ.get("PORT", 8000))
     uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=False
     )