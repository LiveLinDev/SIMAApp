workspace "SIMA — Contenedores" "Descomposición interna del sistema SIMA" {

    !identifiers hierarchical

    model {
        estudiante = person "Estudiante" "Usa la plataforma desde el navegador o móvil."
        admin      = person "Administrador" "Gestiona el sistema vía Django Admin."

        claude = softwareSystem "Anthropic Claude API" "Genera y verifica ítems IRT en formato MINI. Solo interviene en el pipeline de ingesta de clases." {
            tags "External"
        }

        whisper = softwareSystem "Whisper (local)" "Transcribe audio a texto dentro del servidor." {
            tags "External"
        }

        sima = softwareSystem "SIMA" {

            web = container "Web Application" "Orquesta toda la lógica: ingesta de clases, pipeline IRT (generación → verificación → corrección), quizzes adaptativos con selección de ítems por theta CAT, flashcards con repetición espaciada y seguimiento de progreso gamificado." "Python / Django 4.x"

            db = container "Base de datos" "Almacena usuarios, perfiles, planes, LessonJobs con sus ítems IRT, sesiones de evaluación, respuestas del estudiante, parámetros theta actualizados y progreso diario (racha, XP, nivel)." "SQLite (dev) / PostgreSQL (prod)" {
                tags "Database"
            }

            storage = container "Almacenamiento de archivos" "Guarda los audios subidos por el estudiante antes de transcribir." "Sistema de archivos local /media" {
                tags "Storage"
            }
        }

        estudiante -> sima.web    "Sube clases, completa quizzes y revisa progreso (HTTPS)"
        admin      -> sima.web    "Accede a Django Admin (HTTPS)"

        sima.web -> sima.db       "Lee y escribe clases, ítems IRT, sesiones y progreso"
        sima.web -> sima.storage  "Guarda y lee archivos de audio"
        sima.web -> whisper       "Envía ruta de audio; recibe transcripción"
        sima.web -> claude        "Envía contenido de clase; recibe ítems IRT en formato MINI"
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
