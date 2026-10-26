"""ERP connection settings validation."""

import pytest

from connectors.config import load_source_config
from druksmart_common.config import ConfigError

ODOO_ENV = {
    "ODOO_INSTANCE_ID": "odoo-test",
    "ODOO_BASE_URL": "https://odoo.example.com/",
    "ODOO_API_KEY": "secret-key-value",
    "ODOO_DATABASE": "prod",
}
ERP_ENV = {
    "ERPNEXT_INSTANCE_ID": "erp-test",
    "ERPNEXT_BASE_URL": "http://localhost:8080",
    "ERPNEXT_API_KEY": "k",
    "ERPNEXT_API_SECRET": "secret-value",
}


def test_valid_configs_and_defaults():
    odoo = load_source_config("odoo", ODOO_ENV)
    assert odoo.base_url == "https://odoo.example.com"  # trailing slash removed
    assert (odoo.database, odoo.timezone, odoo.page_size) == ("prod", "UTC", 200)
    erp = load_source_config("erpnext", ERP_ENV)
    assert erp.timezone == "Asia/Thimphu"


def test_secrets_are_not_in_repr():
    assert "secret" not in repr(load_source_config("odoo", ODOO_ENV))
    assert "secret" not in repr(load_source_config("erpnext", ERP_ENV))


def test_missing_settings_are_named():
    env = dict(ERP_ENV)
    del env["ERPNEXT_API_SECRET"]
    with pytest.raises(ConfigError, match="ERPNEXT_API_SECRET"):
        load_source_config("erpnext", env)


def test_plain_http_only_allowed_for_local_servers():
    with pytest.raises(ConfigError, match="https"):
        load_source_config("odoo", ODOO_ENV | {"ODOO_BASE_URL": "http://odoo.example.com"})
    assert load_source_config("odoo", ODOO_ENV | {"ODOO_BASE_URL": "http://127.0.0.1:8069"})


def test_internal_docker_hosts_need_explicit_allow_listing():
    env = ODOO_ENV | {"ODOO_BASE_URL": "http://host.docker.internal:8069"}
    with pytest.raises(ConfigError, match="https"):
        load_source_config("odoo", env)
    allowed = env | {"DRUKSMART_INSECURE_HTTP_HOSTS": "host.docker.internal, synthetic-erp"}
    assert load_source_config("odoo", allowed).base_url == "http://host.docker.internal:8069"


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"ERPNEXT_TIMEZONE": "Mars/Base"}, "time zone"),
        ({"DRUKSMART_PAGE_SIZE": "0"}, "DRUKSMART_PAGE_SIZE"),
        ({"DRUKSMART_HTTP_TIMEOUT_SECONDS": "abc"}, "number"),
        ({"ERPNEXT_BASE_URL": "ftp://x"}, "http"),
    ],
)
def test_invalid_values_are_rejected(extra, message):
    with pytest.raises(ConfigError, match=message):
        load_source_config("erpnext", ERP_ENV | extra)
