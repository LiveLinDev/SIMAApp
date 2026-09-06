workspace "SIMA — Contenedores" "Descomposición interna del sistema SIMA (estado septiembre 2026)" {

    !identifiers hierarchical

    model {
        estudiante = person "Estudiante" "Usa la plataforma desde el navegador (escritorio o móvil)."
        admin      = person "Administrador" "Gestiona el sistema vía Django Admin."

        cloud = softwareSystem "Proveedor de IA en la nube" "DeepSeek u otro modelo compatible con OpenAI, o Anthropic; configurable por variables de entorno." {
            tags "External"
        }
        whisper = softwareSystem "Whisper (local)" "Transcripción con segmentos y tiempo dentro del servidor." {
            tags "External"
        }
        correo = softwareSystem "Servidor de correo (SMTP)" {
            tags "External"
        }

        sima = softwareSystem "SIMA" {

            web = container "Aplicación web" "Django 4.x/5.x. Vistas por dominio (learning/views/), motor adaptativo (adaptive, psychometrics, spaced_repetition), servicios de IA (learning/services/), créditos, resúmenes, progreso y recordatorios. Con SIMA_QUEUE_MODE=thread también ejecuta el worker en hilos." "Python / Django"

            worker = container "Worker de trabajos" "Proceso aparte (manage.py run_worker) con SIMA_QUEUE_MODE=db: reclama en la base de datos los trabajos en cola (clases, refuerzos, resúmenes) con bloqueo, ejecuta el pipeline y reencola los atascados. Varios workers pueden convivir." "Python / Django management command"

            scheduler = container "Tareas programadas" "Programador de tareas de Windows o cron: send_study_reminders (diario), run_worker --once (opcional), requeue_jobs." "Sistema operativo"

            db = container "Base de datos" "Usuarios, perfiles y créditos; cursos, clases (LessonJob), transcripciones con segmentos; banco de preguntas con estadísticas y calibración; sesiones de práctica y respuestas; perfil adaptativo por curso; flashcards SM-2; resúmenes; trabajos de refuerzo y resumen; actividad, racha y recomendaciones." "PostgreSQL" {
                tags "Database"
            }

            storage = container "Almacenamiento de archivos" "Audios subidos (se descartan tras transcribir) y logs rotativos (logs/sima.log)." "Sistema de archivos local" {
                tags "Storage"
            }
        }

        estudiante -> sima.web       "Sube clases, practica, repasa, genera refuerzo y resúmenes, revisa progreso (HTTPS)"
        admin      -> sima.web       "Accede a Django Admin (HTTPS)"

        sima.web    -> sima.db       "Lee y escribe todo el modelo; deja trabajos en cola (QUEUED)"
        sima.web    -> sima.storage  "Guarda audios y escribe logs"
        sima.web    -> cloud         "Refuerzo y resúmenes en modo thread; también el pipeline de clase"
        sima.web    -> whisper       "Transcribe en modo thread"

        sima.worker -> sima.db       "Reclama trabajos (select_for_update skip_locked), guarda resultados y estado"
        sima.worker -> cloud         "Genera y verifica ítems .mini, refuerzo y resúmenes"
        sima.worker -> whisper       "Transcribe el audio de la clase"
        sima.worker -> sima.storage  "Lee audios; escribe logs"

        sima.scheduler -> sima.web   "Ejecuta comandos de gestión (recordatorios, reencolado)"
        sima.web    -> correo        "Envía recordatorios de estudio"
    }

    views {
        container sima "Contenedores" {
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
            element "Container" {
                background #58cc02
                stroke     #46a302
                shape      roundedBox
            }
            element "Database" {
                shape      cylinder
                background #24323f
                stroke     #0d1a22
            }
            element "Storage" {
                shape      folder
                background #24323f
                stroke     #0d1a22
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
