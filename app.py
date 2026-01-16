#!/usr/bin/env python3
"""
===========================================
🔥 IPTV MULTI-LIST PROCESSOR
===========================================
Procesa múltiples listas IPTV y mantiene duplicados como reservas
===========================================
"""

import re
import logging
import requests
from datetime import datetime
from flask import Flask, jsonify, request, make_response
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

app = Flask(__name__)
auth = HTTPBasicAuth()

CONTRASEÑA_SEGURA = "PrivacidadMaxima2024!"
USERS = {
    "tv_user": generate_password_hash(CONTRASEÑA_SEGURA)
}

# ============================================================================
# ¡AÑADE TODAS TUS LISTAS AQUÍ!
# ============================================================================

IPTV_SOURCES = [
    # LISTA PRINCIPAL
    "http://urbi.myftp.org:47247/get.php?username=cunadopablo&password=5689P4&type=m3u_plus&output=m3u8",
    
    # LISTA SECUNDARIA 1 (si tienes)
    # "http://servidor2.com:8000/get.php?user=xxx&pass=yyy&type=m3u",
    
    # LISTA SECUNDARIA 2 (si tienes)  
    # "http://servidor3.com/live/usuario/contraseña/123.m3u8",
    
    # LISTA SECUNDARIA 3 (si tienes)
    # "http://backup.tv/playlist.m3u?token=ABCD1234",
]

# ============================================================================
# CONFIGURACIÓN DE PROCESAMIENTO
# ============================================================================

PROCESSING_CONFIG = {
    "remove_php": True,           # Eliminar streams .php (SÍ)
    "remove_epg": True,           # Eliminar EPG metadata (SÍ)
    "remove_logos": True,         # Eliminar logos (SÍ)
    "remove_categories": True,    # Eliminar categorías (SÍ)
    "remove_tokens": True,        # Eliminar tokens de URLs (SÍ)
    "keep_duplicates": True,      # ¡MANTENER DUPLICADOS! (RESERVAS)
    "update_interval_hours": 6,   # Actualizar cada 6 horas
}

# Cache
CURRENT_PLAYLIST = ""
LAST_UPDATE = None
STATS = {
    "total_canales": 0,
    "canales_unicos": 0,
    "canales_duplicados": 0,
    "listas_procesadas": 0,
    "streams_eliminados": 0
}

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# ============================================================================
# AUTENTICACIÓN
# ============================================================================

@auth.verify_password
def verify_password(username, password):
    if username in USERS and check_password_hash(USERS.get(username), password):
        return username
    return None

# ============================================================================
# FUNCIONES DE PROCESAMIENTO MEJORADAS
# ============================================================================

def descargar_lista(url, lista_num):
    """Descarga una lista IPTV"""
    try:
        logger.info(f"📥 Descargando lista #{lista_num}: {url[:60]}...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Referer': 'https://televizo.app/'
        }
        
        response = requests.get(url, headers=headers, timeout=45, verify=False)
        
        if response.status_code == 200:
            contenido = response.text
            
            if "#EXTM3U" not in contenido:
                logger.warning(f"⚠️ Lista #{lista_num}: No tiene #EXTM3U")
                return None
            
            canales = contenido.count("#EXTINF:")
            logger.info(f"✅ Lista #{lista_num}: {canales} canales descargados")
            return contenido
            
        else:
            logger.error(f"❌ Lista #{lista_num}: HTTP {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"🔥 Lista #{lista_num}: Error - {e}")
        return None

def limpiar_stream_url(url, config):
    """Limpia URL de stream según configuración"""
    if not url or '://' not in url:
        return None
    
    # 1. ELIMINAR streams .php
    if config["remove_php"] and '.php' in url.lower():
        return None
    
    # 2. ELIMINAR tokens de URL
    if config["remove_tokens"]:
        # Eliminar parámetros comunes de token
        url = re.sub(r'[&?](token|key|signature|hash|stoken|token2)=[^&]*', '', url)
        # Limpiar doble ? o &
        url = re.sub(r'[&?]{2,}', '?', url)
        url = url.rstrip('?&')
    
    return url

def extraer_info_canal(linea_extinf, config):
    """Extrae información limpia del canal"""
    nombre = "Canal"
    duracion = "10.0"
    
    if ',' in linea_extinf:
        # Extraer duración
        duracion_match = re.search(r'#EXTINF:([^,]+),', linea_extinf)
        if duracion_match:
            duracion = duracion_match.group(1).strip()
        
        # Extraer nombre
        partes = linea_extinf.split(',', 1)
        if len(partes) > 1:
            nombre = partes[1].strip()
            
            # ELIMINAR EPG metadata si está configurado
            if config["remove_epg"]:
                nombre = re.sub(r'\[.*?\]', '', nombre)
                nombre = re.sub(r'\(.*?\)', '', nombre)
            
            # ELIMINAR metadatos específicos
            if config["remove_logos"]:
                nombre = re.sub(r'tvg-logo="[^"]*"', '', nombre)
            
            if config["remove_categories"]:
                nombre = re.sub(r'group-title="[^"]*"', '', nombre)
            
            # Limpiar espacios extra
            nombre = ' '.join(nombre.split())
    
    return nombre, duracion

def procesar_lista(contenido, config, lista_num):
    """Procesa una lista individual manteniendo duplicados"""
    if not contenido:
        return [], 0, 0
    
    lineas = contenido.split('\n')
    canales_procesados = []
    canales_agregados = 0
    streams_eliminados = 0
    
    i = 0
    while i < len(lineas):
        linea = lineas[i].strip()
        
        # LÍNEA #EXTINF: (CANAL)
        if linea.startswith("#EXTINF:"):
            # Extraer información del canal
            nombre, duracion = extraer_info_canal(linea, config)
            
            # Buscar URL en siguientes líneas
            url_encontrada = None
            for j in range(1, 6):  # Buscar hasta 5 líneas adelante
                if i + j < len(lineas):
                    posible_url = lineas[i + j].strip()
                    if posible_url and '://' in posible_url and not posible_url.startswith('#'):
                        url_encontrada = posible_url
                        break
            
            if url_encontrada:
                # Limpiar URL
                url_limpia = limpiar_stream_url(url_encontrada, config)
                
                if url_limpia:
                    # ¡MANTENER DUPLICADO! Añadir sufijo para identificar
                    sufijo_lista = f" [L{lista_num}]" if len(IPTV_SOURCES) > 1 else ""
                    nombre_completo = f"{nombre}{sufijo_lista}"
                    
                    # Crear entrada de canal
                    canal = {
                        "extinf": f"#EXTINF:{duracion},{nombre_completo}",
                        "url": url_limpia,
                        "nombre": nombre,
                        "lista_origen": lista_num
                    }
                    
                    canales_procesados.append(canal)
                    canales_agregados += 1
                    i += j  # Saltar a la línea de URL
                else:
                    streams_eliminados += 1
            else:
                streams_eliminados += 1
            
            i += 1
        
        # IGNORAR otras líneas
        else:
            i += 1
    
    logger.info(f"📊 Lista #{lista_num}: {canales_agregados} canales procesados, {streams_eliminados} eliminados")
    return canales_procesados, canales_agregados, streams_eliminados

def combinar_listas(todas_listas):
    """Combina todas las listas manteniendo duplicados"""
    canales_combinados = []
    canales_unicos = set()
    duplicados = 0
    
    for lista_canales in todas_listas:
        for canal in lista_canales:
            # Añadir siempre (¡MANTENER DUPLICADOS!)
            canales_combinados.append(canal)
            
            # Contar duplicados para estadísticas
            clave = f"{canal['nombre']}|{canal['url']}"
            if clave in canales_unicos:
                duplicados += 1
            else:
                canales_unicos.add(clave)
    
    return canales_combinados, len(canales_unicos), duplicados

def generar_m3u8_final(canales_combinados):
    """Genera M3U8 final a partir de canales combinados"""
    # Encabezados HLS
    resultado = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-TARGETDURATION:10",
        "#EXT-X-MEDIA-SEQUENCE:0",
        ""
    ]
    
    # Añadir todos los canales (incluidos duplicados)
    for canal in canales_combinados:
        resultado.append(canal["extinf"])
        resultado.append(canal["url"])
        resultado.append("")  # Línea en blanco para separar
    
    # Final HLS
    resultado.append("#EXT-X-ENDLIST")
    
    return '\n'.join(resultado)

def actualizar_todas_listas():
    """Procesa TODAS las listas configuradas"""
    global CURRENT_PLAYLIST, LAST_UPDATE, STATS
    
    logger.info("="*60)
    logger.info("🔄 PROCESANDO MÚLTIPLES LISTAS IPTV")
    logger.info(f"📋 Listas configuradas: {len(IPTV_SOURCES)}")
    logger.info("="*60)
    
    todas_listas_canales = []
    stats_temp = {
        "total_canales": 0,
        "canales_por_lista": [],
        "streams_eliminados": 0,
        "listas_exitosas": 0
    }
    
    # Procesar cada lista
    for idx, fuente in enumerate(IPTV_SOURCES, 1):
        contenido = descargar_lista(fuente, idx)
        
        if contenido:
            canales_procesados, agregados, eliminados = procesar_lista(
                contenido, PROCESSING_CONFIG, idx
            )
            
            if canales_procesados:
                todas_listas_canales.append(canales_procesados)
                stats_temp["total_canales"] += agregados
                stats_temp["canales_por_lista"].append(agregados)
                stats_temp["streams_eliminados"] += eliminados
                stats_temp["listas_exitosas"] += 1
                
                logger.info(f"✅ Lista #{idx}: {agregados} canales añadidos")
    
    # Combinar todas las listas
    if todas_listas_canales:
        canales_combinados, unicos, duplicados = combinar_listas(todas_listas_canales)
        
        # Generar M3U8 final
        CURRENT_PLAYLIST = generar_m3u8_final(canales_combinados)
        LAST_UPDATE = datetime.now()
        
        # Actualizar estadísticas
        STATS["total_canales"] = len(canales_combinados)
        STATS["canales_unicos"] = unicos
        STATS["canales_duplicados"] = duplicados
        STATS["listas_procesadas"] = stats_temp["listas_exitosas"]
        STATS["streams_eliminados"] = stats_temp["streams_eliminados"]
        
        logger.info("="*60)
        logger.info("✅ PROCESAMIENTO COMPLETADO")
        logger.info(f"📊 Estadísticas finales:")
        logger.info(f"   • Canales totales: {STATS['total_canales']}")
        logger.info(f"   • Canales únicos: {STATS['canales_unicos']}")
        logger.info(f"   • Canales duplicados (reservas): {STATS['canales_duplicados']}")
        logger.info(f"   • Listas procesadas: {STATS['listas_procesadas']}/{len(IPTV_SOURCES)}")
        logger.info(f"   • Streams eliminados: {STATS['streams_eliminados']}")
        logger.info(f"   • Tasa reservas: {(STATS['canales_duplicados']/STATS['total_canales']*100):.1f}%")
        logger.info("="*60)
        
        return True
    
    logger.error("❌ No se pudo procesar ninguna lista")
    return False

# ============================================================================
# RUTAS WEB
# ============================================================================

@app.route('/')
@auth.login_required
def index():
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>📡 IPTV Multi-List</title>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 900px;
                margin: 0 auto;
                padding: 20px;
                background: #0f172a;
                color: #e2e8f0;
            }}
            .header {{
                background: linear-gradient(135deg, #1e293b 0%, #475569 100%);
                padding: 30px;
                border-radius: 15px;
                margin-bottom: 25px;
                text-align: center;
            }}
            .card {{
                background: #1e293b;
                padding: 20px;
                margin-bottom: 20px;
                border-radius: 10px;
                border-left: 5px solid #3b82f6;
            }}
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin: 20px 0;
            }}
            .stat-box {{
                background: #334155;
                padding: 15px;
                border-radius: 8px;
                text-align: center;
            }}
            .stat-number {{
                font-size: 2em;
                font-weight: bold;
                color: #60a5fa;
            }}
            .btn {{
                display: inline-block;
                background: #3b82f6;
                color: white;
                padding: 12px 25px;
                text-decoration: none;
                border-radius: 8px;
                font-weight: bold;
                margin: 8px 5px;
                border: none;
                cursor: pointer;
            }}
            .btn:hover {{ background: #2563eb; }}
            .btn.warning {{ background: #f59e0b; }}
            .btn.warning:hover {{ background: #d97706; }}
            .url-box {{
                background: #1e293b;
                padding: 15px;
                border-radius: 8px;
                font-family: 'Courier New', monospace;
                margin: 15px 0;
                border: 1px solid #475569;
                word-break: break-all;
            }}
            .source-list {{
                background: #0f172a;
                padding: 15px;
                border-radius: 8px;
                margin: 10px 0;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>📡 IPTV MULTI-LIST PROCESSOR</h1>
            <p>Procesa múltiples listas • Mantiene duplicados como reservas</p>
        </div>
        
        <div class="card">
            <h2>📊 ESTADÍSTICAS ACTUALES</h2>
            <div class="stats-grid">
                <div class="stat-box">
                    <div class="stat-number">{STATS["total_canales"]}</div>
                    <div>Canales totales</div>
                </div>
                <div class="stat-box">
                    <div class="stat-number">{STATS["canales_unicos"]}</div>
                    <div>Canales únicos</div>
                </div>
                <div class="stat-box">
                    <div class="stat-number">{STATS["canales_duplicados"]}</div>
                    <div>Reservas (duplicados)</div>
                </div>
                <div class="stat-box">
                    <div class="stat-number">{STATS["listas_procesadas"]}</div>
                    <div>Listas activas</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>📡 URL PARA TELEVIZO</h2>
            <div class="url-box">
                https://iptv-privacy-server.onrender.com/playlist.m3u8
            </div>
            <button class="btn" onclick="copyUrl()">📋 Copiar URL</button>
            <a href="/playlist.m3u8" class="btn">⬇️ Descargar M3U8</a>
        </div>
        
        <div class="card">
            <h2>🔧 HERRAMIENTAS</h2>
            <a href="/update" class="btn">🔄 Procesar Todas las Listas</a>
            <a href="/sources" class="btn warning">📋 Ver Fuentes Configuradas</a>
            <a href="/stats" class="btn">📊 Estadísticas Detalladas</a>
            <a href="/preview" class="btn">👁️ Vista Previa</a>
        </div>
        
        <div class="card">
            <h2>⚙️ CONFIGURACIÓN TELEVIZO</h2>
            <p><strong>URL:</strong> https://iptv-privacy-server.onrender.com/playlist.m3u8</p>
            <p><strong>HTTP Authentication:</strong> SÍ</p>
            <p><strong>Usuario:</strong> tv_user</p>
            <p><strong>Contraseña:</strong> {CONTRASEÑA_SEGURA}</p>
            <p><em>Los canales duplicados aparecen como reservas [L1], [L2], etc.</em></p>
        </div>
        
        <div class="card">
            <h2>🎯 CARACTERÍSTICAS</h2>
            <p>✅ Procesa múltiples listas simultáneamente</p>
            <p>✅ <strong>MANTIENE duplicados como reservas</strong></p>
            <p>✅ Elimina streams .php, EPG, tokens, logos</p>
            <p>✅ Formato M3U8 HLS válido</p>
            <p>✅ Estadísticas detalladas de reservas</p>
        </div>
        
        <script>
            function copyUrl() {{
                const url = "https://iptv-privacy-server.onrender.com/playlist.m3u8";
                navigator.clipboard.writeText(url).then(() => {{
                    alert('✅ URL copiada al portapapeles');
                }});
            }}
        </script>
    </body>
    </html>
    '''

@app.route('/playlist.m3u8')
@auth.login_required
def get_playlist():
    """Devuelve playlist combinada"""
    if not CURRENT_PLAYLIST:
        return "#EXTM3U\n#EXTINF:-1,Actualiza primero\nhttp://example.com/test.ts", 200
    
    response = make_response(CURRENT_PLAYLIST)
    response.headers['Content-Type'] = 'application/vnd.apple.mpegurl'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    
    logger.info(f"📤 Playlist servida: {STATS['total_canales']} canales")
    return response

@app.route('/update')
@auth.login_required
def update_now():
    """Procesa todas las listas"""
    if actualizar_todas_listas():
        return jsonify({
            "status": "success",
            "message": f"{len(IPTV_SOURCES)} listas procesadas",
            "stats": STATS,
            "timestamp": LAST_UPDATE.isoformat(),
            "features": [
                f"✅ {STATS['listas_procesadas']}/{len(IPTV_SOURCES)} listas procesadas",
                f"✅ {STATS['total_canales']} canales totales",
                f"✅ {STATS['canales_unicos']} canales únicos",
                f"✅ {STATS['canales_duplicados']} reservas (duplicados)",
                f"✅ Tasa reservas: {(STATS['canales_duplicados']/STATS['total_canales']*100 if STATS['total_canales'] > 0 else 0):.1f}%"
            ]
        })
    else:
        return jsonify({
            "status": "error",
            "message": "Error procesando listas"
        }), 500

@app.route('/sources')
@auth.login_required
def show_sources():
    """Muestra fuentes configuradas"""
    sources_info = []
    for idx, source in enumerate(IPTV_SOURCES, 1):
        sources_info.append({
            "numero": idx,
            "url": source[:80] + "..." if len(source) > 80 else source,
            "estado": "✅ Configurada"
        })
    
    return jsonify({
        "total_fuentes": len(IPTV_SOURCES),
        "fuentes": sources_info,
        "instruccion": "Para añadir más listas, edita IPTV_SOURCES en app.py"
    })

@app.route('/stats')
@auth.login_required
def detailed_stats():
    """Estadísticas detalladas"""
    return jsonify({
        "estadisticas": STATS,
        "configuracion": PROCESSING_CONFIG,
        "timestamp": LAST_UPDATE.isoformat() if LAST_UPDATE else None,
        "fuentes_configuradas": len(IPTV_SOURCES),
        "resumen": {
            "total_canales": STATS["total_canales"],
            "canales_unicos": STATS["canales_unicos"],
            "reservas": STATS["canales_duplicados"],
            "tasa_reservas": f"{(STATS['canales_duplicados']/STATS['total_canales']*100 if STATS['total_canales'] > 0 else 0):.1f}%"
        }
    })

@app.route('/preview')
@auth.login_required
def preview():
    """Vista previa de canales (incluye duplicados)"""
    if not CURRENT_PLAYLIST:
        return "Lista no generada", 404
    
    lineas = CURRENT_PLAYLIST.split('\n')
    preview_lines = ["=== VISTA PREVIA (primeros 15 canales) ===", ""]
    canales_mostrados = 0
    
    for i, linea in enumerate(lineas):
        if linea.startswith("#EXTINF:"):
            nombre = linea.split(',', 1)[1] if ',' in linea else "Canal"
            
            # Buscar URL
            url = ""
            if i + 1 < len(lineas) and '://' in lineas[i + 1]:
                url = lineas[i + 1][:60] + "..." if len(lineas[i + 1]) > 60 else lineas[i + 1]
            
            preview_lines.append(f"📺 {nombre}")
            preview_lines.append(f"   🔗 {url}")
            preview_lines.append("")
            
            canales_mostrados += 1
        
        if canales_mostrados >= 15:
            break
    
    response = make_response('\n'.join(preview_lines))
    response.headers['Content-Type'] = 'text/plain'
    return response

# ============================================================================
# INICIALIZACIÓN
# ============================================================================

if __name__ == '__main__':
    logger.info("🚀 INICIANDO IPTV MULTI-LIST PROCESSOR")
    logger.info("="*60)
    logger.info("🎯 CARACTERÍSTICAS PRINCIPALES:")
    logger.info(f"   • Listas configuradas: {len(IPTV_SOURCES)}")
    logger.info(f"   • Mantiene duplicados: {PROCESSING_CONFIG['keep_duplicates']}")
    logger.info(f"   • Streams .php: {'ELIMINADOS' if PROCESSING_CONFIG['remove_php'] else 'MANTENIDOS'}")
    logger.info(f"   • EPG metadata: {'ELIMINADO' if PROCESSING_CONFIG['remove_epg'] else 'MANTENIDO'}")
    logger.info("="*60)
    
    # Procesar al inicio
    actualizar_todas_listas()
    
    app.run(host='0.0.0.0', port=5000)