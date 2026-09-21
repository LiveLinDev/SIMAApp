"""Lectura de las respuestas de generación con mini-format frente al lector anterior."""
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from learning.parse_mini import apply_corrections_with_trace, merge_mini_chunks, parse_mini
from learning.services import generation, lectura_mini

CAB = "a|m=IRT3PL|d=20260921|n=4|l=es|t=respiracion|bd=2,2,0,0,0,0|cat=0,-3,3,0.3,4,SH"


def item(n, enunciado, opciones="mitocondria*,cloroplasto,nucleo,vacuola"):
    return f"i{n}|L1|Respiracion celular|{enunciado}|{opciones}|1.0,-0.3,0.25|2|biologia,0.2,low"


BIEN = [item(1, "En que organelo ocurre la respiracion celular?"),
        item(2, "Que gas se consume en la respiracion aerobica?", "oxigeno*,helio,neon,argon"),
        item(3, "Que molecula almacena la energia liberada?", "ATP*,ADN,ARN,glucogeno"),
        item(4, "Que etapa ocurre en el citoplasma?", "glucolisis*,ciclo de Krebs,cadena respiratoria,fermentacion")]

# prosa alrededor, un ítem sin respuesta marcada y la respuesta cortada por el límite de tokens
RESPUESTA = "\n".join([
    "Aqui tienes los items solicitados:",
    CAB,
    BIEN[0],
    item(2, "Que gas se consume en la respiracion aerobica?", "oxigeno,helio,neon,argon"),
    BIEN[2],
    "i4|L1|Respiracion celular|Que etapa ocurre en el cito",
])


class LecturaMiniTests(SimpleTestCase):
    def test_contrato_a_lee_el_formato_de_sima(self):
        texto, ev = lectura_mini.leer_bloque("\n".join([CAB, *BIEN]), 4, "1 de 1",
                                             llamar=lambda p: self.fail("no debia reparar"),
                                             pedir_faltantes=lambda n, e: self.fail("no debia pedir"))
        self.assertEqual((ev.recibidos, ev.finales, ev.llamadas), (4, 4, 1))
        self.assertEqual(len(parse_mini(texto).items), 4)

    def test_repara_solo_las_lineas_invalidas_y_pide_solo_lo_que_falta(self):
        pedidos = []

        def llamar(prompt):
            pedidos.append(prompt)
            return BIEN[1]

        def faltantes(n, enunciados):
            self.assertEqual(n, 1)
            self.assertEqual(len(enunciados), 3)
            return "\n".join([CAB, BIEN[3].replace("i4|", "i1|")])

        texto, ev = lectura_mini.leer_bloque(RESPUESTA, 4, "1 de 1", llamar, faltantes)
        self.assertEqual(ev.recibidos, 2)
        self.assertTrue(ev.truncado)
        self.assertIn("E08", {codigo for _, codigo, _ in ev.lineas_invalidas})
        self.assertEqual(len(ev.reparados), 1)
        self.assertEqual((ev.faltantes_pedidos, ev.recuperados, ev.finales, ev.llamadas), (1, 1, 4, 3))
        # la reparación solo lleva la línea mala, no el bloque entero
        self.assertNotIn("ATP", pedidos[0])
        items = parse_mini(texto).items
        self.assertEqual(len(items), 4)
        gas = next(i for i in items if "gas" in i.statement)
        self.assertIn("oxigeno*", gas.raw)

    def test_correccion_invalida_no_se_acepta(self):
        texto, ev = lectura_mini.leer_bloque(
            RESPUESTA, 3, "1 de 1",
            llamar=lambda p: item(2, "Que gas se consume?", "oxigeno,helio,neon,argon"),
            pedir_faltantes=lambda n, e: "")
        # la corrección sigue sin respuesta marcada: no entra; la línea cortada no se repara, se pide como faltante
        self.assertEqual(ev.reparados, [])
        self.assertEqual(len(ev.rechazados), 1)
        self.assertEqual(ev.faltantes_pedidos, 1)
        self.assertEqual(ev.finales, 2)
        self.assertNotIn("helio", texto)

    def test_el_lector_anterior_marca_la_primera_opcion_y_acepta_el_item_cortado(self):
        ev = lectura_mini.diagnostico_legado(RESPUESTA, 4, "1 de 1")
        self.assertEqual(ev.legado_sin_correcta, 1)
        self.assertEqual(ev.recibidos, 2)
        self.assertTrue(ev.truncado)

    def test_respuesta_con_razonamiento_y_sin_cabecera(self):
        # forma observada con deepseek-v4-flash: plan en prosa, sin cabecera, "i1: L1|..." y corte final
        texto = "\n\n".join([
            "Let me analyze the content and generate 3 items in MINI format.",
            "1. L1 - Organelo -> cloroplasto",
            "Let me finalize:",
            BIEN[0].replace("i1|", "i1: "),
            BIEN[1].replace("i2|", "i2: "),
            "i3: L1|Respiracion celular|Que molecula almacena la",
        ])
        ev = lectura_mini.diagnostico_legado(texto, 3, "1")
        self.assertEqual((ev.legado_aceptados, ev.legado_descartados), (0, 3))
        _, ev = lectura_mini.leer_bloque(texto, 3, "1", llamar=lambda p: self.fail("no debia reparar"),
                                         pedir_faltantes=lambda n, e: BIEN[2])
        self.assertTrue(ev.sin_cabecera)
        self.assertEqual((ev.normalizados, ev.prosa_descartada), (3, 3))
        self.assertTrue(ev.truncado)
        self.assertEqual((ev.recibidos, ev.recuperados, ev.finales, ev.llamadas), (2, 1, 3, 2))

    def test_borrador_y_version_final_vale_la_ultima(self):
        borrador = item(1, "Donde ocurre la respiracion?", "mitocondria,cloroplasto,nucleo,vacuola")
        texto = "\n".join([CAB, borrador, BIEN[1], "Version final:", BIEN[0], BIEN[1]])
        _, ev = lectura_mini.leer_bloque(texto, 2, "1", llamar=lambda p: self.fail("no debia reparar"),
                                         pedir_faltantes=lambda n, e: self.fail("no debia pedir"))
        self.assertEqual((ev.borradores, ev.recibidos, ev.finales, ev.llamadas), (2, 2, 2, 1))
        self.assertEqual(ev.legado_aceptados, 4)

    def test_salida_se_une_con_merge_mini_chunks(self):
        a, _ = lectura_mini.leer_bloque("\n".join([CAB, *BIEN[:2]]), 2, "1", None, None)
        b, _ = lectura_mini.leer_bloque("\n".join([CAB, *BIEN[2:]]), 2, "2", None, None)
        self.assertEqual(len(parse_mini(merge_mini_chunks([a, b])).items), 4)


@override_settings(LOCAL_ITEMS_REQUESTED=4)
class GeneracionConLectorTests(SimpleTestCase):
    def _generar(self, respuestas):
        informe = []
        with patch.object(generation, "call_ai", side_effect=respuestas), \
                patch.object(generation, "resolve_backend", return_value="cloud"), \
                patch.object(generation, "generation_chunk_plan", return_value=(["texto"], [4], 4)):
            _, mini, _ = generation.generate_items("texto", backend="cloud", items_requested=4, informe=informe)
        return mini, informe

    def test_minifmt_por_defecto(self):
        with patch.dict("os.environ", {"SIMA_LECTOR": "minifmt"}):
            mini, informe = self._generar([RESPUESTA, BIEN[1], "\n".join([CAB, BIEN[3]])])
        self.assertEqual(len(parse_mini(mini).items), 4)
        self.assertEqual(informe[0]["lector"], "minifmt")
        self.assertEqual(lectura_mini.resumen(informe)["llamadas"], 3)

    def test_legado_conserva_el_comportamiento_anterior(self):
        with patch.dict("os.environ", {"SIMA_LECTOR": "legado"}):
            mini, informe = self._generar([RESPUESTA])
        self.assertEqual(informe[0]["lector"], "legado")
        self.assertEqual(informe[0]["legado_sin_correcta"], 1)
        self.assertEqual(mini, RESPUESTA)


class CorreccionesTests(SimpleTestCase):
    """Correcciones del verificador observadas con deepseek-chat (clase de fotosíntesis, 21-sep-2026)."""
    MINI = "\n".join(["a|m=IRT3PL|n=2|l=es", item(1, "Las plantas CAM abren sus estomas durante la ____", "noche*,mañana,tarde,mediodía"),
                      BIEN[1]])
    REPORTE = "\n".join([
        "v|n=2|e=2|s=CORREGIDO",
        "e1|i1|ambiguous_statement|enunciado|Las plantas CAM abren sus estomas durante la ____|"
        "Las plantas CAM abren sus estomas durante la noche|evitar formato cloze",
        "e2|i2|wrong_statement|opciones|oxigeno*,helio,neon,argon|Oxigeno*,Helio,Neon,Argon|mayuscula inicial",
    ])

    def _corregir(self, lector):
        with patch.dict("os.environ", {"SIMA_LECTOR": lector}):
            return apply_corrections_with_trace(self.MINI, self.REPORTE)

    def test_correccion_de_opciones_no_se_escribe_en_el_enunciado(self):
        for lector in ("legado", "minifmt"):
            salida, _ = self._corregir(lector)
            gas = parse_mini(salida).items[1]
            self.assertEqual(gas.statement, "Que gas se consume en la respiracion aerobica?")
            self.assertEqual(gas.options[0]["text"], "Oxigeno")

    def test_minifmt_rechaza_la_correccion_que_rompe_el_item(self):
        salida, traza = self._corregir("minifmt")
        self.assertTrue(traza[0]["rejected"])
        self.assertIn("____", parse_mini(salida).items[0].statement)
        salida, traza = self._corregir("legado")
        self.assertNotIn("____", parse_mini(salida).items[0].statement)
