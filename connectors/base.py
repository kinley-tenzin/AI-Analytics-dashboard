"""Common connector interface, value objects and errors shared by all ERP adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Protocol

from druksmart_common.contracts import EntityContract, SourceContract, load_source_contract

# ------------------------------------------------------------------------- errors


class ConnectorError(Exception):
    """Base class for all connector failures."""


class AuthenticationError(ConnectorError):
    """Credentials missing, wrong or expired (HTTP 401). Never retried."""


class PermissionDeniedError(ConnectorError):
    """Authenticated, but the ERP user may not read this data (HTTP 403)."""


class EntityNotFoundError(ConnectorError):
    """The model / DocType does not exist or is not installed on this ERP."""


class InvalidRequestError(ConnectorError):
    """The ERP rejected the request, e.g. an unknown field or bad filter."""


class TransientError(ConnectorError):
    """Timeouts, connection errors, HTTP 429/502/503/504: safe to retry."""


class RetryExhaustedError(TransientError):
    """A transient failure persisted after all retry attempts."""


class ResponseFormatError(ConnectorError):
    """The ERP answered with something that does not match the documented API shape."""


class ReadOnlyViolationError(ConnectorError):
    """Code attempted a non-read API operation. The platform never writes to an ERP."""


class UnsupportedEntityError(ConnectorError):
    """The entity is not in the source contract or its extraction is deferred."""


# -------------------------------------------------------------------- value objects


@dataclass(frozen=True)
class ExtractionWindow:
    """Records modified in ``(modified_after, modified_until]`` (aware UTC datetimes).

    ``modified_after=None`` means "from the beginning" (full extraction). The upper bound is
    the run start, so records changing during the run are left for the next run instead of
    shifting pages under us.
    """

    modified_after: datetime | None
    modified_until: datetime

    def __post_init__(self):
        for value in (self.modified_after, self.modified_until):
            if value is not None and value.tzinfo is None:
                raise ValueError("ExtractionWindow datetimes must be timezone-aware")


@dataclass(frozen=True)
class Page:
    entity: str
    number: int
    records: list[dict[str, Any]]
    last_source_id: str  # keyset cursor: the next page starts after this id


@dataclass(frozen=True)
class ConnectionReport:
    source_system: str
    base_url: str
    reachable: bool
    authenticated: bool
    user: str | None = None
    server_version: str | None = None
    version_supported: bool | None = None
    details: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.reachable and self.authenticated and self.version_supported is not False


@dataclass(frozen=True)
class EntityCheck:
    entity: str
    available: bool
    missing_fields: list[str] = field(default_factory=list)
    detail: str = ""


class CheckpointStore(Protocol):
    """Where extraction checkpoints live (implemented by ``ingestion``; in-memory in tests)."""

    def get_checkpoint(
        self, source_system: str, source_instance: str, entity: str
    ) -> datetime | None: ...


# ---------------------------------------------------------------------- interface


class SourceConnector(ABC):
    """Interface every ERP adapter implements. All operations are read-only."""

    source_system: ClassVar[str]
    supported_major_versions: ClassVar[tuple[str, ...]]

    def __init__(self, config):
        if config.source_system != self.source_system:
            raise ValueError(f"{type(self).__name__} cannot use a {config.source_system} config")
        self.config = config
        self.contract: SourceContract = load_source_contract(self.source_system)

    @property
    def source_instance(self) -> str:
        return self.config.instance_id

    def entities(self, module: str | None = None) -> list[str]:
        """Contracted entities that can be extracted (deferred ones excluded)."""
        return [
            name
            for name, spec in self.contract.entities.items()
            if spec.extraction != "deferred" and (module is None or spec.module == module)
        ]

    def entity_contract(self, entity: str) -> EntityContract:
        try:
            spec = self.contract.entity(entity)
        except KeyError:
            raise UnsupportedEntityError(
                f"{entity!r} is not in the {self.source_system} contract"
            ) from None
        if spec.extraction == "deferred":
            raise UnsupportedEntityError(f"{entity!r} extraction is deferred in the contract")
        return spec

    @abstractmethod
    def check_connection(self) -> ConnectionReport:
        """Reachability, authentication and server-version check."""

    @abstractmethod
    def validate_entity(self, entity: str) -> EntityCheck:
        """Confirm the entity exists and every contracted field is readable by this user."""

    def validate_entities(self, entities: list[str] | None = None) -> list[EntityCheck]:
        return [self.validate_entity(e) for e in (entities or self.entities())]

    @abstractmethod
    def fetch_pages(
        self,
        entity: str,
        window: ExtractionWindow,
        *,
        page_size: int | None = None,
        start_after: str | None = None,
    ) -> Iterator[Page]:
        """Yield pages of source records in ascending primary-key order.

        Pages are fetched with keyset pagination (``primary key > last id``), so a record
        modified mid-run never shifts other records between pages.
        """

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
