import streamlit as st
import google.generativeai as genai
import sqlite3
import hashlib
from typing import Dict, List, Optional
import datetime
import pandas as pd
import plotly.express as px
import io
import os

# =============================
# 🔑 Configure Gemini API
# =============================
# IMPORTANT: Keep API key in secrets.toml or env vars, not frontend
# Add to .streamlit/secrets.toml -> [gemini] api_key="YOUR_KEY_HERE"
API_KEY = st.secrets["gemini"]["api_key"]
genai.configure(api_key=API_KEY)

# =============================
# Streamlit Page Setup
# =============================
st.set_page_config(
    page_title="CareerBot - AI Career Counsellor",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# =============================
# CSS for Styling + Popup
# =============================
st.markdown("""
<style>
/* Hero */
.hero-section {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 2rem;
    border-radius: 12px;
    text-align: center;
    color: white;
    margin-bottom: 2rem;
}
.hero-title { font-size: 2rem; font-weight: bold; }
.hero-subtitle { font-size: 1.1rem; opacity: 0.9; }

/* Chat popup */
.chat-popup {
    position: fixed;
    bottom: 80px;
    right: 20px;
    width: 350px;
    max-height: 500px;
    background: #fff;
    border: 1px solid #ddd;
    border-radius: 12px;
    box-shadow: 0px 4px 20px rgba(0,0,0,0.2);
    display: flex;
    flex-direction: column;
    z-index: 999;
    padding: 1rem;
}
.chat-messages {
    flex: 1;
    overflow-y: auto;
    margin-bottom: 0.5rem;
}
.user-msg {
    background: #e3f2fd;
    padding: 0.5rem;
    margin: 0.3rem;
    border-radius: 8px;
    text-align: right;
}
.bot-msg {
    background: #f3e5f5;
    padding: 0.5rem;
    margin: 0.3rem;
    border-radius: 8px;
    text-align: left;
}
.chat-toggle {
    position: fixed;
    bottom: 20px;
    right: 20px;
    background: #764ba2;
    color: white;
    border-radius: 50%;
    padding: 15px;
    cursor: pointer;
    font-size: 20px;
    text-align: center;
    box-shadow: 0px 4px 12px rgba(0,0,0,0.3);
    z-index: 1000;
}
</style>
""", unsafe_allow_html=True)

# =============================
# Database Manager
# =============================
class DatabaseManager:
    def __init__(self, db_path="career_chatbot.db"):
        self.db_path = db_path
        self._create_tables()

    def _create_tables(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Users table
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        # Chat history table
        c.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                is_user INTEGER NOT NULL, -- 1 = user, 0 = bot
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        conn.commit()
        conn.close()

    def hash_password(self, pwd):
        return hashlib.sha256(pwd.encode()).hexdigest()

    def create_user(self, username, pwd):
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                      (username, self.hash_password(pwd)))
            conn.commit()
            conn.close()
            return True
        except:
            return False

    def authenticate_user(self, username, pwd):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT id, username, password_hash FROM users WHERE username=?", (username,))
        row = c.fetchone()
        conn.close()
        if row and row[2] == self.hash_password(pwd):
            return {"id": row[0], "username": row[1]}
        return None

    def save_chat(self, user_id, msg, resp):
        """Save user message + bot response"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Save user msg
        c.execute("INSERT INTO chat_history (user_id, message, is_user) VALUES (?, ?, 1)", (user_id, msg))
        # Save bot response
        c.execute("INSERT INTO chat_history (user_id, message, is_user) VALUES (?, ?, 0)", (user_id, resp))
        conn.commit()
        conn.close()

    def get_chat_history(self, user_id):
        """Fetch chat history in order"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT message, is_user, timestamp FROM chat_history WHERE user_id=? ORDER BY id ASC", (user_id,))
        rows = c.fetchall()
        conn.close()
        return [{"message": r[0], "is_user": r[1], "timestamp": r[2]} for r in rows]

# =============================
# Career Chatbot
# =============================
class CareerChatbot:
    def __init__(self):
        self.model = genai.GenerativeModel("gemini-1.5-flash")
    def get_response(self, message, history=None):
        context = "You are a helpful career counsellor.\n"
        if history:
            for h in history[-3:]:
                context += f"User: {h['message']}\nAssistant: {h['response']}\n"
        context += f"User: {message}\nAssistant:"
        resp = self.model.generate_content(context)
        return resp.text.strip()

# =============================
# Session State
# =============================
if "db" not in st.session_state: st.session_state.db = DatabaseManager()
if "user" not in st.session_state: st.session_state.user = None
if "chat_open" not in st.session_state: st.session_state.chat_open = False
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "chatbot" not in st.session_state: st.session_state.chatbot = CareerChatbot()
# =============================
# Hero Section
# =============================
st.markdown("""
<div class="hero-section">
    <div class="hero-title">🎯 CareerBot</div>
    <div class="hero-subtitle">Your AI Career Counsellor</div>
</div>
""", unsafe_allow_html=True)

# =============================
# Login/Signup
# =============================
if not st.session_state.user:
    tab1,tab2=st.tabs(["Login","Sign Up"])
    with tab1:
        u=st.text_input("Username")
        p=st.text_input("Password", type="password")
        if st.button("Login"):
            user = st.session_state.db.authenticate_user(u, p)
            if user:
                st.session_state.user = user
                # Load saved chat history for this user
                st.session_state.chat_history = st.session_state.db.get_chat_history(user["id"])
                st.success("Logged in!")
                st.rerun()
            else:
                st.error("Invalid login")
    with tab2:
        u=st.text_input("New Username")
        p=st.text_input("New Password", type="password")
        if st.button("Sign Up"):
            if st.session_state.db.create_user(u,p): st.success("Account created! Please login.")
            else: st.error("Username exists")
else:
    st.sidebar.write(f"👋 Welcome, {st.session_state.user['username']}")

    # 🚪 Logout button
    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.session_state.chat_history = []
        st.success("Logged out successfully!")
        st.rerun()

# =============================
# Floating Chat Popup
# =============================
if st.session_state.user:
    # Floating toggle button (💬)
    if st.button("💬", key="chat_toggle_btn"):
        st.session_state.chat_open = not st.session_state.chat_open

    # Show popup only when open
    if st.session_state.chat_open:
        with st.container():
            st.markdown('<div class="chat-popup">', unsafe_allow_html=True)
            st.markdown("### CareerBot Chat")

            # Display chat history
            for h in st.session_state.chat_history:
                if h["is_user"] == 1:
                    st.markdown(f'<div class="user-msg">{h["message"]}</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="bot-msg">{h["message"]}</div>', unsafe_allow_html=True)


            # Input box for new message
            msg = st.text_input("Type your message...", key="chat_input")

            # Send button
            if st.button("Send", key="send_btn"):
                if msg.strip():
                    resp = st.session_state.chatbot.get_response(msg, st.session_state.chat_history)
                    st.session_state.chat_history.append({"message": msg, "response": resp})
                    st.session_state.db.save_chat(st.session_state.user["id"], msg, resp)
                    st.rerun()

            st.markdown("</div>", unsafe_allow_html=True)
