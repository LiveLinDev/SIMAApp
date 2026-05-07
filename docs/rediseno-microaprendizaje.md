# Rediseño SIMA — Microaprendizaje tipo Duolingo

## Cambios implementados

### 1. Dashboard rediseñado (`/dashboard/`)

**Antes**: Lista simple de clases recientes
**Ahora**: Hub de aprendizaje con 3 tabs

#### Tab "Mis clases"
- Grid de tarjetas de clase con:
  - Título y fecha
  - Badge de visibilidad (🔒 privada, 🔗 compartida, 🌐 pública)
  - Progreso visual (0 de X preguntas completadas)
  - CTA "Estudiar ahora" o "Ver pipeline" según estado
- Botones de acción: "+ Nueva clase con IA" y "+ Clase manual"
- Empty state educativo cuando no hay clases

#### Tab "Explorar"
- Placeholder para clases públicas de la comunidad
- Buscador por tema
- Próximamente: grid de clases públicas que otros estudiantes compartieron

#### Tab "Guardadas"
- Placeholder para clases guardadas desde Explorar
- Próximamente: colecciones y carpetas

#### Header con gamificación
- 🔥 Racha actual (días seguidos estudiando)
- ⚡ Nivel y XP total
- 📚 Clases API restantes del plan

---

### 2. Vista de clase rediseñada (`/clase/<id>/`)

**Filosofía**: El estudiante NO debe ver las respuestas correctas hasta que responda.

#### Vista principal: "Estudio" (cuando la clase está lista)

**Oculta las respuestas** — el estudiante solo ve:
- Meta de la clase: N preguntas, IRT adaptativo, badge de verificado
- **Plan de estudio**: selector de intensidad (5/10/15 preguntas por sesión)
- **CTA principal**: "Iniciar quiz adaptativo" (deshabilitado hasta implementar motor CAT)
- **Historial de intentos**: placeholder que muestra qué verá cuando complete quizzes:
  - Puntaje y preguntas correctas/incorrectas
  - Evolución de habilidad (θ) en el tiempo
  - Ítems que necesita repasar
  - Comparación con otros estudiantes
- **Ranking**: placeholder para comparar progreso con otros que estudian la misma clase
- **Botón "Modo avanzado"**: despliega el panel de pipeline

#### Panel "Modo avanzado" (colapsado por defecto)

Solo visible si el usuario hace clic en "Modo avanzado". Contiene:
- Toggle "Vista legible" / "MINI raw"
- Vista legible: ítems renderizados con colores Bloom, opciones correctas marcadas ✓
- Vista raw: texto MINI crudo
- Transcripción (si existe)
- Reporte de verificación (si existe)

**Propósito**: Permitir al creador de la clase revisar y editar, pero mantenerlo fuera del flujo de estudio.

#### Vista: "Pipeline" (cuando la clase aún no está lista)

Muestra los 4 pasos del pipeline:
1. Prompt generador
2. Pegar ítems generados
3. Prompt verificador
4. Pegar reporte → correcciones automáticas

Una vez corregida, redirige a la vista de Estudio.

---

### 3. Modelo de datos actualizado

#### `Profile` (gamificación)
```python
daily_goal = models.PositiveIntegerField(default=10)  # preguntas por día
current_streak = models.PositiveIntegerField(default=0)
longest_streak = models.PositiveIntegerField(default=0)
last_study_date = models.DateField(null=True, blank=True)
total_xp = models.PositiveIntegerField(default=0)

@property
def level(self):
    return (self.total_xp // 100) + 1  # cada 100 XP = 1 nivel
```

#### `LessonJob` (compartir y visibilidad)
```python
class Visibility(models.TextChoices):
    PRIVATE = "private", "Privada"
    SHARED = "shared", "Compartida con link"
    PUBLIC = "public", "Pública en explorar"

visibility = models.CharField(max_length=20, choices=Visibility.choices, default=Visibility.PRIVATE)
share_token = models.CharField(max_length=32, blank=True, unique=True, null=True)
```

---

### 4. Funcionalidades pendientes (próximamente)

#### Motor adaptativo CAT
- Modelo `QuizSession`: sesión activa con theta actual, ítems vistos, respuestas
- Modelo `QuizResponse`: cada respuesta con theta antes/después
- Componente `adaptive_engine.py`: selección de ítem óptimo por información Fisher
- Vista `quiz_start`, `quiz_next`, `quiz_finish`

#### Repetición espaciada
- Modelo `FlashCard`: frente/reverso, intervalo SM-2, fecha próxima revisión
- Componente `spaced_repetition.py`: algoritmo SM-2
- Vista `flashcard_session`, `flashcard_review`

#### Progreso y logros
- Modelo `StudySession`: fecha, tipo actividad, XP ganado, tiempo
- Modelo `StudentProgress`: theta por materia, racha, XP, nivel
- Modelo `Achievement`: logros desbloqueables (primera clase, 7 días seguidos, quiz perfecto, etc.)
- Vista `progress`, `profile`

#### Compartir y explorar
- Generar `share_token` único al cambiar visibilidad a "shared"
- Vista `shared_lesson/<token>`: acceso público de solo lectura
- Vista `explore`: grid de clases públicas con filtros por tema
- Modelo `SavedLesson`: relación many-to-many entre User y LessonJob para guardar clases de otros

#### Ranking
- Calcular ranking por clase: usuarios ordenados por theta final o puntaje promedio
- Vista `lesson_ranking/<id>`: tabla de posiciones

---

## Flujo de usuario ideal (cuando esté completo)

1. **Crear clase**: sube audio o pega apuntes → API genera ítems IRT → verificación automática
2. **Configurar intensidad**: elige 5/10/15 preguntas por sesión según su disponibilidad
3. **Iniciar quiz**: motor CAT selecciona el primer ítem según θ=0 (habilidad inicial neutra)
4. **Responder**: cada respuesta actualiza θ en tiempo real
5. **Finalizar sesión**: ve puntaje, ítems fallados, evolución de θ, gana XP
6. **Racha**: si estudia todos los días, la racha aumenta (gamificación)
7. **Compartir**: puede hacer la clase pública para que otros estudien con su material
8. **Explorar**: descubre clases de otros estudiantes sobre temas que le interesan
9. **Ranking**: compite sanamente con otros que estudian la misma clase

---

## Principios de diseño aplicados

1. **Ocultar respuestas**: el estudiante no ve las opciones correctas hasta que responde
2. **Modo avanzado colapsado**: el pipeline técnico no distrae del estudio
3. **Gamificación visible**: racha, XP y nivel siempre presentes en el dashboard
4. **Intensidad configurable**: el estudiante elige cuánto estudiar por sesión
5. **Social learning**: compartir, explorar y ranking fomentan comunidad
6. **Microaprendizaje**: sesiones cortas (3-10 min) adaptadas al ritmo del estudiante
7. **Feedback inmediato**: después de cada sesión, el estudiante ve qué mejorar

---

## Próximos pasos técnicos

1. Implementar `QuizSession` y motor CAT básico (selección aleatoria primero, luego IRT)
2. Crear vistas `quiz_start`, `quiz_next`, `quiz_finish`
3. Actualizar `Profile.current_streak` y `Profile.total_xp` al completar sesión
4. Implementar lógica de `share_token` y vista `shared_lesson/<token>`
5. Crear vista `explore` con filtro por tema y paginación
6. Implementar `SavedLesson` para guardar clases de otros
7. Agregar ranking por clase
8. Implementar flashcards con SM-2
9. Dashboard de progreso con gráficos de evolución de θ
10. Sistema de logros desbloqueables
