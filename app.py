import streamlit as st
from google import genai
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import re

# --- 1. KONFIGURACJA STRONY ---
st.set_page_config(page_title="LifeOS", layout="wide")

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
    
    prompt = f"Podaj liczbę kalorii dla {weight_g}g produktu: {ingredient_name}. Zwróć tylko liczbę."
    
    try:
        st.toast(f"🤖 AI liczy: {ingredient_name}...")
        response = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=prompt
        )
        # Czyszczenie odpowiedzi i wyciąganie liczby
        text = response.text.strip().replace(',', '.')
        match = re.search(r"[-+]?\d*\.\d+|\d+", text)
        
        if match:
            kcal = float(match.group())
            st.toast(f"✅ Obliczono: {kcal} kcal")
            return kcal
        else:
            st.warning(f"AI zwróciło tekst zamiast liczby: {text}")
            return 0.0
    except Exception as e:
        st.error(f"⚠️ Błąd podczas zapytania AI: {e}")
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

class MealLog(Base):
    __tablename__ = 'meal_logs'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.now)
    calories = Column(Float)
    
class Settings(Base):
    __tablename__ = 'settings'
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True)
    value = Column(Float)

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
SessionLocal = sessionmaker(bind=engine)

# --- 5. FUNKCJE DANYCH (CACHE) ---
@st.cache_data(ttl=300)
def get_dashboard_data():
    db = SessionLocal()
    today = datetime.now().date()
    today_meals = db.query(MealLog).filter(MealLog.date >= today).all()
    today_activity = db.query(ActivityLog).filter(ActivityLog.date >= today).all()
    
    total_kcal_eaten = sum(m.calories for m in today_meals)
    total_kcal_burned = sum(a.calories_burned for a in today_activity)
    total_batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).count()
    
    total_val_res = db.query(MealBatch).all()
    total_value = sum(b.total_price for b in total_val_res if b.total_price)
    
    last_workout = db.query(WorkoutSet).order_by(WorkoutSet.date.desc()).first()
    last_workout_weight = last_workout.weight if last_workout else None
    db.close()
    
    return {
        "eaten": total_kcal_eaten,
        "burned": total_kcal_burned,
        "batches_count": total_batches,
        "batches_value": total_value,
        "last_workout_weight": last_workout_weight
    }

def get_daily_limit():
    db = SessionLocal()
    setting = db.query(Settings).filter_by(key="daily_limit").first()
    db.close()
    return setting.value if setting else 2500.0

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
    ["🏠 Dashboard", "🍳 Nowy Posiłek", "➕ Dodaj Batch", "📦 Zamrażarka", "👟 Aktywność", "💪 Trening"])

st.sidebar.markdown("---")
st.sidebar.subheader("🛠️ Diagnostyka")

if st.sidebar.button("🔍 Testuj połączenie z AI"):
    if client:
        try:
            with st.spinner("Próba kontaktu z Gemini..."):
                test_resp = client.models.generate_content(model="gemini-2.5-flash", contents="Hi. Respond with OK")
                st.sidebar.success(f"Połączenie OK! Odpowiedź: {test_resp.text}")
        except Exception as e:
            st.sidebar.error(f"Błąd połączenia: {e}")
    else:
        st.sidebar.error("Brak klucza GEMINI_KEY w Secrets!")

if st.sidebar.button("🏗️ Wymuś strukturę bazy"):
    Base.metadata.create_all(engine)
    st.sidebar.success("Struktura sprawdzona!")

# --- 7. LOGIKA APLIKACJI ---

current_saved_limit = get_daily_limit()

if choice == "🏠 Dashboard":
    st.title("🚀 Dashboard")
    dash_data = get_dashboard_data()
    limit = get_daily_limit()
    
    # LOGIKA: Limit (np. 2500) - Zjedzone (np. 1500) + Spalone (np. 300) = 1300 pozostało
    # Spalone kalorie "oddają" Ci miejsce w limicie.
    remaining = limit - dash_data["eaten"] + dash_data["burned"]
    
    # Bilans netto (Zjedzone - Spalone)
    net_balance = dash_data["eaten"] - dash_data["burned"]
    
    col1, col2, col3 = st.columns(3)
    
    # Metryka 1: Zjedzone
    col1.metric("Zjedzone", f"{dash_data['eaten']:.0f} kcal")
    
    # Metryka 2: Spalone (Spacer)
    col2.metric("Spalone", f"{dash_data['burned']:.0f} kcal", delta=f"{dash_data['burned']:.0f} bonus", delta_color="normal")
    
    # Metryka 3: Pozostało (z uwzględnieniem ruchu)
    # Jeśli spaliłeś dużo, ta liczba wzrośnie
    col3.metric("Pozostało", f"{remaining:.0f} kcal", help="Wzór: Limit - Zjedzone + Spalone")
    
    st.markdown("---")
    st.subheader("📊 Stan limitu")
    
    # Pasek postępu - pokazuje ile zjadłeś w stosunku do "limit + spalone"
    total_allowed = limit + dash_data["burned"]
    progress = min(dash_data["eaten"] / total_allowed, 1.0) if total_allowed > 0 else 0
    
    st.progress(progress)
    st.write(f"Wykorzystano **{dash_data['eaten']:.0f}** z **{total_allowed:.0f}** dostępnych dzisiaj kcal (wliczając aktywność).")

elif choice == "🍳 Nowy Posiłek":
    st.header("🍳 Rejestracja Posiłku")
    if 'current_ingredients' not in st.session_state:
        st.session_state.current_ingredients = []

    col_in, col_list = st.columns(2)
    with col_in:
        ing_name = st.text_input("Składnik (np. łosoś z airfryera)")
        ing_weight = st.number_input("Waga (g)", min_value=0.0)
        if st.button("Dodaj składnik"):
            if ing_name and ing_weight > 0:
                kcal = get_calories_from_ai(ing_name, ing_weight)
                st.session_state.current_ingredients.append({'name': ing_name, 'weight': ing_weight, 'kcal': kcal})
                st.rerun()

    with col_list:
        total_kcal = sum(i['kcal'] for i in st.session_state.current_ingredients)
        st.subheader(f"Razem: {total_kcal:.0f} kcal")
        for i in st.session_state.current_ingredients:
            st.text(f"• {i['name']}: {i['weight']}g (~{i['kcal']:.0f} kcal)")
        
        if st.button("✅ Zapisz posiłek"):
            db = SessionLocal()
            db.add(MealLog(calories=total_kcal))
            db.commit()
            db.close()
            get_dashboard_data.clear()
            st.session_state.current_ingredients = []
            st.success("Zapisano!")
            st.rerun()

elif choice == "➕ Dodaj Batch":
    st.header("📦 Dodaj Batch")
    b_name = st.text_input("Nazwa potrawy")
    b_weight = st.number_input("Waga całkowita (g)", min_value=0.0)
    b_ing = st.text_area("Lista składników (np. 500g kurczaka, 200g ryżu)")
    
    if st.button("💾 Zapisz do zamrażarki"):
        if b_name and b_weight > 0:
            with st.spinner("AI analizuje..."):
                kcal = get_calories_from_ai(b_ing, 1.0)
                db = SessionLocal()
                db.add(MealBatch(name=b_name, original_weight_g=b_weight, current_weight_g=b_weight, total_calories=kcal))
                db.commit()
                db.close()
                get_dashboard_data.clear()
                st.success("Zapisano!")
        else:
            st.warning("Uzupełnij dane!")

elif choice == "📦 Zamrażarka":
    st.header("📦 Zamrażarka")
    db = SessionLocal()
    batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).all()
    for b in batches:
        st.write(f"**{b.name}**: {b.current_weight_g:.0f}g pozostało")
    db.close()

elif choice == "👟 Aktywność":
    st.header("👟 Monitoring Aktywności")
    
    # Inicjalizacja pamięci sesji dla wyniku analizy
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
                        
                        # Zaktualizowany prompt - nacisk na KALORIE AKTYWNE
                        prompt = """
                        Zanalizuj zrzut ekranu z Apple Fitness. 
                        Wyciągnij dane i zwróć TYLKO JSON:
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
                        
                        import json
                        # Wyciąganie JSON-a z tekstu
                        clean_json = re.search(r"\{.*\}", response.text, re.DOTALL).group()
                        st.session_state.walk_data = json.loads(clean_json)
                        st.success("Analiza zakończona! Sprawdź dane poniżej.")
                        
                    except Exception as e:
                        st.error(f"Błąd analizy: {e}")

        # Wyświetlanie wyniku z sesji (jeśli istnieje) i przycisk zapisu
        if st.session_state.walk_data:
            d = st.session_state.walk_data
            st.markdown("---")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Kalorie Aktywne", f"{d['kcal']} kcal")
            c2.metric("Dystans", f"{d['distance']} km")
            c3.metric("Tempo", f"{d['pace']} /km")
            c4.metric("Tętno", f"{d['hr']} BPM")

            if st.button("✅ Potwierdź i zapisz do bazy"):
                try:
                    db = SessionLocal()
                    new_walk = ActivityLog(
                        calories_burned=float(d['kcal']),
                        distance_km=float(d['distance']) if d['distance'] else 0.0,
                        duration_str=str(d['duration']),
                        avg_pace=str(d['pace']),
                        avg_hr=int(d['hr']) if d['hr'] else 0,
                        date=datetime.now()
                    )
                    db.add(new_walk)
                    db.commit()
                    db.close()
                    
                    # Czyścimy sesję po zapisie
                    st.session_state.walk_data = None
                    get_dashboard_data.clear() # Czyścimy cache dashboardu
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

elif choice == "💪 Trening":
    st.header("💪 Trening")
    st.info("Sekcja w przygotowaniu.")
