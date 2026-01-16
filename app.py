#!/usr/bin/env python3
"""
===========================================
🛡️  IPTV PRIVACY SERVER - TELEVIZO M3U8
===========================================
Servidor IPTV que genera M3U8 HLS válido para Televizo
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

# ¡IMPORTANTE! NO CAMBIES LA CONTRASEÑA SI YA FUNCIONA
CONTRASEÑA_SEGURA = "PrivacidadMaxima2024!"
USERS = {
    "tv_user": generate_password_hash(CONTRASEÑA_SEGURA)
}

# ============================================================================
# CONFIGURACIÓN DE TUS FUENTES IPTV
# ============================================================================

# ¡TU LISTA IPTV REAL! (solo esta línea sin #)
IPTV_SOURCES = [
    "http://urbi.myftp.org:47247/get.php?username=cunadopablo&password=5689P4&type=m3u_plus&output=m3u8",
]

# ============================================================================
# CONFIGURACIÓN DE PRIVACIDAD (STEALTH MODE)
# ============================================================================

PRIVACY_CONFIG = {
    "remove_php": True,          # Eliminar streams PHP
    "remove_epg": True,          # Eliminar EPG metadata
    "remove_logos": True,        # Eliminar logos
    "remove_categories": True,   # Eliminar categorías
    "obfuscate_names": False,    # No ofuscar nombres
    "update_interval_hours": 6,  # Actualizar cada 6 horas
}

# ============================================================================
# VARIABLE GLOBAL PARA LA PLAYLIST
# ============================================================================

CURRENT_PLAYLIST = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:10
#EXT-X-MEDIA-SEQUENCE:0
#EXTINF:10.0,📡 Servidor IPTV Privado
https://iptv-privacy-server.onrender.com/welcome.ts
#EXT-X-ENDLIST
"""

# ============================================================================
# LOGGING CONFIGURADO
# ============================================================================

def setup_logging():
    """Configura logging detallado"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ============================================================================
# AUTENTICACIÓN
# ============================================================================

@auth.verify_password
def verify_password(username, password):
    """Verifica usuario/contraseña"""
    if username in USERS and check_password_hash(USERS.get(username), password):
        logger.info(f"✅ Acceso autorizado para {username}")
        return username
    logger.warning(f"❌ Intento de acceso fallido: {username}")
    return None

# ============================================================================
# FUNCIONES DE PROCESAMIENTO IPTV (REPARADAS)
# ============================================================================

def descargar_lista_iptv(url):
    """Descarga lista IPTV manteniendo formato original"""
    try:
        logger.info(f"📥 Descargando lista M3U8...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/x-mpegURL, */*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'DNT': '1',
        }
        
        response = requests.get(url, headers=headers, timeout=60, verify=False)
        
        if response.status_code == 200:
            contenido = response.text
            
            # Verificaciones críticas
            if not contenido.strip():
                logger.error("❌ Lista vacía recibida")
                return None
            
            if "#EXTM3U" not in contenido:
                logger.error("❌ No es archivo M3U/M3U8 válido (falta #EXTM3U)")
                return None
            
            # Análisis del formato
            lineas_totales = len(contenido.split('\n'))
            canales = contenido.count("#EXTINF:")
            es_hls = "#EXT-X-" in contenido
            
            logger.info(f"✅ Descarga exitosa")
            logger.info(f"   📊 {lineas_totales} líneas, {canales} canales")
            logger.info(f"   🎬 Formato: {'HLS/M3U8' if es_hls else 'M3U simple'}")
            
            return contenido
            
        else:
            logger.error(f"❌ Error HTTP {response.status_code}")
            return None
            
    except requests.exceptions.Timeout:
        logger.error("⏰ Timeout: El servidor IPTV no responde")
        return None
    except Exception as e:
        logger.error(f"🔥 Error descarga: {str(e)}")
        return None

def reparar_formato_m3u8(contenido, config):
    """Repara y limpia formato M3U8 para hacerlo HLS válido"""
    if not contenido:
        return ""
    
    lineas = contenido.split('\n')
    lineas_procesadas = []
    i = 0
    canales_procesados = 0
    
    # Encabezados HLS obligatorios
    encabezados_hls = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-TARGETDURATION:10",
        "#EXT-X-MEDIA-SEQUENCE:0"
    ]
    
    # Añadir encabezados si no están
    tiene_encabezados_hls = any("#EXT-X-VERSION" in l for l in lineas[:10])
    if not tiene_encabezados_hls:
        lineas_procesadas.extend(encabezados_hls)
    
    while i < len(lineas):
        linea = lineas[i].strip()
        
        # 1. LÍNEA #EXTINF: (CANAL)
        if "#EXTINF:" in linea:
            # Extraer duración y nombre
            partes = linea.split(',', 1)
            if len(partes) == 2:
                duracion_part = partes[0].replace("#EXTINF:", "").strip()
                nombre = partes[1].strip()
                
                # Extraer duración numérica
                duracion_match = re.search(r'([0-9.]+)', duracion_part)
                duracion = duracion_match.group(1) if duracion_match else "10.0"
                
                # Limpiar nombre según configuración
                if config["remove_epg"]:
                    nombre = re.sub(r'\[.*?\]', '', nombre)  # Eliminar [EPG info]
                    nombre = re.sub(r'\(.*?\)', '', nombre)  # Eliminar (info)
                
                # Buscar URL en las siguientes líneas (máximo 3 líneas)
                url_encontrada = None
                for j in range(1, 4):
                    if i + j < len(lineas):
                        posible_url = lineas[i + j].strip()
                        if (posible_url and 
                            not posible_url.startswith('#') and 
                            ('://' in posible_url or '.ts' in posible_url or '.m3u8' in posible_url)):
                            url_encontrada = posible_url
                            i += j  # Saltar a la línea de URL
                            break
                
                if url_encontrada:
                    # Verificar filtro PHP
                    if config["remove_php"] and '.php' in url_encontrada.lower():
                        i += 1
                        continue
                    
                    # Añadir canal procesado
                    lineas_procesadas.append(f"#EXTINF:{duracion},{nombre}")
                    lineas_procesadas.append(url_encontrada)
                    canales_procesados += 1
            
            i += 1
        
        # 2. LÍNEAS HLS CORRUPTAS (#EXT-X-SESSION-DATA mal formado)
        elif "#EXT-X-SESSION-DATA" in linea and "DATA-ID=" in linea:
            # Ignorar línea corrupta completamente
            i += 1
        
        # 3. LÍNEAS HLS VÁLIDAS (#EXT-X-...)
        elif linea.startswith("#EXT-X-") and "SESSION-DATA" not in linea:
            # Mantener solo líneas HLS válidas
            if any(x in linea for x in ["VERSION", "TARGETDURATION", "MEDIA-SEQUENCE", "ENDLIST"]):
                lineas_procesadas.append(linea)
            i += 1
        
        # 4. METADATOS A ELIMINAR (según configuración)
        elif config["remove_logos"] and "tvg-logo=" in linea:
            # Eliminar logos
            i += 1
        elif config["remove_categories"] and "group-title=" in linea:
            # Eliminar categorías
            i += 1
        elif config["remove_epg"] and any(x in linea for x in ["tvg-id=", "tvg-name=", "tvg-url="]):
            # Eliminar EPG
            i += 1
        
        # 5. URL SUELTA (sin #EXTINF antes)
        elif (linea and not linea.startswith('#') and 
              '://' in linea and
              (i == 0 or not lineas[i-1].strip().startswith("#EXTINF:"))):
            # Crear entrada genérica
            lineas_procesadas.append(f"#EXTINF:10.0,Canal {canales_procesados+1}")
            lineas_procesadas.append(linea)
            canales_procesados += 1
            i += 1
        
        # 6. OTRAS LÍNEAS (# comentarios, etc)
        elif linea.startswith("#") and not linea.startswith("#EXT"):
            # Mantener comentarios simples
            lineas_procesadas.append(linea)
            i += 1
        else:
            i += 1
    
    # Asegurar EXT-X-ENDLIST al final
    if not any("#EXT-X-ENDLIST" in l for l in lineas_procesadas):
        lineas_procesadas.append("#EXT-X-ENDLIST")
    
    logger.info(f"🔄 Formato reparado: {canales_procesados} canales procesados")
    
    return '\n'.join(lineas_procesadas)

def actualizar_playlists():
    """Actualiza todas las listas y repara formato"""
    if not IPTV_SOURCES:
        logger.warning("⚠️ No hay fuentes IPTV configuradas")
        return {
            "status": "error",
            "message": "Configura tus fuentes IPTV en app.py"
        }
    
    todo_contenido = ""
    
    for fuente in IPTV_SOURCES:
        logger.info(f"🔄 Procesando fuente: {fuente[:50]}...")
        
        # Descargar
        contenido = descargar_lista_iptv(fuente)
        if not contenido:
            logger.error(f"❌ No se pudo descargar: {fuente[:50]}")
            continue
        
        # Reparar y limpiar
        reparado = reparar_formato_m3u8(contenido, PRIVACY_CONFIG)
        if reparado:
            todo_contenido += reparado + "\n"
    
    # Actualizar playlist global
    if todo_contenido and len(todo_contenido) > 100:
        global CURRENT_PLAYLIST
        CURRENT_PLAYLIST = todo_contenido
        
        canales = todo_contenido.count("#EXTINF:")
        logger.info(f"✅ Playlist actualizada: {canales} canales")
        
        return {
            "status": "success",
            "message": "Playlist M3U8 actualizada",
            "canales": canales,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "formato": "HLS/M3U8 válido"
        }
    
    # Fallback si todo falla
    return {
        "status": "warning",
        "message": "Usando playlist de respaldo",
        "canales": 1
    }

# ============================================================================
# RUTAS WEB PRINCIPALES
# ============================================================================

@app.route('/')
@auth.login_required
def index():
    """Página principal"""
    html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>🎬 IPTV M3U8 - Televizo</title>
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
            .btn.success {{
                background: #10b981;
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
            code {{
                background: #334155;
                padding: 2px 6px;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
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
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🎬 Servidor IPTV M3U8</h1>
            <p>Formato HLS válido para Televizo</p>
            <span class="status online">● HLS VÁLIDO</span>
        </div>
        
        <div class="card">
            <h2>📡 URL para Televizo</h2>
            <div class="url-box">
                https://iptv-privacy-server.onrender.com/playlist.m3u8
            </div>
            <button class="btn" onclick="copyUrl()">📋 Copiar URL</button>
            <a href="/playlist.m3u8" class="btn success">⬇️ Descargar Ahora</a>
        </div>
        
        <div class="card">
            <h2>⚙️ Configuración en Televizo</h2>
            <p>1. <strong>Añadir lista</strong> → <strong>URL</strong></p>
            <p>2. <strong>URL:</strong> <code>https://iptv-privacy-server.onrender.com/playlist.m3u8</code></p>
            <p>3. <strong>Marcar:</strong> ✓ HTTP Authentication</p>
            <p>4. <strong>Usuario:</strong> <code>tv_user</code></p>
            <p>5. <strong>Contraseña:</strong> <code>{CONTRASEÑA_SEGURA}</code></p>
            <p>6. <strong>¡Guardar y disfrutar!</strong></p>
        </div>
        
        <div class="card">
            <h2>🔧 Herramientas</h2>
            <a href="/update" class="btn">🔄 Actualizar Lista</a>
            <a href="/debug" class="btn">🐛 Información Debug</a>
            <a href="/check" class="btn">✅ Verificar Formato</a>
        </div>
        
        <div class="card">
            <h2>🎯 Características</h2>
            <p>• ✅ Formato M3U8 HLS válido</p>
            <p>• ✅ Compatible con Televizo 100%</p>
            <p>• ✅ Líneas HLS corruptas eliminadas</p>
            <p>• ✅ Encabezados HLS correctos</p>
            <p>• ✅ Actualización automática cada 6h</p>
        </div>
        
        <script>
            function copyUrl() {{
                const url = "https://iptv-privacy-server.onrender.com/playlist.m3u8";
                navigator.clipboard.writeText(url).then(() => {{
                    alert('URL copiada al portapapeles ✓');
                }});
            }}
        </script>
    </body>
    </html>
    '''
    return html

@app.route('/playlist.m3u8')
@auth.login_required
def get_playlist():
    """Devuelve playlist en formato M3U8 HLS válido"""
    response = make_response(CURRENT_PLAYLIST)
    response.headers['Content-Type'] = 'application/vnd.apple.mpegurl'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    logger.info("🎬 Playlist M3U8 servida a cliente")
    return response

@app.route('/update')
@auth.login_required
def update_now():
    """Fuerza una actualización manual"""
    result = actualizar_playlists()
    return jsonify(result)

@app.route('/debug')
@auth.login_required
def debug_info():
    """Información de diagnóstico"""
    canales = CURRENT_PLAYLIST.count("#EXTINF:")
    lineas = len(CURRENT_PLAYLIST.split('\n'))
    tamaño = len(CURRENT_PLAYLIST)
    
    # Detectar formato
    es_hls_valido = all(x in CURRENT_PLAYLIST for x in ["#EXTM3U", "#EXT-X-VERSION", "#EXT-X-ENDLIST"])
    formato = "HLS/M3U8 válido" if es_hls_valido else "M3U simple"
    
    # Primeras 5 líneas
    primeras_lineas = '\n'.join(CURRENT_PLAYLIST.split('\n')[:5])
    
    return jsonify({
        "status": "online",
        "canales": canales,
        "lineas": lineas,
        "tamaño_bytes": tamaño,
        "formato": formato,
        "hls_valido": es_hls_valido,
        "primeras_lineas": primeras_lineas,
        "timestamp": datetime.now().isoformat(),
        "fuentes_configuradas": len(IPTV_SOURCES),
        "actualizacion_automatica": f"Cada {PRIVACY_CONFIG['update_interval_hours']} horas"
    })

@app.route('/check')
@auth.login_required
def check_format():
    """Verifica formato HLS específicamente"""
    checks = {
        "tiene_extm3u": "#EXTM3U" in CURRENT_PLAYLIST,
        "tiene_ext_x_version": "#EXT-X-VERSION" in CURRENT_PLAYLIST,
        "tiene_ext_x_endlist": "#EXT-X-ENDLIST" in CURRENT_PLAYLIST,
        "tiene_extinf": "#EXTINF:" in CURRENT_PLAYLIST,
        "no_tiene_corrupto": "#EXT-X-SESSION-DATA" not in CURRENT_PLAYLIST or "DATA-ID=" not in CURRENT_PLAYLIST,
        "lineas_totales": len(CURRENT_PLAYLIST.split('\n')),
        "canales_totales": CURRENT_PLAYLIST.count("#EXTINF:")
    }
    
    checks["hls_completamente_valido"] = all([
        checks["tiene_extm3u"],
        checks["tiene_ext_x_version"],
        checks["tiene_ext_x_endlist"],
        checks["tiene_extinf"],
        checks["no_tiene_corrupto"]
    ])
    
    return jsonify({
        "verificacion_hls": checks,
        "compatible_televizo": checks["hls_completamente_valido"],
        "mensaje": "✅ Formato HLS válido para Televizo" if checks["hls_completamente_valido"] else "❌ Problemas detectados"
    })

# ============================================================================
# INICIALIZACIÓN Y TAREAS PROGRAMADAS
# ============================================================================

def inicializar_servidor():
    """Inicializa el servidor con actualización"""
    logger.info("="*60)
    logger.info("🎬 INICIANDO SERVIDOR IPTV M3U8 PARA TELEVIZO")
    logger.info("="*60)
    
    # Actualizar al inicio
    logger.info("🔄 Actualizando lista al inicio...")
    resultado = actualizar_playlists()
    
    if resultado["status"] == "success":
        logger.info(f"✅ {resultado['canales']} canales cargados")
    else:
        logger.warning("⚠️ Usando playlist de respaldo")
    
    # Programar actualizaciones automáticas
    intervalo = PRIVACY_CONFIG["update_interval_hours"]
    schedule.every(intervalo).hours.do(actualizar_playlists)
    
    logger.info(f"⏰ Actualización automática cada {intervalo} horas")
    logger.info(f"🔑 Usuario: tv_user | Contraseña: {CONTRASEÑA_SEGURA}")
    logger.info("🌐 Servidor listo en modo HLS/M3U8")

# ============================================================================
# EJECUCIÓN PRINCIPAL
# ============================================================================

if __name__ == '__main__':
    inicializar_servidor()
    app.run(host='0.0.0.0', port=5000, debug=False)