from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.db.utils import OperationalError, ProgrammingError

from .models import Course, LessonJob, Plan, PlanCatalog


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)
    invite_code = forms.CharField(
        label="Código de invitación",
        max_length=64,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.conf import settings

        self.requires_invite = getattr(settings, "SIMA_REGISTRATION", "open") == "invite"
        if self.requires_invite:
            self.fields["invite_code"].required = True
        else:
            del self.fields["invite_code"]

    def clean_invite_code(self):
        from django.conf import settings
        from django.utils.crypto import constant_time_compare

        code = (self.cleaned_data.get("invite_code") or "").strip()
        if not constant_time_compare(code, getattr(settings, "SIMA_INVITE_CODE", "")):
            raise forms.ValidationError("El código de invitación no es válido.")
        return code


class PlanForm(forms.Form):
    plan = forms.ChoiceField(choices=Plan.choices, widget=forms.RadioSelect)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            choices = list(
                PlanCatalog.objects.filter(is_active=True)
                .order_by("sort_order", "monthly_price_usd")
                .values_list("code", "name")
            )
        except (OperationalError, ProgrammingError):
            choices = []
        self.fields["plan"].choices = choices or Plan.choices


class CourseForm(forms.ModelForm):
    main_topics_text = forms.CharField(
        label="Temas principales",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "fotosíntesis, célula, genética"}),
        help_text="Sepáralos con comas.",
    )

    class Meta:
        model = Course
        fields = (
            "name",
            "academic_period",
            "description",
            "instructor",
            "level",
            "student_goal",
            "exam_date",
        )
        labels = {
            "name": "Nombre del curso",
            "academic_period": "Ciclo o periodo",
            "description": "Descripción",
            "instructor": "Docente",
            "level": "Nivel",
            "student_goal": "Objetivo de estudio",
            "exam_date": "Próximo examen",
        }
        widgets = {
            "exam_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "name": forms.TextInput(attrs={"placeholder": "Ej: Biología General", "autofocus": True}),
            "academic_period": forms.TextInput(attrs={"placeholder": "Ej: 2026-1"}),
            "description": forms.Textarea(attrs={"rows": 2, "placeholder": "Qué cubre este curso"}),
            "instructor": forms.TextInput(attrs={"placeholder": "Opcional"}),
            "student_goal": forms.Textarea(attrs={"rows": 2, "placeholder": "Ej: aprobar el parcial"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["main_topics_text"].initial = ", ".join(self.instance.main_topics or [])

    def save(self, commit=True):
        course = super().save(commit=False)
        raw_topics = self.cleaned_data.get("main_topics_text", "")
        course.main_topics = [
            topic.strip()
            for topic in raw_topics.replace("\n", ",").split(",")
            if topic.strip()
        ][:24]
        if commit:
            course.save()
        return course


class FreeLessonForm(forms.ModelForm):
    class Meta:
        model = LessonJob
        fields = ("course", "title", "source_text", "tags")
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Ej: Fotosintesis en 20 minutos"}),
            "source_text": forms.Textarea(attrs={"rows": 8, "placeholder": "Pega aqui el texto de una clase o el tema que quieres aprender..."}),
            "tags": forms.TextInput(attrs={"placeholder": "historia, biologia, examen parcial"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = Course.objects.filter(user=user, is_archived=False) if user else Course.objects.none()
        self.fields["course"].label = "Curso"
        self.fields["course"].empty_label = "Selecciona un curso"


class ApiLessonForm(forms.ModelForm):
    class Meta:
        model = LessonJob
        fields = ("course", "title", "source_text", "audio", "tags")
        labels = {
            "course": "Curso",
            "title": "Título",
            "source_text": "Texto de la clase",
            "audio": "Audio de la clase",
            "tags": "Etiquetas",
        }
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Ej: Clase 3 · Mercados"}),
            "source_text": forms.Textarea(attrs={"rows": 8, "placeholder": "Pega aquí el texto de tu clase o tus apuntes"}),
            "audio": forms.ClearableFileInput(attrs={"accept": "audio/*", "capture": "microphone"}),
            "tags": forms.TextInput(attrs={"placeholder": "parcial 1, repaso"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = Course.objects.filter(user=user, is_archived=False) if user else Course.objects.none()
        self.fields["course"].empty_label = "Selecciona un curso"


class ManualResultForm(forms.Form):
    toon_output = forms.CharField(
        label="TOON generado",
        widget=forms.Textarea(attrs={"rows": 8, "placeholder": "Pega aqui el TOON que te devolvio la IA..."}),
    )


class VerificationResultForm(forms.Form):
    verification_output = forms.CharField(
        label="JSON o reporte de verificacion",
        widget=forms.Textarea(attrs={"rows": 8, "placeholder": "Pega aqui el .json/reporte final..."}),
    )
