terraform {
  required_version = "~> 1.16.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.69.1"
    }
    random = {
      source  = "hashicorp/random"
      version = "= 3.9.1"
    }
  }

  # Remote state in the bucket created by infra/bootstrap. Partial configuration: the bucket name is account
  # specific, so it comes from backend.hcl (copy backend.hcl.example) or -backend-config in CI.
  # use_lockfile = S3 native state locking (a <key>.tflock object), no DynamoDB table.
  backend "s3" {
    key          = "envs/demo/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project    = "ai-incident-platform"
      env        = "demo"
      managed_by = "terraform"
    }
  }
}
