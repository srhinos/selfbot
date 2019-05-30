@echo off
chcp 65001
echo pip install --upgrade git+https://github.com/Rapptz/discord.py
:start
cls
python run.py
timeout 10 > NUL
goto start