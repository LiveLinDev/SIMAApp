# Diagramas UML y de datos de SIMA

Diagramas que pide la UPC además de la arquitectura lógica y física (ver `docs/archimate/`):

| Archivo | Qué es | Cómo se regenera |
|---|---|---|
| `despliegue.png` | Diagrama de despliegue UML: nodos «device» / «executionEnvironment», artefactos y rutas de comunicación con puerto y protocolo | `python docs/uml/draw_deployment.py` |
| `modelo_datos.png` | Modelo de datos (entidad-relación, pata de gallo) leído de los modelos Django reales: PK, FK y columnas clave de las 22 tablas de `learning` más `auth_user` | `python manage.py shell -c "exec(open('docs/uml/draw_er.py', encoding='utf-8').read())"` |

Ambos se dibujan con matplotlib con posiciones controladas (los motores automáticos, PlantUML/smetana, producían
cruces y etiquetas amontonadas). El ER omite las FK repetidas a `user` y `course` de las tablas de actividad
(se indica en la nota del diagrama) y enruta las líneas por los pasillos entre filas y columnas; con `ER_DEBUG=1`
el script imprime cualquier segmento que cruce una tabla.

Uso en la exposición: `TP2/OE2_SUSTENTACION_Palma_Palomino_v6.pptx`, diapositivas 19 (arquitectura lógica),
23 (arquitectura física), 24 (despliegue) y 25 (base de datos).
