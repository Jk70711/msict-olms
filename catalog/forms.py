from django import forms
from .models import Footer, MediaSlide, News


class FooterForm(forms.ModelForm):
    """Form for editing footer configuration"""
    class Meta:
        model = Footer
        fields = [
            'school_name', 'address', 'phone', 'email', 'location',
            'copyright_text', 'faq_link',
            'social_facebook', 'social_twitter', 'social_linkedin', 'social_instagram',
            'additional_links', 'is_active'
        ]
        widgets = {
            'school_name': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'maxlength': '10', 'pattern': '^0\\d{9}$', 'placeholder': 'e.g. 0712345678'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            'copyright_text': forms.TextInput(attrs={'class': 'form-control'}),
            'faq_link': forms.URLInput(attrs={'class': 'form-control'}),
            'social_facebook': forms.URLInput(attrs={'class': 'form-control'}),
            'social_twitter': forms.URLInput(attrs={'class': 'form-control'}),
            'social_linkedin': forms.URLInput(attrs={'class': 'form-control'}),
            'social_instagram': forms.URLInput(attrs={'class': 'form-control'}),
            'additional_links': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Example:\nAbout Us|/about\nContact|/contact\nPrivacy Policy|/privacy'
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class MediaSlideForm(forms.ModelForm):
    """Form for creating/editing media slides"""
    class Meta:
        model = MediaSlide
        fields = ['title', 'description', 'image', 'slide_type', 'bg_color', 'link_url', 'is_active', 'display_order', 'expires_at']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'image': forms.FileInput(attrs={'class': 'form-control'}),
            'slide_type': forms.Select(attrs={'class': 'form-select'}),
            'bg_color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color'}),
            'link_url': forms.URLInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'display_order': forms.NumberInput(attrs={'class': 'form-control'}),
            'expires_at': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
        }


class NewsForm(forms.ModelForm):
    """Form for creating/editing news posts"""
    class Meta:
        model = News
        fields = ['title', 'content', 'news_type', 'image', 'video_url', 'link_url', 'attachment', 'is_active', 'is_featured', 'expires_at']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'content': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'news_type': forms.Select(attrs={'class': 'form-select'}),
            'image': forms.FileInput(attrs={'class': 'form-control'}),
            'video_url': forms.URLInput(attrs={'class': 'form-control'}),
            'link_url': forms.URLInput(attrs={'class': 'form-control'}),
            'attachment': forms.FileInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_featured': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'expires_at': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
        }
