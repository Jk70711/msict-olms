import json
from django.db import models
from accounts.models import OLMSUser


class ReportTemplate(models.Model):
    name = models.CharField(max_length=200)
    created_by = models.ForeignKey(OLMSUser, on_delete=models.CASCADE, related_name='report_templates')
    table_key = models.CharField(max_length=50)
    columns_json = models.TextField(default='[]')
    preset = models.CharField(max_length=20, default='7d')
    custom_duration = models.CharField(max_length=50, blank=True)
    filters_json = models.TextField(default='[]')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'report_templates'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.created_by.username})'

    def get_columns(self):
        try:
            return json.loads(self.columns_json) if self.columns_json else []
        except (ValueError, TypeError):
            return []

    def get_filters(self):
        try:
            return json.loads(self.filters_json) if self.filters_json else []
        except (ValueError, TypeError):
            return []
