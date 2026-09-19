"""make protocol exclusions explicit

Revision ID: 0007_protocol_exclusions
Revises: 0006_controlled_experiments
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_protocol_exclusions"
down_revision: str | None = "0006_controlled_experiments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("experiment_runs", sa.Column("classification_note", sa.String()))
    op.drop_constraint("ck_experiment_run_validity", "experiment_runs", type_="check")
    op.drop_constraint("ck_experiment_run_classification", "experiment_runs", type_="check")
    op.create_check_constraint(
        "ck_experiment_run_validity",
        "experiment_runs",
        "validity IN ('valid','infrastructure_failure','protocol_excluded')",
    )
    op.create_check_constraint(
        "ck_experiment_run_classification",
        "experiment_runs",
        "classification IN "
        "('benchmark_success','benchmark_failure','infrastructure_failure','protocol_excluded')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE experiment_runs SET validity = 'infrastructure_failure', "
        "classification = 'infrastructure_failure' "
        "WHERE validity = 'protocol_excluded'"
    )
    op.drop_constraint("ck_experiment_run_validity", "experiment_runs", type_="check")
    op.drop_constraint("ck_experiment_run_classification", "experiment_runs", type_="check")
    op.create_check_constraint(
        "ck_experiment_run_validity",
        "experiment_runs",
        "validity IN ('valid','infrastructure_failure')",
    )
    op.create_check_constraint(
        "ck_experiment_run_classification",
        "experiment_runs",
        "classification IN ('benchmark_success','benchmark_failure','infrastructure_failure')",
    )
    op.drop_column("experiment_runs", "classification_note")
