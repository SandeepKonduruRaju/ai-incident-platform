output "state_bucket" {
  description = "Use as bucket in infra/envs/demo/backend.hcl."
  value       = aws_s3_bucket.tfstate.bucket
}

output "github_deploy_role_arn" {
  description = "Repository variable AWS_DEPLOY_ROLE_ARN."
  value       = aws_iam_role.github_deploy.arn
}

output "github_terraform_role_arn" {
  description = "Repository variable AWS_TERRAFORM_ROLE_ARN."
  value       = aws_iam_role.github_terraform.arn
}

output "github_oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.github.arn
}

output "budget_name" {
  value = module.budget.name
}
