#!/usr/bin/env python3
"""
===========================================
🛡️  IPTV PRIVACY SERVER - RENDER.COM
===========================================
Servidor privado para listas IPTV anonimizadas
Modo STEALTH: Sin logos, sin categorías, sin EPG
===========================================
"""

import os
import re
import json
import time
import logging
import requests
import hashlib
import schedule
from datetime import datetime
from pathlib import Path
from flask import Flask, send_file, jsonify, request, make_response
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
from urllib.parse import urlparse

# ============================================================================
# CONFIGURACIÓN INICIAL
# ============================================================================

app = Flask(__name__)
auth = HTTPBasicAuth()

# ¡IMPORTANTE! CAMBIA ESTA CONTRASEÑA POR UNA SEGURA
CONTRASEÑA_SEGURA = "PrivacidadMaxima2024!"  # ¡CAMBIA ESTO!
USERS = {
    "tv_user": generate_password_hash(CONTRASEÑA_SEGURA)
}

# ============================================================================
# CONFIGURACIÓN DE TUS FUENTES IPTV
# ============================================================================

# ¡AÑADE TUS URLs IPTV AQUÍ! (entre las comillas)
IPTV_SOURCES = [
    # EJEMPLOS - REEMPLAZA CON TUS URLs:
    # "http://tuservidor.com/get.php?username=TU_USUARIO&password=TU_PASS",
    # "http://otro.com:8000/live/usuario/contraseña/token.m3u8",
   
    # DEJA AL MENOS UNA PARA PRUEBAS:
    "http://example.com/test.m3u"  # Esto es solo para prueba inicial
]

# ============================================================================
# CONFIGURACIÓN DE PRIVACIDAD (STEALTH MODE)
# ============================================================================

PRIVACY_CONFIG = {
    "remove_php": True,          # Eliminar streams PHP (SÍ)
    "remove_epg": True,          # Eliminar EPG metadata (SÍ)
    "remove_logos": True,        # Eliminar logos (SÍ - STEALTH)
    "remove_categories": True,   # Eliminar categorías (SÍ - STEALTH)
    "obfuscate_names": False,    # No ofuscar nombres (mejor legibilidad)
    "update_interval_hours": 6,  # Actualizar cada 6 horas
}

# ============================================================================
# VARIABLE GLOBAL PARA LA PLAYLIST
# ============================================================================

CURRENT_PLAYLIST = """#EXTM3U
#EXTINF:-1,⚠️  SERVIDOR EN CONFIGURACIÓN
# Este es el servidor IPTV privado
# Añade tus URLs IPTV en render_app.py
#EXTINF:-1,📺 Canal de Prueba 1
http://example.com/test1.ts
#EXTINF:-1,📻 Canal de Prueba 2
http://example.com/test2.m3u8
"""

# ============================================================================
# LOGGING CONFIGURADO
# ============================================================================

def setup_logging():
    """Configura logging sin información sensible"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ============================================================================
# AUTENTICACIÓN
# ============================================================================

@auth.verify_password
def verify_password(username, password):
    """Verifica usuario/contraseña sin log sensitive"""
    if username in USERS and check_password_hash(USERS.get(username), password):
        logger.info("Acceso autorizado")
        return username
    logger.warning("Intento de acceso fallido")
    return None

# ============================================================================
# FUNCIONES DE PROCESAMIENTO IPTV
# ============================================================================

def download_iptv_list(url):
    """Descarga lista IPTV de forma anónima"""
    try:
        logger.info(f"Descargando lista")
       
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'DNT': '1',
        }
       
        response = requests.get(url, headers=headers, timeout=30, verify=False)
        response.raise_for_status()
       
        return response.text
       
    except Exception as e:
        logger.error(f"Error descarga: {str(e)[:50]}")
        return None

def clean_iptv_content(content, config):
    """Limpia contenido IPTV según configuración de privacidad"""
    if not content:
        return ""
   
    lines = content.split('\n')
    cleaned_lines = []
    i = 0
    streams_removed = 0
    streams_kept = 0
   
    while i < len(lines):
        line = lines[i]
       
        # Procesar línea #EXTINF:
        if "#EXTINF:" in line:
            # Eliminar metadatos según configuración
            cleaned_line = line
           
            if config["remove_epg"]:
                cleaned_line = re.sub(r'tvg-id="[^"]*"', '', cleaned_line)
                cleaned_line = re.sub(r'url-tvg="[^"]*"', '', cleaned_line)
                cleaned_line = re.sub(r'x-tvg-url="[^"]*"', '', cleaned_line)
           
            if config["remove_logos"]:
                cleaned_line = re.sub(r'tvg-logo="[^"]*"', '', cleaned_line)
           
            if config["remove_categories"]:
                cleaned_line = re.sub(r'group-title="[^"]*"', '', cleaned_line)
           
            # Limpiar espacios extra
            cleaned_line = re.sub(r'\s+', ' ', cleaned_line).strip()
           
            # Verificar siguiente línea (URL del stream)
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
               
                # Eliminar streams PHP si está configurado
                if config["remove_php"] and ('.php' in next_line.lower()):
                    streams_removed += 1
                    i += 2  # Saltar ambas líneas
                    continue
               
                # Mantener stream válido
                cleaned_lines.append(cleaned_line)
                cleaned_lines.append(next_line)
                streams_kept += 1
                i += 2
            else:
                cleaned_lines.append(cleaned_line)
                i += 1
       
        # Eliminar líneas EPG independientes
        elif config["remove_epg"] and ("url-tvg" in line or "x-tvg-url" in line):
            i += 1
       
        # Mantener otras líneas (como #EXTM3U)
        else:
            cleaned_lines.append(line)
            i += 1
   
    logger.info(f"Procesado: {streams_kept} streams mantenidos, {streams_removed} eliminados")
   
    return '\n'.join(cleaned_lines)

def update_all_playlists():
    """Actualiza todas las listas configuradas"""
    if not IPTV_SOURCES:
        logger.warning("No hay fuentes IPTV configuradas")
        return {"status": "info", "message": "Configura tus fuentes IPTV en render_app.py"}
   
    all_content = ""
   
    for source in IPTV_SOURCES:
        logger.info(f"Procesando fuente")
       
        # Descargar
        content = download_iptv_list(source)
        if not content:
            continue
       
        # Limpiar
        cleaned = clean_iptv_content(content, PRIVACY_CONFIG)
        if cleaned:
            all_content += cleaned + "\n"
   
    # Guardar playlist combinada
    if all_content and len(all_content) > 100:  # Más de solo encabezado
        # Asegurar encabezado M3U
        if not all_content.startswith("#EXTM3U"):
            all_content = "#EXTM3U\n" + all_content
       
        # Actualizar playlist global
        global CURRENT_PLAYLIST
        CURRENT_PLAYLIST = all_content
       
        logger.info(f"Playlist actualizada: {len(all_content.splitlines())} líneas")
        return {
            "status": "success",
            "message": f"Playlist actualizada",
            "lines": len(all_content.splitlines()),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
   
    return {"status": "warning", "message": "Usando playlist de prueba"}

# ============================================================================
# RUTAS WEB PRINCIPALES
# ============================================================================

@app.route('/')
@auth.login_required
def index():
    """Página principal del servidor"""
    stats = {
        "sources": len(IPTV_SOURCES),
        "privacy_mode": "STEALTH",
        "features": [
            "✅ Sin logos identificables",
            "✅ Sin categorías reveladoras",
            "✅ Sin EPG/metadatos",
            "✅ Streams directos solamente",
            "✅ HTTPS seguro",
            "✅ Actualización automática"
        ]
    }
   
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>🛡️ Servidor IPTV Privado</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                background: #0f172a;
                color: #e2e8f0;
                line-height: 1.6;
            }}
            .header {{
                background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
                padding: 2rem;
                border-radius: 15px;
                margin-bottom: 2rem;
                text-align: center;
                border: 1px solid #475569;
            }}
            .card {{
                background: #1e293b;
                padding: 1.5rem;
                margin-bottom: 1.5rem;
                border-radius: 10px;
                border: 1px solid #334155;
            }}
            .feature-list {{
                background: #0f172a;
                padding: 1rem;
                border-radius: 8px;
                margin: 1rem 0;
            }}
            .btn {{
                display: inline-block;
                background: #3b82f6;
                color: white;
                padding: 12px 24px;
                text-decoration: none;
                border-radius: 8px;
                font-weight: bold;
                margin: 5px;
                border: none;
                cursor: pointer;
                transition: background 0.3s;
            }}
            .btn:hover {{
                background: #2563eb;
            }}
            .btn.warning {{
                background: #f59e0b;
            }}
            .btn.warning:hover {{
                background: #d97706;
            }}
            .url-box {{
                background: #1e293b;
                padding: 1rem;
                border-radius: 8px;
                font-family: 'Courier New', monospace;
                margin: 1rem 0;
                border: 1px solid #475569;
                word-break: break-all;
            }}
            footer {{
                text-align: center;
                margin-top: 2rem;
                color: #94a3b8;
                font-size: 0.9rem;
            }}
            .status {{
                display: inline-block;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 0.9rem;
                margin-left: 10px;
            }}
            .status.online {{
                background: #10b981;
                color: white;
            }}
            .config-box {{
                background: #0f172a;
                padding: 1rem;
                border-radius: 8px;
                margin: 1rem 0;
                border-left: 4px solid #3b82f6;
            }}
            code {{
                background: #1e293b;
                padding: 2px 6px;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🛡️ Servidor IPTV Privado</h1>
            <p>Tu contenido seguro y anónimo</p>
            <span class="status online">● EN LÍNEA</span>
        </div>
       
        <div class="card">
            <h2>📊 Estado del Servidor</h2>
            <p>• Fuentes configuradas: <strong>{stats['sources']}</strong></p>
            <p>• Modo privacidad: <strong>{stats['privacy_mode']}</strong></p>
            <p>• Actualización automática: <strong>Cada {PRIVACY_CONFIG['update_interval_hours']} horas</strong></p>
        </div>
       
        <div class="card">
            <h2>🛡️ Características de Privacidad</h2>
            <div class="feature-list">
    """
   
    for feature in stats["features"]:
        html += f"<p>{feature}</p>"
   
    html += f"""
            </div>
        </div>
       
        <div class="card">
            <h2>📥 Descargar Playlist</h2>
            <p>Usa esta URL en Televizo o cualquier reproductor:</p>
            <div class="url-box" id="playlistUrl">
                https://{request.host}/playlist.m3u8
            </div>
            <button class="btn" onclick="copyUrl()">📋 Copiar URL</button>
            <a href="/playlist.m3u8" class="btn">⬇️ Descargar Ahora</a>
        </div>
       
        <div class="card">
            <h2>⚙️ Acciones</h2>
            <a href="/update" class="btn">🔄 Actualizar Ahora</a>
            <a href="/config" class="btn">⚙️ Ver Configuración</a>
        </div>
       
        <div class="card">
            <h2>🔧 Configuración Necesaria</h2>
            <div class="config-box">
                <p><strong>⚠️ ATENCIÓN:</strong> Este servidor está funcionando, pero necesita tu configuración.</p>
                <p>1. Edita el archivo <code>render_app.py</code></p>
                <p>2. Encuentra la sección <code>IPTV_SOURCES</code></p>
                <p>3. Añade tus URLs IPTV reales</p>
                <p>4. Sube los cambios a GitHub</p>
                <p>5. Render se actualizará automáticamente</p>
            </div>
            <a href="/instructions" class="btn warning">📖 Ver Instrucciones Detalladas</a>
        </div>
       
        <div class="card">
            <h2>📱 Instrucciones para Televizo</h2>
            <p>1. Abre Televizo en tu Android</p>
            <p>2. Ve a "Añadir lista" → "URL"</p>
            <p>3. Pega la URL de arriba</p>
            <p>4. Usuario: <code>tv_user</code></p>
            <p>5. Contraseña: <code>{CONTRASEÑA_SEGURA}</code></p>
            <p>6. ¡Listo! (añade tus URLs después)</p>
        </div>
       
        <footer>
            <p>Servidor IPTV Privado v1.0 • Modo STEALTH activado</p>
            <p>🔒 No se almacenan logs • No se comparten datos • 100% Privado</p>
        </footer>
       
        <script>
            function copyUrl() {{
                const url = document.getElementById('playlistUrl').textContent;
                navigator.clipboard.writeText(url).then(() => {{
                    alert('URL copiada al portapapeles ✓');
                }});
            }}
        </script>
    </body>
    </html>
    """
   
    return html

@app.route('/playlist.m3u8')
@auth.login_required
def get_playlist():
    """Devuelve la playlist actual en formato M3U8"""
    response = make_response(CURRENT_PLAYLIST)
    response.headers['Content-Type'] = 'application/vnd.apple.mpegurl'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
   
    logger.info("Playlist servida a cliente")
    return response

@app.route('/update')
@auth.login_required
def update_now():
    """Fuerza una actualización manual"""
    result = update_all_playlists()
    return jsonify(result)

@app.route('/config')
@auth.login_required
def show_config():
    """Muestra la configuración actual"""
    config_display = {
        "privacy_settings": PRIVACY_CONFIG,
        "sources_count": len(IPTV_SOURCES),
        "sources_configured": IPTV_SOURCES if IPTV_SOURCES else ["⚠️ No hay fuentes configuradas"],
        "current_user": auth.current_user(),
        "server_status": "online",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    return jsonify(config_display)

@app.route('/instructions')
@auth.login_required
def instructions():
    """Página de instrucciones detalladas"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Instrucciones de Configuración</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                padding: 20px;
                max-width: 800px;
                margin: 0 auto;
            }
            .step {
                background: #f5f5f5;
                padding: 15px;
                margin: 10px 0;
                border-radius: 8px;
            }
            code {
                background: #333;
                color: white;
                padding: 10px;
                display: block;
                margin: 10px 0;
                border-radius: 5px;
            }
        </style>
    </head>
    <body>
        <h1>📖 Instrucciones de Configuración</h1>
       
        <div class="step">
            <h2>Paso 1: Editar render_app.py</h2>
            <p>Encuentra esta sección en el archivo:</p>
            <code>
# ¡AÑADE TUS URLs IPTV AQUÍ! (entre las comillas)<br>
IPTV_SOURCES = [<br>
&nbsp;&nbsp;# EJEMPLOS - REEMPLAZA CON TUS URLs:<br>
&nbsp;&nbsp;# "http://tuservidor.com/get.php?username=TU_USUARIO&password=TU_PASS",<br>
&nbsp;&nbsp;# "http://otro.com:8000/live/usuario/contraseña/token.m3u8",<br>
]<br>
            </code>
        </div>
       
        <div class="step">
            <h2>Paso 2: Añadir tus URLs</h2>
            <p>Ejemplo de cómo quedaría:</p>
            <code>
IPTV_SOURCES = [<br>
&nbsp;&nbsp;"http://tuservidor1.com/get.php?username=TU1&password=PASS1",<br>
&nbsp;&nbsp;"http://tuservidor2.com:8000/live/user/pass/123.m3u8",<br>
&nbsp;&nbsp;"http://servidor3.com/lista.m3u"<br>
]<br>
            </code>
        </div>
       
        <div class="step">
            <h2>Paso 3: Cambiar contraseña (opcional pero recomendado)</h2>
            <p>Encuentra esta línea:</p>
            <code>CONTRASEÑA_SEGURA = "PrivacidadMaxima2024!"</code>
            <p>Cámbiala por una contraseña segura.</p>
        </div>
       
        <div class="step">
            <h2>Paso 4: Subir cambios a GitHub</h2>
            <p>Desde Git Bash en Windows:</p>
            <code>
cd /c/IPTV_Privado<br>
git add .<br>
git commit -m "Added my IPTV sources"<br>
git push origin main<br>
            </code>
        </div>
       
        <div class="step">
            <h2>Paso 5: Render se actualiza automáticamente</h2>
            <p>Espera 2-3 minutos y refresca tu servidor.</p>
        </div>
       
        <a href="/">← Volver al servidor</a>
    </body>
    </html>
    """
    return html

# ============================================================================
# INICIALIZACIÓN Y CONFIGURACIÓN PROGRAMADA
# ============================================================================

def initialize_server():
    """Inicializa el servidor"""
    logger.info("=" * 60)
    logger.info("🛡️  INICIANDO SERVIDOR IPTV PRIVADO")
    logger.info("=" * 60)
   
    # Configurar actualización automática
    interval = PRIVACY_CONFIG["update_interval_hours"]
    schedule.every(interval).hours.do(update_all_playlists)
   
    logger.info(f"Actualización automática configurada cada {interval} horas")
   
    logger.info("Servidor listo en modo de prueba")
    logger.info(f"Usuario: tv_user | Contraseña: {CONTRASEÑA_SEGURA}")

# ============================================================================
# EJECUCIÓN PRINCIPAL
# ============================================================================

if __name__ == "__main__":
    # Inicializar servidor
    initialize_server()
   
    # Iniciar Flask
    port = int(os.environ.get("PORT", 5000))
   
    # En Render, necesitamos ejecutar así
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True
    )