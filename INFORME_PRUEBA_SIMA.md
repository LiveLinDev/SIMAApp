# Informe de prueba - SIMAApp arranque y generacion de preguntas

## 1. Script de arranque actualizado

Archivo modificado: `f:/SIMA/SIMAApp/INICIAR_SIMA.bat`

Antes apuntaba a `F:\Agente\iniciar-todo-sima.bat` (ruta obsoleta por el movimiento de carpetas).
Ahora apunta a `f:\SIMA\SIMAApp\start-everything.bat`, que levanta:
- PostgreSQL (puerto 5433)
- Modelo local de IA via Ollama (puerto 8001)
- Proxy IA (puerto 8003)
- Django (puerto 8002)
- Proxy publico (puerto 25564)

El script mantiene la ventana abierta con `pause` para poder ver errores.

## 2. Configuracion del modelo local

Se creo `f:/SIMA/SIMAApp/start-model.bat` para iniciar Ollama en `127.0.0.1:8001`.
Se descargo `qwen2.5:7b` (~4.7 GB) como modelo local.

Variables ajustadas en `.env`:
- `LOCAL_MODEL=qwen2.5:7b`
- `LOCAL_CHUNK_WORDS=1000` (chunks mas pequenos para Ollama)
- `LOCAL_ITEMS_PER_CHUNK_MAX=10`
- `LOCAL_COHERENCE_MAX_ITEMS=1` (evita reparacion monolitica que fallaba con este modelo)

## 3. Correcciones de robustez aplicadas

- `learning/services.py`: se eliminan caracteres NUL (`\x00`) del output del modelo local antes de guardarlo, evitando errores de PostgreSQL.
- `learning/job_queue.py`: se eliminan caracteres NUL de `verification_trace` y `correction_trace` antes de guardar el job.

## 4. Ejecucion del arranque

Se ejecuto `INICIAR_SIMA.bat`. Todos los servicios levantaron correctamente:
- Modelo local (Ollama): http://127.0.0.1:8001/v1/models -> 200
- Proxy IA: http://127.0.0.1:8003/_proxy/health -> 200
- Django: http://127.0.0.1:8002/ -> 200
- Proxy publico: http://127.0.0.1:25564/ -> 200

## 5. Clase subida

- Usuario de prueba: `test_agente_sima`
- Curso: `Biologia General - Fotosintesis`
- Texto: `clase_fotosintesis_3000.txt` (~2856 palabras)
- Job automatico: http://127.0.0.1:8002/clase/65/
- Job manual coherente: http://127.0.0.1:8002/clase/66/

## 6. Resultado de la generacion automatica

El pipeline automatico genero **28 items** en formato MINI y los parseo a JSON.
Archivo: `job65_automatico.json`

## 7. Revision de coherencia - ERRORES ENCONTRADOS

Se detectaron items con respuesta correcta erronea o distractores inconsistentes:

| Item | Pregunta | Problema |
|------|----------|----------|
| i3 | "Cual de las siguientes reacciones NO es parte de la fotosintesis?" | Marca como correcta "reduccion de dioxido de carbono", pero esa SI es parte del ciclo de Calvin. |
| i5 | "Que papel desempena la clorofila?" | Marca "transporta oxigeno" como correcta; la clorofila captura luz. |
| i9 | "Durante la fosforilacion fotosintetica, que molecula se reduce para formar NADPH?" | Marca "ATP"; la correcta es NADP+. |
| i10 | "Que papel juega el oxigeno en la fotosintesis?" | Marca "Donador de electrones"; el oxigeno es producto. |
| i13 | "Donde se libera el dioxido de carbono en la fotosintesis CAM?" | Respuesta confusa/incorrecta. |
| i15 | "Que etapa del ciclo de Calvin produce gliceraldehido 3-fosfato?" | Marca "Fijacion del CO2"; el G3P se forma en la reduccion. |

Conclusion: el formato MINI y el parseo a JSON funcionan correctamente, pero el modelo local qwen2.5:7b comete errores conceptuales que deben revisarse manualmente antes de usar los items en evaluaciones.

## 8. MINI manual coherente

Como referencia, se subio un job con 12 preguntas manuales coherentes sobre fotosintesis.
Archivo: `mini_fotosintesis_manual.json`
Ejemplo:
- "Que elementos principales necesitan las plantas para realizar la fotosintesis?" -> luz solar, agua y dioxido de carbono
- "Cual de las siguientes sustancias es un producto directo de la fotosintesis?" -> glucosa
- "En que parte de la planta ocurre principalmente la fotosintesis?" -> en las hojas

## 9. Recomendaciones

- Para produccion, usar un modelo mas capaz (Claude/Anthropic) o un modelo local mayor (14B+) y revisar siempre las preguntas.
- Mantener los ajustes de `.env` mientras se use Ollama como backend local.
- Considerar activar la verificacion con EduQG si se dispone de material de referencia validado.
