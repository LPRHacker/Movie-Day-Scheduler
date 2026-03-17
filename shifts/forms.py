from django import forms
from .models import Preference, Movie

class PreferenceForm(forms.ModelForm):
    class Meta:
        model = Preference
        fields = ['movie']
