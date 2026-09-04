"""use_str_id_for_user_drop_oidc_sub

Revision ID: 5a1f26b97088
Revises: 80ca18798af8
Create Date: 2026-03-12 21:30:13.378396

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa


# revision identifiers, used by Alembic.
revision: str = "5a1f26b97088"
down_revision: Union[str, Sequence[str], None] = "80ca18798af8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("collection_owner_id_fkey", "collection", type_="foreignkey")
    op.alter_column(
        "user",
        "id",
        existing_type=sa.UUID(),
        type_=sqlmodel.sql.sqltypes.AutoString(),
        existing_nullable=False,
        postgresql_using="id::text",
    )
    op.alter_column(
        "collection",
        "owner_id",
        existing_type=sa.UUID(),
        type_=sqlmodel.sql.sqltypes.AutoString(),
        existing_nullable=False,
        postgresql_using="owner_id::text",
    )
    op.create_foreign_key(
        "collection_owner_id_fkey", "collection", "user", ["owner_id"], ["id"]
    )
    op.drop_constraint(op.f("uq_user_oidc_sub"), "user", type_="unique")
    op.drop_column("user", "oidc_sub")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "user", sa.Column("oidc_sub", sa.VARCHAR(), autoincrement=False, nullable=True)
    )
    op.create_unique_constraint(
        op.f("uq_user_oidc_sub"),
        "user",
        ["oidc_sub"],
        postgresql_nulls_not_distinct=False,
    )
    op.drop_constraint("collection_owner_id_fkey", "collection", type_="foreignkey")
    op.alter_column(
        "user",
        "id",
        existing_type=sqlmodel.sql.sqltypes.AutoString(),
        type_=sa.UUID(),
        existing_nullable=False,
        postgresql_using="id::uuid",
    )
    op.alter_column(
        "collection",
        "owner_id",
        existing_type=sqlmodel.sql.sqltypes.AutoString(),
        type_=sa.UUID(),
        existing_nullable=False,
        postgresql_using="owner_id::uuid",
    )
    op.create_foreign_key(
        "collection_owner_id_fkey", "collection", "user", ["owner_id"], ["id"]
    )
