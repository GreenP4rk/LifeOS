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
        # Pobieranie klucza z Streamlit Secrets
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
            model="gemini-2.0-flash", 
            contents=prompt
        )
        # Wyciąganie samej liczby za pomocą regex (bezpieczniejsze)
        text = response.text.strip().replace(',', '.')
        match = re.search(r"[-+]?\d*\.\d+|\d+", text)
        
        if match:
            kcal = float(match.group())
            st.toast(f"✅ Obliczono: {kcal} kcal")
            return kcal
        else:
            st.warning(f"AI zwróciło dziwny format: {text}")
            return 0.0
    except Exception as e:
        st.error(f"Błąd podczas zapytania AI: {e}")
        return 0.0

# --- 3. BAZA DANYCH (Szybkie Modele) ---
Base = declarative_base()

class MealBatch(Base):
    __tablename__ = 'meal_batches'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    original_weight_g = Column(Float)
    current_weight_g = Column(Float)
    total_calories = Column(Float)
    total_price = Column(Float)
    date_prepared = Column(DateTime, default=datetime.now)

class ActivityLog(Base):
    __tablename__ = 'activity_log'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.now)
    steps = Column(Integer)
    calories_burned = Column(Float)

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

@st.cache_resource
def init_db_engine():
    try:
        db_url = st.secrets["DB_URL"]
        if "postgresql" in db_url and "postgresql+psycopg2" not in db_url:
            db_url = db_url.replace("postgresql://", "postgresql+psycopg2://")
    except:
        db_url = 'sqlite:///lifeos_core.db'
    
    return create_engine(db_url, pool_pre_ping=True)

engine = init_db_engine()
SessionLocal = sessionmaker(bind=engine)

# --- 4. FUNKCJE DANYCH (Zoptymalizowane) ---
@st.cache_data(ttl=300)
def get_daily_limit():
    db = SessionLocal()
    setting = db.query(Settings).filter_by(key="daily_limit").first()
    db.close()
    return setting.value if setting else 2500.0

@st.cache_data(ttl=60)
def get_dashboard_metrics():
    db = SessionLocal()
    today = datetime.now().date()
    eaten = sum(m.calories for m in db.query(MealLog).filter(MealLog.date >= today).all())
    burned = sum(a.calories_burned for a in db.query(ActivityLog).filter(ActivityLog.date >= today).all())
    batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).count()
    db.close()
    return {"eaten": eaten, "burned": burned, "batches": batches}

# --- 5. BOCZNY PANEL I NAWIGACJA ---
st.sidebar.title("🧭 Menu LifeOS")
choice = st.sidebar.radio("Przejdź do:", ["🏠 Dashboard", "🍳 Nowy Posiłek", "➕ Dodaj Batch", "📦 Zamrażarka", "👟 Aktywność"])

st.sidebar.markdown("---")
st.sidebar.subheader("🛠️ Diagnostyka i Ustawienia")

# PRZYCISK TESTOWY AI
if st.sidebar.button("🔍 Testuj połączenie z AI"):
    if client:
        try:
            with st.spinner("Próba kontaktu z Gemini..."):
                test_resp = client.models.generate_content(model="gemini-2.0-flash", contents="Hi. Respond with 'OK'")
                st.sidebar.success(f"Połączenie OK! Odpowiedź: {test_resp.text}")
        except Exception as e:
            st.sidebar.error(f"Błąd połączenia: {e}")
    else:
        st.sidebar.error("Brak klucza GEMINI_KEY w Secrets!")

if st.sidebar.button("🏗️ Wymuś bazę"):
    Base.metadata.create_all(engine)
    st.sidebar.success("Tabele gotowe!")

# --- 6. LOGIKA EKRANÓW ---
if choice == "🏠 Dashboard":
    st.title("🚀 Dashboard")
    metrics = get_dashboard_metrics()
    limit = get_daily_limit()
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Zjedzone", f"{metrics['eaten']:.0f} kcal")
    c2.metric("Spalone", f"{metrics['burned']:.0f} kcal")
    c3.metric("Pozostało", f"{limit - metrics['eaten']:.0f} kcal")
    
    st.progress(min(metrics['eaten'] / limit, 1.0))

elif choice == "🍳 Nowy Posiłek":
    st.header("🍳 Rejestracja Posiłku")
    ing_name = st.text_input("Co jesz? (np. Jajecznica z 3 jaj)")
    ing_weight = st.number_input("Waga (g)", min_value=0.0, step=10.0)
    
    if st.button("🔥 Oblicz i dodaj"):
        if ing_name and ing_weight > 0:
            kcal = get_calories_from_ai(ing_name, ing_weight)
            if kcal > 0:
                db = SessionLocal()
                db.add(MealLog(calories=kcal))
                db.commit()
                db.close()
                get_dashboard_metrics.clear()
                st.success(f"Dodano {kcal:.0f} kcal do dziennika!")
        else:
            st.warning("Wpisz nazwę i wagę!")

elif choice == "➕ Dodaj Batch":
    st.header("➕ Dodaj do zamrażarki")
    b_name = st.text_input("Nazwa potrawy")
    b_weight = st.number_input("Waga całkowita (g)", min_value=0.0)
    b_ingredients = st.text_area("Składniki (jeden pod drugim, np. 500g kurczaka)")
    
    if st.button("💾 Zapisz Batch"):
        with st.spinner("AI analizuje cały przepis..."):
            # Prosta analiza zbiorcza dla oszczędności czasu
            kcal = get_calories_from_ai(b_ingredients, 1.0) # Tu AI liczy całość
            db = SessionLocal()
            db.add(MealBatch(name=b_name, original_weight_g=b_weight, current_weight_g=b_weight, total_calories=kcal))
            db.commit()
            db.close()
            st.success("Danie zapisane!")

elif choice == "📦 Zamrażarka":
    st.header("📦 Zawartość zamrażarki")
    db = SessionLocal()
    items = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).all()
    for item in items:
        st.write(f"**{item.name}**: {item.current_weight_g:.0f}g pozostało")
    db.close()

elif choice == "👟 Aktywność":
    st.header("👟 Kroki")
    steps = st.number_input("Liczba kroków", min_value=0, step=100)
    if st.button("Zapisz"):
        db = SessionLocal()
        db.add(ActivityLog(steps=steps, calories_burned=steps * 0.04))
        db.commit()
        db.close()
        get_dashboard_metrics.clear()
        st.success("Zapisano!")        
        cleaned_response = response.text.strip().replace(',', '.')
        return float(''.join(c for c in cleaned_response if c.isdigit() or c == '.'))
    except Exception as e:
        st.error(f"⚠️ Problem z obliczeniami AI: {e}")
        return 0.0
        
# --- 2. BAZA DANYCH - MODELE ---
# Modele muszą być zdefiniowane przed inicjalizacją połączenia
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
    steps = Column(Integer, nullable=False)
    calories_burned = Column(Float)

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

# --- 3. BAZA DANYCH - POŁĄCZENIE (KESHOWANE) ---
@st.cache_resource
def init_db_engine():
    try:
        db_url = st.secrets["DB_URL"]
    except Exception:
        db_url = 'sqlite:///lifeos_core.db'

    if "supabase.com" in db_url or "pooler.supabase.com" in db_url:
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+psycopg2://")
        
        return create_engine(
            db_url,
            connect_args={
                "sslmode": "require",
                "connect_timeout": 10,
                "options": "-c statement_timeout=30000"
            },
            pool_pre_ping=True,
            pool_recycle=300
        )
    return create_engine(db_url)

engine = init_db_engine()
SessionLocal = sessionmaker(bind=engine)

# --- 5. FUNKCJE POMOCNICZE I OPTYMALIZACJA ZAPYTAŃ ---
@st.cache_data(ttl=300) # Pamięta dane przez 5 minut (300 sekund)
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

# --- 6. NAWIGACJA (SIDEBAR) ---
st.sidebar.title("🧭 Menu LifeOS")
choice = st.sidebar.radio("Przejdź do:", 
    ["🏠 Dashboard", "🍳 Nowy Posiłek", "➕ Dodaj Batch", "📦 Zamrażarka", "👟 Aktywność", "💪 Trening"])

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Ustawienia")
current_saved_limit = get_daily_limit()
new_limit_input = st.sidebar.number_input("Dzienny limit kcal", value=float(current_saved_limit), step=50.0)

if st.sidebar.button("💾 Zapisz limit"):
    set_daily_limit(new_limit_input)
    st.sidebar.success("Zapisano!")
    st.rerun()

st.sidebar.markdown("---")
# Ukryty przycisk serwisowy - używaj tylko jeśli dodasz nowe tabele do kodu
if st.sidebar.button("🛠️ Serwis: Wymuś strukturę bazy", help="Utworzy tabele, jeśli ich brakuje"):
    Base.metadata.create_all(engine)
    st.sidebar.success("Struktura sprawdzona!")

# --- 7. GŁÓWNA LOGIKA APLIKACJI ---

if choice == "🏠 Dashboard":
    st.title("🚀 LifeOS: Dashboard")
    
    col_title, col_btn = st.columns([4, 1])
    with col_btn:
        if st.button("🔄 Odśwież dane"):
            get_dashboard_data.clear() # Czyści cache i zmusza do pobrania nowych danych
            st.rerun()
    
    # Pobieranie danych z CACHE (Błyskawiczne!)
    dash_data = get_dashboard_data()
    remaining_kcal = current_saved_limit - dash_data["eaten"]
    balance = dash_data["eaten"] - dash_data["burned"]
    
    # Metryki
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("Zjedzone dzisiaj", f"{dash_data['eaten']:.0f} kcal", f"Limit: {current_saved_limit}")
    with col2:
        st.metric("Bilans netto", f"{balance:.0f} kcal", delta_color="inverse")
    with col3:
        st.metric("Pozostało kcal", f"{remaining_kcal:.0f} kcal")
    with col4:
        st.metric("Spalone (spacer)", f"{dash_data['burned']:.0f} kcal")
    with col5:
        st.metric("W zamrażarce", f"{dash_data['batches_count']} potraw", f"{dash_data['batches_value']:.2f} zł")
    with col6:
        if dash_data['last_workout_weight']:
            st.metric("Ostatni trening", f"{dash_data['last_workout_weight']} kg", "Progres!")
        else:
            st.metric("Ostatni trening", "Brak", "Zacznij!")

    # Pasek postępu
    st.subheader("📊 Postęp dziennego limitu")
    progress = min(dash_data["eaten"] / current_saved_limit, 1.0)
    st.progress(progress)
    st.write(f"Wykorzystałeś **{progress*100:.1f}%** swojego limitu ({dash_data['eaten']:.0f} / {current_saved_limit:.0f} kcal)")

    if dash_data["eaten"] > current_saved_limit:
        st.warning(f"⚠️ Przekroczyłeś limit o {dash_data['eaten'] - current_saved_limit:.0f} kcal!")

elif choice == "🍳 Nowy Posiłek":
    st.header("🍳 Rejestracja Posiłku")
    mode = st.radio("Źródło:", ["Kalkulator AI", "Zamrażarka"])
    
    if mode == "Kalkulator AI":
        if 'current_ingredients' not in st.session_state:
            st.session_state.current_ingredients = []

        col_in, col_list = st.columns(2)
        with col_in:
            ing_name = st.text_input("Składnik (np. łosoś z airfryera)")
            ing_weight = st.number_input("Waga (g)", min_value=0.0)
            if st.button("Dodaj składnik"):
                with st.spinner('AI liczy...'):
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
                get_dashboard_data.clear() # Czyścimy cache, żeby dashboard zobaczył nowy posiłek
                st.session_state.current_ingredients = []
                st.success("Zapisano!")
                st.rerun()
    else:
        # Logika wyjmowania z zamrażarki
        db = SessionLocal()
        batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).all()
        if batches:
            batch_dict = {f"{b.name} ({b.current_weight_g:.0f}g)": b for b in batches}
            sel = st.selectbox("Wybierz danie:", list(batch_dict.keys()))
            batch = batch_dict[sel]
            weight = st.number_input("Ile gramów?", min_value=0.0, max_value=batch.current_weight_g)
            
            if st.button("✅ Zjedzone"):
                kcal = (batch.total_calories / batch.original_weight_g) * weight
                db.add(MealLog(calories=kcal))
                target = db.query(MealBatch).filter_by(id=batch.id).first()
                target.current_weight_g -= weight
                db.commit()
                db.close()
                get_dashboard_data.clear() # Odświeżenie dashboardu
                st.success(f"Dodano {kcal:.0f} kcal")
                st.rerun()
        else:
            st.warning("Zamrażarka jest pusta!")
        db.close()

elif choice == "➕ Dodaj Batch":
    st.header("📦 Gotowanie na zapas (Batch)")
    if 'batch_ingredients' not in st.session_state:
        st.session_state.batch_ingredients = []

    b_name = st.text_input("Nazwa potrawy (np. Chili Con Carne)")
    c1, c2 = st.columns(2)
    with c1:
        i_name = st.text_input("Składnik")
        i_weight = st.number_input("Waga (g)", min_value=0.0, key="batch_w")
        if st.button("Dodaj do garnka"):
            with st.spinner('AI liczy...'):
                kcal = get_calories_from_ai(i_name, i_weight)
                st.session_state.batch_ingredients.append({'name': i_name, 'weight': i_weight, 'kcal': kcal})
            st.rerun()
    
    with c2:
        total_k = sum(i['kcal'] for i in st.session_state.batch_ingredients)
        total_w = sum(i['weight'] for i in st.session_state.batch_ingredients)
        st.subheader(f"Bilans: {total_w:.0f}g | {total_k:.0f} kcal")
        if st.button("💾 Schowaj do zamrażarki"):
            db = SessionLocal()
            db.add(MealBatch(name=b_name, original_weight_g=total_w, current_weight_g=total_w, total_calories=total_k))
            db.commit()
            db.close()
            get_dashboard_data.clear() # Odświeżenie dashboardu
            st.session_state.batch_ingredients = []
            st.success("Zapisano!")

elif choice == "📦 Zamrażarka":
    st.header("📦 Twoje zapasy")
    db = SessionLocal()
    batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).all()
    for b in batches:
        with st.expander(f"{b.name} - {b.current_weight_g:.0f}g / {b.original_weight_g:.0f}g"):
            st.write(f"Kaloryczność: {(b.total_calories/b.original_weight_g)*100:.0f} kcal / 100g")
            if st.button(f"Wyrzuć {b.id}", key=f"del_{b.id}"):
                b.current_weight_g = 0
                db.commit()
                get_dashboard_data.clear()
                st.rerun()
    db.close()

elif choice == "👟 Aktywność":
    st.header("👟 Rejestracja aktywności")
    steps = st.number_input("Ile kroków zrobiono?", min_value=0, step=500)
    if st.button("Zapisz kroki"):
        db = SessionLocal()
        burned = steps * 0.04  # Prosty przelicznik
        db.add(ActivityLog(steps=steps, calories_burned=burned))
        db.commit()
        db.close()
        get_dashboard_data.clear()
        st.success(f"Spalono {burned:.0f} kcal!")

elif choice == "💪 Trening":
    st.header("💪 Trening")
    st.info("Sekcja treningowa w przygotowaniu.")
