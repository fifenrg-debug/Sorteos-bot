import os
import sqlite3
import time
from flask import Flask, render_template, request, jsonify, g
import telebot

# --- CONFIGURACIÓN DINÁMICA PARA LA NUBE Y LOCAL ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(BASE_DIR, 'templates')
app = Flask(__name__, template_folder=template_dir)

# Carpeta de subidas relativa
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Base de datos relativa
DATABASE = os.path.join(BASE_DIR, 'sorteo.db')

# Credenciales
TOKEN = os.environ.get('TELEGRAM_TOKEN', '8933969399:AAGWHO0-ZlE9kNlw4SOwixd-IbHmkmPPSXY')
ADMIN_ID = int(os.environ.get('ADMIN_ID', 8478276387))

bot = telebot.TeleBot(TOKEN)

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                saldo REAL DEFAULT 0.0,
                es_admin BOOLEAN DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transacciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                tipo TEXT,
                monto REAL,
                datos_bancarios TEXT,
                estado TEXT DEFAULT 'pendiente'
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tiradas_ruleta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                numero_obtenido INTEGER,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tipos_sorteo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT,
                precio REAL,
                total_numeros INTEGER
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tickets_sorteos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sorteo_id INTEGER,
                numero INTEGER,
                telegram_id INTEGER,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(sorteo_id, numero)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS estado_sorteo (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                fin_timestamp INTEGER
            )
        ''')
        
        tiempo_inicial = int(time.time()) + 7200
        cursor.execute('INSERT OR IGNORE INTO estado_sorteo (id, fin_timestamp) VALUES (1, ?)', (tiempo_inicial,))
        
        cursor.execute('SELECT COUNT(*) FROM tipos_sorteo')
        if cursor.fetchone()[0] == 0:
            sorteos_iniciales = [
                ("Sorteo Rápido 50 CUP", 50.0, 20),
                ("Sorteo Estándar 100 CUP", 100.0, 30),
                ("Sorteo Premium 500 CUP", 500.0, 50),
                ("Sorteo VIP 1000 CUP", 1000.0, 50)
            ]
            cursor.executemany('INSERT OR IGNORE INTO tipos_sorteo (titulo, precio, total_numeros) VALUES (?, ?, ?)', sorteos_iniciales)
            
        db.commit()

@bot.message_handler(commands=['start'])
def enviar_bienvenida(message):
    user_id = message.from_user.id
    username = message.from_user.username or "usuario"
    
    db = sqlite3.connect(DATABASE)
    cursor = db.cursor()
    cursor.execute('SELECT * FROM usuarios WHERE telegram_id = ?', (user_id,))
    if not cursor.fetchone():
        es_admin = 1 if int(user_id) == int(ADMIN_ID) else 0
        cursor.execute('INSERT INTO usuarios (telegram_id, username, saldo, es_admin) VALUES (?, ?, ?, ?)',
                       (user_id, username, 0.0, es_admin))
        db.commit()
    db.close()
    
    admin_text = "\n\n👑 *Panel Admin Activo*: Usa /admin para ver los comandos de gestión." if int(user_id) == int(ADMIN_ID) else ""
    bot.reply_to(message, f"¡Bienvenido a Sorteos en Cuba! 🎁\nPresiona el botón del menú para abrir la aplicación y probar tu suerte.{admin_text}", parse_mode="Markdown")

# --- COMANDOS DE ADMINISTRADOR ---

@bot.message_handler(commands=['admin'])
def panel_admin(message):
    if int(message.from_user.id) != int(ADMIN_ID):
        return bot.reply_to(message, f"❌ No tienes permisos.")
    
    texto = (
        "👑 *Panel de Administración - Sorteos en Cuba*\n\n"
        "Comandos disponibles:\n"
        "👥 `/usuarios` - Ver lista de usuarios registrados y sus saldos.\n"
        "🔔 `/pendientes` - Ver transacciones pendientes.\n"
        "➕ `/dar_saldo [ID] [Monto]` - Añadir saldo directamente.\n"
        "✅ `/aprobar [ID_Transaccion]` - Aprobar recarga o retiro."
    )
    bot.reply_to(message, texto, parse_mode="Markdown")

@bot.message_handler(commands=['usuarios'])
def listar_usuarios(message):
    if int(message.from_user.id) != int(ADMIN_ID): return
    db = sqlite3.connect(DATABASE)
    cursor = db.cursor()
    cursor.execute('SELECT telegram_id, username, saldo FROM usuarios')
    usuarios = cursor.fetchall()
    db.close()
    
    respuesta = "👥 *Usuarios Registrados:*\n\n"
    for u in usuarios:
        respuesta += f"ID: `{u[0]}` | @{u[1]} | Saldo: *{u[2]} CUP*\n"
    bot.reply_to(message, respuesta, parse_mode="Markdown")

@bot.message_handler(commands=['pendientes'])
def ver_pendientes(message):
    if int(message.from_user.id) != int(ADMIN_ID): return
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    cursor = db.cursor()
    cursor.execute("SELECT id, telegram_id, tipo, monto, datos_bancarios FROM transacciones WHERE estado = 'pendiente'")
    trans = cursor.fetchall()
    db.close()
    
    if not trans:
        return bot.reply_to(message, "✅ No hay transacciones pendientes.")
    
    respuesta = "🔔 *Transacciones Pendientes:*\n\n"
    for t in trans:
        respuesta += f"🆔 Trx ID: `{t['id']}`\n👤 User ID: `{t['telegram_id']}`\n📌 Tipo: *{t['tipo']}*\n💵 Monto: *{t['monto']}*\n📱 Ref: {t['datos_bancarios']}\n-------------------\n"
    bot.reply_to(message, respuesta, parse_mode="Markdown")

@bot.message_handler(commands=['dar_saldo'])
def dar_saldo(message):
    if int(message.from_user.id) != int(ADMIN_ID): return
    try:
        partes = message.text.split()
        target_id = int(partes[1])
        monto = float(partes[2])
        
        db = sqlite3.connect(DATABASE)
        cursor = db.cursor()
        cursor.execute('UPDATE usuarios SET saldo = saldo + ? WHERE telegram_id = ?', (monto, target_id))
        db.commit()
        db.close()
        
        bot.reply_to(message, f"✅ Se han sumado {monto} CUP al usuario `{target_id}` exitosamente.", parse_mode="Markdown")
        try:
            bot.send_message(target_id, f"🎉 ¡Han acreditado {monto} CUP a tu monedero!")
        except:
            pass
    except Exception as e:
        bot.reply_to(message, "❌ Formato incorrecto. Usa: `/dar_saldo [telegram_id] [monto]`", parse_mode="Markdown")

@bot.message_handler(commands=['aprobar'])
def aprobar_transaccion(message):
    if int(message.from_user.id) != int(ADMIN_ID): return
    try:
        trx_id = int(message.text.split()[1])
        db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        cursor = db.cursor()
        cursor.execute("SELECT * FROM transacciones WHERE id = ? AND estado = 'pendiente'", (trx_id,))
        trx = cursor.fetchone()
        
        if not trx:
            db.close()
            return bot.reply_to(message, "❌ Transacción no encontrada o ya procesada.")
        
        telegram_id = trx['telegram_id']
        tipo = trx['tipo']
        monto = trx['monto']
        
        if tipo == 'recarga':
            cursor.execute("UPDATE usuarios SET saldo = saldo + ? WHERE telegram_id = ?", (monto, telegram_id))
        elif tipo == 'retiro':
            cursor.execute("UPDATE usuarios SET saldo = saldo - ? WHERE telegram_id = ?", (monto, telegram_id))
            
        cursor.execute("UPDATE transacciones SET estado = 'aprobado' WHERE id = ?", (trx_id,))
        db.commit()
        db.close()
        
        bot.reply_to(message, f"✅ Transacción #{trx_id} aprobada con éxito.")
        try:
            bot.send_message(telegram_id, f"✅ ¡Tu solicitud de {tipo} por {monto} CUP ha sido aprobada!")
        except:
            pass
    except Exception as e:
        bot.reply_to(message, "❌ Error. Usa: `/aprobar [id_transaccion]`")

# --- ENDPOINTS FLASK ---

@app.route('/')
def index():
    return render_template('index.html')

# --- RUTA PARA EL WEBHOOK DE TELEGRAM ---
@app.route(f'/bot/{TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return '', 403

@app.route('/api/sorteo/tiempo', methods=['GET'])
def obtener_tiempo_sorteo():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT fin_timestamp FROM estado_sorteo WHERE id = 1')
    row = cursor.fetchone()
    
    ahora = int(time.time())
    fin = row['fin_timestamp'] if row else (ahora + 7200)
    
    if ahora >= fin:
        fin = ahora + 7200
        cursor.execute('UPDATE estado_sorteo SET fin_timestamp = ? WHERE id = 1', (fin,))
        db.commit()
        
    restante = max(0, fin - ahora)
    return jsonify({"tiempo_restante": restante})

@app.route('/api/usuario/<int:telegram_id>', methods=['GET'])
def obtener_usuario(telegram_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM usuarios WHERE telegram_id = ?', (telegram_id,))
    user = cursor.fetchone()
    
    if not user:
        es_admin = 1 if int(telegram_id) == int(ADMIN_ID) else 0
        cursor.execute('INSERT INTO usuarios (telegram_id, username, saldo, es_admin) VALUES (?, ?, ?, ?)', 
                       (telegram_id, f"user_{telegram_id}", 0.0, es_admin))
        db.commit()
        cursor.execute('SELECT * FROM usuarios WHERE telegram_id = ?', (telegram_id,))
        user = cursor.fetchone()

    return jsonify({
        "telegram_id": user["telegram_id"],
        "saldo": float(user["saldo"] if user["saldo"] is not None else 0.0),
        "es_admin": bool(user["es_admin"])
    })

@app.route('/api/recargar', methods=['POST'])
def recargar():
    telegram_id = request.form.get('telegram_id')
    monto = request.form.get('monto')
    referencia = request.form.get('referencia', 'MiTransfer')
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('INSERT INTO transacciones (telegram_id, tipo, monto, datos_bancarios, estado) VALUES (?, ?, ?, ?, ?)',
                   (telegram_id, 'recarga', monto, referencia, 'pendiente'))
    db.commit()
    trx_id = cursor.lastrowid

    if 'captura' in request.files:
        foto = request.files['captura']
        if foto.filename != '':
            ruta_guardado = os.path.join(app.config['UPLOAD_FOLDER'], foto.filename)
            foto.save(ruta_guardado)
            
            try:
                caption = (
                    f"🔔 *Nueva solicitud de recarga (con captura)*\n"
                    f"🆔 Trx ID: `{trx_id}`\n"
                    f"👤 Usuario ID: `{telegram_id}`\n"
                    f"💵 Monto: `{monto}` CUP\n"
                    f"Ref: {referencia}\n\n"
                    f"Usa `/aprobar {trx_id}` para acreditar."
                )
                with open(ruta_guardado, 'rb') as foto_file:
                    bot.send_photo(ADMIN_ID, foto_file, caption=caption, parse_mode="Markdown")
            except Exception as e:
                print("Error al enviar foto al admin:", e)
    else:
        try:
            bot.send_message(ADMIN_ID, f"🔔 *Nueva solicitud de recarga*\n🆔 Trx ID: `{trx_id}`\nUsuario ID: `{telegram_id}`\nMonto: `{monto}` CUP\nRef: {referencia}\n\nUsa `/aprobar {trx_id}` para acreditar.", parse_mode="Markdown")
        except Exception as e:
            print("Error al notificar admin:", e)

    return jsonify({"exito": True, "mensaje": "Solicitud y comprobante enviados al administrador."})

@app.route('/api/retirar', methods=['POST'])
def retirar():
    data = request.json
    telegram_id = data.get('telegram_id')
    monto = data.get('monto')
    datos = data.get('datos_bancarios', 'Tarjeta CUP')
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT saldo FROM usuarios WHERE telegram_id = ?', (telegram_id,))
    user = cursor.fetchone()
    
    if not user or user['saldo'] < monto:
        return jsonify({"exito": False, "mensaje": "Saldo insuficiente para realizar el retiro."})
        
    cursor.execute('INSERT INTO transacciones (telegram_id, tipo, monto, datos_bancarios, estado) VALUES (?, ?, ?, ?, ?)',
                   (telegram_id, 'retiro', monto, datos, 'pendiente'))
    db.commit()
    
    try:
        bot.send_message(ADMIN_ID, f"🏛️ *Nueva solicitud de retiro*\nUsuario ID: `{telegram_id}`\nMonto: `{monto}` CUP\nDatos: {datos}\n\nUsa `/aprobar [ID]` cuando le transfieras.", parse_mode="Markdown")
    except Exception as e:
        print("Error al notificar admin:", e)

    return jsonify({"exito": True, "mensaje": "Solicitud de retiro enviada."})

@app.route('/api/girar', methods=['POST'])
def registrar_giro():
    data = request.json
    telegram_id = data.get('telegram_id')
    numero = data.get('numero')
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('INSERT INTO tiradas_ruleta (telegram_id, numero_obtenido) VALUES (?, ?)',
                   (telegram_id, numero))
    db.commit()
    
    return jsonify({"exito": True, "mensaje": f"¡Número {numero} registrado exitosamente!"})

@app.route('/api/soporte', methods=['POST'])
def enviar_soporte():
    data = request.json
    telegram_id = data.get('telegram_id')
    mensaje_soporte = data.get('mensaje')
    
    if not mensaje_soporte:
        return jsonify({"exito": False, "mensaje": "El mensaje no puede estar vacío."})
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT username FROM usuarios WHERE telegram_id = ?', (telegram_id,))
    user = cursor.fetchone()
    username = f"@{user['username']}" if user and user['username'] else f"ID: {telegram_id}"
    
    try:
        texto_admin = (
            f"🎧 *Nueva consulta de Soporte*\n\n"
            f"👤 Usuario: {username}\n"
            f"🆔 ID de Telegram: `{telegram_id}`\n\n"
            f"💬 *Mensaje:* \n{mensaje_soporte}"
        )
        bot.send_message(ADMIN_ID, texto_admin, parse_mode="Markdown")
    except Exception as e:
        print("Error al enviar mensaje de soporte al admin:", e)
        return jsonify({"exito": False, "mensaje": "Error al enviar el mensaje."})

    return jsonify({"exito": True, "mensaje": "¡Tu mensaje de soporte ha sido enviado con éxito!"})

# --- ENDPOINTS PARA SORTEOS Y TICKETS ---

@app.route('/api/sorteos/disponibles', methods=['GET'])
def listar_sorteos_disponibles():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM tipos_sorteo')
    sorteos = cursor.fetchall()
    
    resultado = []
    for s in sorteos:
        resultado.append({
            "id": s["id"],
            "titulo": s["titulo"],
            "precio": float(s["precio"]),
            "total_numeros": int(s["total_numeros"])
        })
    return jsonify(resultado)

@app.route('/api/sorteos/<int:sorteo_id>/ocupados', methods=['GET'])
def obtener_numeros_ocupados(sorteo_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT numero, telegram_id FROM tickets_sorteos WHERE sorteo_id = ?', (sorteo_id,))
    tickets = cursor.fetchall()
    
    ocupados = {t["numero"]: t["telegram_id"] for t in tickets}
    return jsonify(ocupados)

@app.route('/api/sorteos/comprar', methods=['POST'])
def comprar_ticket_sorteo():
    data = request.json
    telegram_id = data.get('telegram_id')
    sorteo_id = data.get('sorteo_id')
    numero = data.get('numero')
    
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT precio, titulo FROM tipos_sorteo WHERE id = ?', (sorteo_id,))
    sorteo = cursor.fetchone()
    if not sorteo:
        return jsonify({"exito": False, "mensaje": "El sorteo seleccionado no existe."})
    
    precio = sorteo["precio"]
    
    cursor.execute('SELECT saldo FROM usuarios WHERE telegram_id = ?', (telegram_id,))
    user = cursor.fetchone()
    if not user or user["saldo"] < precio:
        return jsonify({"exito": False, "mensaje": f"Saldo insuficiente. Necesitas {precio} CUP."})
    
    try:
        cursor.execute('INSERT INTO tickets_sorteos (sorteo_id, numero, telegram_id) VALUES (?, ?, ?)',
                       (sorteo_id, numero, telegram_id))
        cursor.execute('UPDATE usuarios SET saldo = saldo - ? WHERE telegram_id = ?', (precio, telegram_id))
        db.commit()
        
        return jsonify({
            "exito": True, 
            "mensaje": f"¡Compra exitosa! Has adquirido el número {numero} para el {sorteo['titulo']}."
        })
    except sqlite3.IntegrityError:
        db.rollback()
        return jsonify({"exito": False, "mensaje": "Lo sentimos, este número ya fue comprado por otro usuario."})
    except Exception as e:
        db.rollback()
        print("Error en compra de ticket:", e)
        return jsonify({"exito": False, "mensaje": "Ocurrió un error al procesar la compra."})

# Inicialización y configuración del Webhook al arrancar la app web
init_db()

WEBHOOK_URL = f"https://NoelPro.pythonanywhere.com/bot/{TOKEN}"
try:
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    print(f"Webhook configurado correctamente en: {WEBHOOK_URL}")
except Exception as e:
    print("Error al configurar el webhook:", e)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
alse)
