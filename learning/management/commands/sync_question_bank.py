from django.core.management.base import BaseCommand

from learning.adaptive import sync_question_bank
from learning.models import LessonJob


class Command(BaseCommand):
    help = "Lleva al banco del curso (Question/AnswerOption) los items de todas las clases listas."

    def add_arguments(self, parser):
        parser.add_argument("--course", type=int, help="Solo las clases de este curso (id).")

    def handle(self, *args, **options):
        jobs = LessonJob.objects.filter(course__isnull=False).exclude(corrected_output="", toon_output="")
        if options.get("course"):
            jobs = jobs.filter(course_id=options["course"])
        synced = skipped = 0
        for job in jobs.order_by("id"):
            quiz = sync_question_bank(job)
            if quiz is None:
                skipped += 1
                continue
            synced += 1
            self.stdout.write(f"  #{job.pk:<4} {job.title[:48]:<50} -> {quiz.questions.count()} preguntas")
        self.stdout.write(self.style.SUCCESS(f"{synced} clase(s) sincronizadas, {skipped} omitidas."))
