import os
import sqlite3
from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify, Response, send_from_directory, g
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import current_app
from werkzeug.utils import secure_filename
import json
import csv
import io
import random
import requests
import re
import unicodedata
import secrets
from difflib import SequenceMatcher
import folium
from geopy.geocoders import ArcGIS
from geopy.distance import geodesic

from database import get_db_connection

from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', 'local-development-key-change-before-deploying')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 86400


@app.after_request
def include_global_cursor(response):
    if response.mimetype != 'text/html' or response.direct_passthrough or response.is_streamed:
        return response

    content = response.get_data(as_text=True)
    project_stylesheet = re.compile(
        r'<link\b(?=[^>]*\bhref=["\'][^"\']*(?:/static/)?(?:css|CSS)/'
        r'(?:style|admin-crud|responsive|widgets|cursor)\.css(?:[?#][^"\']*)?["\'])[^>]*>',
        flags=re.IGNORECASE
    )
    content = project_stylesheet.sub('', content)
    stylesheet = url_for('static', filename='css/style.css', v='20261024-forest-green-palette')
    legacy_link = f'<link rel="stylesheet" href="{stylesheet}">'
    premium_stylesheet = url_for('static', filename='css/platform-premium.css', v='20261025-circuit-sections-v14')
    premium_link = f'<link rel="stylesheet" href="{premium_stylesheet}">'

    head_end = re.search(r'</head\s*>', content, flags=re.IGNORECASE)
    head_content = content[:head_end.start()] if head_end else content
    inline_style = re.search(r'<style\b', head_content, flags=re.IGNORECASE)
    if inline_style:
        content = content[:inline_style.start()] + legacy_link + content[inline_style.start():]
    elif head_end:
        content = re.sub(r'</head\s*>', f'{legacy_link}</head>', content, count=1, flags=re.IGNORECASE)
    elif re.search(r'<body\b', content, flags=re.IGNORECASE):
        content = re.sub(r'<body\b', f'<head>{legacy_link}</head><body', content, count=1, flags=re.IGNORECASE)

    if re.search(r'</head\s*>', content, flags=re.IGNORECASE):
        content = re.sub(r'</head\s*>', f'{premium_link}</head>', content, count=1, flags=re.IGNORECASE)
    elif re.search(r'</body\s*>', content, flags=re.IGNORECASE):
        content = re.sub(r'</body\s*>', f'{premium_link}</body>', content, count=1, flags=re.IGNORECASE)
    response.set_data(content)
    return response


@app.template_filter('cop')
def formato_cop(valor):
    try:
        monto = Decimal(str(valor if valor is not None else 0))
        pesos = int(monto.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (ArithmeticError, TypeError, ValueError):
        pesos = 0
    return f'{pesos:,}'.replace(',', '.')


@app.template_filter('product_image_url')
def product_image_url(image_path):
    path = str(image_path or '').strip().replace('\\', '/')
    if path.startswith(('https://', 'http://')):
        return path

    path = path.lstrip('/')
    if path.startswith('static/'):
        path = path[len('static/'):]
    if not path.startswith(('uploads/', 'img/', 'IMG/')):
        path = f'img/{path}' if path else 'IMG/tenis.jpg'

    normalized_path = os.path.normpath(path).replace('\\', '/')
    if normalized_path == '..' or normalized_path.startswith('../'):
        normalized_path = 'IMG/tenis.jpg'
    path = normalized_path
    absolute_path = os.path.join(app.static_folder, *path.split('/'))
    if not os.path.isfile(absolute_path):
        path = 'IMG/tenis.jpg'
    return url_for('static', filename=path)


# Configuración de Sesión
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = os.environ.get(
    'SESSION_FILE_DIR',
    os.path.join(app.instance_path, 'flask_session'),
)
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
Session(app)

# Servidor y puerto oficial de Gmail para envíos seguros
app.config['MAIL_SERVER'] = 'smtp.gmail.com'  # Servidor SMTP de Google
app.config['MAIL_PORT'] = 587                 # Puerto estándar con cifrado TLS
app.config['MAIL_USE_TLS'] = True             # Activa la seguridad TLS (Transport Layer Security)

# Credenciales de autenticación
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = (
    'TENNISSEL',
    os.environ.get('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME']),
)
 
# Inicializamos el envío de correos asociándolo a tu app de Flask
mail = Mail(app)

# Inicializamos el generador de tokens usando la clave secreta de tu proyecto
serializer = URLSafeTimedSerializer(app.secret_key)

UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads', 'perfiles')
PRODUCT_UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads', 'productos')
REFUND_UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads', 'reembolsos')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
PROFILE_AVATARS = (
    'avatar-tennisel-1.png',
    'avatar-tennisel-2.png',
    'avatar-tennisel-3.png',
    'avatar-tennisel-4.png',
    'avatar-tennisel-5.png',
    'avatar-tennisel-6.png',
    'avatar-tennisel-7.png',
    'avatar-tennisel-8.png',
    'avatar-tennisel-9.png',
)
LEGACY_PROFILE_AVATARS = {
    'avatar-tenis-1.svg': 'avatar-tennisel-1.png',
    'avatar-tenis-2.svg': 'avatar-tennisel-2.png',
    'avatar-tenis-3.svg': 'avatar-tennisel-3.png',
    'avatar-tenis-4.svg': 'avatar-tennisel-4.png',
    'avatar-tenis-5.svg': 'avatar-tennisel-5.png',
    'avatar-tenis-6.svg': 'avatar-tennisel-6.png',
    'avatar-tenis-7.svg': 'avatar-tennisel-7.png',
    'avatar-tenis-8.svg': 'avatar-tennisel-8.png',
}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
if not os.path.exists(PRODUCT_UPLOAD_FOLDER):
    os.makedirs(PRODUCT_UPLOAD_FOLDER)
if not os.path.exists(REFUND_UPLOAD_FOLDER):
    os.makedirs(REFUND_UPLOAD_FOLDER)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in (ALLOWED_EXTENSIONS | {'webp'})


def foto_perfil_url(foto):
    if not foto:
        return url_for('static', filename=f'IMG/{PROFILE_AVATARS[0]}', v='20261005-7')
    nombre_archivo = secure_filename(os.path.basename(str(foto).replace('\\', '/')))
    if not nombre_archivo or nombre_archivo == 'default.png':
        nombre_archivo = PROFILE_AVATARS[0]
    nombre_archivo = LEGACY_PROFILE_AVATARS.get(nombre_archivo, nombre_archivo)
    if nombre_archivo in PROFILE_AVATARS:
        return url_for('static', filename=f'IMG/{nombre_archivo}', v='20261005-7')
    return url_for('servir_foto_perfil', filename=nombre_archivo)


def asegurar_avatar_predeterminado(usuario_id):
    avatar = PROFILE_AVATARS[(int(usuario_id) - 1) % len(PROFILE_AVATARS)]
    conn = get_db_connection()
    if conn is None:
        return
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT foto FROM perfil_usuario WHERE usuario_id = %s', (usuario_id,))
        row = cursor.fetchone()
        if not row or not row[0] or row[0] == 'default.png':
            cursor.execute('''
                INSERT INTO perfil_usuario (usuario_id, foto)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE foto = VALUES(foto)
            ''', (usuario_id, avatar))
            conn.commit()
    except sqlite3.Error as err:
        conn.rollback()
        app.logger.exception('No se pudo asignar el avatar predeterminado del usuario %s: %s', usuario_id, err)
    finally:
        if cursor:
            cursor.close()
        conn.close()


@app.route('/uploads/perfiles/<path:filename>')
def servir_foto_perfil(filename):
    nombre_archivo = secure_filename(os.path.basename(filename))
    if not nombre_archivo or nombre_archivo != filename:
        return '', 404
    carpetas = (
        os.path.join(app.static_folder, 'uploads', 'perfiles'),
        os.path.abspath(os.path.join(app.root_path, '..', 'static', 'uploads', 'perfiles')),
        os.path.abspath(app.config.get('UPLOAD_FOLDER', UPLOAD_FOLDER)),
    )
    for carpeta in dict.fromkeys(carpetas):
        if os.path.isfile(os.path.join(carpeta, nombre_archivo)):
            return send_from_directory(carpeta, nombre_archivo, conditional=True)
    return '', 404


def perfil_image_valida(file_storage):
    if not allowed_file(file_storage.filename or ''):
        return False
    contenido = file_storage.stream.read(5 * 1024 * 1024 + 1)
    file_storage.stream.seek(0)
    if len(contenido) > 5 * 1024 * 1024:
        return False
    extension = os.path.splitext(secure_filename(file_storage.filename or ''))[1].lower()
    firmas = {
        '.png': contenido.startswith(b'\x89PNG\r\n\x1a\n'),
        '.jpg': contenido.startswith(b'\xff\xd8\xff'),
        '.jpeg': contenido.startswith(b'\xff\xd8\xff'),
        '.gif': contenido.startswith((b'GIF87a', b'GIF89a')),
        '.webp': contenido.startswith(b'RIFF') and contenido[8:12] == b'WEBP',
    }
    return firmas.get(extension, False)


@app.route('/proxy-imagen')
def proxy_imagen():
    """Entrega imágenes remotas para evitar bloqueos de hotlink del navegador."""
    image_url = request.args.get('url', '')
    if image_url.startswith('IMG/'):
        return send_from_directory(app.static_folder, image_url)
    if not image_url.startswith(('https://', 'http://')):
        return '', 400

    try:
        response = requests.get(
            image_url,
            headers={'User-Agent': 'TENNISSEL/1.0'},
            timeout=8,
            stream=True
        )
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            return '', 415
        return Response(
            response.content,
            content_type=content_type,
            headers={'Cache-Control': 'public, max-age=3600'}
        )
    except requests.RequestException:
        return '', 404


def asegurar_columna_hora_fin(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'reservas'
              AND COLUMN_NAME = 'hora_fin'
        ''')
        if not cursor.fetchone()[0]:
            cursor.execute('ALTER TABLE reservas ADD COLUMN hora_fin TIME DEFAULT NULL')
            conn.commit()
    finally:
        cursor.close()


def asegurar_columna_usuario_reserva(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'reservas'
              AND COLUMN_NAME = 'user_id'
        ''')
        if not cursor.fetchone()[0]:
            cursor.execute('ALTER TABLE reservas ADD COLUMN user_id INT NULL AFTER locacion_id')
            conn.commit()
        cursor.execute('SELECT id, username, nombre_completo FROM usuarios')
        usuarios_por_nombre = {}
        for usuario in cursor.fetchall():
            for nombre in (usuario[1], usuario[2]):
                if nombre:
                    usuarios_por_nombre.setdefault(normalizar_termino_busqueda(nombre), usuario[0])

        cursor.execute('SELECT id, nombre_usuario FROM reservas WHERE user_id IS NULL')
        for reserva_id, nombre_usuario in cursor.fetchall():
            usuario_id = usuarios_por_nombre.get(normalizar_termino_busqueda(nombre_usuario))
            if usuario_id:
                cursor.execute(
                    'UPDATE reservas SET user_id = %s WHERE id = %s AND user_id IS NULL',
                    (usuario_id, reserva_id),
                )
        conn.commit()
    finally:
        cursor.close()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Para acceder a esta seccion necesitas registrarte primero.', 'warning')
            return redirect(url_for('registro'))
        return f(*args, **kwargs)
    return decorated_function


def not_banned_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        usuario_id = session.get('user_id')
        if usuario_id:
            baneado, _ = usuario_baneado(usuario_id)
            if baneado:
                flash('Tu cuenta esta bloqueada. Debes solicitar una revision antes de continuar.', 'error')
                return redirect(url_for('apelar_baneo'))
        return f(*args, **kwargs)
    return decorated_function


def tienda_premium_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debes iniciar sesión para administrar productos.', 'warning')
            return redirect(url_for('login'))
        if session.get('role') != 'tienda':
            flash('Solo las cuentas Tienda pueden proponer productos.', 'warning')
            return redirect(url_for('index'))
        baneado, _ = usuario_baneado(session['user_id'])
        if baneado:
            return redirect(url_for('apelar_baneo'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debes iniciar sesion primero.', 'warning')
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash('Acceso denegado.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


def asegurar_columnas_pago_premium(conn):
    cursor = conn.cursor()
    try:
        for nombre, definicion in (
            ('metodo_pago', "VARCHAR(32) NOT NULL DEFAULT 'prueba'"),
            ('pago_simulado', 'TINYINT(1) NOT NULL DEFAULT 1'),
            ('fecha_fin', 'DATETIME NULL'),
        ):
            cursor.execute('''
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'premium'
                  AND COLUMN_NAME = %s
            ''', (nombre,))
            if not cursor.fetchone()[0]:
                cursor.execute(f'ALTER TABLE premium ADD COLUMN {nombre} {definicion}')
        conn.commit()
    finally:
        cursor.close()


def verificar_premium(user_id):
    """Verifica si un usuario tiene suscripcion activa en la tabla premium."""
    conn = get_db_connection()
    if not conn:
        return False
    cursor = None
    try:
        asegurar_columnas_pago_premium(conn)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) FROM premium
            WHERE user_id = %s AND (fecha_fin IS NULL OR fecha_fin > CURRENT_TIMESTAMP)
        ''', (user_id,))
        resultado = cursor.fetchone()
        return resultado and resultado[0] > 0
    except sqlite3.Error as err:
        print(f"Error verificando premium: {err}")
        return False
    finally:
        if cursor:
            cursor.close()
        conn.close()


PALABRAS_PROHIBIDAS = {
    # Lista inicial multilingue; se puede ampliar sin cambiar el flujo de moderacion.
    'puta', 'puto', 'putas', 'putos', 'mierda', 'marica', 'maricon',
    'hijueputa', 'hijoputa', 'cojones', 'cabron', 'pendejo', 'idiota',
    'fuck', 'fucking', 'shit', 'bitch', 'asshole', 'bastard', 'motherfucker',
    'dick', 'cunt', 'slut', 'whore', 'bullshit', 'kurwa', 'dupa', 'putain',
    'merde', 'scheisse', 'arschloch', 'zorra'
}

TERMINOS_PRODUCTO_REVISION = {
    'adulterado', 'armas', 'contrabando', 'estafa', 'estafar',
    'falsificado', 'falsificacion', 'ilegal', 'medicamento',
    'esteroide', 'esteroides', 'robado'
}


def texto_moderacion(texto):
    """Normaliza texto para detectar insultos con acentos, simbolos o leetspeak."""
    texto = unicodedata.normalize('NFKD', texto.lower())
    texto = ''.join(char for char in texto if not unicodedata.combining(char))
    reemplazos = str.maketrans({'0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's',
                                '7': 't', '@': 'a', '$': 's'})
    texto = texto.translate(reemplazos)
    return re.sub(r'[^a-z0-9]+', ' ', texto)


def contiene_lenguaje_ofensivo(texto):
    normalizado = texto_moderacion(texto)
    tokens = set(normalizado.split())
    return bool(tokens.intersection(PALABRAS_PROHIBIDAS))


def motivo_revision_producto(texto):
    normalizado = texto_moderacion(texto)
    tokens = set(normalizado.split())
    motivos = []
    if tokens.intersection(PALABRAS_PROHIBIDAS):
        motivos.append('lenguaje ofensivo')
    if tokens.intersection(TERMINOS_PRODUCTO_REVISION) or {'arma', 'armas'}.issubset(tokens):
        motivos.append('contenido que requiere validación')
    return ', '.join(motivos) or None


def asegurar_columna_propietario_producto(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'productos'
              AND COLUMN_NAME = 'owner_user_id'
        ''')
        if not cursor.fetchone()[0]:
            cursor.execute('ALTER TABLE productos ADD COLUMN owner_user_id INT NULL AFTER id')
            conn.commit()
        cursor.execute('''
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'productos'
              AND COLUMN_NAME = 'en_oferta'
        ''')
        if not cursor.fetchone()[0]:
            cursor.execute('ALTER TABLE productos ADD COLUMN en_oferta TINYINT(1) NOT NULL DEFAULT 0')
            conn.commit()
        cursor.execute('''
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'productos'
              AND COLUMN_NAME = 'es_novedad'
        ''')
        if not cursor.fetchone()[0]:
            cursor.execute('ALTER TABLE productos ADD COLUMN es_novedad TINYINT(1) NOT NULL DEFAULT 0')
            conn.commit()
        cursor.execute('''
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'productos'
              AND COLUMN_NAME = 'estado_revision'
        ''')
        if not cursor.fetchone()[0]:
            cursor.execute("ALTER TABLE productos ADD COLUMN estado_revision ENUM('pendiente','aprobado','rechazado') NOT NULL DEFAULT 'aprobado'")
            conn.commit()
        cursor.execute('''
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'productos'
              AND COLUMN_NAME = 'variaciones'
        ''')
        if not cursor.fetchone()[0]:
            cursor.execute('ALTER TABLE productos ADD COLUMN variaciones JSON NULL')
            conn.commit()
        cursor.execute('''
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'productos'
              AND COLUMN_NAME = 'moderation_note'
        ''')
        if not cursor.fetchone()[0]:
            cursor.execute("ALTER TABLE productos ADD COLUMN moderation_note VARCHAR(255) NULL")
            conn.commit()
        cursor.execute('''
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'productos'
              AND COLUMN_NAME = 'destacado_solicitado'
        ''')
        if not cursor.fetchone()[0]:
            cursor.execute('ALTER TABLE productos ADD COLUMN destacado_solicitado TINYINT(1) NOT NULL DEFAULT 0')
            conn.commit()
        cursor.execute('''
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'productos'
              AND COLUMN_NAME = 'fecha_fin_oferta'
        ''')
        if not cursor.fetchone()[0]:
            cursor.execute('ALTER TABLE productos ADD COLUMN fecha_fin_oferta DATETIME NULL')
            conn.commit()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS producto_migraciones_catalogo (
                nombre VARCHAR(80) PRIMARY KEY,
                aplicado_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS producto_ofertas_empresa (
                producto_id INT PRIMARY KEY,
                precio_regular DECIMAL(12, 2) NOT NULL,
                porcentaje_descuento TINYINT UNSIGNED NOT NULL,
                fecha_activacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_ofertas_empresa_activacion (fecha_activacion)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        cursor.execute("SELECT nombre FROM producto_migraciones_catalogo WHERE nombre = 'banderas_iniciales'")
        if not cursor.fetchone():
            cursor.execute('''
                                UPDATE productos
                                SET en_oferta = 1, fecha_fin_oferta = DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 7 DAY)
                WHERE activo = 1 AND precio_anterior IS NOT NULL
                  AND precio_anterior > precio AND precio > 0 AND RAND() < 0.45
            ''')
            cursor.execute('UPDATE productos SET es_novedad = 1 WHERE activo = 1 AND RAND() < 0.25')
            cursor.execute("INSERT INTO producto_migraciones_catalogo (nombre) VALUES ('banderas_iniciales')")
            conn.commit()
        cursor.execute("SELECT nombre FROM producto_migraciones_catalogo WHERE nombre = 'ofertas_visibles_catalogo'")
        if not cursor.fetchone():
            cursor.execute('''
                UPDATE productos
                SET en_oferta = 1,
                    fecha_fin_oferta = CASE
                        WHEN en_oferta = 1 AND fecha_fin_oferta > CURRENT_TIMESTAMP THEN fecha_fin_oferta
                        ELSE DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 7 DAY)
                    END
                WHERE activo = 1 AND estado_revision = 'aprobado'
                  AND precio > 0 AND precio_anterior IS NOT NULL AND precio_anterior > precio
            ''')
            cursor.execute("INSERT INTO producto_migraciones_catalogo (nombre) VALUES ('ofertas_visibles_catalogo')")
            conn.commit()
    finally:
        cursor.close()


def asegurar_catalogo_empresa(conn):
    """Completa fichas vacías y activa una campaña persistente de ofertas de empresa."""
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT id, nombre, descripcion_corta, descripcion_larga,
                   subcategoria, marca, color, talla
            FROM productos
            WHERE descripcion_corta IS NULL OR TRIM(descripcion_corta) = ''
               OR descripcion_larga IS NULL OR TRIM(descripcion_larga) = ''
        ''')
        productos_sin_descripcion = cursor.fetchall()
        for fila in productos_sin_descripcion:
            producto_id, nombre, corta, larga, categoria, marca, color, talla = fila
            nombre = (nombre or 'Producto de tenis').strip()
            detalles = []
            if marca and str(marca).strip():
                detalles.append(f"Marca: {str(marca).strip()}")
            if categoria and str(categoria).strip():
                detalles.append(f"Categoría: {str(categoria).strip()}")
            if color and str(color).strip():
                detalles.append(f"Color: {str(color).strip()}")
            if talla and str(talla).strip():
                detalles.append(f"Talla: {str(talla).strip()}")

            descripcion_corta = (str(corta).strip() if corta and str(corta).strip()
                                 else ' · '.join([nombre] + detalles)[:255])
            descripcion_larga = (str(larga).strip() if larga and str(larga).strip()
                                 else (
                                     f"{nombre}. {' '.join(detalles)}. "
                                     "Consulta las características y la disponibilidad "
                                     "en esta ficha antes de comprar."
                                 )[:2000])
            cursor.execute('''
                UPDATE productos
                SET descripcion_corta = %s, descripcion_larga = %s
                WHERE id = %s
            ''', (descripcion_corta, descripcion_larga, producto_id))

        cursor.execute("""
            SELECT nombre FROM producto_migraciones_catalogo
            WHERE nombre = 'ofertas_empresa_iniciales_v1'
        """)
        if cursor.fetchone():
            conn.commit()
            return

        # Clear only expired non-company promotions before selecting new items.
        cursor.execute('''
            UPDATE productos
            SET precio = CASE
                    WHEN precio_anterior IS NOT NULL AND precio_anterior > precio THEN precio_anterior
                    ELSE precio
                END,
                precio_anterior = NULL,
                en_oferta = 0,
                fecha_fin_oferta = NULL
            WHERE en_oferta = 1 AND fecha_fin_oferta IS NOT NULL
              AND fecha_fin_oferta <= CURRENT_TIMESTAMP
              AND NOT EXISTS (
                  SELECT 1 FROM producto_ofertas_empresa oe
                  WHERE oe.producto_id = productos.id
              )
        ''')

        cursor.execute('''
            SELECT id, precio
            FROM productos
            WHERE activo = 1 AND estado_revision = 'aprobado'
              AND stock > 0 AND precio >= 10
              AND NOT (
                  en_oferta = 1 AND precio_anterior IS NOT NULL
                  AND precio_anterior > precio
                  AND (fecha_fin_oferta IS NULL OR fecha_fin_oferta > CURRENT_TIMESTAMP)
              )
              AND NOT EXISTS (
                  SELECT 1 FROM producto_ofertas_empresa oe
                  WHERE oe.producto_id = productos.id
              )
            ORDER BY RAND()
            LIMIT 5
        ''')
        seleccion = cursor.fetchall()
        ofertas_activadas = 0
        for producto_id, precio_actual in seleccion:
            precio_regular = Decimal(str(precio_actual))
            porcentaje = random.choice((10, 15, 20, 25))
            precio_oferta = (precio_regular * Decimal(100 - porcentaje) / Decimal(100)).quantize(
                Decimal('1'), rounding=ROUND_HALF_UP
            )
            if precio_oferta <= 0 or precio_oferta >= precio_regular:
                continue
            cursor.execute('''
                UPDATE productos
                SET precio_anterior = %s, precio = %s, en_oferta = 1, fecha_fin_oferta = NULL
                WHERE id = %s
            ''', (precio_regular, precio_oferta, producto_id))
            cursor.execute('''
                INSERT INTO producto_ofertas_empresa
                    (producto_id, precio_regular, porcentaje_descuento)
                VALUES (%s, %s, %s)
            ''', (producto_id, precio_regular, porcentaje))
            ofertas_activadas += 1

        if ofertas_activadas == 0:
            conn.commit()
            return

        cursor.execute("""
            INSERT INTO producto_migraciones_catalogo (nombre)
            VALUES ('ofertas_empresa_iniciales_v1')
        """)
        conn.commit()
    finally:
        cursor.close()


def expirar_ofertas(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('''
            UPDATE productos
            SET fecha_fin_oferta = DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 7 DAY)
            WHERE activo = 1 AND en_oferta = 1 AND fecha_fin_oferta IS NULL
              AND precio_anterior IS NOT NULL AND precio_anterior > precio
              AND NOT EXISTS (
                  SELECT 1 FROM producto_ofertas_empresa oe
                  WHERE oe.producto_id = productos.id
              )
        ''')
        ofertas_legacy = cursor.rowcount
        cursor.execute('''
            UPDATE productos
            SET precio = CASE
                    WHEN precio_anterior IS NOT NULL AND precio_anterior > precio THEN precio_anterior
                    ELSE precio
                END,
                precio_anterior = NULL,
                en_oferta = 0,
                fecha_fin_oferta = NULL
            WHERE en_oferta = 1 AND fecha_fin_oferta IS NOT NULL
              AND fecha_fin_oferta <= CURRENT_TIMESTAMP
              AND NOT EXISTS (
                  SELECT 1 FROM producto_ofertas_empresa oe
                  WHERE oe.producto_id = productos.id
              )
        ''')
        if ofertas_legacy or cursor.rowcount:
            conn.commit()
    finally:
        cursor.close()


def asegurar_tabla_favoritos(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS favoritos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                usuario_id INT NOT NULL,
                producto_id INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_favoritos_usuario (usuario_id),
                UNIQUE KEY uq_favoritos_usuario_producto (usuario_id, producto_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        cursor.execute('''
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'favoritos'
              AND INDEX_NAME = 'uq_favoritos_usuario_producto'
        ''')
        if not cursor.fetchone()[0]:
            cursor.execute('''
                SELECT 1 FROM favoritos
                GROUP BY usuario_id, producto_id HAVING COUNT(*) > 1 LIMIT 1
            ''')
            if not cursor.fetchone():
                cursor.execute('''
                    ALTER TABLE favoritos
                    ADD UNIQUE KEY uq_favoritos_usuario_producto (usuario_id, producto_id)
                ''')
        conn.commit()
    finally:
        cursor.close()


def asegurar_tabla_productos_vistos(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS productos_vistos (
                usuario_id INT NOT NULL,
                producto_id INT NOT NULL,
                visto_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (usuario_id, producto_id),
                INDEX idx_productos_vistos_recientes (usuario_id, visto_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        conn.commit()
    finally:
        cursor.close()


def asegurar_tabla_lista_deseos(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS lista_deseos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                usuario_id INT NOT NULL,
                producto_id INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_deseos_usuario (usuario_id),
                UNIQUE KEY uq_deseos_usuario_producto (usuario_id, producto_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        conn.commit()
    finally:
        cursor.close()


def asegurar_tabla_direcciones(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS direcciones_usuario (
                id INT AUTO_INCREMENT PRIMARY KEY,
                usuario_id INT NOT NULL,
                etiqueta VARCHAR(60) NOT NULL DEFAULT 'Casa',
                nombre_recibe VARCHAR(150) NOT NULL,
                telefono VARCHAR(40) NOT NULL,
                departamento VARCHAR(120) NOT NULL,
                ciudad VARCHAR(120) NOT NULL,
                barrio VARCHAR(120) NOT NULL,
                direccion VARCHAR(300) NOT NULL,
                complemento VARCHAR(150) NULL,
                codigo_postal VARCHAR(20) NULL,
                instrucciones VARCHAR(500) NULL,
                es_principal TINYINT(1) NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_direcciones_usuario (usuario_id, es_principal, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        conn.commit()
    finally:
        cursor.close()


def asegurar_tabla_solicitudes_reembolso(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS solicitudes_reembolso (
                id INT AUTO_INCREMENT PRIMARY KEY,
                factura_id INT NOT NULL,
                usuario_id INT NOT NULL,
                motivo VARCHAR(1000) NOT NULL,
                evidencia VARCHAR(255) NULL,
                estado VARCHAR(24) NOT NULL DEFAULT 'pendiente',
                respuesta_admin VARCHAR(1000) NULL,
                revisado_por INT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_reembolsos_factura (factura_id, created_at),
                INDEX idx_reembolsos_usuario (usuario_id, created_at),
                INDEX idx_reembolsos_estado (estado, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        cursor.execute('''
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'solicitudes_reembolso'
              AND COLUMN_NAME = 'evidencia'
        ''')
        if not cursor.fetchone()[0]:
            cursor.execute('ALTER TABLE solicitudes_reembolso ADD COLUMN evidencia VARCHAR(255) NULL AFTER motivo')
        for nombre_columna, definicion in (
            ('referencia_simulada', 'VARCHAR(80) NULL'),
            ('monto_simulado', 'DECIMAL(12,2) NULL'),
        ):
            cursor.execute('''
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'solicitudes_reembolso'
                  AND COLUMN_NAME = %s
            ''', (nombre_columna,))
            if not cursor.fetchone()[0]:
                cursor.execute(
                    f'ALTER TABLE solicitudes_reembolso ADD COLUMN {nombre_columna} {definicion}'
                )
        conn.commit()
    finally:
        cursor.close()


def sumar_dias_habiles(fecha_base, cantidad_dias):
    fecha = fecha_base.date() if isinstance(fecha_base, datetime) else fecha_base
    dias_sumados = 0
    while dias_sumados < cantidad_dias:
        fecha += timedelta(days=1)
        if fecha.weekday() < 5:
            dias_sumados += 1
    return fecha


def normalizar_termino_busqueda(texto):
    texto = unicodedata.normalize('NFKD', str(texto or '').casefold())
    return ''.join(caracter for caracter in texto if not unicodedata.combining(caracter))


def limpiar_datos_direccion(datos):
    return {
        'nombre_recibe': (datos.get('nombre_recibe') or '').strip()[:150],
        'telefono': (datos.get('telefono') or '').strip()[:40],
        'departamento': (datos.get('departamento') or '').strip()[:120],
        'ciudad': (datos.get('ciudad') or '').strip()[:120],
        'barrio': (datos.get('barrio') or '').strip()[:120],
        'direccion': (datos.get('direccion') or '').strip()[:300],
        'complemento': (datos.get('complemento') or '').strip()[:150],
        'codigo_postal': (datos.get('codigo_postal') or '').strip()[:20],
        'instrucciones': (datos.get('instrucciones') or '').strip()[:500],
    }


def asegurar_tablas_seguimiento_envios(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS marketplace_envios (
                id INT AUTO_INCREMENT PRIMARY KEY,
                factura_id INT NOT NULL,
                usuario_id INT NOT NULL,
                tienda_user_id INT NULL,
                numero_envio VARCHAR(40) NOT NULL UNIQUE,
                estado VARCHAR(32) NOT NULL DEFAULT 'pedido_recibido',
                nombre_recibe VARCHAR(150) NULL,
                direccion_envio VARCHAR(300) NOT NULL,
                departamento_envio VARCHAR(120) NULL,
                ciudad_envio VARCHAR(120) NOT NULL,
                barrio_envio VARCHAR(120) NULL,
                complemento_envio VARCHAR(150) NULL,
                codigo_postal_envio VARCHAR(20) NULL,
                telefono_envio VARCHAR(40) NOT NULL,
                instrucciones_envio VARCHAR(500) NULL,
                fecha_estimada DATE NULL,
                transportadora VARCHAR(100) NULL,
                codigo_seguimiento VARCHAR(120) NULL,
                url_seguimiento VARCHAR(500) NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                entregado_at DATETIME NULL,
                archivado_por_usuario_at DATETIME NULL,
                INDEX idx_marketplace_envios_usuario (usuario_id, created_at),
                INDEX idx_marketplace_envios_tienda (tienda_user_id, estado)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS marketplace_envio_eventos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                envio_id INT NOT NULL,
                actor_user_id INT NULL,
                estado VARCHAR(32) NOT NULL,
                descripcion VARCHAR(500) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_marketplace_eventos_envio (envio_id, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        columnas_envio = (
            ('nombre_recibe', 'VARCHAR(150) NULL'),
            ('departamento_envio', 'VARCHAR(120) NULL'),
            ('barrio_envio', 'VARCHAR(120) NULL'),
            ('complemento_envio', 'VARCHAR(150) NULL'),
            ('codigo_postal_envio', 'VARCHAR(20) NULL'),
            ('instrucciones_envio', 'VARCHAR(500) NULL'),
            ('entregado_at', 'DATETIME NULL'),
            ('archivado_por_usuario_at', 'DATETIME NULL'),
        )
        for nombre_columna, definicion_columna in columnas_envio:
            cursor.execute('''
                SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'marketplace_envios'
                  AND COLUMN_NAME = %s
            ''', (nombre_columna,))
            if not cursor.fetchone()[0]:
                cursor.execute(f'ALTER TABLE marketplace_envios ADD COLUMN {nombre_columna} {definicion_columna}')
        conn.commit()
    finally:
        cursor.close()


def asegurar_tabla_valoraciones_producto(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS producto_valoraciones (
                id INT AUTO_INCREMENT PRIMARY KEY,
                producto_id INT NOT NULL,
                usuario_id INT NOT NULL,
                calificacion TINYINT NOT NULL,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY valoracion_producto_usuario (producto_id, usuario_id),
                FOREIGN KEY (producto_id) REFERENCES productos(id) ON DELETE CASCADE,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        conn.commit()
    finally:
        cursor.close()


def imagen_producto_valida(file_storage):
    extension = os.path.splitext(secure_filename(file_storage.filename or ''))[1].lower()
    if extension not in {'.png', '.jpg', '.jpeg', '.gif', '.webp'}:
        return False
    cabecera = file_storage.stream.read(12)
    file_storage.stream.seek(0)
    firmas = (
        cabecera.startswith(b'\x89PNG'),
        cabecera.startswith(b'\xff\xd8\xff'),
        cabecera.startswith((b'GIF87a', b'GIF89a')),
        cabecera.startswith(b'RIFF') and cabecera[8:12] == b'WEBP',
    )
    return any(firmas)


def usuario_baneado(usuario_id):
    conn = get_db_connection()
    if not conn:
        return False, None
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT baneado, motivo_baneo FROM usuarios WHERE id = %s", (usuario_id,))
        usuario = cursor.fetchone() or {}
        return bool(usuario.get('baneado')), usuario.get('motivo_baneo')
    except sqlite3.Error:
        return False, None
    finally:
        if cursor:
            cursor.close()
        conn.close()


def asegurar_tabla_bloqueos_usuarios(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bloqueos_usuarios (
                bloqueador_id INT NOT NULL,
                bloqueado_id INT NOT NULL,
                fecha_bloqueo TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (bloqueador_id, bloqueado_id),
                INDEX idx_bloqueos_bloqueado (bloqueado_id),
                CONSTRAINT fk_bloqueos_bloqueador
                    FOREIGN KEY (bloqueador_id) REFERENCES usuarios(id) ON DELETE CASCADE,
                CONSTRAINT fk_bloqueos_bloqueado
                    FOREIGN KEY (bloqueado_id) REFERENCES usuarios(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
    finally:
        cursor.close()


def usuarios_bloqueados(cursor, primer_usuario_id, segundo_usuario_id):
    cursor.execute('''
        SELECT 1 FROM bloqueos_usuarios
        WHERE (bloqueador_id = %s AND bloqueado_id = %s)
           OR (bloqueador_id = %s AND bloqueado_id = %s)
        LIMIT 1
    ''', (primer_usuario_id, segundo_usuario_id, segundo_usuario_id, primer_usuario_id))
    return cursor.fetchone() is not None


def banear_usuario_por_moderacion(usuario_id, motivo, evidencia, locacion_id):
    conn = get_db_connection()
    if not conn:
        return False
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE usuarios
            SET baneado = 1, motivo_baneo = %s, evidencia_baneo = %s,
                locacion_baneo = %s, fecha_baneo = NOW()
            WHERE id = %s
        """, (motivo, evidencia, locacion_id, usuario_id))
        conn.commit()
        return True
    except sqlite3.Error as err:
        conn.rollback()
        print(f"Error aplicando baneo automatico: {err}")
        return False
    finally:
        if cursor:
            cursor.close()
        conn.close()


def asegurar_tabla_notificaciones_productos(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notificaciones_productos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                usuario_id INT NOT NULL,
                titulo VARCHAR(180) NOT NULL,
                mensaje TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_notificaciones_productos_usuario (usuario_id, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        conn.commit()
    finally:
        cursor.close()


def asegurar_tablas_proceso_tienda(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tienda_procesos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                tienda_id INT NOT NULL UNIQUE,
                estado VARCHAR(32) NOT NULL DEFAULT 'conversacion',
                acuerdo TEXT NULL,
                tienda_acepto TINYINT(1) NOT NULL DEFAULT 0,
                admin_pendiente TINYINT(1) NOT NULL DEFAULT 0,
                tienda_pendiente TINYINT(1) NOT NULL DEFAULT 0,
                ubicacion_ciudad VARCHAR(120) NULL,
                ubicacion_direccion VARCHAR(255) NULL,
                lat DECIMAL(10,7) NULL,
                lng DECIMAL(10,7) NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                CONSTRAINT fk_tienda_procesos_usuario FOREIGN KEY (tienda_id)
                    REFERENCES usuarios(id) ON DELETE CASCADE,
                INDEX idx_tienda_procesos_estado (estado)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tienda_proceso_mensajes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                proceso_id INT NOT NULL,
                emisor_id INT NULL,
                tipo VARCHAR(24) NOT NULL DEFAULT 'texto',
                texto TEXT NOT NULL,
                datos_extra JSON NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_tienda_proceso_mensaje_proceso FOREIGN KEY (proceso_id)
                    REFERENCES tienda_procesos(id) ON DELETE CASCADE,
                CONSTRAINT fk_tienda_proceso_mensaje_emisor FOREIGN KEY (emisor_id)
                    REFERENCES usuarios(id) ON DELETE SET NULL,
                INDEX idx_tienda_proceso_mensajes (proceso_id, created_at, id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        conn.commit()
    finally:
        cursor.close()


def obtener_proceso_tienda(conn, tienda_id):
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "INSERT IGNORE INTO tienda_procesos (tienda_id) VALUES (%s)",
            (tienda_id,)
        )
        cursor.execute('SELECT * FROM tienda_procesos WHERE tienda_id = %s', (tienda_id,))
        proceso = cursor.fetchone()
        cursor.execute(
            'SELECT COUNT(*) AS total FROM tienda_proceso_mensajes WHERE proceso_id = %s',
            (proceso['id'],)
        )
        if not cursor.fetchone()['total']:
            cursor.execute('''
                INSERT INTO tienda_proceso_mensajes (proceso_id, tipo, texto)
                VALUES (%s, 'sistema', %s)
            ''', (
                proceso['id'],
                'Bienvenida a TENNISSEL. Cuéntanos sobre tu tienda y coordinaremos aquí las condiciones, la logística y la publicación de tus productos.'
            ))
            conn.commit()
        return proceso
    finally:
        cursor.close()


def tienda_tiene_acuerdo_activo(conn, tienda_id):
    asegurar_tablas_proceso_tienda(conn)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT 1 FROM tienda_procesos
            WHERE tienda_id = %s AND estado = 'activo' AND tienda_acepto = 1
              AND acuerdo IS NOT NULL AND TRIM(acuerdo) <> ''
              AND ubicacion_ciudad IS NOT NULL AND TRIM(ubicacion_ciudad) <> ''
              AND ubicacion_direccion IS NOT NULL AND TRIM(ubicacion_direccion) <> ''
        ''', (tienda_id,))
        return cursor.fetchone() is not None
    finally:
        cursor.close()


@app.route('/tienda/productos/plantilla.csv')
@tienda_premium_required
def plantilla_carga_productos_tienda():
    contenido = (
        'nombre,descripcion,categoria,precio,stock,sku,marca,subcategoria,color,talla,peso,precio_anterior,imagen\n'
        '"Raqueta de ejemplo","Descripción del producto","Raquetas",250000,5,RAQ-001,Marca,Raquetas,Negro,L3,0.3,,raqueta.jpg\n'
    )
    return Response(
        contenido,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=plantilla_productos_tennissel.csv'}
    )


def contar_notificaciones(user_id):
    """Cuenta todas las notificaciones disponibles para un usuario."""
    conn = get_db_connection()
    if not conn:
        return 0

    cursor = None
    try:
        asegurar_tabla_notificaciones_productos(conn)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*)
            FROM (
                SELECT id FROM soporte_tecnico
                WHERE usuario_id = %s AND respuesta IS NOT NULL
                UNION ALL
                SELECT id FROM solicitudes_contacto
                WHERE usuario_id = %s AND respuesta IS NOT NULL
                UNION ALL
                SELECT id FROM notificaciones_moderacion
                WHERE usuario_id = %s
                UNION ALL
                SELECT id FROM notificaciones_productos
                WHERE usuario_id = %s
            ) AS notificaciones
        """, (user_id, user_id, user_id, user_id))
        resultado = cursor.fetchone()
        return resultado[0] if resultado else 0
    except sqlite3.Error as err:
        print(f"Error contando notificaciones: {err}")
        return 0
    finally:
        if cursor:
            cursor.close()
        conn.close()


def contar_solicitudes_productos_pendientes():
    """Cuenta propuestas de tienda pendientes para mostrarlas a administración."""
    cache_key = 'solicitudes_productos_pendientes'
    if hasattr(g, cache_key):
        return getattr(g, cache_key)

    conn = get_db_connection()
    if not conn:
        app.logger.error('No se pudo consultar la cola de solicitudes pendientes de productos.')
        setattr(g, cache_key, 0)
        return 0

    cursor = None
    try:
        asegurar_columna_propietario_producto(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM productos
            WHERE owner_user_id IS NOT NULL AND estado_revision = 'pendiente'
        """)
        total = int(cursor.fetchone()['total'])
        setattr(g, cache_key, total)
        return total
    except sqlite3.Error as err:
        print(f'Error contando solicitudes pendientes de productos: {err}')
        setattr(g, cache_key, 0)
        return 0
    finally:
        if cursor:
            cursor.close()
        conn.close()


@app.context_processor
def contexto_usuario():
    """Expone el estado de autenticación y Premium a todas las plantillas."""
    autenticado = 'user_id' in session
    foto_usuario_url = url_for('static', filename=f'IMG/{PROFILE_AVATARS[0]}', v='20261005-7')
    if autenticado:
        conn_foto = get_db_connection()
        if conn_foto is not None:
            cursor_foto = None
            try:
                cursor_foto = conn_foto.cursor()
                cursor_foto.execute(
                    'SELECT foto FROM perfil_usuario WHERE usuario_id = %s',
                    (session['user_id'],)
                )
                foto_row = cursor_foto.fetchone()
                foto_usuario_url = foto_perfil_url(foto_row[0] if foto_row else None)
            except sqlite3.Error as err:
                app.logger.exception('No se pudo cargar la foto del usuario para la plantilla: %s', err)
            finally:
                if cursor_foto:
                    cursor_foto.close()
                conn_foto.close()
    esta_baneado = bool(usuario_baneado(session['user_id'])[0]) if autenticado else False
    es_premium = autenticado and (
        session.get('role') in ('admin', 'premium')
        or verificar_premium(session['user_id'])
    )
    return {
        'usuario_autenticado': autenticado,
        'is_premium': es_premium,
        'is_banned': esta_baneado,
        'profile_photo_url': foto_usuario_url,
        'notification_count': contar_notificaciones(session['user_id']) if autenticado else 0,
        'product_review_count': contar_solicitudes_productos_pendientes()
        if autenticado and session.get('role') == 'admin' else 0,
    }


# ═══════════════════════════════════════════════════════════════════════════
# RUTAS PUBLICAS
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/robots.txt')
def robots_txt():
    contenido = f"User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /tienda/\nSitemap: {url_for('sitemap_xml', _external=True)}\n"
    return Response(contenido, mimetype='text/plain')


@app.route('/sitemap.xml')
def sitemap_xml():
    urls = [url_for('index', _external=True), url_for('productos', _external=True)]
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute('SELECT slug FROM productos WHERE activo = 1 ORDER BY id DESC')
            urls.extend(url_for('producto_detalle', slug=row['slug'], _external=True) for row in cursor.fetchall())
        finally:
            cursor.close()
            conn.close()
    xml = '<?xml version="1.0" encoding="UTF-8"?>' + '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    xml += ''.join(f'<url><loc>{url}</loc></url>' for url in urls)
    xml += '</urlset>'
    return Response(xml, mimetype='application/xml')


@app.route('/juegos')
def juegos():
    """Centro de minijuegos de TENNISSEL."""
    return render_template('juegos.html')


@app.route('/juego')
def juego():
    """Partido interactivo Tennis Arena."""
    return render_template('juego.html')


def asegurar_tablas_recompensas_juego(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tennissel_juego_recompensas (
                usuario_id INT NOT NULL PRIMARY KEY,
                victorias INT NOT NULL DEFAULT 0,
                giros_disponibles INT NOT NULL DEFAULT 0,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tennissel_juego_partidas (
                usuario_id INT NOT NULL,
                partida_id VARCHAR(80) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (usuario_id, partida_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tennissel_ruleta_cupones (
                codigo VARCHAR(40) NOT NULL PRIMARY KEY,
                usuario_id INT NOT NULL,
                tipo VARCHAR(20) NOT NULL,
                valor VARCHAR(30) NOT NULL,
                usado TINYINT(1) NOT NULL DEFAULT 0,
                factura_id INT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_ruleta_cupon_usuario (usuario_id, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        cursor.execute('''
            SELECT COLUMN_NAME FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tennissel_ruleta_cupones'
        ''')
        columnas = {fila[0] for fila in cursor.fetchall()}
        if 'usado' not in columnas:
            cursor.execute('ALTER TABLE tennissel_ruleta_cupones ADD COLUMN usado TINYINT(1) NOT NULL DEFAULT 0')
        if 'factura_id' not in columnas:
            cursor.execute('ALTER TABLE tennissel_ruleta_cupones ADD COLUMN factura_id INT NULL')
    finally:
        cursor.close()


def leer_recompensas_juego(cursor, usuario_id):
    cursor.execute(
        'SELECT victorias, giros_disponibles FROM tennissel_juego_recompensas WHERE usuario_id = %s',
        (usuario_id,)
    )
    fila = cursor.fetchone()
    victorias, giros = fila if fila else (0, 0)
    return {'victorias': int(victorias), 'giros': int(giros), 'restantes': (100 - int(victorias) % 100) % 100 or 100}


def ruleta_usuario_permitido():
    return session.get('role') not in {'admin', 'tienda'}


@app.route('/api/juego/recompensas')
def api_recompensas_juego():
    usuario_id = session.get('user_id')
    if not usuario_id or not ruleta_usuario_permitido():
        return jsonify(autenticado=False, victorias=0, giros=0, restantes=100)
    conn = get_db_connection()
    if not conn:
        return jsonify(error='No se pudo consultar el progreso.'), 503
    cursor = None
    try:
        asegurar_tablas_recompensas_juego(conn)
        cursor = conn.cursor()
        return jsonify(autenticado=True, **leer_recompensas_juego(cursor, usuario_id))
    except sqlite3.Error as err:
        print(f'Error al consultar recompensas de juego: {err}')
        return jsonify(error='No se pudo consultar el progreso.'), 500
    finally:
        if cursor:
            cursor.close()
        conn.close()


@app.route('/api/juego/victoria', methods=['POST'])
@login_required
def api_registrar_victoria_juego():
    if not ruleta_usuario_permitido():
        return jsonify(error='Esta recompensa es para cuentas de jugador.'), 403
    datos = request.get_json(silent=True) or {}
    partida_id = str(datos.get('partida_id') or '').strip()
    modo = str(datos.get('modo') or '').strip()
    if modo not in {'solo', 'local', 'doubles', 'doubles_local'} or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', partida_id):
        return jsonify(error='El resultado de la partida no es válido.'), 400

    conn = get_db_connection()
    if not conn:
        return jsonify(error='No se pudo guardar la victoria.'), 503
    cursor = None
    try:
        asegurar_tablas_recompensas_juego(conn)
        conn.start_transaction()
        cursor = conn.cursor()
        cursor.execute('INSERT IGNORE INTO tennissel_juego_recompensas (usuario_id) VALUES (%s)', (session['user_id'],))
        cursor.execute(
            'INSERT IGNORE INTO tennissel_juego_partidas (usuario_id, partida_id) VALUES (%s, %s)',
            (session['user_id'], partida_id)
        )
        giro_desbloqueado = False
        if cursor.rowcount:
            cursor.execute('''
                SELECT victorias, giros_disponibles FROM tennissel_juego_recompensas
                WHERE usuario_id = %s FOR UPDATE
            ''', (session['user_id'],))
            victorias, giros = cursor.fetchone()
            nuevas_victorias = int(victorias) + 1
            giro_desbloqueado = nuevas_victorias % 100 == 0
            nuevos_giros = int(giros) + (1 if nuevas_victorias % 100 == 0 else 0)
            cursor.execute('''
                UPDATE tennissel_juego_recompensas SET victorias = %s, giros_disponibles = %s
                WHERE usuario_id = %s
            ''', (nuevas_victorias, nuevos_giros, session['user_id']))
        estado = leer_recompensas_juego(cursor, session['user_id'])
        conn.commit()
        return jsonify(ok=True, giro_desbloqueado=giro_desbloqueado, **estado)
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error al guardar victoria de juego: {err}')
        return jsonify(error='No se pudo guardar la victoria.'), 500
    finally:
        if cursor:
            cursor.close()
        conn.close()


@app.route('/api/juego/ruleta/girar', methods=['POST'])
@login_required
def api_girar_ruleta_juego():
    if not ruleta_usuario_permitido():
        return jsonify(error='Esta recompensa es para cuentas de jugador.'), 403
    premios = [
        {'texto': '5% OFF', 'tipo': 'descuento', 'valor': '5%'},
        {'texto': '10% OFF', 'tipo': 'descuento', 'valor': '10%'},
        {'texto': '15% OFF', 'tipo': 'descuento', 'valor': '15%'},
        {'texto': '20% OFF', 'tipo': 'descuento', 'valor': '20%'},
        {'texto': 'ENVIO GRATIS', 'tipo': 'envio', 'valor': 'ENVIO GRATIS'},
        {'texto': '5% OFF', 'tipo': 'descuento', 'valor': '5%'},
        {'texto': '25% OFF', 'tipo': 'descuento', 'valor': '25%'},
        {'texto': '30% OFF', 'tipo': 'descuento', 'valor': '30%'}
    ]
    conn = get_db_connection()
    if not conn:
        return jsonify(error='No se pudo iniciar la ruleta.'), 503
    cursor = None
    try:
        asegurar_tablas_recompensas_juego(conn)
        conn.start_transaction()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT victorias, giros_disponibles FROM tennissel_juego_recompensas
            WHERE usuario_id = %s FOR UPDATE
        ''', (session['user_id'],))
        fila = cursor.fetchone()
        if not fila or int(fila[1]) < 1:
            conn.rollback()
            return jsonify(error='Necesitas 100 victorias por cada giro de la ruleta.',
                           victorias=int(fila[0]) if fila else 0, giros=0), 403
        indice = secrets.randbelow(len(premios))
        premio = premios[indice]
        codigo = f"TENNIS{session['user_id']}{secrets.token_hex(4).upper()}"
        cursor.execute('''
            UPDATE tennissel_juego_recompensas SET giros_disponibles = giros_disponibles - 1
            WHERE usuario_id = %s AND giros_disponibles > 0
        ''', (session['user_id'],))
        cursor.execute('''
            INSERT INTO tennissel_ruleta_cupones (codigo, usuario_id, tipo, valor)
            VALUES (%s, %s, %s, %s)
        ''', (codigo, session['user_id'], premio['tipo'], premio['valor']))
        estado = leer_recompensas_juego(cursor, session['user_id'])
        conn.commit()
        return jsonify(ok=True, premio_index=indice, premio=premio, codigo=codigo, **estado)
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error al girar ruleta: {err}')
        return jsonify(error='No se pudo completar el giro.'), 500
    finally:
        if cursor:
            cursor.close()
        conn.close()


@app.route('/api/juego/cupon/validar', methods=['POST'])
@login_required
def api_validar_cupon_juego():
    if not ruleta_usuario_permitido():
        return jsonify(error='Este cupón es para cuentas de jugador.'), 403
    datos = request.get_json(silent=True) or {}
    codigo = str(datos.get('codigo') or '').strip().upper()[:40]
    if not codigo:
        return jsonify(error='Escribe el código de tu premio.'), 400
    conn = get_db_connection()
    if not conn:
        return jsonify(error='No se pudo validar el código.'), 503
    cursor = None
    try:
        asegurar_tablas_recompensas_juego(conn)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT tipo, valor FROM tennissel_ruleta_cupones
            WHERE codigo = %s AND usuario_id = %s AND usado = 0
        ''', (codigo, session['user_id']))
        cupon = cursor.fetchone()
        if not cupon:
            return jsonify(error='El código no existe, ya se usó o pertenece a otra cuenta.'), 404
        tipo, valor = cupon
        return jsonify(ok=True, codigo=codigo, tipo=tipo, valor=valor)
    except sqlite3.Error as err:
        print(f'Error al validar cupón de ruleta: {err}')
        return jsonify(error='No se pudo validar el código.'), 500
    finally:
        if cursor:
            cursor.close()
        conn.close()


SECCIONES_INFORMATIVAS = {
    'jugadores': ('Jugadores', 'Conoce cómo analizar el estilo, la evolución y los resultados de los tenistas del circuito.'),
    'partidos_recientes': ('Partidos recientes', 'Aprende a leer resultados, estadísticas y decisiones que definen cada encuentro.'),
    'datos_y_tips': ('Datos y tips', 'Convierte estadísticas y hábitos de entrenamiento en mejoras concretas para tu juego.'),
    'noticias_semanales': ('Noticias semanales', 'Sigue los resultados, el ranking y el calendario con el contexto de cada semana.'),
    'noticias_new': ('Noticias de último momento', 'Consulta novedades del circuito y aprende a diferenciar información confirmada de rumores.'),
    'marcas_y_utiles': ('Marcas y útiles', 'Elige raquetas, calzado y accesorios según tu nivel, superficie y forma de jugar.'),
    'sitios_tennis': ('Sitios para ver tenis', 'Encuentra recursos para seguir marcadores, calendarios, estadísticas y transmisiones.'),
}


def mostrar_seccion_informativa(seccion):
    """Carga el contenido editable y conserva la guía completa si la tabla está vacía."""
    titulo, descripcion = SECCIONES_INFORMATIVAS[seccion]
    bloques = []
    conn = get_db_connection()
    if conn:
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            # El nombre procede exclusivamente del diccionario anterior, no de la petición.
            cursor.execute(
                f'SELECT tipo, titulo, texto, orden FROM contenido_{seccion} '
                'WHERE activo = TRUE ORDER BY orden, id'
            )
            bloques = cursor.fetchall()
        except sqlite3.Error as err:
            print(f'Error cargando contenido de {seccion}: {err}')
        finally:
            if cursor:
                cursor.close()
            conn.close()
    return render_template('informacion/info_generica.html', titulo=titulo, descripcion=descripcion, bloques=bloques)


@app.route('/informacion/jugadores')
def informacion_jugadores():
    return mostrar_seccion_informativa('jugadores')


@app.route('/informacion/atp_wta')
def informacion_atp_wta():
    return render_template('informacion/atp_wta.html')


@app.route('/informacion/datos_y_tips')
def informacion_datos_y_tips():
    return mostrar_seccion_informativa('datos_y_tips')


@app.route('/informacion/noticias_new')
def informacion_noticias_new():
    return mostrar_seccion_informativa('noticias_new')


@app.route('/informacion/noticias_semanales')
def informacion_noticias_semanales():
    return mostrar_seccion_informativa('noticias_semanales')


@app.route('/informacion/partidos_recientes')
def informacion_partidos_recientes():
    return mostrar_seccion_informativa('partidos_recientes')


@app.route('/informacion/sitios_tennis')
def informacion_sitios_tennis():
    return mostrar_seccion_informativa('sitios_tennis')


@app.route('/informacion/torneos')
def informacion_torneos():
    """Muestra los bloques y eventos que administra el panel de torneos."""
    contenidos, torneos = [], []
    conn = get_db_connection()
    if conn:
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute('''
                SELECT tipo, titulo, texto, orden
                FROM contenido_torneos
                WHERE activo = TRUE
                ORDER BY orden, id
            ''')
            contenidos = cursor.fetchall()
            cursor.execute('''
                SELECT id, nombre, categoria, fecha, lugar, nivel, descripcion
                FROM torneos
                WHERE activo = TRUE
                ORDER BY orden, id
            ''')
            torneos = cursor.fetchall()
        except sqlite3.Error as err:
            # La página sigue disponible aunque todavía no se haya aplicado la migración.
            print(f'Error cargando torneos: {err}')
        finally:
            if cursor:
                cursor.close()
            conn.close()
    return render_template('informacion/torneos.html', contenidos=contenidos, torneos=torneos)


@app.route('/informacion/marcas_y_utiles')
def informacion_marcas_y_utiles():
    return mostrar_seccion_informativa('marcas_y_utiles')





@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if 'user_id' in session:
        flash('Ya tienes una sesión iniciada.', 'info')
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        telefono = request.form.get('telefono', '').strip()
        email = request.form.get('email', '').strip()
        ciudad = request.form.get('ciudad', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        nivel = request.form.get('nivel', 'principiante')
        rol = request.form.get('rol', 'cliente')

        if not username or not email or not password:
            flash('Por favor, completa todos los campos obligatorios.', 'error')
            return redirect(url_for('registro'))

        if password != confirm_password:
            flash('Las contraseñas no coinciden.', 'error')
            return redirect(url_for('registro'))

        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'error')
            return redirect(url_for('registro'))

        if nivel not in {'principiante', 'intermedio', 'avanzado'} or rol not in {'cliente', 'profesor', 'tienda'}:
            flash('Selecciona un nivel y tipo de cuenta válidos.', 'error')
            return redirect(url_for('registro'))

        hashed_password = generate_password_hash(password)
        conn = get_db_connection()
        if conn is None:
            flash('Error al conectar con la base de datos.', 'error')
            return redirect(url_for('registro'))

        try:
            cursor = conn.cursor()
            query_usuario = """
                INSERT INTO usuarios (username, nombre_completo, email, telefono, ciudad, password, rol)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query_usuario, (username, username, email, telefono, ciudad or None, hashed_password, rol))
            usuario_id = cursor.lastrowid

            query_perfil_defecto = """
                INSERT INTO perfil_usuario (usuario_id, foto, nivel, mano, reves)
                VALUES (%s, 'default.png', %s, 'diestro', 'dos_manos')
            """
            cursor.execute(query_perfil_defecto, (usuario_id, nivel))
            conn.commit()
            flash('Registro exitoso! Por favor inicia sesion.', 'success')
            return redirect(url_for('login'))
        except sqlite3.Error as err:
            conn.rollback()
            print(f"Error al registrar: {err}")
            flash('No fue posible registrar el usuario. El correo o usuario ya existen.', 'error')
            return redirect(url_for('registro'))
        finally:
            cursor.close()
            conn.close()

    return render_template('registro.html')


@app.route("/login", methods=["GET", "POST"])
def login():
    if 'user_id' in session:
        flash('Ya tienes una sesión iniciada.', 'info')
        return redirect(url_for('index'))

    if request.method == "POST":
        email = request.form.get("email", '').strip()
        password = request.form.get("password", '')
        conn = get_db_connection()
        if conn is None:
            flash("Error de conexion.", "error")
            return redirect(url_for("login"))

        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM usuarios WHERE email = %s", (email,))
            usuario = cursor.fetchone()
        except sqlite3.Error as err:
            print(f"Error: {err}")
            flash("Error al consultar la base de datos.", "error")
            return redirect(url_for("login"))
        finally:
            cursor.close()
            conn.close()

        if usuario and check_password_hash(usuario["password"], password):
            asegurar_avatar_predeterminado(usuario['id'])
            session['user_id'] = usuario['id']
            session['username'] = usuario['username']
            session['role'] = usuario['rol']
            if usuario.get('baneado'):
                flash('Tu cuenta esta bloqueada. Puedes consultar o enviar una apelación.', 'error')
                return redirect(url_for('apelar_baneo'))
            flash(f"Bienvenido de vuelta, {usuario['username']}!", "success")
            return redirect(url_for("index"))
        flash("Correo o contrasena incorrectos.", "error")

    return render_template("login.html")


@app.route('/logout')
def logout():
    session.clear()
    flash('Has cerrado sesion correctamente.', 'info')
    return redirect(url_for('index'))


@app.route('/productos')
def productos():
    subcat = request.args.get('subcategoria') or request.args.get('categoria')
    marca = request.args.get('marca')
    color = request.args.get('color')
    talla = request.args.get('talla')
    precio_min = request.args.get('precio_min')
    precio_max = request.args.get('precio_max')
    orden = request.args.get('orden')
    coleccion = request.args.get('coleccion', '')
    busqueda = request.args.get('q', '').strip()[:120]
    lista_guardados = request.args.get('lista', '')
    if lista_guardados not in {'favoritos', 'deseos'}:
        lista_guardados = ''
    if lista_guardados and not session.get('user_id'):
        return redirect(url_for('login', next=request.full_path.rstrip('?')))

    query = '''SELECT productos.*,
                      (SELECT categorias.nombre FROM categorias
                       WHERE categorias.id = productos.categoria_id LIMIT 1) AS categoria,
                      COALESCE((SELECT AVG(pv.calificacion) FROM producto_valoraciones pv
                                WHERE pv.producto_id = productos.id), 0) AS valoracion_promedio,
                      (SELECT COUNT(*) FROM producto_valoraciones pv
                       WHERE pv.producto_id = productos.id) AS total_valoraciones
               FROM productos WHERE activo = 1 AND estado_revision = 'aprobado' '''
    params = []

    if busqueda:
        terminos = re.findall(r'[\w]+', busqueda, flags=re.UNICODE)[:8]
        campos_busqueda = ('nombre', 'marca', 'subcategoria', 'color', 'talla', 'sku', 'descripcion_corta')
        for termino in terminos:
            query += ' AND (' + ' OR '.join(f'{campo} LIKE %s' for campo in campos_busqueda) + ')'
            params.extend([f'%{termino}%' for _ in campos_busqueda])

    if coleccion == 'ofertas':
        query += " AND en_oferta = 1 AND precio_anterior IS NOT NULL AND precio_anterior > precio AND precio > 0"
    elif coleccion == 'novedades':
        query += ' AND es_novedad = 1'

    if lista_guardados == 'favoritos':
        query += ' AND EXISTS (SELECT 1 FROM favoritos f WHERE f.producto_id = productos.id AND f.usuario_id = %s)'
        params.append(session['user_id'])
    elif lista_guardados == 'deseos':
        query += ' AND EXISTS (SELECT 1 FROM lista_deseos d WHERE d.producto_id = productos.id AND d.usuario_id = %s)'
        params.append(session['user_id'])

    if subcat and subcat != 'Todas':
        query += " AND subcategoria = %s"
        params.append(subcat)
    if marca:
        query += " AND marca LIKE %s"
        params.append(f"%{marca}%")
    if color:
        query += " AND color LIKE %s"
        params.append(f"%{color}%")
    if talla:
        query += " AND talla = %s"
        params.append(talla)
    if precio_min:
        query += " AND precio >= %s"
        params.append(precio_min)
    if precio_max:
        query += " AND precio <= %s"
        params.append(precio_max)
    ordenes_catalogo = {
        'precio_asc': 'precio ASC',
        'precio_desc': 'precio DESC',
        'mejor_valorados': 'valoracion_promedio DESC, total_valoraciones DESC, productos.id DESC',
        'mas_vendidos': '''COALESCE((
            SELECT SUM(df.cantidad)
            FROM detalle_factura df
            JOIN facturas f ON f.id = df.factura_id
            WHERE df.producto_id = productos.id AND f.estado = 'pagado'
        ), 0) DESC, created_at DESC, id DESC''',
        'nombre_asc': 'nombre ASC',
        'nombre_desc': 'nombre DESC'
    }
    parametros_orden = []
    orden_sql = ordenes_catalogo.get(orden)
    if orden == 'recientes' and session.get('user_id'):
        orden_sql = '''(SELECT MAX(pv.visto_at) FROM productos_vistos pv
                        WHERE pv.usuario_id = %s AND pv.producto_id = productos.id) IS NULL,
                       (SELECT MAX(pv.visto_at) FROM productos_vistos pv
                        WHERE pv.usuario_id = %s AND pv.producto_id = productos.id) DESC,
                       created_at DESC, id DESC'''
        parametros_orden.extend((session['user_id'], session['user_id']))
    elif orden == 'recientes':
        vistos = session.get('productos_vistos', [])
        vistos = list(dict.fromkeys(producto_id for producto_id in vistos if isinstance(producto_id, int)))[:40]
        if vistos:
            placeholders = ', '.join(['%s'] * len(vistos))
            orden_sql = f'FIELD(productos.id, {placeholders}), created_at DESC, id DESC'
            parametros_orden.extend(vistos)
        else:
            orden_sql = 'created_at DESC, id DESC'
    if not orden_sql and coleccion == 'novedades':
        orden_sql = 'created_at DESC, id DESC'
    elif not orden_sql and coleccion == 'ofertas':
        orden_sql = '(precio_anterior - precio) / precio_anterior DESC'
    elif not orden_sql and lista_guardados == 'favoritos':
        orden_sql = 'valoracion_promedio DESC, total_valoraciones DESC, productos.id DESC'
    orden_sql = orden_sql or 'destacado DESC, created_at DESC, id DESC'
    if busqueda:
        query += ''' ORDER BY CASE WHEN nombre = %s THEN 0 WHEN nombre LIKE %s THEN 1
                     WHEN marca LIKE %s THEN 2 ELSE 3 END, '''
        params.extend((busqueda, f'{busqueda}%', f'{busqueda}%'))
        query += orden_sql
    else:
        query += f' ORDER BY {orden_sql}'
    params.extend(parametros_orden)

    conn = get_db_connection()
    if not conn:
        flash("Error de conexion a la base de datos", "error")
        return render_template('productos.html', productos=[], favoritos_ids=set(),
                               deseos_ids=set(), busqueda=busqueda,
                               lista_guardados=lista_guardados)

    try:
        cursor = conn.cursor(dictionary=True)
        asegurar_columna_propietario_producto(conn)
        asegurar_tabla_valoraciones_producto(conn)
        asegurar_catalogo_empresa(conn)
        expirar_ofertas(conn)
        if orden == 'recientes' and session.get('user_id'):
            asegurar_tabla_productos_vistos(conn)
        if session.get('user_id'):
            asegurar_tabla_favoritos(conn)
            asegurar_tabla_lista_deseos(conn)
        cursor.execute(query, tuple(params))
        lista_productos = cursor.fetchall()
        favoritos_ids = set()
        deseos_ids = set()
        if session.get('user_id'):
            cursor.execute('SELECT producto_id FROM favoritos WHERE usuario_id = %s', (session['user_id'],))
            favoritos_ids = {fila['producto_id'] for fila in cursor.fetchall()}
            asegurar_tabla_lista_deseos(conn)
            cursor.execute('SELECT producto_id FROM lista_deseos WHERE usuario_id = %s', (session['user_id'],))
            deseos_ids = {fila['producto_id'] for fila in cursor.fetchall()}
    except sqlite3.Error as err:
        print(f"Error al filtrar productos: {err}")
        lista_productos = []
        favoritos_ids = set()
        deseos_ids = set()
    finally:
        cursor.close()
        conn.close()

    return render_template('productos.html', productos=lista_productos,
                           favoritos_ids=favoritos_ids, deseos_ids=deseos_ids,
                           busqueda=busqueda, lista_guardados=lista_guardados)


@app.route('/productos/sugerencias')
def sugerencias_productos():
    termino = request.args.get('q', '').strip()[:80]
    if not termino:
        return jsonify(sugerencias=[])
    conn = get_db_connection()
    if not conn:
        return jsonify(sugerencias=[])
    cursor = None
    sugerencias = []
    try:
        asegurar_columna_propietario_producto(conn)
        cursor = conn.cursor(dictionary=True)
        patron = f'%{termino}%'
        prefijo = f'{termino}%'
        cursor.execute('''
            SELECT nombre AS valor
            FROM productos
            WHERE activo = 1 AND estado_revision = 'aprobado'
              AND (nombre LIKE %s OR marca LIKE %s OR subcategoria LIKE %s
                   OR descripcion_corta LIKE %s)
            ORDER BY CASE WHEN nombre LIKE %s THEN 0 ELSE 1 END, nombre ASC
            LIMIT 5
        ''', (patron, patron, patron, patron, prefijo))
        sugerencias.extend({'tipo': 'Producto', 'valor': fila['valor']} for fila in cursor.fetchall())
        cursor.execute('''
            SELECT DISTINCT marca AS valor
            FROM productos
            WHERE activo = 1 AND estado_revision = 'aprobado'
              AND marca IS NOT NULL AND marca <> '' AND marca LIKE %s
            ORDER BY CASE WHEN marca LIKE %s THEN 0 ELSE 1 END, marca ASC
            LIMIT 3
        ''', (patron, prefijo))
        sugerencias.extend({'tipo': 'Marca', 'valor': fila['valor']} for fila in cursor.fetchall())
        cursor.execute('''
            SELECT DISTINCT subcategoria AS valor
            FROM productos
            WHERE activo = 1 AND estado_revision = 'aprobado'
              AND subcategoria IS NOT NULL AND subcategoria <> '' AND subcategoria LIKE %s
            ORDER BY CASE WHEN subcategoria LIKE %s THEN 0 ELSE 1 END, subcategoria ASC
            LIMIT 3
        ''', (patron, prefijo))
        sugerencias.extend({'tipo': 'Categoría', 'valor': fila['valor']} for fila in cursor.fetchall())
        if not sugerencias and len(normalizar_termino_busqueda(termino)) >= 3:
            cursor.execute('''
                SELECT nombre, marca, subcategoria
                FROM productos
                WHERE activo = 1 AND estado_revision = 'aprobado'
                ORDER BY created_at DESC, id DESC LIMIT 500
            ''')
            consulta_normalizada = normalizar_termino_busqueda(termino)
            candidatos = {}
            for fila in cursor.fetchall():
                for tipo, valor in (('Producto', fila['nombre']), ('Marca', fila.get('marca')),
                                    ('Categoría', fila.get('subcategoria'))):
                    if not valor:
                        continue
                    partes = str(valor).split() if tipo != 'Producto' else [str(valor)]
                    puntuacion = max((SequenceMatcher(None, consulta_normalizada,
                                                       normalizar_termino_busqueda(parte)).ratio()
                                      for parte in partes), default=0)
                    if puntuacion >= 0.68:
                        clave = (tipo, str(valor))
                        candidatos[clave] = max(candidatos.get(clave, 0), puntuacion)
            sugerencias = [
                {'tipo': 'Corrección sugerida', 'valor': valor}
                for (tipo, valor), _ in sorted(candidatos.items(), key=lambda item: -item[1])[:5]
            ]
    except sqlite3.Error as err:
        print(f'Error al sugerir productos: {err}')
        sugerencias = []
    finally:
        if cursor:
            cursor.close()
        conn.close()
    return jsonify(sugerencias=sugerencias)


@app.route('/api/buscar-sitio')
def sugerencias_sitio():
    termino = request.args.get('q', '').strip()[:80]
    if not termino:
        return jsonify(sugerencias=[])
    secciones = [
        ('Productos', ('producto', 'tienda', 'comprar', 'raqueta', 'pelota'), url_for('productos')),
        ('Reservas', ('reserva', 'cancha', 'horario'), url_for('reservas')),
        ('Jugadores', ('jugador', 'rival', 'matchmaking'), url_for('matchmaking')),
        ('Mapas', ('mapa', 'canchas', 'ubicacion'), url_for('mapas')),
        ('Entrenamientos', ('entreno', 'entrenamiento', 'rutina', 'ejercicio'), url_for('entreno')),
        ('Premium', ('premium', 'suscripcion', 'beneficios'), url_for('premium')),
        ('Mis compras', ('compra', 'factura', 'pedido'), url_for('mis_compras')),
        ('Favoritos', ('favorito', 'guardado'), url_for('productos', lista='favoritos')),
        ('Lista de deseos', ('deseo', 'wishlist'), url_for('productos', lista='deseos')),
        ('Contacto', ('contacto', 'ayuda', 'soporte'), url_for('contacto')),
    ]
    consulta = normalizar_termino_busqueda(termino)
    coincidencias = []
    correcciones = []
    for titulo, palabras, enlace in secciones:
        textos = (titulo, *palabras)
        if any(consulta in normalizar_termino_busqueda(texto) for texto in textos):
            coincidencias.append({'tipo': 'Sección', 'valor': titulo, 'url': enlace})
            continue
        if len(consulta) >= 3:
            puntuacion = max((SequenceMatcher(None, consulta, normalizar_termino_busqueda(texto)).ratio()
                              for texto in textos), default=0)
            if puntuacion >= 0.68:
                correcciones.append((puntuacion, {'tipo': '¿Quisiste decir?', 'valor': titulo, 'url': enlace}))
    resultados = coincidencias[:7] or [resultado for _, resultado in sorted(correcciones, key=lambda item: -item[0])[:5]]
    return jsonify(sugerencias=resultados)


@app.route('/favoritos')
@login_required
def mis_favoritos():
    conn = get_db_connection()
    if not conn:
        flash('No fue posible cargar tu lista de deseos.', 'error')
        return redirect(url_for('productos', lista='favoritos'))
    cursor = None
    productos_favoritos = []
    try:
        asegurar_tabla_favoritos(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute('''
            SELECT p.*, f.created_at AS agregado_at
            FROM favoritos f
            JOIN productos p ON p.id = f.producto_id
            WHERE f.usuario_id = %s AND p.activo = 1 AND p.estado_revision = 'aprobado'
            ORDER BY f.created_at DESC, f.id DESC
        ''', (session['user_id'],))
        productos_favoritos = cursor.fetchall()
    except sqlite3.Error as err:
        print(f'Error al cargar favoritos: {err}')
        flash('No fue posible cargar tu lista de deseos.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()
    return redirect(url_for('productos', lista='favoritos'))


@app.route('/lista-deseos')
@login_required
def mis_deseos():
    conn = get_db_connection()
    if not conn:
        flash('No fue posible cargar tu lista de deseos.', 'error')
        return redirect(url_for('productos', lista='deseos'))
    cursor = None
    productos_deseados = []
    try:
        asegurar_tabla_lista_deseos(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute('''
            SELECT p.*, d.created_at AS agregado_at
            FROM lista_deseos d
            JOIN productos p ON p.id = d.producto_id
            WHERE d.usuario_id = %s AND p.activo = 1 AND p.estado_revision = 'aprobado'
            ORDER BY d.created_at DESC, d.id DESC
        ''', (session['user_id'],))
        productos_deseados = cursor.fetchall()
    except sqlite3.Error as err:
        print(f'Error al cargar lista de deseos: {err}')
        flash('No fue posible cargar tu lista de deseos.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()
    return redirect(url_for('productos', lista='deseos'))


@app.post('/favoritos/<int:producto_id>/alternar')
@login_required
def alternar_favorito(producto_id):
    ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    destino = request.form.get('next', '')
    if not destino.startswith('/') or destino.startswith('//'):
        destino = url_for('productos')
    conn = get_db_connection()
    if not conn:
        if ajax:
            return jsonify(ok=False, error='No fue posible actualizar tus favoritos.'), 503
        flash('No fue posible actualizar tus favoritos.', 'error')
        return redirect(destino)
    cursor = None
    favorito_activo = False
    try:
        asegurar_tabla_favoritos(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM productos WHERE id = %s AND activo = 1 AND estado_revision = 'aprobado'", (producto_id,))
        if not cursor.fetchone():
            if ajax:
                return jsonify(ok=False, error='Este producto ya no está disponible.'), 404
            flash('Este producto ya no está disponible.', 'warning')
            return redirect(destino)
        cursor.execute('''
            SELECT id FROM favoritos WHERE usuario_id = %s AND producto_id = %s
        ''', (session['user_id'], producto_id))
        favorito = cursor.fetchone()
        if favorito:
            cursor.execute('DELETE FROM favoritos WHERE id = %s AND usuario_id = %s',
                           (favorito['id'], session['user_id']))
            flash('Producto eliminado de favoritos.', 'info')
        else:
            cursor.execute('INSERT IGNORE INTO favoritos (usuario_id, producto_id) VALUES (%s, %s)',
                           (session['user_id'], producto_id))
            flash('Producto agregado a favoritos.', 'success')
        conn.commit()
        favorito_activo = not bool(favorito)
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error al actualizar favoritos: {err}')
        if ajax:
            return jsonify(ok=False, error='No fue posible actualizar tus favoritos.'), 500
        flash('No fue posible actualizar tus favoritos.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()
    if ajax:
        return jsonify(ok=True, guardado=favorito_activo, tipo='favoritos')
    return redirect(destino)


@app.post('/lista-deseos/<int:producto_id>/alternar')
@login_required
def alternar_deseo(producto_id):
    ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    destino = request.form.get('next', '')
    if not destino.startswith('/') or destino.startswith('//'):
        destino = url_for('mis_deseos')
    conn = get_db_connection()
    if not conn:
        if ajax:
            return jsonify(ok=False, error='No fue posible actualizar tu lista de deseos.'), 503
        flash('No fue posible actualizar tu lista de deseos.', 'error')
        return redirect(destino)
    cursor = None
    deseo_activo = False
    try:
        asegurar_tabla_lista_deseos(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM productos WHERE id = %s AND activo = 1 AND estado_revision = 'aprobado'", (producto_id,))
        if not cursor.fetchone():
            if ajax:
                return jsonify(ok=False, error='Este producto ya no está disponible.'), 404
            flash('Este producto ya no está disponible.', 'warning')
            return redirect(destino)
        cursor.execute('SELECT id FROM lista_deseos WHERE usuario_id = %s AND producto_id = %s',
                       (session['user_id'], producto_id))
        deseo = cursor.fetchone()
        if deseo:
            cursor.execute('DELETE FROM lista_deseos WHERE id = %s AND usuario_id = %s',
                           (deseo['id'], session['user_id']))
            flash('Producto quitado de la lista de deseos.', 'info')
        else:
            cursor.execute('INSERT IGNORE INTO lista_deseos (usuario_id, producto_id) VALUES (%s, %s)',
                           (session['user_id'], producto_id))
            flash('Producto guardado en la lista de deseos.', 'success')
        conn.commit()
        deseo_activo = not bool(deseo)
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error al actualizar lista de deseos: {err}')
        if ajax:
            return jsonify(ok=False, error='No fue posible actualizar tu lista de deseos.'), 500
        flash('No fue posible actualizar tu lista de deseos.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()
    if ajax:
        return jsonify(ok=True, guardado=deseo_activo, tipo='deseos')
    return redirect(destino)


@app.route('/mis-direcciones', methods=['GET', 'POST'])
@login_required
def mis_direcciones():
    conn = get_db_connection()
    if not conn:
        flash('No fue posible cargar tus direcciones.', 'error')
        return redirect(url_for('ver_carrito'))
    cursor = None
    direcciones = []
    try:
        asegurar_tabla_direcciones(conn)
        cursor = conn.cursor(dictionary=True)
        if request.method == 'POST':
            datos = limpiar_datos_direccion(request.form)
            if not all(datos[campo] for campo in
                       ('nombre_recibe', 'telefono', 'departamento', 'ciudad', 'barrio', 'direccion')):
                flash('Completa los datos obligatorios de la dirección.', 'error')
            else:
                cursor.execute('SELECT COUNT(*) AS total FROM direcciones_usuario WHERE usuario_id = %s',
                               (session['user_id'],))
                primera = cursor.fetchone()['total'] == 0
                es_principal = primera or request.form.get('es_principal') == 'on'
                if es_principal:
                    cursor.execute('UPDATE direcciones_usuario SET es_principal = 0 WHERE usuario_id = %s',
                                   (session['user_id'],))
                cursor.execute('''
                    INSERT INTO direcciones_usuario
                        (usuario_id, etiqueta, nombre_recibe, telefono, departamento, ciudad, barrio,
                         direccion, complemento, codigo_postal, instrucciones, es_principal)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (session['user_id'], (request.form.get('etiqueta') or 'Casa').strip()[:60],
                      datos['nombre_recibe'], datos['telefono'], datos['departamento'], datos['ciudad'],
                      datos['barrio'], datos['direccion'], datos['complemento'] or None,
                      datos['codigo_postal'] or None, datos['instrucciones'] or None, int(es_principal)))
                conn.commit()
                flash('Dirección guardada.', 'success')
                return redirect(url_for('mis_direcciones'))

        cursor.execute('''
            SELECT * FROM direcciones_usuario
            WHERE usuario_id = %s
            ORDER BY es_principal DESC, created_at DESC, id DESC
        ''', (session['user_id'],))
        direcciones = cursor.fetchall()
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error en direcciones guardadas: {err}')
        flash('No fue posible guardar o cargar la dirección.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()
    return render_template('mis_direcciones.html', direcciones=direcciones)


@app.post('/mis-direcciones/<int:direccion_id>/principal')
@login_required
def direccion_principal(direccion_id):
    conn = get_db_connection()
    if not conn:
        flash('No fue posible actualizar la dirección principal.', 'error')
        return redirect(url_for('mis_direcciones'))
    cursor = None
    try:
        asegurar_tabla_direcciones(conn)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM direcciones_usuario WHERE id = %s AND usuario_id = %s',
                       (direccion_id, session['user_id']))
        if not cursor.fetchone():
            flash('No encontramos esa dirección en tu cuenta.', 'error')
        else:
            cursor.execute('UPDATE direcciones_usuario SET es_principal = 0 WHERE usuario_id = %s',
                           (session['user_id'],))
            cursor.execute('UPDATE direcciones_usuario SET es_principal = 1 WHERE id = %s AND usuario_id = %s',
                           (direccion_id, session['user_id']))
            conn.commit()
            flash('Dirección principal actualizada.', 'success')
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error al elegir dirección principal: {err}')
        flash('No fue posible actualizar la dirección principal.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()
    return redirect(url_for('mis_direcciones'))


@app.post('/mis-direcciones/<int:direccion_id>/eliminar')
@login_required
def eliminar_direccion(direccion_id):
    conn = get_db_connection()
    if not conn:
        flash('No fue posible eliminar la dirección.', 'error')
        return redirect(url_for('mis_direcciones'))
    cursor = None
    try:
        asegurar_tabla_direcciones(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute('''
            SELECT es_principal FROM direcciones_usuario
            WHERE id = %s AND usuario_id = %s
        ''', (direccion_id, session['user_id']))
        direccion = cursor.fetchone()
        if not direccion:
            flash('No encontramos esa dirección en tu cuenta.', 'error')
        else:
            cursor.execute('DELETE FROM direcciones_usuario WHERE id = %s AND usuario_id = %s',
                           (direccion_id, session['user_id']))
            if direccion['es_principal']:
                cursor.execute('''
                    UPDATE direcciones_usuario SET es_principal = 1
                    WHERE usuario_id = %s ORDER BY created_at DESC, id DESC LIMIT 1
                ''', (session['user_id'],))
            conn.commit()
            flash('Dirección eliminada.', 'success')
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error eliminando dirección: {err}')
        flash('No fue posible eliminar la dirección.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()
    return redirect(url_for('mis_direcciones'))


@app.route('/tienda/proceso', methods=['GET', 'POST'])
@tienda_premium_required
def proceso_tienda():
    conn = get_db_connection()
    if not conn:
        flash('No fue posible conectar con la base de datos.', 'error')
        return redirect(url_for('index'))
    cursor = None
    try:
        asegurar_tablas_proceso_tienda(conn)
        proceso = obtener_proceso_tienda(conn, session['user_id'])
        cursor = conn.cursor(dictionary=True)
        if request.method == 'POST':
            accion = request.form.get('accion', '')
            if accion == 'mensaje':
                texto = request.form.get('texto', '').strip()[:2000]
                if not texto:
                    flash('Escribe un mensaje antes de enviarlo.', 'warning')
                else:
                    cursor.execute('''
                        INSERT INTO tienda_proceso_mensajes (proceso_id, emisor_id, texto)
                        VALUES (%s, %s, %s)
                    ''', (proceso['id'], session['user_id'], texto))
                    cursor.execute('UPDATE tienda_procesos SET admin_pendiente = 1 WHERE id = %s', (proceso['id'],))
                    conn.commit()
                    flash('Mensaje enviado a TENNISSEL.', 'success')
            elif accion == 'ubicacion':
                ciudad = request.form.get('ciudad', '').strip()[:120]
                direccion = request.form.get('direccion', '').strip()[:255]
                try:
                    lat_raw = request.form.get('lat', '').strip()
                    lng_raw = request.form.get('lng', '').strip()
                    lat = float(lat_raw) if lat_raw else None
                    lng = float(lng_raw) if lng_raw else None
                    if ((lat is None) != (lng is None)
                            or (lat is not None and not -90 <= lat <= 90)
                            or (lng is not None and not -180 <= lng <= 180)):
                        raise ValueError
                except (TypeError, ValueError):
                    flash('Las coordenadas de ubicación no son válidas.', 'error')
                    return redirect(url_for('proceso_tienda'))
                if not ciudad or not direccion:
                    flash('Indica la ciudad y la dirección o punto de entrega.', 'error')
                else:
                    ubicacion = {'ciudad': ciudad, 'direccion': direccion, 'lat': lat, 'lng': lng}
                    cursor.execute('''
                        UPDATE tienda_procesos
                        SET ubicacion_ciudad = %s, ubicacion_direccion = %s, lat = %s, lng = %s
                        WHERE id = %s
                    ''', (ciudad, direccion, lat, lng, proceso['id']))
                    cursor.execute('''
                        INSERT INTO tienda_proceso_mensajes
                            (proceso_id, emisor_id, tipo, texto, datos_extra)
                        VALUES (%s, %s, 'ubicacion', %s, %s)
                    ''', (
                        proceso['id'], session['user_id'],
                        f'Ubicación compartida: {ciudad} · {direccion}',
                        json.dumps(ubicacion, ensure_ascii=False)
                    ))
                    cursor.execute('UPDATE tienda_procesos SET admin_pendiente = 1 WHERE id = %s', (proceso['id'],))
                    conn.commit()
                    flash('Ubicación compartida con TENNISSEL.', 'success')
            elif accion == 'aceptar_acuerdo':
                if request.form.get('confirmar') != 'on':
                    flash('Confirma que revisaste y aceptas las condiciones.', 'warning')
                elif not proceso.get('acuerdo'):
                    flash('TENNISSEL aún no ha enviado las condiciones del acuerdo.', 'warning')
                elif not proceso.get('ubicacion_ciudad') or not proceso.get('ubicacion_direccion'):
                    flash('Comparte primero la ubicación de tu tienda para continuar.', 'warning')
                elif proceso.get('tienda_acepto'):
                    flash('El acuerdo ya está aceptado y tu tienda puede gestionar productos.', 'info')
                else:
                    cursor.execute('''
                        UPDATE tienda_procesos
                        SET tienda_acepto = 1, estado = 'activo'
                        WHERE id = %s AND acuerdo IS NOT NULL
                    ''', (proceso['id'],))
                    cursor.execute('''
                        INSERT INTO tienda_proceso_mensajes (proceso_id, emisor_id, tipo, texto)
                        VALUES (%s, %s, 'sistema', %s)
                    ''', (
                        proceso['id'], session['user_id'],
                        'La tienda aceptó las condiciones propuestas. Ya puede enviar productos para revisión.'
                    ))
                    cursor.execute('UPDATE tienda_procesos SET admin_pendiente = 1 WHERE id = %s', (proceso['id'],))
                    conn.commit()
                    flash('Acuerdo confirmado. Ya puedes cargar tus productos.', 'success')
            else:
                flash('La acción solicitada no es válida.', 'error')
            return redirect(url_for('proceso_tienda'))

        proceso = obtener_proceso_tienda(conn, session['user_id'])
        cursor.execute('UPDATE tienda_procesos SET tienda_pendiente = 0 WHERE id = %s', (proceso['id'],))
        conn.commit()
        cursor.execute('''
            SELECT m.*, u.username AS emisor_nombre
            FROM tienda_proceso_mensajes m
            LEFT JOIN usuarios u ON u.id = m.emisor_id
            WHERE m.proceso_id = %s
            ORDER BY m.created_at ASC, m.id ASC
        ''', (proceso['id'],))
        mensajes = cursor.fetchall()
        return render_template('tienda_proceso.html', proceso=proceso, mensajes=mensajes)
    except sqlite3.Error as err:
        conn.rollback()
        app.logger.exception('No se pudo cargar el proceso de incorporación de tienda: %s', err)
        flash('No fue posible cargar el proceso de tu tienda.', 'error')
        return redirect(url_for('index'))
    finally:
        if cursor:
            cursor.close()
        conn.close()


@app.route('/admin/tiendas', methods=['GET', 'POST'])
@admin_required
def admin_tiendas():
    conn = get_db_connection()
    if not conn:
        flash('No fue posible conectar con la base de datos.', 'error')
        return redirect(url_for('index'))
    cursor = None
    try:
        asegurar_tablas_proceso_tienda(conn)
        cursor = conn.cursor(dictionary=True)
        if request.method == 'POST':
            search = request.form.get('q', '').strip()[:120]
            tienda_id = request.form.get('tienda_id', type=int)
            accion = request.form.get('accion', '')
            if not tienda_id:
                flash('Selecciona una tienda válida.', 'error')
                return redirect(url_for('admin_tiendas', q=search))
            cursor.execute("SELECT id FROM usuarios WHERE id = %s AND rol = 'tienda'", (tienda_id,))
            if not cursor.fetchone():
                flash('La cuenta seleccionada no es una tienda válida.', 'error')
                return redirect(url_for('admin_tiendas', q=search))
            proceso = obtener_proceso_tienda(conn, tienda_id)
            if accion == 'mensaje':
                texto = request.form.get('texto', '').strip()[:2000]
                if not texto:
                    flash('Escribe un mensaje antes de enviarlo.', 'warning')
                else:
                    cursor.execute('''
                        INSERT INTO tienda_proceso_mensajes (proceso_id, emisor_id, texto)
                        VALUES (%s, %s, %s)
                    ''', (proceso['id'], session['user_id'], texto))
                    cursor.execute('UPDATE tienda_procesos SET tienda_pendiente = 1 WHERE id = %s', (proceso['id'],))
                    conn.commit()
                    flash('Mensaje enviado a la tienda.', 'success')
            elif accion == 'acuerdo':
                acuerdo = request.form.get('acuerdo', '').strip()[:12000]
                if not acuerdo:
                    flash('Especifica claramente las condiciones comerciales y operativas.', 'error')
                elif acuerdo == (proceso.get('acuerdo') or ''):
                    flash('Las condiciones no han cambiado.', 'info')
                else:
                    cursor.execute('''
                        UPDATE tienda_procesos
                        SET acuerdo = %s, tienda_acepto = 0, estado = 'acuerdo_propuesto'
                        WHERE id = %s
                    ''', (acuerdo, proceso['id']))
                    cursor.execute('''
                        INSERT INTO tienda_proceso_mensajes
                            (proceso_id, emisor_id, tipo, texto)
                        VALUES (%s, %s, 'sistema', %s)
                    ''', (
                        proceso['id'], session['user_id'],
                        'TENNISSEL envió o actualizó la propuesta de condiciones. La tienda debe revisarla y aceptarla.'
                    ))
                    cursor.execute('UPDATE tienda_procesos SET tienda_pendiente = 1 WHERE id = %s', (proceso['id'],))
                    conn.commit()
                    flash('Propuesta de acuerdo enviada. La tienda debe aceptarla para habilitar la carga de productos.', 'success')
            else:
                flash('La acción solicitada no es válida.', 'error')
            return redirect(url_for('admin_tiendas', tienda_id=tienda_id, q=search))

        search = request.args.get('q', '').strip()[:120]
        cursor.execute("SELECT id FROM usuarios WHERE rol = 'tienda' ORDER BY username")
        tiendas_ids = [row['id'] for row in cursor.fetchall()]
        for tienda_id in tiendas_ids:
            obtener_proceso_tienda(conn, tienda_id)
        query = '''
            SELECT u.id, u.username, u.email, p.id AS proceso_id, p.estado,
                   p.acuerdo, p.tienda_acepto, p.ubicacion_ciudad, p.ubicacion_direccion,
                   p.lat, p.lng, p.admin_pendiente
            FROM usuarios u
            JOIN tienda_procesos p ON p.tienda_id = u.id
            WHERE u.rol = 'tienda'
        '''
        params = []
        if search:
            query += '''
                AND (
                    CAST(u.id AS CHAR) LIKE %s OR u.username LIKE %s OR u.email LIKE %s
                    OR p.estado LIKE %s OR p.ubicacion_ciudad LIKE %s
                    OR p.ubicacion_direccion LIKE %s OR p.acuerdo LIKE %s
                )
            '''
            pattern = f'%{search}%'
            params = [pattern] * 7
        query += ' ORDER BY CASE WHEN p.estado = \'activo\' THEN 1 ELSE 0 END, u.username'
        cursor.execute(query, params)
        tiendas = cursor.fetchall()
        tienda_id = request.args.get('tienda_id', type=int)
        seleccionada = next((tienda for tienda in tiendas if tienda['id'] == tienda_id), None)
        if seleccionada:
            cursor.execute('UPDATE tienda_procesos SET admin_pendiente = 0 WHERE id = %s', (seleccionada['proceso_id'],))
            conn.commit()
            seleccionada['admin_pendiente'] = 0
            cursor.execute('''
                SELECT m.*, u.username AS emisor_nombre
                FROM tienda_proceso_mensajes m
                LEFT JOIN usuarios u ON u.id = m.emisor_id
                WHERE m.proceso_id = %s
                ORDER BY m.created_at ASC, m.id ASC
            ''', (seleccionada['proceso_id'],))
            seleccionada['mensajes'] = cursor.fetchall()
        return render_template(
            'admin/tiendas.html',
            tiendas=tiendas,
            seleccionada=seleccionada,
            search=search
        )
    except sqlite3.Error as err:
        conn.rollback()
        app.logger.exception('No se pudo cargar la administración de tiendas: %s', err)
        flash('No fue posible cargar el proceso de tiendas.', 'error')
        return redirect(url_for('index'))
    finally:
        if cursor:
            cursor.close()
        conn.close()


@app.route('/tienda/productos/carga-masiva', methods=['POST'])
@tienda_premium_required
def cargar_productos_masivo():
    if 'archivo_csv' not in request.files or not request.files['archivo_csv'].filename:
        flash('Selecciona un archivo CSV para cargar varios productos.', 'error')
        return redirect(url_for('tienda_productos'))
    archivo_csv = request.files['archivo_csv']
    if not archivo_csv.filename.lower().endswith('.csv'):
        flash('El archivo de productos debe estar en formato CSV.', 'error')
        return redirect(url_for('tienda_productos'))
    contenido = archivo_csv.stream.read(2_000_001)
    if len(contenido) > 2_000_000:
        flash('El CSV supera el tamaño máximo de 2 MB.', 'error')
        return redirect(url_for('tienda_productos'))
    try:
        texto_csv = contenido.decode('utf-8-sig')
        muestra = texto_csv[:4096]
        try:
            dialecto = csv.Sniffer().sniff(muestra, delimiters=',;\t')
        except csv.Error:
            dialecto = csv.excel
        lector = csv.DictReader(io.StringIO(texto_csv), dialect=dialecto)
        encabezados = {str(header or '').strip().lower() for header in (lector.fieldnames or [])}
        requeridos = {'nombre', 'descripcion', 'categoria', 'precio', 'stock'}
        if not requeridos.issubset(encabezados):
            raise ValueError('El CSV debe incluir las columnas: nombre, descripcion, categoria, precio y stock.')
        filas = list(lector)
    except (UnicodeDecodeError, csv.Error, ValueError) as err:
        flash(str(err) or 'No se pudo leer el CSV. Guárdalo como CSV UTF-8.', 'error')
        return redirect(url_for('tienda_productos'))
    if not filas or len(filas) > 50:
        flash('El archivo debe incluir entre 1 y 50 productos por carga.', 'error')
        return redirect(url_for('tienda_productos'))

    imagenes = {}
    for imagen in request.files.getlist('imagenes'):
        if not imagen.filename:
            continue
        nombre_original = secure_filename(imagen.filename)
        nombre_clave = nombre_original.casefold()
        if not nombre_original or nombre_clave in imagenes or not imagen_producto_valida(imagen):
            flash('Hay imágenes inválidas o nombres de imagen repetidos. Usa PNG, JPG, GIF o WEBP.', 'error')
            return redirect(url_for('tienda_productos'))
        imagenes[nombre_clave] = imagen

    conn = get_db_connection()
    if not conn:
        flash('No fue posible conectar con la base de datos.', 'error')
        return redirect(url_for('tienda_productos'))
    cursor = None
    archivos_guardados = []
    carga_confirmada = False
    try:
        if not tienda_tiene_acuerdo_activo(conn, session['user_id']):
            flash('Completa el proceso de incorporación y acepta el acuerdo antes de cargar productos.', 'warning')
            return redirect(url_for('proceso_tienda'))
        asegurar_columna_propietario_producto(conn)
        cursor = conn.cursor(dictionary=True)
        productos = []
        errores = []
        for numero, fila in enumerate(filas, start=2):
            fila = {
                str(clave or '').strip().lower(): str(valor or '').strip()
                for clave, valor in fila.items()
            }
            nombre = fila.get('nombre', '')[:150]
            descripcion = fila.get('descripcion', '')[:2000]
            categoria_raw = fila.get('categoria', '')
            try:
                precio = Decimal(fila.get('precio', ''))
                stock = int(fila.get('stock', ''))
                if not nombre or not descripcion or not categoria_raw or not precio.is_finite() or precio <= 0 or stock < 0:
                    raise ValueError
            except (InvalidOperation, TypeError, ValueError):
                errores.append(f'Fila {numero}: revisa nombre, descripción, categoría, precio y stock.')
                continue
            if categoria_raw.isdigit():
                cursor.execute('SELECT id FROM categorias WHERE id = %s', (int(categoria_raw),))
            else:
                cursor.execute('SELECT id FROM categorias WHERE LOWER(nombre) = LOWER(%s)', (categoria_raw,))
            categoria = cursor.fetchone()
            if not categoria:
                errores.append(f'Fila {numero}: no se encontró la categoría "{categoria_raw}".')
                continue
            precio_anterior_raw = fila.get('precio_anterior', '')
            try:
                precio_anterior = Decimal(precio_anterior_raw) if precio_anterior_raw else None
                peso = Decimal(fila['peso']) if fila.get('peso') else None
                if ((precio_anterior is not None and
                     (not precio_anterior.is_finite() or precio_anterior <= precio))
                        or (peso is not None and (not peso.is_finite() or peso < 0))):
                    raise ValueError
            except (InvalidOperation, TypeError, ValueError):
                errores.append(f'Fila {numero}: revisa precio_anterior o peso.')
                continue
            nombre_imagen = secure_filename(fila.get('imagen', '')) if fila.get('imagen') else ''
            nombre_imagen = nombre_imagen.casefold()
            if nombre_imagen and nombre_imagen not in imagenes:
                errores.append(f'Fila {numero}: adjunta la imagen "{nombre_imagen}" o deja la columna imagen vacía.')
                continue
            productos.append({
                'nombre': nombre,
                'descripcion': descripcion,
                'categoria_id': categoria['id'],
                'precio': precio,
                'precio_anterior': precio_anterior,
                'stock': stock,
                'peso': peso,
                'subcategoria': fila.get('subcategoria', '')[:100] or None,
                'marca': fila.get('marca', '')[:50] or None,
                'color': fila.get('color', '')[:50] or None,
                'talla': fila.get('talla', '')[:50] or None,
                'sku': fila.get('sku', '')[:50] or None,
                'imagen': nombre_imagen,
            })
        if errores:
            flash('No se cargó ningún producto. ' + ' '.join(errores[:8]), 'error')
            return redirect(url_for('tienda_productos'))
        if not productos:
            flash('El archivo no contiene productos válidos.', 'error')
            return redirect(url_for('tienda_productos'))

        prefijo = datetime.now().strftime('%Y%m%d%H%M%S%f')
        rutas_imagen = {}
        imagenes_referenciadas = {
            producto['imagen'] for producto in productos if producto['imagen']
        }
        for indice_imagen, (nombre_clave, imagen) in enumerate(imagenes.items(), start=1):
            if nombre_clave not in imagenes_referenciadas:
                continue
            extension = os.path.splitext(secure_filename(imagen.filename))[1].lower()
            nombre_archivo = f"tienda_{session['user_id']}_{prefijo}_{indice_imagen}{extension}"
            imagen.save(os.path.join(PRODUCT_UPLOAD_FOLDER, nombre_archivo))
            archivos_guardados.append(nombre_archivo)
            rutas_imagen[nombre_clave] = f'uploads/productos/{nombre_archivo}'
        for indice, producto in enumerate(productos):
            slug_base = re.sub(
                r'[^a-z0-9]+', '-',
                texto_moderacion(producto['nombre'])
            ).strip('-') or 'producto'
            slug = f"{slug_base[:90]}-{session['user_id']}-{prefijo[-12:]}-{indice + 1}"
            texto_revision = ' '.join((
                producto['nombre'], producto['descripcion'],
                producto['subcategoria'] or '', producto['marca'] or '',
                producto['color'] or '', producto['talla'] or '', producto['sku'] or ''
            ))
            nota_revision = motivo_revision_producto(texto_revision)
            imagen_path = rutas_imagen.get(producto['imagen'], 'IMG/tenis.jpg')
            cursor.execute('''
                INSERT INTO productos
                    (owner_user_id, nombre, slug, descripcion_corta, descripcion_larga,
                     categoria_id, subcategoria, marca, color, talla, precio,
                     precio_anterior, stock, sku, imagen_principal, peso,
                     activo, estado_revision, en_oferta, moderation_note)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        0, 'pendiente', %s, %s)
            ''', (
                session['user_id'], producto['nombre'], slug,
                producto['descripcion'][:255], producto['descripcion'],
                producto['categoria_id'], producto['subcategoria'], producto['marca'],
                producto['color'], producto['talla'], producto['precio'],
                producto['precio_anterior'], producto['stock'], producto['sku'],
                imagen_path, producto['peso'], int(producto['precio_anterior'] is not None),
                nota_revision
            ))
        conn.commit()
        carga_confirmada = True
        flash(f'Se enviaron {len(productos)} productos para revisión de TENNISSEL.', 'success')
    except sqlite3.Error as err:
        conn.rollback()
        app.logger.exception('Error en la carga masiva de productos de tienda: %s', err)
        flash('No se cargó ningún producto. Revisa que los SKU no estén repetidos y que los datos sean válidos.', 'error')
    except OSError as err:
        conn.rollback()
        app.logger.exception('No se pudieron guardar las imágenes de la carga masiva: %s', err)
        flash('No se cargaron los productos porque no se pudieron guardar las imágenes adjuntas.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()
        if not carga_confirmada:
            for nombre_archivo in archivos_guardados:
                ruta = os.path.join(PRODUCT_UPLOAD_FOLDER, nombre_archivo)
                if os.path.isfile(ruta):
                    os.remove(ruta)
    return redirect(url_for('tienda_productos'))


@app.route('/tienda/productos', methods=['GET', 'POST'])
@tienda_premium_required
def tienda_productos():
    conn = get_db_connection()
    if not conn:
        flash('No fue posible conectar con la base de datos.', 'error')
        return render_template('tienda_productos.html', productos=[], categorias=[])

    cursor = conn.cursor(dictionary=True)
    asegurar_columna_propietario_producto(conn)
    if not tienda_tiene_acuerdo_activo(conn, session['user_id']):
        cursor.close()
        conn.close()
        flash('Completa el proceso de incorporación de tu tienda antes de proponer productos.', 'warning')
        return redirect(url_for('proceso_tienda'))
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        precio_raw = request.form.get('precio', '').strip()
        categoria_raw = request.form.get('categoria_id', '').strip()
        subcategoria = request.form.get('subcategoria', '').strip()[:100]
        marca = request.form.get('marca', '').strip()[:50]
        color = request.form.get('color', '').strip()[:50]
        talla = request.form.get('talla', '').strip()[:50]
        sku = request.form.get('sku', '').strip()[:50] or None
        precio_anterior_raw = request.form.get('precio_anterior', '').strip()
        peso_raw = request.form.get('peso', '').strip()
        caracteristicas = [linea.strip()[:180] for linea in request.form.get('caracteristicas', '').splitlines() if linea.strip()][:20]
        tipos_variacion = request.form.getlist('variacion_tipo[]')
        valores_variacion = request.form.getlist('variacion_valor[]')
        stocks_variacion = request.form.getlist('variacion_stock[]')
        imagen = request.files.get('imagen')
        nombre_archivo = (imagen.filename if imagen else '').strip()

        texto_publicacion = ' '.join((
            nombre, descripcion, subcategoria, marca, color, talla, sku or '',
            *caracteristicas, *tipos_variacion, *valores_variacion, nombre_archivo
        ))
        nota_contenido = motivo_revision_producto(texto_publicacion)
        nota_revision = nota_contenido

        try:
            precio = float(precio_raw)
            stock = int(request.form.get('stock', '0'))
            categoria_id = int(categoria_raw)
            precio_anterior = float(precio_anterior_raw) if precio_anterior_raw else None
            peso = float(peso_raw) if peso_raw else None
        except (TypeError, ValueError):
            flash('Revisa precio, categoría, stock, precio anterior y peso.', 'error')
            cursor.close()
            conn.close()
            return redirect(url_for('tienda_productos'))
        variaciones = []
        variaciones_invalidas = False
        for tipo, valor, stock_variante in zip(tipos_variacion, valores_variacion, stocks_variacion):
            tipo = tipo.strip()[:50]
            valor = valor.strip()[:80]
            stock_variante = stock_variante.strip()
            if not tipo and not valor and not stock_variante:
                continue
            try:
                cantidad_variante = int(stock_variante)
            except (TypeError, ValueError):
                variaciones_invalidas = True
                break
            if not tipo or not valor or cantidad_variante < 0:
                variaciones_invalidas = True
                break
            variaciones.append({'tipo': tipo, 'valor': valor, 'stock': cantidad_variante})

        if (not nombre or not descripcion or precio <= 0 or stock < 0
                or (precio_anterior is not None and precio_anterior <= precio)
                or (peso is not None and peso < 0) or variaciones_invalidas
                or not imagen or not imagen.filename):
            flash('Completa los datos requeridos y revisa que las variaciones, precios y cantidades sean válidos.', 'error')
            cursor.close()
            conn.close()
            return redirect(url_for('tienda_productos'))
        if not imagen_producto_valida(imagen):
            flash('La imagen debe ser PNG, JPG, GIF o WEBP válida.', 'error')
            cursor.close()
            conn.close()
            return redirect(url_for('tienda_productos'))

        nombre_seguro = secure_filename(imagen.filename)
        nombre_archivo = f"tienda_{session['user_id']}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{nombre_seguro}"
        ruta_imagen = os.path.join(PRODUCT_UPLOAD_FOLDER, nombre_archivo)
        imagen.save(ruta_imagen)
        slug_base = re.sub(r'[^a-z0-9]+', '-', texto_moderacion(nombre)).strip('-') or 'producto'
        slug = f'{slug_base}-{session["user_id"]}-{datetime.now().strftime("%H%M%S%f")}'
        try:
            cursor.execute('SELECT id FROM categorias WHERE id = %s', (categoria_id,))
            categoria = cursor.fetchone()
            if not categoria:
                raise ValueError('Selecciona una categoría válida.')
            destacado_solicitado = bool(request.form.get('solicitar_destacado') == 'on'
                                        and verificar_premium(session['user_id']))
            estado_revision = 'pendiente'
            activo = 0
            cursor.execute('''
                INSERT INTO productos
                    (owner_user_id, nombre, slug, descripcion_corta, descripcion_larga,
                     categoria_id, subcategoria, marca, color, talla, precio, precio_anterior,
                     stock, sku, imagen_principal, peso, especificaciones, variaciones,
                     destacado_solicitado, activo, estado_revision, en_oferta, moderation_note)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (session['user_id'], nombre, slug, descripcion[:255], descripcion,
                  categoria['id'], subcategoria or None, marca or None, color or None, talla or None,
                  precio, precio_anterior, stock, sku, f'uploads/productos/{nombre_archivo}', peso,
                  json.dumps(caracteristicas, ensure_ascii=False),
                  json.dumps(variaciones, ensure_ascii=False), int(destacado_solicitado),
                  activo, estado_revision, int(precio_anterior is not None), nota_revision))
            conn.commit()
            if nota_contenido:
                mensaje = (
                    'Tu propuesta quedó pendiente de revisión por contenido que requiere validación. '
                    'Tu cuenta no recibe ninguna sanción.'
                )
            else:
                mensaje = 'Tu producto fue enviado a administración para aprobación y se publicará cuando sea aprobado.'
                if destacado_solicitado:
                    mensaje += ' También se revisará la solicitud de publicación destacada.'
            flash(mensaje, 'success')
        except ValueError as err:
            conn.rollback()
            if os.path.exists(ruta_imagen):
                os.remove(ruta_imagen)
            flash(str(err), 'error')
        except sqlite3.Error as err:
            conn.rollback()
            if os.path.exists(ruta_imagen):
                os.remove(ruta_imagen)
            print(f'Error creando producto de tienda: {err}')
            flash('No se pudo publicar el producto.', 'error')
        finally:
            cursor.close()
            conn.close()
        return redirect(url_for('tienda_productos'))

    cursor.execute('SELECT id, nombre FROM categorias ORDER BY nombre ASC')
    categorias = cursor.fetchall()
    cursor.execute('''
        SELECT id, nombre, descripcion_corta, precio, imagen_principal, estado_revision,
               destacado_solicitado, moderation_note
        FROM productos WHERE owner_user_id = %s ORDER BY created_at DESC, id DESC
    ''', (session['user_id'],))
    productos_tienda = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('tienda_productos.html', productos=productos_tienda, categorias=categorias)


@app.route('/tienda/productos/<int:id>/editar', methods=['GET', 'POST'])
@tienda_premium_required
def editar_producto_tienda(id):
    conn = get_db_connection()
    if not conn:
        flash('No fue posible conectar con la base de datos.', 'error')
        return redirect(url_for('tienda_productos'))

    cursor = None
    imagen_nueva = None
    try:
        cursor = conn.cursor(dictionary=True)
        asegurar_columna_propietario_producto(conn)
        cursor.execute('SELECT * FROM productos WHERE id = %s AND owner_user_id = %s FOR UPDATE',
                       (id, session['user_id']))
        producto = cursor.fetchone()
        if not producto:
            flash('No encontramos ese producto en tu tienda.', 'error')
            return redirect(url_for('tienda_productos'))

        cursor.execute('SELECT id, nombre FROM categorias ORDER BY nombre ASC')
        categorias = cursor.fetchall()
        if request.method == 'POST':
            nombre = request.form.get('nombre', '').strip()[:150]
            descripcion = request.form.get('descripcion', '').strip()[:2000]
            subcategoria = request.form.get('subcategoria', '').strip()[:100] or None
            marca = request.form.get('marca', '').strip()[:50] or None
            color = request.form.get('color', '').strip()[:50] or None
            talla = request.form.get('talla', '').strip()[:50] or None
            sku = request.form.get('sku', '').strip()[:50] or None
            caracteristicas = [line.strip()[:180] for line in request.form.get('caracteristicas', '').splitlines() if line.strip()][:20]
            tipos_variacion = request.form.getlist('variacion_tipo[]')
            valores_variacion = request.form.getlist('variacion_valor[]')
            stocks_variacion = request.form.getlist('variacion_stock[]')
            imagen = request.files.get('imagen')

            try:
                precio = Decimal(request.form.get('precio', '').strip())
                precio_anterior_raw = request.form.get('precio_anterior', '').strip()
                precio_anterior = Decimal(precio_anterior_raw) if precio_anterior_raw else None
                stock = int(request.form.get('stock', ''))
                categoria_id = int(request.form.get('categoria_id', ''))
                peso_raw = request.form.get('peso', '').strip()
                peso = Decimal(peso_raw) if peso_raw else None
                variaciones_limpias = []
                for tipo, valor, stock_variacion in zip(tipos_variacion, valores_variacion, stocks_variacion):
                    tipo = tipo.strip()[:50]
                    valor = valor.strip()[:80]
                    stock_variacion = stock_variacion.strip()
                    if not tipo and not valor and not stock_variacion:
                        continue
                    cantidad = int(stock_variacion)
                    if not tipo or not valor or cantidad < 0:
                        raise ValueError
                    variaciones_limpias.append({'tipo': tipo, 'valor': valor, 'stock': cantidad})
                if (not nombre or not descripcion or not precio.is_finite() or precio <= 0
                        or stock < 0 or (precio_anterior is not None and
                        (not precio_anterior.is_finite() or precio_anterior <= precio))
                        or (peso is not None and (not peso.is_finite() or peso < 0))):
                    raise ValueError
            except (InvalidOperation, TypeError, ValueError):
                flash('Revisa nombre, precio, precio anterior, stock, categoría, peso y variaciones.', 'error')
                return redirect(url_for('editar_producto_tienda', id=id))

            cursor.execute('SELECT id FROM categorias WHERE id = %s', (categoria_id,))
            if not cursor.fetchone():
                flash('Selecciona una categoría válida.', 'error')
                return redirect(url_for('editar_producto_tienda', id=id))
            if sku:
                cursor.execute('SELECT id FROM productos WHERE sku = %s AND id <> %s LIMIT 1', (sku, id))
                if cursor.fetchone():
                    flash('Ese SKU ya está asociado a otro producto.', 'error')
                    return redirect(url_for('editar_producto_tienda', id=id))
            if imagen and imagen.filename and not imagen_producto_valida(imagen):
                flash('La imagen debe ser PNG, JPG, GIF o WEBP válida.', 'error')
                return redirect(url_for('editar_producto_tienda', id=id))

            imagen_actual = producto.get('imagen_principal') or ''
            imagen_final = imagen_actual
            if imagen and imagen.filename:
                nombre_seguro = secure_filename(imagen.filename)
                nombre_archivo = f"tienda_{session['user_id']}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{nombre_seguro}"
                imagen_nueva = os.path.join(PRODUCT_UPLOAD_FOLDER, nombre_archivo)
                imagen.save(imagen_nueva)
                imagen_final = f'uploads/productos/{nombre_archivo}'

            fecha_fin_oferta = producto.get('fecha_fin_oferta')
            if precio_anterior is None:
                fecha_fin_oferta = None
            elif (not producto.get('en_oferta') or not fecha_fin_oferta
                  or fecha_fin_oferta <= datetime.now()):
                fecha_fin_oferta = datetime.now() + timedelta(days=7)

            def cargar_lista_json(valor):
                if isinstance(valor, str):
                    try:
                        valor = json.loads(valor)
                    except json.JSONDecodeError:
                        return []
                return valor if isinstance(valor, list) else []

            precio_actual_anterior = Decimal(str(producto.get('precio') or 0))
            precio_anterior_guardado = producto.get('precio_anterior')
            precio_anterior_guardado = Decimal(str(precio_anterior_guardado)) if precio_anterior_guardado is not None else None
            caracteristicas_guardadas = cargar_lista_json(producto.get('especificaciones'))
            variaciones_guardadas = cargar_lista_json(producto.get('variaciones'))
            requiere_revision = any((
                producto.get('nombre') != nombre,
                (producto.get('descripcion_larga') or producto.get('descripcion_corta') or '') != descripcion,
                producto.get('categoria_id') != categoria_id,
                (producto.get('subcategoria') or None) != subcategoria,
                (producto.get('marca') or None) != marca,
                (producto.get('color') or None) != color,
                (producto.get('talla') or None) != talla,
                (producto.get('sku') or None) != sku,
                precio_actual_anterior != precio,
                precio_anterior_guardado != precio_anterior,
                (Decimal(str(producto.get('peso'))) if producto.get('peso') is not None else None) != peso,
                caracteristicas_guardadas != caracteristicas,
                variaciones_guardadas != variaciones_limpias,
                imagen_nueva is not None,
            ))
            estado_revision = 'pendiente' if requiere_revision else producto['estado_revision']
            activo = 0 if requiere_revision else producto['activo']
            moderation_note = 'Cambios enviados a revisión por la tienda.' if requiere_revision else producto.get('moderation_note')

            try:
                cursor.execute('''
                    UPDATE productos SET nombre = %s, descripcion_corta = %s, descripcion_larga = %s,
                        categoria_id = %s, subcategoria = %s, marca = %s, color = %s, talla = %s,
                        precio = %s, precio_anterior = %s, stock = %s, sku = %s, peso = %s,
                        especificaciones = %s, variaciones = %s, imagen_principal = %s,
                        en_oferta = %s, fecha_fin_oferta = %s, estado_revision = %s,
                        activo = %s, moderation_note = %s
                    WHERE id = %s AND owner_user_id = %s
                ''', (nombre, descripcion[:255], descripcion, categoria_id, subcategoria, marca,
                      color, talla, precio, precio_anterior, stock, sku, peso,
                      json.dumps(caracteristicas, ensure_ascii=False),
                      json.dumps(variaciones_limpias, ensure_ascii=False), imagen_final,
                      int(precio_anterior is not None), fecha_fin_oferta, estado_revision,
                      activo, moderation_note, id, session['user_id']))
                conn.commit()
            except sqlite3.Error:
                conn.rollback()
                if imagen_nueva and os.path.exists(imagen_nueva):
                    os.remove(imagen_nueva)
                raise

            if imagen_nueva and imagen_actual.startswith('uploads/productos/'):
                imagen_anterior = os.path.abspath(os.path.join(app.static_folder, imagen_actual))
                carpeta_productos = os.path.abspath(PRODUCT_UPLOAD_FOLDER)
                if os.path.commonpath((imagen_anterior, carpeta_productos)) == carpeta_productos and os.path.isfile(imagen_anterior):
                    os.remove(imagen_anterior)
            if requiere_revision:
                flash('Cambios guardados y enviados a revisión antes de volver a publicar el producto.', 'success')
            else:
                flash('Inventario actualizado correctamente.', 'success')
            return redirect(url_for('tienda_productos'))

        try:
            caracteristicas_actuales = producto.get('especificaciones') or []
            if isinstance(caracteristicas_actuales, str):
                caracteristicas_actuales = json.loads(caracteristicas_actuales)
            if not isinstance(caracteristicas_actuales, list):
                caracteristicas_actuales = []
            variaciones_actuales = producto.get('variaciones') or []
            if isinstance(variaciones_actuales, str):
                variaciones_actuales = json.loads(variaciones_actuales)
            if not isinstance(variaciones_actuales, list):
                variaciones_actuales = []
        except (TypeError, ValueError, json.JSONDecodeError):
            caracteristicas_actuales, variaciones_actuales = [], []

        return render_template('tienda_editar_producto.html', producto=producto,
                               categorias=categorias,
                               caracteristicas='\n'.join(str(item) for item in caracteristicas_actuales),
                               variaciones=variaciones_actuales)
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error editando producto de tienda: {err}')
        flash('No se pudo cargar o actualizar el producto.', 'error')
        return redirect(url_for('tienda_productos'))
    finally:
        if cursor:
            cursor.close()
        conn.close()


@app.route('/tienda/productos/<int:id>/eliminar', methods=['POST'])
@tienda_premium_required
def eliminar_producto_tienda(id):
    conn = get_db_connection()
    if not conn:
        flash('No fue posible conectar con la base de datos.', 'error')
        return redirect(url_for('tienda_productos'))
    cursor = None
    imagen = ''
    try:
        cursor = conn.cursor(dictionary=True)
        asegurar_columna_propietario_producto(conn)
        cursor.execute('''
            SELECT imagen_principal FROM productos
            WHERE id = %s AND owner_user_id = %s
        ''', (id, session['user_id']))
        producto = cursor.fetchone()
        if not producto:
            flash('No puedes eliminar productos de otra tienda.', 'error')
            return redirect(url_for('tienda_productos'))
        cursor.execute('SELECT id FROM detalle_factura WHERE producto_id = %s LIMIT 1', (id,))
        tiene_facturas = cursor.fetchone()
        cursor.execute('SELECT id FROM orden_items WHERE producto_id = %s LIMIT 1', (id,))
        tiene_ordenes = cursor.fetchone()
        if tiene_facturas or tiene_ordenes:
            flash('Este producto tiene ventas asociadas y no se puede eliminar.', 'warning')
            return redirect(url_for('tienda_productos'))
        cursor.execute('DELETE FROM productos WHERE id = %s AND owner_user_id = %s', (id, session['user_id']))
        if not cursor.rowcount:
            flash('El producto ya no existe o ya no pertenece a tu tienda.', 'warning')
            return redirect(url_for('tienda_productos'))
        conn.commit()
        imagen = producto.get('imagen_principal', '')
        flash('Producto eliminado correctamente.', 'success')
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error eliminando producto de tienda: {err}')
        flash('No se pudo eliminar el producto.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()

    if imagen.startswith('uploads/productos/'):
        nombre_archivo = imagen.rsplit('/', 1)[-1]
        ruta_imagen = os.path.join(app.static_folder, 'uploads', 'productos', nombre_archivo)
        if nombre_archivo and os.path.isfile(ruta_imagen):
            try:
                os.remove(ruta_imagen)
            except OSError as err:
                print(f'No se pudo eliminar la imagen del producto {id}: {err}')
                flash('El producto fue eliminado, pero no se pudo retirar su imagen del servidor.', 'warning')
    return redirect(url_for('tienda_productos'))


@app.route('/producto/<int:id>')
def producto_detalle_legacy(id):
    conn = get_db_connection()
    if not conn:
        return "Error de conexion", 500
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT slug FROM productos WHERE id = %s", (id,))
    producto = cursor.fetchone()
    cursor.close()
    conn.close()
    if not producto:
        return "Producto no encontrado", 404
    return redirect(url_for('producto_detalle', slug=producto['slug']), code=301)


@app.route('/productos/<string:slug>')
def producto_detalle(slug):
    conn = get_db_connection()
    if not conn:
        return "Error de conexion", 500

    cursor = conn.cursor(dictionary=True)
    asegurar_columna_propietario_producto(conn)
    expirar_ofertas(conn)
    asegurar_tabla_valoraciones_producto(conn)
    cursor.execute("SELECT * FROM productos WHERE slug = %s AND activo = 1 AND estado_revision = 'aprobado'", (slug,))
    producto = cursor.fetchone()

    if not producto:
        cursor.close()
        conn.close()
        return "Producto no encontrado", 404

    for campo_json in ('especificaciones', 'variaciones'):
        valor_json = producto.get(campo_json)
        if isinstance(valor_json, str):
            try:
                producto[campo_json] = json.loads(valor_json)
            except (ValueError, TypeError):
                producto[campo_json] = []

    if session.get('user_id'):
        try:
            asegurar_tabla_productos_vistos(conn)
            cursor.execute('''
                INSERT INTO productos_vistos (usuario_id, producto_id)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE visto_at = CURRENT_TIMESTAMP
            ''', (session['user_id'], producto['id']))
            conn.commit()
        except sqlite3.Error as err:
            conn.rollback()
            print(f'Error guardando producto visto: {err}')
    else:
        vistos = session.get('productos_vistos', [])
        vistos = [producto_id for producto_id in vistos if isinstance(producto_id, int) and producto_id != producto['id']]
        session['productos_vistos'] = [producto['id'], *vistos[:39]]

    es_favorito = False
    favoritos_ids = set()
    deseos_ids = set()
    if session.get('user_id'):
        asegurar_tabla_favoritos(conn)
        asegurar_tabla_lista_deseos(conn)
        cursor.execute('''
            SELECT id FROM favoritos WHERE usuario_id = %s AND producto_id = %s
        ''', (session['user_id'], producto['id']))
        es_favorito = cursor.fetchone() is not None
        cursor.execute('SELECT producto_id FROM favoritos WHERE usuario_id = %s', (session['user_id'],))
        favoritos_ids = {fila['producto_id'] for fila in cursor.fetchall()}
        cursor.execute('SELECT producto_id FROM lista_deseos WHERE usuario_id = %s', (session['user_id'],))
        deseos_ids = {fila['producto_id'] for fila in cursor.fetchall()}

    try:
        cursor.execute('''
            SELECT COALESCE(AVG(calificacion), 0) AS promedio, COUNT(*) AS total
            FROM producto_valoraciones WHERE producto_id = %s
        ''', (producto['id'],))
        valoracion = cursor.fetchone() or {'promedio': 0, 'total': 0}
        cursor.execute('''
            SELECT * FROM productos
            WHERE id != %s AND activo = 1 AND categoria_id = %s
            ORDER BY CASE WHEN subcategoria = %s THEN 0 ELSE 1 END,
                     destacado DESC, id DESC
            LIMIT 4
        ''', (producto['id'], producto.get('categoria_id'), producto.get('subcategoria')))
        similares = cursor.fetchall()
    except sqlite3.Error:
        similares = []

    try:
        cursor.execute("""
            SELECT pf.*, u.username AS usuario_nombre,
                   COALESCE(AVG(pv.calificacion), 0) AS valoracion_promedio,
                   COUNT(pv.id) AS total_valoraciones
            FROM preguntas_frecuentes pf
            LEFT JOIN usuarios u ON u.id = pf.usuario_id
            LEFT JOIN preguntas_frecuentes_valoraciones pv ON pv.pregunta_id = pf.id
            WHERE pf.producto_id = %s AND pf.aprobada = 1
            GROUP BY pf.id
            ORDER BY valoracion_promedio DESC, total_valoraciones DESC, pf.created_at DESC
        """, (producto['id'],))
        preguntas = cursor.fetchall()
    except sqlite3.Error:
        preguntas = []

    cursor.close()
    conn.close()
    return render_template('producto_detalle.html', producto=producto, similares=similares,
                           preguntas=preguntas, valoracion=valoracion,
                           es_favorito=es_favorito, favoritos_ids=favoritos_ids,
                           deseos_ids=deseos_ids)


@app.route('/productos/<string:slug>/preguntas', methods=['POST'])
@login_required
@not_banned_required
def preguntar_producto(slug):
    pregunta = request.form.get('pregunta', '').strip()
    if not pregunta or len(pregunta) > 1000:
        flash('Escribe una pregunta válida de máximo 1000 caracteres.', 'error')
        return redirect(url_for('producto_detalle', slug=slug))
    if contiene_lenguaje_ofensivo(pregunta):
        banear_usuario_por_moderacion(session['user_id'], 'Lenguaje ofensivo en una pregunta de producto.', pregunta, None)
        flash('Tu cuenta fue bloqueada por publicar contenido ofensivo.', 'error')
        return redirect(url_for('apelar_baneo'))
    conn = get_db_connection()
    if not conn:
        flash('No fue posible guardar la pregunta.', 'error')
        return redirect(url_for('producto_detalle', slug=slug))
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute('SELECT id FROM productos WHERE slug = %s AND activo = 1', (slug,))
        producto = cursor.fetchone()
        if not producto:
            return 'Producto no encontrado', 404
        cursor.execute('''
            INSERT INTO preguntas_frecuentes (producto_id, usuario_id, pregunta, aprobada)
            VALUES (%s, %s, %s, 1)
        ''', (producto['id'], session['user_id'], pregunta))
        conn.commit()
        flash('Pregunta enviada. Aparecerá cuando sea aprobada.', 'success')
    except sqlite3.Error:
        conn.rollback()
        flash('No fue posible guardar la pregunta.', 'error')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('producto_detalle', slug=slug))


@app.route('/preguntas/<int:pregunta_id>/calificar', methods=['POST'])
@login_required
@not_banned_required
def calificar_pregunta_producto(pregunta_id):
    try:
        calificacion = int(request.form.get('calificacion', 0))
    except (TypeError, ValueError):
        calificacion = 0
    if calificacion not in range(1, 6):
        flash('La calificación debe estar entre 1 y 5 estrellas.', 'error')
        return redirect(request.referrer or url_for('productos'))
    conn = get_db_connection()
    if not conn:
        flash('No fue posible guardar la calificación.', 'error')
        return redirect(request.referrer or url_for('productos'))
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO preguntas_frecuentes_valoraciones (pregunta_id, usuario_id, calificacion)
            SELECT id, %s, %s FROM preguntas_frecuentes WHERE id = %s AND aprobada = 1
            ON DUPLICATE KEY UPDATE calificacion = VALUES(calificacion), fecha = CURRENT_TIMESTAMP
        ''', (session['user_id'], calificacion, pregunta_id))
        if cursor.rowcount == 0:
            flash('La pregunta no está disponible para calificar.', 'error')
        else:
            conn.commit()
            flash('Tu calificación de la pregunta fue guardada.', 'success')
    except sqlite3.Error:
        conn.rollback()
        flash('No fue posible guardar la calificación.', 'error')
    finally:
        cursor.close()
        conn.close()
    return redirect(request.referrer or url_for('productos'))


@app.route('/productos/<string:slug>/calificar', methods=['POST'])
@login_required
@not_banned_required
def calificar_producto(slug):
    try:
        calificacion = int(request.form.get('calificacion', 0))
    except (TypeError, ValueError):
        calificacion = 0
    if calificacion not in range(1, 6):
        flash('La calificación debe estar entre 1 y 5 estrellas.', 'error')
        return redirect(url_for('producto_detalle', slug=slug))
    conn = get_db_connection()
    if not conn:
        flash('No fue posible guardar la calificación.', 'error')
        return redirect(url_for('producto_detalle', slug=slug))
    cursor = conn.cursor(dictionary=True)
    try:
        asegurar_tabla_valoraciones_producto(conn)
        cursor.execute('SELECT id FROM productos WHERE slug = %s AND activo = 1', (slug,))
        producto = cursor.fetchone()
        if not producto:
            return 'Producto no encontrado', 404
        cursor.execute('''
            INSERT INTO producto_valoraciones (producto_id, usuario_id, calificacion)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE calificacion = VALUES(calificacion), fecha = CURRENT_TIMESTAMP
        ''', (producto['id'], session['user_id'], calificacion))
        conn.commit()
        flash('Tu calificación fue guardada.', 'success')
    except sqlite3.Error:
        conn.rollback()
        flash('No fue posible guardar la calificación.', 'error')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('producto_detalle', slug=slug))


@app.route('/catalogo')
def catalogo():
    categoria = request.args.get('categoria')
    subcategoria = request.args.get('subcategoria')
    marca = request.args.get('marca')
    color = request.args.get('color')
    talla = request.args.get('talla')
    precio_max = request.args.get('precio_max')

    conn = get_db_connection()
    if not conn:
        return render_template('productos.html', productos=[], favoritos_ids=set(),
                               deseos_ids=set(), busqueda='', lista_guardados='')

    query = "SELECT * FROM productos WHERE activo = 1 AND estado_revision = 'aprobado'"
    parametros = []
    favoritos_ids = set()
    deseos_ids = set()
    productos_lista = []

    if categoria:
        query += " AND categoria = %s"
        parametros.append(categoria)
    if subcategoria:
        query += " AND subcategoria = %s"
        parametros.append(subcategoria)
    if marca:
        query += " AND marca = %s"
        parametros.append(marca)
    if color:
        query += " AND color = %s"
        parametros.append(color)
    if talla:
        query += " AND talla = %s"
        parametros.append(talla)
    if precio_max:
        query += " AND precio <= %s"
        parametros.append(precio_max)

    try:
        cursor = conn.cursor(dictionary=True)
        asegurar_columna_propietario_producto(conn)
        expirar_ofertas(conn)
        if session.get('user_id'):
            asegurar_tabla_favoritos(conn)
            asegurar_tabla_lista_deseos(conn)
            cursor.execute('SELECT producto_id FROM favoritos WHERE usuario_id = %s', (session['user_id'],))
            favoritos_ids = {fila['producto_id'] for fila in cursor.fetchall()}
            cursor.execute('SELECT producto_id FROM lista_deseos WHERE usuario_id = %s', (session['user_id'],))
            deseos_ids = {fila['producto_id'] for fila in cursor.fetchall()}
        cursor.execute(query, tuple(parametros))
        productos_lista = cursor.fetchall()
    except sqlite3.Error as err:
        print(f"Error en catalogo: {err}")
        productos_lista = []
    finally:
        cursor.close()
        conn.close()

    return render_template('productos.html', productos=productos_lista,
                           favoritos_ids=favoritos_ids, deseos_ids=deseos_ids,
                           busqueda='', lista_guardados='')


@app.route('/contacto', methods=['GET', 'POST'])
def contacto():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        correo = request.form.get('correo', '').strip()
        motivo = request.form.get('motivo', '').strip()
        mensaje = request.form.get('mensaje', '').strip()
        usuario_id = session.get('user_id')

        conn = get_db_connection()
        if conn is None:
            flash("Error de conexion a la base de datos.", "error")
            return redirect(url_for('contacto'))

        try:
            cursor = conn.cursor()
            query = """
                INSERT INTO solicitudes_contacto (usuario_id, nombre, correo, motivo, mensaje)
                VALUES (%s, %s, %s, %s, %s)
            """
            cursor.execute(query, (usuario_id, nombre, correo, motivo, mensaje))
            conn.commit()
            flash('Mensaje enviado con exito!', 'success')
            return redirect(url_for('contacto_exito'))
        except sqlite3.Error as err:
            print(f"Error: {err}")
            flash('Hubo un error interno.', 'error')
            return redirect(url_for('contacto'))
        finally:
            cursor.close()
            conn.close()

    usuario_datos = None
    if 'user_id' in session:
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT username, email FROM usuarios WHERE id = %s", (session['user_id'],))
                usuario_datos = cursor.fetchone()
            except sqlite3.Error as err:
                print(f"Error: {err}")
            finally:
                cursor.close()
                conn.close()

    return render_template('contacto.html', usuario=usuario_datos)


@app.route('/contacto-exito')
def contacto_exito():
    return render_template('contacto_exito.html')


# ═══════════════════════════════════════════════════════════════════════════
# RUTAS PROTEGIDAS (LOGIN REQUIRED)
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/carrito/agregar/<int:producto_id>', methods=['POST'])
@login_required
def agregar_al_carrito(producto_id):
    usuario_id = session.get('user_id')
    try:
        cantidad = int(request.form.get('cantidad', 1))
    except ValueError:
        cantidad = 1

    conn = get_db_connection()
    if not conn:
        flash("Error de conexion", "error")
        return redirect(url_for('productos'))

    try:
        cursor = conn.cursor()
        query = """
            INSERT INTO carrito (usuario_id, producto_id, cantidad) 
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE cantidad = cantidad + VALUES(cantidad)
        """
        cursor.execute(query, (usuario_id, producto_id, cantidad))
        conn.commit()
        flash("Producto agregado al carrito", "success")
    except sqlite3.Error as err:
        conn.rollback()
        print(f"Error al agregar al carrito: {err}")
        flash("No se pudo agregar el producto", "error")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('ver_carrito'))


@app.route('/api/compras', methods=['POST'])
@login_required
def crear_compra():
    datos = request.get_json(silent=True) or {}
    if not isinstance(datos, dict):
        return jsonify(error='Los datos de compra no tienen un formato válido.'), 400
    if datos.get('modo_demo') is not True:
        return jsonify(error='La compra está disponible únicamente en modo demostración hasta configurar una pasarela.'), 503

    metodos_demo = {'tarjeta', 'visa', 'mastercard', 'american_express', 'transferencia', 'paypal',
                    'apple_pay', 'google_pay', 'mercado_pago', 'contra_entrega', 'nequi', 'daviplata', 'pse'}
    metodo_pago = str(datos.get('metodo_pago') or '').strip()
    if metodo_pago not in metodos_demo:
        return jsonify(error='Selecciona un método de demostración válido.'), 400

    productos_solicitados = datos.get('productos')
    if not isinstance(productos_solicitados, list) or not productos_solicitados:
        return jsonify(error='Agrega al menos un producto al carrito.'), 400

    cantidades_por_producto = {}
    try:
        for item in productos_solicitados:
            producto_id = int(item['id'])
            cantidad = int(item['cantidad'])
            if producto_id <= 0 or cantidad <= 0 or cantidad > 99:
                raise ValueError
            cantidades_por_producto[producto_id] = cantidades_por_producto.get(producto_id, 0) + cantidad
            if cantidades_por_producto[producto_id] > 99:
                raise ValueError
    except (KeyError, TypeError, ValueError):
        return jsonify(error='El carrito contiene productos o cantidades no válidos.'), 400

    direccion = limpiar_datos_direccion(datos)
    campos_requeridos = ('nombre_recibe', 'telefono', 'departamento', 'ciudad', 'barrio', 'direccion')
    if any(not direccion[campo] for campo in campos_requeridos):
        return jsonify(error='Completa todos los datos obligatorios de entrega.'), 400

    conn = get_db_connection()
    if not conn:
        return jsonify(error='No fue posible conectar con la base de datos. No se creó ningún pedido.'), 503

    cursor = None
    try:
        asegurar_tabla_direcciones(conn)
        asegurar_tablas_seguimiento_envios(conn)
        asegurar_tablas_recompensas_juego(conn)
        cursor = conn.cursor(dictionary=True)

        if datos.get('direccion_id'):
            try:
                direccion_id = int(datos['direccion_id'])
            except (TypeError, ValueError):
                return jsonify(error='La dirección seleccionada no es válida.'), 400
            cursor.execute(
                'SELECT id FROM direcciones_usuario WHERE id = %s AND usuario_id = %s',
                (direccion_id, session['user_id'])
            )
            if not cursor.fetchone():
                return jsonify(error='La dirección seleccionada no pertenece a tu cuenta.'), 400

        productos = []
        subtotal = Decimal('0')
        tiendas = set()
        for producto_id in sorted(cantidades_por_producto):
            cantidad = cantidades_por_producto[producto_id]
            cursor.execute('''
                SELECT id, owner_user_id, nombre, precio, stock
                FROM productos
                WHERE id = %s AND activo = 1 AND estado_revision = 'aprobado'
                FOR UPDATE
            ''', (producto_id,))
            producto = cursor.fetchone()
            if not producto:
                conn.rollback()
                return jsonify(error='Uno de los productos ya no está disponible.'), 409
            if producto['stock'] < cantidad:
                conn.rollback()
                return jsonify(error=f'No hay suficiente inventario de {producto["nombre"]}.'), 409

            precio = Decimal(str(producto['precio']))
            importe = precio * cantidad
            producto.update(cantidad=cantidad, precio_unitario=precio, subtotal=importe)
            productos.append(producto)
            subtotal += importe
            tiendas.add(producto['owner_user_id'])

        codigo_cupon = str(datos.get('codigo_cupon') or '').strip().upper()[:40]
        descuento = Decimal('0.00')
        tipo_cupon = None
        valor_cupon = None
        if codigo_cupon:
            cursor.execute('''
                SELECT tipo, valor FROM tennissel_ruleta_cupones
                WHERE codigo = %s AND usuario_id = %s AND usado = 0 FOR UPDATE
            ''', (codigo_cupon, session['user_id']))
            cupon = cursor.fetchone()
            if not cupon:
                conn.rollback()
                return jsonify(error='El cupón no existe, ya se usó o pertenece a otra cuenta.'), 400
            tipo_cupon, valor_cupon = cupon['tipo'], cupon['valor']
            if tipo_cupon == 'descuento':
                porcentaje = Decimal(re.sub(r'[^0-9.]', '', str(valor_cupon)) or '0')
                descuento = (subtotal * porcentaje / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        envio = Decimal('0') if subtotal >= Decimal('300000') or tipo_cupon == 'envio' else Decimal('10000')
        ahorro_envio = Decimal('10000') if tipo_cupon == 'envio' and subtotal < Decimal('300000') else Decimal('0.00')
        descuento_reportado = descuento + ahorro_envio
        total = max(Decimal('0'), subtotal - descuento) + envio
        cursor.execute('''
            INSERT INTO facturas (usuario_id, total, estado, metodo_pago)
            VALUES (%s, %s, 'demo', %s)
        ''', (session['user_id'], total, f'demo_{metodo_pago}'))
        factura_id = cursor.lastrowid
        if codigo_cupon:
            cursor.execute('''
                UPDATE tennissel_ruleta_cupones SET usado = 1, factura_id = %s
                WHERE codigo = %s AND usuario_id = %s AND usado = 0
            ''', (factura_id, codigo_cupon, session['user_id']))
            if cursor.rowcount != 1:
                conn.rollback()
                return jsonify(error='No fue posible reservar el uso de este cupón.'), 409

        for producto in productos:
            cursor.execute('''
                INSERT INTO detalle_factura
                    (factura_id, producto_id, cantidad, precio_unitario, subtotal)
                VALUES (%s, %s, %s, %s, %s)
            ''', (
                factura_id, producto['id'], producto['cantidad'],
                producto['precio_unitario'], producto['subtotal']
            ))
            cursor.execute(
                'UPDATE productos SET stock = stock - %s WHERE id = %s',
                (producto['cantidad'], producto['id'])
            )

        if datos.get('guardar_direccion') is True:
            cursor.execute('''
                INSERT INTO direcciones_usuario
                    (usuario_id, nombre_recibe, telefono, departamento, ciudad, barrio,
                     direccion, complemento, codigo_postal, instrucciones)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                session['user_id'], direccion['nombre_recibe'], direccion['telefono'],
                direccion['departamento'], direccion['ciudad'], direccion['barrio'],
                direccion['direccion'], direccion['complemento'],
                direccion['codigo_postal'], direccion['instrucciones']
            ))

        fecha_estimada = (datetime.now() + timedelta(days=5)).date()
        for tienda_id in tiendas:
            numero_envio = f'DEMO-{factura_id}-{tienda_id or 0}'
            cursor.execute('''
                INSERT INTO marketplace_envios
                    (factura_id, usuario_id, tienda_user_id, numero_envio, estado,
                     nombre_recibe, direccion_envio, departamento_envio, ciudad_envio,
                     barrio_envio, complemento_envio, codigo_postal_envio,
                     telefono_envio, instrucciones_envio, fecha_estimada)
                VALUES (%s, %s, %s, %s, 'pedido_recibido', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                factura_id, session['user_id'], tienda_id, numero_envio,
                direccion['nombre_recibe'], direccion['direccion'], direccion['departamento'],
                direccion['ciudad'], direccion['barrio'], direccion['complemento'],
                direccion['codigo_postal'], direccion['telefono'],
                direccion['instrucciones'], fecha_estimada
            ))
            envio_id = cursor.lastrowid
            cursor.execute('''
                INSERT INTO marketplace_envio_eventos (envio_id, actor_user_id, estado, descripcion)
                VALUES (%s, %s, 'pedido_recibido', 'Pedido de demostración confirmado.')
            ''', (envio_id, session['user_id']))

        cursor.execute('DELETE FROM carrito WHERE usuario_id = %s', (session['user_id'],))
        conn.commit()
        return jsonify(
            factura_id=factura_id,
            metodo_pago=metodo_pago.replace('_', ' ').title(),
            fecha_entrega_estimada=fecha_estimada.isoformat(),
            modo_demo=True,
            total=str(total),
            descuento=str(descuento_reportado),
            codigo_cupon=codigo_cupon or None
        ), 201
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error al registrar compra de demostración: {err}')
        return jsonify(error='No se pudo registrar el pedido. No se completó la compra.'), 500
    finally:
        if cursor:
            cursor.close()
        conn.close()


@app.route('/carrito')
@login_required
def ver_carrito():
    usuario_id = session.get('user_id')
    conn = get_db_connection()
    if not conn:
        flash("Error de conexion", "error")
        return redirect(url_for('index'))

    carrito_items = []
    direcciones = []
    total = 0
    try:
        asegurar_tabla_direcciones(conn)
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT c.id AS carrito_id, p.id AS producto_id, p.nombre, p.precio, c.cantidad, 
                   (p.precio * c.cantidad) AS subtotal
            FROM carrito c
            JOIN productos p ON c.producto_id = p.id
            WHERE c.usuario_id = %s
        """
        cursor.execute(query, (usuario_id,))
        carrito_items = cursor.fetchall()
        total = sum(item['subtotal'] for item in carrito_items)
        cursor.execute('''
            SELECT * FROM direcciones_usuario
            WHERE usuario_id = %s ORDER BY es_principal DESC, created_at DESC, id DESC
        ''', (usuario_id,))
        direcciones = cursor.fetchall()
    except sqlite3.Error as err:
        print(f"Error al cargar carrito: {err}")
    finally:
        cursor.close()
        conn.close()

    return render_template('carrito.html', carrito=carrito_items, total=total, direcciones=direcciones)


@app.route('/carrito/eliminar/<int:carrito_id>', methods=['POST'])
@login_required
def eliminar_item_carrito(carrito_id):
    usuario_id = session.get('user_id')
    conn = get_db_connection()
    if not conn:
        flash("Error de conexion", "error")
        return redirect(url_for('ver_carrito'))

    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM carrito WHERE id = %s AND usuario_id = %s", (carrito_id, usuario_id))
        conn.commit()
        flash("Producto eliminado del carrito", "success")
    except sqlite3.Error as err:
        conn.rollback()
        print(f"Error al eliminar item: {err}")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('ver_carrito'))


@app.route('/premium', methods=['GET', 'POST'])
@login_required
def premium():
    compra_premium = None
    conn_actual = get_db_connection()
    if conn_actual:
        cursor_actual = None
        try:
            asegurar_columnas_pago_premium(conn_actual)
            cursor_actual = conn_actual.cursor(dictionary=True)
            cursor_actual.execute('''
                SELECT plan, metodo_pago, pago_simulado, fecha_inicio, fecha_fin
                FROM premium WHERE user_id = %s
                ORDER BY fecha_inicio DESC LIMIT 1
            ''', (session['user_id'],))
            compra_premium = cursor_actual.fetchone()
            if compra_premium:
                compra_premium['importe'] = {
                    'Pase Mensual PRO': 39900,
                    'Pase Élite Anual': 299900,
                }.get(compra_premium.get('plan'), 0)
        except sqlite3.Error as err:
            app.logger.exception('No se pudo cargar el comprobante Premium: %s', err)
        finally:
            if cursor_actual:
                cursor_actual.close()
            conn_actual.close()
    if request.method == 'POST':
        planes = {'Pase Mensual PRO': 30, 'Pase Élite Anual': 365}
        importes_planes = {30: 39900, 365: 299900}
        metodos_demo = {'tarjeta', 'visa', 'mastercard', 'american_express', 'transferencia', 'paypal',
                        'apple_pay', 'google_pay', 'mercado_pago', 'contra_entrega', 'nequi', 'daviplata', 'pse'}
        metodos_pagos = {
            'tarjeta': 'tarjeta', 'visa': 'tarjeta', 'mastercard': 'tarjeta',
            'american_express': 'tarjeta', 'apple_pay': 'tarjeta', 'google_pay': 'tarjeta',
            'mercado_pago': 'tarjeta', 'contra_entrega': 'tarjeta',
            'transferencia': 'transferencia', 'pse': 'transferencia',
            'paypal': 'paypal', 'nequi': 'nequi', 'daviplata': 'daviplata',
        }
        plan = request.form.get('plan', '').strip()
        metodo_pago = request.form.get('metodo_pago', '').strip()
        if plan not in planes or metodo_pago not in metodos_demo:
            flash('Selecciona un plan y un método de demostración válidos.', 'error')
            return redirect(url_for('premium'))
        conn = get_db_connection()
        if not conn:
            flash('No fue posible activar Premium.', 'error')
            return redirect(url_for('premium'))
        cursor = None
        try:
            asegurar_columnas_pago_premium(conn)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO premium (user_id, plan, metodo_pago, pago_simulado, fecha_fin)
                VALUES (%s, %s, %s, 1, %s)
                ON DUPLICATE KEY UPDATE plan = VALUES(plan), metodo_pago = VALUES(metodo_pago),
                                        pago_simulado = 1, fecha_inicio = CURRENT_TIMESTAMP,
                                        fecha_fin = VALUES(fecha_fin)
            ''', (session['user_id'], plan, metodo_pago,
                  datetime.now() + timedelta(days=planes[plan])))
            cursor.execute('''
                INSERT INTO pagos
                    (orden_id, usuario_id, monto, metodo, estado, referencia_pago)
                VALUES (NULL, %s, %s, %s, 'completado', %s)
            ''', (
                session['user_id'], importes_planes[planes[plan]], metodos_pagos[metodo_pago],
                f'PREMIUM-DEMO:{plan}:{metodo_pago}'[:100]
            ))
            conn.commit()
            flash(f'{plan} quedó activo por {planes[plan]} días en modo demostración. No se realizó ningún cobro real.', 'success')
            return redirect(url_for('index'))
        except sqlite3.Error as err:
            conn.rollback()
            print(f'Error activando Premium de demostración: {err}')
            flash('No fue posible activar el plan Premium.', 'error')
            return redirect(url_for('premium'))
        finally:
            if cursor:
                cursor.close()
            conn.close()

    return render_template('premium.html', compra_premium=compra_premium)


@app.route('/exito')
def exito():
    return render_template('exito.html')


@app.route('/notificaciones')
@login_required
def notificaciones():
    usuario_id = session.get('user_id')
    conn = get_db_connection()
    if conn is None:
        flash("Error de conexion.", "error")
        return redirect(url_for('index'))

    try:
        asegurar_tabla_notificaciones_productos(conn)
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT id, motivo, mensaje, respuesta, fecha_respuesta, NULL AS evidencia,
                   'soporte' AS origen, NULL AS detalle
            FROM soporte_tecnico WHERE usuario_id = %s AND respuesta IS NOT NULL
            UNION ALL
            SELECT id, motivo, mensaje, respuesta, fecha_respuesta, NULL AS evidencia,
                   'contacto' AS origen, NULL AS detalle
            FROM solicitudes_contacto WHERE usuario_id = %s AND respuesta IS NOT NULL
            UNION ALL
            SELECT id, titulo AS motivo, apelacion AS mensaje, respuesta,
                   fecha_respuesta, evidencia, 'moderacion' AS origen, NULL AS detalle
            FROM notificaciones_moderacion WHERE usuario_id = %s
            UNION ALL
            SELECT id, titulo AS motivo, NULL AS mensaje, NULL AS respuesta,
                   created_at AS fecha_respuesta, NULL AS evidencia,
                   'productos' AS origen, mensaje AS detalle
            FROM notificaciones_productos WHERE usuario_id = %s
            ORDER BY fecha_respuesta DESC
        """
        cursor.execute(query, (usuario_id, usuario_id, usuario_id, usuario_id))
        notificaciones_list = cursor.fetchall()
    except sqlite3.Error as err:
        print(f"Error al cargar notificaciones: {err}")
        notificaciones_list = []
    finally:
        cursor.close()
        conn.close()

    return render_template('notificaciones.html', notificaciones=notificaciones_list)


@app.route('/api/notificaciones/count')
@login_required
def api_notificaciones_count():
    return jsonify(count=contar_notificaciones(session['user_id']))


@app.route('/soporte_tecnico', methods=['GET', 'POST'])
@login_required
def soporte_tecnico():
    if request.method == 'POST':
        motivo = request.form.get('motivo', '').strip()
        mensaje = request.form.get('mensaje', '').strip()
        usuario_id = session.get('user_id')

        if not motivo or not mensaje:
            flash("Por favor, completa todos los campos.", "error")
            return redirect(url_for('soporte_tecnico'))

        conn = get_db_connection()
        if conn is None:
            flash("Error de conexion.", "error")
            return redirect(url_for('soporte_tecnico'))

        try:
            cursor = conn.cursor()
            query = """
                INSERT INTO soporte_tecnico (usuario_id, motivo, mensaje, fecha_envio)
                VALUES (%s, %s, %s, NOW())
            """
            cursor.execute(query, (usuario_id, motivo, mensaje))
            conn.commit()
            flash('Solicitud de soporte enviada con exito!', 'success')
            return redirect(url_for('contacto_exito'))
        except sqlite3.Error as err:
            conn.rollback()
            print(f"Error al guardar soporte: {err}")
            flash('Hubo un error al procesar tu solicitud.', 'error')
            return redirect(url_for('soporte_tecnico'))
        finally:
            cursor.close()
            conn.close()

    return render_template('soporte_tecnico.html')


# ═══════════════════════════════════════════════════════════════════════════
# RUTA DE EDITAR PERFIL
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/editarperfil', methods=['GET', 'POST'])
@login_required
def editarperfil():
    conn = get_db_connection()
    if conn is None:
        flash("Error de conexión con la base de datos.", "error")
        return redirect(url_for("index"))

    if request.method == 'POST':
        username        = request.form.get('username', '').strip()
        nombre_completo = request.form.get('nombre_completo', '').strip()
        email           = request.form.get('email', '').strip()
        telefono        = request.form.get('telefono', '').strip()
        ciudad          = request.form.get('ciudad', '').strip()
        nivel           = request.form.get('nivel', 'principiante')
        mano_dominante  = request.form.get('mano_dominante', 'diestro')
        reves           = request.form.get('reves', 'dos_manos')
        biografia       = request.form.get('biografia', '').strip()
        avatar_preset   = request.form.get('avatar_preset', '').strip()

        if not username or not email or not nombre_completo:
            flash("El nombre de usuario, nombre completo y correo son obligatorios.", "error")
            conn.close()
            return redirect(url_for("editarperfil"))
        if len(biografia) > 500:
            flash("La descripción no puede superar los 500 caracteres.", "error")
            conn.close()
            return redirect(url_for("editarperfil"))

        file = request.files.get('foto_perfil')
        if file and file.filename:
            if not perfil_image_valida(file):
                flash("La foto debe ser PNG, JPG, GIF o WEBP válida y pesar menos de 5 MB.", "error")
                conn.close()
                return redirect(url_for("editarperfil"))

        foto_filename = None
        foto_path = None
        foto_vieja = None
        cursor = None
        try:
            if file and file.filename:
                ext = os.path.splitext(secure_filename(file.filename))[1].lower()
                foto_filename = f"user_{session['user_id']}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}{ext}"
                foto_path = os.path.join(app.config['UPLOAD_FOLDER'], foto_filename)
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                file.save(foto_path)
            elif avatar_preset in PROFILE_AVATARS:
                foto_filename = avatar_preset
            cursor = conn.cursor()

            cursor.execute("SELECT foto FROM perfil_usuario WHERE usuario_id = %s", (session['user_id'],))
            foto_row = cursor.fetchone()
            foto_vieja = foto_row[0] if foto_row else None
            cursor.execute("""
                UPDATE usuarios 
                SET username = %s, nombre_completo = %s, email = %s, 
                    telefono = %s, ciudad = %s
                WHERE id = %s
            """, (username, nombre_completo, email, telefono, ciudad, session['user_id']))

            cursor.execute("SELECT COUNT(*) FROM perfil_usuario WHERE usuario_id = %s", (session['user_id'],))
            existe = cursor.fetchone()[0]

            if existe:
                if foto_filename:
                    cursor.execute("""
                        UPDATE perfil_usuario 
                        SET nivel = %s, mano = %s, reves = %s, biografia = %s, foto = %s
                        WHERE usuario_id = %s
                    """, (nivel, mano_dominante, reves, biografia, foto_filename, session['user_id']))
                else:
                    cursor.execute("""
                        UPDATE perfil_usuario 
                        SET nivel = %s, mano = %s, reves = %s, biografia = %s
                        WHERE usuario_id = %s
                    """, (nivel, mano_dominante, reves, biografia, session['user_id']))
            else:
                foto_def = foto_filename or 'default.png'
                cursor.execute("""
                    INSERT INTO perfil_usuario (usuario_id, foto, nivel, mano, reves, biografia)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (session['user_id'], foto_def, nivel, mano_dominante, reves, biografia))

            nueva_password = request.form.get('password', '').strip()
            if nueva_password:
                if len(nueva_password) < 6:
                    flash("La nueva contraseña debe tener al menos 6 caracteres.", "warning")
                else:
                    cursor.execute("""
                        UPDATE usuarios SET password = %s WHERE id = %s
                    """, (generate_password_hash(nueva_password), session['user_id']))

            conn.commit()
            session['username'] = username
            if foto_filename and foto_vieja and foto_vieja != 'default.png':
                vieja = secure_filename(os.path.basename(str(foto_vieja).replace('\\', '/')))
                if vieja and vieja != foto_filename:
                    for folder in (
                        app.config['UPLOAD_FOLDER'],
                        os.path.abspath(os.path.join(app.root_path, '..', 'static', 'uploads', 'perfiles')),
                    ):
                        old_path = os.path.join(folder, vieja)
                        if os.path.isfile(old_path):
                            try:
                                os.remove(old_path)
                            except OSError as err:
                                app.logger.warning('No se pudo retirar la foto de perfil anterior: %s', err)
            flash("Perfil actualizado con éxito!", "success")
            return redirect(url_for("editarperfil"))

        except sqlite3.Error as err:
            conn.rollback()
            if foto_path and os.path.isfile(foto_path):
                os.remove(foto_path)
            print(f"Error al actualizar el perfil: {err}")
            flash("Error al actualizar los datos.", "error")
            return redirect(url_for("editarperfil"))
        except OSError as err:
            conn.rollback()
            if foto_path and os.path.isfile(foto_path):
                os.remove(foto_path)
            app.logger.exception('No se pudo guardar la foto de perfil: %s', err)
            flash("No se pudo guardar la foto de perfil. Inténtalo de nuevo.", "error")
            return redirect(url_for("editarperfil"))
        finally:
            if cursor:
                cursor.close()
            conn.close()

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT 
                u.id, u.username, u.nombre_completo, u.email, 
                u.telefono, u.ciudad,
                p.foto, p.biografia, p.nivel, p.mano AS mano_dominante, p.reves
            FROM usuarios u
            LEFT JOIN perfil_usuario p ON u.id = p.usuario_id
            WHERE u.id = %s
        """, (session['user_id'],))
        usuario = cursor.fetchone()
        if usuario:
            foto_guardada = usuario.get('foto')
            usuario['avatar_preset'] = LEGACY_PROFILE_AVATARS.get(foto_guardada, foto_guardada) if foto_guardada in (*PROFILE_AVATARS, *LEGACY_PROFILE_AVATARS) else ''
            usuario['foto'] = foto_perfil_url(usuario.get('foto'))
    except sqlite3.Error as err:
        print(err)
        flash("No fue posible obtener el usuario.", "error")
        return redirect(url_for("index"))
    finally:
        cursor.close()
        conn.close()

    if usuario is None:
        flash("Usuario no encontrado.", "error")
        return redirect(url_for("index"))

    return render_template("editarperfil.html", usuario=usuario, profile_avatars=PROFILE_AVATARS)


DIAS_ESPANOL = {
    0: 'Lunes', 1: 'Martes', 2: 'Miercoles', 
    3: 'Jueves', 4: 'Viernes', 5: 'Sabado', 6: 'Domingo'
}


@app.route('/terminos-servicio')
def terminos_servicio():
    return render_template('terminos_servicio.html')

@app.route('/politica-privacidad')
def politica_privacidad():
    return render_template('politica_privacidad.html')


# --- RUTAS DE POLÍTICAS Y LEGALES ---

@app.route('/politica-devoluciones')
def politica_devoluciones():
    return render_template('politica_devoluciones.html')

@app.route('/politica-garantias')
def politica_garantias():
    return render_template('politica_garantias.html')

@app.route('/tratamiento-datos')
def tratamiento_datos():
    return render_template('tratamiento_datos.html')

@app.route('/politica-cookies')
def politica_cookies():
    return render_template('politica_cookies.html')

@app.route('/entreno')
@login_required
def entreno():
    dias_semana = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    dia_seleccionado = request.args.get('dia', dias_semana[datetime.today().weekday()])
    
    rol_usuario = session.get('role', 'cliente')
    tiene_premium_db = verificar_premium(session['user_id'])

    ve_contenido_premium = (rol_usuario == 'admin' or tiene_premium_db)
    tipo_cuenta = 'admin' if rol_usuario == 'admin' else ('premium' if tiene_premium_db else 'free')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if ve_contenido_premium:
        query = """
            SELECT r.*, e.nombre, e.descripcion, e.categoria, e.dificultad
            FROM rutinas_entrenamiento r
            JOIN ejercicios e ON r.ejercicio_id = e.id
            WHERE r.dia_semana = %s
        """
        cursor.execute(query, (dia_seleccionado,))
    else:
        query = """
            SELECT r.*, e.nombre, e.descripcion, e.categoria, e.dificultad
            FROM rutinas_entrenamiento r
            JOIN ejercicios e ON r.ejercicio_id = e.id
            WHERE r.dia_semana = %s AND r.tipo_usuario = 'free'
        """
        cursor.execute(query, (dia_seleccionado,))

    rutinas = cursor.fetchall()
    cursor.close()
    conn.close()

    tiempo_total = sum(r['duracion_minutos'] for r in rutinas) if rutinas else 0
    calorias_totales = sum(r['calorias_estimadas'] for r in rutinas) if rutinas else 0

    return render_template(
        'entreno.html',
        dia=dia_seleccionado,
        tipo_cuenta=tipo_cuenta,
        rutinas=rutinas,
        tiempo_total=tiempo_total,
        calorias_totales=calorias_totales
    )

@app.route('/matchmaking')
@login_required
@not_banned_required
def matchmaking():
    if session.get('role') == 'admin' or session.get('role') == 'profesor' or verificar_premium(session['user_id']):
        canchas = []
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute("SELECT id, nombre FROM locaciones WHERE LOWER(TRIM(tipo)) = 'cancha' ORDER BY nombre")
                canchas = cursor.fetchall()
            finally:
                cursor.close()
                conn.close()
        return render_template('matchmaking.html', canchas=canchas)
    flash("Para acceder a Matchmaking necesitas una cuenta Premium.", "warning")
    return redirect(url_for('premium'))

@app.route('/chatbot')
@login_required
def chatbot_page():
    return render_template('chatbot.html')

@app.route('/api/reservas/disponibilidad')
@login_required
@not_banned_required
def disponibilidad_reservas():
    fecha = request.args.get('fecha')
    if not fecha:
        return jsonify({'error': 'Selecciona una fecha.'}), 400
    horarios = [f'{hour:02d}:00' for hour in range(6, 22)]
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'No se pudo conectar a la base de datos.'}), 503
    cursor = conn.cursor(dictionary=True)
    try:
        asegurar_columna_hora_fin(conn)
        asegurar_columna_usuario_reserva(conn)
        cursor.execute("SELECT id, nombre, direccion FROM locaciones WHERE tipo = 'cancha' ORDER BY nombre")
        canchas = cursor.fetchall()
        cursor.execute('''
                 SELECT locacion_id,
                     MIN(id) AS id,
                     TIME_FORMAT(hora_reserva, CONCAT(CHAR(37), 'H:', CHAR(37), 'i')) AS hora_reserva,
                     TIME_FORMAT(COALESCE(hora_fin, ADDTIME(hora_reserva, '01:00:00')), CONCAT(CHAR(37), 'H:', CHAR(37), 'i')) AS hora_fin
            FROM reservas WHERE fecha_reserva = %s
            GROUP BY locacion_id, fecha_reserva, hora_reserva, hora_fin
        ''', (fecha,))
        reservas_por_cancha = {}
        for reserva in cursor.fetchall():
            reservas_por_cancha.setdefault(reserva['locacion_id'], []).append(reserva)
        for cancha in canchas:
            cancha['reservas'] = reservas_por_cancha.get(cancha['id'], [])
        cursor.execute('SELECT nombre_completo, username FROM usuarios WHERE id = %s', (session['user_id'],))
        usuario = cursor.fetchone() or {}
        mis_reservas = []
        cursor.execute('''
                SELECT r.id, r.nombre_usuario, r.fecha_reserva, r.hora_reserva, r.hora_fin,
                       l.nombre AS nombre_cancha, l.direccion
                FROM reservas r JOIN locaciones l ON l.id = r.locacion_id
                WHERE r.user_id = %s AND r.fecha_reserva >= CURDATE()
                ORDER BY r.fecha_reserva, r.hora_reserva
            ''', (session['user_id'],))
        mis_reservas = cursor.fetchall()
        for reserva in mis_reservas:
            for campo in ('hora_reserva', 'hora_fin'):
                valor = reserva.get(campo)
                if hasattr(valor, 'total_seconds'):
                    total_seconds = int(valor.total_seconds())
                    horas, resto = divmod(total_seconds, 3600)
                    minutos = resto // 60
                    reserva[campo] = f'{horas:02d}:{minutos:02d}'
                elif valor is not None:
                    reserva[campo] = str(valor)[:5]
        return jsonify({'fecha': fecha, 'horarios': horarios, 'canchas': canchas, 'mis_reservas': mis_reservas})
    finally:
        cursor.close()
        conn.close()

@app.route('/api/reservas', methods=['POST'])
@login_required
@not_banned_required
def crear_reserva_api():
    data = request.json or {}
    locacion_id = data.get('locacion_id')
    fecha = data.get('fecha_reserva')
    hora = data.get('hora_reserva')
    hora_fin = data.get('hora_fin')
    if not locacion_id or not fecha or not hora or not hora_fin:
        return jsonify({'error': 'Faltan datos de la reserva.'}), 400
    try:
        locacion_id = int(locacion_id)
        datetime.strptime(fecha, '%Y-%m-%d')
        inicio = datetime.strptime(hora, '%H:%M') if len(hora) == 5 else datetime.strptime(hora, '%H:%M:%S')
        final = datetime.strptime(hora_fin, '%H:%M') if len(hora_fin) == 5 else datetime.strptime(hora_fin, '%H:%M:%S')
    except (TypeError, ValueError):
        return jsonify({'error': 'La fecha o el horario no tienen un formato valido.'}), 400
    duracion = (final - inicio).total_seconds() / 3600
    if duracion not in (1, 2):
        return jsonify({'error': 'La reserva debe durar exactamente 1 o 2 horas.'}), 400
    if inicio.hour < 6 or final.hour > 22:
        return jsonify({'error': 'Las reservas solo están disponibles entre las 06:00 y las 22:00.'}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'No se pudo conectar a la base de datos.'}), 503
    cursor = conn.cursor(dictionary=True)
    try:
        asegurar_columna_hora_fin(conn)
        asegurar_columna_usuario_reserva(conn)
        cursor.execute('SELECT nombre_completo, username FROM usuarios WHERE id = %s', (session['user_id'],))
        usuario = cursor.fetchone()
        cursor.execute('SELECT COUNT(*) AS total FROM reservas WHERE user_id = %s AND fecha_reserva >= CURDATE()', (session['user_id'],))
        if cursor.fetchone()['total'] >= 2:
            return jsonify({'error': 'Cada usuario puede tener como máximo 2 reservas activas.'}), 409
        cursor.execute('''
            SELECT id FROM reservas
            WHERE locacion_id = %s AND fecha_reserva = %s
              AND hora_reserva < %s AND COALESCE(hora_fin, ADDTIME(hora_reserva, '01:00:00')) > %s
        ''', (locacion_id, fecha, hora_fin, hora))
        if cursor.fetchone():
            return jsonify({'error': 'Ese horario ya está reservado.'}), 409
        nombre_usuario = (usuario.get('nombre_completo') or usuario.get('username')) if usuario else session.get('username', 'Usuario')
        cursor.execute('INSERT INTO reservas (locacion_id, user_id, nombre_usuario, fecha_reserva, hora_reserva, hora_fin) VALUES (%s, %s, %s, %s, %s, %s)', (locacion_id, session['user_id'], nombre_usuario or 'Usuario', fecha, hora, hora_fin))
        conn.commit()
        return jsonify({'status': 'success', 'reserva_id': cursor.lastrowid})
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error guardando reserva: {err}')
        return jsonify({'error': 'No se pudo guardar la reserva. Verifica que la tabla reservas tenga la columna hora_fin.'}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/api/reservas/<int:reserva_id>', methods=['DELETE'])
@login_required
@not_banned_required
def eliminar_reserva(reserva_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'No se pudo conectar a la base de datos.'}), 503
    cursor = conn.cursor()
    try:
        asegurar_columna_usuario_reserva(conn)
        cursor.execute('DELETE FROM reservas WHERE id = %s AND user_id = %s', (reserva_id, session['user_id']))
        if cursor.rowcount == 0:
            conn.rollback()
            return jsonify({'error': 'La reserva no existe o no pertenece a tu cuenta.'}), 404
        conn.commit()
        return jsonify({'status': 'success'})
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error eliminando reserva: {err}')
        return jsonify({'error': 'No se pudo eliminar la reserva.'}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/reservas')
@login_required
@not_banned_required
def reservas():
    if session.get('role') == 'admin' or verificar_premium(session['user_id']):
        return render_template('reservas.html')
    flash("Para acceder a Reservas necesitas una cuenta Premium.", "warning")
    return redirect(url_for('premium'))


# ═══════════════════════════════════════════════════════════════════════════
# RUTAS ADMIN
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/admin/torneos', methods=['GET', 'POST'])
@admin_required
def admin_torneos():
    """CRUD de los bloques informativos y del calendario de torneos."""
    search = request.args.get('q', '').strip()[:120]
    conn = get_db_connection()
    if not conn:
        flash('No fue posible conectar con la base de datos.', 'error')
        return redirect(url_for('index'))

    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == 'POST':
            accion = request.form.get('accion')
            registro_id = request.form.get('id', type=int)

            if accion == 'guardar_bloque':
                datos = (request.form.get('tipo', '').strip(), request.form.get('titulo', '').strip(),
                         request.form.get('texto', '').strip(), request.form.get('orden', type=int) or 0)
                if not all(datos[:3]):
                    flash('Completa todos los campos del bloque.', 'error')
                elif registro_id:
                    cursor.execute('UPDATE contenido_torneos SET tipo = %s, titulo = %s, texto = %s, orden = %s WHERE id = %s', (*datos, registro_id))
                    conn.commit()
                    flash('Bloque actualizado correctamente.', 'success')
                else:
                    cursor.execute('INSERT INTO contenido_torneos (tipo, titulo, texto, orden) VALUES (%s, %s, %s, %s)', datos)
                    conn.commit()
                    flash('Bloque creado correctamente.', 'success')
            elif accion == 'eliminar_bloque' and registro_id:
                cursor.execute('DELETE FROM contenido_torneos WHERE id = %s', (registro_id,))
                conn.commit()
                flash('Bloque eliminado.', 'success')
            elif accion == 'guardar_torneo':
                datos = (request.form.get('nombre', '').strip(), request.form.get('categoria', '').strip(),
                         request.form.get('fecha', '').strip(), request.form.get('lugar', '').strip(),
                         request.form.get('nivel', '').strip(), request.form.get('descripcion', '').strip())
                if not all(datos):
                    flash('Completa todos los datos del torneo.', 'error')
                elif registro_id:
                    cursor.execute('''UPDATE torneos SET nombre = %s, categoria = %s, fecha = %s,
                                      lugar = %s, nivel = %s, descripcion = %s WHERE id = %s''', (*datos, registro_id))
                    conn.commit()
                    flash('Torneo actualizado correctamente.', 'success')
                else:
                    cursor.execute('''INSERT INTO torneos (nombre, categoria, fecha, lugar, nivel, descripcion)
                                      VALUES (%s, %s, %s, %s, %s, %s)''', datos)
                    conn.commit()
                    flash('Torneo creado correctamente.', 'success')
            elif accion == 'eliminar_torneo' and registro_id:
                cursor.execute('DELETE FROM torneos WHERE id = %s', (registro_id,))
                conn.commit()
                flash('Torneo eliminado.', 'success')

            return redirect(url_for('admin_torneos'))

        pattern = f'%{search}%'
        contents_sql = 'SELECT id, tipo, titulo, texto, orden FROM contenido_torneos'
        tournament_sql = 'SELECT id, nombre, categoria, fecha, lugar, nivel, descripcion FROM torneos'
        if search:
            contents_sql += ' WHERE tipo LIKE %s OR titulo LIKE %s OR texto LIKE %s'
            tournament_sql += ' WHERE CAST(id AS CHAR) LIKE %s OR nombre LIKE %s OR categoria LIKE %s OR fecha LIKE %s OR lugar LIKE %s OR nivel LIKE %s OR descripcion LIKE %s'
            cursor.execute(contents_sql + ' ORDER BY orden, id', (pattern, pattern, pattern))
        else:
            cursor.execute(contents_sql + ' ORDER BY orden, id')
        contenidos = cursor.fetchall()
        if search:
            cursor.execute(tournament_sql + ' ORDER BY orden, id', (pattern,) * 7)
        else:
            cursor.execute(tournament_sql + ' ORDER BY orden, id')
        torneos = cursor.fetchall()
        return render_template('admin/torneos.html', contenidos=contenidos, torneos=torneos, search=search)
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error administrando torneos: {err}')
        flash('No fue posible guardar los cambios. Verifica que ejecutaste informacion_extra.sql.', 'error')
        return redirect(url_for('admin_torneos'))
    finally:
        cursor.close()
        conn.close()


@app.route('/admin/denuncias', methods=['GET', 'POST'])
@admin_required
def admin_denuncias():
    search = request.form.get('q', '') if request.method == 'POST' else request.args.get('q', '')
    search = search.strip()[:120]
    conn = get_db_connection()
    if not conn:
        flash('No fue posible cargar las denuncias.', 'error')
        return redirect(url_for('index'))
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == 'POST':
            denuncia_id = request.form.get('denuncia_id')
            accion = request.form.get('accion')
            cursor.execute('SELECT denunciado_id FROM denuncias_mensajes WHERE id = %s', (denuncia_id,))
            denuncia = cursor.fetchone()
            if denuncia and accion == 'banear':
                cursor.execute('''
                    UPDATE usuarios SET baneado = 1, motivo_baneo = %s, evidencia_baneo = %s, fecha_baneo = NOW()
                    WHERE id = %s
                ''', ('Denuncia de mensaje revisada por administración.', f'Denuncia #{denuncia_id}', denuncia['denunciado_id']))
                cursor.execute("""
                    UPDATE denuncias_mensajes SET estado = 'revisada'
                    WHERE denunciado_id = %s AND estado = 'pendiente'
                """, (denuncia['denunciado_id'],))
                flash('Se confirmó el bloqueo y las denuncias pendientes quedaron revisadas.', 'success')
            elif denuncia and accion == 'descartar':
                cursor.execute("UPDATE denuncias_mensajes SET estado = 'descartada' WHERE id = %s", (denuncia_id,))
                flash('La denuncia fue descartada.', 'info')
            elif denuncia and accion == 'liberar':
                cursor.execute('''
                    UPDATE usuarios
                    SET baneado = 0, motivo_baneo = NULL, evidencia_baneo = NULL,
                        locacion_baneo = NULL, fecha_baneo = NULL
                    WHERE id = %s
                ''', (denuncia['denunciado_id'],))
                cursor.execute("""
                    UPDATE denuncias_mensajes SET estado = 'descartada'
                    WHERE denunciado_id = %s AND estado = 'pendiente'
                """, (denuncia['denunciado_id'],))
                flash('El usuario fue liberado y sus denuncias pendientes se descartaron.', 'success')
            conn.commit()
        query = '''
            SELECT d.*, m.texto, u1.username AS denunciante, u2.username AS denunciado,
                   u2.baneado AS denunciado_baneado, u2.motivo_baneo
            FROM denuncias_mensajes d
            JOIN messages m ON m.id = d.mensaje_id
            JOIN usuarios u1 ON u1.id = d.denunciante_id
            JOIN usuarios u2 ON u2.id = d.denunciado_id
        '''
        parameters = []
        if search:
            query += """ WHERE (CAST(d.id AS CHAR) LIKE %s OR d.estado LIKE %s
                         OR m.texto LIKE %s OR u1.username LIKE %s OR u2.username LIKE %s)"""
            parameters = [f'%{search}%'] * 5
        cursor.execute(query + ' ORDER BY d.fecha_denuncia DESC', parameters)
        return render_template('admin/denuncias.html', denuncias=cursor.fetchall(), search=search)
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error cargando denuncias: {err}')
        flash('No fue posible cargar las denuncias.', 'error')
        return redirect(url_for('index'))
    finally:
        cursor.close()
        conn.close()

ADMIN_CRUDS = {
    'categorias': {
        'title': 'Categorías de tienda', 'table': 'categorias',
        'bounds': {'orden': (0, None)},
        'fields': [
            ('nombre', 'Nombre', 'text', True), ('slug', 'Slug', 'text', True),
            ('descripcion', 'Descripción', 'textarea', False), ('icono', 'Icono', 'text', False),
            ('orden', 'Orden', 'number', False), ('activo', 'Activo', 'checkbox', False),
        ],
        'columns': ['id', 'nombre', 'slug', 'orden', 'activo'],
    },
    'ejercicios': {
        'title': 'Ejercicios', 'table': 'ejercicios',
        'fields': [
            ('nombre', 'Nombre', 'text', True), ('descripcion', 'Descripción', 'textarea', False),
            ('categoria', 'Categoría', 'text', False),
            ('dificultad', 'Dificultad', 'select:Principiante|Intermedio|Avanzado|Élite', False),
        ],
        'columns': ['id', 'nombre', 'categoria', 'dificultad'],
    },
    'rutinas': {
        'title': 'Rutinas de entrenamiento', 'table': 'rutinas_entrenamiento',
        'bounds': {'duracion_minutos': (0, None), 'calorias_estimadas': (0, None)},
        'fields': [
            ('dia_semana', 'Día', 'select:Lunes|Martes|Miércoles|Jueves|Viernes|Sábado|Domingo', True),
            ('tipo_usuario', 'Tipo de usuario', 'select:free|premium', True),
            ('titulo_rutina', 'Título', 'text', True), ('objetivo', 'Objetivo', 'textarea', True),
            ('consejo_entrenador', 'Consejo', 'textarea', False), ('ejercicio_id', 'Ejercicio', 'integer', False),
            ('series_repeticiones', 'Series / repeticiones', 'text', False),
            ('duracion_minutos', 'Duración (minutos)', 'integer', False),
            ('calorias_estimadas', 'Calorías', 'integer', False), ('imagen_url', 'Imagen', 'url', False),
        ],
        'columns': ['id', 'dia_semana', 'tipo_usuario', 'titulo_rutina', 'duracion_minutos'],
        'lookups': {'ejercicio_id': ('ejercicios', 'id', 'nombre')},
    },
    'locaciones': {
        'title': 'Ubicaciones del mapa', 'table': 'locaciones',
        'bounds': {'lat': (-90, 90), 'lng': (-180, 180)},
        'fields': [
            ('nombre', 'Nombre', 'text', True), ('tipo', 'Tipo', 'select:cancha|tienda|bar|restaurante|club', True),
            ('lat', 'Latitud', 'decimal', True), ('lng', 'Longitud', 'decimal', True),
            ('estrellas', 'Estrellas', 'text', False), ('direccion', 'Dirección', 'text', True),
            ('horario', 'Horario', 'text', True), ('telefono', 'Teléfono', 'text', True),
            ('precio_aprox', 'Precio aproximado', 'text', True), ('info_adicional', 'Información', 'textarea', True),
            ('imagen_url', 'Imagen (URL)', 'url', False),
        ],
        'columns': ['id', 'nombre', 'tipo', 'direccion', 'telefono', 'imagen_url'],
    },
    'reservas': {
        'title': 'Reservas de canchas', 'table': 'reservas',
        'fields': [
            ('locacion_id', 'Ubicación', 'integer', True), ('user_id', 'Cuenta de usuario', 'integer', False),
            ('nombre_usuario', 'Nombre del usuario', 'text', True),
            ('fecha_reserva', 'Fecha', 'date', True), ('hora_reserva', 'Hora de inicio', 'time', True),
            ('hora_fin', 'Hora de finalización', 'time', False),
        ],
        'columns': ['id', 'locacion_id', 'nombre_usuario', 'fecha_reserva', 'hora_reserva'],
        'column_labels': {'locacion_id': 'Ubicación'},
        'lookups': {
            'locacion_id': ('locaciones', 'id', 'nombre'),
            'user_id': ('usuarios', 'id', 'username'),
        },
    },
    'premium': {
        'title': 'Suscripciones Premium', 'table': 'premium',
        'fields': [('user_id', 'Cuenta de usuario', 'integer', True), ('plan', 'Plan', 'text', True)],
        'columns': ['id', 'user_id', 'plan', 'fecha_inicio'],
        'column_labels': {'user_id': 'Cuenta de usuario'},
        'lookups': {'user_id': ('usuarios', 'id', 'username')},
    },
    'resenas': {
        'title': 'Reseñas y calificaciones de productos', 'table': 'producto_valoraciones',
        'bounds': {'calificacion': (1, 5)},
        'fields': [
            ('producto_id', 'Producto', 'integer', True), ('usuario_id', 'Cuenta de usuario', 'integer', True),
            ('calificacion', 'Calificación (1-5)', 'integer', True),
        ],
        'columns': ['id', 'producto_id', 'usuario_id', 'calificacion', 'valoracion_promedio', 'total_valoraciones_producto', 'fecha'],
        'column_labels': {
            'producto_id': 'Producto', 'usuario_id': 'Cliente',
            'valoracion_promedio': 'Promedio del producto',
            'total_valoraciones_producto': 'Reseñas del producto',
        },
        'order_by': 'valoracion_promedio DESC, total_valoraciones_producto DESC, base.id DESC',
        'lookups': {
            'producto_id': ('productos', 'id', 'nombre'),
            'usuario_id': ('usuarios', 'id', 'username'),
        },
    },
    'favoritos': {
        'title': 'Favoritos', 'table': 'favoritos',
        'fields': [('usuario_id', 'Cuenta de usuario', 'integer', True), ('producto_id', 'Producto', 'integer', True)],
        'columns': ['id', 'usuario_id', 'producto_id', 'valoracion_promedio', 'total_valoraciones_producto', 'created_at'],
        'column_labels': {
            'usuario_id': 'Cliente', 'producto_id': 'Producto',
            'valoracion_promedio': 'Promedio del producto',
            'total_valoraciones_producto': 'Reseñas del producto',
        },
        'order_by': 'valoracion_promedio DESC, total_valoraciones_producto DESC, base.created_at DESC',
        'lookups': {
            'usuario_id': ('usuarios', 'id', 'username'),
            'producto_id': ('productos', 'id', 'nombre'),
        },
    },
    'pagos': {
        'title': 'Pagos', 'table': 'pagos',
        'bounds': {'monto': (0, None)},
        'fields': [
            ('orden_id', 'Orden', 'integer', False), ('usuario_id', 'Cuenta de usuario', 'integer', True),
            ('monto', 'Monto', 'decimal', True),
            ('metodo', 'Método', 'select:tarjeta|transferencia|efecty|nequi|daviplata|paypal', True),
            ('estado', 'Estado', 'select:pendiente|completado|fallido|reembolsado', True),
            ('referencia_pago', 'Referencia', 'text', False),
        ],
        'columns': ['id', 'orden_id', 'usuario_id', 'monto', 'metodo', 'estado', 'created_at'],
        'column_labels': {'orden_id': 'Orden', 'usuario_id': 'Cliente'},
        'lookups': {
            'orden_id': ('ordenes', 'id', 'numero_orden'),
            'usuario_id': ('usuarios', 'id', 'username'),
        },
    },
    'comentarios': {
        'title': 'Comentarios del mapa', 'table': 'comentarios',
        'bounds': {'estrellas': (1, 5)},
        'fields': [
            ('locacion_id', 'Ubicación', 'integer', True), ('usuario_id', 'Cuenta de usuario', 'integer', False),
            ('nombre_usuario', 'Nombre visible', 'text', True), ('comentario', 'Comentario', 'textarea', True),
            ('estrellas', 'Estrellas (1-5)', 'integer', True),
        ],
        'columns': ['id', 'locacion_id', 'usuario_id', 'nombre_usuario', 'comentario', 'estrellas', 'acuerdo_promedio', 'total_acuerdos'],
        'column_labels': {
            'locacion_id': 'Ubicación', 'usuario_id': 'Cuenta de usuario',
            'acuerdo_promedio': 'Promedio de acuerdos',
            'total_acuerdos': 'Total de acuerdos',
        },
        'order_by': 'acuerdo_promedio DESC, total_acuerdos DESC, id DESC',
        'lookups': {
            'locacion_id': ('locaciones', 'id', 'nombre'),
            'usuario_id': ('usuarios', 'id', 'username'),
        },
    },
    'ordenes': {
        'title': 'Órdenes y envíos', 'table': 'ordenes',
        'bounds': {'subtotal': (0, None), 'envio': (0, None), 'descuento': (0, None), 'total': (0, None)},
        'fields': [
            ('usuario_id', 'Cuenta de usuario', 'integer', True), ('numero_orden', 'Número de orden', 'text', True),
            ('estado', 'Estado', 'select:pendiente|pagado|en_proceso|enviado|entregado|cancelado', True),
            ('subtotal', 'Subtotal', 'decimal', True), ('envio', 'Envío', 'decimal', False),
            ('descuento', 'Descuento', 'decimal', False), ('total', 'Total', 'decimal', True),
            ('direccion_envio', 'Dirección', 'textarea', False), ('ciudad_envio', 'Ciudad', 'text', False),
            ('telefono_envio', 'Teléfono', 'text', False),
        ],
        'columns': ['id', 'numero_orden', 'usuario_id', 'estado', 'total', 'created_at'],
        'column_labels': {'usuario_id': 'Cliente'},
        'lookups': {'usuario_id': ('usuarios', 'id', 'username')},
    },
}


def _crud_config(resource):
    return ADMIN_CRUDS.get(resource)


@app.route('/admin/crud/<resource>', methods=['GET', 'POST'])
@admin_required
def admin_crud(resource):
    config = _crud_config(resource)
    if not config:
        flash('Módulo administrativo no encontrado.', 'error')
        return redirect(url_for('index'))

    conn = get_db_connection()
    if not conn:
        flash('Error de conexión con la base de datos.', 'error')
        return redirect(url_for('index'))
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        if resource in {'resenas', 'favoritos'}:
            asegurar_tabla_valoraciones_producto(conn)
        search_value = request.form.get('q', '') if request.method == 'POST' else request.args.get('q', '')
        page_value = request.form.get('page', default=1, type=int) if request.method == 'POST' else request.args.get('page', default=1, type=int)
        search = search_value.strip()[:120]
        page = max(page_value or 1, 1)
        per_page = 50
        lookup_options = {}
        for field_name, (lookup_table, lookup_id, lookup_label) in config.get('lookups', {}).items():
            cursor.execute(
                f"SELECT {lookup_id} AS option_value, {lookup_label} AS option_label "
                f"FROM {lookup_table} ORDER BY {lookup_label} ASC"
            )
            lookup_options[field_name] = [
                {'value': str(option['option_value']), 'label': f"{option['option_label']} · #{option['option_value']}"}
                for option in cursor.fetchall()
            ]
        form_fields = []
        for field_name, label, field_type, required in config['fields']:
            options = []
            display_type = field_type
            if field_type.startswith('select:'):
                display_type = 'select'
                options = [
                    {'value': option, 'label': option.replace('_', ' ').title()}
                    for option in field_type[7:].split('|')
                ]
            elif field_name in lookup_options:
                display_type = 'select'
                options = lookup_options[field_name]
            form_fields.append({
                'name': field_name,
                'label': label,
                'type': display_type,
                'required': required,
                'options': options,
                'min': config.get('bounds', {}).get(field_name, (None, None))[0],
                'max': config.get('bounds', {}).get(field_name, (None, None))[1],
            })

        if request.method == 'POST':
            record_id_raw = request.form.get('record_id', '').strip()
            if resource in {'resenas', 'favoritos'} and not record_id_raw:
                flash(
                    'Las reseñas y los favoritos se registran desde la actividad real de los clientes.',
                    'warning'
                )
                return redirect(url_for('admin_crud', resource=resource, q=search, page=page))
            try:
                record_id = int(record_id_raw) if record_id_raw else None
                if record_id is not None and record_id < 1:
                    raise ValueError
            except ValueError:
                flash('El registro que intentas editar no es válido.', 'error')
                return redirect(url_for('admin_crud', resource=resource, q=search, page=page))

            values = []
            columns = []
            for field_name, label, field_type, required in config['fields']:
                raw_value = request.form.get(field_name, '').strip()
                value = raw_value
                if field_type == 'checkbox':
                    value = 1 if request.form.get(field_name) in ('1', 'on', 'true') else 0
                elif raw_value == '' and not required:
                    value = None
                elif field_type == 'integer' and raw_value:
                    try:
                        value = int(raw_value)
                    except ValueError:
                        flash(f'El campo «{label}» debe ser un número entero.', 'error')
                        return redirect(url_for('admin_crud', resource=resource, q=search, page=page))
                elif field_type == 'decimal' and raw_value:
                    try:
                        value = Decimal(raw_value)
                        if not value.is_finite():
                            raise InvalidOperation
                    except (InvalidOperation, ValueError):
                        flash(f'El campo «{label}» debe ser un número válido.', 'error')
                        return redirect(url_for('admin_crud', resource=resource, q=search, page=page))
                if required and value in (None, ''):
                    flash(f'Completa el campo obligatorio «{label}».', 'error')
                    return redirect(url_for('admin_crud', resource=resource, q=search, page=page))
                if field_type in ('integer', 'decimal') and value is not None:
                    minimum, maximum = config.get('bounds', {}).get(field_name, (None, None))
                    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
                        flash(f'El campo «{label}» debe estar dentro del rango permitido.', 'error')
                        return redirect(url_for('admin_crud', resource=resource, q=search, page=page))
                if field_type.startswith('select:') and value not in (None, ''):
                    allowed_values = {option['value'] for option in form_fields[len(columns)]['options']}
                    if str(value) not in allowed_values:
                        flash(f'Selecciona una opción válida para «{label}».', 'error')
                        return redirect(url_for('admin_crud', resource=resource, q=search, page=page))
                if field_name in config.get('lookups', {}) and value not in (None, ''):
                    allowed_values = {option['value'] for option in lookup_options[field_name]}
                    if str(value) not in allowed_values:
                        flash(f'Selecciona una relación válida para «{label}».', 'error')
                        return redirect(url_for('admin_crud', resource=resource, q=search, page=page))
                columns.append(field_name)
                values.append(value)

            if record_id:
                cursor.execute(f"SELECT id FROM {config['table']} WHERE id = %s", (record_id,))
                if not cursor.fetchone():
                    flash('El registro que intentas actualizar ya no existe.', 'warning')
                    return redirect(url_for('admin_crud', resource=resource, q=search, page=page))
                assignments = ', '.join(f'{column} = %s' for column in columns)
                cursor.execute(f"UPDATE {config['table']} SET {assignments} WHERE id = %s", (*values, record_id))
                mensaje = 'Registro actualizado correctamente.'
            else:
                placeholders = ', '.join(['%s'] * len(columns))
                cursor.execute(f"INSERT INTO {config['table']} ({', '.join(columns)}) VALUES ({placeholders})", values)
                mensaje = 'Registro creado correctamente.'
            conn.commit()
            flash(mensaje, 'success')
            return redirect(url_for('admin_crud', resource=resource, q=search, page=page))

        base_alias = 'c' if resource == 'comentarios' else 'base'
        lookup_joins = []
        lookup_selects = []
        lookup_searchable = []
        for field_name, (lookup_table, lookup_id, lookup_label) in config.get('lookups', {}).items():
            lookup_alias = f'lookup_{field_name}'
            lookup_joins.append(
                f'LEFT JOIN {lookup_table} {lookup_alias} '
                f'ON {lookup_alias}.{lookup_id} = {base_alias}.{field_name}'
            )
            lookup_selects.append(f'{lookup_alias}.{lookup_label} AS {field_name}_label')
            lookup_searchable.append(f'{lookup_alias}.{lookup_label}')
        lookup_join_sql = ' ' + ' '.join(lookup_joins) if lookup_joins else ''
        searchable = [field[0] for field in config['fields'] if field[2] != 'checkbox']
        where_clause = ''
        search_params = []
        if search:
            where_clause = ' WHERE ' + ' OR '.join(
                [f'CAST({base_alias}.{field} AS CHAR) LIKE %s' for field in searchable]
                + [f'CAST({field} AS CHAR) LIKE %s' for field in lookup_searchable]
            )
            search_params = [f'%{search}%'] * (len(searchable) + len(lookup_searchable))
        from_clause = f"{config['table']} {base_alias}{lookup_join_sql}"
        cursor.execute(
            f"SELECT COUNT(DISTINCT {base_alias}.id) AS total FROM {from_clause}{where_clause}",
            search_params
        )
        total_records = int(cursor.fetchone()['total'])
        total_pages = max((total_records + per_page - 1) // per_page, 1)
        page = min(page, total_pages)
        offset = (page - 1) * per_page
        query = (
            "SELECT c.*, COALESCE(AVG(cv.calificacion), 0) AS acuerdo_promedio, "
            "COUNT(cv.id) AS total_acuerdos "
            + (', ' + ', '.join(lookup_selects) if lookup_selects else '')
            + f" FROM comentarios c LEFT JOIN comentarios_valoraciones cv ON cv.comentario_id = c.id"
            + lookup_join_sql + where_clause
            if resource == 'comentarios' else
            f"SELECT base.*{', ' + ', '.join(lookup_selects) if lookup_selects else ''}"
            + (
                ", COALESCE((SELECT AVG(pv.calificacion) FROM producto_valoraciones pv "
                "WHERE pv.producto_id = base.producto_id), 0) AS valoracion_promedio, "
                "(SELECT COUNT(*) FROM producto_valoraciones pv "
                "WHERE pv.producto_id = base.producto_id) AS total_valoraciones_producto"
                if resource in {'resenas', 'favoritos'} else ''
            )
            + f" FROM {config['table']} base{lookup_join_sql}{where_clause}"
        )
        if resource == 'comentarios':
            group_columns = ['c.id'] + [
                f'lookup_{field_name}.{lookup[2]}'
                for field_name, lookup in config.get('lookups', {}).items()
            ]
            query += ' GROUP BY ' + ', '.join(group_columns) + ' ORDER BY acuerdo_promedio DESC, total_acuerdos DESC, c.id DESC'
        else:
            query += ' ORDER BY ' + config.get('order_by', f'{base_alias}.id DESC')
        cursor.execute(query + ' LIMIT %s OFFSET %s', (*search_params, per_page, offset))
        records = cursor.fetchall()
        edit_id = request.args.get('edit', type=int)
        record = None
        if edit_id:
            cursor.execute(f"SELECT * FROM {config['table']} WHERE id = %s", (edit_id,))
            record = cursor.fetchone()
            if not record:
                flash('El registro que intentas editar ya no existe.', 'warning')
                return redirect(url_for('admin_crud', resource=resource, q=search, page=page))
        return render_template(
            'admin/crud.html',
            config=config,
            records=records,
            record=record,
            search=search,
            resource=resource,
            form_fields=form_fields,
            boolean_fields=[field[0] for field in config['fields'] if field[2] == 'checkbox'],
            page=page,
            total_pages=total_pages,
            total_records=total_records,
        )
    except (sqlite3.Error, InvalidOperation) as err:
        conn.rollback()
        print(f'Error CRUD {resource}: {err}')
        flash('No se pudo completar el cambio. Revisa los datos y las relaciones del registro.', 'error')
        return redirect(url_for('admin_crud', resource=resource, q=search, page=page))
    finally:
        if cursor:
            cursor.close()
        conn.close()


@app.post('/admin/crud/<resource>/eliminar/<int:record_id>')
@admin_required
def admin_crud_eliminar(resource, record_id):
    config = _crud_config(resource)
    if not config:
        flash('Módulo administrativo no encontrado.', 'error')
        return redirect(url_for('index'))
    conn = get_db_connection()
    if not conn:
        flash('Error de conexión con la base de datos.', 'error')
        return redirect(url_for('index'))
    cursor = None
    search = request.form.get('q', '').strip()[:120]
    page = max(request.form.get('page', default=1, type=int) or 1, 1)
    try:
        cursor = conn.cursor()
        if resource == 'categorias':
            cursor.execute('SELECT id FROM productos WHERE categoria_id = %s LIMIT 1', (record_id,))
            if cursor.fetchone():
                flash('No puedes eliminar esta categoría porque tiene productos asociados. Reasigna primero esos productos.', 'warning')
                return redirect(url_for('admin_crud', resource=resource, q=search, page=page))
        elif resource == 'ejercicios':
            cursor.execute('SELECT id FROM rutinas_entrenamiento WHERE ejercicio_id = %s LIMIT 1', (record_id,))
            if cursor.fetchone():
                flash('No puedes eliminar este ejercicio porque está asociado a una rutina.', 'warning')
                return redirect(url_for('admin_crud', resource=resource, q=search, page=page))
        elif resource == 'locaciones':
            cursor.execute('SELECT id FROM reservas WHERE locacion_id = %s LIMIT 1', (record_id,))
            tiene_reservas = cursor.fetchone()
            cursor.execute('SELECT id FROM comentarios WHERE locacion_id = %s LIMIT 1', (record_id,))
            tiene_comentarios = cursor.fetchone()
            if tiene_reservas or tiene_comentarios:
                flash('No puedes eliminar esta ubicación porque tiene reservas o comentarios asociados.', 'warning')
                return redirect(url_for('admin_crud', resource=resource, q=search, page=page))
        cursor.execute(f"DELETE FROM {config['table']} WHERE id = %s", (record_id,))
        if not cursor.rowcount:
            flash('El registro ya no existe o ya fue eliminado.', 'warning')
            return redirect(url_for('admin_crud', resource=resource, q=search, page=page))
        conn.commit()
        flash('Registro eliminado correctamente.', 'success')
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error eliminando {resource}: {err}')
        flash('No se puede eliminar este registro porque está relacionado con otros datos.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()
    return redirect(url_for('admin_crud', resource=resource, q=search, page=page))

@app.route('/apelar-baneo', methods=['GET', 'POST'])
def apelar_baneo():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        motivo = request.form.get('motivo', '').strip()
        if not email or not motivo:
            flash('Completa tu correo y explica el motivo de la apelación.', 'error')
            return redirect(url_for('apelar_baneo'))

        conn = get_db_connection()
        if conn is None:
            flash('No fue posible enviar la apelación.', 'error')
            return redirect(url_for('apelar_baneo'))
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT id, baneado, evidencia_baneo, locacion_baneo
                FROM usuarios WHERE email = %s
            """, (email,))
            usuario = cursor.fetchone()
            if not usuario or not usuario['baneado']:
                flash('No encontramos un bloqueo activo para ese correo.', 'warning')
                return redirect(url_for('apelar_baneo'))
            cursor.execute("""
                INSERT INTO apelaciones_baneo
                    (usuario_id, correo, motivo, evidencia_comentario, locacion_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (usuario['id'], email, motivo, usuario.get('evidencia_baneo'), usuario.get('locacion_baneo')))
            conn.commit()
            flash('Tu apelación fue enviada para revisión administrativa.', 'success')
            return redirect(url_for('apelar_baneo'))
        except sqlite3.Error as err:
            conn.rollback()
            print(f"Error guardando apelación: {err}")
            flash('No fue posible enviar la apelación.', 'error')
        finally:
            if cursor:
                cursor.close()
            conn.close()
    return render_template('apelar_baneo.html')


@app.route('/admin/apelaciones', methods=['GET', 'POST'])
@admin_required
def admin_apelaciones():
    search = request.form.get('q', '') if request.method == 'POST' else request.args.get('q', '')
    search = search.strip()[:120]
    conn = get_db_connection()
    if conn is None:
        flash('Error de conexión con la base de datos.', 'error')
        return redirect(url_for('index'))
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        if request.method == 'POST':
            apelacion_id = request.form.get('apelacion_id')
            decision = request.form.get('decision')
            cursor.execute("SELECT usuario_id FROM apelaciones_baneo WHERE id = %s", (apelacion_id,))
            apelacion = cursor.fetchone()
            if apelacion and decision in ('aprobar', 'rechazar'):
                estado = 'aprobada' if decision == 'aprobar' else 'rechazada'
                if decision == 'aprobar':
                    cursor.execute("UPDATE usuarios SET baneado = 0, motivo_baneo = NULL, fecha_baneo = NULL WHERE id = %s", (apelacion['usuario_id'],))
                decision_texto = (
                    'Tu apelación fue aprobada. Tu cuenta ha sido desbloqueada y puedes volver a utilizar los servicios.'
                    if decision == 'aprobar' else
                    'Tu apelación fue rechazada. El bloqueo se mantiene porque la evidencia fue considerada suficiente.'
                )
                cursor.execute("""
                    INSERT INTO notificaciones_moderacion
                        (usuario_id, apelacion_id, titulo, apelacion, respuesta, evidencia)
                    SELECT usuario_id, id, %s, motivo, %s, evidencia_comentario
                    FROM apelaciones_baneo WHERE id = %s
                """, ('Resultado de apelación', decision_texto, apelacion_id))
                cursor.execute("""
                    UPDATE apelaciones_baneo
                    SET estado = %s, revisado_por = %s, fecha_revision = NOW()
                    WHERE id = %s
                """, (estado, session['user_id'], apelacion_id))
                conn.commit()
                flash('Apelación procesada correctamente.', 'success')
            return redirect(url_for('admin_apelaciones', q=search))

        query = """
            SELECT a.*, u.username, u.email AS usuario_email, u.motivo_baneo
            FROM apelaciones_baneo a
            JOIN usuarios u ON u.id = a.usuario_id
            WHERE a.estado = 'pendiente'
        """
        parameters = []
        if search:
            query += """ AND (CAST(a.id AS CHAR) LIKE %s OR a.motivo LIKE %s
                         OR a.evidencia_comentario LIKE %s OR u.username LIKE %s OR u.email LIKE %s)"""
            parameters = [f'%{search}%'] * 5
        cursor.execute(query + ' ORDER BY a.fecha_envio ASC', parameters)
        apelaciones = cursor.fetchall()
        return render_template('admin/apelaciones.html', apelaciones=apelaciones, search=search)
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error cargando apelaciones: {err}')
        flash('No fue posible cargar las apelaciones.', 'error')
        return redirect(url_for('index'))
    finally:
        if cursor:
            cursor.close()
        conn.close()

@app.route('/admin/perfiles', methods=['GET', 'POST'])
@admin_required
def admin_perfiles():
    conn = get_db_connection()
    if conn is None:
        flash("Error de conexión con la base de datos.", "error")
        return redirect(url_for('index'))

    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)

        if request.method == "POST":
            action = request.form.get("action")

            if action == "eliminar":
                usuario_id = request.form.get("usuario_id")
                try:
                    if int(usuario_id) == session['user_id']:
                        flash("No puedes eliminar tu propia cuenta.", "error")
                    else:
                        tiene_historial = False
                        for tabla in ('ordenes', 'pagos', 'facturas'):
                            cursor.execute(f"SELECT id FROM {tabla} WHERE usuario_id = %s LIMIT 1", (usuario_id,))
                            if cursor.fetchone():
                                tiene_historial = True
                                break
                        if tiene_historial:
                            flash("No puedes eliminar una cuenta con historial de órdenes, pagos o facturas.", "warning")
                        else:
                            cursor.execute("DELETE FROM usuarios WHERE id=%s", (usuario_id,))
                            if cursor.rowcount:
                                conn.commit()
                                flash("Usuario eliminado correctamente.", "success")
                            else:
                                flash("El usuario ya no existe.", "warning")
                except (ValueError, TypeError):
                    flash("ID de usuario inválido.", "error")

            return redirect(url_for('admin_perfiles'))

        # Consulta con LEFT JOIN para traer los datos de ambas tablas
        cursor.execute("""
            SELECT 
                u.id, u.username, u.email, u.telefono, u.rol, u.fecha_creacion,
                p.apellido, p.foto, p.nivel, p.club
            FROM usuarios u
            LEFT JOIN perfil_usuario p ON u.id = p.usuario_id
            ORDER BY u.id DESC
        """)
        usuarios = cursor.fetchall()
        for usuario in usuarios:
            usuario['foto'] = foto_perfil_url(usuario.get('foto'))
        return render_template('admin/perfiles.html', usuarios=usuarios)

    except sqlite3.Error as err:
        if conn:
            conn.rollback()
        print(f"Error de base de datos: {err}")
        flash("Error al cargar los perfiles.", "error")
        return redirect(url_for('index'))
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@app.route('/admin/actualizar_eliminar_perfil/<int:id>', methods=['GET', 'POST'])
@admin_required
def admin_actualizar_usuario(id):
    conn = get_db_connection()
    if conn is None:
        flash("Error de conexión con la base de datos.", "error")
        return redirect(url_for('admin_perfiles'))

    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)

        if request.method == "POST":
            # 1. Recibir datos de la tabla 'usuarios'
            username = request.form.get("username", '').strip()
            email = request.form.get("email", '').strip()
            telefono = request.form.get("telefono", '').strip()
            rol = request.form.get("rol")
            password = request.form.get("password", '')
            allowed_roles = {'admin', 'cliente', 'visita', 'premium', 'jugador', 'profesor', 'tienda'}
            if not username or not email or rol not in allowed_roles:
                flash("Completa usuario y correo, y selecciona un rol válido.", "error")
                return redirect(url_for('admin_actualizar_usuario', id=id))

            # 2. Recibir datos de la tabla 'perfil_usuario'
            apellido = request.form.get("apellido", '').strip() or None
            fecha_nacimiento = request.form.get("fecha_nacimiento") or None
            nivel = request.form.get("nivel", 'principiante')
            mano = request.form.get("mano", 'diestro')
            reves = request.form.get("reves", 'dos_manos')
            club = request.form.get("club", '').strip() or None
            biografia = request.form.get("biografia", '').strip() or None

            # 3. Procesar la subida de la nueva foto de perfil
            foto_nombre = None
            if 'foto_perfil' in request.files:
                file = request.files['foto_perfil']
                if file and file.filename:
                    if not perfil_image_valida(file):
                        flash("La foto debe ser PNG, JPG, GIF o WEBP válida y pesar menos de 5 MB.", "error")
                        return redirect(url_for('admin_actualizar_usuario', id=id))
                    ext = os.path.splitext(secure_filename(file.filename))[1].lower()
                    foto_nombre = f"user_{id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}{ext}"
                    folder = current_app.config['UPLOAD_FOLDER']
                    os.makedirs(folder, exist_ok=True)
                    
                    ruta_guardado = os.path.join(folder, foto_nombre)
                    file.save(ruta_guardado)

            # 4. Actualizar la tabla 'usuarios' (con o sin cambio de contraseña)
            if password:
                password_hash = generate_password_hash(password)
                cursor.execute("""
                    UPDATE usuarios 
                    SET username=%s, email=%s, telefono=%s, password=%s, rol=%s
                    WHERE id=%s
                """, (username, email, telefono, password_hash, rol, id))
            else:
                cursor.execute("""
                    UPDATE usuarios 
                    SET username=%s, email=%s, telefono=%s, rol=%s
                    WHERE id=%s
                """, (username, email, telefono, rol, id))

            # 5. Insertar o Actualizar la tabla 'perfil_usuario'
            if foto_nombre:
                # Si subió nueva foto, se actualiza la columna 'foto'
                cursor.execute("""
                    INSERT INTO perfil_usuario 
                        (usuario_id, apellido, foto, fecha_nacimiento, nivel, mano, reves, club, biografia)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        apellido = VALUES(apellido),
                        foto = VALUES(foto),
                        fecha_nacimiento = VALUES(fecha_nacimiento),
                        nivel = VALUES(nivel),
                        mano = VALUES(mano),
                        reves = VALUES(reves),
                        club = VALUES(club),
                        biografia = VALUES(biografia)
                """, (id, apellido, foto_nombre, fecha_nacimiento, nivel, mano, reves, club, biografia))
            else:
                # Si no subió foto, mantenemos la foto actual en la base de datos
                cursor.execute("""
                    INSERT INTO perfil_usuario 
                        (usuario_id, apellido, fecha_nacimiento, nivel, mano, reves, club, biografia)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        apellido = VALUES(apellido),
                        fecha_nacimiento = VALUES(fecha_nacimiento),
                        nivel = VALUES(nivel),
                        mano = VALUES(mano),
                        reves = VALUES(reves),
                        club = VALUES(club),
                        biografia = VALUES(biografia)
                """, (id, apellido, fecha_nacimiento, nivel, mano, reves, club, biografia))

            conn.commit()
            flash("Perfil actualizado correctamente.", "success")
            return redirect(url_for('admin_perfiles'))

        # GET: Consultar datos del usuario unificando ambas tablas
        cursor.execute("""
            SELECT 
                u.id, u.username, u.email, u.telefono, u.rol,
                p.apellido, p.foto, p.fecha_nacimiento, p.nivel, p.mano, p.reves, p.club, p.biografia
            FROM usuarios u
            LEFT JOIN perfil_usuario p ON u.id = p.usuario_id
            WHERE u.id = %s
        """, (id,))
        usuario = cursor.fetchone()

        if not usuario:
            flash("Usuario no encontrado.", "error")
            return redirect(url_for('admin_perfiles'))

        usuario['foto'] = foto_perfil_url(usuario.get('foto'))
        return render_template('admin/actualizar_eliminar_perfil.html', usuario=usuario)

    except sqlite3.Error as err:
        if conn:
            conn.rollback()
        print(f"Error de base de datos: {err}")
        flash("Error al actualizar datos del perfil.", "error")
        return redirect(url_for('admin_perfiles'))
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

@app.route('/admin/facturas')
@admin_required
def facturas():
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión a la base de datos.", "error")
        return redirect(url_for('index'))

    busqueda = request.args.get('busqueda', '').strip()
    cursor = None
    
    try:
        asegurar_tablas_seguimiento_envios(conn)
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT
                f.id,
                CONCAT('FAC-', LPAD(f.id, 4, '0')) AS id_formateado,
                f.fecha,
                f.total,
                f.estado,
                f.metodo_pago,
                f.usuario_id,
                u.username AS cliente,
                u.email AS cliente_email,
                (SELECT COUNT(*) FROM marketplace_envios e WHERE e.factura_id = f.id) AS envios_total,
                (SELECT GROUP_CONCAT(e.estado, ', ')
                 FROM (
                     SELECT estado FROM marketplace_envios
                     WHERE factura_id = f.id
                     ORDER BY created_at DESC
                 ) e) AS estados_envio
            FROM facturas f
            JOIN usuarios u ON f.usuario_id = u.id
        """
        params = []

        if busqueda:
            query += """ WHERE f.id LIKE %s 
                        OR CONCAT('FAC-', LPAD(f.id, 4, '0')) LIKE %s 
                        OR u.username LIKE %s 
                        OR u.email LIKE %s 
                        OR f.estado LIKE %s"""
            pattern = f"%{busqueda}%"
            params = [pattern, pattern, pattern, pattern, pattern]

        query += " ORDER BY f.fecha DESC"
        cursor.execute(query, params)
        facturas_raw = cursor.fetchall()

        facturas = []
        for fac in facturas_raw:
            cursor.execute("""
                SELECT
                    df.id AS detalle_id,
                    df.producto_id,
                    df.cantidad,
                    df.precio_unitario,
                    df.subtotal,
                    p.nombre AS producto_nombre,
                    p.imagen_principal
                FROM detalle_factura df
                JOIN productos p ON df.producto_id = p.id
                WHERE df.factura_id = %s
            """, (fac['id'],))
            productos = cursor.fetchall()

            fac['productos'] = productos
            fac['fecha_iso'] = fac['fecha'].strftime('%Y-%m-%dT%H:%M:%S') if fac['fecha'] else ''
            fac['fecha_entrega_estimada'] = (fac['fecha'] + timedelta(days=5)).date().isoformat() if fac['fecha'] else ''
            fac['num_productos'] = sum(p['cantidad'] for p in productos)
            facturas.append(fac)

    except sqlite3.Error as err:
        print(f"Error al cargar facturas: {err}")
        flash("Error al cargar las facturas.", "error")
        facturas = []
    finally:
        if cursor:
            cursor.close()
        conn.close()

    return render_template('admin/facturas.html', facturas=facturas, busqueda=busqueda, facturas_json=preparar_facturas(facturas))


# RUTA 2: Editar Factura + Datos de Entrega (Acepta GET para mostrar y POST para guardar o eliminar)
@app.route('/admin/factura/editar/<int:id>', methods=['GET', 'POST'])
@admin_required
def editar_factura(id):
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión a la base de datos.", "error")
        return redirect(url_for('facturas'))

    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        # Opción 1: Procesar Eliminación directa desde el formulario
        if request.form.get('accion') == 'eliminar':
            try:
                asegurar_tablas_seguimiento_envios(conn)
                asegurar_tabla_solicitudes_reembolso(conn)
                cursor.execute("SELECT id FROM facturas WHERE id = %s", (id,))
                if not cursor.fetchone():
                    flash("La factura ya no existe.", "warning")
                else:
                    cursor.execute("SELECT id FROM marketplace_envios WHERE factura_id = %s LIMIT 1", (id,))
                    tiene_envio = cursor.fetchone()
                    cursor.execute("SELECT id FROM solicitudes_reembolso WHERE factura_id = %s LIMIT 1", (id,))
                    tiene_reembolso = cursor.fetchone()
                    if tiene_envio or tiene_reembolso:
                        flash("No puedes eliminar una factura con seguimiento de envío o solicitud de reembolso asociada.", "warning")
                    else:
                        cursor.execute("DELETE FROM facturas WHERE id = %s", (id,))
                        conn.commit()
                        flash("Factura eliminada correctamente.", "success")
            except sqlite3.Error as err:
                conn.rollback()
                flash("Error al eliminar la factura.", "error")
            finally:
                cursor.close()
                conn.close()
            return redirect(url_for('facturas'))

        # Opción 2: Guardar Cambios y Datos de Entrega
        try:
            usuario_id = int(request.form.get('usuario_id', ''))
            estado = request.form.get('estado')
            metodo_pago = request.form.get('metodo_pago', '').strip()[:50]
            if usuario_id < 1 or estado not in {'pendiente', 'pagado', 'enviado', 'entregado', 'cancelado'}:
                flash("Selecciona un cliente y un estado válidos.", "error")
                return redirect(url_for('editar_factura', id=id))
            
            productos_ids = request.form.getlist('producto_id[]')
            cantidades = request.form.getlist('cantidad[]')
            precios = request.form.getlist('precio[]')
            if not productos_ids or len(productos_ids) != len(cantidades) or len(productos_ids) != len(precios):
                flash("La factura debe conservar sus productos y los datos de cada línea deben estar completos.", "error")
                return redirect(url_for('editar_factura', id=id))
            detalles_validados = []
            nuevo_total = Decimal('0.00')
            for producto_raw, cantidad_raw, precio_raw in zip(productos_ids, cantidades, precios):
                try:
                    producto_id = int(producto_raw)
                    cantidad = int(cantidad_raw)
                    precio = Decimal(precio_raw)
                    if producto_id < 1 or cantidad < 1 or not precio.is_finite() or precio < 0:
                        raise ValueError
                except (InvalidOperation, ValueError, TypeError):
                    flash("Revisa que cada producto, cantidad y precio sea válido.", "error")
                    return redirect(url_for('editar_factura', id=id))
                subtotal = (Decimal(cantidad) * precio).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                nuevo_total += subtotal
                detalles_validados.append((producto_id, cantidad, precio, subtotal))
            nuevo_total = nuevo_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            cursor.execute("SELECT id FROM facturas WHERE id = %s FOR UPDATE", (id,))
            if not cursor.fetchone():
                flash("La factura ya no existe.", "warning")
                return redirect(url_for('facturas'))

            # Actualizar datos principales
            cursor.execute("""
                UPDATE facturas 
                SET usuario_id = %s, estado = %s, metodo_pago = %s, total = %s 
                WHERE id = %s
            """, (usuario_id, estado, metodo_pago, nuevo_total, id))

            # Reemplazar detalles de los productos
            cursor.execute("DELETE FROM detalle_factura WHERE factura_id = %s", (id,))
            for producto_id, cantidad, precio, subtotal in detalles_validados:
                cursor.execute("""
                    INSERT INTO detalle_factura (factura_id, producto_id, cantidad, precio_unitario, subtotal)
                    VALUES (%s, %s, %s, %s, %s)
                """, (id, producto_id, cantidad, precio, subtotal))

            conn.commit()
            flash("Factura y productos actualizados correctamente.", "success")
            return redirect(url_for('facturas'))

        except (sqlite3.Error, InvalidOperation, ValueError, TypeError) as err:
            conn.rollback()
            print(f"Error al actualizar factura: {err}")
            flash("No se pudo actualizar la factura. Revisa los datos y las relaciones.", "error")
            return redirect(url_for('editar_factura', id=id))
        finally:
            cursor.close()
            conn.close()

    # GET: Cargar datos actuales de la factura
    cursor.execute("""
        SELECT f.*, CONCAT('FAC-', LPAD(f.id, 4, '0')) AS id_formateado, u.username, u.email
        FROM facturas f
        JOIN usuarios u ON f.usuario_id = u.id
        WHERE f.id = %s
    """, (id,))
    factura = cursor.fetchone()

    cursor.execute("""
        SELECT df.*, p.nombre AS producto_nombre, p.imagen_principal
        FROM detalle_factura df
        JOIN productos p ON df.producto_id = p.id
        WHERE df.factura_id = %s
    """, (id,))
    detalles = cursor.fetchall()

    cursor.execute("SELECT id, username, email FROM usuarios ORDER BY username ASC")
    usuarios = cursor.fetchall()

    cursor.execute("SELECT id, nombre, precio FROM productos WHERE activo = 1 ORDER BY nombre ASC")
    productos = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('admin/editar_factura.html', factura=factura, detalles=detalles, usuarios=usuarios, productos=productos)


def preparar_facturas(facturas):
    for factura in facturas:
        factura['fecha'] = factura.get('fecha_iso', '')
        fecha_entrega_real = factura.get('fecha_entrega_real')
        factura['fecha_entrega_real'] = fecha_entrega_real.isoformat() if fecha_entrega_real else ''
        factura['total'] = float(factura['total']) if isinstance(factura.get('total'), Decimal) else factura.get('total', 0)
        for producto in factura.get('productos', []):
            producto['imagen_url'] = product_image_url(producto.get('imagen_principal'))
            for campo in ('precio_unitario', 'subtotal'):
                if isinstance(producto.get(campo), Decimal):
                    producto[campo] = float(producto[campo])
        solicitud = factura.get('solicitud_reembolso')
        if solicitud and isinstance(solicitud.get('monto_simulado'), Decimal):
            solicitud['monto_simulado'] = float(solicitud['monto_simulado'])
    return facturas


@app.route('/mis-compras')
@login_required
def mis_compras():
    """Muestra únicamente las facturas del usuario que inició sesión."""
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión a la base de datos.", "error")
        return redirect(url_for('index'))

    facturas_usuario = []
    cursor = None
    try:
        asegurar_tabla_solicitudes_reembolso(conn)
        asegurar_tablas_seguimiento_envios(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT f.id, CONCAT('FAC-', LPAD(f.id, 4, '0')) AS id_formateado,
                   f.fecha, f.total, f.estado, f.metodo_pago, u.username AS cliente
            FROM facturas f
            JOIN usuarios u ON u.id = f.usuario_id
            WHERE f.usuario_id = %s
            ORDER BY f.fecha DESC
        """, (session['user_id'],))
        facturas_usuario = cursor.fetchall()

        for factura in facturas_usuario:
            cursor.execute("""
                SELECT df.cantidad, df.precio_unitario, df.subtotal,
                       p.nombre AS producto_nombre, p.imagen_principal
                FROM detalle_factura df
                JOIN productos p ON p.id = df.producto_id
                WHERE df.factura_id = %s
            """, (factura['id'],))
            factura['productos'] = cursor.fetchall()
            factura['fecha_iso'] = factura['fecha'].isoformat() if factura['fecha'] else ''
            factura['fecha_entrega_estimada'] = (factura['fecha'] + timedelta(days=5)).date().isoformat() if factura['fecha'] else ''
            cursor.execute('''
                SELECT MAX(entregado_at) AS fecha_entrega_real
                FROM marketplace_envios
                WHERE factura_id = %s AND usuario_id = %s
            ''', (factura['id'], session['user_id']))
            entrega = cursor.fetchone() or {}
            factura['fecha_entrega_real'] = entrega.get('fecha_entrega_real')
            cursor.execute('''
                SELECT id, estado, motivo, evidencia, respuesta_admin,
                       referencia_simulada, monto_simulado, created_at, updated_at
                FROM solicitudes_reembolso
                WHERE factura_id = %s AND usuario_id = %s
                ORDER BY created_at DESC, id DESC LIMIT 1
            ''', (factura['id'], session['user_id']))
            factura['solicitud_reembolso'] = cursor.fetchone()
            if factura['solicitud_reembolso']:
                for campo_fecha in ('created_at', 'updated_at'):
                    valor_fecha = factura['solicitud_reembolso'].get(campo_fecha)
                    factura['solicitud_reembolso'][campo_fecha] = valor_fecha.isoformat() if valor_fecha else ''
            fecha_entrega = factura['fecha_entrega_real'].date() if factura['fecha_entrega_real'] else None
            fecha_limite = sumar_dias_habiles(fecha_entrega, 5) if fecha_entrega else None
            solicitud = factura['solicitud_reembolso']
            factura['fecha_limite_reembolso'] = fecha_limite.isoformat() if fecha_limite else ''
            factura['puede_solicitar_reembolso'] = bool(
                factura['estado'] in {'pagado', 'demo'}
                and fecha_entrega
                and fecha_limite
                and datetime.now().date() <= fecha_limite
                and (not solicitud or solicitud['estado'] == 'rechazado')
            )

        cursor.execute('''
            SELECT id, monto, metodo, created_at,
                   SUBSTRING_INDEX(SUBSTRING_INDEX(referencia_pago, ':', 2), ':', -1) AS plan,
                   SUBSTRING_INDEX(referencia_pago, ':', -1) AS metodo_seleccionado
            FROM pagos
            WHERE usuario_id = %s AND referencia_pago LIKE 'PREMIUM-DEMO:%'
            ORDER BY created_at DESC
        ''', (session['user_id'],))
        for pago_premium in cursor.fetchall():
            fecha_pago = pago_premium['created_at']
            monto = pago_premium['monto']
            facturas_usuario.append({
                'id': -pago_premium['id'],
                'id_formateado': f"PREM-{pago_premium['id']:04d}",
                'fecha': fecha_pago,
                'fecha_iso': fecha_pago.isoformat() if fecha_pago else '',
                'total': monto,
                'estado': 'demo',
                'metodo_pago': f"Premium demo - {pago_premium['metodo_seleccionado'] or pago_premium['metodo']}",
                'cliente': session.get('username', ''),
                'tipo': 'premium',
                'fecha_entrega_estimada': 'Suscripción digital',
                'fecha_entrega_real': None,
                'fecha_limite_reembolso': '',
                'puede_solicitar_reembolso': False,
                'solicitud_reembolso': None,
                'productos': [{
                    'cantidad': 1,
                    'precio_unitario': monto,
                    'subtotal': monto,
                    'producto_nombre': pago_premium['plan'] or 'Plan Premium',
                    'imagen_principal': None,
                }],
            })
        facturas_usuario.sort(key=lambda factura: factura.get('fecha') or datetime.min, reverse=True)
    except sqlite3.Error as err:
        print(f"Error al cargar compras: {err}")
        flash("No fue posible cargar tus compras.", "error")
    finally:
        if cursor:
            cursor.close()
        conn.close()

    return render_template(
        'facturas.html',
        facturas_json=preparar_facturas(facturas_usuario),
        abrir_reembolso=request.args.get('reembolso', type=int)
    )


@app.post('/mis-compras/<int:factura_id>/reembolso')
@login_required
def solicitar_reembolso(factura_id):
    motivo = request.form.get('motivo', '').strip()[:1000]
    if len(motivo) < 20:
        flash('Describe el motivo del reembolso con al menos 20 caracteres.', 'error')
        return redirect(url_for('mis_compras'))
    evidencia = request.files.get('evidencia')
    if not evidencia or not evidencia.filename or not imagen_producto_valida(evidencia):
        flash('Adjunta una fotografía de evidencia válida (PNG, JPG, GIF o WEBP).', 'error')
        return redirect(url_for('mis_compras'))
    evidencia.stream.seek(0, os.SEEK_END)
    evidencia_size = evidencia.stream.tell()
    evidencia.stream.seek(0)
    if evidencia_size > 5 * 1024 * 1024:
        flash('La fotografía de evidencia no puede superar 5 MB.', 'error')
        return redirect(url_for('mis_compras'))

    conn = get_db_connection()
    if not conn:
        flash('No fue posible registrar la solicitud.', 'error')
        return redirect(url_for('mis_compras'))
    cursor = None
    ruta_evidencia = None
    try:
        asegurar_tabla_solicitudes_reembolso(conn)
        asegurar_tablas_seguimiento_envios(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute('''
            SELECT f.id, f.fecha, f.estado,
                   (SELECT MAX(e.entregado_at) FROM marketplace_envios e
                    WHERE e.factura_id = f.id AND e.usuario_id = f.usuario_id) AS fecha_entrega_real
            FROM facturas f
            WHERE f.id = %s AND f.usuario_id = %s
            FOR UPDATE
        ''', (factura_id, session['user_id']))
        factura = cursor.fetchone()
        if not factura:
            flash('No encontramos esa factura en tu cuenta.', 'error')
            return redirect(url_for('mis_compras'))
        if factura['estado'] not in {'pagado', 'demo'}:
            flash('Solo se puede solicitar devolución para una compra confirmada.', 'error')
            return redirect(url_for('mis_compras'))
        fecha_entrega = factura['fecha_entrega_real'].date() if factura['fecha_entrega_real'] else None
        if not fecha_entrega:
            flash('El pedido debe figurar como entregado antes de solicitar un reembolso.', 'warning')
            return redirect(url_for('mis_compras'))
        fecha_limite = sumar_dias_habiles(fecha_entrega, 5)
        if not fecha_limite or datetime.now().date() > fecha_limite:
            flash('El plazo de retracto de cinco días hábiles venció para esta compra.', 'error')
            return redirect(url_for('mis_compras'))

        cursor.execute('''
            SELECT estado FROM solicitudes_reembolso
            WHERE factura_id = %s AND usuario_id = %s
            ORDER BY created_at DESC, id DESC LIMIT 1
            FOR UPDATE
        ''', (factura_id, session['user_id']))
        solicitud_anterior = cursor.fetchone()
        if solicitud_anterior and solicitud_anterior['estado'] in {'pendiente', 'aprobado', 'completado'}:
            flash('Ya existe una solicitud de reembolso en curso o completada para esta factura.', 'info')
            return redirect(url_for('mis_compras'))

        nombre_evidencia = secure_filename(evidencia.filename)[:120]
        nombre_evidencia = f'reembolso_{session["user_id"]}_{factura_id}_{datetime.now().strftime("%Y%m%d%H%M%S%f")}_{nombre_evidencia}'
        ruta_evidencia = os.path.join(REFUND_UPLOAD_FOLDER, nombre_evidencia)
        evidencia.save(ruta_evidencia)
        cursor.execute('''
            INSERT INTO solicitudes_reembolso (factura_id, usuario_id, motivo, evidencia)
            VALUES (%s, %s, %s, %s)
        ''', (factura_id, session['user_id'], motivo, f'uploads/reembolsos/{nombre_evidencia}'))
        conn.commit()
        if factura['estado'] == 'demo':
            flash('Solicitud de devolución registrada. Esta compra fue de demostración; no hubo un cargo bancario que devolver.', 'success')
        else:
            flash('Solicitud de reembolso enviada. Puedes consultar su estado en esta factura.', 'success')
    except (sqlite3.Error, OSError) as err:
        conn.rollback()
        if ruta_evidencia and os.path.exists(ruta_evidencia):
            os.remove(ruta_evidencia)
        print(f'Error al solicitar reembolso: {err}')
        flash('No fue posible registrar la solicitud.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()
    return redirect(url_for('mis_compras', reembolso=factura_id))


@app.route('/admin/reembolsos', methods=['GET', 'POST'])
@admin_required
def admin_reembolsos():
    search = request.form.get('q', '') if request.method == 'POST' else request.args.get('q', '')
    search = search.strip()[:120]
    conn = get_db_connection()
    if not conn:
        flash('No fue posible cargar los reembolsos.', 'error')
        return redirect(url_for('admin_facturas'))
    cursor = None
    solicitudes = []
    try:
        asegurar_tabla_solicitudes_reembolso(conn)
        asegurar_tablas_seguimiento_envios(conn)
        cursor = conn.cursor(dictionary=True)
        if request.method == 'POST':
            solicitud_id = request.form.get('solicitud_id', type=int)
            estado_nuevo = request.form.get('estado', '')
            respuesta = request.form.get('respuesta_admin', '').strip()[:1000]
            cursor.execute('''
                SELECT r.estado, r.factura_id, f.estado AS factura_estado, f.total AS factura_total
                FROM solicitudes_reembolso r
                JOIN facturas f ON f.id = r.factura_id
                WHERE r.id = %s
                FOR UPDATE
            ''', (solicitud_id,))
            solicitud_actual = cursor.fetchone()
            transiciones = {
                'pendiente': {'aprobado', 'rechazado'},
                'aprobado': {'completado'},
            }
            if not solicitud_actual or estado_nuevo not in transiciones.get(solicitud_actual['estado'], set()):
                flash('La transición de estado del reembolso no es válida.', 'error')
            elif estado_nuevo == 'completado' and len(respuesta) < 5:
                flash('Agrega una nota de resolución; para compras pagadas incluye la referencia de devolución.', 'error')
            else:
                if estado_nuevo == 'completado' and solicitud_actual['factura_estado'] == 'demo':
                    referencia_simulada = f'SIM-REF-{solicitud_id:06d}'
                    nota_resolucion = (
                        f'{respuesta[:700]} · Devolución simulada por '
                        f'${solicitud_actual["factura_total"]:,.2f}; no hubo movimiento de dinero.'
                    )
                    cursor.execute('''
                        UPDATE solicitudes_reembolso
                        SET estado = %s, respuesta_admin = %s, revisado_por = %s,
                            referencia_simulada = %s, monto_simulado = %s
                        WHERE id = %s
                    ''', (estado_nuevo, nota_resolucion, session['user_id'],
                          referencia_simulada, solicitud_actual['factura_total'], solicitud_id))
                else:
                    cursor.execute('''
                        UPDATE solicitudes_reembolso
                        SET estado = %s, respuesta_admin = %s, revisado_por = %s
                        WHERE id = %s
                    ''', (estado_nuevo, respuesta or None, session['user_id'], solicitud_id))
                conn.commit()
                flash(
                    'Devolución simulada completada y registrada; no hubo movimiento de dinero.'
                    if estado_nuevo == 'completado' and solicitud_actual['factura_estado'] == 'demo'
                    else 'Estado de reembolso actualizado.',
                    'success'
                )

        query = '''
            SELECT r.*, f.total AS factura_total, f.estado AS estado_factura,
                   CONCAT('FAC-', LPAD(f.id, 4, '0')) AS factura_formateada,
                   f.fecha AS fecha_compra,
                   (SELECT MAX(e.entregado_at) FROM marketplace_envios e
                    WHERE e.factura_id = f.id AND e.usuario_id = r.usuario_id) AS fecha_entrega_real,
                   COALESCE(u.nombre_completo, u.username, u.email) AS cliente
            FROM solicitudes_reembolso r
            JOIN facturas f ON f.id = r.factura_id
            JOIN usuarios u ON u.id = r.usuario_id
        '''
        parameters = []
        if search:
            query += """ WHERE (CAST(r.factura_id AS CHAR) LIKE %s OR r.estado LIKE %s
                         OR r.motivo LIKE %s OR u.username LIKE %s OR u.email LIKE %s
                         OR u.nombre_completo LIKE %s)"""
            parameters = [f'%{search}%'] * 6
        cursor.execute(
            query + " ORDER BY FIELD(r.estado, 'pendiente', 'aprobado', 'rechazado', 'completado'), r.created_at DESC",
            parameters
        )
        solicitudes = cursor.fetchall()
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error en gestión de reembolsos: {err}')
        flash('No fue posible cargar las solicitudes.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()
    return render_template('admin/reembolsos.html', solicitudes=solicitudes, search=search)


ESTADOS_ENVIO = {
    'pedido_recibido': 'Pedido confirmado',
    'preparando': 'En preparación',
    'empacado': 'Pedido empacado',
    'enviado': 'Entregado a transportadora',
    'en_camino': 'En tránsito',
    'en_reparto': 'En reparto',
    'entregado': 'Entregado',
    'incidencia': 'Novedad en el envío',
}
PASOS_ENVIO = ('pedido_recibido', 'preparando', 'empacado', 'enviado', 'en_camino', 'en_reparto', 'entregado')
TRANSICIONES_ENVIO = {
    'pedido_recibido': {'pedido_recibido', 'preparando', 'incidencia'},
    'preparando': {'preparando', 'empacado', 'incidencia'},
    'empacado': {'empacado', 'enviado', 'incidencia'},
    'enviado': {'enviado', 'en_camino', 'en_reparto', 'incidencia'},
    'en_camino': {'en_camino', 'en_reparto', 'entregado', 'incidencia'},
    'en_reparto': {'en_reparto', 'entregado', 'incidencia'},
    'entregado': {'entregado'},
    'incidencia': {'incidencia'},
}


@app.route('/mis-envios')
@login_required
def mis_envios():
    vista_envios = request.args.get('vista', 'activos')
    if vista_envios not in {'activos', 'archivados'}:
        vista_envios = 'activos'
    estado_filtro = request.args.get('estado', '').strip()
    buscar = request.args.get('q', '').strip()[:120]
    conn = get_db_connection()
    if not conn:
        flash('No fue posible cargar tus envíos.', 'error')
        return redirect(url_for('mis_compras'))

    cursor = None
    envios = []
    try:
        asegurar_tablas_seguimiento_envios(conn)
        cursor = conn.cursor(dictionary=True)
        query = '''
            SELECT e.*, f.estado AS estado_pago,
                   CONCAT('FAC-', LPAD(e.factura_id, 4, '0')) AS factura_formateada,
                   COALESCE(u.nombre_completo, u.username, 'Tienda TENNISSEL') AS tienda_nombre
            FROM marketplace_envios e
            JOIN facturas f ON f.id = e.factura_id
            LEFT JOIN usuarios u ON u.id = e.tienda_user_id
            WHERE e.usuario_id = %s
        '''
        params = [session['user_id']]
        if vista_envios == 'archivados':
            query += ' AND e.archivado_por_usuario_at IS NOT NULL'
        else:
            query += ' AND e.archivado_por_usuario_at IS NULL'
        if estado_filtro in ESTADOS_ENVIO:
            query += ' AND e.estado = %s'
            params.append(estado_filtro)
        if buscar:
            query += ''' AND (e.numero_envio LIKE %s OR e.codigo_seguimiento LIKE %s
                            OR CAST(e.factura_id AS CHAR) LIKE %s OR e.ciudad_envio LIKE %s
                            OR e.nombre_recibe LIKE %s OR u.username LIKE %s)'''
            termino = f'%{buscar}%'
            params.extend((termino, termino, termino, termino, termino, termino))
        query += ' ORDER BY e.created_at DESC, e.id DESC'
        cursor.execute(query, tuple(params))
        envios = cursor.fetchall()
        for envio in envios:
            cursor.execute('''
                SELECT estado, descripcion, created_at
                FROM marketplace_envio_eventos
                WHERE envio_id = %s
                ORDER BY created_at DESC, id DESC
            ''', (envio['id'],))
            envio['eventos'] = cursor.fetchall()
            estado_progreso = envio['estado']
            if estado_progreso == 'incidencia':
                estado_progreso = next((evento['estado'] for evento in envio['eventos']
                                        if evento['estado'] != 'incidencia'), 'pedido_recibido')
            envio['estado_progreso_indice'] = PASOS_ENVIO.index(estado_progreso) if estado_progreso in PASOS_ENVIO else 0
            envio['entrega_vencida'] = bool(
                envio.get('fecha_estimada')
                and envio['fecha_estimada'] < datetime.now().date()
                and envio['estado'] != 'entregado'
            )
            cursor.execute('''
                SELECT p.nombre, p.imagen_principal, df.cantidad
                FROM detalle_factura df
                JOIN productos p ON p.id = df.producto_id
                WHERE df.factura_id = %s AND p.owner_user_id <=> %s
            ''', (envio['factura_id'], envio['tienda_user_id']))
            envio['productos'] = cursor.fetchall()
            if envio.get('fecha_estimada'):
                envio['dias_restantes'] = max((envio['fecha_estimada'] - datetime.now().date()).days, 0)
    except sqlite3.Error as err:
        print(f'Error al cargar seguimiento de envíos: {err}')
        flash('No fue posible cargar el seguimiento de tus pedidos.', 'error')
        envios = []
    finally:
        if cursor:
            cursor.close()
        conn.close()

    return render_template('mis_envios.html', envios=envios, estados_envio=ESTADOS_ENVIO,
                           pasos_envio=PASOS_ENVIO, vista_envios=vista_envios,
                           estado_filtro=estado_filtro, buscar=buscar)


@app.post('/mis-envios/<int:envio_id>/archivar')
@login_required
def archivar_envio(envio_id):
    vista_origen = request.form.get('vista', 'activos')
    if vista_origen not in {'activos', 'archivados'}:
        vista_origen = 'activos'
    conn = get_db_connection()
    if not conn:
        flash('No fue posible actualizar tu lista de pedidos.', 'error')
        return redirect(url_for('mis_envios', vista=vista_origen))

    cursor = None
    try:
        asegurar_tablas_seguimiento_envios(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute('''
            SELECT id, estado, archivado_por_usuario_at
            FROM marketplace_envios
            WHERE id = %s AND usuario_id = %s
        ''', (envio_id, session['user_id']))
        envio = cursor.fetchone()
        if not envio:
            flash('No encontramos ese envío en tu cuenta.', 'error')
        elif envio['estado'] != 'entregado':
            flash('Solo puedes archivar un envío cuando la tienda confirme que fue entregado.', 'warning')
        elif envio['archivado_por_usuario_at']:
            flash('Este envío ya está archivado.', 'info')
        else:
            cursor.execute('''
                UPDATE marketplace_envios
                SET archivado_por_usuario_at = CURRENT_TIMESTAMP
                WHERE id = %s AND usuario_id = %s AND estado = 'entregado'
                  AND archivado_por_usuario_at IS NULL
            ''', (envio_id, session['user_id']))
            conn.commit()
            flash('Envío archivado. La factura y el historial se conservaron.', 'success')
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error archivando envío: {err}')
        flash('No fue posible archivar el envío.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()
    return redirect(url_for('mis_envios', vista=vista_origen))


@app.route('/tienda/envios')
@login_required
def gestionar_envios():
    rol = session.get('role')
    if rol not in ('tienda', 'admin'):
        flash('Esta sección es para tiendas y administración.', 'error')
        return redirect(url_for('index'))
    estado_filtro = request.args.get('estado', '').strip()
    buscar = request.args.get('q', '').strip()[:120]

    conn = get_db_connection()
    if not conn:
        flash('No fue posible cargar los pedidos.', 'error')
        return redirect(url_for('index'))

    cursor = None
    envios = []
    try:
        asegurar_columna_propietario_producto(conn)
        asegurar_tablas_seguimiento_envios(conn)
        cursor = conn.cursor(dictionary=True)
        query = '''
            SELECT e.*, f.estado AS estado_pago,
                   CONCAT('FAC-', LPAD(e.factura_id, 4, '0')) AS factura_formateada,
                   COALESCE(u.nombre_completo, u.username, 'Cliente') AS cliente_nombre
            FROM marketplace_envios e
            JOIN facturas f ON f.id = e.factura_id
            JOIN usuarios u ON u.id = e.usuario_id
        '''
        condiciones = []
        params = []
        if rol != 'admin':
            condiciones.append('e.tienda_user_id = %s')
            params.append(session['user_id'])
        condiciones.append('e.archivado_por_usuario_at IS NULL')
        if estado_filtro in ESTADOS_ENVIO:
            condiciones.append('e.estado = %s')
            params.append(estado_filtro)
        if buscar:
            condiciones.append('''(e.numero_envio LIKE %s OR e.codigo_seguimiento LIKE %s
                                  OR CAST(e.factura_id AS CHAR) LIKE %s OR e.ciudad_envio LIKE %s
                                  OR e.nombre_recibe LIKE %s OR u.username LIKE %s
                                  OR u.nombre_completo LIKE %s)''')
            termino = f'%{buscar}%'
            params.extend((termino, termino, termino, termino, termino, termino, termino))
        query += ' WHERE ' + ' AND '.join(condiciones)
        query += ' ORDER BY e.created_at DESC, e.id DESC'
        cursor.execute(query, tuple(params))
        envios = cursor.fetchall()
        for envio in envios:
            estado_base = envio['estado']
            if estado_base == 'incidencia':
                cursor.execute('''
                    SELECT estado FROM marketplace_envio_eventos
                    WHERE envio_id = %s AND estado != 'incidencia'
                    ORDER BY created_at DESC, id DESC LIMIT 1
                ''', (envio['id'],))
                evento_base = cursor.fetchone()
                estado_base = evento_base['estado'] if evento_base else 'pedido_recibido'
            envio['estados_permitidos'] = set(TRANSICIONES_ENVIO.get(estado_base, {estado_base}))
            if envio['estado'] == 'incidencia':
                envio['estados_permitidos'].add('incidencia')
            cursor.execute('''
                SELECT p.nombre AS producto_nombre, p.imagen_principal, df.cantidad
                FROM detalle_factura df
                JOIN productos p ON p.id = df.producto_id
                WHERE df.factura_id = %s AND p.owner_user_id <=> %s
            ''', (envio['factura_id'], envio['tienda_user_id']))
            envio['productos'] = cursor.fetchall()
    except sqlite3.Error as err:
        print(f'Error al cargar pedidos de tienda: {err}')
        flash('No fue posible cargar los pedidos.', 'error')
        envios = []
    finally:
        if cursor:
            cursor.close()
        conn.close()

    return render_template('tienda_envios.html', envios=envios, estados_envio=ESTADOS_ENVIO,
                           transiciones_envio=TRANSICIONES_ENVIO,
                           estado_filtro=estado_filtro, buscar=buscar, rol=rol)


@app.route('/tienda/envios/<int:envio_id>/actualizar', methods=['POST'])
@login_required
def actualizar_estado_envio(envio_id):
    rol = session.get('role')
    if rol not in ('tienda', 'admin'):
        return jsonify(error='No tienes permiso para actualizar este envío.'), 403

    estado_nuevo = request.form.get('estado', '')
    descripcion = request.form.get('descripcion', '').strip()[:500]
    fecha_raw = request.form.get('fecha_estimada', '').strip()
    transportadora = request.form.get('transportadora', '').strip()[:100]
    codigo_seguimiento = request.form.get('codigo_seguimiento', '').strip()[:120]
    url_seguimiento = request.form.get('url_seguimiento', '').strip()[:500]
    if estado_nuevo not in ESTADOS_ENVIO:
        flash('Selecciona un estado de envío válido.', 'error')
        return redirect(url_for('gestionar_envios'))
    if url_seguimiento and not url_seguimiento.startswith('https://'):
        flash('El enlace de seguimiento debe comenzar con https://.', 'error')
        return redirect(url_for('gestionar_envios'))
    try:
        fecha_estimada = datetime.strptime(fecha_raw, '%Y-%m-%d').date() if fecha_raw else None
    except ValueError:
        flash('La fecha estimada no es válida.', 'error')
        return redirect(url_for('gestionar_envios'))

    conn = get_db_connection()
    if not conn:
        flash('No fue posible guardar el seguimiento.', 'error')
        return redirect(url_for('gestionar_envios'))
    cursor = None
    try:
        asegurar_tablas_seguimiento_envios(conn)
        cursor = conn.cursor(dictionary=True)
        query = '''SELECT id, tienda_user_id, estado, transportadora, fecha_estimada,
                  codigo_seguimiento, url_seguimiento
               FROM marketplace_envios WHERE id = %s'''
        params = [envio_id]
        if rol != 'admin':
            query += ' AND tienda_user_id = %s'
            params.append(session['user_id'])
        cursor.execute(query, tuple(params))
        envio = cursor.fetchone()
        if not envio:
            flash('No encontramos ese envío en tu tienda.', 'error')
            return redirect(url_for('gestionar_envios'))

        estado_base = envio['estado']
        if estado_base == 'incidencia':
            cursor.execute('''
                SELECT estado FROM marketplace_envio_eventos
                WHERE envio_id = %s AND estado != 'incidencia'
                ORDER BY created_at DESC, id DESC LIMIT 1
            ''', (envio_id,))
            evento_base = cursor.fetchone()
            estado_base = evento_base['estado'] if evento_base else 'pedido_recibido'
        if estado_nuevo not in TRANSICIONES_ENVIO.get(estado_base, set()):
            flash('El estado no puede retroceder ni modificarse después de la entrega.', 'error')
            return redirect(url_for('gestionar_envios'))
        if estado_nuevo in {'enviado', 'en_camino', 'en_reparto', 'entregado'} and not (transportadora or envio.get('transportadora')):
            flash('Indica la transportadora o el repartidor responsable antes de registrar el despacho.', 'error')
            return redirect(url_for('gestionar_envios'))

        datos_seguimiento_modificados = any((
            fecha_estimada != envio.get('fecha_estimada'),
            (transportadora or None) != (envio.get('transportadora') or None),
            (codigo_seguimiento or None) != (envio.get('codigo_seguimiento') or None),
            (url_seguimiento or None) != (envio.get('url_seguimiento') or None),
        ))

        cursor.execute('''
            UPDATE marketplace_envios
            SET estado = %s, fecha_estimada = %s, transportadora = %s,
                codigo_seguimiento = %s, url_seguimiento = %s,
                entregado_at = CASE WHEN %s = 'entregado' THEN COALESCE(entregado_at, CURRENT_TIMESTAMP) ELSE entregado_at END
            WHERE id = %s
        ''', (estado_nuevo, fecha_estimada, transportadora or None,
              codigo_seguimiento or None, url_seguimiento or None, estado_nuevo, envio_id))

        if estado_nuevo != envio['estado'] or descripcion or datos_seguimiento_modificados:
            texto_evento = descripcion or (
                f'Estado actualizado: {ESTADOS_ENVIO[estado_nuevo]}.'
                if estado_nuevo != envio['estado'] else 'Datos de seguimiento actualizados.'
            )
            cursor.execute('''
                INSERT INTO marketplace_envio_eventos (envio_id, actor_user_id, estado, descripcion)
                VALUES (%s, %s, %s, %s)
            ''', (envio_id, session['user_id'], estado_nuevo, texto_evento))
        conn.commit()
        flash('El seguimiento del pedido fue actualizado.', 'success')
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error actualizando envío: {err}')
        flash('No fue posible guardar el seguimiento.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()
    return redirect(url_for('gestionar_envios'))





# ═══════════════════════════════════════════════════════════════════════════
# CRUD DE PRODUCTOS (ADMIN)
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# CRUD DE PRODUCTOS (ADMIN)
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# CRUD DE PRODUCTOS (ADMIN)
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/admin/productos')
@admin_required
def admin_productos():
    vista = request.args.get('vista', 'pendientes')
    if vista not in {'pendientes', 'catalogo'}:
        vista = 'pendientes'
    search = request.args.get('q', '').strip()[:120]
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión con la base de datos.", "error")
        return redirect(url_for("index"))
    asegurar_columna_propietario_producto(conn)
    expirar_ofertas(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM productos
        WHERE owner_user_id IS NOT NULL AND estado_revision = 'pendiente'
    """)
    solicitudes_pendientes = cursor.fetchone()['total']
    g.solicitudes_productos_pendientes = int(solicitudes_pendientes)
    query = """
         SELECT p.id, p.nombre, p.descripcion_corta, p.descripcion_larga, p.sku, p.marca,
             p.subcategoria, p.color, p.talla, p.peso, p.especificaciones, p.variaciones,
             p.precio, p.stock, p.imagen_principal,
               p.destacado, p.destacado_solicitado, p.activo, p.estado_revision,
               p.moderation_note,
               p.owner_user_id, u.username AS tienda_nombre
        FROM productos p
        LEFT JOIN usuarios u ON u.id = p.owner_user_id
    """
    if vista == 'pendientes':
        query += " WHERE p.owner_user_id IS NOT NULL AND p.estado_revision = 'pendiente'"
    else:
        query += " WHERE p.activo = 1 AND p.estado_revision = 'aprobado'"
    parameters = []
    if search:
        query += """ AND (
            CAST(p.id AS CHAR) LIKE %s OR p.nombre LIKE %s OR p.sku LIKE %s
            OR p.marca LIKE %s OR u.username LIKE %s
        )"""
        parameters = [f'%{search}%'] * 5
    if vista == 'pendientes':
        query += ' ORDER BY p.destacado_solicitado DESC, p.created_at ASC, p.id ASC'
    else:
        query += ' ORDER BY p.destacado DESC, p.created_at DESC, p.id DESC'
    cursor.execute(query, parameters)
    productos = cursor.fetchall()
    for producto in productos:
        for campo_json in ('especificaciones', 'variaciones'):
            valor_json = producto.get(campo_json)
            if isinstance(valor_json, str):
                try:
                    producto[campo_json] = json.loads(valor_json)
                except (ValueError, TypeError):
                    producto[campo_json] = []
    cursor.close()
    conn.close()
    return render_template(
        'admin/productos.html',
        productos=productos,
        vista=vista,
        solicitudes_pendientes=solicitudes_pendientes,
        search=search
    )


@app.route('/admin/productos/<int:id>/revision', methods=['POST'])
@admin_required
def revisar_producto_tienda(id):
    estado_revision = request.form.get('estado_revision', '')
    if estado_revision not in {'aprobado', 'rechazado'}:
        flash('Selecciona una decisión válida para la solicitud.', 'error')
        return redirect(url_for('admin_productos'))
    conn = get_db_connection()
    if not conn:
        flash('No fue posible actualizar la solicitud.', 'error')
        return redirect(url_for('admin_productos'))
    cursor = None
    try:
        asegurar_columna_propietario_producto(conn)
        asegurar_tabla_notificaciones_productos(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute('''
            SELECT id, owner_user_id, nombre, estado_revision, destacado_solicitado
            FROM productos
            WHERE id = %s AND owner_user_id IS NOT NULL
            FOR UPDATE
        ''', (id,))
        producto = cursor.fetchone()
        if not producto or producto['estado_revision'] != 'pendiente':
            conn.rollback()
            flash('La solicitud ya fue revisada o no existe.', 'warning')
        else:
            destacado = int(estado_revision == 'aprobado' and producto['destacado_solicitado'])
            cursor.execute('''
                UPDATE productos
                SET estado_revision = %s, activo = %s,
                    destacado = CASE WHEN %s = 1 THEN 1 ELSE destacado END,
                    fecha_fin_oferta = CASE
                        WHEN %s = 1 AND en_oferta = 1
                             AND (fecha_fin_oferta IS NULL OR fecha_fin_oferta <= CURRENT_TIMESTAMP)
                        THEN DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 7 DAY)
                        ELSE fecha_fin_oferta
                    END
                WHERE id = %s AND estado_revision = 'pendiente'
            ''', (estado_revision, int(estado_revision == 'aprobado'), destacado,
                  int(estado_revision == 'aprobado'), id))
            if not cursor.rowcount:
                conn.rollback()
                flash('La solicitud ya fue revisada por otra sesión.', 'warning')
            else:
                titulo = 'Producto aprobado' if estado_revision == 'aprobado' else 'Producto rechazado'
                estado_texto = 'aprobada y publicada' if estado_revision == 'aprobado' else 'rechazada'
                detalle_destacado = ' También fue publicado como destacado.' if destacado else ''
                mensaje = f'Tu solicitud para "{producto["nombre"]}" fue {estado_texto}.{detalle_destacado}'
                cursor.execute('''
                    INSERT INTO notificaciones_productos (usuario_id, titulo, mensaje)
                    VALUES (%s, %s, %s)
                ''', (producto['owner_user_id'], titulo, mensaje))
                conn.commit()
                flash('Solicitud aprobada y publicada.' if estado_revision == 'aprobado'
                      else 'Solicitud rechazada. Se notificó a la tienda.', 'success')
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error revisando propuesta de producto: {err}')
        flash('No fue posible actualizar la solicitud.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()
    return redirect(url_for('admin_productos'))

@app.route('/admin/productos/editar/<int:id>', methods=['GET', 'POST'])
@admin_required
def editar_producto(id):
    conn = get_db_connection()
    if not conn:
        flash('No fue posible conectar con la base de datos.', 'error')
        return redirect(url_for('admin_productos'))
    asegurar_columna_propietario_producto(conn)
    expirar_ofertas(conn)
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        slug = request.form.get('slug', '').strip()
        descripcion_corta = request.form.get('descripcion_corta', '').strip()
        descripcion_larga = request.form.get('descripcion_larga', '').strip()
        categoria_id_raw = request.form.get('categoria_id', '')
        subcategoria = request.form.get('subcategoria', '').strip()
        marca = request.form.get('marca', '').strip()
        color = request.form.get('color', '').strip()
        talla = request.form.get('talla', '').strip()
        precio_raw = request.form.get('precio', '')
        precio_anterior_raw = request.form.get('precio_anterior', '').strip()
        stock_raw = request.form.get('stock', '0')
        sku = request.form.get('sku', '').strip()
        imagen_principal = request.form.get('imagen_principal', 'default-product.jpg').strip()
        video_url = request.form.get('video_url', '').strip()
        peso_raw = request.form.get('peso', '').strip()
        badge = request.form.get('badge', '').strip()
        en_oferta = 1 if request.form.get('en_oferta') == 'on' else 0
        fecha_fin_raw = request.form.get('fecha_fin_oferta', '').strip()
        try:
            categoria_id = int(categoria_id_raw)
            precio = Decimal(precio_raw)
            precio_anterior = Decimal(precio_anterior_raw) if precio_anterior_raw else None
            stock = int(stock_raw)
            peso = Decimal(peso_raw) if peso_raw else None
            if (not nombre or categoria_id < 1 or stock < 0 or not precio.is_finite() or precio < 0
                    or (precio_anterior is not None and (not precio_anterior.is_finite() or precio_anterior < 0))
                    or (peso is not None and (not peso.is_finite() or peso < 0))):
                raise ValueError
            fecha_fin_oferta = datetime.strptime(fecha_fin_raw, '%Y-%m-%dT%H:%M') if fecha_fin_raw else None
            if en_oferta and (not fecha_fin_oferta or fecha_fin_oferta <= datetime.now()
                              or precio_anterior is None or precio_anterior <= precio):
                raise ValueError
        except (InvalidOperation, ValueError, TypeError):
            cursor.close()
            conn.close()
            flash('Revisa el nombre, categoría, precio, stock, peso y los datos de la oferta.', 'error')
            return redirect(url_for('editar_producto', id=id))
        if not en_oferta:
            fecha_fin_oferta = None
        es_novedad = 1 if request.form.get('es_novedad') == 'on' else 0
        destacado = 1 if request.form.get('destacado') == 'on' else 0
        activo = 1 if request.form.get('activo') == 'on' else 0
        estado_revision = request.form.get('estado_revision', 'aprobado')
        if estado_revision not in {'pendiente', 'aprobado', 'rechazado'}:
            cursor.close()
            conn.close()
            flash('Selecciona un estado de revisión válido.', 'error')
            return redirect(url_for('editar_producto', id=id))
        if estado_revision != 'aprobado':
            activo = 0

        # Manejo de campos JSON opcionales
        imagenes_raw = request.form.get('imagenes', '').strip()
        especificaciones_raw = request.form.get('especificaciones', '').strip()
        variaciones_raw = request.form.get('variaciones', '').strip()
        preguntas_raw = request.form.get('preguntas_frecuentes', '').strip()

        try:
            imagenes_data = json.loads(imagenes_raw) if imagenes_raw else None
            especificaciones_data = json.loads(especificaciones_raw) if especificaciones_raw else None
            variaciones_data = json.loads(variaciones_raw) if variaciones_raw else None
            preguntas = json.loads(preguntas_raw) if preguntas_raw else []
            if any(
                value is not None and not isinstance(value, (list, dict))
                for value in (imagenes_data, especificaciones_data, variaciones_data)
            ):
                raise ValueError
            if not isinstance(preguntas, list):
                raise ValueError
            if any(
                not isinstance(item, dict)
                or not isinstance(item.get('pregunta'), str)
                or not item['pregunta'].strip()
                or not isinstance(item.get('respuesta'), str)
                or not item['respuesta'].strip()
                for item in preguntas
            ):
                raise ValueError
            imagenes = json.dumps(imagenes_data, ensure_ascii=False) if imagenes_data is not None else None
            especificaciones = json.dumps(especificaciones_data, ensure_ascii=False) if especificaciones_data is not None else None
            variaciones = json.dumps(variaciones_data, ensure_ascii=False) if variaciones_data is not None else None
            preguntas = [
                {'pregunta': item['pregunta'].strip(), 'respuesta': item['respuesta'].strip()}
                for item in preguntas
            ]
        except (ValueError, TypeError):
            cursor.close()
            conn.close()
            flash('Revisa el formato JSON de imágenes, características, variaciones y preguntas frecuentes.', 'error')
            return redirect(url_for('editar_producto', id=id))

        try:
            cursor.execute("""
                UPDATE productos SET 
                    nombre=%s, slug=%s, descripcion_corta=%s, descripcion_larga=%s,
                    categoria_id=%s, subcategoria=%s, marca=%s, color=%s, talla=%s,
                    precio=%s, precio_anterior=%s, fecha_fin_oferta=%s, stock=%s, sku=%s, imagen_principal=%s,
                    imagenes=%s, video_url=%s, especificaciones=%s, variaciones=%s, peso=%s,
                    destacado=%s, badge=%s, activo=%s, en_oferta=%s, es_novedad=%s,
                    estado_revision=%s
                WHERE id=%s
            """, (
                nombre, slug or crear_slug(nombre), descripcion_corta, descripcion_larga,
                categoria_id, subcategoria, marca, color, talla,
                precio, precio_anterior, fecha_fin_oferta, stock, sku, imagen_principal,
                imagenes, video_url, especificaciones, variaciones, peso,
                destacado, badge, activo, en_oferta, es_novedad, estado_revision, id
            ))
            if not cursor.rowcount:
                cursor.execute("SELECT id FROM productos WHERE id = %s", (id,))
                if not cursor.fetchone():
                    cursor.close()
                    conn.close()
                    flash('El producto ya no existe.', 'warning')
                    return redirect(url_for('admin_productos'))

            cursor.execute("DELETE FROM preguntas_frecuentes WHERE producto_id = %s", (id,))
            for item in preguntas:
                cursor.execute("""
                    INSERT INTO preguntas_frecuentes (producto_id, pregunta, respuesta, aprobada)
                    VALUES (%s, %s, %s, 1)
                """, (id, item['pregunta'], item['respuesta']))

            conn.commit()
        except sqlite3.Error as err:
            conn.rollback()
            print(f'Error actualizando producto: {err}')
            flash('No fue posible guardar el producto. Verifica sus relaciones y el SKU.', 'error')
            cursor.close()
            conn.close()
            return redirect(url_for('editar_producto', id=id))

        cursor.close()
        conn.close()
        flash("Producto actualizado correctamente.", "success")
        return redirect(url_for('admin_productos'))

    cursor.execute("SELECT * FROM productos WHERE id = %s", (id,))
    producto = cursor.fetchone()
    if not producto:
        cursor.close()
        conn.close()
        flash('El producto que intentas editar no existe.', 'warning')
        return redirect(url_for('admin_productos'))
    cursor.execute("SELECT pregunta, respuesta FROM preguntas_frecuentes WHERE producto_id = %s ORDER BY id", (id,))
    producto['preguntas_frecuentes'] = json.dumps(cursor.fetchall(), ensure_ascii=False, indent=2)
    cursor.execute("SELECT id, nombre FROM categorias ORDER BY nombre ASC")
    categorias = cursor.fetchall()
    cursor.close()
    conn.close()

    # Convertir JSON a String legible para los textareas
    if producto:
        if isinstance(producto.get('imagenes'), (dict, list)):
            producto['imagenes'] = json.dumps(producto['imagenes'], ensure_ascii=False)
        if isinstance(producto.get('especificaciones'), (dict, list)):
            producto['especificaciones'] = json.dumps(producto['especificaciones'], ensure_ascii=False)
        if isinstance(producto.get('variaciones'), (dict, list)):
            producto['variaciones'] = json.dumps(producto['variaciones'], ensure_ascii=False, indent=2)

    return render_template('admin/editar_producto.html', producto=producto, categorias=categorias)

@app.route('/admin/productos/eliminar/<int:id>', methods=['POST'])
@admin_required
def eliminar_producto(id):
    conn = get_db_connection()
    if not conn:
        flash('No fue posible conectar con la base de datos.', 'error')
        return redirect(url_for('admin_productos'))
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM detalle_factura WHERE producto_id = %s LIMIT 1", (id,))
        tiene_facturas = cursor.fetchone()
        cursor.execute("SELECT id FROM orden_items WHERE producto_id = %s LIMIT 1", (id,))
        tiene_ordenes = cursor.fetchone()
        if tiene_facturas or tiene_ordenes:
            flash('No puedes eliminar un producto incluido en facturas u órdenes.', 'warning')
        else:
            cursor.execute("DELETE FROM productos WHERE id = %s", (id,))
            if cursor.rowcount:
                conn.commit()
                flash("Producto eliminado correctamente.", "success")
            else:
                flash('El producto ya no existe.', 'warning')
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error eliminando producto: {err}')
        flash('No se pudo eliminar el producto.', 'error')
    finally:
        if cursor:
            cursor.close()
        conn.close()
    return redirect(url_for('admin_productos'))



@app.route('/admin/pedidos')
@admin_required
def admin_pedidos_envios():
    return redirect(url_for('gestionar_envios'))


@app.route('/admin/pedidos/detalle/<int:id>', methods=['GET', 'POST'])
@admin_required
def detalle_pedido(id):
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión a la base de datos.", "error")
        return redirect(url_for('admin_pedidos_envios'))

    try:
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            try:
                cursor.execute(
                    'SELECT id, estado, envio, descuento FROM ordenes WHERE id = %s FOR UPDATE',
                    (id,)
                )
                orden_bloqueada = cursor.fetchone()
                if not orden_bloqueada:
                    raise ValueError('La orden ya no existe.')
                if orden_bloqueada['estado'] != 'pendiente':
                    raise ValueError('Solo puedes editar artículos de órdenes pendientes.')

                cursor.execute(
                    "SELECT id FROM pagos WHERE orden_id = %s AND estado = 'completado' LIMIT 1",
                    (id,)
                )
                if cursor.fetchone():
                    raise ValueError('No puedes editar una orden que ya tiene un pago completado.')

                accion = request.form.get('accion', '')
                item_id = request.form.get('item_id', type=int)
                item_actual = None
                if accion in {'actualizar', 'eliminar'}:
                    if not item_id or item_id < 1:
                        raise ValueError('Selecciona un artículo válido.')
                    cursor.execute(
                        'SELECT id, producto_id, cantidad, precio_unitario FROM orden_items '
                        'WHERE id = %s AND orden_id = %s FOR UPDATE',
                        (item_id, id)
                    )
                    item_actual = cursor.fetchone()
                    if not item_actual:
                        raise ValueError('El artículo ya no existe en esta orden.')
                elif accion != 'agregar':
                    raise ValueError('La acción solicitada no es válida.')

                producto_nuevo_id = None
                cantidad_nueva = None
                if accion != 'eliminar':
                    try:
                        producto_nuevo_id = int(request.form.get('producto_id', ''))
                        cantidad_nueva = int(request.form.get('cantidad', ''))
                    except (TypeError, ValueError):
                        raise ValueError('Selecciona un producto y una cantidad válidos.')
                    if producto_nuevo_id < 1 or not 1 <= cantidad_nueva <= 99:
                        raise ValueError('La cantidad debe estar entre 1 y 99.')

                producto_anterior_id = item_actual['producto_id'] if item_actual else None
                ids_producto = sorted({
                    producto_id for producto_id in (producto_anterior_id, producto_nuevo_id)
                    if producto_id is not None
                })
                productos_bloqueados = {}
                for producto_id in ids_producto:
                    cursor.execute(
                        'SELECT id, nombre, precio, stock, activo, estado_revision '
                        'FROM productos WHERE id = %s FOR UPDATE',
                        (producto_id,)
                    )
                    producto = cursor.fetchone()
                    if not producto:
                        raise ValueError('Uno de los productos ya no existe.')
                    productos_bloqueados[producto_id] = producto

                if accion != 'eliminar':
                    producto_nuevo = productos_bloqueados[producto_nuevo_id]
                    if producto_nuevo_id != producto_anterior_id and (
                        not producto_nuevo['activo']
                        or producto_nuevo['estado_revision'] != 'aprobado'
                    ):
                        raise ValueError('Solo puedes agregar productos activos y aprobados.')

                    stock_disponible = int(producto_nuevo['stock'] or 0)
                    if producto_nuevo_id == producto_anterior_id:
                        stock_disponible += int(item_actual['cantidad'])
                    if stock_disponible < cantidad_nueva:
                        raise ValueError(
                            f"No hay suficiente inventario de {producto_nuevo['nombre']}."
                        )

                    if producto_anterior_id is not None and producto_anterior_id != producto_nuevo_id:
                        cursor.execute(
                            'UPDATE productos SET stock = stock + %s WHERE id = %s',
                            (item_actual['cantidad'], producto_anterior_id)
                        )
                    if producto_nuevo_id == producto_anterior_id:
                        diferencia_stock = int(item_actual['cantidad']) - cantidad_nueva
                        if diferencia_stock:
                            cursor.execute(
                                'UPDATE productos SET stock = stock + %s WHERE id = %s',
                                (diferencia_stock, producto_nuevo_id)
                            )
                    else:
                        cursor.execute(
                            'UPDATE productos SET stock = stock - %s WHERE id = %s',
                            (cantidad_nueva, producto_nuevo_id)
                        )

                    precio_unitario = (
                        Decimal(str(item_actual['precio_unitario']))
                        if producto_nuevo_id == producto_anterior_id
                        else Decimal(str(producto_nuevo['precio']))
                    )
                    if not precio_unitario.is_finite() or precio_unitario < 0:
                        raise ValueError('El precio del producto no es válido.')
                    subtotal_item = (precio_unitario * cantidad_nueva).quantize(
                        Decimal('0.01'), rounding=ROUND_HALF_UP
                    )
                    if accion == 'agregar':
                        cursor.execute('''
                            INSERT INTO orden_items
                                (orden_id, producto_id, nombre_producto, cantidad, precio_unitario, subtotal)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        ''', (
                            id, producto_nuevo_id, producto_nuevo['nombre'],
                            cantidad_nueva, precio_unitario, subtotal_item
                        ))
                        flash('Artículo agregado y stock actualizado.', 'success')
                    else:
                        cursor.execute('''
                            UPDATE orden_items
                            SET producto_id = %s, nombre_producto = %s, cantidad = %s,
                                precio_unitario = %s, subtotal = %s
                            WHERE id = %s AND orden_id = %s
                        ''', (
                            producto_nuevo_id, producto_nuevo['nombre'], cantidad_nueva,
                            precio_unitario, subtotal_item, item_id, id
                        ))
                        flash('Artículo actualizado y stock ajustado.', 'success')
                else:
                    cursor.execute(
                        'UPDATE productos SET stock = stock + %s WHERE id = %s',
                        (item_actual['cantidad'], producto_anterior_id)
                    )
                    cursor.execute(
                        'DELETE FROM orden_items WHERE id = %s AND orden_id = %s',
                        (item_id, id)
                    )
                    flash('Artículo eliminado y stock restaurado.', 'success')

                cursor.execute(
                    'SELECT COALESCE(SUM(subtotal), 0) AS subtotal FROM orden_items WHERE orden_id = %s',
                    (id,)
                )
                subtotal_orden = Decimal(str(cursor.fetchone()['subtotal'] or 0)).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                )
                envio = Decimal(str(orden_bloqueada['envio'] or 0))
                descuento = Decimal(str(orden_bloqueada['descuento'] or 0))
                total_orden = max(
                    Decimal('0.00'), subtotal_orden + envio - descuento
                ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                cursor.execute(
                    'UPDATE ordenes SET subtotal = %s, total = %s WHERE id = %s',
                    (subtotal_orden, total_orden, id)
                )
                conn.commit()
                return redirect(url_for('detalle_pedido', id=id))
            except (InvalidOperation, ValueError, TypeError) as err:
                conn.rollback()
                flash(str(err), 'error')
                return redirect(url_for('detalle_pedido', id=id))

        cursor.execute("""
            SELECT o.*, u.nombre_completo AS cliente_nombre, u.email AS cliente_email,
                   u.username AS cliente_usuario
            FROM ordenes o
            JOIN usuarios u ON o.usuario_id = u.id
            WHERE o.id = %s
        """, (id,))
        pedido = cursor.fetchone()

        if not pedido:
            flash("La orden solicitada no existe.", "error")
            return redirect(url_for('admin_pedidos_envios'))

        # 2. Obtener los ítems de la orden
        cursor.execute("""
            SELECT oi.id, oi.orden_id, oi.producto_id, oi.nombre_producto,
                   oi.cantidad, oi.precio_unitario, oi.subtotal,
                   p.nombre AS catalogo_nombre, p.imagen_principal
            FROM orden_items oi
            LEFT JOIN productos p ON p.id = oi.producto_id
            WHERE oi.orden_id = %s
            ORDER BY oi.id ASC
        """, (id,))
        items = cursor.fetchall()

        # 3. Obtener el estado del pago asociado
        cursor.execute("""
            SELECT * FROM pagos WHERE orden_id = %s
        """, (id,))
        pago = cursor.fetchone()
        cursor.execute(
            "SELECT id FROM pagos WHERE orden_id = %s AND estado = 'completado' LIMIT 1",
            (id,)
        )
        tiene_pago_completado = cursor.fetchone() is not None
        cursor.execute(
            'SELECT id, nombre, precio, stock, activo, estado_revision '
            'FROM productos ORDER BY nombre ASC'
        )
        productos_disponibles = cursor.fetchall()

    except sqlite3.Error as err:
        conn.rollback()
        print(f"Error al cargar detalle de orden: {err}")
        flash("Error al cargar los detalles de la orden.", "error")
        return redirect(url_for('admin_pedidos_envios'))
    finally:
        cursor.close()
        conn.close()

    return render_template(
        'admin/detalle_pedido.html',
        pedido=pedido,
        items=items,
        pago=pago,
        productos_disponibles=productos_disponibles,
        editable_items=pedido['estado'] == 'pendiente' and not tiene_pago_completado,
        tiene_pago_completado=tiene_pago_completado,
    )

@app.route('/admin/facturas')
@admin_required
def admin_facturas():
    return redirect(url_for('facturas'))

@app.route('/admin/pagos')
@admin_required
def admin_pagos():
    return redirect(url_for('facturas'))

@app.route('/admin/inventario')
@admin_required
def admin_inventario():
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión a la base de datos.", "error")
        return redirect(url_for('index'))

    busqueda = request.args.get('busqueda', '').strip()
    orden = request.args.get('orden', 'id_asc')

    try:
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT p.id, p.nombre, p.sku, p.precio, p.stock, p.activo, p.categoria_id, c.nombre AS categoria_nombre
            FROM productos p
            LEFT JOIN categorias c ON p.categoria_id = c.id
        """
        params = []

        if busqueda:
            query += " WHERE p.nombre LIKE %s OR p.sku LIKE %s OR p.id LIKE %s"
            pattern = f"%{busqueda}%"
            params = [pattern, pattern, pattern]

        # Diccionario seguro de cláusulas de ordenamiento SQL
        ordenes_sql = {
            'id_asc': " ORDER BY p.id ASC",
            'id_desc': " ORDER BY p.id DESC",
            'precio_asc': " ORDER BY p.precio ASC",
            'precio_desc': " ORDER BY p.precio DESC",
            'stock_asc': " ORDER BY p.stock ASC",
            'stock_desc': " ORDER BY p.stock DESC",
            'nombre_asc': " ORDER BY p.nombre ASC",
            'nombre_desc': " ORDER BY p.nombre DESC"
        }

        # Aplica el orden seleccionado o usa id_asc por defecto
        query += ordenes_sql.get(orden, " ORDER BY p.id ASC")

        cursor.execute(query, params)
        productos = cursor.fetchall()

    except sqlite3.Error as err:
        print(f"Error al cargar inventario: {err}")
        flash("Error al cargar el inventario.", "error")
        productos = []
    finally:
        cursor.close()
        conn.close()

    return render_template('admin/inventario.html', productos=productos, busqueda=busqueda, orden=orden)



def crear_slug(texto):
    texto = texto.lower().strip()
    texto = re.sub(r'[^\w\s-]', '', texto)
    return re.sub(r'[\s_-]+', '-', texto)

# RUTA 2: Crear / Editar Producto y Control de Stock
@app.route('/admin/inventario/editar/<int:id>', methods=['GET', 'POST'])
@admin_required
def editar_inventario(id):
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión a la base de datos.", "error")
        return redirect(url_for('admin_inventario'))

    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        # Procesar eliminación rápida
        if request.form.get('accion') == 'eliminar':
            try:
                cursor.execute("SELECT id FROM detalle_factura WHERE producto_id = %s LIMIT 1", (id,))
                tiene_facturas = cursor.fetchone()
                cursor.execute("SELECT id FROM orden_items WHERE producto_id = %s LIMIT 1", (id,))
                tiene_ordenes = cursor.fetchone()
                if tiene_facturas or tiene_ordenes:
                    flash("No puedes eliminar un producto incluido en facturas u órdenes.", "warning")
                else:
                    cursor.execute("DELETE FROM productos WHERE id = %s", (id,))
                    if cursor.rowcount:
                        conn.commit()
                        flash("Producto eliminado del inventario.", "success")
                    else:
                        flash("El producto ya no existe.", "warning")
            except sqlite3.Error as err:
                conn.rollback()
                print(f"Error eliminando producto del inventario: {err}")
                flash("No se pudo eliminar el producto.", "error")
            finally:
                cursor.close()
                conn.close()
            return redirect(url_for('admin_inventario'))

        try:
            nombre = request.form.get('nombre', '').strip()
            categoria_id = int(request.form.get('categoria_id', ''))
            precio = Decimal(request.form.get('precio', ''))
            stock = int(request.form.get('stock', '0'))
            if not nombre or categoria_id < 1 or stock < 0 or not precio.is_finite() or precio < 0:
                raise ValueError
            slug = crear_slug(nombre)
            descripcion_corta = request.form.get('descripcion_corta', '').strip()
            marca = request.form.get('marca', '').strip()
            sku = request.form.get('sku', '').strip() or None
            activo = 1 if request.form.get('activo') else 0
            destacado = 1 if request.form.get('destacado') else 0

            if id == 0:
                cursor.execute("""
                    INSERT INTO productos (nombre, slug, descripcion_corta, categoria_id, marca, precio, stock, sku, activo, destacado)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (nombre, slug, descripcion_corta, categoria_id, marca, precio, stock, sku, activo, destacado))
                flash("Producto creado e ingresado al inventario con éxito.", "success")
            else:
                cursor.execute("""
                    UPDATE productos 
                    SET nombre = %s, slug = %s, descripcion_corta = %s, categoria_id = %s, marca = %s, 
                        precio = %s, stock = %s, sku = %s, activo = %s, destacado = %s
                    WHERE id = %s
                """, (nombre, slug, descripcion_corta, categoria_id, marca, precio, stock, sku, activo, destacado, id))
                flash("Inventario y producto actualizados correctamente.", "success")

            conn.commit()
            return redirect(url_for('admin_inventario'))

        except (InvalidOperation, ValueError, TypeError):
            conn.rollback()
            flash("Revisa el nombre, la categoría, el precio y el stock.", "error")
            return redirect(url_for('editar_inventario', id=id))
        except sqlite3.Error as err:
            conn.rollback()
            print(f"Error en CRUD de inventario: {err}")
            flash("No se pudo guardar el producto. Revisa que la categoría y el SKU sean válidos.", "error")
            return redirect(url_for('editar_inventario', id=id))
        finally:
            cursor.close()
            conn.close()

    # GET: Cargar datos actualizados
    producto = None
    if id > 0:
        cursor.execute("SELECT * FROM productos WHERE id = %s", (id,))
        producto = cursor.fetchone()
        if not producto:
            cursor.close()
            conn.close()
            flash("El producto no existe.", "warning")
            return redirect(url_for('admin_inventario'))

    cursor.execute("SELECT id, nombre FROM categorias ORDER BY nombre ASC")
    categorias = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('admin/editar_inventario.html', producto=producto, producto_id=id, categorias=categorias)


@app.route('/admin/contacto')
@admin_required
def admin_contacto():
    search = request.args.get('q', '').strip()[:120]
    conn = get_db_connection()
    if conn is None:
        flash("Error de conexion.", "error")
        return redirect(url_for('index'))

    try:
        cursor = conn.cursor(dictionary=True)
        query = "SELECT * FROM solicitudes_contacto WHERE respuesta IS NULL"
        parameters = []
        if search:
            query += " AND (CAST(id AS CHAR) LIKE %s OR motivo LIKE %s OR nombre LIKE %s OR correo LIKE %s OR mensaje LIKE %s)"
            parameters = [f'%{search}%'] * 5
        cursor.execute(query + " ORDER BY fecha_envio DESC", parameters)
        mensajes = cursor.fetchall()
    except sqlite3.Error as err:
        print(f"Error cargando mensajes: {err}")
        mensajes = []
    finally:
        cursor.close()
        conn.close()

    return render_template('admin/contacto.html', mensajes=mensajes, search=search)


@app.route('/admin/responder_contacto/<int:msg_id>', methods=['POST'])
@admin_required
def responder_contacto(msg_id):
    respuesta = request.form.get('respuesta', '').strip()
    if not respuesta:
        flash('La respuesta no puede estar vacia.', 'error')
        return redirect(url_for('admin_contacto'))

    conn = get_db_connection()
    if conn is None:
        flash("Error de conexion.", "error")
        return redirect(url_for('admin_contacto'))

    try:
        cursor = conn.cursor()
        query = """
            UPDATE solicitudes_contacto 
            SET respuesta = %s, fecha_respuesta = NOW() WHERE id = %s
        """
        cursor.execute(query, (respuesta, msg_id))
        conn.commit()
        flash('Respuesta enviada con exito!', 'success')
    except sqlite3.Error as err:
        conn.rollback()
        print(f"Error al responder contacto: {err}")
        flash('Hubo un error al enviar la respuesta.', 'error')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin_contacto'))


@app.route('/admin/soporte')
@admin_required
def admin_soporte():
    search = request.args.get('q', '').strip()[:120]
    conn = get_db_connection()
    if conn is None:
        flash("Error de conexion.", "error")
        return redirect(url_for('index'))

    try:
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT s.id, s.motivo, s.mensaje, s.fecha_envio, s.respuesta, u.username 
            FROM soporte_tecnico s
            JOIN usuarios u ON s.usuario_id = u.id
        """
        parameters = []
        if search:
            query += """ WHERE CAST(s.id AS CHAR) LIKE %s OR s.motivo LIKE %s
                         OR s.mensaje LIKE %s OR s.respuesta LIKE %s OR u.username LIKE %s"""
            parameters = [f'%{search}%'] * 5
        cursor.execute(query + " ORDER BY s.fecha_envio DESC", parameters)
        tickets = cursor.fetchall()
    except sqlite3.Error as err:
        print(f"Error cargando soporte: {err}")
        tickets = []
    finally:
        cursor.close()
        conn.close()

    return render_template('admin/soporte.html', tickets=tickets, search=search)


@app.route('/admin/soporte/responder/<int:ticket_id>', methods=['POST'])
@admin_required
def responder_soporte(ticket_id):
    respuesta = request.form.get('respuesta', '').strip()
    if not respuesta:
        flash('La respuesta no puede estar vacia.', 'error')
        return redirect(url_for('admin_soporte'))

    conn = get_db_connection()
    if conn is None:
        flash("Error de conexion.", "error")
        return redirect(url_for('admin_soporte'))

    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE soporte_tecnico SET respuesta = %s, fecha_respuesta = NOW() WHERE id = %s
        """, (respuesta, ticket_id))
        conn.commit()
        flash('Respuesta enviada correctamente.', 'success')
    except sqlite3.Error as err:
        conn.rollback()
        print(f"Error al responder soporte: {err}")
        flash('Hubo un error al enviar la respuesta.', 'error')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin_soporte'))


@app.route('/admin/eliminar_mensaje/<string:origen>/<int:id_msg>', methods=['POST'])
@admin_required
def eliminar_mensaje(origen, id_msg):
    tabla = "soporte_tecnico" if origen == "soporte" else "solicitudes_contacto"
    redirect_url = 'admin_soporte' if origen == "soporte" else 'admin_contacto'

    conn = get_db_connection()
    if conn is None:
        flash("Error de conexion.", "error")
        return redirect(url_for(redirect_url))

    try:
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM {tabla} WHERE id = %s", (id_msg,))
        conn.commit()
        flash("Registro eliminado correctamente.", "success")
    except sqlite3.Error as err:
        conn.rollback()
        print(f"Error al eliminar registro: {err}")
        flash("No se pudo eliminar el registro.", "error")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for(redirect_url))


@app.route('/usuario/eliminar_notificacion/<string:origen>/<int:id_notif>', methods=['POST'])
@login_required
def eliminar_notificacion(origen, id_notif):
    usuario_id = session.get('user_id')
    tablas = {
        'soporte': 'soporte_tecnico',
        'contacto': 'solicitudes_contacto',
        'moderacion': 'notificaciones_moderacion',
        'productos': 'notificaciones_productos',
    }
    tabla = tablas.get(origen)
    if not tabla:
        flash("Origen de notificación no válido.", "error")
        return redirect(url_for('notificaciones'))

    conn = get_db_connection()
    if conn is None:
        flash("Error de conexion.", "error")
        return redirect(url_for('notificaciones'))

    try:
        if origen == 'productos':
            asegurar_tabla_notificaciones_productos(conn)
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM {tabla} WHERE id = %s AND usuario_id = %s", (id_notif, usuario_id))
        conn.commit()
        flash("Notificacion eliminada correctamente.", "success")
    except sqlite3.Error as err:
        conn.rollback()
        print(f"Error al eliminar notificacion: {err}")
        flash("No se pudo eliminar la notificacion.", "error")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('notificaciones'))



# 1. Ruta para solicitar la recuperación
# ==========================================
# RUTAS DE RECUPERACIÓN DE CONTRASEÑA
# ==========================================

@app.route('/recuperar', methods=['GET', 'POST'])
def recuperar_password():
    if request.method == 'POST':
        email = request.form.get('email')
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM usuarios WHERE email = %s", (email,))
            usuario = cursor.fetchone()
            cursor.close()
            conn.close()
        except Exception as e:
            print(">>> ERROR BD AL BUSCAR USUARIO:", str(e))
            usuario = None

        if usuario:
            token = serializer.dumps(email, salt='recuperar-password-salt')
            link = url_for('reset_password', token=token, _external=True)

            msg = Message('Restablecimiento de Contraseña - TENNISSEL', recipients=[email])
            
            msg.html = f'''
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
            </head>
            <body style="margin: 0; padding: 0; background-color: #0d1117; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #ffffff;">
                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; margin: 30px auto; background-color: #161b22; border: 1px solid #21262d; border-radius: 12px; overflow: hidden;">
                    <tr>
                        <td align="center" style="padding: 30px 20px 10px 20px; background-color: #161b22;">
                            <h1 style="color: #ffffff; font-size: 28px; font-weight: 800; letter-spacing: 2px; margin: 0;">
                                TENNIS<span style="color: #228B22;">SEL.</span>
                            </h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 20px 40px 30px 40px; text-align: center;">
                            <h2 style="color: #ffffff; font-size: 20px; font-weight: 600; margin-bottom: 15px;">¿Olvidaste tu contraseña?</h2>
                            <p style="color: #8b949e; font-size: 14px; line-height: 1.6; margin-bottom: 25px;">
                                Recibimos una solicitud para restablecer la contraseña de tu cuenta en <strong>TENNISSEL</strong>. Haz clic en el siguiente botón para continuar:
                            </p>
                            <div style="margin: 30px 0;">
                                <a href="{link}" target="_blank" style="background-color: #228B22; color: #000000; text-decoration: none; padding: 14px 28px; border-radius: 8px; font-weight: bold; font-size: 15px; display: inline-block; box-shadow: 0 4px 12px rgba(34,139,34,0.2);">
                                    Restablecer Contraseña
                                </a>
                            </div>
                            <p style="color: #8b949e; font-size: 12px; line-height: 1.5; margin-top: 25px;">
                                Si el botón no funciona, copia y pega el siguiente enlace en tu navegador:<br>
                                <a href="{link}" style="color: #228B22; word-break: break-all;">{link}</a>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 0 40px;">
                            <hr style="border: 0; border-top: 1px solid #21262d; margin: 0;">
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 20px 40px; text-align: center; background-color: #0d1117;">
                            <p style="color: #484f58; font-size: 12px; margin: 0; line-height: 1.4;">
                                Este enlace expira en <strong>1 hora</strong>.<br>
                                Si no solicitaste este cambio, puedes ignorar este mensaje de forma segura.
                            </p>
                            <p style="color: #30363d; font-size: 11px; margin-top: 15px;">
                                &copy; TENNISSEL. Todos los derechos reservados.
                            </p>
                        </td>
                    </tr>
                </table>
            </body>
            </html>
            '''
            
            try:
                mail.send(msg)
                flash('Hemos enviado un enlace de recuperación a tu correo electrónico.', 'info')
                return redirect(url_for('login'))
            except Exception as e:
                print(">>> ERROR AL ENVIAR CORREO:", str(e))
                flash('Error al enviar el correo. Inténtalo de nuevo.', 'danger')
        else:
            flash('No existe ninguna cuenta asociada a este correo electrónico.', 'warning')

    return render_template('recuperar_password.html')


@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = serializer.loads(token, salt='recuperar-password-salt', max_age=3600)
    except (SignatureExpired, BadTimeSignature):
        session.pop('recovery_token', None)
        flash('El enlace es inválido o ha expirado. Por favor solicita uno nuevo.', 'danger')
        return redirect(url_for('recuperar_password'))

    session['recovery_token'] = token

    if request.method == 'POST':
        nueva_password = request.form.get('password')
        password_hashed = generate_password_hash(nueva_password)

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            query = "UPDATE usuarios SET password = %s WHERE email = %s"
            cursor.execute(query, (password_hashed, email))
            conn.commit()

            cursor.close()
            conn.close()

            session.pop('recovery_token', None)

            flash('¡Tu contraseña se ha actualizado correctamente! Ya puedes iniciar sesión.', 'success')
            return redirect(url_for('login'))

        except Exception as e:
            print(">>> ERROR BD AL ACTUALIZAR CONTRASEÑA:", str(e))
            flash('Ocurrió un error al actualizar la contraseña en la base de datos.', 'danger')

    return render_template('reset_password.html', token=token)

    #MAPAS PERRAS 

@app.post('/comentario/<int:comentario_id>/calificar')
@login_required
@not_banned_required
def calificar_comentario_mapa(comentario_id):
    try:
        calificacion = int(request.form.get('calificacion', 0))
    except (TypeError, ValueError):
        calificacion = 0
    if calificacion not in range(1, 6):
        flash('La valoración debe estar entre 1 y 5.', 'error')
        return redirect(request.referrer or url_for('mapas'))
    conn = get_db_connection()
    if not conn:
        flash('No fue posible guardar la valoración.', 'error')
        return redirect(request.referrer or url_for('mapas'))
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO comentarios_valoraciones (comentario_id, usuario_id, calificacion)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE calificacion = VALUES(calificacion), fecha = CURRENT_TIMESTAMP
        """, (comentario_id, session['user_id'], calificacion))
        conn.commit()
        flash('Valoración guardada.', 'success')
    except sqlite3.Error:
        conn.rollback()
        flash('No fue posible guardar la valoración.', 'error')
    finally:
        cursor.close()
        conn.close()
    return redirect(request.referrer or url_for('mapas'))


@app.route('/mapas', methods=['GET', 'POST'])
@login_required
@not_banned_required
def mapas():
    baneado, motivo_baneo = usuario_baneado(session['user_id'])
    if baneado:
        flash('Tu cuenta esta bloqueada por incumplir las normas de la comunidad.', 'error')
        return redirect(url_for('apelar_baneo'))

    es_usuario_gratuito = session.get('role') not in ('admin', 'premium') and not verificar_premium(session['user_id'])
    if request.method == 'GET' and es_usuario_gratuito and session.get('mapas_uso_gratuito'):
        flash('Si quieres tener acceso nuevamente, únete a Premium.', 'warning')
        return redirect(url_for('premium'))

    direccion = request.form.get('direccion', '')
    categoria = request.form.get('categoria', 'todos')
    
    mensaje_error = None
    mensaje_exito = None
    
    # Manejar POST requests
    if request.method == 'POST':
        action = request.form.get('action')
        
        # 1. Manejar Comentarios
        if action == 'comentar':
            loc_id = request.form.get('locacion_id')
            usuario_id = session['user_id']
            usuario = session.get('username', 'Usuario')
            comentario = request.form.get('comentario')
            estrellas = request.form.get('estrellas')
            if loc_id and comentario and estrellas and contiene_lenguaje_ofensivo(comentario):
                motivo = 'Lenguaje ofensivo detectado en una reseña.'
                banear_usuario_por_moderacion(usuario_id, motivo, comentario, loc_id)
                flash('Tu reseña fue eliminada y tu cuenta fue bloqueada automáticamente. Puedes apelar la decisión.', 'error')
                return redirect(url_for('apelar_baneo'))

            if loc_id and comentario and estrellas:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("INSERT INTO comentarios (locacion_id, usuario_id, nombre_usuario, comentario, estrellas) VALUES (%s, %s, %s, %s, %s)",
                            (loc_id, usuario_id, usuario, comentario, int(estrellas)))
                conn.commit()
                cur.close(); conn.close()
                mensaje_exito = f"✅ Comentario publicado correctamente por {usuario}."
                
        # 2. Manejar Reservas
        elif action == 'reservar':
            loc_id = request.form.get('locacion_id')
            usuario = request.form.get('usuario_reserva')
            fecha = request.form.get('fecha_reserva')
            hora = request.form.get('hora_reserva')
            hora_fin = request.form.get('hora_fin') or '23:59:59'
            
            if loc_id and usuario and fecha and hora:
                conn = get_db_connection()
                cur = conn.cursor(dictionary=True)
                asegurar_columna_hora_fin(conn)
                asegurar_columna_usuario_reserva(conn)
                cur.execute('SELECT COUNT(*) AS total FROM reservas WHERE user_id = %s AND fecha_reserva >= CURDATE()', (session['user_id'],))
                if cur.fetchone()['total'] >= 2:
                    mensaje_error = 'Cada usuario puede tener como máximo 2 reservas activas.'
                    cur.close(); conn.close()
                else:
                    # Revisar si ya existe reserva
                    cur.execute("""
                    SELECT * FROM reservas
                    WHERE locacion_id = %s AND fecha_reserva = %s
                      AND hora_reserva < %s
                      AND COALESCE(hora_fin, ADDTIME(hora_reserva, '01:00:00')) > %s
                    """, (loc_id, fecha, hora_fin, hora))
                    existe = cur.fetchone()
                
                if mensaje_error:
                    pass
                elif existe:
                    mensaje_error = f"⚠️ La cancha ya está reservada el {fecha} a las {hora}. Por favor, elige otro horario."
                elif hora_fin <= hora:
                    mensaje_error = "La hora final debe ser posterior a la hora inicial."
                else:
                    try:
                        cur.execute("INSERT INTO reservas (locacion_id, user_id, nombre_usuario, fecha_reserva, hora_reserva, hora_fin) VALUES (%s, %s, %s, %s, %s, %s)",
                                    (loc_id, session['user_id'], usuario, fecha, hora, hora_fin))
                        conn.commit()
                        mensaje_exito = f"🎾 ¡Reserva confirmada exitosamente para {usuario} el {fecha} a las {hora}!"
                    except Exception as err:
                        mensaje_error = f"Error al reservar: La cancha podría estar ocupada."
                
                cur.close(); conn.close()

    # Cargar todas las ubicaciones para que el filtro de reseñas sea independiente
    # del filtro de categoría utilizado para los marcadores del mapa.
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    asegurar_columna_hora_fin(conn)
    cur.execute("SELECT * FROM locaciones")
    locaciones = cur.fetchall()
    locaciones_mapa = (
        locaciones if categoria == 'todos'
        else [loc for loc in locaciones if loc['tipo'] == categoria]
    )
    
    # Obtener comentarios
    cur.execute("SELECT * FROM comentarios ORDER BY id DESC")
    todos_comentarios = cur.fetchall()
    cur.execute("""
        SELECT comentario_id, AVG(calificacion) AS promedio, COUNT(*) AS total
        FROM comentarios_valoraciones GROUP BY comentario_id
    """)
    valoraciones = {row['comentario_id']: row for row in cur.fetchall()}
    
    comentarios_por_locacion = {}
    for c in todos_comentarios:
        l_id = c['locacion_id']
        c['acuerdo_promedio'] = float(valoraciones.get(c['id'], {}).get('promedio') or 0)
        c['total_acuerdos'] = int(valoraciones.get(c['id'], {}).get('total') or 0)
        if l_id not in comentarios_por_locacion:
            comentarios_por_locacion[l_id] = []
        comentarios_por_locacion[l_id].append(c)

    for comentarios in comentarios_por_locacion.values():
        comentarios.sort(key=lambda comentario: (comentario['total_acuerdos'], comentario['acuerdo_promedio']), reverse=True)
    
    # Obtener promedio de estrellas
    cur.execute("SELECT locacion_id, AVG(estrellas) as prom FROM comentarios GROUP BY locacion_id")
    promedios = {row['locacion_id']: round(row['prom'], 1) for row in cur.fetchall()}
    
    # Consultar todas las reservas para el panel lateral
    cur.execute("""
        SELECT r.id, r.nombre_usuario, r.fecha_reserva, r.hora_reserva, r.hora_fin, l.nombre AS nombre_cancha
        FROM reservas r
        JOIN locaciones l ON r.locacion_id = l.id
        ORDER BY r.fecha_reserva, r.hora_reserva
    """)
    reservas_lista = cur.fetchall()
    
    cur.close(); conn.close()

    # Resolver la ubicación antes de crear el mapa para que el centro inicial sea correcto.
    posicion_usuario = None

    if direccion:
        try:
            coordenadas = [parte.strip() for parte in direccion.split(',')]
            if len(coordenadas) == 2:
                latitud = float(coordenadas[0])
                longitud = float(coordenadas[1])
                if -90 <= latitud <= 90 and -180 <= longitud <= 180:
                    posicion_usuario = (latitud, longitud)
            else:
                geolocator = ArcGIS(user_agent="tennisel_app")
                ubicacion = geolocator.geocode(f"{direccion}, Bogotá, Colombia")
                if ubicacion:
                    posicion_usuario = (ubicacion.latitude, ubicacion.longitude)
        except Exception as e:
            print("Error geocoder:", e)

    mapa = folium.Map(
        location=list(posicion_usuario or (4.6650, -74.0850)),
        zoom_start=14 if posicion_usuario else 12,
        width='100%',
        height='100%',
        control_scale=True,
    )

    puntos_visibles = [(float(loc['lat']), float(loc['lng'])) for loc in locaciones_mapa]
    if posicion_usuario:
        puntos_visibles.append(posicion_usuario)
    if len(puntos_visibles) > 1:
        folium.FitBounds(
            puntos_visibles,
            padding_top_left=(28, 28),
            padding_bottom_right=(28, 28),
            max_zoom=16,
        ).add_to(mapa)
    elif len(puntos_visibles) == 1:
        mapa.location = list(puntos_visibles[0])
        mapa.zoom_start = 15

    if posicion_usuario:
        folium.Marker(
            posicion_usuario,
            popup="Tu ubicación",
            tooltip="Tu ubicación",
            icon=folium.Icon(color="red", icon="user")
        ).add_to(mapa)

    colores = {'cancha': 'green', 'tienda': 'gray', 'bar': 'orange'}
    iconos = {'cancha': '🎾', 'tienda': '🛍️', 'bar': '🍻'}

    locaciones_mapa_ids = {loc['id'] for loc in locaciones_mapa}

    for loc in locaciones:
        loc['comentarios_lista'] = comentarios_por_locacion.get(loc['id'], [])
        lat, lng = float(loc['lat']), float(loc['lng'])
        distancia_km = geodesic(posicion_usuario, (lat, lng)).kilometers if posicion_usuario else None
        promedio = promedios.get(loc['id'])
        calidad = float(promedio) if promedio is not None else float(str(loc.get('estrellas', '')).count('⭐'))
        loc['distancia_km'] = distancia_km
        loc['calidad'] = calidad
        dist = f"<br><b>Distancia:</b> {distancia_km:.1f} km" if distancia_km is not None else ""
        prom_estrellas = f"{calidad:.1f}/5" if promedio is not None else f"{int(calidad)}/5"
        
        # Formulario inyectado en el mapa
        if loc['tipo'] == 'cancha':
            form_reserva = f"""
            <form action="/mapas" method="POST" target="_parent" style="margin-top:10px; display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:7px; width:100%; box-sizing:border-box;">
                <input type="hidden" name="action" value="reservar">
                <input type="hidden" name="locacion_id" value="{loc['id']}">
                <input type="hidden" name="direccion" value="{direccion}">
                <input type="hidden" name="categoria" value="{categoria}">
                <input type="text" name="usuario_reserva" placeholder="Tu nombre" required style="grid-column:1/-1; min-width:0; width:100%; box-sizing:border-box; padding:8px; border-radius:6px; border:1px solid #35443a; color:#f4f7f5; background:#18211b; font-size:12px; font-family:sans-serif;">
                <input type="date" name="fecha_reserva" required style="grid-column:1/-1; min-width:0; width:100%; box-sizing:border-box; padding:8px; border-radius:6px; border:1px solid #35443a; color:#f4f7f5; background:#18211b; font-size:12px; font-family:sans-serif;">
                <input type="time" name="hora_reserva" step="3600" required style="min-width:0; width:100%; box-sizing:border-box; padding:8px; border-radius:6px; border:1px solid #35443a; color:#f4f7f5; background:#18211b; font-size:12px; font-family:sans-serif;">
                <input type="time" name="hora_fin" step="3600" required style="min-width:0; width:100%; box-sizing:border-box; padding:8px; border-radius:6px; border:1px solid #35443a; color:#f4f7f5; background:#18211b; font-size:12px; font-family:sans-serif;">
                <button type="submit" style="grid-column:1/-1; background:#00d95a; color:#06120a; border:none; padding:9px; border-radius:7px; cursor:pointer; font-weight:bold; width:100%; margin-top:2px;">Reservar Cancha</button>
            </form>
            """
        else:
            form_reserva = ""
        
        html = f"""
        <div style="font-family:Arial,sans-serif; width:290px; max-width:calc(100vw - 64px); max-height:65vh; overflow-y:auto; box-sizing:border-box; background:#111713; color:#fff; padding:12px; border:1px solid #39ff14; border-radius:12px;">
            <img src="{url_for('proxy_imagen', url=loc.get('imagen_url', ''))}" onerror="this.onerror=null; this.src='https://images.unsplash.com/photo-1595435934249-5df7ed86e1c0?auto=format&fit=crop&w=500&q=70';" style="display:block; width:100%; height:130px; object-fit:cover; border-radius:8px; margin-bottom:10px;">
            <h4 style="color:#39ff14; margin:0; font-size:16px; line-height:1.35; overflow-wrap:anywhere;">{iconos.get(loc['tipo'], '📍')} {loc['nombre']}</h4>
            <hr style="border-color:#39ff14; margin:10px 0;">
            <small style="font-size:12px; line-height:1.6; overflow-wrap:anywhere;"><b>Dir:</b> {loc['direccion']}<br>
            <b>Precio:</b> {loc['precio_aprox']}<br>
            <b>Rating:</b> ⭐ {prom_estrellas}</small>
            {dist}
            {form_reserva}
        </div>
        """
        if loc['id'] in locaciones_mapa_ids:
            folium.Marker([lat, lng], popup=folium.Popup(html, max_width=330),
                          icon=folium.Icon(color=colores.get(loc['tipo'], 'blue'))).add_to(mapa)

    if es_usuario_gratuito and request.method == 'GET':
        session['mapas_uso_gratuito'] = True

    return render_template('mapas.html',
                           mapa_widget=mapa.get_root().render(),
                           locaciones=locaciones,
                           reservas=reservas_lista,
                           mensaje_error=mensaje_error,
                           mensaje_exito=mensaje_exito)


import math

def api_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Debes iniciar sesion.'}), 401
        baneado, motivo = usuario_baneado(session['user_id'])
        if baneado:
            return jsonify({'error': 'Tu cuenta esta bloqueada.', 'motivo': motivo}), 403
        if session.get('role') not in ('admin', 'profesor') and not verificar_premium(session['user_id']):
            return jsonify({'error': 'El chat y el matchmaking requieren Premium.'}), 403
        return f(*args, **kwargs)
    return decorated_function

def haversine(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2): return 9999.0
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)

@app.route('/api/radar', methods=['GET'])
@api_login_required
def obtener_radar():
    user_id = session['user_id']
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'No se pudo conectar a la base de datos.'}), 503
    cursor = conn.cursor(dictionary=True)
    try:
        asegurar_tabla_bloqueos_usuarios(conn)
        cursor.execute('''
            SELECT p.lat, p.lng FROM perfil_usuario p WHERE p.usuario_id = %s
        ''', (user_id,))
        mi_ubi = cursor.fetchone() or {}
        cursor.execute('''
            SELECT u.id, COALESCE(u.nombre_completo, u.username) AS nombre, p.foto, p.biografia, u.ciudad AS barrio, p.ubicacion_texto, p.lat, p.lng, p.nivel, u.rol
            FROM usuarios u
            LEFT JOIN perfil_usuario p ON p.usuario_id = u.id
            WHERE u.id <> %s AND (p.compartir = 1 OR p.id IS NULL)
              AND u.rol NOT IN ('admin', 'profesor') AND u.baneado = 0
              AND NOT EXISTS (
                  SELECT 1 FROM bloqueos_usuarios b
                  WHERE (b.bloqueador_id = %s AND b.bloqueado_id = u.id)
                     OR (b.bloqueador_id = u.id AND b.bloqueado_id = %s)
              )
        ''', (user_id, user_id, user_id))
        otros = cursor.fetchall()
        resultados = []
        for usuario in otros:
            distancia = haversine(mi_ubi.get('lat'), mi_ubi.get('lng'), usuario['lat'], usuario['lng'])
            cursor.execute('''
                SELECT id, emisor_id, receptor_id, estado FROM contacts
                WHERE (emisor_id = %s AND receptor_id = %s) OR (emisor_id = %s AND receptor_id = %s)
                ORDER BY id DESC LIMIT 1
            ''', (user_id, usuario['id'], usuario['id'], user_id))
            contacto = cursor.fetchone()
            estado = 'ninguno'
            if contacto:
                estado = 'aceptado' if contacto['estado'] == 'aceptada' else ('enviado' if contacto['emisor_id'] == user_id else 'recibido')
            resultados.append({
                'id': usuario['id'], 'nombre': usuario['nombre'],
                'foto': foto_perfil_url(usuario['foto']),
                'biografia': usuario.get('biografia') or '',
                'rol': usuario['rol'],
                'ubicacion_texto': usuario['barrio'] or 'Zona no indicada',
                'distancia_km': distancia, 'nivel': usuario['nivel'],
                'estado_chat': estado, 'contacto_id': contacto['id'] if contacto else None
            })
        resultados.sort(key=lambda item: item['distancia_km'])
        return jsonify(resultados)
    finally:
        cursor.close()
        conn.close()

@app.route('/api/matchmaking/usuarios', methods=['GET'])
@api_login_required
def matchmaking_usuarios():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'No se pudo conectar a la base de datos.'}), 503
    cursor = conn.cursor(dictionary=True)
    try:
        asegurar_tabla_bloqueos_usuarios(conn)
        if session.get('role') == 'admin':
            role_filter = "AND u.rol <> 'admin'"
            admin_contact_params = ()
        else:
            role_filter = """AND (
                u.rol NOT IN ('admin', 'profesor')
                OR (u.rol = 'admin' AND EXISTS (
                    SELECT 1 FROM contacts c
                    WHERE c.estado = 'aceptada'
                      AND ((c.emisor_id = %s AND c.receptor_id = u.id)
                           OR (c.emisor_id = u.id AND c.receptor_id = %s))
                ))
            )"""
            admin_contact_params = (session['user_id'], session['user_id'])
        cursor.execute(f'''
            SELECT u.id, COALESCE(u.nombre_completo, u.username) AS nombre, u.rol,
                   u.ciudad AS barrio, p.foto, p.biografia, p.nivel, p.mano, p.reves
            FROM usuarios u LEFT JOIN perfil_usuario p ON p.usuario_id = u.id
                        WHERE u.id <> %s AND u.baneado = 0
                            {role_filter}
                            AND NOT EXISTS (
                                SELECT 1 FROM bloqueos_usuarios b
                                WHERE (b.bloqueador_id = %s AND b.bloqueado_id = u.id)
                                   OR (b.bloqueador_id = u.id AND b.bloqueado_id = %s)
                            )
            ORDER BY u.username
        ''', (session['user_id'], *admin_contact_params, session['user_id'], session['user_id']))
        usuarios = cursor.fetchall()
        for usuario in usuarios:
            usuario['foto'] = foto_perfil_url(usuario.get('foto'))
            cursor.execute('''
                SELECT id, emisor_id, estado FROM contacts
                WHERE (emisor_id = %s AND receptor_id = %s) OR (emisor_id = %s AND receptor_id = %s)
                ORDER BY id DESC LIMIT 1
            ''', (session['user_id'], usuario['id'], usuario['id'], session['user_id']))
            contacto = cursor.fetchone()
            usuario['contacto_id'] = contacto['id'] if contacto else None
            usuario['estado_chat'] = 'ninguno' if not contacto else ('aceptado' if contacto['estado'] == 'aceptada' else ('enviado' if contacto['emisor_id'] == session['user_id'] else 'recibido'))
        return jsonify(usuarios)
    finally:
        cursor.close()
        conn.close()

@app.route('/api/profesores', methods=['GET'])
@api_login_required
def obtener_profesores():
    user_id = session['user_id']
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'No se pudo conectar a la base de datos.'}), 503
    cursor = conn.cursor(dictionary=True)
    try:
        asegurar_tabla_bloqueos_usuarios(conn)
        cursor.execute('''
                 SELECT u.id, COALESCE(u.nombre_completo, u.username) AS nombre,
                     p.foto, p.biografia, u.ciudad AS barrio, p.ubicacion_texto, p.nivel
                 FROM usuarios u LEFT JOIN perfil_usuario p ON p.usuario_id = u.id
                 WHERE u.id <> %s AND u.rol = 'profesor' AND u.baneado = 0
                   AND NOT EXISTS (
                       SELECT 1 FROM bloqueos_usuarios b
                       WHERE (b.bloqueador_id = %s AND b.bloqueado_id = u.id)
                          OR (b.bloqueador_id = u.id AND b.bloqueado_id = %s)
                   )
        ''', (user_id, user_id, user_id))
        profesores = cursor.fetchall()
        for profesor in profesores:
            profesor['foto'] = foto_perfil_url(profesor.get('foto'))
            cursor.execute('''
                SELECT id, emisor_id, receptor_id, estado FROM contacts
                WHERE (emisor_id = %s AND receptor_id = %s) OR (emisor_id = %s AND receptor_id = %s)
                ORDER BY id DESC LIMIT 1
            ''', (user_id, profesor['id'], profesor['id'], user_id))
            contacto = cursor.fetchone()
            profesor['estado_chat'] = 'ninguno'
            profesor['contacto_id'] = None
            if contacto:
                profesor['contacto_id'] = contacto['id']
                profesor['estado_chat'] = 'aceptado' if contacto['estado'] == 'aceptada' else ('enviado' if contacto['emisor_id'] == user_id else 'recibido')
        return jsonify(profesores)
    except Exception as err:
        print(f'Error cargando profesores: {err}')
        return jsonify({'error': 'No se pudieron cargar los profesores.'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/solicitar_chat', methods=['POST'])
@api_login_required
def solicitar_chat():
    try:
        receptor_id = int((request.get_json(silent=True) or {}).get('receptor_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Destinatario no válido.'}), 400
    if receptor_id <= 0 or receptor_id == session['user_id']:
        return jsonify({'error': 'Destinatario no valido.'}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'No se pudo conectar a la base de datos.'}), 503
    cursor = conn.cursor(dictionary=True)
    try:
        asegurar_tabla_bloqueos_usuarios(conn)
        cursor.execute("SELECT id FROM usuarios WHERE id = %s AND rol <> 'admin' AND baneado = 0", (receptor_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'El usuario no está disponible para conversar.'}), 404
        if usuarios_bloqueados(cursor, session['user_id'], receptor_id):
            return jsonify({'error': 'No puedes iniciar una conversación con este usuario.'}), 403
        cursor.execute('''
            SELECT id, emisor_id, estado FROM contacts
            WHERE (emisor_id = %s AND receptor_id = %s) OR (emisor_id = %s AND receptor_id = %s)
            ORDER BY id DESC LIMIT 1
        ''', (session['user_id'], receptor_id, receptor_id, session['user_id']))
        contacto = cursor.fetchone()
        if contacto:
            if contacto['estado'] != 'aceptada':
                cursor.execute("UPDATE contacts SET estado = 'aceptada' WHERE id = %s", (contacto['id'],))
                conn.commit()
            return jsonify({'status': 'accepted', 'contacto_id': contacto['id'], 'estado': 'aceptada'})
        cursor.execute("INSERT INTO contacts (emisor_id, receptor_id, estado) VALUES (%s, %s, 'aceptada')", (session['user_id'], receptor_id))
        conn.commit()
        return jsonify({'status': 'accepted', 'contacto_id': cursor.lastrowid, 'estado': 'aceptada'})
    except sqlite3.Error as err:
        conn.rollback()
        app.logger.exception('No se pudo iniciar una conversación de matchmaking: %s', err)
        return jsonify({'error': 'No se pudo iniciar la conversación.'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/contactos', methods=['GET'])
@api_login_required
def obtener_contactos():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'No se pudo conectar a la base de datos.'}), 503
    cursor = conn.cursor(dictionary=True)
    try:
        asegurar_tabla_bloqueos_usuarios(conn)
        cursor.execute('''
            SELECT u.id, u.username AS nombre, u.rol, p.foto, p.biografia, p.nivel,
                   c.id AS contacto_id, c.estado, c.emisor_id, c.receptor_id
            FROM contacts c
            JOIN usuarios u ON u.id = IF(c.emisor_id = %s, c.receptor_id, c.emisor_id)
            LEFT JOIN perfil_usuario p ON p.usuario_id = u.id
            WHERE (c.emisor_id = %s OR c.receptor_id = %s)
              AND NOT EXISTS (
                  SELECT 1 FROM bloqueos_usuarios b
                  WHERE (b.bloqueador_id = %s AND b.bloqueado_id = u.id)
                     OR (b.bloqueador_id = u.id AND b.bloqueado_id = %s)
              )
            ORDER BY u.username
        ''', (session['user_id'], session['user_id'], session['user_id'], session['user_id'], session['user_id']))
        contactos = cursor.fetchall()
        for contacto in contactos:
            contacto['foto'] = foto_perfil_url(contacto.get('foto'))
            contacto['estado_chat'] = 'aceptado' if contacto['estado'] == 'aceptada' else ('recibido' if contacto['receptor_id'] == session['user_id'] else 'enviado')
        return jsonify(contactos)
    finally:
        cursor.close()
        conn.close()

@app.route('/api/perfiles/<int:usuario_id>', methods=['GET'])
@api_login_required
def obtener_perfil_chat(usuario_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'No se pudo conectar a la base de datos.'}), 503
    cursor = conn.cursor(dictionary=True)
    try:
        asegurar_tabla_bloqueos_usuarios(conn)
        if usuario_id != session['user_id'] and usuarios_bloqueados(cursor, session['user_id'], usuario_id):
            return jsonify({'error': 'No puedes consultar el perfil de este usuario.'}), 403
        cursor.execute('''
                 SELECT u.id, u.username AS nombre, u.rol, u.ciudad AS barrio, p.foto, p.biografia, p.nivel,
                     p.mano, p.reves
            FROM usuarios u LEFT JOIN perfil_usuario p ON p.usuario_id = u.id
            WHERE u.id = %s
        ''', (usuario_id,))
        perfil = cursor.fetchone()
        if not perfil:
            return jsonify({'error': 'Perfil no encontrado.'}), 404
        perfil['foto'] = foto_perfil_url(perfil.get('foto'))
        return jsonify(perfil)
    finally:
        cursor.close()
        conn.close()

@app.route('/api/locaciones/canchas', methods=['GET'])
@api_login_required
def obtener_canchas_chat():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'No se pudo conectar a la base de datos.'}), 503
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute('''
            SELECT id, nombre, direccion, horario, telefono, precio_aprox, lat, lng
            FROM locaciones
            WHERE LOWER(TRIM(tipo)) = 'cancha'
            ORDER BY nombre
        ''')
        return jsonify(cursor.fetchall())
    finally:
        cursor.close()
        conn.close()

@app.route('/api/responder_solicitud', methods=['POST'])
@api_login_required
def responder_solicitud():
    data = request.json or {}
    estado = data.get('estado')
    if estado not in ('aceptada', 'rechazada'):
        return jsonify({'error': 'Estado no valido.'}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'No se pudo conectar a la base de datos.'}), 503
    cursor = conn.cursor()
    try:
        asegurar_tabla_bloqueos_usuarios(conn)
        cursor.execute('SELECT emisor_id FROM contacts WHERE id = %s AND receptor_id = %s', (data.get('contacto_id'), session['user_id']))
        solicitud = cursor.fetchone()
        if not solicitud:
            return jsonify({'error': 'La solicitud no está disponible.'}), 404
        if usuarios_bloqueados(cursor, session['user_id'], solicitud[0]):
            return jsonify({'error': 'No puedes aceptar la solicitud de este usuario.'}), 403
        cursor.execute('UPDATE contacts SET estado = %s WHERE id = %s AND receptor_id = %s', (estado, data.get('contacto_id'), session['user_id']))
        conn.commit()
        return jsonify({'status': 'success'})
    finally:
        cursor.close()
        conn.close()

@app.route('/api/mensajes/<int:otro_usuario_id>', methods=['GET'])
@api_login_required
def obtener_mensajes(otro_usuario_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'No se pudo conectar a la base de datos.'}), 503
    cursor = conn.cursor(dictionary=True)
    try:
        asegurar_tabla_bloqueos_usuarios(conn)
        if usuarios_bloqueados(cursor, session['user_id'], otro_usuario_id):
            return jsonify({'error': 'Esta conversación está bloqueada.'}), 403
        cursor.execute('''
            SELECT 1 FROM contacts
            WHERE estado = 'aceptada'
              AND ((emisor_id = %s AND receptor_id = %s)
                   OR (emisor_id = %s AND receptor_id = %s))
            LIMIT 1
        ''', (session['user_id'], otro_usuario_id, otro_usuario_id, session['user_id']))
        if session.get('role') != 'admin' and not cursor.fetchone():
            return jsonify({'error': 'Inicia la conversación antes de consultar los mensajes.'}), 403
        cursor.execute('''
            SELECT m.* FROM messages m
            WHERE (m.emisor_id = %s AND m.receptor_id = %s) OR (m.emisor_id = %s AND m.receptor_id = %s)
            ORDER BY m.enviado ASC
        ''', (session['user_id'], otro_usuario_id, otro_usuario_id, session['user_id']))
        response = jsonify(cursor.fetchall())
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        return response
    finally:
        cursor.close()
        conn.close()

@app.route('/api/enviar_mensaje', methods=['POST'])
@api_login_required
def enviar_mensaje():
    data = request.json or {}
    receptor_id = data.get('receptor_id')
    texto = (data.get('texto') or '').strip()
    if not receptor_id or not texto:
        return jsonify({'error': 'Mensaje incompleto.'}), 400
    try:
        receptor_id = int(receptor_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'El destinatario no es valido.'}), 400
    if receptor_id == session['user_id']:
        return jsonify({'error': 'No puedes enviarte un mensaje a ti mismo.'}), 400
    tipo = data.get('tipo', 'texto')
    if tipo not in ('texto', 'propuesta'):
        tipo = 'texto'
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'No se pudo conectar a la base de datos.'}), 503
    cursor = conn.cursor()
    try:
        asegurar_tabla_bloqueos_usuarios(conn)
        if usuarios_bloqueados(cursor, session['user_id'], receptor_id):
            return jsonify({'error': 'Esta conversación está bloqueada.'}), 403
        cursor.execute('''
            SELECT id, estado FROM contacts
            WHERE ((emisor_id = %s AND receptor_id = %s) OR (emisor_id = %s AND receptor_id = %s))
              AND estado = 'aceptada'
            LIMIT 1
        ''', (session['user_id'], receptor_id, receptor_id, session['user_id']))
        if session.get('role') != 'admin' and not cursor.fetchone():
            return jsonify({'error': 'Primero debes aceptar la conexión para enviar mensajes.'}), 403
        datos_extra = json.dumps(data.get('datos_extra', {})) if tipo == 'propuesta' else None
        cursor.execute('''
            INSERT INTO messages (emisor_id, receptor_id, texto, tipo, datos_extra, estado_propuesta)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (session['user_id'], receptor_id, texto, tipo, datos_extra, 'pendiente' if tipo == 'propuesta' else None))
        conn.commit()
        return jsonify({'status': 'success', 'mensaje_id': cursor.lastrowid})
    except sqlite3.Error as err:
        conn.rollback()
        print(f'Error enviando mensaje: {err}')
        return jsonify({'error': 'No se pudo guardar el mensaje. Revisa la tabla messages en la base de datos.'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/denunciar_mensaje', methods=['POST'])
@api_login_required
def denunciar_mensaje():
    data = request.json or {}
    try:
        mensaje_id = int(data.get('mensaje_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'El mensaje denunciado no es válido.'}), 400
    motivo = (data.get('motivo') or 'Lenguaje ofensivo o conducta inapropiada.').strip()[:255]
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'No se pudo conectar a la base de datos.'}), 503
    cursor = conn.cursor(dictionary=True)
    try:
        asegurar_tabla_bloqueos_usuarios(conn)
        cursor.execute('''
            SELECT emisor_id, receptor_id FROM messages
            WHERE id = %s AND (emisor_id = %s OR receptor_id = %s)
        ''', (mensaje_id, session['user_id'], session['user_id']))
        mensaje = cursor.fetchone()
        if not mensaje or mensaje['emisor_id'] == session['user_id']:
            return jsonify({'error': 'No puedes denunciar este mensaje.'}), 400
        denunciado_id = mensaje['emisor_id']
        cursor.execute('SELECT id FROM usuarios WHERE id = %s FOR UPDATE', (denunciado_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'El usuario denunciado ya no está disponible.'}), 404
        cursor.execute('''
            SELECT id FROM denuncias_mensajes
            WHERE mensaje_id = %s AND denunciante_id = %s AND estado <> 'descartada'
            LIMIT 1
        ''', (mensaje_id, session['user_id']))
        if cursor.fetchone():
            return jsonify({'error': 'Ya denunciaste este mensaje.'}), 409
        cursor.execute('''
            INSERT INTO denuncias_mensajes (mensaje_id, denunciante_id, denunciado_id, motivo)
            VALUES (%s, %s, %s, %s)
        ''', (mensaje_id, session['user_id'], mensaje['emisor_id'], motivo))
        cursor.execute('''
            INSERT IGNORE INTO bloqueos_usuarios (bloqueador_id, bloqueado_id)
            VALUES (%s, %s)
        ''', (session['user_id'], denunciado_id))
        cursor.execute('''
            SELECT COUNT(DISTINCT denunciante_id) AS total
            FROM denuncias_mensajes
            WHERE denunciado_id = %s AND estado = 'pendiente'
        ''', (denunciado_id,))
        denuncias_pendientes = cursor.fetchone()['total']
        suspendido = denuncias_pendientes >= 3
        if suspendido:
            cursor.execute('''
                UPDATE usuarios
                SET baneado = 1,
                    motivo_baneo = %s,
                    evidencia_baneo = %s,
                    fecha_baneo = NOW()
                WHERE id = %s
            ''', (
                'Suspensión automática: recibió denuncias de 3 usuarios distintos; pendiente de verificación administrativa.',
                'Denuncias pendientes de revisión en el panel de administración.',
                denunciado_id,
            ))
        conn.commit()
        return jsonify({
            'status': 'success',
            'blocked': True,
            'suspended': suspendido,
            'pending_reports': denuncias_pendientes,
        })
    except sqlite3.Error as err:
        conn.rollback()
        app.logger.exception('No se pudo guardar la denuncia ni bloquear la conversación: %s', err)
        return jsonify({'error': 'La denuncia no pudo guardarse.'}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/responder_propuesta', methods=['POST'])
@api_login_required
def responder_propuesta():
    data = request.json or {}
    accion = data.get('accion')
    if accion not in ('aceptada', 'rechazada'):
        return jsonify({'error': 'Accion no valida.'}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'No se pudo conectar a la base de datos.'}), 503
    cursor = conn.cursor(dictionary=True)
    try:
        asegurar_columna_hora_fin(conn)
        asegurar_columna_usuario_reserva(conn)
        cursor.execute('''
            SELECT emisor_id, receptor_id, datos_extra FROM messages
            WHERE id = %s AND receptor_id = %s AND tipo = 'propuesta' AND estado_propuesta = 'pendiente'
        ''', (data.get('mensaje_id'), session['user_id']))
        mensaje = cursor.fetchone()
        if not mensaje:
            return jsonify({'error': 'Propuesta no encontrada.'}), 404
        asegurar_tabla_bloqueos_usuarios(conn)
        if usuarios_bloqueados(cursor, mensaje['emisor_id'], mensaje['receptor_id']):
            return jsonify({'error': 'Esta conversación está bloqueada.'}), 403
        if accion == 'aceptada':
            propuesta = json.loads(mensaje['datos_extra'] or '{}')
            locacion_id = propuesta.get('locacion_id')
            fecha = propuesta.get('fecha_reserva')
            hora = propuesta.get('hora_reserva')
            try:
                duracion = int(propuesta.get('duracion', 1))
                hora_inicio = datetime.strptime(hora, '%H:%M')
            except (TypeError, ValueError):
                return jsonify({'error': 'La fecha, hora o duración de la propuesta no son válidas.'}), 400
            if not locacion_id or not fecha or not hora:
                return jsonify({'error': 'La propuesta no tiene datos de reserva completos.'}), 400
            if duracion not in (1, 2):
                return jsonify({'error': 'La propuesta debe durar 1 o 2 horas.'}), 400
            hora_fin = (hora_inicio + timedelta(hours=duracion)).strftime('%H:%M:%S')
            cursor.execute('''
                                SELECT id FROM reservas
                                WHERE locacion_id = %s AND fecha_reserva = %s
                                    AND hora_reserva < %s
                                    AND COALESCE(hora_fin, ADDTIME(hora_reserva, '01:00:00')) > %s
                        ''', (locacion_id, fecha, hora_fin, hora))
            if cursor.fetchone():
                return jsonify({'error': 'La cancha ya esta reservada en ese horario.'}), 409
            participantes = (session['user_id'], mensaje['emisor_id'])
            cursor.execute('''
                SELECT user_id, COUNT(*) AS total FROM reservas
                WHERE user_id IN (%s, %s) AND fecha_reserva >= CURDATE()
                GROUP BY user_id
            ''', participantes)
            reservas_por_usuario = {row['user_id']: row['total'] for row in cursor.fetchall()}
            if any(reservas_por_usuario.get(usuario_id, 0) >= 2 for usuario_id in participantes):
                return jsonify({'error': 'Uno de los participantes ya tiene el máximo de 2 reservas activas.'}), 409
            cursor.execute('SELECT id, username, nombre_completo FROM usuarios WHERE id IN (%s, %s)', participantes)
            nombres = {row['id']: (row['nombre_completo'] or row['username'] or 'Usuario') for row in cursor.fetchall()}
            cursor.execute('''
                INSERT INTO reservas (locacion_id, user_id, nombre_usuario, fecha_reserva, hora_reserva, hora_fin)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (locacion_id, session['user_id'], nombres.get(session['user_id'], session.get('username', 'Usuario')), fecha, hora, hora_fin))
            cursor.execute('''
                INSERT INTO reservas (locacion_id, user_id, nombre_usuario, fecha_reserva, hora_reserva, hora_fin)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (locacion_id, mensaje['emisor_id'], nombres.get(mensaje['emisor_id'], 'Profesor'), fecha, hora, hora_fin))
        cursor.execute('UPDATE messages SET estado_propuesta = %s WHERE id = %s', (accion, data.get('mensaje_id')))
        texto = 'La propuesta de clase fue aceptada.' if accion == 'aceptada' else 'La propuesta de clase fue rechazada.'
        cursor.execute('INSERT INTO messages (emisor_id, receptor_id, texto, tipo) VALUES (%s, %s, %s, "sistema")', (session['user_id'], mensaje['emisor_id'], texto))
        conn.commit()
        return jsonify({'status': 'success'})
    finally:
        cursor.close()
        conn.close()

# ==========================================
# RUTA CHATBOT (NUEVO)
# ==========================================
@app.route('/api/chatbot', methods=['POST'])
def chatbot():
    data = request.get_json(silent=True) or {}
    mensaje = str(data.get('mensaje', '')).strip().lower()
    pagina = str(data.get('pagina', '')).lower()
    if not mensaje:
        return jsonify({'respuesta': 'Escribe una pregunta y te ayudo con reservas, jugadores, entrenamientos, productos o tu cuenta.'})

    intenciones = [
        (('hola', 'buenas', 'saludos'), 'Hola. Soy Tenny, la asistente virtual de TENNISSEL. Puedo orientarte paso a paso sobre reservas, jugadores, profesores, entrenamientos, productos, torneos, Premium y tu cuenta.', None, None),
        (('mis reservas', 'mis reserva', 'agenda'), 'En Reservas puedes desplegar “Mis reservas” para revisar tus canchas, fechas y horarios. Desde cada tarjeta también puedes eliminar una reserva que ya no necesites.', 'reservas', 'Abrir Mis reservas'),
        (('reserva', 'reservar', 'cancha', 'horario'), 'Para reservar, selecciona una fecha, elige una cancha y pulsa un horario disponible. Después revisa el resumen, elige entre 1 o 2 horas y confirma con “Enviar reserva”.', 'reservas', 'Ir a Reservas'),
        (('jugador', 'jugadores', 'rival', 'matchmaking', 'pareja'), 'En Matchmaking puedes revisar los perfiles registrados, abrir su información y enviar una solicitud de chat. Cuando la otra persona acepte, podrán conversar.', 'matchmaking', 'Abrir Matchmaking'),
        (('profesor', 'entrenador', 'clase'), 'En Matchmaking puedes encontrar profesores, consultar su perfil y enviarles una propuesta de clase con cancha, fecha y hora. La propuesta queda dentro de la conversación.', 'matchmaking', 'Buscar profesores'),
        (('entrenamiento', 'entrenar', 'rutina', 'ejercicio'), 'La sección Entrenamiento organiza rutinas por día, objetivo, nivel y tipo de cuenta. Puedes consultar ejercicios de técnica, físico, táctica y recuperación.', 'entreno', 'Ver entrenamientos'),
        (('producto', 'comprar', 'tienda', 'raqueta', 'pelota', 'grip', 'zapatilla'), 'En Productos puedes buscar raquetas, pelotas, grips, ropa, calzado y tecnología. Usa los filtros de categoría, marca, talla, color y precio para encontrar una opción adecuada.', 'productos', 'Ver productos'),
        (('favorito', 'favoritos', 'lista de deseos', 'deseo', 'guardados'), 'En Productos puedes filtrar el mismo catálogo por Favoritos o Lista de deseos. Usa el corazón o el marcador de cada tarjeta para guardar o quitar artículos sin salir de la página.', 'productos', 'Abrir productos guardados'),
        (('busqueda reciente', 'búsqueda reciente', 'autocompletar', 'corregir búsqueda', 'error ortografico', 'error ortográfico'), 'Los buscadores de TENNISSEL sugieren secciones, productos, marcas y categorías desde el primer carácter. También puedes elegir una corrección sugerida o una búsqueda reciente.', 'productos', 'Buscar productos'),
        (('oferta', 'ofertas', 'descuento', 'promocion', 'promoción', 'temporizador'), 'Las ofertas con fecha de vencimiento muestran una cuenta regresiva. Al terminar, el sistema restaura automáticamente el precio habitual en la siguiente actualización de la página.', 'productos', 'Ver ofertas'),
        (('apple pay', 'google pay', 'google wallet', 'billetera digital'), 'Apple Pay y Google Pay todavía no procesan pagos en TENNISSEL: falta configurar y verificar una pasarela de pago. No introduzcas datos de tarjeta en formularios de la plataforma.', 'premium', 'Consultar planes'),
        (('cancelar premium', 'reembolso premium', 'cancelacion premium', 'cancelación premium', 'renovacion premium', 'renovación premium'), 'TENNISSEL aún no registra ciclos de facturación ni renovaciones Premium con una pasarela, por lo que no puede prorratear o cancelar renovaciones automáticamente. Contacta a soporte para revisar tu caso.', 'soporte_tecnico', 'Contactar soporte'),
        (('reembolso', 'devolucion', 'devolución', 'producto defectuoso'), 'Para productos físicos, la solicitud está disponible durante cinco días hábiles desde la entrega registrada. Se pide motivo y fotografía; administración revisa y registra manualmente la ejecución. No se procesa automáticamente por una pasarela.', 'mis_compras', 'Ver mis compras'),
        (('premium', 'suscripcion', 'suscripción', 'pago'), 'Premium habilita herramientas avanzadas como Matchmaking, Reservas y funciones especiales de la plataforma. La activación de pago está pendiente de configurar una pasarela segura; no se deben ingresar datos de tarjeta en TENNISSEL.', 'premium', 'Conocer Premium'),
        (('regla', 'puntuacion', 'puntuación', 'set', 'tie break'), 'La puntuación habitual de un game avanza 0, 15, 30 y 40. Un set normalmente se gana con seis juegos y diferencia de dos, aunque algunos formatos usan tie-break.', 'informacion_jugadores', 'Aprender sobre tenis'),
        (('torneo', 'torneos', 'grand slam', 'ranking'), 'En la sección informativa puedes seguir jugadores, torneos, rankings, partidos recientes, noticias semanales y datos para entender mejor el circuito.', 'informacion_jugadores', 'Ver información'),
        (('perfil', 'cuenta', 'contraseña', 'contrasena'), 'Desde el menú de perfil puedes actualizar tus datos, foto, nivel de juego, mano dominante, revés, ubicación y preferencias de visibilidad.', 'editarperfil', 'Editar mi perfil'),
        (('problema', 'error', 'no funciona', 'ayuda'), 'Puedo orientarte con la plataforma. Indícame si el problema ocurre en Reservas, Matchmaking, Productos, Entrenamiento, el chat o tu perfil y te indicaré el siguiente paso.', None, None),
    ]
    encontrado = next((item for item in intenciones if any(palabra in mensaje for palabra in item[0])), None)
    respuesta = encontrado[1] if encontrado else None
    enlace = url_for(encontrado[2]) if encontrado and encontrado[2] else None
    enlace_texto = encontrado[3] if encontrado else None
    if respuesta is None and 'reserva' in pagina:
        respuesta = 'Estás en Reservas. Selecciona una fecha y una cancha, revisa el horario, elige la duración y confirma la reserva. En la parte superior encontrarás tu agenda personal.'
        enlace, enlace_texto = url_for('reservas'), 'Abrir Reservas'
    elif respuesta is None and 'matchmaking' in pagina:
        respuesta = 'Estás en Matchmaking: selecciona un usuario para consultar su perfil y enviar una solicitud de chat.'
        enlace, enlace_texto = url_for('matchmaking'), 'Abrir Matchmaking'
    elif respuesta is None:
        respuesta = 'Soy Tenny, una asistente virtual de TENNISSEL. Puedo ayudarte con reservas, mis reservas, jugadores, profesores, entrenamientos, productos, Premium, torneos y tu perfil. Escribe una pregunta concreta y te guiaré.'
    return jsonify({'respuesta': respuesta, 'enlace': enlace, 'enlace_texto': enlace_texto})


def comprobar_entorno():
    print('PY=', os.sys.executable)
    print('KEY=', os.environ.get('SPORTRADAR_API_KEY'))
    print('BASE=', os.environ.get('SPORTRADAR_BASE_URL'))
    print('LOCALE=', os.environ.get('SPORTRADAR_LOCALE'))


def probar_api():
    try:
        respuesta = requests.get(
            'https://www.thesportsdb.com/api/v1/json/123/searchteams.php',
            params={'t': 'Arsenal'},
            timeout=10
        )
        respuesta.raise_for_status()
        datos = respuesta.json()
    except requests.RequestException as err:
        codigo = err.response.status_code if err.response is not None else 'sin respuesta'
        print(f'No se pudo consultar TheSportsDB (HTTP {codigo}): {err}')
        return
    except ValueError as err:
        print(f'TheSportsDB devolvió una respuesta que no es JSON válido: {err}')
        return

    equipos = datos.get('teams') if isinstance(datos, dict) else None
    equipo = next((item for item in equipos if isinstance(item, dict)), None) if isinstance(equipos, list) else None
    if equipo is None:
        print('No se encontro el equipo solicitado.')
        return

    # Algunas terminales de Windows no pueden codificar todos los caracteres
    # incluidos en los datos devueltos por la API. Sustituirlos evita que el
    # último print cierre el proceso con UnicodeEncodeError.
    salida = os.sys.stdout
    if hasattr(salida, 'reconfigure'):
        salida.reconfigure(errors='replace')
    try:
        print('Equipo:6', equipo.get('strTeam') or 'No disponible')
        print('Deporte:', equipo.get('strSport') or 'No disponible')
        print('Pais:', equipo.get('strCountry') or 'No disponible')
        print('Liga:', equipo.get('strLeague') or 'No disponible')
        print('Logo:', equipo.get('strBadge') or 'No disponible')
    except (OSError, UnicodeError, AttributeError) as err:
        print(f'El equipo se consulto, pero no se pudo mostrar toda la respuesta: {err}')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Servidor y herramientas de TENNISSEL')
    parser.add_argument('--check-environment', action='store_true', help='Muestra la configuracion de Sportradar')
    parser.add_argument('--test-api', action='store_true', help='Prueba la API publica de equipos')
    args = parser.parse_args()

    if args.check_environment:
        comprobar_entorno()
    elif args.test_api:
        probar_api()
    else:
        app.run(debug=True, use_reloader=False)
