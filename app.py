import streamlit as st
from google import genai
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import re
import pandas as pd
import plotly.graph_objects as go
from datetime import timedelta
import numpy as np
import json
import PIL.Image
import requests

# --- 1. KONFIGURACJA STRONY ---
st.set_page_config(page_title="LifeOS", layout="wide")

if 'scan_step' not in st.session_state:
    st.session_state.scan_step = "IDLE" # Możliwe: IDLE, SCANNING, VERIFYING
if 'temp_product' not in st.session_state:
    st.session_state.temp_product = None

# --- 2. KONFIGURACJA AI (Nowe SDK: google-genai) ---
@st.cache_resource
def init_genai():
    try:
        if "GEMINI_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_KEY"]
            return genai.Client(api_key=api_key)
        else:
            return None
    except Exception as e:
        st.error(f"Błąd inicjalizacji klienta AI: {e}")
        return None

client = init_genai()

def get_calories_from_ai(ingredient_name, weight_g):
    if client is None:
        st.error("Brak klucza API (GEMINI_KEY) w Secrets!")
        return 0.0
    
    # Bardzo rygorystyczny prompt
    prompt = f"Ile kalorii, białka, węglowodanów i tłuszczy ma {weight_g}g produktu: {ingredient_name}? Zwróć dane WYŁĄCZNIE w formacie JSON: {{\"kcal\": 0, \"protein\": 0, \"carbs\": 0, \"fat\": 0}}. Nie dopisuj żadnego tekstu."
    
    try:
        st.toast(f"🤖 AI liczy: {ingredient_name}...")
        response = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=prompt
        )
        text = response.text.strip()
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return data
        return {"kcal": 0, "protein": 0, "carbs": 0, "fat": 0}
    except:
        return {"kcal": 0, "protein": 0, "carbs": 0, "fat": 0}
    

def get_nutrition_from_ai(item_name=None, amount=1, unit="g", image_file=None):
    if client is None:
        st.error("Brak klucza API!")
        return {"kcal": 0, "protein": 0, "carbs": 0, "fat": 0}
    
    # Prompt dla tekstu i obrazu
    prompt = f"""
    Działaj jako ekspert dietetyczny. 
    Zidentyfikuj produkt i podaj wartości odżywcze (kcal, białko, węglowodany, tłuszcze) dla: {amount} {unit} {item_name if item_name else 'produktu na zdjęciu'}.
    Jeśli to zdjęcie kodu kreskowego, spróbuj go odczytać i znaleźć produkt.
    Jeśli podano jednostki domowe (łyżka, szklanka, sztuka), przelicz je na standardowe wagi.
    Zwróć TYLKO czysty JSON: {{"item": "nazwa", "kcal": 0, "protein": 0, "carbs": 0, "fat": 0}}
    """
    
    try:
        if image_file:
            img = PIL.Image.open(image_file)
            response = client.models.generate_content(
                model="gemini-2.5-flash", # Najszybszy do wizji
                contents=[prompt, img]
            )
        else:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            
        # Wyciąganie JSONa z odpowiedzi
        text_response = response.text
        json_match = re.search(r"\{.*\}", text_response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return data
        return {"kcal": 0, "protein": 0, "carbs": 0, "fat": 0}
    except Exception as e:
        st.error(f"Błąd AI: {e}")
        return {"kcal": 0, "protein": 0, "carbs": 0, "fat": 0}

def get_workout_calories_from_ai(workout_summary, weight_kg, height_cm):
    if client is None:
        return 0.0
    
    prompt = f"""
    Użytkownik o wadze {weight_kg} kg i wzroście {height_cm} cm wykonał dzisiaj następujący trening siłowy:
    {workout_summary}
    
    Oszacuj całkowitą liczbę spalonych kalorii podczas tego treningu, biorąc pod uwagę jego parametry ciała, objętość treningową i ciężary.
    Zwróć TYLKO samą liczbę (bez tekstu, bez jednostek, np. 350).
    """
    try:
        st.toast("🤖 AI analizuje Twój trening i parametry...")
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        text = response.text.strip().replace(',', '.')
        match = re.search(r"[-+]?\d*\.\d+|\d+", text)
        if match:
            return float(match.group())
        return 0.0
    except Exception as e:
        st.error(f"Błąd AI przy treningu: {e}")
        return 0.0

def safe_float(value):
    try:
        if value is None: return 0.0
        # Usuwamy ewentualne jednostki "kcal" i zamieniamy przecinki na kropki
        clean_val = str(value).replace('kcal', '').replace(',', '.').strip()
        return float(clean_val)
    except (ValueError, TypeError):
        return 0.0

def get_data_from_off(barcode):
    """Sprawdza Open Food Facts."""
    try:
        url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == 1:
                p = data["product"]
                n = p.get("nutriments", {})
                return {
                    "name": p.get("product_name", "Produkt z bazy"),
                    "kcal": n.get("energy-kcal_100g", 0),
                    "protein": n.get("proteins_100g", 0),
                    "fat": n.get("fat_100g", 0),
                    "carbs": n.get("carbohydrates_100g", 0),
                    "source": "Open Food Facts (Baza)"
                }
    except: pass
    return None

def analyze_product_image(image_file):
    """Najpierw sprawdza kod kreskowy, potem analizuje tabelę. Używa gemini-2.5-flash."""
    if client is None:
        return None
        
    try:
        # Siłowa konwersja na RGB zapobiega błędom 400 (Bad Request) przy przezroczystości (RGBA)
        img = PIL.Image.open(image_file).convert('RGB')
        
        # KROK 1: Szybki skan kodu kreskowego
        res = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=["Podaj TYLKO cyfry kodu kreskowego ze zdjęcia. Jeśli go nie ma, napisz 'NONE'.", img]
        )
        barcode = res.text.strip()
        
        if barcode != "NONE" and barcode.isdigit():
            off_data = get_data_from_off(barcode)
            if off_data: return off_data

        # KROK 2: Pełna analiza jeśli brak kodu
        prompt = """
        Zidentyfikuj produkt i odczytaj wartości na 100g.
        Zwróć TYLKO JSON: {"name": "...", "kcal": 0, "protein": 0, "fat": 0, "carbs": 0}
        """
        response = client.models.generate_content(model="gemini-2.5-flash", contents=[prompt, img])
        
        clean = re.sub(r'```json|```', '', response.text).strip()
        data = json.loads(clean)
        data["source"] = "Analiza wizualna AI"
        return data

    except Exception as e:
        # Łapiemy błąd tu, aby Streamlit Cloud go nie ocenzurował w konsoli
        st.error(f"Szczegóły błędu API: {str(e)}")
        return None

# --- 3. BAZA DANYCH - MODELE ---
Base = declarative_base()

class MealLog(Base):
    __tablename__ = "meal_logs"
    id = Column(Integer, primary_key=True, index=True)
    calories = Column(Float)
    date = Column(DateTime, default=datetime.now)
    protein_g = Column(Float, default=0.0)
    carbs_g = Column(Float, default=0.0)
    fat_g = Column(Float, default=0.0)

class MealBatch(Base):
    __tablename__ = "meal_batches"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    original_weight_g = Column(Float)
    current_weight_g = Column(Float)
    total_calories = Column(Float)
    date_prepared = Column(DateTime, default=datetime.now)
    total_protein = Column(Float, default=0.0)
    total_carbs = Column(Float, default=0.0)
    total_fat = Column(Float, default=0.0)

class BatchDraft(Base):
    __tablename__ = 'batch_drafts'
    id = Column(Integer, primary_key=True)
    ingredient_name = Column(String)
    weight = Column(Float)
    kcal = Column(Float)
    protein = Column(Float, default=0.0)
    carbs = Column(Float, default=0.0)
    fat = Column(Float, default=0.0)

class ActivityLog(Base):
    __tablename__ = 'activity_log'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.now)
    steps = Column(Integer, default=0)
    calories_burned = Column(Float)
    distance_km = Column(Float, nullable=True)
    duration_str = Column(String, nullable=True)
    avg_pace = Column(String, nullable=True)
    avg_hr = Column(Integer, nullable=True)

class WorkoutSet(Base):
    __tablename__ = 'workout_sets'
    id = Column(Integer, primary_key=True)
    exercise_id = Column(Integer)
    date = Column(DateTime, default=datetime.now)
    weight = Column(Float)
    reps = Column(Integer)

class Settings(Base):
    __tablename__ = 'settings'
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True)
    value = Column(Float)

class WorkoutLog(Base):
    __tablename__ = 'workout_log'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.now)
    exercise_name = Column(String)
    equipment_type = Column(String)
    weight_kg = Column(Float)
    reps = Column(Integer)
    sets = Column(Integer)

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
    name = Column(String, nullable=False)  # Używamy 'name', bo tak masz w bazie
    is_bought = Column(Boolean, default=False)
    date_added = Column(DateTime, default=datetime.now)
    
# --- 4. BAZA DANYCH - POŁĄCZENIE ---
@st.cache_resource
def init_db_engine():
    try:
        db_url = st.secrets["DB_URL"]
        if "postgresql" in db_url and "postgresql+psycopg2" not in db_url:
            db_url = db_url.replace("postgresql://", "postgresql+psycopg2://")
    except Exception:
        db_url = 'sqlite:///lifeos_core.db'

    return create_engine(db_url, pool_pre_ping=True)

engine = init_db_engine()

Base.metadata.create_all(engine) # Zabezpieczenie: upewnijmy się, że wszystkie tabele (w tym nowa draft) powstaną
SessionLocal = sessionmaker(bind=engine)

# --- 5. FUNKCJE DANYCH (CACHE) ---
@st.cache_data(ttl=300)
def get_dashboard_data():
    db = SessionLocal()
    today = datetime.now().date()
    
    # Dane o posiłkach
    today_meals = db.query(MealLog).filter(MealLog.date >= today).all()
    total_kcal_eaten = sum(m.calories for m in today_meals)
    total_protein = sum(m.protein_g for m in today_meals)
    total_carbs = sum(m.carbs_g for m in today_meals)
    total_fat = sum(m.fat_g for m in today_meals)
    
    # Dane o aktywności
    today_activity = db.query(ActivityLog).filter(ActivityLog.date >= today).all()
    total_kcal_burned = sum(a.calories_burned for a in today_activity)
    
    # Pobranie najnowszej wagi
    latest_meas = db.query(BodyMeasurement).order_by(BodyMeasurement.date.desc()).first()
    weight = latest_meas.weight if latest_meas else 80.0
    
    # Pobranie limitu kcal
    limit_kcal = get_daily_limit()
    
    # OBLICZANIE CELÓW MAKRO
    # Białko: 2g / kg
    target_p = weight * 2.0
    # Tłuszcz: 0.8g / kg
    target_f = weight * 0.8
    # Węglowodany: Reszta z limitu (1g P/W = 4kcal, 1g T = 9kcal)
    remaining_kcal = limit_kcal - (target_p * 4) - (target_f * 9)
    target_c = max(remaining_kcal / 4, 0)
    
    total_batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).count()
    db.close()
    
    return {
        "eaten": total_kcal_eaten,
        "protein": total_protein,
        "carbs": total_carbs,
        "fat": total_fat,
        "burned": total_kcal_burned,
        "batches_count": total_batches,
        "weight": weight,  # <--- DODAJ TĘ LINIĘ
        "targets": {
            "kcal": limit_kcal,
            "protein": target_p,
            "carbs": target_c,
            "fat": target_f
        }
    }

def get_daily_limit():
    try:
        db = SessionLocal()
        from sqlalchemy import text
        result = db.execute(text("SELECT value FROM settings WHERE key = 'daily_limit'")).fetchone()
        db.close()
        if result:
            return int(result[0])
        return 1850 
    except:
        return 1850
        
def set_daily_limit(new_limit):
    db = SessionLocal()
    setting = db.query(Settings).filter_by(key="daily_limit").first()
    if setting:
        setting.value = new_limit
    else:
        db.add(Settings(key="daily_limit", value=new_limit))
    db.commit()
    db.close()

# --- 6. NAWIGACJA ---
st.sidebar.title("🧭 Menu LifeOS")
choice = st.sidebar.radio("Przejdź do:", 
    ["🏠 Dashboard", "🛒 Lista Zakupów", "🥫 Spiżarnia", 
     "🍳 Nowy Posiłek", "➕ Dodaj Batch", "📦 Zamrażarka", "👟 Aktywność", "💪 Trening", "📏 Pomiary"])

st.sidebar.markdown("---")

st.sidebar.markdown("### ⚙️ Twój Plan")
current_limit = get_daily_limit()

new_limit = st.sidebar.number_input(
    "Dzienny cel (kcal)", 
    value=current_limit, 
    step=50,
    min_value=1200,
    max_value=5000
)

if new_limit != current_limit:
    if st.sidebar.button("💾 Zapisz nowy limit"):
        db = SessionLocal()
        from sqlalchemy import text
        db.execute(text("INSERT INTO settings (key, value) VALUES ('daily_limit', :val) ON CONFLICT (key) DO UPDATE SET value = :val"), {"val": str(new_limit)})
        db.commit()
        db.close()
        st.sidebar.success(f"Limit zmieniony na {new_limit}!")
        st.rerun()

st.sidebar.markdown("---")

with st.sidebar.expander("🛠️ Debug & Developer Tools"):
    st.write("Funkcje testowe i administracyjne")
    if st.button("🧨 Resetuj tabelę Aktywność"):
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS activity_log CASCADE"))
            conn.commit()
        Base.metadata.create_all(engine)
        st.warning("Tabela ActivityLog została zresetowana.")
        
    if st.button("🔨 Wymuś strukturę bazy"):
        Base.metadata.create_all(engine)
        st.info("Zaktualizowano schemat tabel.")
        
    if st.checkbox("Pokaż surowe dane sesji"):
        st.write(st.session_state)

# --- 7. LOGIKA APLIKACJI ---

if choice == "🏠 Dashboard":
    st.title("🚀 Dashboard")
    
    db_dash = SessionLocal()
    latest_measurement = db_dash.query(BodyMeasurement).order_by(BodyMeasurement.date.desc()).first()
    db_dash.close()
    
    if latest_measurement:
        days_passed = (datetime.now() - latest_measurement.date).days
        if days_passed >= 7:
            st.warning(f"🔔 Minęło {days_passed} dni od Twoich ostatnich pomiarów! Zaktualizuj je w zakładce 'Pomiary'.")
    else:
        st.info("🔔 Skonfiguruj swój profil w zakładce 'Pomiary', aby rozpocząć monitorowanie postępów.")
        
    dash_data = get_dashboard_data()
    limit = get_daily_limit()
    
    total_allowed = limit + dash_data["burned"]
    remaining = total_allowed - dash_data["eaten"]
    is_over_limit = remaining < 0
    
    if is_over_limit:
        st.error(f"⚠️ PRZEKROCZONO LIMIT o {abs(remaining):.0f} kcal!")
    elif remaining < 200:
        st.warning(f"🔔 Uwaga: Zostało tylko {remaining:.0f} kcal.")
    else:
        st.success(f"✅ Świetnie! Masz jeszcze {remaining:.0f} kcal zapasu.")

    col1, col2, col3 = st.columns(3)
    col1.metric("Zjedzone", f"{dash_data['eaten']:.0f} kcal")
    col2.metric("Spalone", f"{dash_data['burned']:.0f} kcal", delta=f"{dash_data['burned']:.0f} bonus")
    col3.metric(
        "Pozostało", 
        f"{remaining:.0f} kcal", 
        delta=f"{remaining:.0f}" if is_over_limit else None,
        delta_color="inverse"
    )
    
    st.markdown("---")
    
    st.subheader("📊 Stan limitu")
    progress = min(dash_data["eaten"] / total_allowed, 1.0) if total_allowed > 0 else 0
    st.progress(progress)
    
    if is_over_limit:
        st.write(f"📈 Wykorzystano **{progress*100:.1f}%** (Przekroczenie o {abs(remaining):.0f} kcal)")
    else:
        st.write(f"Wykorzystano **{progress*100:.1f}%** dostępnej energii.")

    # --- NOWE: MAKRO NA DASHBOARDZIE Z CELAMI ---
    st.divider()
    st.markdown("### 📊 Postęp Makroskładników")
    
    t = dash_data["targets"]
    
    col_p, col_c, col_f = st.columns(3)
    
    with col_p:
        p_perc = min(dash_data['protein'] / t['protein'], 1.2) if t['protein'] > 0 else 0
        st.metric("🥩 Białko", f"{dash_data['protein']:.0f} / {t['protein']:.0f} g")
        st.progress(p_perc if p_perc <= 1.0 else 1.0)
        st.caption(f"Cel: {t['protein']:.0f}g (2g/kg)")

    with col_c:
        c_perc = min(dash_data['carbs'] / t['carbs'], 1.2) if t['carbs'] > 0 else 0
        st.metric("🍞 Węglowodany", f"{dash_data['carbs']:.0f} / {t['carbs']:.0f} g")
        st.progress(c_perc if c_perc <= 1.0 else 1.0)
        st.caption(f"Cel: {t['carbs']:.0f}g (reszta)")

    with col_f:
        f_perc = min(dash_data['fat'] / t['fat'], 1.2) if t['fat'] > 0 else 0
        st.metric("🥑 Tłuszcze", f"{dash_data['fat']:.0f} / {t['fat']:.0f} g")
        st.progress(f_perc if f_perc <= 1.0 else 1.0)
        st.caption(f"Cel: {t['fat']:.0f}g (0.8g/kg)")

    # Zmień tę linię:
    st.info(f"💡 Cele obliczone na podstawie Twojej ostatniej wagi: **{dash_data['weight']:.1f} kg**")

elif choice == "🍳 Nowy Posiłek":
    st.header("🍳 Rejestracja Posiłku")
    source = st.radio("Skąd pochodzi posiłek?", ["Kalkulator AI (świeży)", "📦 Wyciągam z zamrażarki"], horizontal=True)

    if source == "Kalkulator AI (świeży)":
        if 'current_ingredients' not in st.session_state:
            st.session_state.current_ingredients = []
        if 'scan_step' not in st.session_state:
            st.session_state.scan_step = "IDLE"

        col_in, col_list = st.columns(2)
        
        with col_in:
            # --- MASZYNA STANÓW SKANOWANIA ---
            
            # STAN: IDLE - Przycisk startowy
            if st.session_state.scan_step == "IDLE":
                if st.button("📷 Skanuj produkt / tabelę"):
                    st.session_state.scan_step = "SCANNING"
                    st.session_state.temp_product = None # Czyścimy śmieci
                    st.rerun()

            # STAN: SCANNING - Aparat wywołany tylko tutaj
            elif st.session_state.scan_step == "SCANNING":
                st.info("Skieruj aparat na produkt lub tabelę wartości")
                captured_image = st.camera_input("Zrób zdjęcie", key="main_camera")
                
                if captured_image:
                    with st.spinner("🤖 Analizuję (Kod kreskowy / AI)..."):
                        # analyze_product_image teraz najpierw sprawdza bazę OFF, potem tabelę
                        data = analyze_product_image(captured_image)
                        if data:
                            st.session_state.temp_product = data
                            st.session_state.scan_step = "VERIFYING"
                            st.rerun()
                
                if st.button("❌ Anuluj"):
                    st.session_state.scan_step = "IDLE"
                    st.session_state.temp_product = None
                    st.rerun()

            # STAN: VERIFYING - Potwierdzenie przed dodaniem do listy
            elif st.session_state.scan_step == "VERIFYING":
                p = st.session_state.temp_product
                source_info = p.get('source', 'Analiza AI')
                st.success(f"🤖 Rozpoznano: **{p['name']}**")
                st.caption(f"Źródło danych: {source_info}")
                
                cols = st.columns(4)
                cols[0].metric("Kcal (100g)", p['kcal'])
                cols[1].metric("B", p['protein'])
                cols[2].metric("W", p['carbs'])
                cols[3].metric("T", p['fat'])

                with st.form("confirm_meal_form"):
                    amount = st.number_input("Ile gramów/sztuk zjadłeś?", min_value=0.0, step=1.0, value=100.0)
                    unit = st.selectbox("Jednostka", ["g", "ml", "sztuka", "łyżka", "szklanka"])
                    
                    if st.form_submit_button("✅ Potwierdź i dodaj do listy"):
                        # Przelicznik dla 100g/ml
                        ratio = amount / 100.0 if unit in ["g", "ml"] else amount
                        
                        st.session_state.current_ingredients.append({
                            'name': f"{amount}{unit} {p['name']}",
                            'weight': amount,
                            'kcal': p['kcal'] * ratio,
                            'protein': p['protein'] * ratio,
                            'carbs': p['carbs'] * ratio,
                            'fat': p['fat'] * ratio
                        })
                        # Pełne czyszczenie po dodaniu
                        st.session_state.scan_step = "IDLE"
                        st.session_state.temp_product = None
                        st.rerun()

                if st.button("🔄 Spróbuj skanować jeszcze raz"):
                    st.session_state.temp_product = None
                    st.session_state.scan_step = "SCANNING"
                    st.rerun()

            st.markdown("---")
            with st.expander("Wpisz ręcznie (bez skanowania)"):
                ing_name = st.text_input("Nazwa składnika")
                c_w, c_u = st.columns([1, 1])
                ing_weight = c_w.number_input("Ilość", min_value=0.0, value=100.0, key="man_w")
                ing_unit = c_u.selectbox("Jednostka", ["g", "ml", "sztuka", "łyżka"], key="man_u")
                
                if st.button("➕ Dodaj ręcznie"):
                    if ing_name:
                        with st.spinner("Liczenie..."):
                            data = get_nutrition_from_ai(ing_name, ing_weight, unit=ing_unit)
                            st.session_state.current_ingredients.append({
                                'name': f"{ing_weight}{ing_unit} {ing_name}", 
                                'weight': ing_weight, 
                                'kcal': data['kcal'], 'protein': data['protein'], 
                                'carbs': data['carbs'], 'fat': data['fat']
                            })
                            st.rerun()

        with col_list:
            total_kcal = sum(i['kcal'] for i in st.session_state.current_ingredients)
            st.subheader(f"Podsumowanie: {total_kcal:.0f} kcal")
            
            for idx, item in enumerate(st.session_state.current_ingredients):
                c1, c2 = st.columns([4, 1])
                c1.text(f"• {item['name']} ({item['kcal']:.0f} kcal)")
                if c2.button("🗑️", key=f"del_{idx}"):
                    st.session_state.current_ingredients.pop(idx)
                    st.rerun()
            
            if st.session_state.current_ingredients:
                if st.button("💾 ZAPISZ CAŁY POSIŁEK", type="primary"):
                    db = SessionLocal()
                    db.add(MealLog(
                        calories=total_kcal,
                        date=datetime.now(), 
                        protein_g=sum(i['protein'] for i in st.session_state.current_ingredients),
                        carbs_g=sum(i['carbs'] for i in st.session_state.current_ingredients),
                        fat_g=sum(i['fat'] for i in st.session_state.current_ingredients)
                    ))
                    db.commit()
                    db.close()
                    st.session_state.current_ingredients = []
                    get_dashboard_data.clear()
                    st.success("Posiłek zapisany!")
                    st.rerun()

    else:
        # Logika zamrażarki (bez zmian)
        st.subheader("📦 Wybór z zapasów")
        db = SessionLocal()
        batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).all()
        for batch in batches:
            col_info, col_actions = st.columns([2, 2])
            with col_info: st.write(f"**{batch.name}** ({batch.current_weight_g:.0f}g)")
            with col_actions:
                eat_w = st.number_input(f"Gramy", min_value=0.0, max_value=float(batch.current_weight_g), key=f"e_{batch.id}")
                if st.button("🍽️ Zjedz", key=f"b_{batch.id}"):
                    ratio = eat_w / batch.original_weight_g
                    db.add(MealLog(calories=batch.total_calories * ratio, 
                                   date=datetime.now(),
                                   protein_g=batch.total_protein * ratio if hasattr(batch, 'total_protein') else 0,
                                   carbs_g=batch.total_carbs * ratio if hasattr(batch, 'total_carbs') else 0,
                                   fat_g=batch.total_fat * ratio if hasattr(batch, 'total_fat') else 0))
                    batch.current_weight_g -= eat_w
                    db.commit()
                    st.rerun()
        db.close()

elif choice == "➕ Dodaj Batch":
    st.header("📦 Gotowanie na zapas")
    db = SessionLocal()
    drafts = db.query(BatchDraft).all()
    b_name = st.text_input("Nazwa potrawy")
    
    col_in, col_summary = st.columns(2)
    with col_in:
        # SKANOWANIE W BATCHU
        if not st.session_state.scan_active and st.session_state.temp_product is None:
            if st.button("📷 Skanuj składnik"):
                st.session_state.scan_active = True
                st.rerun()

        if st.session_state.scan_active:
            cap = st.camera_input("Zrób zdjęcie składnika")
            if cap:
                data = analyze_product_image(cap)
                if data:
                    st.session_state.temp_product = data
                    st.session_state.scan_active = False
                    st.rerun()

        if st.session_state.temp_product:
            p = st.session_state.temp_product
            st.write(f"Produkt: {p['name']} (100g: {p['kcal']} kcal)")
            with st.form("batch_scan_form"):
                amount = st.number_input("Waga/Ilość", min_value=0.0)
                unit = st.selectbox("Jednostka", ["g", "ml", "sztuka"])
                if st.form_submit_button("Dodaj do garnka"):
                    final = get_nutrition_from_ai(p['name'], amount, unit)
                    db.add(BatchDraft(ingredient_name=f"{amount}{unit} {p['name']}", weight=amount, 
                                      kcal=final['kcal'], protein=final['protein'], carbs=final['carbs'], fat=final['fat']))
                    db.commit()
                    st.session_state.temp_product = None
                    st.rerun()

    with col_summary:
        st.subheader("Zawartość garnka")
        for d in drafts: st.text(f"• {d.ingredient_name} ({d.kcal:.0f} kcal)")
        if st.button("💾 ZAPISZ BATCH"):
            total_w = sum(d.weight for d in drafts)
            db.add(MealBatch(name=b_name, original_weight_g=total_w, current_weight_g=total_w,
                             total_calories=sum(d.kcal for d in drafts), date_prepared=datetime.now()))
            db.query(BatchDraft).delete()
            db.commit()
            st.rerun()
    db.close()

# --- 👟 AKTYWNOŚĆ ---
elif choice == "👟 Aktywność":
    st.header("👟 Monitoring Aktywności")
    
    if 'walk_data' not in st.session_state:
        st.session_state.walk_data = None

    tabs = st.tabs(["📸 Import ze zdjęcia", "✍️ Wpis ręczny", "📈 Historia"])
    
    with tabs[0]:
        st.subheader("Wgraj zrzut ekranu z Fitness")
        uploaded_file = st.file_uploader("Wybierz zdjęcie...", type=["jpg", "jpeg", "png"], key="fitness_upload")
        
        if uploaded_file is not None:
            st.image(uploaded_file, caption="Podgląd zrzutu", width=250)
            
            if st.button("🚀 Analizuj zdjęcie"):
                with st.spinner("Gemini analizuje tętno i kalorie aktywne..."):
                    try:
                        import PIL.Image
                        img = PIL.Image.open(uploaded_file)
                        
                        prompt = """
                        Zanalizuj zrzut ekranu z Apple Fitness. Wyciągnij dane i zwróć TYLKO JSON:
                        {
                          "kcal": 0.0, 
                          "distance": 0.0, 
                          "duration": "00:00", 
                          "hr": 0, 
                          "pace": "0:00"
                        }
                        UWAGA: Dla 'kcal' weź wartość opisaną jako 'kalorie aktywne' (active calories), nie 'razem'.
                        """
                        response = client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=[prompt, img]
                        )
                        clean_json = re.search(r"\{.*\}", response.text, re.DOTALL).group()
                        st.session_state.walk_data = json.loads(clean_json)
                        st.success("Analiza zakończona! Sprawdź dane poniżej.")
                    except Exception as e:
                        st.error(f"Błąd analizy: {e}")

        if st.session_state.walk_data:
            d = st.session_state.walk_data
            st.markdown("---")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Kalorie Aktywne", f"{d.get('kcal', 0)} kcal")
            c2.metric("Dystans", f"{d.get('distance', 0)} km")
            c3.metric("Tempo", f"{d.get('pace', '0:00')} /km")
            c4.metric("Tętno", f"{d.get('hr', 0)} BPM")

            if st.button("✅ Potwierdź i zapisz do bazy"):
                try:
                    db = SessionLocal()
                    new_walk = ActivityLog(
                        calories_burned=float(d.get('kcal', 0)),
                        distance_km=float(d.get('distance', 0)) if d.get('distance') else 0.0,
                        duration_str=str(d.get('duration', '00:00')),
                        avg_pace=str(d.get('pace', '0:00')),
                        avg_hr=int(d.get('hr', 0)) if d.get('hr') else 0,
                        date=datetime.now()
                    )
                    db.add(new_walk)
                    db.commit()
                    db.close()
                    st.session_state.walk_data = None
                    get_dashboard_data.clear() 
                    st.success("Spacer zapisany! Bilans kalorii został zaktualizowany.")
                    st.balloons()
                    st.rerun()
                except Exception as e:
                    st.error(f"Błąd zapisu do bazy: {e}")

    with tabs[1]:
        manual_steps = st.number_input("Kroki", min_value=0, step=500)
        if st.button("Zapisz kroki ręcznie"):
            db = SessionLocal()
            db.add(ActivityLog(steps=manual_steps, calories_burned=manual_steps * 0.04))
            db.commit()
            db.close()
            get_dashboard_data.clear()
            st.success("Zapisano kroki!")

    with tabs[2]:
        st.subheader("Ostatnie aktywności")
        db = SessionLocal()
        logs = db.query(ActivityLog).order_by(ActivityLog.date.desc()).limit(5).all()
        for l in logs:
            with st.expander(f"📅 {l.date.strftime('%d.%m %H:%M')} — {l.calories_burned:.0f} kcal"):
                st.write(f"📍 Dystans: {l.distance_km} km")
                st.write(f"⏱ Tempo: {l.avg_pace} /km | ❤️ Tętno: {l.avg_hr} BPM")
        db.close()

# --- 💪 TRENING ---
elif choice == "💪 Trening":
    st.header("💪 Dziennik Treningowy")
    db = SessionLocal()
    
    existing_exercises = db.query(WorkoutLog.exercise_name).distinct().all()
    exercise_options = sorted([ex[0] for ex in existing_exercises if ex[0]])
    
    tabs = st.tabs(["📝 Dodaj ćwiczenie", "📈 Historia postępów"])
    
    with tabs[0]:
        with st.form("workout_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                selection = st.selectbox("Wybierz ćwiczenie", ["-- Nowe ćwiczenie --"] + exercise_options)
                if selection == "-- Nowe ćwiczenie --":
                    ex_name = st.text_input("Wpisz nazwę nowego ćwiczenia", placeholder="np. Wyciskanie żołnierskie")
                else:
                    ex_name = selection
                eq_type = st.selectbox("Rodzaj obciążenia", ["Masa własna", "Hantle", "Kettlebell", "Sztanga", "Gumy", "Inne"])
            
            with col2:
                weight = st.number_input("Ciężar (kg)", min_value=0.0, step=0.5)
                reps = st.number_input("Liczba powtórzeń", min_value=1, step=1)
                sets = st.number_input("Liczba serii", min_value=1, step=1)
                
            submit_workout = st.form_submit_button("🚀 Zapisz serię")
            
            if submit_workout:
                if ex_name:
                    clean_name = ex_name.strip().capitalize()
                    new_ex = WorkoutLog(
                        exercise_name=clean_name, equipment_type=eq_type,
                        weight_kg=weight, reps=reps, sets=sets, date=datetime.now()
                    )
                    db.add(new_ex)
                    db.commit()
                    st.success(f"Zapisano: {clean_name}")
                    st.rerun() 
                else:
                    st.error("Musisz podać nazwę ćwiczenia!")

    with tabs[1]:
        st.subheader("Ostatnie serie")
        logs = db.query(WorkoutLog).order_by(WorkoutLog.date.desc()).limit(30).all()
        if logs:
            for l in logs:
                with st.expander(f"📅 {l.date.strftime('%d.%m %H:%M')} - {l.exercise_name}"):
                    st.write(f"**Sprzęt:** {l.equipment_type}")
                    st.write(f"**Wynik:** {l.sets} serii x {l.reps} powt.")
                    st.info(f"⚖️ Obciążenie: {l.weight_kg} kg" if l.weight_kg > 0 else "💪 Masa ciała")
        else:
            st.info("Brak wpisów.")
    
    st.markdown("---")
    st.subheader("🔥 Podsumowanie dzisiejszego treningu")
    if st.button("🤖 Oblicz kalorie z dzisiejszego treningu"):
        today = datetime.now().date()
        today_logs = db.query(WorkoutLog).filter(WorkoutLog.date >= today).all()
        latest_meas = db.query(BodyMeasurement).order_by(BodyMeasurement.date.desc()).first()
        
        if not today_logs:
            st.warning("Najpierw dodaj jakieś serie treningowe z dzisiaj!")
        elif not latest_meas:
            st.error("Uzupełnij najpierw swoją wagę i wzrost w zakładce 'Pomiary', aby AI mogło poprawnie policzyć kalorie!")
        else:
            summary = "\n".join([f"- {l.exercise_name}: {l.sets} serii, {l.reps} powt., {l.weight_kg}kg ({l.equipment_type})" for l in today_logs])
            st.text("Przekazywane do AI:")
            st.text(summary)
            
            with st.spinner("AI analizuje intensywność..."):
                kcal_burned = get_workout_calories_from_ai(summary, latest_meas.weight, latest_meas.height)
                
                if kcal_burned > 0:
                    db.add(ActivityLog(steps=0, calories_burned=kcal_burned, duration_str="Trening Siłowy", date=datetime.now()))
                    db.commit()
                    get_dashboard_data.clear()
                    st.success(f"Doliczono {kcal_burned:.0f} kcal do Twojego dziennego bilansu spalania!")
                    st.balloons()
                else:
                    st.warning("Nie udało się obliczyć kalorii.")
    db.close()

# --- 📏 POMIARY ---
elif choice == "📏 Pomiary":
    st.header("📏 Śledzenie sylwetki i pomiary")
    db = SessionLocal()
    all_measurements = db.query(BodyMeasurement).order_by(BodyMeasurement.date.asc()).all()
    last_m = all_measurements[-1] if all_measurements else None
    
    tabs = st.tabs(["📝 Wprowadź pomiary", "📈 Historia", "📊 Wykresy i Trendy"])
    
    with tabs[0]:
        meas_date = st.date_input("Data pomiaru", value=datetime.now().date())
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### ⚖️ Podstawowe")
            weight = st.number_input("Waga (kg)", value=float(last_m.weight) if last_m else 80.0, step=0.1)
            height = st.number_input("Wzrost (cm)", value=float(last_m.height) if last_m else 180.0, step=1.0)
        with c2:
            st.markdown("#### 📏 Obwody (cm)")
            chest = st.number_input("Klatka piersiowa", value=float(last_m.chest) if last_m and last_m.chest else 0.0, step=0.5)
            waist = st.number_input("Pas (pępek)", value=float(last_m.waist) if last_m else 0.0, step=0.5)
            belly = st.number_input("Brzuch", value=float(last_m.belly) if last_m else 0.0, step=0.5)
            thigh = st.number_input("Udo", value=float(last_m.thigh) if last_m and last_m.thigh else 0.0, step=0.5)
            biceps = st.number_input("Biceps", value=float(last_m.biceps) if last_m else 0.0, step=0.5)

        if st.button("💾 Zapisz pomiary"):
            final_dt = datetime.combine(meas_date, datetime.now().time())
            new_m = BodyMeasurement(
                weight=weight, height=height, chest=chest, waist=waist, 
                belly=belly, thigh=thigh, biceps=biceps, date=final_dt
            )
            db.add(new_m)
            db.commit()
            st.success("Zapisano!")
            st.rerun()

    with tabs[1]:
        for m in reversed(all_measurements):
            with st.expander(f"📅 {m.date.strftime('%d.%m.%Y')} | {m.weight}kg"):
                st.write(f"**Klatka:** {m.chest}cm | **Pas:** {m.waist}cm | **Brzuch:** {m.belly}cm")
                st.write(f"**Udo:** {m.thigh}cm | **Biceps:** {m.biceps}cm")

    with tabs[2]:
        if len(all_measurements) < 2:
            st.info("Potrzebujesz co najmniej dwóch pomiarów, aby wygenerować wykres trendu.")
        else:
            df = pd.DataFrame([{
                'Data': m.date, 'Waga': m.weight, 'Klatka': m.chest, 'Pas': m.waist,
                'Brzuch': m.belly, 'Udo': m.thigh, 'Biceps': m.biceps
            } for m in all_measurements])
            
            option = st.selectbox("Wybierz parametr do analizy:", ["Waga", "Klatka", "Pas", "Brzuch", "Udo", "Biceps"])
            
            df['timestamp'] = df['Data'].map(pd.Timestamp.timestamp)
            z = np.polyfit(df['timestamp'], df[option], 1)
            p = np.poly1d(z)
            
            last_date = df['Data'].max()
            future_dates = [last_date + timedelta(days=i) for i in range(15)]
            future_timestamps = [pd.Timestamp(d).timestamp() for d in future_dates]
            future_trend = p(future_timestamps)

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df['Data'], y=df[option], mode='lines+markers', name='Pomiary', line=dict(color='#00f2ff', width=3)))
            combined_dates = pd.concat([df['Data'], pd.Series(future_dates[1:])])
            combined_trend = p(pd.concat([df['timestamp'], pd.Series(future_timestamps[1:])]))
            fig.add_trace(go.Scatter(x=combined_dates, y=combined_trend, mode='lines', name='Trend (14 dni)', line=dict(color='rgba(255, 0, 0, 0.4)', dash='dash')))

            fig.update_layout(title=f"Analiza: {option}", template="plotly_dark", hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)

            current_val = df[option].iloc[-1]
            predicted_val = future_trend[-1]
            diff = predicted_val - current_val
            
            st.subheader("🤖 Analiza AI Trendu")
            trend_desc = "spadnie" if diff < 0 else "wzrośnie"
            st.write(f"Przy obecnym tempie, za 2 tygodnie Twój **{option.lower()}** {trend_desc} o ok. **{abs(diff):.2f}**.")
    db.close()

# --- 🛒 LISTA ZAKUPÓW ---
elif choice == "🛒 Lista Zakupów":
    st.header("🛒 Inteligentna Lista Zakupów")

    db = SessionLocal()
    
    # UI do dodawania produktów
    col_add, col_btn = st.columns([3, 1])
    new_item = col_add.text_input("Co dopisać do listy?", placeholder="np. Pierś z kurczaka, mleko...")
    if col_btn.button("➕ Dodaj") and new_item:
        db.add(ShoppingListItem(name=new_item))
        db.commit()
        st.rerun()

    # Wyświetlanie listy - filtrujemy produkty niekupione
    items = db.query(ShoppingListItem).filter(ShoppingListItem.is_bought == False).all()
    
    if items:
        st.subheader("Twoje produkty:")
        for it in items:
            c1, c2 = st.columns([4, 1])
            # Checkbox do oznaczania jako kupione
            if c1.checkbox(it.name, key=f"check_{it.id}"):
                it.is_bought = True
                db.commit()
                st.rerun()
            
            # Przycisk usuwania
            if c2.button("🗑️", key=f"del_it_{it.id}"):
                db.delete(it)
                db.commit()
                st.rerun()
    else:
        st.info("Twoja lista zakupów jest pusta.")
    
    st.divider()

    # --- FUNKCJA ANALIZY GAZETKI ---
    st.subheader("💡 Analiza okazji i sezonowości")
    flyer_link = st.text_input("Wklej link do gazetki (Biedronka, Lidl, itp.)")
    
    if st.button("🔍 Analizuj okazje"):
        if flyer_link:
            with st.spinner("🤖 AI analizuje gazetkę pod kątem Twojej listy i makroskładników..."):
                my_items = [i.name for i in items]
                
                # Budujemy prompt z nowymi wytycznymi
                prompt = f"""
                Jesteś ekspertem ds. żywienia i łowcą promocji.
                Link do gazetki: {flyer_link}
                Twoja lista zakupów: {', '.join(my_items) if my_items else 'Lista jest pusta'}
                DZIŚ JEST: {datetime.now().strftime('%A, %d %B %Y')}

                ZADANIA:
                1. Jeśli lista zakupów NIE jest pusta: Sprawdź, czy produkty z listy są w promocji. Jeśli tak, wypisz je: "Produkt - Cena (strona X)".
                2. Jeśli produktów z listy nie ma w promocji LUB lista jest pusta: Wypisz po 5 najlepszych promocyjnych produktów w kategoriach:
                   - BIAŁKO (np. mięso, ryby, twarogi, strączki)
                   - WĘGLOWODANY (np. owoce, kasze, ryż, pieczywo dobrej jakości)
                   - TŁUSZCZE (np. oleje, awokado, orzechy)
                3. SEZONOWOŚĆ: Na końcu dodaj krótką listę 3 warzyw/owoców, które są teraz w szczycie sezonu i warto je kupić.

                RESTRYKCJE:
                - PRZY KAŻDYM PRODUKCIE MUSISZ PODAĆ NUMER STRONY W NAWIASIE, np. (strona 4). Jeśli nie widzisz numeru, opisz miejsce (np. okładka, ostatnia strona).
                - Jeśli produkt wymaga zakupu wielosztuk (np. 2+1), zaznacz to.
                - NIE ZMYŚLAJ cen. Jeśli nie jesteś pewien, nie wypisuj produktu.
                """
                
                try:
                    # Używamy modelu 2.5 Flash dla szybkości i dobrej analizy tekstu w obrazach
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt
                    )
                    st.success("✅ Analiza zakończona!")
                    st.markdown(response.text)
                except Exception as e:
                    st.error(f"Błąd analizy AI: {e}")
        else:
            st.warning("Najpierw wklej link do gazetki!")

# --- 🥫 SPIŻARNIA ---
elif choice == "🥫 Spiżarnia":
    st.header("🥫 Twoja Spiżarnia")
    db = SessionLocal()
    
    with st.expander("➕ Dodaj produkt do spiżarni"):
        c1, c2 = st.columns(2)
        p_name = c1.text_input("Nazwa produktu (np. Ryż Basmati)")
        p_weight = c2.number_input("Waga (g)", min_value=0.0, step=50.0)
        
        if st.button("Zapisz w spiżarni"):
            if p_name and p_weight > 0:
                db.add(PantryItem(name=p_name, weight_g=p_weight))
                db.commit()
                st.success(f"Dodano {p_name} ({p_weight}g) do zapasów!")
                st.rerun()

    st.subheader("Aktualne zapasy")
    pantry_items = db.query(PantryItem).filter(PantryItem.weight_g > 0).all()
    
    if not pantry_items:
        st.info("Twoja spiżarnia jest pusta.")
    else:
        for p in pantry_items:
            c_name, c_weight, c_action = st.columns([2, 1, 1.5])
            c_name.write(f"**{p.name}**")
            c_weight.write(f"{p.weight_g:.0f} g")
            
            with c_action:
                with st.popover("⚙️ Akcje"):
                    take_w = st.number_input("Ile ubyło? (g)", min_value=0.0, max_value=float(p.weight_g), step=10.0, key=f"take_{p.id}")
                    if st.button("Zabierz / Pożycz", key=f"btn_take_{p.id}"):
                        p.weight_g -= take_w
                        db.commit()
                        st.rerun()
                    if st.button("🗑️ Usuń całkowicie", key=f"btn_del_p_{p.id}"):
                        p.weight_g = 0
                        db.commit()
                        st.rerun()
    db.close()
