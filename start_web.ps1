$ErrorActionPreference = "Stop"

Write-Host "Starting backend on http://0.0.0.0:8000"
Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot'; py -m pip install -r web_backend\requirements.txt; py -m web_backend.run"

Write-Host "Starting frontend on http://0.0.0.0:5173"
Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\web_frontend'; npm install; npm run dev"

Write-Host "Open http://127.0.0.1:5173"
