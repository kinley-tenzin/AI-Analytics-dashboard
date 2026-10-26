from django.contrib import admin

from .models import QuestionLog


@admin.register(QuestionLog)
class QuestionLogAdmin(admin.ModelAdmin):
    list_display = ("asked_at", "user", "status", "function", "interpreter", "duration_ms")
    list_filter = ("status", "interpreter", "function")
    search_fields = ("question", "user__username")
    readonly_fields = [f.name for f in QuestionLog._meta.fields]
