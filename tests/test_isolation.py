"""Tenant isolation: one town can't reach another by editing the URL.

Each town is a separate instance — its own database, object store, KMS key,
container/route, and (critically) its own SECRET_KEY. A session minted for one
town is signed with that town's key, so it is cryptographically invalid at any
other town, and there is no shared database to query across. This test proves
the provisioner hands every town fully distinct, non-shared primitives.
"""

from orchestrator import provisioner
from orchestrator.models import Tenant
from tests.conftest import make_tenant, provision


def test_towns_get_fully_distinct_infrastructure(client, db):
    a = make_tenant(client, slug="alpha", name="Alpha")
    b = make_tenant(client, slug="bravo", name="Bravo")
    provision(client, a["id"])
    provision(client, b["id"])

    ta = db.get(Tenant, a["id"])
    tb = db.get(Tenant, b["id"])

    # Separate database, object store, KMS key, and loopback port — nothing shared.
    assert ta.db_name and ta.db_name != tb.db_name
    assert ta.storage_bucket != tb.storage_bucket
    assert ta.kms_key_ref != tb.kms_key_ref
    assert ta.backend_port != tb.backend_port
    # Distinct hostnames route to distinct containers.
    assert ta.slug != tb.slug


def test_each_town_has_its_own_signing_key_and_tokens(client, db):
    a = make_tenant(client, slug="charlie", name="Charlie")
    b = make_tenant(client, slug="delta", name="Delta")
    provision(client, a["id"])
    provision(client, b["id"])

    # SECRET_KEY signs the town app's own sessions. Distinct per town => a
    # session/cookie from town A can never authenticate against town B.
    sa = provisioner.get_platform_secret(db, a["id"], "SECRET_KEY")
    sb = provisioner.get_platform_secret(db, b["id"], "SECRET_KEY")
    assert sa and sb and sa != sb

    # The provisioning token (state->town control channel) is also per town.
    pa = provisioner.get_platform_secret(db, a["id"], "PROVISIONING_TOKEN")
    pb = provisioner.get_platform_secret(db, b["id"], "PROVISIONING_TOKEN")
    assert pa and pb and pa != pb

    # And the one-time admin setup password is per town.
    aa = provisioner.get_platform_secret(db, a["id"], "INITIAL_ADMIN_PASSWORD")
    ab = provisioner.get_platform_secret(db, b["id"], "INITIAL_ADMIN_PASSWORD")
    assert aa and ab and aa != ab
