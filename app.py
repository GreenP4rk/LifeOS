import streamlit as st
import google.generativeai as genai
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

# --- KONFIGURACJA STRONY (Musi być pierwsza!) ---
st.set_page_config(page_title="LifeOS", layout="wide")

# --- KONFIGURACJA AI ---
# Zamiast wpisywać klucz tutaj, bierzemy go z "bezpiecznego schowka" Streamlit
try:
    api_key = st.secrets["GEMINI_KEY"]
except:
    # To pozwoli Ci nadal uruchamiać kod lokalnie na komputerze
    api_key = "TWÓJ_KLUCZ_API_DO_TESTÓW_LOKALNYCH"

genai.configure(api_key=api_key)
model = genai.GenerativeModel('models/gemini-2.5-flash')

def get_calories_from_ai(ingredient_name, weight_g):
    prompt = f"Podaj liczbę kalorii dla {weight_g}g produktu: {ingredient_name}. Zwróć tylko liczbę."
    try:
        response = model.generate_content(prompt)
        clean_result = response.text.strip()
        return float(clean_result)
    except Exception as e:
        st.error(f"Błąd AI: {e}")
        return 0.0

# --- BAZA DANYCH ---
engine = create_engine('sqlite:///lifeos_core.db', echo=False)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

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

class Exercise(Base):
    __tablename__ = 'exercises'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    equipment = Column(String)

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

Base.metadata.create_all(engine)

# --- FUNKCJE POMOCNICZE ---
def calculate_walking_calories(steps):
    return steps * 0.04

def calories_to_steps(calories):
    return int(calories * 25)

def get_daily_limit():
    db = SessionLocal()
    setting = db.query(Settings).filter_by(key="daily_limit").first()
    db.close()
    return setting.value if setting else 2500.0  # 2500 to wartość domyślna

def set_daily_limit(new_limit):
    db = SessionLocal()
    setting = db.query(Settings).filter_by(key="daily_limit").first()
    if setting:
        setting.value = new_limit
    else:
        db.add(Settings(key="daily_limit", value=new_limit))
    db.commit()
    db.close()

# --- NAWIGACJA ---
st.sidebar.title("🧭 Menu LifeOS")
choice = st.sidebar.radio("Przejdź do:", 
    ["🏠 Dashboard", "🍳 Nowy Posiłek", "➕ Dodaj Batch", "📦 Zamrażarka", "👟 Aktywność", "💪 Trening"])
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Ustawienia Limitów")

# Pobieramy aktualny limit z bazy danych
current_saved_limit = get_daily_limit()

# Pole do wpisania nowego limitu
new_limit_input = st.sidebar.number_input(
    "Dzienny limit kcal", 
    value=float(current_saved_limit), 
    step=50.0
)

# Przycisk zapisu
if st.sidebar.button("💾 Zapisz nowy limit"):
    set_daily_limit(new_limit_input)
    st.sidebar.success(f"Zapisano: {new_limit_input:.0f} kcal")
    st.rerun()

# Używamy tej zmiennej w całej reszcie aplikacji
daily_limit = current_saved_limit

# --- LOGIKA DANYCH ---
db = SessionLocal()
today = datetime.now().date()

today_logs = db.query(ActivityLog).filter(ActivityLog.date >= today).all()
total_steps_today = sum(log.steps for log in today_logs)
total_kcal_burned_walking = sum(log.calories_burned for log in today_logs)

total_batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).count()
total_val_res = db.query(MealBatch).all()
total_value = sum(b.total_price for b in total_val_res if b.total_price)

last_workout = db.query(WorkoutSet).order_by(WorkoutSet.date.desc()).first()

today_meals = db.query(MealLog).filter(MealLog.date >= today).all()
total_kcal_eaten = sum(m.calories for m in today_meals)

remaining_kcal = daily_limit - total_kcal_eaten
db.close()

# --- DASHBOARD ---
st.title("🚀 LifeOS: Twój Dashboard")
col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    st.metric("Zjedzone dzisiaj", f"{total_kcal_eaten:.0f} kcal", f"Limit: {daily_limit}")
with col2:
    balance = total_kcal_eaten - total_kcal_burned_walking
    st.metric("Bilans netto", f"{balance:.0f} kcal", delta_color="inverse")
with col3:
    st.metric("Pozostało kcal", f"{remaining_kcal:.0f} kcal")
with col4:
    st.metric("Spalone (spacer)", f"{total_kcal_burned_walking:.0f} kcal")
with col5:
    st.metric("W zamrażarce", f"{total_batches} potraw", f"{total_value:.2f} zł")
with col6:
    if last_workout:
        st.metric("Ostatni trening", f"{last_workout.weight} kg", "Progres!")
    else:
        st.metric("Ostatni trening", "Brak", "Zacznij!")

# --- WIZUALIZACJA LIMITU ---
st.subheader("📊 Postęp dziennego limitu")
progress_calculated = min(total_kcal_eaten / daily_limit, 1.0) # Nie więcej niż 100%
percentage = progress_calculated * 100

# Kolor paska zmienia się na czerwony, jeśli przekroczysz limit
bar_color = "green" if total_kcal_eaten <= daily_limit else "red"

st.progress(progress_calculated)
st.write(f"Wykorzystałeś **{percentage:.1f}%** swojego limitu ({total_kcal_eaten:.0f} / {daily_limit:.0f} kcal)")

if total_kcal_eaten > daily_limit:
    st.warning(f"⚠️ Przekroczyłeś limit o {total_kcal_eaten - daily_limit:.0f} kcal!")

st.markdown("---")

# --- GŁÓWNA LOGIKA ---

if choice == "🏠 Dashboard":
    st.subheader("Witaj w swoim Centrum Dowodzenia")
    st.info("Wszystkie dane są aktualizowane w czasie rzeczywistym.")

elif choice == "🍳 Nowy Posiłek":
    st.header("🍳 Rejestracja Posiłku")
    mode = st.radio("Co jesz?", ["Świeży posiłek (Kalkulator)", "Zapas z zamrażarki"])
    
    if mode == "Świeży posiłek (Kalkulator)":
        if 'current_ingredients' not in st.session_state:
            st.session_state.current_ingredients = []

        col_in, col_list = st.columns(2)
        with col_in:
            st.subheader("Dodaj składnik")
            ing_name = st.text_input("Co dodajesz?")
            ing_weight = st.number_input("Waga (g)", min_value=0.0)
            if st.button("Dodaj do listy"):
                with st.spinner('AI liczy...'):
                    est_kcal = get_calories_from_ai(ing_name, ing_weight)
                st.session_state.current_ingredients.append({'name': ing_name, 'weight': ing_weight, 'kcal': est_kcal})
                st.rerun()

        with col_list:
            st.subheader("Twój Posiłek")
            total_kcal = sum(i['kcal'] for i in st.session_state.current_ingredients)
            for i in st.session_state.current_ingredients:
                st.text(f"• {i['name']}: {i['weight']}g (~{i['kcal']:.0f} kcal)")
            
            if st.button("✅ Następny posiłek (Zapisz)"):
                if total_kcal > 0:
                    db = SessionLocal()
                    db.add(MealLog(calories=total_kcal))
                    db.commit()
                    db.close()
                    st.session_state.current_ingredients = []
                    st.success("Zapisano!")
                    st.rerun()

    else:
        st.subheader("Wybierz gotowe danie")
        db = SessionLocal()
        available_batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).all()
        if available_batches:
            batch_dict = {f"{b.name} (Dostępne: {b.current_weight_g:.0f}g)": b for b in available_batches}
            sel_label = st.selectbox("Co wyjmujesz?", list(batch_dict.keys()))
            sel_batch = batch_dict[sel_label]
            
            w_to_eat = st.number_input("Ile gramów nakładasz?", min_value=0.0, max_value=sel_batch.current_weight_g)
            kcal_per_g = sel_batch.total_calories / sel_batch.original_weight_g
            calc_kcal = w_to_eat * kcal_per_g
            st.info(f"Ta porcja ma ok. **{calc_kcal:.0f} kcal**")
            
            if st.button("✅ Zjedzone"):
                db.add(MealLog(calories=calc_kcal))
                target = db.query(MealBatch).filter(MealBatch.id == sel_batch.id).first()
                target.current_weight_g -= w_to_eat
                db.commit()
                db.close()
                st.success("Smacznego!")
                st.rerun()
        else:
            st.warning("Pusto w zamrażarce!")
        db.close()

elif choice == "➕ Dodaj Batch":
    st.header("📦 Tworzenie Batacha")
    if 'batch_ingredients' not in st.session_state:
        st.session_state.batch_ingredients = []

    col_a, col_b = st.columns(2)
    with col_a:
        b_name = st.text_input("Nazwa całej potrawy")
        i_name = st.text_input("Składnik")
        i_weight = st.number_input("Waga (g)", min_value=0.0, key="b_i_w")
        if st.button("Dodaj do garnka"):
            with st.spinner('AI liczy...'):
                kcal = get_calories_from_ai(i_name, i_weight)
            st.session_state.batch_ingredients.append({'name': i_name, 'weight': i_weight, 'kcal': kcal})
            st.rerun()

    with col_b:
        total_w = sum(i['weight'] for i in st.session_state.batch_ingredients)
        total_k = sum(i['kcal'] for i in st.session_state.batch_ingredients)
        st.subheader(f"Suma: {total_w:.0f}g | {total_k:.0f} kcal")
        if st.button("💾 Zapisz Batch"):
            db = SessionLocal()
            db.add(MealBatch(name=b_name, original_weight_g=total_w, current_weight_g=total_w, total_calories=total_k))
            db.commit()
            db.close()
            st.session_state.batch_ingredients = []
            st.success("Zapisano w zamrażarce!")

elif choice == "📦 Zamrażarka":
    st.header("Aktualny inwentarz")
    db = SessionLocal()
    batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).all()
    
    # Obliczamy wartość pozostałych zapasów (proporcjonalnie do wagi)
    current_total_value = 0
    for b in batches:
        if b.total_price:
            current_total_value += (b.total_price * (b.current_weight_g / b.original_weight_g))

    st.metric("Szacunkowa wartość zapasów", f"{current_total_value:.2f} zł")

    if batches:
        for b in batches:
            with st.expander(f"🍲 {b.name} (Zostało: {b.current_weight_g:.0f}g)"):
                col_info, col_actions = st.columns([2, 1])
                
                with col_info:
                    density = b.total_calories / b.original_weight_g
                    st.write(f"**Gęstość:** {density:.2f} kcal/g")
                    st.write(f"**W zamrażarce od:** {b.date_prepared.strftime('%Y-%m-%d')}")
                    st.progress(b.current_weight_g / b.original_weight_g)
                
                with col_actions:
                    # Przycisk korekty (wyrzucenie/podjedzenie przez kogoś)
                    if st.button(f"🗑️ Usuń resztę {b.id}", help="Usuń bez liczenia kalorii (np. wyrzucone)"):
                        target = db.query(MealBatch).filter(MealBatch.id == b.id).first()
                        target.current_weight_g = 0
                        db.commit()
                        st.warning(f"Usunięto {b.name} z inwentarza.")
                        st.rerun()
    else:
        st.info("Brak zapasów.")
    db.close()

elif choice == "👟 Aktywność":
    st.header("Dziennik kroków")
    with st.form("steps"):
        s = st.number_input("Kroki", min_value=0, step=100)
        if st.form_submit_button("Zapisz"):
            db = SessionLocal()
            db.add(ActivityLog(steps=s, calories_burned=calculate_walking_calories(s)))
            db.commit()
            db.close()
            st.rerun()

elif choice == "💪 Trening":
    st.header("Trening")
    st.info("Tutaj możesz zarządzać swoimi ćwiczeniami.")
