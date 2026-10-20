# One-time setup, applied BEFORE anything billable:
#   1. the cost budget with e-mail alerts (first, so every later cost is watched)
#   2. the S3 bucket for the remote Terraform state of infra/envs/*
#   3. the GitHub Actions OIDC provider and the two deploy roles (github_oidc.tf)
#
# State locking: S3 native lock files (backend "s3" { use_lockfile = true }, Terraform >= 1.10). The lock is a
# conditional write of <key>.tflock next to the state, so no DynamoDB table is needed (and the DynamoDB-based
# locking is deprecated).

data "aws_caller_identity" "current" {}

module "budget" {
  source = "../modules/budget"

  name              = "ai-incident-platform-monthly"
  monthly_limit_usd = var.monthly_budget_usd
  alert_email       = var.budget_alert_email
}

locals {
  state_bucket_name = "${var.state_bucket_prefix}-${data.aws_caller_identity.current.account_id}-${var.region}"
}

#trivy:ignore:AVD-AWS-0089 No access logging on the state bucket (it would need a second bucket); versioning keeps every state revision.
resource "aws_s3_bucket" "tfstate" {
  bucket = local.state_bucket_name

  # The state is precious: never let "terraform destroy" delete the bucket while it holds objects.
  force_destroy = false
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled"
  }
}

#trivy:ignore:AVD-AWS-0132 SSE-S3 (AES-256) instead of a customer-managed KMS key (no extra key cost).
resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    object_ownership = "BucketOwnerEnforced" # ACLs disabled
  }
}

# Old state versions are kept for 90 days, then removed (the current version is never expired).
resource "aws_s3_bucket_lifecycle_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# TLS only: any request over plain HTTP is denied.
data "aws_iam_policy_document" "tfstate" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.tfstate.arn,
      "${aws_s3_bucket.tfstate.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  policy = data.aws_iam_policy_document.tfstate.json

  depends_on = [aws_s3_bucket_public_access_block.tfstate]
}
