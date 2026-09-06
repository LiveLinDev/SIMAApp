workspace "SIMA" "Sistema Inteligente de Microaprendizaje Adaptativo" {

    model {
        estudiante = person "Estudiante" "Sube grabaciones o apuntes de clase, practica con evaluación adaptativa por curso, repasa con repetición espaciada, genera refuerzo y resúmenes, y sigue su progreso por tema."
        admin      = person "Administrador" "Gestiona usuarios, planes, trabajos y contenido desde Django Admin."

        sima = softwareSystem "SIMA" "Convierte clases universitarias (audio o texto) en un banco de ítems verificados (IRT 3PL, formato .mini) por curso y acompaña el estudio: práctica adaptativa con memoria (EAP, randomesque, calibración Elo, Bayesian Knowledge Tracing), refuerzo dirigido, repetición espaciada SM-2, olvido por tema, simulacros con nota, resúmenes, plan de hoy, progreso y recordatorios."

        cloud = softwareSystem "Proveedor de IA en la nube" "Modelo de lenguaje configurable (DeepSeek u otro compatible con OpenAI, o Anthropic). Genera y verifica ítems, refuerzo y resúmenes. No interviene en la evaluación ni en el seguimiento." {
            tags "External"
        }

        whisper = softwareSystem "Whisper (local)" "Transcribe el audio de la clase a texto con segmentos y marcas de tiempo, dentro del propio servidor." {
            tags "External"
        }

        correo = softwareSystem "Servidor de correo (SMTP)" "Entrega los recordatorios de estudio." {
            tags "External"
        }

        estudiante -> sima    "Sube clases, practica, repasa, genera refuerzo y resúmenes, revisa progreso"
        admin      -> sima    "Administra usuarios, planes, trabajos y contenido"
        sima       -> cloud   "Envía contenido de la clase o del perfil; recibe ítems .mini, explicaciones y resúmenes"
        sima       -> whisper "Envía el archivo de audio; recibe transcripción con segmentos"
        sima       -> correo  "Envía recordatorios diarios a quienes los activaron"
    }

    views {
        systemContext sima "Contexto" {
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
            element "Software System" {
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
