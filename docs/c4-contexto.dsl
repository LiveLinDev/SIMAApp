workspace "SIMA" "Plataforma de microaprendizaje universitario" {

    model {
        estudiante = person "Estudiante" "Sube grabaciones o apuntes de clase, completa evaluaciones adaptativas diarias, repasa con flashcards de repetición espaciada y monitorea su progreso por materia."
        admin      = person "Administrador" "Gestiona usuarios, planes y contenido desde Django Admin."

        sima = softwareSystem "SIMA" "Convierte grabaciones y apuntes de clases universitarias en ítems de evaluación calibrados (IRT 3PL). Sirve quizzes adaptativos diarios, flashcards con repetición espaciada y seguimiento de progreso gamificado (racha, XP, niveles) para que el estudiante aprenda en base a su propio material de clase."

        claude = softwareSystem "Anthropic Claude API" "Genera y verifica ítems de evaluación en formato MINI (IRT 3PL) a partir del contenido de la clase. No interviene en la lógica de evaluación ni en el seguimiento del estudiante." {
            tags "External"
        }

        whisper = softwareSystem "Whisper (local)" "Transcribe grabaciones de audio de clase a texto plano dentro del propio servidor." {
            tags "External"
        }

        estudiante -> sima   "Sube clases, completa quizzes adaptativos y revisa su progreso"
        admin      -> sima   "Administra usuarios, planes y contenido"
        sima       -> claude "Envía contenido de clase; recibe ítems IRT calibrados en formato MINI"
        sima       -> whisper "Envía archivo de audio; recibe transcripción de texto"
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
