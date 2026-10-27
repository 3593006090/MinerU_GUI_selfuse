@echo off
rem MinerU launcher (auto env)
setlocal
set "MINERU_ROOT=E:\MinerU"
set "MINERU_HOME=E:\MinerU\.mineru"
set "MODELSCOPE_CACHE=E:\MinerU\.cache\modelscope"
set "HF_HOME=E:\MinerU\.cache\hf"
"E:\MinerU\.venv\Scripts\mineru-kit.exe" %*
endlocal
