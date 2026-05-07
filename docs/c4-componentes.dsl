workspace "SIMA — Componentes" "Componentes internos del Web Application de SIMA" {

    !identifiers hierarchical

    model {
        estudiante = person "Estudiante" "Usa la plataforma desde el navegador o móvil."
        admin      = person "Administrador" "Gestiona el sistema vía Django Admin."

        claude = softwareSystem "Anthropic Claude API" "Genera y verifica ítems IRT en formato MINI." {
            tags "External"
        }
        whisper = softwareSystem "Whisper (local)" "Transcribe audio a texto dentro del servidor." {
            tags "External"
        }
        db = softwareSystem "Base de datos" "PostgreSQL / SQLite." {
            tags "External"
        }

        sima = softwareSystem "SIMA" {

            web = container "Web Application" "Django 4.x" {

                # ── Ingesta y pipeline IRT ─────────────────────────────────
                lesson_views = component "Lesson Views" "Gestiona el ciclo completo de una clase: creación (free/api), transcripción, generación de ítems IRT, verificación, corrección y descarga. Rutas: free_lesson, api_lesson, lesson_detail, submit_toon, submit_verification, submit_correction, download_json." "learning/views.py — existe"

                lesson_models = component "LessonJob Model" "Entidad central del pipeline. Campos: source_text, audio, transcript, generation_prompt, toon_output (ítems MINI brutos), verification_prompt, verification_output (reporte v|), corrected_output (ítems MINI finales), status, error." "learning/models.py — existe"

                services = component "Services" "Integración con IA. Funciones: build_generation_prompt, build_verification_prompt, call_claude, transcribe_audio, configure_local_ffmpeg." "learning/services.py — existe"

                # ── Evaluación adaptativa (planeado) ──────────────────────
                adaptive_engine = component "Motor Adaptativo CAT" "Selecciona el siguiente ítem óptimo según el theta (habilidad estimada) actual del estudiante usando el criterio de máxima información Fisher. Actualiza theta tras cada respuesta con estimación MLE/EAP." "learning/cat_engine.py — planeado" {
                    tags "Planned"
                }

                eval_views = component "Evaluation Views" "Sirve sesiones de evaluación diaria: inicia quiz adaptativo, recibe respuestas, delega selección de ítem al Motor CAT y registra la sesión. Rutas: quiz_start, quiz_next, quiz_finish." "learning/views.py — planeado" {
                    tags "Planned"
                }

                eval_models = component "Evaluation Models" "QuizSession (sesión activa: theta_actual, ítems vistos, respuestas), QuizResponse (ítem respondido, correcto, theta antes/después), FlashCard (frente/reverso extraído de ítems IRT, intervalo de repaso espaciado, fecha próxima revisión)." "learning/models.py — planeado" {
                    tags "Planned"
                }

                # ── Repetición espaciada (planeado) ───────────────────────
                spacedrepetition = component "Motor de Repetición Espaciada" "Calcula el intervalo de repaso de cada flashcard usando el algoritmo SM-2. Actualiza facilidad y fecha de próxima revisión según la autoevaluación del estudiante (fácil/regular/difícil)." "learning/spaced_repetition.py — planeado" {
                    tags "Planned"
                }

                flashcard_views = component "Flashcard Views" "Sirve sesiones de repaso de flashcards: muestra frente, recibe autoevaluación, delega al Motor de Repetición Espaciada. Rutas: flashcard_session, flashcard_review." "learning/views.py — planeado" {
                    tags "Planned"
                }

                # ── Progreso y gamificación (planeado) ────────────────────
                progress_views = component "Progress Views" "Muestra dashboard de progreso: racha diaria, XP acumulado, nivel, curva de theta por materia, historial de sesiones y logros desbloqueados. Rutas: progress, profile." "learning/views.py — planeado" {
                    tags "Planned"
                }

                progress_models = component "Progress & Gamification Models" "StudySession (fecha, tipo actividad, XP ganado, tiempo), StudentProgress (theta por materia, racha actual, XP total, nivel), Achievement (logros: primera clase, 7 días seguidos, quiz perfecto, etc.)." "learning/models.py — planeado" {
                    tags "Planned"
                }

                # ── Infraestructura compartida ─────────────────────────────
                profile_model = component "Profile & Plan Model" "Perfil del usuario: plan activo (free/basic/pro/unlimited), clases API usadas este mes, fecha de reset mensual." "learning/models.py — existe"

                forms = component "Forms" "Valida inputs del usuario: RegisterForm, FreeLessonForm, ApiLessonForm, PlanForm, ManualResultForm, VerificationResultForm." "learning/forms.py — existe"

                templates = component "Templates" "Renderiza HTML server-side. Existentes: home, dashboard, lesson_detail, lesson_form, plans. Planeados: quiz, flashcard_session, progress, profile." "templates/learning/ — existe + planeado"

                auth = component "Auth" "Autenticación, sesiones y decorador @login_required." "django.contrib.auth — existe"

                django_admin = component "Django Admin" "Administra usuarios, planes, LessonJobs y datos de progreso." "django.contrib.admin — existe"
            }
        }

        # ── Relaciones existentes ──────────────────────────────────────────
        estudiante -> sima.web.lesson_views    "Sube clases y gestiona el pipeline IRT"
        admin      -> sima.web.django_admin    "Administra datos del sistema"

        sima.web.lesson_views -> sima.web.forms          "Valida inputs"
        sima.web.lesson_views -> sima.web.lesson_models  "Lee y escribe LessonJobs"
        sima.web.lesson_views -> sima.web.services       "Orquesta transcripción y generación IRT"
        sima.web.lesson_views -> sima.web.templates      "Renderiza HTML"
        sima.web.lesson_views -> sima.web.auth           "Protegido con @login_required"

        sima.web.services -> claude   "Envía contenido; recibe ítems IRT en formato MINI"
        sima.web.services -> whisper  "Envía ruta de audio; recibe transcripción"

        sima.web.lesson_models -> db  "Persiste LessonJobs e ítems IRT"
        sima.web.profile_model -> db  "Persiste perfiles y planes"

        sima.web.django_admin -> sima.web.lesson_models  "Gestiona"
        sima.web.django_admin -> sima.web.profile_model  "Gestiona"

        # ── Relaciones planeadas ───────────────────────────────────────────
        estudiante -> sima.web.eval_views       "Inicia y responde quiz adaptativo diario"
        estudiante -> sima.web.flashcard_views  "Repasa flashcards con repetición espaciada"
        estudiante -> sima.web.progress_views   "Consulta progreso, racha y logros"

        sima.web.eval_views -> sima.web.lesson_models    "Lee ítems IRT corregidos del LessonJob"
        sima.web.eval_views -> sima.web.adaptive_engine  "Solicita siguiente ítem óptimo"
        sima.web.eval_views -> sima.web.eval_models      "Persiste sesión y respuestas"
        sima.web.eval_views -> sima.web.progress_models  "Registra XP y actualiza racha"
        sima.web.eval_views -> sima.web.templates        "Renderiza pantalla de quiz"
        sima.web.eval_views -> sima.web.auth             "Protegido con @login_required"

        sima.web.adaptive_engine -> sima.web.eval_models "Lee theta actual y respuestas previas"

        sima.web.flashcard_views -> sima.web.eval_models       "Lee flashcards pendientes de repaso"
        sima.web.flashcard_views -> sima.web.spacedrepetition  "Calcula próximo intervalo de repaso"
        sima.web.flashcard_views -> sima.web.progress_models   "Registra XP de la sesión"
        sima.web.flashcard_views -> sima.web.templates         "Renderiza pantalla de flashcard"
        sima.web.flashcard_views -> sima.web.auth              "Protegido con @login_required"

        sima.web.progress_views -> sima.web.progress_models  "Lee historial, racha y logros"
        sima.web.progress_views -> sima.web.eval_models      "Lee resultados de evaluaciones"
        sima.web.progress_views -> sima.web.templates        "Renderiza dashboard de progreso"
        sima.web.progress_views -> sima.web.auth             "Protegido con @login_required"

        sima.web.eval_models     -> db  "Persiste sesiones, respuestas y flashcards"
        sima.web.progress_models -> db  "Persiste progreso, XP, racha y logros"
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
            element "Planned" {
                background #ffc800
                stroke     #c99a00
                color      #24323f
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
