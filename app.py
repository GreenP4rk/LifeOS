import streamlit as st
import google.generativeai as genai
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

# --- 1. KONFIGURACJA STRONY ---
st.set_page_config(page_title="LifeOS", layout="wide")

# --- 2. KONFIGURACJA AI ---
@st.cache_resource
def init_genai():
    try:
        api_key = st.secrets["GEMINI_KEY"]
    except:
        api_key = "TWOJ_KLUCZ_LOKALNY"
    genai.configure(api_key=api_key)
    return genai.GenerativeModel('models/gemini-2.5-flash')

model = init_genai()

def get_calories_from_ai(ingredient_name, weight_g):
    prompt = f"Podaj liczbę kalorii dla {weight_g}g produktu: {ingredient_name}. Zwróć tylko liczbę."
    try:
        response = model.generate_content(prompt)
        return float(response.text.strip())
    except Exception as e:
        st.error(f"Błąd AI: {e}")
        return 0.0

# --- 3. BAZA DANYCH (Zoptymalizowane połączenie) ---
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
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

# --- 4. MODELE ---
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

# Base.metadata.create_all(engine)

# --- 5. FUNKCJE POMOCNICZE ---
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

@st.cache_data(ttl=300)  # Pamiętaj dane przez 5 minut
def get_dashboard_data():
    db = SessionLocal()
    today = datetime.now().date()
    today_meals = db.query(MealLog).filter(MealLog.date >= today).all()
    today_activity = db.query(ActivityLog).filter(ActivityLog.date >= today).all()
    
    data = {
        "eaten": sum(m.calories for m in today_meals),
        "burned": sum(a.calories_burned for a in today_activity),
        "batches_count": db.query(MealBatch).filter(MealBatch.current_weight_g > 0).count()
    }
    db.close()
    return data

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

# --- 7. GŁÓWNA LOGIKA APLIKACJI ---

if choice == "🏠 Dashboard":
    st.title("🚀 LifeOS: Dashboard")
    
    # Dane pobieramy TYLKO tutaj
    db = SessionLocal()
    today = datetime.now().date()
    dash_data = get_dashboard_data()
    total_kcal_eaten = dash_data["eaten"]
    total_kcal_burned = dash_data["burned"]
    total_batches = dash_data["batches_count"]
    db.close()

    remaining_kcal = current_saved_limit - total_kcal_eaten
    
    # Metryki
    m1, m2, m3 = st.columns(3)
    m1.metric("Zjedzone", f"{total_kcal_eaten:.0f} kcal")
    m2.metric("Spalone", f"{total_kcal_burned:.0f} kcal")
    m3.metric("Pozostało", f"{remaining_kcal:.0f} kcal")

    # Pasek postępu
    st.subheader("📊 Postęp limitu")
    progress = min(total_kcal_eaten / current_saved_limit, 1.0)
    st.progress(progress)
    st.write(f"Zużycie: {progress*100:.1f}% limitu ({current_saved_limit} kcal)")

elif choice == "🍳 Nowy Posiłek":
    st.header("🍳 Rejestracja Posiłku")
    mode = st.radio("Źródło:", ["Kalkulator AI", "Zamrażarka"])
    
    if mode == "Kalkulator AI":
        if 'current_ingredients' not in st.session_state:
            st.session_state.current_ingredients = []

        col_in, col_list = st.columns(2)
        with col_in:
            ing_name = st.text_input("Składnik")
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
        st.success(f"Spalono {burned:.0f} kcal!")

elif choice == "💪 Trening":
    st.header("💪 Trening")
    st.info("Sekcja treningowa w przygotowaniu.")
