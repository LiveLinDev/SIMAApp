from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0024_course_vocabulary"),
    ]

    operations = [
        migrations.AddField(
            model_name="lessonjob",
            name="transcription_job_id",
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
