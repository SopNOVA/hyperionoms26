"""initial models: users, customers, onts, telemetry_events

Revision ID: 8f4c2a1b9e3d
Revises: 
Create Date: 2026-06-02 16:46:16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "8f4c2a1b9e3d"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # userrole enum
    userrole = sa.Enum("admin", "supervisor", "technician", name="userrole")

    # users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", userrole, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=True),
        sa.Column("is_superuser", sa.Boolean(), server_default=sa.false(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    # customers
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("document", sa.String(length=50), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("plan", sa.String(length=100), nullable=True),
        sa.Column("installation_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mac_address", sa.String(length=17), nullable=True),
        sa.Column("gpon_sn", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_customers_id"), "customers", ["id"], unique=False)
    op.create_index(op.f("ix_customers_name"), "customers", ["name"], unique=False)
    op.create_index(op.f("ix_customers_document"), "customers", ["document"], unique=True)
    op.create_index(op.f("ix_customers_mac_address"), "customers", ["mac_address"], unique=True)
    op.create_index(op.f("ix_customers_gpon_sn"), "customers", ["gpon_sn"], unique=True)

    # olts (new for Hyperion-ONMS)
    op.create_table(
        "olts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("firmware", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'UP'"), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ping_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_olts_id"), "olts", ["id"], unique=False)
    op.create_index(op.f("ix_olts_name"), "olts", ["name"], unique=False)
    op.create_index(op.f("ix_olts_ip_address"), "olts", ["ip_address"], unique=False)
    op.create_index(op.f("ix_olts_status"), "olts", ["status"], unique=False)

    # onts (enhanced with mac + olt link)
    op.create_table(
        "onts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gpon_sn", sa.String(length=50), nullable=False),
        sa.Column("mac_address", sa.String(length=17), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("firmware", sa.String(length=100), nullable=True),
        sa.Column("olt_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ),
        sa.ForeignKeyConstraint(["olt_id"], ["olts.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_onts_id"), "onts", ["id"], unique=False)
    op.create_index(op.f("ix_onts_gpon_sn"), "onts", ["gpon_sn"], unique=True)
    op.create_index(op.f("ix_onts_mac_address"), "onts", ["mac_address"], unique=True)
    op.create_index(op.f("ix_onts_olt_id"), "onts", ["olt_id"], unique=False)
    op.create_index(op.f("ix_onts_customer_id"), "onts", ["customer_id"], unique=False)

    # telemetry_events
    op.create_table(
        "telemetry_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ont_id", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("classification", sa.String(length=50), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("wan_ip", sa.String(length=45), nullable=True),
        sa.Column("ping_8_avg", sa.Float(), nullable=True),
        sa.Column("ping_1_avg", sa.Float(), nullable=True),
        sa.Column("tcp_retrans_segs", sa.Integer(), nullable=True),
        sa.Column("data", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("delivery", sa.String(length=20), server_default=sa.text("'live'"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["ont_id"], ["onts.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_telemetry_events_id"), "telemetry_events", ["id"], unique=False)
    op.create_index(op.f("ix_telemetry_events_ont_id"), "telemetry_events", ["ont_id"], unique=False)
    op.create_index(op.f("ix_telemetry_events_received_at"), "telemetry_events", ["received_at"], unique=False)
    op.create_index(op.f("ix_telemetry_events_classification"), "telemetry_events", ["classification"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_telemetry_events_classification"), table_name="telemetry_events")
    op.drop_index(op.f("ix_telemetry_events_received_at"), table_name="telemetry_events")
    op.drop_index(op.f("ix_telemetry_events_ont_id"), table_name="telemetry_events")
    op.drop_index(op.f("ix_telemetry_events_id"), table_name="telemetry_events")
    op.drop_table("telemetry_events")

    op.drop_index(op.f("ix_onts_customer_id"), table_name="onts")
    op.drop_index(op.f("ix_onts_olt_id"), table_name="onts")
    op.drop_index(op.f("ix_onts_mac_address"), table_name="onts")
    op.drop_index(op.f("ix_onts_gpon_sn"), table_name="onts")
    op.drop_index(op.f("ix_onts_id"), table_name="onts")
    op.drop_table("onts")

    op.drop_index(op.f("ix_olts_status"), table_name="olts")
    op.drop_index(op.f("ix_olts_ip_address"), table_name="olts")
    op.drop_index(op.f("ix_olts_name"), table_name="olts")
    op.drop_index(op.f("ix_olts_id"), table_name="olts")
    op.drop_table("olts")

    op.drop_index(op.f("ix_customers_gpon_sn"), table_name="customers")
    op.drop_index(op.f("ix_customers_mac_address"), table_name="customers")
    op.drop_index(op.f("ix_customers_document"), table_name="customers")
    op.drop_index(op.f("ix_customers_name"), table_name="customers")
    op.drop_index(op.f("ix_customers_id"), table_name="customers")
    op.drop_table("customers")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_table("users")

    # Drop enum type (postgres)
    op.execute("DROP TYPE IF EXISTS userrole")
