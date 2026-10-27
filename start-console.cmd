@echo off
cd /d E:\MinerU
set "MINERU_HOME=E:\MinerU\.mineru"
set "MODELSCOPE_CACHE=E:\MinerU\.cache\modelscope"
set "HF_HOME=E:\MinerU\.cache\hf"
set "MINERU_ROOT=E:\MinerU"
set "PYTHONIOENCODING=utf-8"
"E:\MinerU\.venv\Scripts\python.exe" "E:\MinerU\webapp\server.py"
pause
