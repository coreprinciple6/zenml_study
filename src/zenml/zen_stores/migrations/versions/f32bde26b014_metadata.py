"""metadata [f32bde26b014].

Revision ID: f32bde26b014
Revises: 0.35.0
Create Date: 2023-03-07 16:21:39.034053

"""
import sqlmodel
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f32bde26b014'
down_revision = '0.35.0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database schema and/or data, creating a new revision."""
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('stack_component', schema=None) as batch_op:
        batch_op.add_column(sa.Column('metadata_values', sa.LargeBinary(), nullable=True))

    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade database schema and/or data back to the previous revision."""
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('stack_component', schema=None) as batch_op:
        batch_op.drop_column('metadata_values')

    # ### end Alembic commands ###
