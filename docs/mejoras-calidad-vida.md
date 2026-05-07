# Mejoras de Calidad de Vida — SIMA

## Cambios implementados (última actualización)

### 1. Selector de backend de IA mejorado

**Problema**: El selector aparecía siempre, incluso cuando solo se transcribía audio (Whisper), y no quedaba claro que Whisper siempre es local.

**Solución**:
- Nota explicativa: "Whisper (transcripción de audio) siempre corre localmente, independiente de esta selección"
- El selector solo afecta la generación y verificación de ítems IRT
- Opciones claras:
  - **Anthropic Claude**: muestra "No configurado" con nota roja si `ANTHROPIC_API_KEY` no es real
  - **Modelo local**: muestra el nombre del modelo (ej: `qwen-coder-14b-q4km`) y endpoint (LM Studio / Ollama)
- Radio buttons con feedback visual inmediato (JS actualiza el estado)

### 2. Modal de visibilidad funcional

**Problemas**:
- No se podía cerrar (faltaba backdrop clickeable y botón X)
- Los radio buttons no cambiaban de color al seleccionar
- No se podía cambiar la visibilidad después de crear la clase

**Soluciones**:
- Backdrop oscuro clickeable para cerrar
- Botón X en la esquina superior derecha
- Radio buttons con estado visual manejado por JS (clase `.share-option--active`)
- Form funcional que hace POST a `/clase/<pk>/visibilidad/`
- Genera `share_token` automáticamente al elegir "Compartida con link"
- Muestra el link completo con botón "Copiar" que usa `navigator.clipboard`
- Se puede cambiar entre privada/compartida/pública en cualquier momento

### 3. Editar nombre de la clase

**Problema**: No había forma de cambiar el título después de crear la clase.

**Solución**:
- Botón de lápiz al lado del título en el header
- Click → muestra input inline con el título actual
- Botones "Guardar" y "Cancelar"
- POST a `/clase/<pk>/renombrar/`
- Límite de 140 caracteres
- Feedback con mensaje de éxito

### 4. SVGs en lugar de emojis

**Problema**: Los emojis se ven inconsistentes entre sistemas operativos y no son profesionales.

**Solución**:
- Todos los iconos reemplazados por SVGs inline con stroke configurable
- Dashboard: fuego (racha), rayo (XP), libro (clases), candado/link/globo (visibilidad)
- Lesson detail: compartir, descargar, editar, cerrar modal
- Empty states: gráficos, estrella, globo, libro
- Consistencia visual en toda la app

### 5. Detección automática de backend disponible

**Implementación**:
```python
def get_available_backends() -> dict:
    key = (settings.ANTHROPIC_API_KEY or "").strip()
    anthropic_real = bool(key) and key.lower() != "local"
    return {
        "anthropic": anthropic_real,
        "local": True,
        "default": "anthropic" if anthropic_real else "local",
    }
```

- Si `ANTHROPIC_API_KEY` es `"local"` o vacío → solo backend local disponible
- Si es una key real → ambos backends disponibles, Anthropic por defecto
- El backend seleccionado se pasa a `call_claude(prompt, backend="anthropic"|"local")`

### 6. Backend local con API compatible OpenAI

**Implementación**:
```python
def _call_local(prompt: str) -> str:
    local_base = getattr(settings, "LOCAL_API_BASE", "http://localhost:1234/v1")
    model = settings.ANTHROPIC_MODEL  # ej: qwen-coder-14b-q4km
    client = OpenAI(api_key="local", base_url=local_base)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=6000,
        temperature=0.2,
    )
    return response.choices[0].message.content or ""
```

Compatible con:
- LM Studio (puerto 1234 por defecto)
- Ollama (con proxy compatible OpenAI)
- Cualquier servidor local que implemente la API de OpenAI

---

## Próximas mejoras de calidad de vida (inspiradas en Duolingo)

### Feedback inmediato y animaciones

- [ ] Animación de confetti al completar un quiz perfecto
- [ ] Sonido de "ding" al responder correctamente
- [ ] Vibración suave en móvil al fallar
- [ ] Transiciones suaves entre preguntas (slide/fade)
- [ ] Barra de progreso animada durante el quiz

### Racha y motivación

- [ ] Notificación diaria: "¡No pierdas tu racha de X días!"
- [ ] Recordatorio si no has estudiado hoy (configurable)
- [ ] Celebración visual al alcanzar hitos (7, 30, 100 días)
- [ ] Comparación con tu mejor racha histórica
- [ ] Opción de "congelar racha" (1 día gratis al mes)

### Progreso visual

- [ ] Gráfico de evolución de θ (habilidad) por tema
- [ ] Mapa de calor de días estudiados (estilo GitHub)
- [ ] Círculo de progreso por materia con porcentaje
- [ ] Badges desbloqueables con animación
- [ ] Timeline de logros recientes

### Personalización

- [ ] Elegir avatar o foto de perfil
- [ ] Temas de color (claro/oscuro/verde/azul)
- [ ] Configurar meta diaria (5/10/15/20 preguntas)
- [ ] Elegir horario preferido para notificaciones
- [ ] Modo "intensivo" vs "relajado"

### Social y competencia

- [ ] Agregar amigos por username
- [ ] Ver racha de amigos (sin presión)
- [ ] Tabla de líderes semanal/mensual
- [ ] Compartir logro en redes sociales
- [ ] Grupos de estudio con ranking interno

### Adaptatividad IRT mejorada

- [ ] Mostrar θ (habilidad estimada) actual por tema
- [ ] Explicación simple: "Tu nivel en este tema es X/10"
- [ ] Sugerencia de ítems a repasar según θ bajo
- [ ] Predicción de probabilidad de éxito en próximo ítem
- [ ] Ajuste de dificultad en tiempo real visible

### Repetición espaciada (flashcards)

- [ ] Algoritmo SM-2 implementado
- [ ] Indicador de "próxima revisión en X días"
- [ ] Autoevaluación: Fácil/Regular/Difícil
- [ ] Priorizar flashcards que están por vencer
- [ ] Estadística de retención por flashcard

### Microinteracciones

- [ ] Botones con efecto de "press" (scale down)
- [ ] Hover states en todas las tarjetas
- [ ] Loading states con skeleton screens
- [ ] Toast notifications en lugar de alerts
- [ ] Confirmación visual al guardar cambios

### Accesibilidad

- [ ] Atajos de teclado (Enter para siguiente, 1-4 para opciones)
- [ ] Modo alto contraste
- [ ] Tamaño de fuente ajustable
- [ ] Screen reader friendly (ARIA labels)
- [ ] Navegación completa por teclado

### Onboarding

- [ ] Tour guiado para nuevos usuarios
- [ ] Tooltips contextuales en primera visita
- [ ] Video corto explicativo (30 seg)
- [ ] Clase de ejemplo pre-cargada
- [ ] Checklist de primeros pasos

---

## Principios de diseño aplicados

1. **Feedback inmediato**: Toda acción tiene respuesta visual instantánea
2. **Progreso visible**: El usuario siempre sabe dónde está y cuánto falta
3. **Motivación positiva**: Celebrar logros, no castigar errores
4. **Simplicidad**: Cada pantalla tiene un objetivo claro
5. **Consistencia**: Mismos patrones de interacción en toda la app
6. **Accesibilidad**: Usable con teclado, screen readers y diferentes tamaños
7. **Performance**: Animaciones a 60fps, carga rápida
8. **Mobile-first**: Diseñado primero para móvil, luego desktop

---

## Métricas de éxito

- **Engagement**: % de usuarios que vuelven al día siguiente
- **Racha promedio**: días consecutivos de estudio
- **Completion rate**: % de quizzes iniciados que se completan
- **Tiempo en app**: minutos por sesión (objetivo: 5-10 min)
- **NPS**: Net Promoter Score (¿recomendarías SIMA?)
- **Retención**: % de usuarios activos después de 7/30/90 días
