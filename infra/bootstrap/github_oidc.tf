# GitHub Actions -> AWS without stored access keys (OIDC). GitHub issues a short-lived token per job; AWS STS
# exchanges it for temporary credentials of a role, but only if the token's claims match the trust policy:
#   aud = sts.amazonaws.com
#   sub = repo:SandeepKonduruRaju/ai-incident-platform:ref:refs/heads/main   (exact match: no other repo,
#         branch, tag, pull request or fork can assume these roles)
#
# Two roles, both used only by the manual .github/workflows/deploy-aws.yml (and destroy-aws.yml):
#   github-deploy     least privilege for releasing: push the two images, run the one-off ECS tasks, update and
#                     watch the two ECS services, pass ONLY the project's task roles to ECS.
#   github-terraform  terraform apply/destroy of infra/envs/demo. Necessarily broader (it creates the VPC,
#                     RDS, ALB, IAM roles, ...), but limited to the services this stack uses, to IAM roles under
#                     the project's path, and to the project's state bucket.

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # No thumbprint_list: AWS validates GitHub's OIDC certificate itself.
}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  github_sub  = "repo:${var.github_repository}:ref:refs/heads/${var.github_branch}"
  cluster_arn = "arn:aws:ecs:${var.region}:${local.account_id}:cluster/${var.cluster_name}"
  iam_path    = "/ai-incident-platform/" # ECS task/execution roles created by infra/envs/demo
  # The GitHub roles live under a DIFFERENT path, so the terraform role (which may edit roles under
  # iam_path) can never modify its own permissions or the deploy role's: no privilege escalation.
  ci_iam_path  = "/ai-incident-platform-ci/"
  task_roles   = "arn:aws:iam::${local.account_id}:role${local.iam_path}*"
  family_glob  = "arn:aws:ecs:${var.region}:${local.account_id}:task-definition/${var.cluster_name}-*"
  repositories = [for name in var.ecr_repository_names : "arn:aws:ecr:${var.region}:${local.account_id}:repository/${name}"]
}

data "aws_iam_policy_document" "github_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [local.github_sub]
    }
  }
}

# ---------------------------------------------------------------- github-deploy (least privilege)

resource "aws_iam_role" "github_deploy" {
  name                 = "ai-incident-platform-github-deploy"
  path                 = local.ci_iam_path
  assume_role_policy   = data.aws_iam_policy_document.github_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # this API has no resource-level permissions
  }

  statement {
    sid = "PushTheTwoImages"
    actions = [
      "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:DescribeImages",
    ]
    resources = local.repositories
  }

  statement {
    sid       = "UpdateTheTwoServices"
    actions   = ["ecs:UpdateService", "ecs:DescribeServices"]
    resources = [for service in var.ecs_service_names : "arn:aws:ecs:${var.region}:${local.account_id}:service/${var.cluster_name}/${service}"]
  }

  statement {
    sid       = "RunOneOffTasksInTheClusterOnly"
    actions   = ["ecs:RunTask"]
    resources = [local.family_glob, "${local.family_glob}:*"]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [local.cluster_arn]
    }
  }

  statement {
    sid       = "WatchTasks"
    actions   = ["ecs:DescribeTasks", "ecs:ListTasks"]
    resources = ["*"]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [local.cluster_arn]
    }
  }

  statement {
    sid       = "ReadTaskDefinitions"
    actions   = ["ecs:DescribeTaskDefinition"]
    resources = ["*"] # no resource-level permissions for this API
  }

  statement {
    sid       = "PassOnlyTheProjectTaskRolesToEcs"
    actions   = ["iam:PassRole"]
    resources = [local.task_roles]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    sid       = "ReadOneOffTaskLogs"
    actions   = ["logs:GetLogEvents", "logs:FilterLogEvents"]
    resources = ["arn:aws:logs:${var.region}:${local.account_id}:log-group:/ecs/${var.cluster_name}/*"]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "least-privilege-release"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}

# ---------------------------------------------------------------- github-terraform (infrastructure changes)

resource "aws_iam_role" "github_terraform" {
  name                 = "ai-incident-platform-github-terraform"
  path                 = local.ci_iam_path
  assume_role_policy   = data.aws_iam_policy_document.github_trust.json
  max_session_duration = 3600
}

# Accepted risk: Terraform must create and delete whole resource types (VPC, RDS, ALB, ECS, ...): service-level wildcards are limited to the services of this stack; IAM is limited to the project path, S3 to the state bucket.
data "aws_iam_policy_document" "github_terraform" {
  statement {
    sid = "ManageTheStacksServices"
    actions = [
      "ec2:*", "ecs:*", "ecr:*", "rds:*", "elasticloadbalancing:*", "logs:*", "servicediscovery:*",
      "route53:*", # Cloud Map private DNS namespaces are Route 53 private hosted zones
      "acm:DescribeCertificate", "acm:ListCertificates",
      "sts:GetCallerIdentity",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "ProjectSecretsOnly"
    actions   = ["secretsmanager:*"]
    resources = ["arn:aws:secretsmanager:${var.region}:${local.account_id}:secret:${var.secrets_name_prefix}/*"]
  }

  statement {
    sid       = "RdsManagedMasterSecret"
    actions   = ["secretsmanager:DescribeSecret", "secretsmanager:GetResourcePolicy", "secretsmanager:CreateSecret", "secretsmanager:TagResource", "secretsmanager:DeleteSecret", "secretsmanager:RotateSecret"]
    resources = ["arn:aws:secretsmanager:${var.region}:${local.account_id}:secret:rds!*"]
  }

  statement {
    sid       = "ListSecrets"
    actions   = ["secretsmanager:ListSecrets", "secretsmanager:GetRandomPassword"]
    resources = ["*"]
  }

  statement {
    sid = "ProjectRolesOnly"
    actions = [
      "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:UntagRole", "iam:UpdateRole",
      "iam:UpdateAssumeRolePolicy", "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy",
      "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole", "iam:PassRole",
    ]
    resources = [local.task_roles]
  }

  statement {
    sid       = "ServiceLinkedRoles"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "iam:AWSServiceName"
      values = [
        "ecs.amazonaws.com", "elasticloadbalancing.amazonaws.com", "rds.amazonaws.com", "servicediscovery.amazonaws.com",
      ]
    }
  }

  statement {
    sid       = "StateBucket"
    actions   = ["s3:ListBucket", "s3:GetBucketVersioning"]
    resources = [aws_s3_bucket.tfstate.arn]
  }

  statement {
    sid       = "StateObjectsAndLockFiles"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.tfstate.arn}/*"]
  }
}

resource "aws_iam_role_policy" "github_terraform" {
  name   = "terraform-demo-stack"
  role   = aws_iam_role.github_terraform.id
  policy = data.aws_iam_policy_document.github_terraform.json
}
