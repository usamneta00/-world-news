@echo off
echo Fixing dependencies for Python 3.11...
py -3.11 -m pip install yt-dlp openai faster-whisper torch fastapi uvicorn[standard] websockets feedparser sqlalchemy pydantic requests beautifulsoup4 python-multipart aiosqlite asyncio python-dateutil -i https://pypi.tuna.tsinghua.edu.cn/simple
echo Done! Please try running start.bat again.
pause
