@echo off
set WEBUI_AUTH_DISABLED=true
.venv\Scripts\webui.exe start --port 18780 --host 127.0.0.1 --webui-only
