from django.contrib import admin

from .models import BranchScope, LoginFailure


@admin.register(BranchScope)
class BranchScopeAdmin(admin.ModelAdmin):
    list_display = ("user", "branch_key")
    search_fields = ("user__username", "branch_key")


@admin.register(LoginFailure)
class LoginFailureAdmin(admin.ModelAdmin):
    """Failed sign-ins. Deleting a username's rows unlocks it immediately (access/throttle.py)."""

    list_display = ("username", "ip_address", "created_at")
    search_fields = ("username",)
    list_filter = ("created_at",)
    readonly_fields = ("username", "ip_address", "created_at")

    def has_add_permission(self, request):
        return False
