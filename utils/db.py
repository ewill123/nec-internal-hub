import sqlite3
import os
from datetime import datetime

DB_PATH = "data/nec_hub.db"

def init_db():
    if not os.path.exists("data"):
        os.makedirs("data")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
    CREATE TABLE IF NOT EXISTS minutes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        department TEXT NOT NULL,
        meeting_date TEXT NOT NULL,
        attendees TEXT,
        agenda TEXT,
        discussions TEXT,
        decisions TEXT,
        action_items TEXT,
        upcoming_events TEXT,
        submitted_by TEXT,
        submitted_at TEXT
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        posted_by TEXT,
        posted_at TEXT
    )
    ''')

    conn.commit()
    conn.close()

def submit_minutes(data):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
    INSERT INTO minutes (
        department, meeting_date, attendees, agenda, discussions,
        decisions, action_items, upcoming_events, submitted_by, submitted_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data['department'], data['meeting_date'], data['attendees'],
        data['agenda'], data['discussions'], data['decisions'],
        data['action_items'], data['upcoming_events'], data['submitted_by'],
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()