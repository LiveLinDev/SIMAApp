from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0023_course_exam_date"),
    ]

    operations = [
        migrations.AddField(
            model_name="course",
            name="vocabulary",
            field=models.TextField(
                blank=True,
                help_text="Terminos tecnicos del curso separados por comas. Mejoran la transcripcion y se amplian solos al corregir clases.",
            ),
        ),
    ]
