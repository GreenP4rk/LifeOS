import streamlit as st
from google import genai
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import re
import pandas as pd
import plotly.graph_objects as go
from datetime import timedelta
from datetime import datetime
import numpy as np
# Zmień poprzedni import na ten:
from google.genai.types import GenerateContentConfig, Tool, GoogleSearchRetrieval

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
    
     = f"Podaj liczbę kalorii dla {weight_g}g produktu: {ingredient_name}. Zwróć tylko liczbę."
    
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

def get_live_promotions(location="Pszów"):
    from datetime import datetime
    import json
    import re
    
    today = datetime.now().strftime("%d-%m-%Y")
    
    search_prompt = f"""
    DZISIAJ JEST {today}. Przeszukaj internet pod kątem AKTUALNYCH gazetek promocyjnych 
    dla miasta {location} i okolic (Biedronka, Lidl, Kaufland, Netto).
    Znajdź promocje na: Mięso, Nabiał, Warzywa/Owoce.
    Zwróć dane WYŁĄCZNIE jako listę JSON w formacie: 
    [
      {{"sklep": "nazwa", "produkt": "nazwa", "cena": "cena", "okres": "data"}}
    ]
    """

    try:
        # Używamy modelu Gemini 3 Flash (skoro na nim teraz pracujemy)
        # i poprawionej struktury GoogleSearchRetrieval
        response = client.models.generate_content(
            model="gemini-3-flash", 
            contents=search_prompt,
            config=GenerateContentConfig(
                tools=[Tool(google_search_retrieval=GoogleSearchRetrieval())]
            )
        )
        
        if not response.text:
            return []

        json_match = re.search(r"\[.*\]", response.text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return []

    except Exception as e:
        # To sprawi, że błąd pojawi się w konsoli, ale aplikacja będzie działać dalej
        st.error(f"⚠️ Problem z połączeniem z wyszukiwarką: {str(e)}")
        return []

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
    name = Column(String, nullable=False)
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
    try:
        db = SessionLocal()
        from sqlalchemy import text
        result = db.execute(text("SELECT value FROM settings WHERE key = 'daily_limit'")).fetchone()
        db.close()
        if result:
            return int(result[0])
        return 1850 # Domyślny, jeśli baza zawiedzie
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
    ["🏠 Dashboard", "🛒 Lista Zakupów", "🥫 Spiżarnia", "🍳 Nowy Posiłek", "➕ Dodaj Batch", "📦 Zamrażarka", "👟 Aktywność", "💪 Trening", "📏 Pomiary"])

st.sidebar.markdown("---")

# --- SEKCOJA 1: USTWIENIA LIMITU ---
st.sidebar.markdown("### ⚙️ Twój Plan")
current_limit = get_daily_limit()

# Wybór limitu z krokiem 50 kcal
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
        db.execute(text("INSERT INTO settings (key, value) VALUES ('daily_limit', :val) "
                        "ON CONFLICT (key) DO UPDATE SET value = :val"), {"val": str(new_limit)})
        db.commit()
        db.close()
        st.sidebar.success(f"Limit zmieniony na {new_limit}!")
        st.rerun()

st.sidebar.markdown("---")

# --- SEKCOJA 2: TRYB DEBUGOWANIA (SCHOWANY) ---
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

current_saved_limit = get_daily_limit()

if choice == "🏠 Dashboard":
    st.title("🚀 Dashboard")
    
    # Sprawdzanie aktualności pomiarów (Przypominajka)
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
    
    # Obliczenia
    total_allowed = limit + dash_data["burned"]
    remaining = total_allowed - dash_data["eaten"]
    is_over_limit = remaining < 0
    
    # 1. ALERT PRZEKROCZENIA (Czerwone podświetlenie)
    if is_over_limit:
        st.error(f"⚠️ PRZEKROCZONO LIMIT o {abs(remaining):.0f} kcal!")
    elif remaining < 200:
        st.warning(f"🔔 Uwaga: Zostało tylko {remaining:.0f} kcal.")
    else:
        st.success(f"✅ Świetnie! Masz jeszcze {remaining:.0f} kcal zapasu.")

    # 2. METRYKI
    col1, col2, col3 = st.columns(3)
    
    col1.metric("Zjedzone", f"{dash_data['eaten']:.0f} kcal")
    col2.metric("Spalone", f"{dash_data['burned']:.0f} kcal", delta=f"{dash_data['burned']:.0f} bonus")
    
    # Dynamiczny kolor delty dla "Pozostało"
    # Jeśli na minusie, delta pokaże się na czerwono
    col3.metric(
        "Pozostało", 
        f"{remaining:.0f} kcal", 
        delta=f"{remaining:.0f}" if is_over_limit else None,
        delta_color="inverse"
    )
    
    st.markdown("---")
    
    # 3. PASEK POSTĘPU
    st.subheader("📊 Stan limitu")
    progress = min(dash_data["eaten"] / total_allowed, 1.0) if total_allowed > 0 else 0
    
    # Jeśli przekroczono limit, pasek może zmienić się wizualnie (Streamlit progress jest zawsze zielony/niebieski, 
    # ale możemy dodać tekst pod spodem)
    st.progress(progress)
    
    if is_over_limit:
        st.write(f"📈 Wykorzystano **{progress*100:.1f}%** (Przekroczenie o {abs(remaining):.0f} kcal)")
    else:
        st.write(f"Wykorzystano **{progress*100:.1f}%** dostępnej energii.")

# --- 🍳 NOWY POSIŁEK (Z opcją zamrażarki) ---
elif choice == "🍳 Nowy Posiłek":
    st.header("🍳 Rejestracja Posiłku")
    
    # Wybór źródła posiłku
    source = st.radio("Skąd pochodzi posiłek?", ["Kalkulator AI (świeży)", "📦 Wyciągam z zamrażarki"], horizontal=True)

    if source == "Kalkulator AI (świeży)":
        if 'current_ingredients' not in st.session_state:
            st.session_state.current_ingredients = []

        col_in, col_list = st.columns(2)
        with col_in:
            ing_name = st.text_input("Składnik (np. łosoś z airfryera)")
            ing_weight = st.number_input("Waga (g)", min_value=0.0, key="fresh_w")
            if st.button("➕ Dodaj składnik"):
                if ing_name and ing_weight > 0:
                    with st.spinner("Liczenie kalorii..."):
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
                # Zapisujemy cały posiłek na podstawie dodanych składników
                db.add(MealLog(name="Posiłek Składany", calories=total_kcal, date=datetime.now()))
                db.commit()
                db.close()
                st.session_state.current_ingredients = []
                st.success("Zapisano w dzienniku!")
                st.rerun()

    else:
        st.subheader("📦 Wybór z Twoich zapasów")
        db = SessionLocal()
        batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).all()
        
        if not batches:
            st.info("Twoja zamrażarka jest pusta.")
        else:
            for batch in batches:
                col_info, col_actions = st.columns([2, 2])
                with col_info:
                    st.write(f"**{batch.name}**")
                    st.caption(f"Zostało: {batch.current_weight_g:.0f}g")
                
                with col_actions:
                    # 1. Pole do wpisania konkretnej wagi
                    eat_weight = st.number_input("Ile g?", min_value=0.0, max_value=float(batch.current_weight_g), key=f"eat_w_{batch.id}")
                    
                    c_btn1, c_btn2 = st.columns(2)
                    with c_btn1:
                        if st.button("🍽️ Zjedz porcję", key=f"btn_eat_p_{batch.id}"):
                            if eat_weight > 0:
                                kcal_per_g = batch.total_calories / batch.original_weight_g
                                eaten_kcal = eat_weight * kcal_per_g
                                
                                batch.current_weight_g -= eat_weight
                                
                                new_meal = MealLog(
                                    name=f"{batch.name} (Batch)",
                                    calories=eaten_kcal,
                                    date=datetime.now()
                                )
                                db.add(new_meal)
                                db.commit()
                                st.success(f"Smacznego! Log: {eaten_kcal:.0f} kcal")
                                st.rerun()

                    with c_btn2:
                        if st.button("🗑️ Zjedz całość", key=f"btn_all_{batch.id}", help="Usuwa danie i dodaje resztę kalorii do bilansu"):
                            kcal_per_g = batch.total_calories / batch.original_weight_g
                            remaining_kcal = batch.current_weight_g * kcal_per_g
                            
                            full_meal = MealLog(
                                name=f"{batch.name} (Koniec Batcha)",
                                calories=remaining_kcal,
                                date=datetime.now()
                            )
                            db.add(full_meal)
                            db.delete(batch)
                            db.commit() 
                            st.toast(f"Wymieciono do czysta! +{remaining_kcal:.0f} kcal")
                            st.rerun()
        db.close()

# --- ➕ DODAJ BATCH (Wersja ze spiżarnią) ---
elif choice == "➕ Dodaj Batch":
    st.header("📦 Gotowanie na zapas (Bezpieczny Zapis)")
    
    db = SessionLocal()
    from sqlalchemy import text

    drafts = db.execute(text("SELECT id, ingredient_name, weight, kcal FROM batch_drafts")).fetchall()

    b_name = st.text_input("Nazwa potrawy (np. Bigos)", placeholder="Wpisz nazwę...")
    
    col_in, col_summary = st.columns([1, 1])
    
    with col_in:
        st.markdown("### 🛒 Dodaj składnik")
        
        source_type = st.radio("Źródło składnika", ["Z zewnątrz (sklep/ręcznie)", "Ze spiżarni"], horizontal=True)
        
        if source_type == "Ze spiżarni":
            available_items = db.execute(text("SELECT id, name, weight_g FROM pantry_items WHERE weight_g > 0")).fetchall()
            if available_items:
                item_options = {f"{i[1]} (Zostało: {i[2]}g)": i for i in available_items}
                selected_label = st.selectbox("Wybierz produkt", list(item_options.keys()))
                selected_item = item_options[selected_label]
                
                ing_name = selected_item[1]
                ing_weight = st.number_input("Ile gramów bierzesz?", min_value=0.0, max_value=float(selected_item[2]), key="pantry_w")
                
                if st.button("➕ Dodaj do garnka i odejmij ze spiżarni"):
                    if ing_weight > 0:
                        with st.spinner("Liczenie kalorii..."):
                            kcal = get_calories_from_ai(ing_name, ing_weight)
                            db.execute(
                                text("INSERT INTO batch_drafts (ingredient_name, weight, kcal) VALUES (:n, :w, :k)"),
                                {"n": ing_name, "w": ing_weight, "k": kcal}
                            )
                            db.execute(text("UPDATE pantry_items SET weight_g = weight_g - :w WHERE id = :id"), {"w": ing_weight, "id": selected_item[0]})
                            db.commit()
                            st.rerun()
            else:
                st.warning("Brak produktów w spiżarni!")
                
        else:
            ing_name = st.text_input("Nazwa składnika", key="batch_ing_n")
            ing_weight = st.number_input("Waga (g)", min_value=0.0, key="batch_ing_w")
            
            if st.button("➕ Dodaj do garnka"):
                if ing_name and ing_weight > 0:
                    with st.spinner("Liczenie kalorii..."):
                        kcal = get_calories_from_ai(ing_name, ing_weight)
                        db.execute(
                            text("INSERT INTO batch_drafts (ingredient_name, weight, kcal) VALUES (:n, :w, :k)"),
                            {"n": ing_name, "w": ing_weight, "k": kcal}
                        )
                        db.commit()
                        st.rerun()
        
    with col_summary:
        st.markdown("### 🥘 Zawartość garnka")
        
        if not drafts:
            st.info("Twój garnek jest pusty. Dodaj pierwszy składnik.")
        else:
            total_w = sum(d[2] for d in drafts)
            total_k = sum(d[3] for d in drafts)
            
            for d in drafts:
                c1, c2 = st.columns([4, 1])
                c1.text(f"• {d[1]} ({d[2]}g)")
                if c2.button("❌", key=f"del_draft_{d[0]}"):
                    db.execute(text("DELETE FROM batch_drafts WHERE id = :id"), {"id": d[0]})
                    db.commit()
                    st.rerun()
            
            st.divider()
            st.write(f"**Waga całkowita:** {total_w:.0f} g")
            st.write(f"**Kalorie całkowite:** {total_k:.0f} kcal")
            
            if st.button("💾 ZAPISZ I ZAMROŹ"):
                if b_name and total_w > 0:
                    db.add(MealBatch(
                        name=b_name, 
                        original_weight_g=total_w, 
                        current_weight_g=total_w, 
                        total_calories=total_k,
                        date_prepared=datetime.now()
                    ))
                    db.execute(text("DELETE FROM batch_drafts"))
                    db.commit()
                    st.success(f"Danie '{b_name}' bezpiecznie zapisane!")
                    st.balloons()
                    st.rerun()
                else:
                    st.error("Podaj nazwę potrawy przed zapisem!")

    if drafts:
        if st.sidebar.button("🗑️ WYCZYŚĆ CAŁY GARNEK"):
            db.execute(text("DELETE FROM batch_drafts"))
            db.commit()
            st.rerun()
            
    db.close()

# --- 📦 ZAMRAŻARKA (Z opcją usuwania) ---
elif choice == "📦 Zamrażarka":
    st.header("📦 Zawartość Zamrażarki")
    db = SessionLocal()
    batches = db.query(MealBatch).filter(MealBatch.current_weight_g > 0).all()
    
    if not batches:
        st.info("Zamrażarka jest pusta.")
    else:
        for b in batches:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"**{b.name}**")
                st.caption(f"Pozostało: {b.current_weight_g:.0f}g z {b.original_weight_g:.0f}g")
            with col2:
                if st.button("🗑️ Usuń", key=f"del_{b.id}"):
                    target = db.query(MealBatch).filter_by(id=b.id).first()
                    target.current_weight_g = 0
                    db.commit()
                    st.rerun()
            st.divider()
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
                        import json
                        import re
                        img = PIL.Image.open(uploaded_file)
                        
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
                        
                        clean_json = re.search(r"\{.*\}", response.text, re.DOTALL).group()
                        st.session_state.walk_data = json.loads(clean_json)
                        st.success("Analiza zakończona! Sprawdź dane poniżej.")
                        
                    except Exception as e:
                        st.error(f"Błąd analizy: {e}")

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
                    
                    st.session_state.walk_data = None
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
    st.header("💪 Dziennik Treningowy")
    
    db = SessionLocal()
    from sqlalchemy import func
    
    # 1. Pobieramy unikalne nazwy ćwiczeń z bazy (znormalizowane)
    # Wykorzystujemy func.distinct, żeby nie powtarzać nazw
    existing_exercises = db.query(WorkoutLog.exercise_name).distinct().all()
    # Czyszczenie listy: wyciągamy z krotek i sortujemy
    exercise_options = sorted([ex[0] for ex in existing_exercises if ex[0]])
    
    tabs = st.tabs(["📝 Dodaj ćwiczenie", "📈 Historia postępów"])
    
    with tabs[0]:
        with st.form("workout_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            
            with col1:
                # 2. Wybór istniejącego lub opcja dodania nowego
                selection = st.selectbox(
                    "Wybierz ćwiczenie", 
                    ["-- Nowe ćwiczenie --"] + exercise_options
                )
                
                # Jeśli wybrano "Nowe", pokazujemy pole tekstowe
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
                    # 3. Normalizacja nazwy: usuwamy spacje i robimy dużą literę na początku
                    # Dzięki temu "wyciskanie" i "Wyciskanie" będą traktowane jako to samo
                    clean_name = ex_name.strip().capitalize()
                    
                    new_ex = WorkoutLog(
                        exercise_name=clean_name,
                        equipment_type=eq_type,
                        weight_kg=weight,
                        reps=reps,
                        sets=sets,
                        date=datetime.now()
                    )
                    db.add(new_ex)
                    db.commit()
                    st.success(f"Zapisano: {clean_name}")
                    st.rerun() # Odświeżamy, by nowe ćwiczenie wskoczyło na listę selectbox
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
    
    db.close()

# To kod do dodania na końcu sekcji Trening (w głównej wcięciu)
    st.markdown("---")
    st.subheader("🔥 Podsumowanie dzisiejszego treningu")
    if st.button("🤖 Oblicz kalorie z dzisiejszego treningu"):
        db = SessionLocal()
        today = datetime.now().date()
        
        # Pobieramy dzisiejsze ćwiczenia
        today_logs = db.query(WorkoutLog).filter(WorkoutLog.date >= today).all()
        
        # Pobieramy najnowsze wymiary użytkownika
        latest_meas = db.query(BodyMeasurement).order_by(BodyMeasurement.date.desc()).first()
        
        if not today_logs:
            st.warning("Najpierw dodaj jakieś serie treningowe z dzisiaj!")
        elif not latest_meas:
            st.error("Uzupełnij najpierw swoją wagę i wzrost w zakładce 'Pomiary', aby AI mogło poprawnie policzyć kalorie!")
        else:
            # Tworzymy podsumowanie treningu jako tekst dla AI
            summary = "\n".join([f"- {l.exercise_name}: {l.sets} serii, {l.reps} powt., {l.weight_kg}kg ({l.equipment_type})" for l in today_logs])
            st.text("Przekazywane do AI:")
            st.text(summary)
            
            with st.spinner("AI analizuje intensywność..."):
                kcal_burned = get_workout_calories_from_ai(summary, latest_meas.weight, latest_meas.height)
                
                if kcal_burned > 0:
                    # Zapisujemy to jako aktywność do bilansu dziennego
                    db.add(ActivityLog(
                        steps=0, 
                        calories_burned=kcal_burned, 
                        duration_str="Trening Siłowy",
                        date=datetime.now()
                    ))
                    db.commit()
                    get_dashboard_data.clear()
                    st.success(f"Doliczono {kcal_burned:.0f} kcal do Twojego dziennego bilansu spalania!")
                    st.balloons()
                else:
                    st.warning("Nie udało się obliczyć kalorii.")
        db.close()

elif choice == "📏 Pomiary":
    st.header("📏 Śledzenie sylwetki i pomiary")
    
    db = SessionLocal()
    # Pobieramy wszystkie dane do wykresów
    all_measurements = db.query(BodyMeasurement).order_by(BodyMeasurement.date.asc()).all()
    last_m = all_measurements[-1] if all_measurements else None
    
    tabs = st.tabs(["📝 Wprowadź pomiary", "📈 Historia", "📊 Wykresy i Trendy"])
    
    # --- TAB 1: WPISYWANIE ---
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
                weight=weight, height=height, chest=chest, 
                waist=waist, belly=belly, thigh=thigh, 
                biceps=biceps, date=final_dt
            )
            db.add(new_m)
            db.commit()
            st.success("Zapisano!")
            st.rerun()

    # --- TAB 2: HISTORIA ---
    with tabs[1]:
        for m in reversed(all_measurements):
            with st.expander(f"📅 {m.date.strftime('%d.%m.%Y')} | {m.weight}kg"):
                st.write(f"**Klatka:** {m.chest}cm | **Pas:** {m.waist}cm | **Brzuch:** {m.belly}cm")
                st.write(f"**Udo:** {m.thigh}cm | **Biceps:** {m.biceps}cm")

    # --- TAB 3: WYKRESY I TRENDY ---
    with tabs[2]:
        if len(all_measurements) < 2:
            st.info("Potrzebujesz co najmniej dwóch pomiarów, aby wygenerować wykres trendu.")
        else:
            # Konwersja danych z przywróconymi polami
            df = pd.DataFrame([{
                'Data': m.date,
                'Waga': m.weight,
                'Klatka': m.chest,
                'Pas': m.waist,
                'Brzuch': m.belly,
                'Udo': m.thigh,
                'Biceps': m.biceps
            } for m in all_measurements])
            
            # Rozszerzona lista parametrów
            option = st.selectbox("Wybierz parametr do analizy:", ["Waga", "Klatka", "Pas", "Brzuch", "Udo", "Biceps"])
            
            # Obliczenia trendu (bez zmian w logice)
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

            # Analiza trendu
            current_val = df[option].iloc[-1]
            predicted_val = future_trend[-1]
            diff = predicted_val - current_val
            
            st.subheader("🤖 Analiza AI Trendu")
            trend_desc = "spadnie" if diff < 0 else "wzrośnie"
            st.write(f"Przy obecnym tempie, za 2 tygodnie Twój **{option.lower()}** {trend_desc} o ok. **{abs(diff):.2f}**.")

    db.close()

# --- 🛒 LISTA ZAKUPÓW ---
elif choice == "🛒 Lista Zakupów":
    st.header("🛒 Lista Zakupów")
    db = SessionLocal()
    
    # Dodawanie nowego produktu
    with st.form("add_shopping_form", clear_on_submit=True):
        col1, col2 = st.columns([3, 1])
        item_name = col1.text_input("Co musisz kupić?", placeholder="np. Jajka, Mleko, Kurczak")
        submit_item = col2.form_submit_button("➕ Dodaj")
        
        if submit_item and item_name:
            db.add(ShoppingListItem(name=item_name))
            db.commit()
            st.rerun()

    # Wyświetlanie listy
    st.subheader("Do kupienia")
    items_to_buy = db.query(ShoppingListItem).filter(ShoppingListItem.is_bought == False).all()
    
    if not items_to_buy:
        st.info("Lista jest pusta. Wszystko kupione!")
    else:
        for item in items_to_buy:
            col_check, col_name, col_del = st.columns([0.5, 3, 1])
            with col_check:
                # Jeśli zaznaczysz checkbox, produkt ląduje w koszyku
                if st.checkbox("✅", key=f"chk_{item.id}"):
                    item.is_bought = True
                    db.commit()
                    st.toast(f"Kupiono: {item.name}")
                    st.rerun()
            col_name.write(f"**{item.name}**")
            with col_del:
                if st.button("🗑️", key=f"del_shop_{item.id}"):
                    db.delete(item)
                    db.commit()
                    st.rerun()
    
    st.divider()
    if st.button("🧹 Wyczyść kupione z historii"):
        db.query(ShoppingListItem).filter(ShoppingListItem.is_bought == True).delete()
        db.commit()
        st.success("Historia wyczyszczona.")
        st.rerun()

    st.divider()
    st.subheader("🔥 Gorące Okazje w Twojej okolicy")
    
    if st.button("🔍 Skanuj aktualne gazetki (LIVE)"):
        with st.spinner("AI przegląda właśnie aktualne gazetki dla Pszowa..."):
            promos = get_live_promotions("Pszów")
            
            if promos:
                for p in promos:
                    col1, col2, col3 = st.columns([2, 1, 1])
                    col1.write(f"**{p['produkt']}** ({p['sklep']})")
                    col2.write(f"💰 {p['cena']}")
                    
                    # MAGIA: Przycisk, który od razu dodaje promocję do Twojej bazy danych
                    if col3.button("➕ Dodaj", key=f"add_promo_{p['produkt']}"):
                        db = SessionLocal()
                        db.add(ShoppingListItem(name=f"{p['produkt']} ({p['sklep']} - {p['cena']})"))
                        db.commit()
                        db.close()
                        st.toast(f"Dodano {p['produkt']} do listy!")
            else:
                st.warning("Nie udało się pobrać danych. Spróbuj ponownie za chwilę.")
    db.close()

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
                # Opcjonalnie: można tu dodać zapytanie do AI o kcal_per_100g przy dodawaniu
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
