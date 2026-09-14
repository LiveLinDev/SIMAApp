"""Correcciones tras la prueba con estudiantes: vocabulario tecnico, resumen completo, conceptos clave y PDF."""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from learning import pipeline, summaries, vocabulary
from learning.models import ClassSession, Course, LessonJob, Plan, Profile, Summary
from learning.tests_adaptive import MINI


class VocabularyCorrectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("med", password="x")
        self.course = Course.objects.create(user=self.user, name="Fisiología", vocabulary="hemoglobina, taquicardia",
                                            main_topics=["Sistema cardiovascular"])

    def test_whisper_prompt_includes_course_terms(self):
        job = LessonJob(user=self.user, course=self.course, title="Clase 3")
        prompt = vocabulary.whisper_prompt(job)
        self.assertIn("Fisiología", prompt)
        self.assertIn("hemoglobina", prompt)
        self.assertIn("Sistema cardiovascular", prompt)

    def test_parser_accepts_common_model_formats(self):
        raw = "1|hemoglovina|hemoglobina\nx|taqui cardia|taquicardia|t\n- anamnecis -> anamnesis\n3. auscultasion|auscultación\nok"
        self.assertEqual(vocabulary.parse_corrections(raw), [
            ("hemoglovina", "hemoglobina"), ("taqui cardia", "taquicardia"),
            ("anamnecis", "anamnesis"), ("auscultasion", "auscultación"),
        ])

    def test_only_similar_corrections_that_appear_are_accepted(self):
        text = "La hemoglovina transporta oxigeno. Con taqui cardia el pulso sube. El paciente esta estable."
        pairs = vocabulary.merge_pairs([
            ("hemoglovina", "hemoglobina"),     # error de transcripcion: se acepta
            ("taqui cardia", "taquicardia"),    # palabra partida: se acepta
            ("estable", "grave"),               # cambia el sentido: se rechaza
            ("fibrilacion", "fibrilación"),     # no aparece en el texto: se rechaza
        ], text)
        self.assertEqual(pairs, [("hemoglovina", "hemoglobina"), ("taqui cardia", "taquicardia")])

    def test_corrections_that_delete_words_are_rejected(self):
        self.assertFalse(vocabulary.valid_pair("gastecrónicos", "crónicos", "los gastecrónicos"))
        self.assertTrue(vocabulary.valid_pair("cakexia", "caquexia", "la cakexia avanza"))

    def test_corrections_stay_in_the_part_where_they_were_proposed(self):
        first = "Los siervos enferman por priones. " * 70
        second = "Los siervos de la gleba trabajaban la tierra. " * 60
        answers = iter(["x|siervos|ciervos|t", "ok"])
        with override_settings(TRANSCRIPT_VOCABULARY_CHUNK_WORDS=400), \
                patch("learning.services.call_ai", side_effect=lambda *a, **k: next(answers)):
            result = vocabulary.correct_transcript_vocabulary(first + second, course=self.course, title="Clase")
        corrected_first, corrected_second = result["text"][:len(first)], result["text"][len(first):]
        self.assertNotIn("siervos", corrected_first)
        self.assertIn("siervos de la gleba", corrected_second)
        self.assertEqual(result["text"].replace("ciervos", "siervos"), first + second)

    def test_corrections_apply_to_every_occurrence_keeping_capitals(self):
        text = "Hemoglovina baja. La hemoglovina se mide en sangre; hemoglovinas no cambia."
        fixed, applied = vocabulary.apply_corrections(text, [("hemoglovina", "hemoglobina")])
        self.assertEqual(fixed, "Hemoglobina baja. La hemoglobina se mide en sangre; hemoglovinas no cambia.")
        self.assertEqual(applied, [{"before": "hemoglovina", "after": "hemoglobina", "count": 2}])

    @override_settings(TRANSCRIPT_VOCABULARY_CHUNK_WORDS=500)
    def test_long_transcript_is_reviewed_by_parts_and_terms_are_learned(self):
        part_one = "El esterno cleido mastoideo gira la cabeza. " * 60
        part_two = "La anamnecis orienta el diagnostico. " * 60
        transcript = part_one + "\n\n" + part_two
        def fake_ai(prompt, **kwargs):
            chunk = prompt.split("TRANSCRIPCION")[-1]  # como el modelo real, responde segun la parte que recibe
            lines = []
            if "esterno cleido" in chunk:
                lines.append("x|esterno cleido mastoideo|esternocleidomastoideo|t")
            if "anamnecis" in chunk:
                lines += ["x|anamnecis|anamnesis|t", "x|diagnostico|grave|g",
                          "x|orienta el diagnostico|orientan el diagnostico|g"]
            return "\n".join(lines) or "ok"

        with patch("learning.services.call_ai", side_effect=fake_ai) as call_ai:
            result = vocabulary.correct_transcript_vocabulary(transcript, course=self.course, title="Clase 4")
        self.assertEqual(call_ai.call_count, 2)
        self.assertIn("hemoglobina", call_ai.call_args_list[0][0][0])  # el vocabulario del curso va en el prompt
        self.assertNotIn("anamnecis", result["text"])
        self.assertIn("esternocleidomastoideo", result["text"])
        self.assertIn("diagnostico", result["text"])  # la propuesta que no se parece se descarto
        self.assertTrue(result["text"].startswith("El esternocleidomastoideo gira la cabeza."))
        # "orientan" es una correccion general: se aplica, pero no entra al vocabulario del curso
        self.assertIn("orientan el diagnostico", result["text"])
        added = vocabulary.learn_terms(self.course, result["learned_terms"])
        self.assertEqual(sorted(added), ["anamnesis", "esternocleidomastoideo"])
        self.course.refresh_from_db()
        self.assertIn("anamnesis", self.course.vocabulary)

    def test_pipeline_stage_updates_transcript_segments_and_log(self):
        job = LessonJob.objects.create(user=self.user, course=self.course, title="Clase 5", mode=LessonJob.Mode.API,
                                       status=LessonJob.Status.PROCESSING, transcript="La hemoglovina baja en la anemia.")
        segments = [{"start": 0.0, "end": 3.0, "text": "La hemoglovina baja en la anemia."}]
        with patch("learning.services.call_ai", return_value="x|hemoglovina|hemoglobina"):
            fixed_segments = pipeline._review_transcript_vocabulary(job, "cloud", segments)
        job.refresh_from_db()
        self.assertEqual(job.transcript, "La hemoglobina baja en la anemia.")
        self.assertEqual(fixed_segments[0]["text"], "La hemoglobina baja en la anemia.")
        self.assertIn("Términos técnicos revisados", job.processing_log)
        self.assertEqual(job.transcript_repair_trace[-1]["downstream_action"], "vocabulario del curso")

    def test_course_form_saves_vocabulary(self):
        self.client.force_login(self.user)
        resp = self.client.post(f"/cursos/{self.course.pk}/editar/", {
            "name": "Fisiología", "academic_period": "", "level": "introductory",
            "vocabulary": "hemoglobina, taquicardia, anamnesis", "main_topics_text": "",
        })
        self.assertEqual(resp.status_code, 302)
        self.course.refresh_from_db()
        self.assertEqual(self.course.vocabulary, "hemoglobina, taquicardia, anamnesis")


class FullClassSummaryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("lu2", password="x")
        Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.FREE, "credit_balance": 50})
        self.course = Course.objects.create(user=self.user, name="Anatomía")

    def test_long_class_is_summarized_from_notes_of_every_part(self):
        start = "Inicio: el corazon tiene cuatro camaras. " * 300
        end = "Final: la valvula mitral separa auricula y ventriculo izquierdo. " * 300
        job = LessonJob.objects.create(user=self.user, course=self.course, title="Corazón", mode=LessonJob.Mode.API,
                                       status=LessonJob.Status.CORRECTED, corrected_output=MINI, transcript=start + "\n\n" + end)
        prompts = []

        def fake_ai(prompt, **kwargs):
            prompts.append(prompt)
            if "PARTE " in prompt and "NOTAS POR PARTE" not in prompt:
                return "n|nota de " + ("final valvula mitral" if "Final:" in prompt.split("TRANSCRIPCION:")[-1] else "inicio camaras") + "\nc|Válvula mitral"
            return "t|Corazón\nc|Válvula mitral\nc|¿Qué es el corazón?\np|Cuatro cámaras.\np|La válvula mitral."

        with patch("learning.services.call_ai", side_effect=fake_ai):
            parsed = summaries.build_class_summary(job, "cloud")
        part_prompts = [p for p in prompts if "NOTAS POR PARTE" not in p]
        self.assertGreater(len(part_prompts), 1)
        final = prompts[-1]
        self.assertIn("NOTAS POR PARTE", final)
        self.assertIn("nota de inicio camaras", final)
        self.assertIn("nota de final valvula mitral", final)  # la ultima parte de la clase llega al resumen
        self.assertEqual(parsed["key_concepts"], ["Válvula mitral"])  # las preguntas no cuentan como concepto

    def test_short_class_uses_a_single_call(self):
        job = LessonJob.objects.create(user=self.user, course=self.course, title="Corta", mode=LessonJob.Mode.API,
                                       status=LessonJob.Status.CORRECTED, corrected_output=MINI, transcript="El corazon bombea sangre. " * 40)
        with patch("learning.services.call_ai", return_value="t|Corta\nc|Corazón\np|Bombea sangre.") as call_ai:
            summaries.build_class_summary(job, "cloud")
        self.assertEqual(call_ai.call_count, 1)


class SummaryProgressTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("prog", password="x")
        Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.FREE, "credit_balance": 50})
        self.course = Course.objects.create(user=self.user, name="Anatomía")
        self.job = LessonJob.objects.create(user=self.user, course=self.course, title="Corazón", mode=LessonJob.Mode.API,
                                            status=LessonJob.Status.CORRECTED, corrected_output=MINI, transcript="El corazon bombea. " * 40)
        self.client.force_login(self.user)

    def test_pending_summary_page_shows_only_progress(self):
        from learning.models import SummaryJob

        with patch("learning.job_queue.enqueue_summary_job"):
            summary_job = summaries.create_summary_job(self.user, self.course, lesson=self.job)
        page = self.client.get(f"/clase/{self.job.pk}/resumen/")
        self.assertContains(page, "En cola")
        self.assertContains(page, "Empieza en unos segundos.")
        for text in ("Aún no hay resumen", "Todavía no se puede resumir", "Generar resumen ("):
            self.assertNotContains(page, text)

        summary_job.status = SummaryJob.Status.PROCESSING
        summary_job.processing_log = summaries._job_log(summary_job.processing_log, "Procesando", "Leyendo la parte 2 de 4.")
        summary_job.save()
        progress = summaries.summary_job_progress(summary_job)
        self.assertEqual(progress["title"], "Preparando tu resumen")
        self.assertEqual(progress["step"], "Leyendo la parte 2 de 4.")
        self.assertContains(self.client.get(f"/clase/{self.job.pk}/resumen/"), "Leyendo la parte 2 de 4.")

    def test_class_without_content_explains_why(self):
        empty = LessonJob.objects.create(user=self.user, course=self.course, title="Vacía", mode=LessonJob.Mode.API,
                                         status=LessonJob.Status.PROCESSING)
        page = self.client.get(f"/clase/{empty.pk}/resumen/")
        self.assertContains(page, "Todavía no se puede resumir")
        self.assertNotContains(page, "Aún no hay resumen")


class ConceptsAndPdfTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("pdf", password="x")
        Profile.objects.update_or_create(user=self.user, defaults={"plan": Plan.UNLIMITED})
        self.course = Course.objects.create(user=self.user, name="Biología", main_topics=["Tema de otra clase"])
        self.job = LessonJob.objects.create(user=self.user, course=self.course, title="Célula", mode=LessonJob.Mode.API,
                                            status=LessonJob.Status.CORRECTED, corrected_output=MINI, transcript="texto " * 50)
        self.client.force_login(self.user)

    def _summary(self):
        session = pipeline._sync_class_session_status(self.job)
        return Summary.objects.create(course=self.course, class_session=session, kind=Summary.Kind.STRUCTURED,
                                      title="Célula", content="La célula es la unidad de la vida.\n\nQue repasar primero:\n- Organelos",
                                      key_concepts=["Mitocondria", "Membrana plasmática"])

    def test_concepts_come_from_the_class_summary(self):
        self._summary()
        page = self.client.get(f"/clase/{self.job.pk}/mapa/")
        self.assertContains(page, "Membrana plasmática")
        detail = self.client.get(f"/clase/{self.job.pk}/")
        self.assertContains(detail, "Conceptos clave")
        self.assertContains(detail, "Mitocondria")
        self.assertNotContains(detail, "Tema de otra clase")

    def test_questions_pdf(self):
        resp = self.client.get(f"/clase/{self.job.pk}/preguntas.pdf")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))
        self.assertIn("preguntas-celula.pdf", resp["Content-Disposition"])
        self.assertContains(self.client.get(f"/clase/{self.job.pk}/"), f"/clase/{self.job.pk}/preguntas.pdf")

    def test_summary_pdfs(self):
        self.assertEqual(self.client.get(f"/clase/{self.job.pk}/resumen.pdf").status_code, 404)
        self._summary()
        resp = self.client.get(f"/clase/{self.job.pk}/resumen.pdf")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content.startswith(b"%PDF"))
        Summary.objects.create(course=self.course, kind=Summary.Kind.COURSE_ACCUMULATED, title="Biología", content="Todo el curso.")
        resp = self.client.get(f"/cursos/{self.course.pk}/resumen.pdf")
        self.assertEqual(resp.status_code, 200)

    def test_other_users_cannot_download(self):
        other = User.objects.create_user("otro", password="x")
        self.client.force_login(other)
        self.assertEqual(self.client.get(f"/clase/{self.job.pk}/preguntas.pdf").status_code, 404)
