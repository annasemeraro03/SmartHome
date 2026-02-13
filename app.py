import os, json, requests, threading, time, secrets, paho.mqtt.client as mqtt, asyncio
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, abort
from supabase import create_client, Client
from dotenv import load_dotenv
from flask_mail import Mail, Message
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardRemove, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from paho.mqtt.enums import CallbackAPIVersion

load_dotenv()

app = Flask(__name__)
app.secret_key = "dev-secret-key"

TELEGRAM_TOKEN = "8340130393:AAGBw4wxpwEsvTR-DYmz5OIbMRHV0qETvls"
TG_USERNAME, TG_PASSWORD = range(2)

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'smarthome022026@gmail.com'
app.config['MAIL_PASSWORD'] = 'yvuslxswtaxxkgmh' 
mail = Mail(app)

# Configurazione MQTT e API
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
WEATHER_API_KEY = "9060e89b2bd50c039a8edd77e1c112b9"

# Client per inviare comandi (usato da rotte Flask e AI Engine)
mqtt_pub_client = mqtt.Client()
mqtt_pub_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_pub_client.loop_start()

latest_sensor_data = {} 
last_actuator_push = {}
last_suggestions = {}

supabase: Client = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_PUBLISHABLE_KEY")
)

# --- FIX: Inizializzazione Cache (Corretto nome colonna timestamp) ---
def init_actuator_cache():
    """Carica l'ultimo stato noto degli attuatori per ogni stanza dal DB."""
    try:
        rooms = supabase.table("rooms").select("id").execute()
        for room in rooms.data:
            r_id = room['id']
            # NOTA: Usiamo 'timestamp' invece di 'created_at'
            res = supabase.table("actuator_data")\
                .select("*")\
                .eq("room_id", r_id)\
                .order("timestamp", desc=True)\
                .limit(1).execute()
            
            if res.data:
                last_entry = res.data[0]
                last_actuator_push[r_id] = {
                    "state": {
                        "ac_on": last_entry.get("ac_on", False),
                        "heating_on": last_entry.get("heating_on", False),
                        "window_open": last_entry.get("window_open", False),
                        "auto_mode": last_entry.get("auto_mode", True)
                    },
                    "last_db_write": time.time()
                }
        print("✅ Cache attuatori inizializzata dal Database.")
    except Exception as e:
        print(f"⚠️ Errore inizializzazione cache: {e}")

# ... (tieni i tuoi import e config iniziali fino a init_actuator_cache) ...

def sensor_db_worker():
    """Thread per salvataggio storico sensori ogni 5 minuti."""
    while True:
        try:
            if latest_sensor_data:
                for house_id, rooms in latest_sensor_data.items():
                    for topic, data in rooms.items():
                        r_id = data.get('room_id')
                        if r_id:
                            supabase.table("sensor_data").insert({
                                "room_id": r_id,
                                "temperature": data.get("temperature"),
                                "co2": data.get("CO2")
                            }).execute()
                            print(f"📡 [SENSOR_THREAD] Snapshot salvato per stanza: {r_id}")
        except Exception as e:
            print(f"❌ Errore Sensor Worker: {e}")
        time.sleep(300)

def on_connect(client, userdata, flags, rc):
    # Sottoscrizione fondamentale per i dati real-time
    client.subscribe("smarthome/house/+/+/sensors")
    print("✅ MQTT Worker connesso e in ascolto.")

def on_message(client, userdata, msg):
    try:
        parts = msg.topic.split('/')
        if len(parts) < 4: return
        
        h_id = str(parts[2])
        room_topic = parts[3]
        payload = json.loads(msg.payload.decode())

        # Salviamo i dati per la consultazione (usati poi da update_actuators e dashboard)
        if h_id not in latest_sensor_data: latest_sensor_data[h_id] = {}
        
        latest_sensor_data[h_id][room_topic] = {
            'temperature': payload.get('temperature', 0),
            'CO2': payload.get('CO2', 0),
            'received_at': time.time()
        }
    except Exception as e:
        print(f"⚠️ Errore MQTT on_message: {e}")

def on_message(client, userdata, msg):
    print(f"📩 [MQTT] Messaggio grezzo ricevuto sul topic: {msg.topic}")

    try:
        parts = msg.topic.split('/')
        if len(parts) < 4:
            print("⚠️ [MQTT] Topic troppo corto, lo ignoro.")
            return
 
        h_id = str(parts[2])
        room_topic = parts[3]
        payload = json.loads(msg.payload.decode())

        print(f"📦 [MQTT] Payload decodificato: {payload}")

        # Cerchiamo la stanza nel DB per assicurarci che esista
        res = supabase.table("rooms").select("id").eq("house_id", h_id).eq("mqtt_topic_name", room_topic).execute()

        if res.data:
            r_id = res.data[0]['id']
            
            if h_id not in latest_sensor_data:
                latest_sensor_data[h_id] = {}

            latest_sensor_data[h_id][room_topic] = {
                'temperature': payload.get('temperature', 0),
                'CO2': payload.get('CO2', 0),
                'room_id': r_id,
                'received_at': time.time()
            }

            print(f"✅ [MQTT] Memoria aggiornata per {room_topic}! Memoria ora ha chiavi: {latest_sensor_data.keys()}")

        else:
            print(f"❌ [MQTT] ERRORE: Il topic '{room_topic}' per la casa '{h_id}' non esiste nel DB Supabase!")

    except Exception as e:
        print(f"⚠️ [MQTT] Errore critico in on_message: {e}")

def mqtt_worker():
    """Thread che gestisce la ricezione dati MQTT."""
    client_id = f'python-mqtt-{secrets.token_hex(4)}'
    
    # --- FIX PER PAHO-MQTT 2.0+ ---
    try:
        # Se hai la versione 2.0+, devi passare CallbackAPIVersion.VERSION1 o VERSION2
        client = mqtt.Client(CallbackAPIVersion.VERSION1, client_id)
    except (ImportError, AttributeError):
        # Se hai la versione vecchia (1.x)
        client = mqtt.Client(client_id)
    # ------------------------------

    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        print(f"📡 Tentativo di connessione al broker: {MQTT_BROKER}...")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except Exception as e:
        print(f"❌ Errore nel thread MQTT: {e}")

def actuator_watchdog_worker():
    while True:
        try:
            current_time = time.time()
            for room_id, push_info in list(last_actuator_push.items()):
                if (current_time - push_info["last_db_write"]) >= 290:
                    current_state = push_info["state"]
                    
                    supabase.table("actuator_data").insert({
                        "room_id": room_id,
                        **current_state
                    }).execute()

                    last_actuator_push[room_id]["last_db_write"] = current_time
                    print(f"📡 [ACTUATORS_THREAD] Snapshot 5min per stanza {room_id} inviato al DB.")
        except Exception as e:
            print(f"❌ Errore Watchdog: {e}")
        time.sleep(30)

# --- FUNZIONE PER INVIARE NOTIFICHE ---
def send_telegram_notification(house_id, message):
    """
    Invia un messaggio a tutti gli utenti che appartengono alla casa specificata
    e che hanno effettuato l'accoppiamento con il bot Telegram.
    """
    try:
        # 1. Recupera gli utenti della casa che hanno un Chat ID registrato
        res = supabase.table("users")\
            .select("telegram_chat_id")\
            .eq("house_id", house_id)\
            .not_.is_("telegram_chat_id", "null")\
            .execute()

        if not res.data:
            return # Nessun utente ha collegato Telegram per questa casa

        # 2. Invia il messaggio ad ogni utente trovato
        token = TELEGRAM_TOKEN # Assicurati che questa variabile sia definita globalmente
        url = f"https://api.telegram.org/bot{token}/sendMessage"

        for user in res.data:
            chat_id = user.get("telegram_chat_id")
            if chat_id:
                payload = {
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML"
                }
                try:
                    response = requests.post(url, json=payload, timeout=5)
                    if response.status_code != 200:
                        print(f"⚠️ Errore API Telegram per chat_id {chat_id}: {response.text}")
                except Exception as inner_e:
                    print(f"⚠️ Errore connessione Telegram per chat_id {chat_id}: {inner_e}")

    except Exception as e:
        print(f"❌ Errore generale send_telegram_notification: {e}")
    
# --- LOGICA DEL BOT (AUTHENTICATION) ---
async def tg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"DEBUG: Ricevuto /start da {update.message.chat_id}")
    await update.message.reply_text("👋 Benvenuto su SmartHome Bot!\nPer ricevere notifiche, inserisci il tuo Username:")
    return TG_USERNAME

async def tg_get_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text
    print(f"DEBUG: Username ricevuto: {username}")
    context.user_data['tg_user'] = username
    await update.message.reply_text("Ora inserisci la tua Password:")
    return TG_PASSWORD

async def tg_get_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get('tg_user')
    password = update.message.text
    chat_id = str(update.message.chat_id)

    try:
        res = supabase.table("users").select("*").eq("username", username).eq("password", password).execute()

        if res.data and len(res.data) > 0:
            user = res.data[0]
            user_id = user['id']
            h_id = user['house_id']
            
            supabase.table("users").update({"telegram_chat_id": chat_id}).eq("id", user_id).execute()
            
            # Messaggio di successo + STATO ATTUALE
            riassunto = get_actuators_summary(h_id)
            msg_final = (f"✅ Autenticazione riuscita per {username}!\n"
                         f"Riceverai qui le notifiche automatiche.\n"
                         f"{riassunto}")
            
            await update.message.reply_text(msg_final, parse_mode="HTML")
        else:
            await update.message.reply_text("❌ Credenziali errate. Digita /start per riprovare.")
    except Exception as e:
        await update.message.reply_text("⚠️ Errore tecnico durante l'autenticazione.")
    
    return ConversationHandler.END

async def tg_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra la lista dei comandi disponibili."""
    help_text = (
        "🤖 <b>SmartHome Bot - Guida Rapida</b>\n\n"
        "/start - Collega il tuo account SmartHome\n"
        "/stato - Ricevi lo stato attuale di tutte le stanze nella casa\n"
        "/exit  - Disconnetti l'account e smetti di ricevere notifiche\n"
        "/help  - Visualizza questo messaggio"
    )
    await update.message.reply_text(help_text, parse_mode='HTML')

async def tg_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Effettua il logout rimuovendo il chat_id dal database."""
    chat_id = str(update.message.chat_id)
    
    try:
        # Rimuoviamo l'associazione telegram_chat_id nel DB Supabase
        res = supabase.table("users").update({"telegram_chat_id": None}).eq("telegram_chat_id", chat_id).execute()
        
        if res.data:
            await update.message.reply_text(
                "👋 <b>Logout effettuato con successo.</b>\n"
                "Il tuo account è stato scollegato e non riceverai più notifiche.\n"
                "Usa /start se vorrai ricollegarti in futuro.",
                parse_mode='HTML',
                reply_markup=ReplyKeyboardRemove() # Rimuove anche i bottoni se presenti
            )
        else:
            await update.message.reply_text("Non risulti collegato a nessuna casa.")
            
    except Exception as e:
        print(f"❌ Errore durante logout TG: {e}")
        await update.message.reply_text("⚠️ Si è verificato un errore tecnico durante il logout.")
    
    return ConversationHandler.END

async def tg_send_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.message.chat_id)
    
    # Cerchiamo l'utente che ha questo chat_id
    user_res = supabase.table("users").select("house_id").eq("telegram_chat_id", chat_id).execute()
    
    if user_res.data:
        house_id = user_res.data[0]['house_id']
        riassunto = get_actuators_summary(house_id)
        await update.message.reply_text(riassunto, parse_mode='HTML')
    else:
        await update.message.reply_text("❌ Non sei collegato a nessuna casa. Usa /start per autenticarti.")

def telegram_bot_worker():
    """Thread che gestisce il bot Telegram con menu comandi e gestione stati."""
    try:
        # Creiamo un nuovo loop asincrono specifico per questo thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Funzione interna per impostare i suggerimenti nel menu "/" all'avvio
        async def post_init(application: Application):
            commands = [
                BotCommand("start", "Collega il tuo account"),
                BotCommand("stato", "Visualizza lo stato della casa"),
                BotCommand("help", "Mostra la guida ai comandi"),
                BotCommand("exit", "Scollega l'account e stop notifiche")
            ]
            await application.bot.set_my_commands(commands)
            print("✅ [BOT] Menu comandi '/' configurato con successo")

        # Inizializziamo l'applicazione con il post_init
        application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

        # 1. Configura il ConversationHandler per il login
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', tg_start)],
            states={
                TG_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, tg_get_username)],
                TG_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, tg_get_password)],
            },
            fallbacks=[
                CommandHandler('exit', tg_exit),
                CommandHandler('help', tg_help),
                CommandHandler('start', tg_start)
            ],
        )

        # 2. Registriamo gli handler (l'ordine è importante)
        # Handler globali (funzionano sempre)
        application.add_handler(CommandHandler('help', tg_help))
        application.add_handler(CommandHandler('exit', tg_exit))
        application.add_handler(CommandHandler('stato', tg_send_status))
        
        # Handler di conversazione (per il login)
        application.add_handler(conv_handler)
        
        print("🤖 [BOT] Avvio polling (segnali disabilitati per thread)...")

        # stop_signals=None è fondamentale per farlo girare in un thread secondario
        application.run_polling(stop_signals=None, close_loop=False)
        
    except Exception as e:
        print(f"❌ [BOT CRASH]: {e}")

def get_actuators_summary(house_id):
    """Genera un riassunto testuale aggiornato dello stato di tutti gli attuatori."""
    summary = "\n🏠 <b>STATO ATTUALE DELLA CASA:</b>\n\n"
    try:
        # Recuperiamo tutte le stanze della casa
        rooms_res = supabase.table("rooms").select("id, name").eq("house_id", house_id).execute()
        
        if not rooms_res.data:
            return summary + "<i>Nessuna stanza configurata.</i>"

        for room in rooms_res.data:
            r_id = room['id']
            r_name = room['name']
            
            # Recuperiamo lo stato dalla cache last_actuator_push
            info = last_actuator_push.get(r_id, {})
            state = info.get("state", {})
            
            if not state:
                summary += f"📍 {r_name}: <i>Dati non disponibili</i>\n"
                continue

            # Formattazione icone
            ac = "🟢 ON" if state.get("ac_on") else "🔴 OFF"
            heat = "🟢 ON" if state.get("heating_on") else "🔴 OFF"
            win = "📖 Aperte" if state.get("window_open") else "🔒 Chiuse"
            
            summary += f"📍 <b>{r_name}</b>:\n  ❄️ Condiz: {ac} | 🔥 Riscald: {heat} | 🪟 Finestre: {win}\n"
            
        return summary
    except Exception as e:
        return f"\n⚠️ Errore recupero stato: {e}"

@app.route("/update_actuators", methods=["POST"])
def update_actuators():
    if "user_id" not in session: abort(401)
    
    data = request.json
    room_topic = data['room']
    
    # 1. Recupero house_id dell'utente
    user_res = supabase.table("users").select("house_id").eq("id", session['user_id']).execute()
    if not user_res.data: abort(404)
    house_id = user_res.data[0]['house_id']
    
    # 2. Recupero configurazione stanza
    room_res = supabase.table("rooms").select("*").eq("house_id", house_id).eq("mqtt_topic_name", room_topic).execute()
    if not room_res.data: abort(404)
    r = room_res.data[0] 
    room_id = r['id']

    try:
        # 3. Recupero ultimi dati sensori
        sensor_info = latest_sensor_data.get(str(house_id), {}).get(room_topic, {})
        curr_t = sensor_info.get('temperature')
        curr_c = sensor_info.get('CO2')

        current_state = {
            "ac_on": data["conditioner"],
            "heating_on": data["heating"],
            "window_open": data["windows"],
            "auto_mode": data.get("auto_mode", False)
        }

        previous_info = last_actuator_push.get(room_id, {})
        previous_state = previous_info.get("state", {})

        new_sug = None

        # --- LOGICA MUTUA ESCLUSIONE E SUGGERIMENTI ---
        # Controlliamo se almeno un attuatore è acceso
        any_active = current_state["ac_on"] or current_state["heating_on"] or current_state["window_open"]

        if curr_t is not None and curr_c is not None:
            if current_state["auto_mode"]:
                # --- NOTIFICHE TELEGRAM (Solo in Auto Mode) ---
                if previous_state:
                    if current_state["ac_on"] != previous_state.get("ac_on"):
                        azione = "ACCESO" if current_state["ac_on"] else "SPENTO"
                        send_telegram_notification(house_id, f"❄️ Condizionatore <b>{azione}</b> in <b>{r['name']}</b>")
                    
                    if current_state["heating_on"] != previous_state.get("heating_on"):
                        azione = "ACCESO" if current_state["heating_on"] else "SPENTO"
                        send_telegram_notification(house_id, f"🔥 Riscaldamento <b>{azione}</b> in <b>{r['name']}</b>")
                    
                    if current_state["window_open"] != previous_state.get("window_open"):
                        azione = "APERTE" if current_state["window_open"] else "CHIUSE"
                        send_telegram_notification(house_id, f"🪟 Finestre <b>{azione}</b> in <b>{r['name']}</b>")
            else:
                # --- SUGGERIMENTI (Solo se tutto è spento) ---
                if not any_active:
                    if curr_c > r['co2_threshold']:
                        new_sug = "open_windows"
                    elif curr_t < r['min_temperature']:
                        new_sug = "heat_on"
                    elif curr_t > r['max_temperature']:
                        new_sug = "ac_on"
                else:
                    new_sug = None # Nessun suggerimento se un pulsante è già attivo

        # 4. Aggiornamento Cache
        if str(house_id) not in latest_sensor_data: 
            latest_sensor_data[str(house_id)] = {}
        if room_topic not in latest_sensor_data[str(house_id)]:
            latest_sensor_data[str(house_id)][room_topic] = {}
        
        latest_sensor_data[str(house_id)][room_topic]['suggestion'] = new_sug

        if not new_sug:
            last_suggestions[room_id] = None

        # 5. Persistenza e MQTT
        last_actuator_push[room_id] = {"state": current_state, "last_db_write": time.time()}
        
        topic = f"smarthome/house/{house_id}/{room_topic}/actuators"
        mqtt_pub_client.publish(topic, json.dumps(current_state))
        
        supabase.table("actuator_data").insert({"room_id": room_id, **current_state}).execute()

        return jsonify({"status": "success", "suggestion": new_sug})

    except Exception as e:
        print(f"❌ Errore update_actuators: {e}")
        return abort(500)

# --- HELPER FUNCTIONS ---
def get_user(username, admin=False):
    query = supabase.table("users").select("*").eq("username", username)
    if admin: query = query.eq("role", "admin")
    res = query.execute()
    return res.data[0] if res.data and len(res.data) > 0 else None

def get_weather(city):
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=it"
        response = requests.get(url)
        r = response.json()
        if response.status_code != 200:
            return {"temp": "20°C", "desc": "In attivazione...", "icon": "⏳"}
        main_weather = r['weather'][0]['main'].lower()
        icon = "☀️"
        if "cloud" in main_weather: icon = "☁️"
        elif "mist" in main_weather or "fog" in main_weather: icon = "🌫️"
        elif "rain" in main_weather or "drizzle" in main_weather: icon = "🌧️"
        elif "snow" in main_weather: icon = "❄️"
        elif "thunder" in main_weather: icon = "⛈️"
        return {"temp": f"{int(r['main']['temp'])}°C", "desc": r['weather'][0]['description'].capitalize(), "icon": icon}
    except:
        return {"temp": "20°C", "desc": "Meteo non disponibile", "icon": "❓"}

# --- ROTTE API PER IL FRONTEND ---
@app.route("/get_sensor_data/<room>")
def get_sensor_data(room):
    if "user_id" not in session:
        abort(401)

    user_res = supabase.table("users").select("house_id").eq("id", session['user_id']).execute()
    if not user_res.data: abort(404)
    house_id = str(user_res.data[0]['house_id'])

    # 1. Recupero ID e Configurazione Stanza
    room_db = supabase.table("rooms")\
        .select("id, min_temperature, max_temperature, co2_threshold")\
        .eq("house_id", house_id)\
        .eq("mqtt_topic_name", room).execute()
    
    if not room_db.data: abort(404)
        
    room_id = room_db.data[0]['id']
    config = {
        "min_temperature": room_db.data[0].get("min_temperature", 18.0),
        "max_temperature": room_db.data[0].get("max_temperature", 22.0),
        "co2_threshold": room_db.data[0].get("co2_threshold", 1000.0)
    }

    # 2. Meteo Esterno
    city = request.args.get('city')
    weather = get_weather(city)
    try:
        ext_temp = float(weather['temp'].replace('°C', ''))
    except:
        ext_temp = 20.0

    # 3. RECUPERO STATO COMPLETO ATTUATORI
    actuator_info = last_actuator_push.get(room_id, {})
    state = actuator_info.get("state", {})
    
    auto_mode = state.get("auto_mode", True)
    heating_on = state.get("heating_on", False)
    ac_on = state.get("ac_on", False)
    window_open = state.get("window_open", False)

    # 4. Recupero Dati Sensori
    user_data = latest_sensor_data.get(house_id)
    
    if not user_data or room not in user_data:
        res_data = {
            "temperature": 0, "CO2": 0, "waiting": True, "suggestion": "null"
        }
    else:
        res_data = user_data[room].copy()
        res_data['waiting'] = (res_data.get('temperature') == 0 and res_data.get('CO2') == 0)

    # 5. AGGIUNTA METADATI E STATI ATTUATORI ALLA RISPOSTA
    res_data.update({
        "external_temp": ext_temp,
        "config": config,
        "auto_mode": auto_mode,
        "heating_on": heating_on,
        "ac_on": ac_on,
        "window_open": window_open 
    })
    
    return jsonify(res_data)

# --- ROTTE ADMIN ---
@app.route("/admin/add", methods=['GET', 'POST'])
def admin_add_management():
    if "user_id" not in session: abort(401)
    if session.get("role") != "admin": abort(403)
    
    if request.method == 'POST':
        form_type = request.form.get('form_type')

        # --- CASO 1: AGGIUNGI CASA ---
        if form_type == 'house':
            name, city = request.form.get('name'), request.form.get('city')
            try:
                supabase.table("houses").insert({"name": name, "city": city}).execute()
                flash(f'Casa "{name}" aggiunta!', 'success')
            except Exception as e:
                flash(f'Errore casa: {str(e)}', 'danger')

        # --- CASO 2: AGGIUNGI STANZA ---
        elif form_type == 'room':
            house_id = request.form.get('house_id')
            room_name = request.form.get('room_name')
            mqtt_topic = request.form.get('mqtt_topic')
            
            check_name = supabase.table("rooms").select("*").eq("house_id", house_id).eq("name", room_name).execute()
            check_topic = supabase.table("rooms").select("*").eq("house_id", house_id).eq("mqtt_topic_name", mqtt_topic).execute()
            
            if check_name.data:
                flash(f'Errore: Stanza "{room_name}" già presente!', 'danger')
            elif check_topic.data:
                flash(f'Errore: Topic MQTT "{mqtt_topic}" già usato!', 'danger')
            else:
                use_default = 'use_default' in request.form
                min_t = 18.0 if use_default else float(request.form.get('min_temp', 18.0))
                max_t = 22.0 if use_default else float(request.form.get('max_temp', 22.0))
                co2_t = 1000.0 if use_default else float(request.form.get('co2_limit', 1000.0))

                try:
                    supabase.table("rooms").insert({
                        "house_id": house_id, 
                        "name": room_name, 
                        "mqtt_topic_name": mqtt_topic,
                        "min_temperature": min_t,
                        "max_temperature": max_t,
                        "co2_threshold": co2_t
                    }).execute()
                    flash(f'Stanza "{room_name}" creata!', 'success')
                except Exception as e:
                    flash(f'Errore tecnico: {str(e)}', 'danger')

        # --- CASO 3: AGGIUNGI UTENTE (AGGIORNATO CON EMAIL) ---
        elif form_type == 'user':
            house_id = request.form.get('house_id')
            username = request.form.get('username')
            password = request.form.get('password')
            email = request.form.get('email').strip().lower() # <--- RECUPERO EMAIL

            try:
                # Controlliamo se username o email sono già occupati
                check_user = supabase.table("users").select("*").or_(f"username.eq.{username},email.eq.{email}").execute()
                
                if check_user.data:
                    flash('Errore: Username o Email già esistenti!', 'danger')
                else:
                    supabase.table("users").insert({
                        "house_id": house_id,
                        "username": username,
                        "password": password, # Se usi hash, mettilo qui
                        "email": email,       # <--- SALVATAGGIO EMAIL
                        "role": "user"
                    }).execute()
                    flash(f'Utente "{username}" registrato correttamente!', 'success')
            except Exception as e:
                flash(f'Errore registrazione utente: {str(e)}', 'danger')
        
        return redirect(url_for('admin_dashboard')) # O admin_add_management

    houses_res = supabase.table("houses").select("*").execute()
    return render_template('admin_add.html', houses=houses_res.data)

@app.route("/admin/add_user", methods=['GET', 'POST'])
def admin_add_user():
    if "user_id" not in session: abort(401) # Oppure redirect al login se preferisci che l'anonimo non veda l'errore
    if session.get("role") != "admin": abort(403)
    
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password')
        house_id = request.form.get('house_id')
        
        existing_user = supabase.table("users").select("*").eq("username", username).execute()
        if existing_user.data:
            flash(f"L'utente '{username}' esiste già!", "danger")
        else:
            try:
                supabase.table("users").insert({
                    "username": username, "password": password,
                    "house_id": house_id, "role": "user"
                }).execute()
                flash(f"Utente '{username}' creato!", "success")
            except Exception as e:
                flash(f"Errore: {str(e)}", "danger")
        
        return redirect(url_for('admin_add_user'))

    houses = supabase.table("houses").select("*").execute()
    return render_template('add_user.html', houses=houses.data)

@app.route("/admin/dashboard")
def admin_dashboard():
    if "user_id" not in session: abort(401) # Oppure redirect al login se preferisci che l'anonimo non veda l'errore
    if session.get("role") != "admin": abort(403)
    houses_res = supabase.table("houses").select("*").execute()
    return render_template("admin_dashboard.html", houses=houses_res.data, username=session.get("username"))

@app.route("/admin/get_rooms_by_house/<house_id>")
def get_rooms_by_house(house_id):
    if "user_id" not in session: abort(401) # Oppure redirect al login se preferisci che l'anonimo non veda l'errore
    if session.get("role") != "admin": abort(403)
    try:
        rooms_res = supabase.table("rooms").select("*").eq("house_id", house_id).execute()
        final_data = []
        for r in rooms_res.data:
            final_data.append({
                "id": r['id'], 
                "name": r['name'], 
                "mqtt_topic": r['mqtt_topic_name'],
                "min_temp": r['min_temperature'],
                "max_temp": r['max_temperature'],
                "co2_limit": r['co2_threshold']
            })
        return jsonify(final_data)
    except: abort(500)

@app.route("/admin/update_room_config", methods=["POST"])
def update_room_config():
    if "user_id" not in session: abort(401) # Oppure redirect al login se preferisci che l'anonimo non veda l'errore
    if session.get("role") != "admin": abort(403)
    data = request.json
    try:
        supabase.table("rooms").update({
            "min_temperature": data['min'],
            "max_temperature": data['max'],
            "co2_threshold": data['co2']
        }).eq("id", data['room_id']).execute()
        return jsonify({"status": "success"})
    except Exception as e: abort(500)

@app.route("/my_rooms")
def my_rooms():
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    try:
        user_res = supabase.table("users").select("house_id").eq("id", session['user_id']).execute()
        if not user_res.data or not user_res.data[0]['house_id']:
            return render_template('rooms.html', rooms=[])
        
        house_id = user_res.data[0]['house_id']
        rooms_res = supabase.table("rooms").select("*").eq("house_id", house_id).execute()
        
        final_rooms = []
        for r in rooms_res.data:
            final_rooms.append({
                "id": r['id'],
                "name": r['name'],
                "mqtt_topic": r['mqtt_topic_name'],
                "min_temp": r['min_temperature'],
                "max_temp": r['max_temperature'],
                "co2_limit": r['co2_threshold']
            })
        
        return render_template('rooms.html', rooms=final_rooms)
    except Exception as e:
        flash("Errore nel caricamento delle stanze", "danger")
        return redirect(url_for("dashboard"))

@app.route("/settings", methods=["GET", "POST"])
def user_settings():
    if "user_id" not in session:
        return redirect(url_for("login"))

    try:
        # 1. Recupero house_id dell'utente
        user_res = supabase.table("users").select("house_id").eq("id", session['user_id']).execute()
        if not user_res.data:
            flash("Utente non trovato nel database.", "danger")
            return redirect(url_for("dashboard"))
            
        house_id = user_res.data[0]['house_id']

        # 2. Gestione aggiornamento (POST)
        if request.method == "POST":
            room_id = request.form.get("room_id")
            room_name = request.form.get("room_name") 
            min_t = float(request.form.get("min_temp"))
            max_t = float(request.form.get("max_temp"))
            co2_t = float(request.form.get("co2_limit"))

            try:
                supabase.table("rooms").update({
                    "min_temperature": min_t,
                    "max_temperature": max_t,
                    "co2_threshold": co2_t
                }).eq("id", room_id).execute()
                
                flash(f"Configurazione per '{room_name}' aggiornata con successo!", "success")
            except Exception as e:
                print(f"❌ Errore aggiornamento stanza: {e}")
                flash(f"Impossibile salvare i dati: {e}", "danger")
            
            return redirect(url_for("user_settings"))

        # 3. Recupero lista stanze per la visualizzazione (GET)
        rooms_res = supabase.table("rooms").select("*").eq("house_id", house_id).execute()
        
        rooms_with_config = []
        for r in rooms_res.data:
            rooms_with_config.append({
                "id": r['id'],
                "name": r['name'],
                "min_temp": r['min_temperature'],
                "max_temp": r['max_temperature'],
                "co2_limit": r['co2_threshold']
            })

        return render_template("user_settings.html", rooms=rooms_with_config)

    except Exception as e:
        # Questo cattura il "Server disconnected" o altri errori di rete
        print(f"❌ Errore critico Supabase in /settings: {e}")
        flash("Errore di connessione al Database. Riprova tra pochi secondi.", "warning")
        return redirect(url_for("dashboard"))

@app.route("/redirect_history")
def redirect_history():
    if "user_id" not in session: return redirect(url_for("login"))
    return redirect(url_for('history_page'))

@app.route('/history')
def history_page():
    if "user_id" not in session: 
        return redirect(url_for("login"))
    
    user_res = supabase.table("users").select("house_id").eq("id", session['user_id']).execute()
    if not user_res.data or not user_res.data[0]['house_id']:
        flash("Nessuna casa associata.", "warning")
        return redirect(url_for("dashboard"))
    
    house_id = user_res.data[0]['house_id']
    rooms_res = supabase.table("rooms").select("id, name").eq("house_id", house_id).execute()
    
    if not rooms_res.data:
        flash("Nessuna stanza trovata.", "warning")
        return redirect(url_for("dashboard"))
    
    return render_template('history.html', user_rooms=rooms_res.data)

@app.route('/api/stats/<int:room_id>')
def get_room_stats(room_id):
    if "user_id" not in session: abort(401)
    
    selected_date = request.args.get('date') 
    if not selected_date: abort(400)

    try:
        start_ds = f"{selected_date}T00:00:00"
        end_ds = f"{selected_date}T23:59:59"

        # 1. Dati Sensori
        res_sensors = supabase.table("sensor_data")\
            .select("timestamp, temperature, co2")\
            .eq("room_id", room_id)\
            .gte("timestamp", start_ds)\
            .lte("timestamp", end_ds)\
            .order("timestamp").execute()
        
        # 2. Dati Attuatori
        res_actuators = supabase.table("actuator_data")\
            .select("timestamp, ac_on, heating_on, window_open")\
            .eq("room_id", room_id)\
            .gte("timestamp", start_ds)\
            .lte("timestamp", end_ds)\
            .order("timestamp").execute()

        # Formattiamo i sensori
        sensor_list = []
        for s in res_sensors.data:
            sensor_list.append({
                "ora": s['timestamp'].split('T')[1][0:5],
                "temp": s['temperature'],
                "co2": s['co2']
            })

        # Formattiamo gli attuatori
        actuator_list = []
        for a in res_actuators.data:
            actuator_list.append({
                "ora": a['timestamp'].split('T')[1][0:5],
                "heat": 1 if a['heating_on'] else 0,
                "ac": 1 if a['ac_on'] else 0,
                "win": 1 if a['window_open'] else 0
            })
        
        # Restituiamo i due set separati
        return jsonify({
            "sensors": sensor_list,
            "actuators": actuator_list
        })

    except Exception as e:
        print(f"❌ Errore API: {e}")
        abort(500)
    
# --- AUTH & DASHBOARD ---
@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username, password = request.form.get("username"), request.form.get("password")
        user = get_user(username)
        if user and user["password"] == password:
            session.update({"user_id": user["id"], "username": user["username"], "role": user["role"]})
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Username o password errati", is_admin=False)
    return render_template("login.html", is_admin=False)

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username, password = request.form.get("username"), request.form.get("password")
        user = get_user(username, admin=True)
        if user and user["password"] == password:
            session.update({"user_id": user["id"], "username": user["username"], "role": user["role"]})
            return redirect(url_for("admin_dashboard"))
        return render_template("login.html", error="Credenziali admin errate", is_admin=True)
    return render_template("login.html", is_admin=True)

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session: 
        return redirect(url_for("login"))
    if session.get("role") == "admin": 
        return redirect(url_for("admin_dashboard"))
    
    rooms = []
    
    try:
        user_res = supabase.table("users").select("house_id").eq("id", session.get("user_id")).execute()
        if user_res.data:
            house_id = user_res.data[0]["house_id"]
            house_res = supabase.table("houses").select("city").eq("id", house_id).execute()
            if house_res.data: 
                city = house_res.data[0]["city"]
            
            rooms_res = supabase.table("rooms").select("name, mqtt_topic_name").eq("house_id", house_id).execute()
            if rooms_res.data:
                rooms = rooms_res.data
    except Exception as e:
        print(f"Errore recupero stanze: {e}")

    return render_template(
        "dashboard.html", 
        username=session.get("username"), 
        weather=get_weather(city), 
        city=city, 
        rooms=rooms
    )
    
@app.route("/change_password", methods=["GET"])
def change_password_page():
    # Protezione: se non è loggato, rimanda al login
    if "user_id" not in session:
        return redirect(url_for('login'))
    
    return render_template("change_password.html")

@app.route("/change_password", methods=["POST"])
def change_password():
    if "user_id" not in session:
        abort(401)
        
    data = request.json
    old_p = data.get("old_password")
    new_p = data.get("new_password")

    try:
        # Recupero password attuale dal DB
        user_res = supabase.table("users").select("password").eq("id", session['user_id']).execute()
        
        if not user_res.data: abort(404)  
        db_password = user_res.data[0]['password']

        # Confronto diretto (Semplice, in chiaro come richiesto)
        if db_password != old_p: abort(400)

        # Aggiornamento su Supabase
        supabase.table("users").update({"password": new_p}).eq("id", session['user_id']).execute()
        
        # Nota: Qui non usiamo flash() perché la risposta è JSON gestita da JS.
        # Il JS nel template riceverà questo messaggio e lo mostrerà.
        return jsonify({"status": "success", "message": "Password aggiornata con successo!"})

    except Exception as e: abort(500)

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email_inserita = request.form.get("email").strip().lower()
        print(f"\n[DEBUG] Richiesta reset per: {email_inserita}")
        
        # Cerchiamo l'utente (usiamo ilike per ignorare maiuscole/minuscole nel DB)
        user_res = supabase.table("users").select("*").ilike("email", email_inserita).execute()
        
        if user_res.data:
            user = user_res.data[0]
            print(f"[DEBUG] Utente trovato: {user['username']}")
            
            token = secrets.token_urlsafe(32)
            # Usiamo utcnow per evitare problemi di fuso orario tra PC e Database
            scadenza = (datetime.utcnow() + timedelta(hours=1)).isoformat()
            
            # Salviamo token e scadenza su Supabase
            supabase.table("users").update({
                "reset_token": token, 
                "token_expiry": scadenza
            }).eq("id", user['id']).execute()
            
            try:
                link_reset = url_for('reset_password_token', token=token, _external=True)
                msg = Message("Recupero Password - SmartHome",
                              sender=app.config['MAIL_USERNAME'],
                              recipients=[email_inserita])
                
                msg.body = f"""Ciao {user['username']},
Hai richiesto di reimpostare la password del tuo account SmartHome.
Clicca sul link qui sotto (valido per 1 ora):

{link_reset}

Se non sei stato tu, ignora questa mail."""

                mail.send(msg)
                print("[DEBUG] Email inviata con successo!")
                flash("Email di recupero inviata! Controlla la tua posta.", "success")
                
            except Exception as e:
                print(f"[DEBUG] ERRORE SMTP: {e}")
                flash("Errore nell'invio dell'email. Riprova più tardi.", "danger")
        else:
            print("[DEBUG] Email non trovata nel database.")
            flash("Se l'email è registrata, riceverai un link a breve.", "info")
            
        return redirect(url_for('login'))
        
    return render_template("forgot_password.html")

@app.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password_token(token):
    # Cerchiamo l'utente col token
    user_res = supabase.table("users").select("*").eq("reset_token", token).execute()
    
    if not user_res.data:
        flash("Il link non è valido o è già stato usato.", "danger")
        return redirect(url_for('login'))
    
    user = user_res.data[0]
    
    # Controllo scadenza (confronto entrambi in UTC)
    scadenza_db = datetime.fromisoformat(user['token_expiry'])
    if datetime.utcnow() > scadenza_db:
        flash("Il link è scaduto. Richiedine uno nuovo.", "danger")
        return redirect(url_for('forgot_password'))

    if request.method == "POST":
        nuova_password = request.form.get("password")
        
        # Aggiorniamo password e puliamo i campi token
        supabase.table("users").update({
            "password": nuova_password,
            "reset_token": None,
            "token_expiry": None
        }).eq("id", user['id']).execute()
        
        flash("Password aggiornata con successo! Ora puoi accedere.", "success")
        return redirect(url_for('login'))
        
    return render_template("reset_password_form.html", token=token)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# errors handler
# --- ERROR HANDLERS ---

@app.route("/test_error/<int:code>")
def test_error(code):
    # Questa rotta accetta un numero e scatena l'errore corrispondente
    # Esempio: /test_error/404
    abort(code)

@app.errorhandler(400)
def bad_request_error(e):
    # Dati inviati male dai sensori o dal browser
    return render_template('errors/400.html'), 400

@app.errorhandler(401)
def unauthorized_error(e):
    # Utente non loggato o sessione scaduta
    return render_template('errors/401.html'), 401

@app.errorhandler(403)
def forbidden_error(e):
    # Utente loggato ma senza permessi per la risorsa
    return render_template('errors/403.html'), 403

@app.errorhandler(404)
def not_found_error(e):
    # Pagina o stanza inesistente
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    # Errore critico (es. Database offline o bug nel codice)
    return render_template('errors/500.html'), 500

#
#  AVVIO APPLICAZIONE
#
print("\n--- 🏁 AVVIO PROCEDURA DI BOOT ---")

# 1. Inizializza la cache dal DB
print("1️⃣  Inizializzazione cache attuatori...")
init_actuator_cache()

# 2. Avvio Thread MQTT (Ricezione dati real-time)
print("2️⃣  Avvio Thread MQTT...")
t_mqtt = threading.Thread(target=mqtt_worker, daemon=True)
t_mqtt.start()

# 3. Avvio Thread Sensor DB (Storico 5 min)
print("3️⃣  Avvio Thread Sensor DB...")
t_sensor = threading.Thread(target=sensor_db_worker, daemon=True)
t_sensor.start()

# 4. Avvio Watchdog Attuatori (Backup 5 min)
print("4️⃣  Avvio Watchdog sugli attuatori...")
t_watchdog = threading.Thread(target=actuator_watchdog_worker, daemon=True)
t_watchdog.start()

# 5. Avvio Bot Telegram
print("5️⃣  Avvio Bot Telegram...")
t_tg = threading.Thread(target=telegram_bot_worker, daemon=True)
t_tg.start()

print("--- ✅ TUTTI I THREAD SONO PARTITI ---")

# --- AVVIO APPLICAZIONE E THREAD ---
if __name__ == "__main__":
    # 6. Avvio Flask
    print("🚀 Server SmartHome avviato su http://127.0.0.1:5000")
    app.run(debug=False, port=5000)