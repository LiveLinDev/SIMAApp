workspace "SIMA — Componentes" "Componentes internos de la aplicación web de SIMA (estado septiembre 2026; todo existe)" {

    !identifiers hierarchical

    model {
        estudiante = person "Estudiante" "Usa la plataforma desde el navegador."
        admin      = person "Administrador" "Gestiona el sistema vía Django Admin."

        cloud = softwareSystem "Proveedor de IA en la nube" "DeepSeek / compatible OpenAI / Anthropic." {
            tags "External"
        }
        whisper = softwareSystem "Whisper (local)" "Transcripción con segmentos." {
            tags "External"
        }
        db = softwareSystem "Base de datos" "PostgreSQL." {
            tags "External"
        }
        correo = softwareSystem "SMTP" {
            tags "External"
        }

        sima = softwareSystem "SIMA" {

            web = container "Aplicación web" "Django" {

                # ── Vistas (learning/views/) ───────────────────────────────
                views_core = component "Vistas: inicio y panel" "Registro, inicio con «Hoy en SIMA», progreso de dos semanas, preferencias (meta diaria, recordatorios), planes y /salud/." "learning/views/core.py"
                views_courses = component "Vistas: cursos" "Crear, editar, archivar y restaurar cursos; detalle con plan de hoy, progreso, resumen, refuerzos; banco del curso y exportaciones CSV." "learning/views/courses.py"
                views_lessons = component "Vistas: clases" "Carga de clase (audio o texto), estado en vivo, reintentos, reparaciones de transcripción y coherencia, visibilidad, descarga; «Practicar esta clase»." "learning/views/lessons.py"
                views_practice = component "Vistas: práctica" "Sesión adaptativa (pregunta, respuesta con retroalimentación inmediata, cierre), recomendaciones, refuerzo dirigido." "learning/views/practice.py"
                views_study = component "Vistas: estudio" "Flashcards por clase, repaso SM-2 por curso, ejercicios de emparejar y completar, mapa de la clase." "learning/views/study.py"
                views_summaries = component "Vistas: resúmenes" "Resumen de clase y acumulado del curso (encolan un SummaryJob y muestran su estado)." "learning/views/summaries_views.py"
                views_pipeline = component "Vistas: trazas del pipeline" "Visualización etapa por etapa de una clase con métricas y trazas JSON." "learning/views/pipeline.py"

                # ── Núcleo adaptativo ──────────────────────────────────────
                adaptive = component "Núcleo adaptativo" "Banco del curso desde el .mini verificado; sesión CAT (equilibrada, temas débiles, riesgo de olvido, simulacro); perfil por tema y Bloom; olvido por vida media; plan de hoy; recomendaciones; XP y racha; informe del banco." "learning/adaptive.py"
                psychometrics = component "Psicometría" "IRT 3PL (cat.py) + EAP, selección randomesque, calibración Elo de la dificultad, Bayesian Knowledge Tracing y puerta de calidad." "learning/cat.py, learning/psychometrics.py"
                spaced = component "Repetición espaciada" "SM-2 para flashcards: factor de facilidad, intervalos, cola de repaso del curso." "learning/spaced_repetition.py"
                generation = component "Generación adaptativa" "Refuerzo dirigido: ítems b≈θ sobre temas débiles, explicaciones y flashcards; cobra créditos y reembolsa." "learning/adaptive_generation.py"
                summaries = component "Resúmenes" "Resumen estructurado de clase y acumulado del curso; SummaryJob en cola." "learning/summaries.py"
                segments = component "Segmentos" "Segmentos de transcripción con tiempo y enlace pregunta ↔ fragmento de la clase." "learning/segments.py"
                progress = component "Progreso y recordatorios" "Serie diaria y SVG de dos semanas; correos de recordatorio." "learning/progress.py, learning/reminders.py"
                credits = component "Créditos" "Planes, estimación de costos, cobro y reembolso en un ledger." "learning/credits.py"

                # ── Pipeline y servicios de IA ─────────────────────────────
                queue = component "Cola de trabajos" "Encolado en hilos o en BD, worker, reclamo con bloqueo, reencolado de huérfanos y límite de trabajos por usuario." "learning/job_queue.py, management/commands/run_worker.py"
                pipeline = component "Pipeline de la clase" "Transcripción → generación → reparaciones → verificación → corrección → ClassSession/Transcript → banco del curso." "learning/pipeline.py"
                portability = component "Portabilidad" "Exportar e importar un curso como JSON (clases, resúmenes, flashcards) con reconstrucción del banco." "learning/portability.py"
                svc_prompts = component "Servicios: prompts" "Plantillas PROMPT.md / coherence / correct y limpieza del contenido." "learning/services/prompts.py"
                svc_backends = component "Servicios: proveedores" "Resolución de backend (nube compatible OpenAI, Anthropic, local), call_ai, errores." "learning/services/backends.py"
                svc_generation = component "Servicios: generación" "Chunks, presupuesto adaptativo de ítems, reintentos, extracción del bloque .mini." "learning/services/generation.py"
                svc_repairs = component "Servicios: verificación y reparaciones" "Verificación factual y reparaciones del .mini con trazas de cambios." "learning/services/repairs.py"
                svc_evidence = component "Servicios: evidencia" "Búsqueda web, documentos fuente y referencia EduQG para la verificación." "learning/services/evidence.py"
                svc_transcription = component "Servicios: transcripción" "Whisper local: texto y segmentos con tiempo." "learning/services/transcription.py"
                parse_mini = component "Formato .mini" "Parser/serializador, filtros de coherencia y uniformidad, aplicación de correcciones." "learning/parse_mini.py"

                # ── Infraestructura compartida ─────────────────────────────
                models = component "Modelo de datos" "Course, LessonJob, ClassSession, Transcript(+Segment), Quiz/Question/AnswerOption, PracticeSession, StudentAnswer, AdaptiveProfile, Flashcard, Summary, ReinforcementJob, SummaryJob, Recommendation, StudyActivity, Profile, CreditLedgerEntry." "learning/models.py (23 migraciones)"
                templates = component "Plantillas" "24 plantillas server-side con CSS propio (claro/oscuro, móvil)." "templates/learning/"
                auth = component "Auth y admin" "Autenticación, sesiones, @login_required; Django Admin para todo el modelo." "django.contrib"
            }
        }

        estudiante -> sima.web.views_core     "Inicio, preferencias"
        estudiante -> sima.web.views_courses  "Cursos, banco, CSV"
        estudiante -> sima.web.views_lessons  "Sube y revisa clases"
        estudiante -> sima.web.views_practice "Practica, refuerzo"
        estudiante -> sima.web.views_study    "Repasa y ejercita"
        estudiante -> sima.web.views_summaries "Resúmenes"
        admin      -> sima.web.auth           "Django Admin"

        sima.web.views_core      -> sima.web.adaptive   "Hoy en SIMA, plan de hoy"
        sima.web.views_core      -> sima.web.progress   "Progreso de dos semanas"
        sima.web.views_courses   -> sima.web.adaptive   "Resumen del curso, plan, banco"
        sima.web.views_courses   -> sima.web.progress   "Progreso del curso"
        sima.web.views_lessons   -> sima.web.queue      "Encola la clase"
        sima.web.views_lessons   -> sima.web.credits    "Estima y cobra créditos"
        sima.web.views_practice  -> sima.web.adaptive   "Sesión, respuesta, cierre"
        sima.web.views_practice  -> sima.web.generation "Refuerzo dirigido"
        sima.web.views_study     -> sima.web.spaced     "Calificación SM-2"
        sima.web.views_summaries -> sima.web.summaries  "Encola SummaryJob"
        sima.web.views_pipeline  -> sima.web.models     "Lee trazas del LessonJob"

        sima.web.adaptive     -> sima.web.psychometrics "Estimación, selección, calibración, BKT"
        sima.web.adaptive     -> sima.web.segments      "Fragmento y minuto por pregunta"
        sima.web.adaptive     -> sima.web.parse_mini    "Lee el .mini verificado"
        sima.web.adaptive     -> sima.web.spaced        "Tarjetas vencidas para el plan"
        sima.web.generation   -> sima.web.svc_backends  "call_ai"
        sima.web.generation   -> sima.web.credits       "Cobro y reembolso"
        sima.web.generation   -> sima.web.queue         "ReinforcementJob en cola"
        sima.web.summaries    -> sima.web.svc_backends  "call_ai"
        sima.web.summaries    -> sima.web.credits       "Cobro y reembolso"
        sima.web.summaries    -> sima.web.queue         "SummaryJob en cola"
        sima.web.progress     -> correo                 "Recordatorios"

        sima.web.queue -> sima.web.pipeline          "Ejecuta el pipeline de la clase"
        sima.web.queue -> sima.web.generation        "Ejecuta refuerzos"
        sima.web.queue -> sima.web.summaries         "Ejecuta resúmenes"
        sima.web.pipeline -> sima.web.svc_transcription "Transcribe"
        sima.web.pipeline -> sima.web.svc_generation    "Genera ítems"
        sima.web.pipeline -> sima.web.svc_repairs       "Verifica y repara"
        sima.web.pipeline -> sima.web.parse_mini        "Filtra y corrige"
        sima.web.pipeline -> sima.web.adaptive          "Sincroniza el banco del curso"
        sima.web.portability -> sima.web.pipeline       "Recrea ClassSession"
        sima.web.portability -> sima.web.adaptive       "Reconstruye el banco"

        sima.web.svc_generation -> sima.web.svc_prompts  "Plantillas"
        sima.web.svc_generation -> sima.web.svc_backends "call_ai"
        sima.web.svc_repairs    -> sima.web.svc_evidence "Contexto de verificación"
        sima.web.svc_repairs    -> sima.web.svc_backends "call_ai"
        sima.web.svc_evidence   -> sima.web.svc_backends "Consultas generadas por IA"
        sima.web.svc_backends   -> cloud                  "Peticiones al modelo"
        sima.web.svc_transcription -> whisper             "Transcribe"

        sima.web.models -> db "Persistencia"
        sima.web.views_core -> sima.web.templates "Renderiza"
        sima.web.views_core -> sima.web.auth      "Protegido"
    }

    views {
        component sima.web "Componentes" {
            include *
            autoLayout lr
        }

        styles {
            element "Element" {
                color  #ffffff
                stroke #ffffff
            }
            element "Person" {
                shape      person
                background #1cb0f6
                stroke     #168ac2
            }
            element "Component" {
                background #58cc02
                stroke     #46a302
                shape      roundedBox
            }
            element "External" {
                background #6b7a88
                stroke     #4a5560
            }
            relationship "Relationship" {
                thickness 3
            }
        }
    }
}
