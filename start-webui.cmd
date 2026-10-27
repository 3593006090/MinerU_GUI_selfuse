@echo off
cd /d E:\MinerU
set "MINERU_HOME=E:\MinerU\.mineru"
set "MODELSCOPE_CACHE=E:\MinerU\.cache\modelscope"
set "HF_HOME=E:\MinerU\.cache\hf"
set "MINERU_ROOT=E:\MinerU"
set "PYTHONIOENCODING=utf-8"
"E:\MinerU\.venv\Scripts\mineru-kit.exe" webui --server-name 127.0.0.1 --server-port 7860
pause
