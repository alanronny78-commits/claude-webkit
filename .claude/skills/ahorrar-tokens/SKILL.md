---
name: ahorrar-tokens
description: Revisa cuánto pesa el chat actual y prepara el mensaje para seguir en un chat nuevo sin perder nada. Úsala cuando el usuario escriba /ahorrar-tokens, pida "ahorrar tokens", "¿el chat está muy largo?", "abrir un chat nuevo", "pásame esto a otro chat", o pregunte qué modelo usar para una tarea.
---

# Ahorrar tokens

Los avisos automáticos (chat largo, imágenes, modelo, «revisión ligera») los da
el hook `.claude/hooks/ahorro_tokens.py`, configurado en `.claude/settings.json`.
Esta skill es la parte que se pide a mano. Sé breve: esta skill existe para
gastar menos, así que no la conviertas en un informe largo.

## 1. Diagnóstico del chat

Corre:

```
python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/ahorro_tokens.py" diagnostico
```

Y resume en 2–3 líneas, sin jerga: cuánto acumuló el chat (BAJO / MEDIO / ALTO),
cuántas imágenes lleva y qué modelo está usando. Si el nivel es MEDIO o ALTO, o
hay 4 imágenes o más, recomienda abrir un chat nuevo.

## 2. Mensaje de traspaso para el chat nuevo

Si conviene cambiar de chat (o el usuario lo pide), entrégale **un solo bloque
para copiar y pegar**, de no más de ~10 líneas:

- Qué archivos leer primero (rutas del repositorio: `CLAUDE.md` se lee solo;
  nombra los demás: notas, guiones, el archivo de código en el que se trabaja).
- Qué quedó hecho y en qué rama/commit, en una línea.
- Qué falta hacer exactamente, con todos los cambios juntos (A, B y C).
- El nivel de revisión: «revisión ligera» o «revisión completa».

Antes de armarlo, asegúrate de que lo importante esté guardado en el repositorio
(commit y push hechos). Si hay algo solo en este chat (una decisión, una lista),
propón guardarlo en el archivo de notas que corresponda; lo que no está en el
repositorio se pierde al cambiar de chat.

No incluyas en el traspaso el historial del chat, solo lo necesario para seguir.

## 3. Qué modelo usar

| Tarea | Modelo |
|---|---|
| Textos, correos, traducciones, preguntas, renombrar, cambios chicos | **Haiku** o **Sonnet** |
| Cambios normales de código, funciones o pantallas nuevas, pruebas | **Sonnet** |
| Seguridad, datos ya guardados, migraciones, arquitectura, videos, errores difíciles, y las zonas sensibles que marque el `CLAUDE.md` del proyecto | **Opus** |

Se cambia en el selector de modelo (o con `/model` en la terminal). Si dudas, Sonnet.

## 4. Recordatorios (solo si vienen al caso)

1. **Un chat nuevo para cada tarea.** Es lo que más ahorra.
2. **Pocas capturas, y recortadas.** Cada imagen se queda en el chat y se vuelve a pagar en cada mensaje.
3. **Pedidos completos en un solo mensaje:** «cambia A, B y C» mejor que tres mensajes.
4. **Di cuánta revisión quieres.** «revisión ligera» en cambios menores; «revisión completa» en lo delicado.
5. **Modelo liviano para tareas simples** (tabla de arriba).

## Qué significa «revisión ligera»

Hacer el cambio y comprobar solo lo mínimo: que el archivo quede bien y que
pasen las comprobaciones obligatorias antes de subir (las que indique el
`CLAUDE.md` del proyecto: pruebas, compilación, etc.). Sin revisar fotograma
por fotograma, sin volver a montar videos, sin recorrer pantallas. **Nunca**
aplica a las zonas sensibles (las que marque `CLAUDE.md`, o seguridad y datos ya
guardados): ahí la revisión es completa aunque se pida ligera, y se avisa en una línea.
