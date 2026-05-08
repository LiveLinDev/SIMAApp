from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import LessonJob, Plan


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")


class PlanForm(forms.Form):
    plan = forms.ChoiceField(choices=Plan.choices, widget=forms.RadioSelect)


class FreeLessonForm(forms.ModelForm):
    class Meta:
        model = LessonJob
        fields = ("title", "source_text", "tags")
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Ej: Fotosintesis en 20 minutos"}),
            "source_text": forms.Textarea(attrs={"rows": 8, "placeholder": "Pega aqui el texto de una clase o el tema que quieres aprender..."}),
            "tags": forms.TextInput(attrs={"placeholder": "historia, biologia, examen parcial"}),
        }


class ApiLessonForm(forms.ModelForm):
    class Meta:
        model = LessonJob
        fields = ("title", "source_text", "audio", "tags")
        labels = {
            "title": "Titulo",
            "source_text": "Texto de la clase",
            "audio": "Audio de la clase",
            "tags": "Etiquetas",
        }
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Ej: Clase de economia"}),
            "source_text": forms.Textarea(attrs={"rows": 5, "placeholder": "Opcional si subes audio. Tambien puedes pegar texto directo."}),
            "audio": forms.ClearableFileInput(attrs={"accept": "audio/*", "capture": "microphone"}),
            "tags": forms.TextInput(attrs={"placeholder": "moba, historia, videojuegos"}),
        }


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
