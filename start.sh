#!/bin/bash
echo "Starting bot only..."
python bot.py
# gunicorn server:app -b 0.0.0.0:$PORT &  # 先注释掉这行
