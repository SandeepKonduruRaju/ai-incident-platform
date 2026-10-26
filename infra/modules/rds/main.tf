# PostgreSQL on RDS, single instance in the private subnets.
#
# pgvector: no parameter needed. RDS for PostgreSQL ships the "vector" extension; the worker's Alembic migration
# 0002 runs CREATE EXTENSION IF NOT EXISTS vector as the master user (member of rds_superuser).
#
# Master password: generated and stored by RDS itself in Secrets Manager (manage_master_user_password), rotated
# by AWS. Terraform never sees it; ECS injects username/password from that secret into the tasks.

resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids
}

resource "aws_db_parameter_group" "this" {
  name   = "${var.name}-pg${var.engine_major_version}"
  family = "postgres${var.engine_major_version}"

  # TLS for every connection (the apps connect with sslmode=require / ssl=require).
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  lifecycle {
    create_before_destroy = true
  }
}

#trivy:ignore:AVD-AWS-0176 IAM database authentication not used: the apps authenticate with the RDS-managed Secrets Manager password.
#trivy:ignore:AVD-AWS-0177 Deletion protection deliberately off for the demo (destroyed the same day). Production: true.
#trivy:ignore:AVD-AWS-0077 One day of automated backups: the demo database holds only synthetic data and is destroyed the same day. Production: 7-35 days.
#trivy:ignore:AVD-AWS-0133 Performance Insights off for the demo (cost/noise). Production: on.
resource "aws_db_instance" "this" {
  identifier     = var.name
  engine         = "postgres"
  engine_version = var.engine_major_version # major only: RDS picks the current default minor version
  instance_class = var.instance_class

  allocated_storage     = var.allocated_storage_gb
  max_allocated_storage = 0 # no storage autoscaling for the demo
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name                     = var.db_name
  username                    = var.username
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  parameter_group_name   = aws_db_parameter_group.this.name
  vpc_security_group_ids = [var.security_group_id]
  publicly_accessible    = false
  multi_az               = false # production: true (standby in a second AZ)

  backup_retention_period    = var.backup_retention_days
  copy_tags_to_snapshot      = true
  auto_minor_version_upgrade = true
  apply_immediately          = true

  # DEMO SETTINGS: the instance is meant to be destroyed the same day. In production set
  # deletion_protection = true and skip_final_snapshot = false (with a final_snapshot_identifier).
  deletion_protection = var.deletion_protection
  skip_final_snapshot = var.skip_final_snapshot
}
