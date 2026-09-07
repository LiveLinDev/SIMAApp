# Modelo ArchiMate de SIMA

`SIMA.archimate` es el modelo de arquitectura empresarial de SIMA en el formato nativo de
[Archi](https://www.archimatetool.com/) (ArchiMate 3.2). Lo genera `build_model.py`, que es la fuente
de verdad: si cambia la arquitectura, se edita el script y se vuelve a generar. Con `--merge` el script
conserva lo que se editó en Archi (vistas "b" con ruteo MCP, bendpoints, colores) y solo agrega o actualiza
los elementos, relaciones y vistas que define; `bash docs/archimate/render_views.sh` hace merge, valida con la
línea de comandos de Archi y deja un PNG por vista en `docs/img/archimate/`.

## Contenido

| Capa | Elementos |
|---|---|
| Motivación | interesados (estudiante, docente), metas, requisitos (notación .mini, verificación, evaluación adaptativa) y el principio de transcripción local |
| Negocio | actores y rol, los seis procesos del ciclo del estudiante, el servicio de acompañamiento y los objetos de negocio |
| Aplicación | SIMA y sus componentes (vistas, núcleo adaptativo, pipeline, servicios de IA, cola y worker, refuerzo y resúmenes, créditos), cinco servicios de aplicación, interfaces, objetos de datos y los sistemas externos (proveedor de LLM, Whisper) |
| Tecnología | servidor, software de sistema, worker, dispositivo del estudiante, red, servicios tecnológicos y artefactos |

Siete vistas con disposición calculada: motivación, negocio, aplicación, tecnología, una vista en capas y los dos
diagramas que pide la UPC (arquitectura lógica y arquitectura física), más las copias "b" con ruteo hecho en Archi.

## Abrir y exportar

1. Archi 5.10 (portable, con su propio JRE) está en `D:\tools\Archi\Archi.exe` en el equipo de Erick (instalado el 7-sep-2026 desde el
   release oficial de archimatetool.com; se puso en D: porque C: estaba sin espacio). En otro equipo: descargar el portable y descomprimir.
2. Archi → **File → Open** → `docs/archimate/SIMA.archimate`.
3. Para las imágenes de las vistas: **File → Report → HTML** (genera un sitio con cada vista en PNG) o, en cada vista,
   **File → Export → View As Image**.

Desde la línea de comandos (sin abrir la interfaz):

```bash
cd D:\tools\Archi
jre\bin\java -cp plugins\org.eclipse.equinox.launcher_1.7.100.v20251111-0406.jar org.eclipse.equinox.launcher.Main -application com.archimatetool.commandline.app -consoleLog -nosplash -data D:\tools\archi-data --loadModel D:\Tesis\SIMAApp\docs\archimate\SIMA.archimate --html.createReport D:\Tesis\SIMAApp\docs\archimate\report
```

El reporte deja un PNG por vista en `report/<id>/images/`; copias con nombre legible en `docs/img/archimate/`.
Validado el 7-sep-2026: el modelo carga sin errores y las cinco vistas se renderizan.

## Arquitectura lógica y física (convención UPC, vistas 6 y 7)

Lo que espera la carrera de Ingeniería de Software de la UPC, según las tesis del repositorio académico
(asesores Barrientos, Burga, Bautista; p. ej. Baquerizo y Canales 2018: "documentos de arquitectura física y lógica,
además de diagramas de componentes y de despliegue"; Aguilar y Guerrero 2025: "diseño de arquitectura lógica y
física") y el sílabo de Arquitectura de Software (IS256/IS310: "documento de arquitectura con las vistas y diagramas
apropiados"), es el par de vistas del modelo 4+1 de Kruchten adaptado al Taller de Proyecto:

| Diagrama | Qué muestra | Notación habitual | En SIMA |
|---|---|---|---|
| **Arquitectura lógica** | capas de presentación, aplicación (lógica de negocio), dominio e infraestructura; módulos por capa; actores arriba; servicios externos aparte; una flecha entre capas adyacentes | bloques por capa (estilo C4 nivel 3 / UML de componentes) | vista **6**: cada caja es un módulo real de `learning/` (vistas, pipeline, servicios de IA, núcleo adaptativo, SM-2, plan diario, cola, créditos, recordatorios, portabilidad; modelos; ORM, cliente de LLM, parser .mini, Whisper, correo, archivos, configuración) |
| **Arquitectura física** | dispositivos, red, nodos de despliegue, software de sistema y artefactos, con puertos y protocolos en las conexiones; zonas (cliente, red pública, nube, subred privada, externos) | UML de despliegue o diagrama de infraestructura con íconos del proveedor (el OE2 usó Azure) | vista **7**: navegador → DNS/TLS → Nginx :443 → Gunicorn+Django :8000 → PostgreSQL :5432 en subred privada; worker, Whisper local y cron dentro del mismo nodo; LLM y SMTP externos; nota con el entorno de desarrollo |

En la memoria corresponden a "Figura 1. Arquitectura lógica de SIMA" y "Figura 3. Diagrama de despliegue"; en el
documento OE2, a las secciones 3.3 (componentes lógicos) y 3.4 (arquitectura física). Ojo: la Figura 3 del OE2
actual es una plantilla de otro proyecto (empresas, candidatos, Twilio) y debe reemplazarse por la vista 6.

## Edición asistida por IA con el plugin MCP (instalado)

Archi tiene instalado el plugin **ArchiMate MCP Server** v1.8.0 (`fanievh/archi-mcp-server`, licencia MIT) en
`D:\tools\Archi\dropins`. Expone el modelo abierto en Archi por HTTP local (`http://127.0.0.1:18090/mcp`,
solo loopback) con 69 herramientas: consultar, crear, anidar, ruteo ortogonal con evasión de obstáculos,
evaluación objetiva de la disposición (`assess-layout`) y exportación a PNG/SVG.

Uso:

1. Abrir el modelo en Archi y, en la barra de menú, **MCP Server → Start MCP Server**.
2. **Approval Mode** (mismo menú) decide si cada cambio del asistente queda en cola para aprobarlo en la vista
   *Pending Approvals* o se aplica directo. Es un control del humano: el asistente no puede cambiarlo.
3. Claude Code lo encuentra por el `.mcp.json` del repo (`archi` → `http://127.0.0.1:18090/mcp`).
4. El plugin **no guarda el modelo**: tras una sesión hay que guardar en Archi (Ctrl+S).

Flujo aplicado el 7-sep-2026 sobre copias de las vistas (las originales del script se conservan):

| Vista | Original | Con ruteo MCP | Qué se hizo |
|---|---|---|---|
| 2b. Negocio | pobre (14 terminales diagonales) | aceptable | `auto-route-connections` con `autoNudge` |
| 3b. Aplicación | pobre (15 terminales, 10 cruces por cajas) | aceptable | ídem |
| 4b. Tecnología | pobre (hub con 8 asignaciones) | disposición excelente | software y artefactos **anidados** dentro del nodo `Servidor de SIMA` (la contención reemplaza las asignaciones nodo→parte, como recomienda el ArchiMate Cookbook), `auto-connect-view` sin Assignment/Composition, ruteo |
| 5b. Capas | pobre (9 terminales diagonales) | buena | ruteo |

El modo `auto-layout-and-route` (ELK) se probó y se descartó: mejora las métricas pero reordena los grupos y
rompe la convención de capas (negocio arriba, tecnología abajo). Las imágenes con ruteo están en
`docs/img/archimate/mcp/`. Las vistas "b" quedaron guardadas en `SIMA.archimate`; `build_model.py --merge` las respeta.
