# Presentation Outline

## Page 1 [cover]
- **Title**: SIMA — Sistema Inteligente de Microaprendizaje Adaptativo
- **Content**: Plataforma web que transforma grabaciones y apuntes de clases universitarias en material de estudio personalizado con evaluaciones adaptativas IRT 3PL

## Page 2 [table_of_contents]
- **Title**: Agenda
- **Content**: 1. Contexto y problemática; 2. Arquitectura de SIMA; 3. Pipeline de procesamiento; 4. Módulos principales; 5. UI/UX y gamificación; 6. Stack tecnológico y estado actual

## Page 3 [chapter]
- **Title**: 01 — Contexto y Problemática
- **Content**: El gap entre la clase tradicional y el repaso efectivo

## Page 4 [content]
- **Title**: El estudiante universitario peruano enfrenta un problema de retención
- **Content**: Los estudiantes graban clases o toman apuntes masivos, pero no tienen herramientas para convertir ese contenido en material de estudio accionable. El 94% de profesionales L&D favorece el microaprendizaje, pero las plataformas existentes no generan contenido a partir de las clases propias del estudiante. SIMA nace para cerrar ese gap: convierte audio/texto de clase en resúmenes, flashcards, quizzes adaptativos y recomendaciones personalizadas — todo calibrado con IRT 3PL y taxonomía Bloom.

## Page 5 [chapter]
- **Title**: 02 — Arquitectura de SIMA
- **Content**: Django, PostgreSQL, Whisper local, Claude API y motor CAT propio

## Page 6 [content]
- **Title**: Arquitectura C4 — tres niveles de abstracción reales
- **Content**: Contexto: Estudiante y Admin interactúan con SIMA; SIMA consume Whisper (local) para transcribir audio y Claude API (externo) para generar y verificar items IRT. Contenedores: Web Application (Django 4.x) orquesta todo; Base de datos (SQLite dev / PostgreSQL prod); Almacenamiento local /media; Servicio de transcripción Whisper; Servicio de generación IA Claude. Componentes: Views, Models, Services, Forms, Templates, Django Admin, Auth. Todo documentado en Structurizr DSL dentro del repo.

## Page 7 [content]
- **Title**: Modelo de datos relacional — 16 entidades principales
- **Content**: Course (curso académico con periodo, nivel, metas), ClassSession (clase con estados: draft, queued, processing, ready, error), Transcript / TranscriptSegment (transcripción segmentada por tema), Summary (resumen breve, estructurado o acumulado del curso), Flashcard (pregunta/respuesta con mastery_level y next_review_at para SM-2), Quiz / Question / AnswerOption (quiz adaptativo con parámetros IRT a, b, c), StudentAnswer / AdaptiveProfile (theta por curso, weak_topics, strong_topics), QuizAttempt / QuizResponse (sesión CAT con theta_before/after), Profile / UserPreference (plan, racha, XP, nivel, tema, meta diaria), CreditLedgerEntry / StudyActivity / StudyStreak / Recommendation (sistema de créditos, gamificación y recomendaciones).

## Page 8 [chapter]
- **Title**: 03 — Pipeline de Procesamiento
- **Content**: De 4,439 palabras a 50+ items calibrados en 11 etapas

## Page 9 [content]
- **Title**: Pipeline end-to-end: 11 etapas con trazabilidad completa
- **Content**: 1. Entrada: audio o texto → LessonJob status=QUEUED. 2. Transcripción: Whisper local (openai-whisper) convierte audio a texto. 3. Generación MINI: Qwen3 30B local o Claude API genera items en formato MINI (a| cabecera + iN| items). 4. Filtro de incoherentes: detecta enunciados sin ? ni ____; 53 items → 22 incoherentes detectados (no se descartan, se reparan). 5. Reparación de incoherentes: prompt específico convierte cada enunciado en pregunta. 6. Reparación de coherencia general: reescritura quirúrgica manteniendo contenido factual. 7. Construcción de contexto de verificación: búsqueda web vía ddgs + dataset EduQG local. 8. Verificación por IA: revisa corrección factual, plausibilidad de distractores, coherencia IRT/Bloom. 9. Aplicación de correcciones: parseo línea por línea con fallback por nivel Bloom. 10. Relleno de items si es necesario: genera items adicionales para alcanzar banco mínimo IRT. 11. Validación final y persistencia: status=CORRECTED, traza JSON completa.

## Page 10 [chapter]
- **Title**: 04 — Módulos Principales
- **Content**: Transcripción, generación, evaluación adaptativa y seguimiento del progreso

## Page 11 [content]
- **Title**: Módulo 1 — Transcripción automática con Whisper local
- **Content**: Backend: openai-whisper (modelo configurable vía WHISPER_MODEL, default "base"). Proceso: archivo de audio subido a /media → transcrito localmente en el mismo servidor → texto guardado en Transcript.full_text con segmentos por tiempo (TranscriptSegment: start_seconds, end_seconds, text, topic, confidence). Reparación: si la transcripción tiene ruido o deformaciones, un prompt específico (transcript_prompt.md) reconstruye el contenido antes de generar items. Ventaja: no depende de servicios externos de transcripción, costo cero, privacidad total del contenido académico.

## Page 12 [content]
- **Title**: Módulo 2 — Generación de microcontenidos (MINI + IRT 3PL)
- **Content**: Formato MINI: cabecera a|m=IRT3PL|d=YYYYMMDD|n=total|l=es|t=tema|bd=L1-L6|cat=θ_init,θ_min,θ_max,se_stop,max_items,exposure_ctrl. Items: iN|bloom|topic|enunciado|opA,opB,opC,opD|a,b,c|difficulty|content_area,exposure_cap,cognitive_demand. Parámetros IRT: discriminación (a) 0.8-2.5 según nivel Bloom, dificultad (b) -1.5 a 2.0, pseudoazar (c) base 1/4 opciones. Regla de oro: todo enunciado es pregunta con ? o completación con ____. Las 4 alternativas son de la misma categoría semántica y longitud similar. Backend: soporta Claude API (Anthropic) y modelos locales vía OpenAI-compatible API (LM Studio, Ollama). Selección dinámica de backend según disponibilidad.

## Page 13 [content]
- **Title**: Módulo 3 — Evaluaciones adaptativas (CAT motor propio)
- **Content**: Motor implementado en cat.py: selección de ítems por máxima información de Fisher (IRT 3PL), distribución balanceada por nivel Bloom, penalización por exposición. Configuración CAT por cabecera MINI: theta_init=0, theta_min=-3, theta_max=3, se_stop=0.30, max_items=10, exposure_control=SH. Estimación de theta: máxima verosimilitud con 18 iteraciones, clamped al rango [-3, 3]. Niveles de habilidad: Inicial → Básico → En desarrollo → Intermedio → Avanzado → Dominio → Experto. La UI muestra anillo de progreso SVG animado, medallas de nivel, XP ganado, y barras Bloom por nivel de pensamiento. Quiz configurables: 5 (rápido), 10 (estándar), 15 (intenso) preguntas.

## Page 14 [content]
- **Title**: Módulo 4 — Seguimiento de progreso y recomendaciones
- **Content**: AdaptiveProfile: theta por curso, weak_topics, strong_topics, recommended_difficulty. StudentAnswer: cada respuesta guarda theta_before y theta_after, permitiendo ver evolución de habilidad. StudyActivity: tracking de XP y tiempo por actividad (clase subida, resumen revisado, flashcards repasadas, quiz completado). Recommendation: sistema de recomendaciones pendientes/completadas/descartadas con prioridad y fecha límite. Dashboard: cursos activos, clases creadas, materiales listos, meta diaria configurable. Heatmap de actividad, racha actual, nivel y XP totales.

## Page 15 [chapter]
- **Title**: 05 — UI/UX y Gamificación
- **Content**: Diseño mobile-first inspirado en Duolingo, con identidad propia

## Page 16 [content]
- **Title**: Vistas principales — Landing, Dashboard y Detalle de Clase
- **Content**: Landing (/): hero con preview de producto, flujo de 3 pasos (curso → clase → repaso), bento grid de outputs (resumen, quiz, flashcards, recomendación), y planes de suscripción. Dashboard (/dashboard/): tabs de cursos, clases, explorar, guardadas, preferencias. Header gamificado con racha, nivel, XP, clases restantes. Grid de tarjetas de curso con periodo, clases, tags. Lista de clases con badges de visibilidad (privada, compartida, pública) y estado. Detalle de clase (/clase/<pk>/): meta de clase con badges de preguntas, IRT, verificado. Selector de intensidad (5/10/15 preguntas). Barra gamificada con nivel y racha. Botones de acción: Repasar flashcards, Ver pipeline, Mapa de temas, Emparejar conceptos, Completar frases. Modo avanzado colapsado: transcripción, vista MINI raw, reporte de verificación.

## Page 17 [content]
- **Title**: Gamificación implementada — Créditos, racha, niveles y logros
- **Content**: Sistema de créditos: cada acción consume/gana créditos (transcripción, generación de resumen, flashcards, quiz, evaluación adaptativa, regeneración). Planes: Gratis (30 créditos), Básico ($5, 600 créditos, 6 clases API), Pro ($10, 2200 créditos, 20 clases), Ilimitado ($25). Gamificación: current_streak / longest_streak (días seguidos estudiando), total_xp, nivel = (total_xp // 100) + 1. Meta diaria configurable (default 10 preguntas). Preferencias: tema claro/oscuro/sistema, idioma español/inglés, minutos de estudio default. Visibilidad: privada, compartida con link (share_token), pública en explorar. Badges SVG inline (fuego, rayo, libro, candado, link, globo) — sin emojis, consistentes en todos los OS.

## Page 18 [chapter]
- **Title**: 06 — Stack Tecnológico y Estado Actual
- **Content**: Django 4.x, Python, PostgreSQL, Whisper, Claude API, IRT/CAT propio

## Page 19 [content]
- **Title**: Stack real y estado de implementación
- **Content**: Backend: Django 4.x + Python 3.11, SQLite (dev) / PostgreSQL (prod). Frontend: HTML + CSS vanilla, sin framework JS. Zero dependencias de build. Templates: 18 templates HTML en learning/ + base.html + landing pages. Estilos: CSS custom con variables CSS, responsive mobile-first, dark mode soportado. IA: Anthropic Claude API (verificación) + modelos locales Qwen3 30B vía OpenAI-compatible API (generación). Transcripción: openai-whisper local. Motor CAT: implementación propia en cat.py (157 líneas, puro Python + math). Pipeline: 11 etapas con trazabilidad JSON completa. Tests: pipeline de generación, verificación, coherencia y reparación validados con logs. Estado: core funcional — transcripción, generación MINI, verificación, correcciones, quiz adaptativo, flashcards, gamificación, dashboard, planes de crédito, compartir clases. Próximos: motor SM-2 para flashcards, ranking por clase, grupos de estudio, notificaciones push.

## Page 20 [final]
- **Title**: SIMA — De la clase a la dominación, paso a paso
- **Content**: Convierte tus grabaciones y apuntes en material de estudio inteligente. Evaluaciones adaptativas que entienden tu nivel. Microaprendizaje que se siente como un juego. Hecho en Perú, para universitarios peruanos. Código abierto en desarrollo activo.
