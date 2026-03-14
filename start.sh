#!/bin/bash

python bot.py &
gunicorn server:app --bind 0.0.0.0:$PORT
