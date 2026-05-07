from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("learning", "0003_add_gamification_and_sharing"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuizAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_count", models.PositiveIntegerField(default=10)),
                ("theta", models.FloatField(default=0.0)),
                ("standard_error", models.FloatField(default=9.99)),
                ("current_item_id", models.CharField(blank=True, max_length=20)),
                ("selected_item_ids", models.JSONField(blank=True, default=list)),
                ("correct_count", models.PositiveIntegerField(default=0)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("lesson", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="quiz_attempts", to="learning.lessonjob")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="QuizResponse",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("item_id", models.CharField(max_length=20)),
                ("item_bloom", models.CharField(max_length=4)),
                ("item_topic", models.CharField(max_length=160)),
                ("item_area", models.CharField(blank=True, max_length=160)),
                ("item_demand", models.CharField(blank=True, max_length=20)),
                ("theta_before", models.FloatField(default=0.0)),
                ("theta_after", models.FloatField(default=0.0)),
                ("selected_index", models.IntegerField()),
                ("correct_index", models.IntegerField()),
                ("is_correct", models.BooleanField(default=False)),
                ("answered_at", models.DateTimeField(auto_now_add=True)),
                ("attempt", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="responses", to="learning.quizattempt")),
            ],
            options={"ordering": ["answered_at"]},
        ),
    ]
