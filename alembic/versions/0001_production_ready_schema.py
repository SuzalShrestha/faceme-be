"""Production-ready schema"""

from alembic import op
import sqlalchemy as sa


revision = "0001_production"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_id", "users", ["id"], unique=False)

    op.create_table(
        "clusters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("representative_face_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_clusters_id", "clusters", ["id"], unique=False)
    op.create_index("ix_clusters_user_id", "clusters", ["user_id"], unique=False)

    op.create_table(
        "images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("original_name", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_images_id", "images", ["id"], unique=False)
    op.create_index("ix_images_storage_key", "images", ["storage_key"], unique=True)
    op.create_index("ix_images_user_id", "images", ["user_id"], unique=False)

    op.create_table(
        "pipeline_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pipeline_jobs_user_id", "pipeline_jobs", ["user_id"], unique=False)

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sessions_id", "sessions", ["id"], unique=False)
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=True)
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)

    op.create_table(
        "faces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("image_id", sa.Integer(), sa.ForeignKey("images.id"), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("bbox", sa.Text(), nullable=False),
        sa.Column("crop_key", sa.String(), nullable=False),
        sa.Column("det_score", sa.String(), nullable=True),
        sa.Column("cluster_id", sa.Integer(), sa.ForeignKey("clusters.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_faces_id", "faces", ["id"], unique=False)
    op.create_foreign_key(
        "fk_clusters_representative_face_id_faces",
        "clusters",
        "faces",
        ["representative_face_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_clusters_representative_face_id_faces", "clusters", type_="foreignkey")
    op.drop_index("ix_faces_id", table_name="faces")
    op.drop_table("faces")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_index("ix_sessions_token_hash", table_name="sessions")
    op.drop_index("ix_sessions_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_pipeline_jobs_user_id", table_name="pipeline_jobs")
    op.drop_table("pipeline_jobs")
    op.drop_index("ix_images_user_id", table_name="images")
    op.drop_index("ix_images_storage_key", table_name="images")
    op.drop_index("ix_images_id", table_name="images")
    op.drop_table("images")
    op.drop_index("ix_clusters_user_id", table_name="clusters")
    op.drop_index("ix_clusters_id", table_name="clusters")
    op.drop_table("clusters")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
