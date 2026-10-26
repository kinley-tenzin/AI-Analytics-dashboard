"""Fixtures for the Django backend tests (users per role, scopes, warehouse availability)."""

from __future__ import annotations

import pytest


@pytest.fixture
def role_user(django_user_model):
    """Create a user with one DrukSmart role (and optional branches)."""
    from access.models import BranchScope
    from django.contrib.auth.models import Group

    def make(username: str, role: str | None, branches: tuple[str, ...] = ()):
        user = django_user_model.objects.create_user(username=username, password="pw-for-tests")
        if role:
            user.groups.add(Group.objects.get_or_create(name=role)[0])
        for key in branches:
            BranchScope.objects.create(user=user, branch_key=key)
        return user

    return make
