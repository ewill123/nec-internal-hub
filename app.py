import streamlit as st
import yaml
from yaml.loader import SafeLoader
from datetime import datetime, timedelta
import pandas as pd
import sqlite3
import plotly.express as px
import plotly.graph_objects as go
import re
import os
from pathlib import Path
import json
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from io import BytesIO
import base64

# Page config
st.set_page_config(
    page_title="NEC Internal Hub",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# DB setup
DB_PATH = "data/nec_hub.db"
ARCHIVE_PATH = "data/archive"
CUSTOM_DEPTS_PATH = "data/custom_departments.json"

def ensure_directories():
    """Ensure all required directories exist"""
    Path("data").mkdir(exist_ok=True)
    Path(ARCHIVE_PATH).mkdir(exist_ok=True)

def load_custom_departments():
    """Load custom departments added by users"""
    if os.path.exists(CUSTOM_DEPTS_PATH):
        with open(CUSTOM_DEPTS_PATH, 'r') as f:
            return json.load(f)
    return []

def save_custom_department(dept):
    """Save a new custom department"""
    depts = load_custom_departments()
    if dept not in depts:
        depts.append(dept)
        with open(CUSTOM_DEPTS_PATH, 'w') as f:
            json.dump(depts, f)
    return depts

def get_all_departments():
    """Get all departments including custom ones"""
    default_depts = [
        "ICT", "Administration", "Logistics", "HR & Training",
        "Voter Education", "Field Coordination", "Communications"
    ]
    custom_depts = load_custom_departments()
    return default_depts + custom_depts

def init_db():
    """Initialize database with all required columns"""
    ensure_directories()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='minutes'")
    table_exists = c.fetchone() is not None
    
    if not table_exists:
        c.execute('''
        CREATE TABLE minutes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department TEXT NOT NULL,
            meeting_date TEXT NOT NULL,
            attendees TEXT,
            attendees_count INTEGER DEFAULT 0,
            attendees_list TEXT,
            agenda TEXT,
            discussions TEXT,
            decisions TEXT,
            action_items TEXT,
            upcoming_events TEXT,
            submitted_by TEXT,
            submitted_at TEXT,
            is_archived INTEGER DEFAULT 0,
            archived_date TEXT
        )
        ''')
    else:
        c.execute("PRAGMA table_info(minutes)")
        existing_columns = [col[1] for col in c.fetchall()]
        
        new_columns = {
            'attendees_count': 'INTEGER DEFAULT 0',
            'attendees_list': 'TEXT',
            'is_archived': 'INTEGER DEFAULT 0',
            'archived_date': 'TEXT'
        }
        
        for col_name, col_type in new_columns.items():
            if col_name not in existing_columns:
                try:
                    c.execute(f"ALTER TABLE minutes ADD COLUMN {col_name} {col_type}")
                except:
                    pass
    
    conn.commit()
    conn.close()

def archive_old_minutes():
    """Automatically archive minutes older than 24 hours"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    now = datetime.now()
    
    c.execute("""
        SELECT id, meeting_date, department, submitted_by, submitted_at 
        FROM minutes 
        WHERE is_archived = 0 
        AND datetime(submitted_at) < datetime(?, '-1 day')
    """, (now.strftime("%Y-%m-%d %H:%M:%S"),))
    
    to_archive = c.fetchall()
    
    for row in to_archive:
        minutes_id = row[0]
        archive_date = now.strftime("%Y-%m-%d")
        
        c.execute("""
            UPDATE minutes 
            SET is_archived = 1, archived_date = ? 
            WHERE id = ?
        """, (archive_date, minutes_id))
        
    conn.commit()
    conn.close()
    
    return len(to_archive)

def submit_minutes(data):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
    INSERT INTO minutes (
        department, meeting_date, attendees, attendees_count, attendees_list,
        agenda, discussions, decisions, action_items, upcoming_events, 
        submitted_by, submitted_at, is_archived
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data['department'], data['meeting_date'], data['attendees'],
        data['attendees_count'], data['attendees_list'],
        data['agenda'], data['discussions'], data['decisions'],
        data['action_items'], data['upcoming_events'], data['submitted_by'],
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0
    ))
    conn.commit()
    conn.close()

def get_user_minutes(username, include_archived=False):
    try:
        conn = sqlite3.connect(DB_PATH)
        if include_archived:
            df = pd.read_sql_query(
                "SELECT * FROM minutes WHERE submitted_by = ? ORDER BY submitted_at DESC",
                conn, params=(username,)
            )
        else:
            df = pd.read_sql_query(
                "SELECT * FROM minutes WHERE submitted_by = ? AND is_archived = 0 ORDER BY submitted_at DESC",
                conn, params=(username,)
            )
        conn.close()
        return df
    except:
        return pd.DataFrame()

def get_minutes_by_id(minutes_id):
    """Get specific minutes by ID"""
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query(
            "SELECT * FROM minutes WHERE id = ?",
            conn, params=(minutes_id,)
        )
        conn.close()
        return df.iloc[0] if not df.empty else None
    except:
        return None

def get_all_minutes(include_archived=False):
    try:
        conn = sqlite3.connect(DB_PATH)
        if include_archived:
            df = pd.read_sql_query("SELECT * FROM minutes ORDER BY submitted_at DESC", conn)
        else:
            df = pd.read_sql_query("SELECT * FROM minutes WHERE is_archived = 0 ORDER BY submitted_at DESC", conn)
        conn.close()
        return df
    except:
        return pd.DataFrame()

def get_archived_minutes_by_date():
    """Group archived minutes by date"""
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query("""
            SELECT 
                archived_date,
                COUNT(*) as count,
                GROUP_CONCAT(department) as departments,
                GROUP_CONCAT(submitted_by) as submitters,
                GROUP_CONCAT(id) as ids
            FROM minutes 
            WHERE is_archived = 1 
            GROUP BY archived_date 
            ORDER BY archived_date DESC
        """, conn)
        conn.close()
        return df
    except:
        return pd.DataFrame()

def get_dashboard_stats():
    """Real-time dashboard statistics"""
    try:
        conn = sqlite3.connect(DB_PATH)
        
        archive_old_minutes()
        
        total_minutes = pd.read_sql_query("SELECT COUNT(*) as count FROM minutes WHERE is_archived = 0", conn).iloc[0]['count']
        total_attendees = pd.read_sql_query("SELECT COALESCE(SUM(attendees_count), 0) as sum FROM minutes WHERE is_archived = 0", conn).iloc[0]['sum']
        unique_departments = pd.read_sql_query("SELECT COUNT(DISTINCT department) as count FROM minutes WHERE is_archived = 0", conn).iloc[0]['count']
        
        today = datetime.now().strftime("%Y-%m-%d")
        today_minutes = pd.read_sql_query(
            "SELECT COUNT(*) as count FROM minutes WHERE date(submitted_at) = ? AND is_archived = 0", 
            conn, params=(today,)
        ).iloc[0]['count']
        
        weekly = pd.read_sql_query("""
            SELECT COUNT(*) as count FROM minutes 
            WHERE submitted_at >= datetime('now', '-7 days')
            AND is_archived = 0
        """, conn).iloc[0]['count']
        
        dept_stats = pd.read_sql_query("""
            SELECT 
                department,
                COUNT(*) as meeting_count,
                COALESCE(SUM(attendees_count), 0) as total_attendees,
                ROUND(AVG(attendees_count), 1) as avg_attendees
            FROM minutes 
            WHERE is_archived = 0
            GROUP BY department
            ORDER BY meeting_count DESC
        """, conn)
        
        monthly_trend = pd.read_sql_query("""
            SELECT 
                strftime('%Y-%m', submitted_at) as month,
                COUNT(*) as meetings,
                COALESCE(SUM(attendees_count), 0) as attendees
            FROM minutes 
            WHERE is_archived = 0
            AND submitted_at >= date('now', '-6 months')
            GROUP BY month
            ORDER BY month
        """, conn)
        
        conn.close()
        
        return {
            'total_minutes': int(total_minutes),
            'total_attendees': int(total_attendees),
            'unique_departments': int(unique_departments),
            'today_minutes': int(today_minutes),
            'weekly': int(weekly),
            'dept_stats': dept_stats,
            'monthly_trend': monthly_trend
        }
    except Exception as e:
        return {
            'total_minutes': 0,
            'total_attendees': 0,
            'unique_departments': 0,
            'today_minutes': 0,
            'weekly': 0,
            'dept_stats': pd.DataFrame(),
            'monthly_trend': pd.DataFrame()
        }

def export_to_csv(df):
    """Export dataframe to CSV"""
    return df.to_csv(index=False).encode('utf-8')

def export_to_json(df):
    """Export dataframe to JSON"""
    return df.to_json(orient='records', date_format='iso')

def create_pdf(minutes_data):
    """Create PDF for a single minutes entry"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#1e40af'),
        spaceAfter=30,
        alignment=1
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#1e293b'),
        spaceAfter=12,
        spaceBefore=12
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#334155'),
        spaceAfter=6
    )
    
    if os.path.exists('logo.png'):
        try:
            logo = Image('logo.png', width=1.5*inch, height=1.5*inch)
            logo.hAlign = 'CENTER'
            story.append(logo)
            story.append(Spacer(1, 0.2*inch))
        except:
            pass
    
    story.append(Paragraph("Meeting Minutes", title_style))
    story.append(Spacer(1, 0.1*inch))
    
    metadata = [
        ['Department:', minutes_data['department']],
        ['Meeting Date:', minutes_data['meeting_date']],
        ['Submitted By:', minutes_data['submitted_by']],
        ['Submitted At:', minutes_data['submitted_at']]
    ]
    
    metadata_table = Table(metadata, colWidths=[1.5*inch, 4*inch])
    metadata_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 11),
        ('TEXTCOLOR', (0,0), (0,-1), colors.HexColor('#1e40af')),
        ('TEXTCOLOR', (1,0), (1,-1), colors.HexColor('#334155')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(metadata_table)
    story.append(Spacer(1, 0.2*inch))
    
    story.append(Paragraph("Attendees", heading_style))
    attendees, count, _ = parse_attendees(minutes_data['attendees'])
    for attendee in attendees:
        dept_info = f" ({attendee['department']})" if attendee['department'] else ""
        external_info = " [External]" if attendee['is_external'] else ""
        story.append(Paragraph(f"• {attendee['name']}{dept_info}{external_info}", normal_style))
    story.append(Spacer(1, 0.1*inch))
    
    if minutes_data['agenda']:
        story.append(Paragraph("Agenda", heading_style))
        story.append(Paragraph(minutes_data['agenda'].replace('\n', '<br/>'), normal_style))
        story.append(Spacer(1, 0.1*inch))
    
    if minutes_data['discussions']:
        story.append(Paragraph("Discussions", heading_style))
        story.append(Paragraph(minutes_data['discussions'].replace('\n', '<br/>'), normal_style))
        story.append(Spacer(1, 0.1*inch))
    
    if minutes_data['decisions']:
        story.append(Paragraph("Decisions", heading_style))
        story.append(Paragraph(minutes_data['decisions'].replace('\n', '<br/>'), normal_style))
        story.append(Spacer(1, 0.1*inch))
    
    if minutes_data['action_items']:
        story.append(Paragraph("Action Items", heading_style))
        story.append(Paragraph(minutes_data['action_items'].replace('\n', '<br/>'), normal_style))
        story.append(Spacer(1, 0.1*inch))
    
    if minutes_data['upcoming_events']:
        story.append(Paragraph("Upcoming Events", heading_style))
        story.append(Paragraph(minutes_data['upcoming_events'].replace('\n', '<br/>'), normal_style))
    
    doc.build(story)
    buffer.seek(0)
    return buffer

init_db()

try:
    with open('credentials.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
    users = config['users']
except Exception as e:
    st.error(f"Error loading credentials.yaml: {e}")
    st.stop()

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.name = None
    st.session_state.role = None
    st.session_state.username = None

def parse_attendees(attendees_text):
    if not attendees_text or not attendees_text.strip():
        return [], 0, ""
    
    lines = attendees_text.strip().split('\n')
    attendees = []
    
    for line in lines:
        if not line.strip():
            continue
            
        name_part = line.strip()
        department = None
        is_external = False
        
        dept_match = re.search(r'\((.*?)\)', name_part)
        if dept_match:
            department = dept_match.group(1)
            name_part = re.sub(r'\(.*?\)', '', name_part).strip()
        
        if '@' in name_part or 'External' in name_part or '(External)' in line:
            is_external = True
            name_part = name_part.replace('@', '').replace('External', '').strip()
        
        name = name_part.strip()
        if name:
            attendees.append({
                'name': name,
                'department': department,
                'is_external': is_external
            })
    
    return attendees, len(attendees), ', '.join([a['name'] for a in attendees])

# Login Screen
if not st.session_state.logged_in:
    st.markdown("""
    <style>
    .login-gradient {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        z-index: -1;
    }
    
    .login-container {
        max-width: 500px;
        margin: 0 auto;
        padding: 3rem 2.5rem;
        background: white;
        border-radius: 24px;
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
        text-align: center;
    }
    
    .login-logo {
        width: 90px;
        height: auto;
        margin-bottom: 2rem;
    }
    
    .login-title {
        color: #1e293b;
        font-size: 2.2rem;
        font-weight: 700;
        margin-bottom: 0.75rem;
    }
    
    .login-subtitle {
        color: #64748b;
        font-size: 1rem;
        margin-bottom: 2.5rem;
    }
    
    .stTextInput > div {
        margin-bottom: 1.2rem;
    }
    
    .stTextInput > div > div > input {
        width: 100%;
        padding: 1rem 1.2rem;
        border: 2px solid #e2e8f0;
        border-radius: 12px;
        font-size: 1rem;
        transition: all 0.2s;
        background-color: #f8fafc;
        color: #000000 !important;
    }
    
    .stTextInput > div > div > input:focus {
        border-color: #1e40af;
        box-shadow: 0 0 0 4px rgba(30, 64, 175, 0.1);
        background-color: white;
    }
    
    .stButton > button {
        width: 100%;
        padding: 1rem;
        background: linear-gradient(135deg, #1e40af 0%, #1e3a8a 100%);
        color: white;
        border: none;
        border-radius: 12px;
        font-weight: 600;
        font-size: 1.1rem;
        cursor: pointer;
        transition: all 0.2s;
        margin-top: 1rem;
        box-shadow: 0 4px 6px -1px rgba(30, 64, 175, 0.2);
    }
    
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 8px 12px -1px rgba(30, 64, 175, 0.3);
    }
    
    .secure-badge {
        color: #94a3b8;
        font-size: 0.8rem;
        margin-top: 2rem;
        padding-top: 1.5rem;
        border-top: 1px solid #e2e8f0;
    }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown('<div class="login-gradient"></div>', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown('<div class="login-container">', unsafe_allow_html=True)
        
        if os.path.exists('logo.png'):
            st.image('logo.png', width=90)
        else:
            st.markdown("""
            <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/9/9d/National_Elections_Commission_of_Liberia_logo.png/220px-National_Elections_Commission_of_Liberia_logo.png" 
                 class="login-logo">
            """, unsafe_allow_html=True)
        
        st.markdown("""
        <div class="login-title">Welcome Back</div>
        <div class="login-subtitle">Sign in to access the NEC Internal Hub</div>
        """, unsafe_allow_html=True)
        
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter your username", label_visibility="collapsed")
            password = st.text_input("Password", type="password", placeholder="Enter your password", label_visibility="collapsed")
            
            submitted = st.form_submit_button("Sign In")
            
            if submitted:
                if username in users and users[username]['password'] == password:
                    st.session_state.logged_in = True
                    st.session_state.name = users[username]['name']
                    st.session_state.role = users[username].get('role', 'regular')
                    st.session_state.username = username
                    st.rerun()
                else:
                    st.error("Invalid username or password")
        
        st.markdown('<div class="secure-badge">Secure access for authorized personnel only</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    st.stop()

# Main App CSS
st.markdown("""
<style>
    .main-title {
        color: #1e40af;
        text-align: center;
        font-size: 2.5rem;
        font-weight: 700;
        margin-bottom: 1rem;
        padding: 1rem;
        background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
        border-radius: 10px;
    }
    
    .stat-card {
        background: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1);
        text-align: center;
        border: 1px solid #e2e8f0;
        transition: all 0.2s;
    }
    
    .stat-card:hover {
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        border-color: #1e40af;
    }
    
    .stat-value {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1e40af;
        line-height: 1.2;
    }
    
    .stat-label {
        color: #64748b;
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    .content-card {
        background: white;
        border-radius: 16px;
        padding: 1.5rem;
        border: 1px solid #e2e8f0;
        margin-bottom: 1.5rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }
    
    .card-header {
        font-size: 1.2rem;
        font-weight: 600;
        color: #1e293b;
        margin-bottom: 1rem;
        padding-bottom: 0.75rem;
        border-bottom: 2px solid #f1f5f9;
    }
    
    .filter-section {
        background: #f8fafc;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 2rem;
        border: 1px solid #e2e8f0;
    }
    
    .role-badge {
        display: inline-block;
        padding: 0.25rem 1rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 500;
        background: #f1f5f9;
        color: #475569;
    }
    
    .role-badge.admin {
        background: #1e40af;
        color: white;
    }
    
    .attendee-chip {
        display: inline-block;
        background: #e2e8f0;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        margin: 0.25rem;
        font-size: 0.9rem;
        color: #1e293b;
    }
    
    .attendee-chip.internal {
        background: #dbeafe;
        color: #1e40af;
    }
    
    .attendee-chip.external {
        background: #fef3c7;
        color: #92400e;
    }
    
    .archive-folder {
        background: #f1f5f9;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 0.5rem;
        border: 1px solid #cbd5e1;
        cursor: pointer;
    }
    
    .archive-folder:hover {
        background: #e2e8f0;
        border-color: #1e40af;
    }
    
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    
    .stTabs [data-baseweb="tab"] {
        border-radius: 4px 4px 0 0;
        padding: 8px 16px;
        background-color: transparent;
    }
    
    .stTabs [aria-selected="true"] {
        background-color: #1e40af !important;
        color: white !important;
    }
</style>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    if os.path.exists('logo.png'):
        st.image('logo.png', width=150)
    
    st.markdown(f"### {st.session_state.name}")
    role_class = "admin" if st.session_state.role == 'admin' else ""
    st.markdown(f'<span class="role-badge {role_class}">{st.session_state.role.upper()}</span>', unsafe_allow_html=True)
    
    st.markdown("---")
    
    if st.session_state.role == 'admin':
        menu = ["Dashboard", "Submit Minutes", "My Submissions", "Archive", "Export Data"]
    else:
        menu = ["Submit Minutes", "My Submissions", "Archive"]
    
    choice = st.radio("Navigation", menu)
    
    st.markdown("---")
    
    stats = get_dashboard_stats()
    st.metric("Active Minutes", stats['total_minutes'])
    st.metric("Today's Submissions", stats['today_minutes'])
    
    st.markdown("---")
    
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.rerun()

# Submit Minutes
if choice == "Submit Minutes":
    st.markdown('<div class="main-title">Submit Weekly Meeting Minutes</div>', unsafe_allow_html=True)
    
    st.markdown("### Attendees")
    attendees_input = st.text_area(
        "Enter attendees (one per line)",
        placeholder="John Doe (ICT)\nJane Smith (HR)\nexternal@partner.com",
        height=150
    )
    
    attendees_list, attendees_count, attendees_str = parse_attendees(attendees_input)
    
    if attendees_count > 0:
        st.info(f"Total: {attendees_count} attendees")
    
    with st.form("minutes_form"):
        col1, col2 = st.columns(2)
        with col1:
            departments = get_all_departments()
            department = st.selectbox("Department", departments + ["+ Add New Department"])
            
            if department == "+ Add New Department":
                new_dept = st.text_input("Enter new department name")
                if new_dept and st.form_submit_button("Add Department"):
                    save_custom_department(new_dept)
                    st.success(f"Department '{new_dept}' added!")
                    st.rerun()
        with col2:
            meeting_date = st.date_input("Meeting Date", datetime.today())
        
        agenda = st.text_area("Agenda", height=100)
        discussions = st.text_area("Discussions", height=150)
        decisions = st.text_area("Decisions", height=100)
        action_items = st.text_area("Action Items", height=100)
        
        st.markdown("### Latest Events")
        upcoming_events = st.text_area(
            "Upcoming Events",
            placeholder="• Next meeting: March 1, 2026\n• Budget deadline: March 15, 2026",
            height=80
        )
        
        submitted = st.form_submit_button("Submit Minutes", use_container_width=True)
        
        if submitted:
            if not attendees_input.strip():
                st.error("Please add at least one attendee")
            else:
                data = {
                    'department': department if department != "+ Add New Department" else new_dept,
                    'meeting_date': str(meeting_date),
                    'attendees': attendees_input,
                    'attendees_count': attendees_count,
                    'attendees_list': attendees_str,
                    'agenda': agenda,
                    'discussions': discussions,
                    'decisions': decisions,
                    'action_items': action_items,
                    'upcoming_events': upcoming_events,
                    'submitted_by': st.session_state.name
                }
                submit_minutes(data)
                st.success("Minutes submitted successfully!")
                st.balloons()

# My Submissions - FIXED
elif choice == "My Submissions":
    st.markdown('<div class="main-title">My Submissions</div>', unsafe_allow_html=True)
    
    tab1, tab2 = st.tabs(["Active Submissions", "My Archived Minutes"])
    
    with tab1:
        df = get_user_minutes(st.session_state.username, include_archived=False)
        
        if df.empty:
            st.info("No active submissions found")
        else:
            depts = ['All'] + list(df['department'].unique())
            filter_dept = st.selectbox("Filter by Department", depts, key="active_filter")
            
            filtered = df if filter_dept == 'All' else df[df['department'] == filter_dept]
            st.write(f"**{len(filtered)} active submissions**")
            
            for _, row in filtered.iterrows():
                with st.expander(f"{row['meeting_date']} - {row['department']}"):
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.markdown("**Attendees**")
                        if row['attendees']:
                            attendees, count, _ = parse_attendees(row['attendees'])
                            attendee_html = ""
                            for a in attendees:
                                chip_class = "attendee-chip external" if a['is_external'] else "attendee-chip internal"
                                dept_info = f" ({a['department']})" if a['department'] else ""
                                attendee_html += f'<span class="{chip_class}">{a["name"]}{dept_info}</span> '
                            st.markdown(attendee_html, unsafe_allow_html=True)
                        
                        st.markdown("**Agenda**")
                        st.write(row['agenda'])
                        
                        st.markdown("**Discussions**")
                        st.write(row['discussions'])
                        
                        st.markdown("**Decisions**")
                        st.write(row['decisions'])
                        
                        if row['action_items']:
                            st.markdown("**Action Items**")
                            st.write(row['action_items'])
                        
                        if row['upcoming_events']:
                            st.markdown("**Upcoming Events**")
                            st.write(row['upcoming_events'])
                        
                        st.caption(f"Submitted: {row['submitted_at']}")
                    
                    with col2:
                        minutes_data = row.to_dict()
                        pdf_buffer = create_pdf(minutes_data)
                        
                        st.download_button(
                            label="Download PDF",
                            data=pdf_buffer,
                            file_name=f"minutes_{row['id']}_{row['meeting_date']}.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                            key=f"pdf_{row['id']}"
                        )
    
    with tab2:
        df_archived = get_user_minutes(st.session_state.username, include_archived=True)
        df_archived = df_archived[df_archived['is_archived'] == 1] if not df_archived.empty else pd.DataFrame()
        
        if df_archived.empty:
            st.info("No archived minutes found")
        else:
            archived_by_date = df_archived.groupby('archived_date').size().reset_index(name='count')
            st.write(f"**{len(df_archived)} archived minutes**")
            
            for _, date_row in archived_by_date.iterrows():
                archive_date = date_row['archived_date']
                count = date_row['count']
                
                with st.expander(f"Archive: {archive_date} ({count} minutes)"):
                    date_minutes = df_archived[df_archived['archived_date'] == archive_date]
                    
                    for _, row in date_minutes.iterrows():
                        st.markdown(f"**{row['meeting_date']} - {row['department']}**")
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.markdown(f"*Submitted: {row['submitted_at']}*")
                        with col2:
                            minutes_data = row.to_dict()
                            pdf_buffer = create_pdf(minutes_data)
                            st.download_button(
                                label="Download PDF",
                                data=pdf_buffer,
                                file_name=f"archived_{row['id']}_{row['meeting_date']}.pdf",
                                mime="application/pdf",
                                use_container_width=True,
                                key=f"archived_pdf_{row['id']}"
                            )

# Archive - FIXED
elif choice == "Archive":
    st.markdown('<div class="main-title">Archive</div>', unsafe_allow_html=True)
    
    archived_count = archive_old_minutes()
    if archived_count > 0:
        st.success(f"Archived {archived_count} minutes older than 24 hours")
    
    archived = get_archived_minutes_by_date()
    
    if archived.empty:
        st.info("No archived minutes yet")
    else:
        for _, row in archived.iterrows():
            with st.expander(f"Archive: {row['archived_date']} ({row['count']} minutes)"):
                st.write(f"**Departments:** {row['departments']}")
                st.write(f"**Submitted by:** {row['submitters']}")
                
                ids = row['ids'].split(',')
                for minutes_id in ids:
                    minutes_data = get_minutes_by_id(int(minutes_id))
                    if minutes_data is not None:
                        st.markdown(f"**{minutes_data['meeting_date']} - {minutes_data['department']}**")
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.markdown(f"*Submitted by: {minutes_data['submitted_by']}*")
                        with col2:
                            pdf_buffer = create_pdf(minutes_data)
                            st.download_button(
                                label="Download PDF",
                                data=pdf_buffer,
                                file_name=f"archive_{minutes_id}_{minutes_data['meeting_date']}.pdf",
                                mime="application/pdf",
                                use_container_width=True,
                                key=f"archive_pdf_{minutes_id}"
                            )

# Admin Dashboard
elif choice == "Dashboard" and st.session_state.role == 'admin':
    st.markdown('<div class="main-title">Admin Dashboard</div>', unsafe_allow_html=True)
    
    stats = get_dashboard_stats()
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">{stats['total_minutes']}</div>
            <div class="stat-label">Active Minutes</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">{stats['total_attendees']}</div>
            <div class="stat-label">Total Attendees</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">{stats['weekly']}</div>
            <div class="stat-label">This Week</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-value">{stats['unique_departments']}</div>
            <div class="stat-label">Departments</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown('<div class="content-card">', unsafe_allow_html=True)
        st.markdown('<div class="card-header">Minutes by Department</div>', unsafe_allow_html=True)
        if not stats['dept_stats'].empty:
            fig = px.pie(stats['dept_stats'], values='meeting_count', names='department',
                        color_discrete_sequence=px.colors.sequential.Blues_r)
            fig.update_layout(margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col2:
        st.markdown('<div class="content-card">', unsafe_allow_html=True)
        st.markdown('<div class="card-header">Submission Trend</div>', unsafe_allow_html=True)
        if not stats['monthly_trend'].empty:
            fig = px.line(stats['monthly_trend'], x='month', y='meetings', markers=True,
                         color_discrete_sequence=['#1e40af'])
            fig.update_layout(margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    
    st.markdown('<div class="content-card">', unsafe_allow_html=True)
    st.markdown('<div class="card-header">All Submissions</div>', unsafe_allow_html=True)
    
    if st.button("Refresh Data"):
        st.rerun()
    
    all_minutes = get_all_minutes()
    
    if not all_minutes.empty:
        col1, col2, col3 = st.columns(3)
        with col1:
            depts = ['All'] + list(all_minutes['department'].unique())
            filter_dept = st.selectbox("Department", depts)
        with col2:
            users_list = ['All'] + list(all_minutes['submitted_by'].unique())
            filter_user = st.selectbox("Submitted By", users_list)
        with col3:
            date_range = st.selectbox("Date Range", ["All", "Today", "This Week", "This Month"])
        
        filtered = all_minutes.copy()
        if filter_dept != 'All':
            filtered = filtered[filtered['department'] == filter_dept]
        if filter_user != 'All':
            filtered = filtered[filtered['submitted_by'] == filter_user]
        if date_range == "Today":
            today = datetime.now().strftime("%Y-%m-%d")
            filtered = filtered[filtered['submitted_at'].str.startswith(today)]
        elif date_range == "This Week":
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            filtered = filtered[filtered['submitted_at'] >= week_ago]
        elif date_range == "This Month":
            month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            filtered = filtered[filtered['submitted_at'] >= month_ago]
        
        st.write(f"**Showing {len(filtered)} submissions**")
        
        for idx, row in filtered.iterrows():
            with st.expander(f"{row['meeting_date']} - {row['department']} (by {row['submitted_by']})"):
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    st.markdown("**Attendees**")
                    if row['attendees']:
                        attendees, count, _ = parse_attendees(row['attendees'])
                        attendee_html = ""
                        for a in attendees:
                            chip_class = "attendee-chip external" if a['is_external'] else "attendee-chip internal"
                            dept_info = f" ({a['department']})" if a['department'] else ""
                            attendee_html += f'<span class="{chip_class}">{a["name"]}{dept_info}</span> '
                        st.markdown(attendee_html, unsafe_allow_html=True)
                    
                    st.markdown("**Agenda**")
                    st.write(row['agenda'])
                    
                    st.markdown("**Discussions**")
                    st.write(row['discussions'])
                    
                    st.markdown("**Decisions**")
                    st.write(row['decisions'])
                    
                    if row['action_items']:
                        st.markdown("**Action Items**")
                        st.write(row['action_items'])
                    
                    if row['upcoming_events']:
                        st.markdown("**Upcoming Events**")
                        st.write(row['upcoming_events'])
                    
                    st.caption(f"Submitted: {row['submitted_at']}")
                
                with col2:
                    minutes_data = row.to_dict()
                    pdf_buffer = create_pdf(minutes_data)
                    
                    st.download_button(
                        label="Download PDF",
                        data=pdf_buffer,
                        file_name=f"minutes_{row['id']}_{row['meeting_date']}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        key=f"admin_pdf_{row['id']}"
                    )
    else:
        st.info("No submissions yet")
    
    st.markdown('</div>', unsafe_allow_html=True)

# Export Data
elif choice == "Export Data" and st.session_state.role == 'admin':
    st.markdown('<div class="main-title">Export Data</div>', unsafe_allow_html=True)
    
    all_minutes = get_all_minutes(include_archived=True)
    
    if not all_minutes.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            csv = export_to_csv(all_minutes)
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"nec_minutes_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        
        with col2:
            json_data = export_to_json(all_minutes)
            st.download_button(
                label="Download JSON",
                data=json_data,
                file_name=f"nec_minutes_{datetime.now().strftime('%Y%m%d')}.json",
                mime="application/json",
                use_container_width=True
            )
        
        st.markdown("---")
        st.markdown("### Data Preview")
        st.dataframe(all_minutes.head(10), use_container_width=True)
    else:
        st.info("No data to export")