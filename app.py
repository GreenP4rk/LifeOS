import streamlit as st
from google import genai
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timedelta
import re
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import PIL.Image
import json

# --- 1. KONFIGURACJA STRONY ---
st.set_page_config(page_title="LifeOS", layout="wide")

# --- 2. KONFIGURACJA AI ---
@st.cache_resource
def init_genai():
    try:
        if "GEMINI_KEY" in st.secrets:
            return genai.Client(api_key=st.secrets["GEMINI_KEY"])
        return None
    except Exception as e:
        st.error(f"Błąd AI: {e}")
        return None

client = init_genai()

def get_calories_from_ai(ingredient_name, weight_g):
    if client is None: return 0.0
    prompt = f"Podaj liczbę kalorii dla {weight_g}g produktu: {ingredient_name}. Zwróć tylko liczbę."
    try:
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        match = re.search(r"[-+]?\d*\.\d+|\d+", response.text.replace(',', '.'))
        return float(match.group()) if match else 0.0
    except: return 0.0

def get_workout_calories_from_ai(workout_summary, weight_kg, height_cm):
    if client is None: return 0.0
    prompt = f"Waga {weight_kg}kg, wzrost {height_cm}cm. Trening: {workout_summary}. Podaj spalone kcal (sama liczba)."
    try:
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        match = re.search(r"[-+]?\d*\.\d+|\d+", response.text.replace(',', '.'))
        return float(match.group()) if match else 0.0
    except: return 0.0

# --- 3. BAZA DANYCH - MODELE ---
Base = declarative_base()

class MealBatch(Base):
    __tablename__ = 'meal_batches'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    original_weight_g = Column(Float)
    current_weight_g = Column(Float)
    total_calories = Column(Float)
    total_price = Column(Float)
    date_prepared = Column(DateTime, default=datetime.now)

class ActivityLog(Base):
    __tablename__ = 'activity_log'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.now)
    steps = Column(Integer, default=0)
    calories_burned = Column(Float)
    distance_km = Column(Float)
    duration_str = Column(String)
    avg_pace = Column(String)
    avg_hr = Column(Integer)

class WorkoutLog(Base):
    __tablename__ = 'workout_log'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.now)
    exercise_name = Column(String)
    equipment_type = Column(String)
    weight_kg = Column(Float)
    reps = Column(Integer)
    sets = Column(Integer)

class MealLog(Base):
    __tablename__ = 'meal_logs'
    id = Column(Integer, primary_key=True)
    name = Column(String) # DODANO BRAKUJĄCĄ KOLUMNĘ
    date = Column(DateTime, default=datetime.now)
    calories = Column(Float)

class BatchDraft(Base): # DODANO MODEL DLA DRAFTS
    __tablename__ = 'batch_drafts'
    id = Column(Integer, primary_key=True)
    ingredient_name = Column(String)
    weight = Column(Float)
    kcal = Column(Float)

class Settings(Base):
    __tablename__ = 'settings'
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True)
    value = Column(Float)

class BodyMeasurement(Base):
    __tablename__ = 'body_measurements'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.now)
    weight = Column(Float)
    height = Column(Float)
    chest = Column(Float)
    waist = Column(Float)
    belly = Column(Float)
    thigh = Column(Float)
    biceps = Column(Float)

class PantryItem(Base):
    __tablename__ = 'pantry_items'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    weight_g = Column(Float, nullable=False)
    kcal_per_100g = Column(Float)
    date_added = Column(DateTime, default=datetime.now)

class ShoppingListItem(Base):
    __tablename__ = 'shopping_list'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    is_bought = Column(Boolean, default=False)
    date_added = Column(DateTime, default=datetime.now)

# --- 4. POŁĄCZENIE I MIGRACJA ---
@st.cache_resource
def init_db_engine():
    try:
        db_url = st.secrets["DB_URL"]
        if "postgresql" in db_url and "postgresql+psycopg2" not in db_url:
            db_url = db_url.replace("postgresql://", "postgresql+psycopg2://")
    except:
        db_url = 'sqlite:///lifeos_core.db'
    
    _engine = create_engine(db_url, pool_pre_ping=True)
    Base.metadata.create_all(_engine)
    
    # SILNA MIGRACJA: Sprawdza czy kolumna 'name' istnieje w meal_logs
    with _engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE meal_logs ADD COLUMN name VARCHAR;"))
            conn.commit()
        except: pass # Jeśli już istnieje, nic nie robi
    return _engine

engine = init_db_engine()
SessionLocal = sessionmaker(bind=engine)

# --- 5. DASHBOARD DATA ---
@st.cache_data(ttl=60)
def get_dashboard_data():
    db = SessionLocal()
    today = datetime.now().date()
    today_meals = db.query(MealLog).filter(text("date >= :t")).params(t=today).all()
    today_activity = db.query(ActivityLog).filter(text("date >= :t")).params(t=today).all()
    
    res = {
        "eaten": sum(m.calories for m in today_meals),
        "burned": sum(a.calories_burned for a in today_activity),
        "batches_count": db.query(MealBatch).filter(MealBatch.current_weight_g > 0).count()
    }
    db.close()
    return res

def get_daily_limit():
    db = SessionLocal()
    res = db.query(Settings).filter_by(key="daily_limit").first()
    db.close()
    return int(res.value) if res else 1850

# --- 6. MENU ---
st.sidebar.title("🧭 LifeOS")
choice = st.sidebar.radio("Menu:", ["🏠 Dashboard", "🍳 Nowy Posiłek", "➕ Dodaj Batch", "📦 Zamrażarka", "👟 Aktywność", "💪 Trening", "📏 Pomiary", "🛒 Lista Zakupów", "🥫 Spiżarnia"])

# --- 7. LOGIKA DASHBOARD ---
if choice == "🏠 Dashboard":
    st.title("🚀 Status Dnia")
    limit = get_daily_limit()
    data = get_dashboard_data()
    
    total_allowed = limit + data["burned"]
    remaining = total_allowed - data["eaten"]
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Zjedzone", f"{data['eaten']:.0f} kcal")
    c2.metric("Spalone", f"{data['burned']:.0f} kcal")
    c3.metric("Zostało", f"{remaining:.0f} kcal", delta=f"{remaining:.0f}", delta_color="normal")
    
    st.progress(min(data["eaten"] / total_allowed, 1.0) if total_allowed > 0 else 0)

# --- 8. NOWY POSIŁEK (NAPRAWIONY ZAPIS) ---
elif choice == "🍳 Nowy Posiłek":
    st.header("🍳 Rejestracja Posiłku")
    source = st.radio("Źródło", ["Kalkulator AI", "📦 Zamrażarka"], horizontal=True)

    if source == "Kalkulator AI":
        if 'ingredients' not in st.session_state: st.session_state.ingredients = []
        
        name = st.text_input("Składnik")
        weight = st.number_input("Waga (g)", min_value=0.0)
        
        if st.button("➕ Dodaj"):
            kcal = get_calories_from_ai(name, weight)
            st.session_state.ingredients.append({'name': name, 'kcal': kcal})
            st.rerun()
            
        total = sum(i['kcal'] for i in st.session_state.ingredients)
        st.subheader(f"Razem: {total:.0f} kcal")
        
        if st.button("✅ Zapisz Posiłek"):
            db = SessionLocal()
            db.add(MealLog(name="Posiłek AI", calories=total))
            db.commit()
            db.close()
            st.session_state.ingredients = []
            st.success("Zapisano!")
            st.rerun()
    
    else:
        db = SessionLocal()
        batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).all()
        for b in batches:
            col1, col2 = st.columns([3, 1])
            col1.write(f"**{b.name}** ({b.current_weight_g:.0f}g)")
            if col2.button("🍽️ Zjedz 250g", key=f"eat_{b.id}"):
                amount = min(250.0, b.current_weight_g)
                kcal = (b.total_calories / b.original_weight_g) * amount
                b.current_weight_g -= amount
                db.add(MealLog(name=f"{b.name} (Batch)", calories=kcal))
                db.commit()
                st.rerun()
        db.close()

# --- 9. DODAJ BATCH ---
elif choice == "➕ Dodaj Batch":
    st.header("➕ Gotowanie na zapas")
    db = SessionLocal()
    drafts = db.query(BatchDraft).all()
    
    name = st.text_input("Nazwa potrawy")
    c1, c2 = st.columns(2)
    i_name = c1.text_input("Składnik")
    i_weight = c2.number_input("Waga (g)", min_value=0.0)
    
    if st.button("➕ Wrzuć do garnka"):
        kcal = get_calories_from_ai(i_name, i_weight)
        db.add(BatchDraft(ingredient_name=i_name, weight=i_weight, kcal=kcal))
        db.commit()
        st.rerun()
        
    for d in drafts:
        st.text(f"• {d.ingredient_name}: {d.weight}g ({d.kcal:.0f} kcal)")
        
    if st.button("💾 ZAMROŹ CAŁOŚĆ"):
        total_w = sum(d.weight for d in drafts)
        total_k = sum(d.kcal for d in drafts)
        db.add(MealBatch(name=name, original_weight_g=total_w, current_weight_g=total_w, total_calories=total_k))
        db.query(BatchDraft).delete()
        db.commit()
        st.success("Zapisano w zamrażarce!")
        st.rerun()
    db.close()

# --- POZOSTAŁE SEKCE (LOGIKA ANALOGICZNA) ---
elif choice == "📏 Pomiary":
    st.header("📏 Pomiary ciała")
    db = SessionLocal()
    last_m = db.query(BodyMeasurement).order_by(BodyMeasurement.date.desc()).first()
    
    w = st.number_input("Waga", value=float(last_m.weight) if last_m else 80.0)
    p = st.number_input("Pas", value=float(last_m.waist) if last_m else 90.0)
    
    if st.button("Zapisz pomiar"):
        db.add(BodyMeasurement(weight=w, waist=p, date=datetime.now(), height=180, chest=0, belly=0, thigh=0, biceps=0))
        db.commit()
        st.success("Zapisano!")
    db.close()

# --- STOPKA / DEBUG ---
if st.sidebar.button("🧹 Czyść cache"):
    st.cache_data.clear()
