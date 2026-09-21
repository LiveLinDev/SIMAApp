from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0025_lessonjob_transcription_job_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="lessonjob",
            name="lectura_trace",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
