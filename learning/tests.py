from django.test import SimpleTestCase

from .parse_mini import apply_corrections_with_trace, check_option_uniformity, filter_nonuniform_items, parse_mini


class MiniSemanticQualityTests(SimpleTestCase):
    def test_rejects_meta_video_importance_question(self):
        mini = (
            "a|m=IRT3PL|d=20260630|n=1|l=es|t=corrupcion peruana|bd=0,0,0,0,1,0|cat=0,-3,3,0.3,1,SH\n"
            "i1|L5|Evaluar|Que importancia tiene el video en la comprension critica de la independencia del Peru?|"
            "importancia menor,importancia moderada*,importancia mayor,importancia nula|1.9,-0.3,0.25|3|Historia,0.2,medium"
        )

        item = parse_mini(mini).items[0]

        self.assertIn("pregunta_meta_sobre_video_o_clase", check_option_uniformity(item))
        filtered, dropped, _bad_mini = filter_nonuniform_items(mini)
        self.assertEqual(len(parse_mini(filtered).items), 0)
        self.assertEqual(len(dropped), 1)

    def test_rejects_statement_starting_with_el_video(self):
        mini = (
            "a|m=IRT3PL|d=20260630|n=1|l=es|t=corrupcion peruana|bd=0,1,0,0,0,0|cat=0,-3,3,0.3,1,SH\n"
            "i1|L2|Reflexion|El video sugiere que la corrupcion podria estar ligada a ____|"
            "la naturaleza humana*,la falta de leyes,la pobreza extrema,la influencia extranjera|1.1,-0.2,0.25|2|Historia,0.2,medium"
        )

        item = parse_mini(mini).items[0]

        self.assertIn("pregunta_meta_sobre_video_o_clase", check_option_uniformity(item))

    def test_rejects_advertising_question(self):
        mini = (
            "a|m=IRT3PL|d=20260630|n=1|l=es|t=corrupcion peruana|bd=1,0,0,0,0,0|cat=0,-3,3,0.3,1,SH\n"
            "i1|L1|Publicidad|Que se ofrece en la libreria solo para fumadores?|"
            "libros de historia*,libros de ciencia,revistas,periodicos|0.9,-1.0,0.25|1|Historia,0.2,low"
        )

        item = parse_mini(mini).items[0]

        self.assertIn("pregunta_sobre_publicidad_o_call_to_action", check_option_uniformity(item))

    def test_wrong_answer_fix_without_star_is_ignored(self):
        mini = (
            "a|m=IRT3PL|d=20260630|n=1|l=es|t=corrupcion peruana|bd=1,0,0,0,0,0|cat=0,-3,3,0.3,1,SH\n"
            "i1|L1|Financiamiento|Que mecanismo se uso para financiar gastos durante la independencia?|"
            "prestamos,expropiaciones*,impuestos,donaciones|0.9,-1.0,0.25|1|Historia,0.2,low"
        )
        report = (
            "v|d=20260630|n=1|e=1|s=CORREGIDO\n"
            "e1|i1|wrong_answer|options|expropiaciones*|prestamos,expropiaciones,impuestos,donaciones|Sin marca correcta"
        )

        corrected, trace = apply_corrections_with_trace(mini, report)
        item = parse_mini(corrected).items[0]

        self.assertEqual([opt["correct"] for opt in item.options], [False, True, False, False])
        self.assertFalse(trace[0]["applied"])

    def test_key_value_report_fields_are_normalized(self):
        mini = (
            "a|m=IRT3PL|d=20260630|n=1|l=es|t=corrupcion peruana|bd=1,0,0,0,0,0|cat=0,-3,3,0.3,1,SH\n"
            "i1|L1|Financiamiento|Que mecanismo se uso para financiar gastos durante la independencia?|"
            "prestamos,expropiaciones*,impuestos,donaciones|0.9,-1.0,0.25|1|Historia,0.2,low"
        )
        report = (
            "v|d=20260630|n=1|e=1|s=CORREGIDO\n"
            "e<wrong_answer>|i1|error_type=wrong_answer|field=options|"
            "original=\"prestamos,expropiaciones*,impuestos,donaciones\"|"
            "fix=\"prestamos,expropiaciones,impuestos*,donaciones\"|justificacion=Prueba"
        )

        corrected, trace = apply_corrections_with_trace(mini, report)
        item = parse_mini(corrected).items[0]

        self.assertTrue(trace[0]["applied"])
        self.assertEqual([opt["correct"] for opt in item.options], [False, False, True, False])
