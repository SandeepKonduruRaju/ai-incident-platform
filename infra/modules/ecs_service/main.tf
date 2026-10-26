# One Fargate workload: log group, two IAM roles, task definition and (optionally) a long-running service.
# Used for the three services (incident-service, investigation-worker, kafka) and the one-off tasks
# (kafka topics, migrations, ingest), which are run with `aws ecs run-task` (create_service = false).
#
# Roles, per workload, least privilege:
#   execution role: used by the ECS agent BEFORE the app starts: pull this workload's image (its ECR repository
#     only), write to its own log group only, read only the Secrets Manager secrets it injects.
#   task role:      used by the application code at runtime. Our apps call no AWS API, so it has no policy.

data "aws_region" "current" {}

locals {
  secret_arns = distinct([for value_from in values(var.secrets) : regex("^(arn:[^:]+:secretsmanager:[^:]+:[^:]+:secret:[^:]+)", value_from)[0]])
  port_mappings = [for port in var.container_ports : {
    containerPort = port
    protocol      = "tcp"
  }]
  container = merge(
    {
      name         = var.name
      image        = var.image
      essential    = true
      portMappings = local.port_mappings
      environment  = [for key in sort(keys(var.environment)) : { name = key, value = var.environment[key] }]
      # Secrets Manager references only: ECS resolves them at start; values never appear in the task definition.
      secrets                = [for key in sort(keys(var.secrets)) : { name = key, valueFrom = var.secrets[key] }]
      readonlyRootFilesystem = var.readonly_root_filesystem
      mountPoints            = var.readonly_root_filesystem ? [{ sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }] : []
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.this.name
          awslogs-region        = data.aws_region.current.region
          awslogs-stream-prefix = var.name
        }
      }
    },
    var.command == null ? {} : { command = var.command },
    var.health_check_command == null ? {} : {
      healthCheck = {
        command     = ["CMD-SHELL", var.health_check_command]
        interval    = 15
        timeout     = 5
        retries     = 3
        startPeriod = var.health_check_start_period
      }
    },
  )
}

#trivy:ignore:AVD-AWS-0017 Log groups use the default CloudWatch encryption, not a customer-managed KMS key (demo cost).
resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.name_prefix}/${var.name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name_prefix}-${var.name}-execution"
  path               = var.iam_path
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "execution" {
  # Docker Hub images (Kafka) need no ECR permissions at all.
  dynamic "statement" {
    for_each = var.ecr_repository_arn == null ? [] : [1]
    content {
      sid       = "EcrAuth"
      actions   = ["ecr:GetAuthorizationToken"]
      resources = ["*"] # this API has no resource-level permissions
    }
  }

  dynamic "statement" {
    for_each = var.ecr_repository_arn == null ? [] : [1]
    content {
      sid       = "PullOwnImage"
      actions   = ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
      resources = [var.ecr_repository_arn]
    }
  }

  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.this.arn}:*"]
  }

  dynamic "statement" {
    for_each = length(local.secret_arns) == 0 ? [] : [1]
    content {
      sid       = "ReadOwnSecrets"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = local.secret_arns
    }
  }
}

resource "aws_iam_role_policy" "execution" {
  name   = "least-privilege"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution.json
}

# Runtime identity of the application: no AWS permissions (the apps only talk to Postgres, Kafka and HTTP).
resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-${var.name}-task"
  path               = var.iam_path
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_ecs_task_definition" "this" {
  family                   = "${var.name_prefix}-${var.name}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions    = jsonencode([local.container])

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64" # the images are built for amd64 (GitHub runners)
  }

  dynamic "volume" {
    for_each = var.readonly_root_filesystem ? [1] : []
    content {
      name = "tmp" # Fargate task storage, writable, discarded with the task
    }
  }
}

# Cloud Map: <name>.<namespace> resolves to the task IPs (A records), e.g. kafka.incident-platform.local.
resource "aws_service_discovery_service" "this" {
  count = var.create_service && var.service_discovery_namespace_id != null ? 1 : 0

  name = var.name

  dns_config {
    namespace_id   = var.service_discovery_namespace_id
    routing_policy = "MULTIVALUE"

    dns_records {
      type = "A"
      ttl  = 10
    }
  }

  health_check_custom_config {}
}

resource "aws_ecs_service" "this" {
  count = var.create_service ? 1 : 0

  name             = var.name
  cluster          = var.cluster_arn
  task_definition  = aws_ecs_task_definition.this.arn
  desired_count    = var.desired_count
  launch_type      = "FARGATE"
  platform_version = "LATEST"
  propagate_tags   = "SERVICE"

  # Rolling deployment without dropping below the current capacity; a failing deployment rolls back by itself.
  deployment_minimum_healthy_percent = var.deployment_minimum_healthy_percent
  deployment_maximum_percent         = 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  health_check_grace_period_seconds = var.target_group_arn == null ? null : var.health_check_grace_period

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = var.assign_public_ip
  }

  dynamic "service_registries" {
    for_each = aws_service_discovery_service.this
    content {
      registry_arn = service_registries.value.arn
    }
  }

  dynamic "load_balancer" {
    for_each = var.target_group_arn == null ? [] : [1]
    content {
      target_group_arn = var.target_group_arn
      container_name   = var.name
      container_port   = var.container_ports[0]
    }
  }
}
