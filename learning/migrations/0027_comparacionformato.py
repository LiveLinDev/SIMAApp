from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0026_lessonjob_lectura_trace"),
    ]

    operations = [
        migrations.CreateModel(
            name="ComparacionFormato",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("creado", models.DateTimeField(auto_now_add=True)),
                ("estado", models.CharField(default="en_curso", max_length=20)),
                ("items", models.PositiveIntegerField(default=12)),
                ("palabras", models.PositiveIntegerField(default=0)),
                ("fragmento", models.TextField(blank=True)),
                ("modelo", models.CharField(blank=True, max_length=120)),
                ("proveedor", models.CharField(blank=True, max_length=60)),
                ("mini", models.JSONField(blank=True, default=dict)),
                ("json", models.JSONField(blank=True, default=dict)),
            ],
            options={"ordering": ["-creado"]},
        ),
    ]
