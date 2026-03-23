import streamlit as st
from google import genai
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, text
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
        st.error(f"Błąd inicjalizacji klienta AI: {e}")
        return None

client = init_genai()

def get_calories_from_ai(ingredient_name, weight_g):
    if client is None: return 0.0
    prompt = f"Podaj liczbę kalorii dla {weight_g}g produktu: {ingredient_name}. Zwróć tylko liczbę."
    try:
        st.toast(f"🤖 AI liczy: {ingredient_name}...")
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        text_resp = response.text.strip().replace(',', '.')
        match = re.search(r"[-+]?\d*\.\d+|\d+", text_resp)
        return float(match.group()) if match else 0.0
    except:
        return 0.0

def get_workout_calories_from_ai(workout_summary, weight_kg, height_cm):
    if client is None: return 0.0
    prompt = f"Użytkownik ({weight_kg}kg, {height_cm}cm) wykonał trening: {workout_summary}. Oszacuj spalone kalorie. Zwróć TYLKO liczbę."
    try:
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        match = re.search(r"\d+", response.text)
        return float(match.group()) if match else 0.0
    except:
        return 0.0

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

class BatchDraft(Base):
    __tablename__ = 'batch_drafts'
    id = Column(Integer, primary_key=True)
    ingredient_name = Column(String)
    weight = Column(Float)
    kcal = Column(Float)

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
    name = Column(String)
    date = Column(DateTime, default=datetime.now)
    calories = Column(Float)

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

# --- 4. BAZA DANYCH - POŁĄCZENIE ---
@st.cache_resource
def init_db_engine():
    try:
        db_url = st.secrets["DB_URL"].replace("postgresql://", "postgresql+psycopg2://")
    except:
        db_url = 'sqlite:///lifeos_core.db'
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    return engine

engine = init_db_engine()
SessionLocal = sessionmaker(bind=engine)

# --- 5. FUNKCJE POMOCNICZE ---
@st.cache_data(ttl=60)
def get_dashboard_data():
    db = SessionLocal()
    today = datetime.now().date()
    today_meals = db.query(MealLog).filter(MealLog.date >= today).all()
    today_activity = db.query(ActivityLog).filter(ActivityLog.date >= today).all()
    total_kcal_eaten = sum(m.calories for m in today_meals)
    total_kcal_burned = sum(a.calories_burned for a in today_activity)
    total_batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).count()
    db.close()
    return {"eaten": total_kcal_eaten, "burned": total_kcal_burned, "batches_count": total_batches}

def get_daily_limit():
    db = SessionLocal()
    res = db.query(Settings).filter_by(key='daily_limit').first()
    db.close()
    return int(res.value) if res else 1850

# --- 6. NAWIGACJA ---
st.sidebar.title("🧭 Menu LifeOS")
choice = st.sidebar.radio("Przejdź do:", ["🏠 Dashboard", "📏 Pomiary", "🍳 Nowy Posiłek", "➕ Dodaj Batch", "📦 Zamrażarka", "👟 Aktywność", "💪 Trening"])

# --- DASHBOARD ---
if choice == "🏠 Dashboard":
    st.title("🚀 Dashboard")
    dash_data = get_dashboard_data()
    limit = get_daily_limit()
    total_allowed = limit + dash_data["burned"]
    remaining = total_allowed - dash_data["eaten"]
    
    if remaining < 0: st.error(f"⚠️ PRZEKROCZONO LIMIT o {abs(remaining):.0f} kcal!")
    else: st.success(f"✅ Pozostało {remaining:.0f} kcal")

    col1, col2, col3 = st.columns(3)
    col1.metric("Zjedzone", f"{dash_data['eaten']:.0f} kcal")
    col2.metric("Spalone", f"{dash_data['burned']:.0f} kcal")
    col3.metric("Pozostało", f"{remaining:.0f} kcal", delta_color="inverse")
    st.progress(min(dash_data["eaten"] / total_allowed, 1.0) if total_allowed > 0 else 0)

# --- NOWY POSIŁEK ---
elif choice == "🍳 Nowy Posiłek":
    st.header("🍳 Rejestracja Posiłku")
    source = st.radio("Źródło:", ["Kalkulator AI", "📦 Zamrażarka"], horizontal=True)

    if source == "Kalkulator AI":
        if 'ingreds' not in st.session_state: st.session_state.ingreds = []
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Składnik")
            weight = st.number_input("Waga (g)", min_value=0.0)
            if st.button("➕ Dodaj"):
                kcal = get_calories_from_ai(name, weight)
                st.session_state.ingreds.append({'name': name, 'weight': weight, 'kcal': kcal})
                st.rerun()
        with c2:
            total = sum(i['kcal'] for i in st.session_state.ingreds)
            st.subheader(f"Razem: {total:.0f} kcal")
            if st.button("✅ Zapisz") and total > 0:
                db = SessionLocal()
                db.add(MealLog(name="Świeży posiłek", calories=total))
                db.commit()
                db.close()
                st.session_state.ingreds = []
                st.rerun()

    else:
        db = SessionLocal()
        batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).all()
        for batch in batches:
            with st.expander(f"{batch.name} ({batch.current_weight_g:.0f}g)"):
                eat_w = st.number_input("Ile g?", max_value=float(batch.current_weight_g), key=f"e_{batch.id}")
                if st.button("🍽️ Zjedz", key=f"b_{batch.id}"):
                    kcal = (eat_w * batch.total_calories) / batch.original_weight_g
                    batch.current_weight_g -= eat_w
                    db.add(MealLog(name=f"{batch.name} (Batch)", calories=kcal))
                    db.commit()
                    st.rerun()
        db.close()

# --- DODAJ BATCH ---
elif choice == "➕ Dodaj Batch":
    st.header("➕ Gotowanie na zapas")
    db = SessionLocal()
    drafts = db.query(BatchDraft).all()
    b_name = st.text_input("Nazwa potrawy")
    
    col1, col2 = st.columns(2)
    with col1:
        ing_n = st.text_input("Składnik")
        ing_w = st.number_input("Waga (g)", min_value=0.0)
        if st.button("➕ Dodaj do garnka"):
            kcal = get_calories_from_ai(ing_n, ing_w)
            db.add(BatchDraft(ingredient_name=ing_n, weight=ing_w, kcal=kcal))
            db.commit()
            st.rerun()
    with col2:
        total_w = sum(d.weight for d in drafts)
        total_k = sum(d.kcal for d in drafts)
        st.write(f"Suma: {total_k:.0f} kcal / {total_w:.0f}g")
        if st.button("💾 ZAPISZ I ZAMROŹ") and b_name:
            db.add(MealBatch(name=b_name, original_weight_g=total_w, current_weight_g=total_w, total_calories=total_k))
            db.query(BatchDraft).delete()
            db.commit()
            st.success("Zapisano!")
            st.rerun()
    db.close()

# --- ZAMRAŻARKA ---
elif choice == "📦 Zamrażarka":
    st.header("📦 Zawartość Zamrażarki")
    db = SessionLocal()
    batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).all()
    for b in batches:
        c1, c2 = st.columns([3, 1])
        c1.write(f"**{b.name}**: {b.current_weight_g:.0f}g pozostało")
        if c2.button("🗑️ Usuń", key=f"d_{b.id}"):
            db.delete(b)
            db.commit()
            st.rerun()
    db.close()

# --- AKTYWNOŚĆ ---
elif choice == "👟 Aktywność":
    st.header("👟 Aktywność")
    up_file = st.file_uploader("Zrzut ekranu Fitness", type=["png", "jpg"])
    if up_file and st.button("🚀 Analizuj"):
        img = PIL.Image.open(up_file)
        prompt = "Zwróć TYLKO JSON: {'kcal': 0.0, 'distance': 0.0, 'duration': '00:00', 'hr': 0, 'pace': '0:00'}"
        resp = client.models.generate_content(model="gemini-2.0-flash", contents=[prompt, img])
        data = json.loads(re.search(r"\{.*\}", resp.text, re.DOTALL).group())
        db = SessionLocal()
        db.add(ActivityLog(calories_burned=data['kcal'], distance_km=data['distance'], duration_str=data['duration'], avg_hr=data['hr'], avg_pace=data['pace']))
        db.commit()
        db.close()
        st.success("Zapisano aktywność!")

# --- TRENING ---
elif choice == "💪 Trening":
    st.header("💪 Trening")
    db = SessionLocal()
    with st.form("t_form"):
        ex = st.text_input("Ćwiczenie")
        w = st.number_input("Ciężar", min_value=0.0)
        s = st.number_input("Serie", min_value=1)
        r = st.number_input("Powtórzenia", min_value=1)
        if st.form_submit_button("Zapisz"):
            db.add(WorkoutLog(exercise_name=ex, weight_kg=w, sets=s, reps=r))
            db.commit()
            st.rerun()
    
    if st.button("🤖 Oblicz kalorie z dzisiejszego treningu"):
        logs = db.query(WorkoutLog).filter(WorkoutLog.date >= datetime.now().date()).all()
        meas = db.query(BodyMeasurement).order_by(BodyMeasurement.date.desc()).first()
        if logs and meas:
            summary = ", ".join([f"{l.exercise_name} {l.sets}x{l.reps}" for l in logs])
            kcal = get_workout_calories_from_ai(summary, meas.weight, meas.height)
            db.add(ActivityLog(calories_burned=kcal, duration_str="Trening Siłowy"))
            db.commit()
            st.success(f"Dodano {kcal} kcal!")
    db.close()

# --- POMIARY ---
elif choice == "📏 Pomiary":
    st.header("📏 Pomiary")
    db = SessionLocal()
    c1, c2 = st.columns(2)
    with c1:
        w = st.number_input("Waga (kg)")
        h = st.number_input("Wzrost (cm)")
    with c2:
        pas = st.number_input("Pas (cm)")
        bic = st.number_input("Biceps (cm)")
    
    if st.button("💾 Zapisz"):
        db.add(BodyMeasurement(weight=w, height=h, waist=pas, biceps=bic, date=datetime.now()))
        db.commit()
        st.rerun()

    all_m = db.query(BodyMeasurement).order_by(BodyMeasurement.date.asc()).all()
    if len(all_m) > 1:
        df = pd.DataFrame([{"Data": m.date, "Waga": m.weight} for m in all_m])
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['Data'], y=df['Waga'], mode='lines+markers', name='Waga'))
        fig.update_layout(template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
    db.close()
