#!/bin/bash
pip install -r requirements.txt
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
