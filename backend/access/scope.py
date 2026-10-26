"""Authorised data scope of a user. Decided HERE, by the backend, never by the AI model.

Roles are Django groups with the same names as the Superset roles (superset/definitions/access.yml),
so one person gets the same domains in both systems. The accounts are separate, though: the
prototype has no single sign-on between Superset and Django (docs/backend/BACKEND.md).

The website is for managers and senior management (ADR-044). The HR and Accounts Managers may
also AUTHOR dashboards for their own module (in Superset) and publish them on the website; the
Executive and the Branch Manager only use them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

HR = "hr"
ACCOUNTS = "accounts"

# Django group -> KPI domains it may query.
ROLE_DOMAINS: dict[str, frozenset[str]] = {
    "DrukSmart HR Manager": frozenset({HR}),
    "DrukSmart Accounts Manager": frozenset({ACCOUNTS}),
    "DrukSmart Executive": frozenset({HR, ACCOUNTS}),
    "DrukSmart Branch Manager": frozenset({HR, ACCOUNTS}),
}
# Django group -> modules whose dashboards it may author and publish.
ROLE_AUTHOR_DOMAINS: dict[str, frozenset[str]] = {
    "DrukSmart HR Manager": frozenset({HR}),
    "DrukSmart Accounts Manager": frozenset({ACCOUNTS}),
}
BRANCH_RESTRICTED_ROLES = frozenset({"DrukSmart Branch Manager"})


@dataclass(frozen=True)
class Scope:
    """What a user may see. `branch_keys is None` means no branch restriction."""

    username: str
    roles: tuple[str, ...]
    domains: frozenset[str]
    branch_keys: frozenset[str] | None
    author_domains: frozenset[str] = field(default_factory=frozenset)

    def allows(self, domain: str) -> bool:
        return domain in self.domains

    def can_author(self, domain: str) -> bool:
        return domain in self.author_domains

    def as_dict(self) -> dict:
        return {
            "username": self.username,
            "roles": list(self.roles),
            "domains": sorted(self.domains),
            "branch_restricted": self.branch_keys is not None,
            "author_domains": sorted(self.author_domains),
        }


def scope_for(user) -> Scope:
    """Resolve the user's scope from their groups and branch assignments (deny by default)."""
    if not user or not user.is_authenticated or not user.is_active:
        return Scope("", (), frozenset(), frozenset())
    if user.is_superuser:
        everything = frozenset({HR, ACCOUNTS})
        return Scope(user.get_username(), ("Administrator",), everything, None, everything)
    roles = tuple(sorted(g.name for g in user.groups.all() if g.name in ROLE_DOMAINS))
    domains = frozenset().union(*(ROLE_DOMAINS[r] for r in roles)) if roles else frozenset()
    authors = (
        frozenset().union(*(ROLE_AUTHOR_DOMAINS.get(r, frozenset()) for r in roles))
        if roles
        else frozenset()
    )
    branch_keys = None
    if any(r in BRANCH_RESTRICTED_ROLES for r in roles):
        # A branch restriction always wins: a manager with no assigned branch sees nothing, and a
        # branch-restricted user never authors (Superset cannot limit an author to a branch).
        branch_keys = frozenset(user.branch_scopes.values_list("branch_key", flat=True))
        authors = frozenset()
    return Scope(user.get_username(), roles, domains, branch_keys, authors)
