@echo off
start cmd /k "cd backend && uvicorn main:app --reload --port 8002"
echo World News project is starting...
echo Backend: http://localhost:8002
echo Frontend: http://localhost:5174
