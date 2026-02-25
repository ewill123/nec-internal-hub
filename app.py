import streamlit as st
import yaml
from yaml.loader import SafeLoader
from datetime import datetime
import pandas as pd
import sqlite3

# DB setup (same as before)
DB_PATH = "data/nec_hub.db"

def init_db():
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

init_db()

# Load users
try:
    with open('credentials.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    users = config['users']
except Exception as e:
    st.error(f"Error loading credentials.yaml: {e}")
    st.stop()

# Session state for login
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.name = None

st.title("NEC Internal Weekly Minutes & Communication Hub")

if not st.session_state.logged_in:
    st.subheader("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if username in users and users[username]['password'] == password:
            st.session_state.logged_in = True
            st.session_state.name = users[username]['name']
            st.success(f"Welcome {st.session_state.name}!")
            st.rerun()
        else:
            st.error("Invalid username or password")
else:
    st.sidebar.success(f"Logged in as {st.session_state.name}")
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.name = None
        st.rerun()

    tab1, tab2 = st.tabs(["Submit Minutes", "View Minutes"])

    with tab1:
        st.subheader("Submit Weekly Meeting Minutes")
        with st.form("minutes_form"):
            department = st.selectbox("Department / Unit", [
                "ICT", "Administration", "Logistics", "HR & Training",
                "Voter Education", "Field Coordination", "Other"
            ])
            meeting_date = st.date_input("Meeting Date", datetime.today())
            attendees = st.text_area("Attendees")
            agenda = st.text_area("Agenda")
            discussions = st.text_area("Key Discussions")
            decisions = st.text_area("Decisions")
            action_items = st.text_area("Action Items")
            upcoming_events = st.text_area("Upcoming Events")

            submitted = st.form_submit_button("Submit Minutes")

        if submitted:
            if not attendees.strip():
                st.error("Please fill at least Attendees!")
            else:
                data = {
                    'department': department,
                    'meeting_date': str(meeting_date),
                    'attendees': attendees,
                    'agenda': agenda,
                    'discussions': discussions,
                    'decisions': decisions,
                    'action_items': action_items,
                    'upcoming_events': upcoming_events,
                    'submitted_by': st.session_state.name
                }
                submit_minutes(data)
                st.success("Minutes submitted successfully! ✅")
                st.balloons()

    with tab2:
        st.subheader("Recent Minutes")
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query("SELECT * FROM minutes ORDER BY submitted_at DESC LIMIT 20", conn)
        conn.close()
        if df.empty:
            st.info("No minutes submitted yet. Submit one in the first tab!")
        else:
            st.dataframe(df[['department', 'meeting_date', 'submitted_by', 'submitted_at']])
            st.write("Full details in future version.")
