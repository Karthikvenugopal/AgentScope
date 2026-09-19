"""Require official verification when a run is committed as completed."""

from alembic import op

revision = "0002_completion_guard"
down_revision = "0001_verified_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE FUNCTION agentscope_completed_run_guard() RETURNS trigger AS $$
        BEGIN
            IF NEW.status = 'completed' AND NOT EXISTS (
                SELECT 1 FROM verifications v JOIN run_metrics m USING (run_id)
                WHERE v.run_id = NEW.run_id AND v.passed AND NOT v.timed_out
            ) THEN
                RAISE EXCEPTION 'completed run requires verification and metrics'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER completed_run_guard
        AFTER INSERT OR UPDATE ON runs DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION agentscope_completed_run_guard()
    """)


def downgrade():
    op.execute("DROP TRIGGER completed_run_guard ON runs")
    op.execute("DROP FUNCTION agentscope_completed_run_guard()")
