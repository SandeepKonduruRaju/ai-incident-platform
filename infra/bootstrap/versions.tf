terraform {
  # Pinned: the same Terraform and AWS provider versions locally and in CI (.terraform.lock.hcl pins the hashes).
  required_version = "~> 1.16.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.69.1"
    }
  }

  # The bootstrap creates the remote-state bucket, so its own (small) state is LOCAL: keep
  # infra/bootstrap/terraform.tfstate safe (it is gitignored). Optionally migrate it into the bucket afterwards.
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
