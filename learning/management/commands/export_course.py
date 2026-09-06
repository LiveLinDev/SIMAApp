from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from learning.models import Course
from learning.portability import dumps, export_course


class Command(BaseCommand):
    help = "Exporta un curso (clases con transcripcion y .mini, resumenes, flashcards) a JSON."

    def add_arguments(self, parser):
        parser.add_argument("course_id", type=int)
        parser.add_argument("--out", help="Ruta del JSON (por defecto curso_<id>.json en el directorio actual).")

    def handle(self, *args, **options):
        try:
            course = Course.objects.get(pk=options["course_id"])
        except Course.DoesNotExist as exc:
            raise CommandError(f"No existe el curso {options['course_id']}.") from exc
        payload = export_course(course)
        out = Path(options["out"] or f"curso_{course.pk}.json")
        out.write_text(dumps(payload), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(
            f"Exportado «{course.name}»: {len(payload['lessons'])} clases, {len(payload['summaries'])} resumenes, "
            f"{len(payload['flashcards'])} flashcards -> {out}"
        ))
