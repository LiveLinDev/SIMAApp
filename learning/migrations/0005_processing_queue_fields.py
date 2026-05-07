from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0004_quiz_attempts"),
    ]

    operations = [
        migrations.AddField(
            model_name="lessonjob",
            name="ai_backend",
            field=models.CharField(default="auto", max_length=20),
        ),
        migrations.AddField(
            model_name="lessonjob",
            name="processing_stage",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="lessonjob",
            name="api_usage_counted",
            field=models.BooleanField(default=False),
        ),
    ]
