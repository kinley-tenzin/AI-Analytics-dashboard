"""Read-only ERP connectors (Odoo, ERPNext) behind one common interface.

Connectors only talk to ERP APIs and yield source records page by page. They know nothing
about PostgreSQL; storing records and checkpoints is the job of ``ingestion``.
"""

from connectors.base import SourceConnector
from connectors.config import SourceConfig, load_source_config


def create_connector(config: SourceConfig, **kwargs) -> SourceConnector:
    """Build the adapter for ``config.source_system`` (kwargs go to the API client)."""
    from connectors.erpnext import ERPNextConnector
    from connectors.odoo import OdooConnector

    adapters = {"odoo": OdooConnector, "erpnext": ERPNextConnector}
    return adapters[config.source_system](config, **kwargs)


__all__ = ["SourceConnector", "SourceConfig", "create_connector", "load_source_config"]
