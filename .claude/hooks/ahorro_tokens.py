#!/usr/bin/env python3
"""Avisos automáticos para ahorrar tokens (skill /ahorrar-tokens).

Lo lanza Claude Code como hook (ver .claude/settings.json):
  - SessionStart     -> recordatorio breve de cómo pedir.
  - UserPromptSubmit -> revisa el chat antes de cada mensaje y avisa si:
      * el chat ya está largo (conviene abrir uno nuevo),
      * se agregaron imágenes (recordar recortarlas),
      * el modelo elegido no calza con la tarea,
      * el mensaje pide "revisión ligera" (se le indica a Claude que la respete).
  - diagnostico      -> lo usa la skill para mostrar el estado del chat.

Por qué el tamaño se mide como CRECIMIENTO desde el primer mensaje y no en
absoluto: el arranque ya trae instrucciones, herramientas y CLAUDE.md, y eso
pesa distinto según dónde se abra (nube, escritorio, con uno o dos
repositorios). Lo que el usuario controla, y lo que se paga en cada mensaje
nuevo, es lo que el chat fue acumulando encima.

Por qué cada aviso se muestra una sola vez por nivel (y no en cada mensaje):
un aviso repetido se deja de leer, y además el propio aviso consume tokens.

Nunca debe bloquear al usuario: ante cualquier error sale en silencio.
"""
import json
import os
import re
import sys
import tempfile

# Umbrales en tokens acumulados por el chat (además del arranque).
# Se pueden cambiar sin tocar el código con variables de entorno.
AVISO = int(os.environ.get("AHORRO_TOKENS_AVISO", "60000"))
ALERTA = int(os.environ.get("AHORRO_TOKENS_ALERTA", "120000"))
# A partir de cuántas imágenes en el chat se sugiere uno nuevo.
MAX_IMAGENES = int(os.environ.get("AHORRO_TOKENS_MAX_IMAGENES", "4"))
# Cada cuántos mensajes se repite la alerta roja si se sigue en el mismo chat.
REPETIR_ALERTA_CADA = 5

# Tareas que merecen el modelo más capaz: seguridad, datos, arquitectura y
# errores difíciles. Si un proyecto tiene zonas sensibles propias (las de su
# CLAUDE.md), agrégalas a esta lista.
PALABRAS_PESADAS = [
    "seguridad", "permiso", "contraseña", "credencial",
    "migración", "migracion", "sql", "base de datos", "borrar datos",
    "video", "vídeo", "guion", "guión", "montaje",
    "arquitectura", "refactor", "rediseñ", "investiga", "depura", "error en producción",
    "no funciona", "se cae", "falla", "bug", "fórmula", "formula",
]
# Tareas chicas, para las que alcanza un modelo liviano.
PALABRAS_LIVIANAS = [
    "redacta", "redáctame", "traduce", "resume", "resúmeme", "corrige la ortografía",
    "ortografía", "typo", "texto", "mensaje para", "correo", "email", "whatsapp",
    "qué es", "que es", "qué significa", "explícame", "explicame", "cómo se",
    "pregunta", "renombra", "cambia el título", "cambia el texto", "color",
    "dónde está", "donde esta",
]


def leer_transcripcion(ruta):
    """Devuelve (tamaño_inicial, tamaño_actual, modelo, imágenes, bytes_img, mensajes)."""
    inicial = actual = None
    modelo = ""
    imagenes = 0
    bytes_img = 0
    mensajes = 0
    if not ruta or not os.path.exists(ruta):
        return 0, 0, "", 0, 0, 0
    with open(ruta, encoding="utf-8", errors="replace") as f:
        for linea in f:
            try:
                ev = json.loads(linea)
            except ValueError:
                continue
            tipo = ev.get("type")
            msg = ev.get("message") or {}
            if tipo == "assistant":
                uso = msg.get("usage") or {}
                total = (uso.get("input_tokens", 0)
                         + uso.get("cache_read_input_tokens", 0)
                         + uso.get("cache_creation_input_tokens", 0))
                if total:
                    if inicial is None:
                        inicial = total
                    actual = total
                if msg.get("model"):
                    modelo = msg["model"]
            elif tipo == "user":
                contenido = msg.get("content")
                if isinstance(contenido, str) or (
                        isinstance(contenido, list)
                        and any(b.get("type") == "text" for b in contenido if isinstance(b, dict))):
                    mensajes += 1
                n, b = contar_imagenes(contenido)
                imagenes += n
                bytes_img += b
    return inicial or 0, actual or 0, modelo, imagenes, bytes_img, mensajes


def contar_imagenes(nodo):
    """Cuenta imágenes en un mensaje, también las que vienen dentro de herramientas
    (capturas de pantalla, archivos leídos), que pesan igual."""
    if isinstance(nodo, list):
        n = b = 0
        for x in nodo:
            dn, db = contar_imagenes(x)
            n += dn
            b += db
        return n, b
    if isinstance(nodo, dict):
        if nodo.get("type") == "image":
            datos = (nodo.get("source") or {}).get("data") or ""
            return 1, len(datos) * 3 // 4
        return contar_imagenes(nodo.get("content"))
    return 0, 0


def familia(modelo):
    m = (modelo or "").lower()
    for nombre in ("haiku", "sonnet", "opus", "fable"):
        if nombre in m:
            return nombre
    return ""


def clasificar(prompt):
    p = (prompt or "").lower()
    if any(k in p for k in PALABRAS_PESADAS):
        return "pesada"
    # No se usa el largo del mensaje: un «OK, hazlo» corto puede estar aprobando
    # un cambio delicado.
    if any(k in p for k in PALABRAS_LIVIANAS):
        return "liviana"
    return "normal"


def ruta_estado(sesion):
    seguro = re.sub(r"[^A-Za-z0-9_-]", "", sesion or "sin-sesion")
    return os.path.join(tempfile.gettempdir(), f"ahorro_tokens_{seguro}.json")


def cargar_estado(sesion):
    try:
        with open(ruta_estado(sesion), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def guardar_estado(sesion, estado):
    try:
        with open(ruta_estado(sesion), "w", encoding="utf-8") as f:
            json.dump(estado, f)
    except OSError:
        pass


def miles(n):
    return f"{round(n / 1000):,}".replace(",", ".") + " mil"


def al_enviar(datos):
    sesion = datos.get("session_id", "")
    prompt = datos.get("prompt", "")
    inicial, actual, modelo, imagenes, bytes_img, mensajes = leer_transcripcion(
        datos.get("transcript_path"))
    crecimiento = max(0, actual - inicial)
    estado = cargar_estado(sesion)
    estado["turno"] = estado.get("turno", 0) + 1
    avisos = []       # lo que ve el usuario
    para_claude = []  # lo que se le indica a Claude

    # 1. Chat largo -> chat nuevo.
    nivel = 2 if crecimiento >= ALERTA else 1 if crecimiento >= AVISO else 0
    ultimo_nivel = estado.get("nivel", 0)
    repetir = nivel == 2 and (estado["turno"] - estado.get("turno_alerta", 0)) >= REPETIR_ALERTA_CADA
    if nivel > ultimo_nivel or repetir:
        if nivel == 2:
            avisos.append(
                f"🔴 Este chat ya es muy largo (~{miles(crecimiento)} tokens acumulados): "
                "cada mensaje nuevo vuelve a leer todo eso. Abre un chat nuevo para lo "
                "siguiente; escribe /ahorrar-tokens y te preparo el mensaje para pegar allá.")
            estado["turno_alerta"] = estado["turno"]
        else:
            avisos.append(
                f"🟡 El chat va creciendo (~{miles(crecimiento)} tokens acumulados). "
                "Si la próxima tarea es otra, mejor en un chat nuevo: lo importante ya "
                "está guardado en el repositorio.")
        para_claude.append(
            "Aviso de ahorro de tokens: el chat está largo. Al terminar esta respuesta, "
            "recuérdale en una línea que abra un chat nuevo para la siguiente tarea.")
    estado["nivel"] = max(nivel, ultimo_nivel) if not repetir else nivel

    # 2. Imágenes.
    previas = estado.get("imagenes", 0)
    if imagenes > previas:
        nuevas = imagenes - previas
        kb = bytes_img // 1024
        texto = (f"🖼️ {nuevas} imagen(es) nueva(s) en el chat ({imagenes} en total, ~{kb} KB). "
                 "Cada imagen se queda en la conversación y se vuelve a pagar en cada "
                 "mensaje: recorta solo la parte que importa y manda pocas.")
        if imagenes >= MAX_IMAGENES:
            texto += " Ya son varias: para seguir, conviene un chat nuevo."
        avisos.append(texto)
    estado["imagenes"] = imagenes

    # 3. Modelo acorde a la tarea.
    tipo = clasificar(prompt)
    fam = familia(modelo)
    sugerencia = None
    if tipo == "pesada" and fam in ("haiku", "sonnet"):
        sugerencia = ("🧠 Esto parece delicado (seguridad, datos, arquitectura o un error difícil). "
                      "Conviene el modelo más capaz (Opus) en el selector de modelo.")
    elif tipo == "liviana" and fam in ("opus", "fable"):
        sugerencia = ("🪶 Parece una tarea chica (texto, pregunta o cambio menor). "
                      "Un modelo más liviano (Sonnet, o Haiku para lo más simple) alcanza "
                      "y gasta bastante menos: cámbialo en el selector de modelo.")
    clave = f"{tipo}:{fam}"
    if sugerencia and estado.get("ultima_sugerencia") != clave:
        avisos.append(sugerencia)
        estado["ultima_sugerencia"] = clave

    # 4. Nivel de revisión pedido por el usuario.
    p = prompt.lower()
    if "revisión ligera" in p or "revision ligera" in p:
        para_claude.append(
            "El usuario pidió REVISIÓN LIGERA: haz el cambio y verifica solo lo mínimo "
            "indispensable (que compile o que el archivo quede bien). No revises cuadro "
            "a cuadro, no repitas montajes ni recorras pantallas. Sí corre las "
            "comprobaciones obligatorias antes de subir (las de CLAUDE.md, si las hay). "
            "Respuesta breve. Excepción: si toca una zona sensible (las que marque "
            "CLAUDE.md, o seguridad y datos ya guardados), revisa completo y avísalo en una línea.")
    elif "revisión completa" in p or "revision completa" in p:
        para_claude.append("El usuario pidió REVISIÓN COMPLETA: verifica a fondo antes de entregar.")

    guardar_estado(sesion, estado)
    if not avisos and not para_claude:
        return None
    salida = {}
    if avisos:
        salida["systemMessage"] = "\n".join(avisos)
        # A Claude solo un resumen corto: repetirle el aviso entero gastaría los
        # mismos tokens que se busca ahorrar.
        para_claude.append(
            "Al usuario ya se le mostró un aviso de ahorro de tokens; no lo repitas entero.")
    salida["hookSpecificOutput"] = {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "\n".join(para_claude),
    }
    return salida


def al_iniciar(datos):
    if datos.get("source") not in (None, "startup", "clear"):
        return None
    return {"systemMessage": (
        "💡 Ahorro de tokens: una tarea por chat · pedidos completos en un solo mensaje · "
        "pocas capturas y recortadas · di «revisión ligera» en cambios menores · "
        "modelo liviano para textos y preguntas. Escribe /ahorrar-tokens para ver el estado del chat.")}


def diagnostico(ruta):
    inicial, actual, modelo, imagenes, bytes_img, mensajes = leer_transcripcion(ruta)
    crecimiento = max(0, actual - inicial)
    nivel = "ALTO" if crecimiento >= ALERTA else "MEDIO" if crecimiento >= AVISO else "BAJO"
    print(json.dumps({
        "tokens_arranque": inicial,
        "tokens_actuales": actual,
        "tokens_acumulados_por_el_chat": crecimiento,
        "nivel": nivel,
        "umbral_aviso": AVISO,
        "umbral_alerta": ALERTA,
        "mensajes_del_usuario": mensajes,
        "imagenes": imagenes,
        "kb_imagenes": bytes_img // 1024,
        "modelo": familia(modelo) or modelo,
    }, ensure_ascii=False, indent=2))


def ultima_transcripcion():
    """Para la skill: la transcripción más reciente de este equipo."""
    base = os.path.expanduser("~/.claude/projects")
    candidatas = []
    for raiz, _, archivos in os.walk(base):
        for a in archivos:
            if a.endswith(".jsonl"):
                r = os.path.join(raiz, a)
                candidatas.append((os.path.getmtime(r), r))
    return max(candidatas)[1] if candidatas else None


def main():
    modo = sys.argv[1] if len(sys.argv) > 1 else "prompt"
    if modo == "diagnostico":
        diagnostico(sys.argv[2] if len(sys.argv) > 2 else ultima_transcripcion())
        return
    try:
        datos = json.load(sys.stdin)
    except ValueError:
        return
    salida = al_iniciar(datos) if modo == "inicio" else al_enviar(datos)
    if salida:
        print(json.dumps(salida, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — un aviso nunca debe trabar el chat
        pass
