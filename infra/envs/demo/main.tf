# The demo environment: the whole platform on ECS Fargate in one region, sized for a same-day demo.
# See infra/README.md for the architecture, costs and the bootstrap -> deploy -> destroy steps.

locals {
  name           = "ai-incident-platform-demo" # also the ECS cluster name (the bootstrap roles are scoped to it)
  iam_path       = "/ai-incident-platform/"    # the deploy role may only pass roles under this path
  namespace_name = "incident-platform.local"
  secrets_prefix = "ai-incident-platform/demo"
}

module "network" {
  source = "../../modules/network"

  name               = local.name
  enable_nat_gateway = var.enable_nat_gateway
}

module "security_groups" {
  source = "../../modules/security_groups"

  name         = local.name
  vpc_id       = module.network.vpc_id
  enable_https = var.certificate_arn != null
}

module "ecr" {
  source = "../../modules/ecr"

  repository_names = ["incident-service", "investigation-worker"]
}

module "rds" {
  source = "../../modules/rds"

  name                 = local.name
  subnet_ids           = module.network.private_subnet_ids
  security_group_id    = module.security_groups.rds_id
  engine_major_version = var.postgres_major_version
}

module "secrets" {
  source = "../../modules/secrets"

  name_prefix                     = local.secrets_prefix
  create_anthropic_api_key_secret = var.llm_provider == "anthropic"
}

#trivy:ignore:AVD-AWS-0034 Container Insights off for the demo (extra CloudWatch cost); enable in production.
resource "aws_ecs_cluster" "this" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

# Private DNS for the tasks: kafka.incident-platform.local, investigation-worker.incident-platform.local.
resource "aws_service_discovery_private_dns_namespace" "this" {
  name        = local.namespace_name
  description = "Service discovery for the ai-incident-platform demo"
  vpc         = module.network.vpc_id
}

module "alb" {
  source = "../../modules/alb"

  name              = "aip-demo" # ALB and target group names are limited to 32 characters
  vpc_id            = module.network.vpc_id
  public_subnet_ids = module.network.public_subnet_ids
  security_group_id = module.security_groups.alb_id
  certificate_arn   = var.certificate_arn
}

module "kafka" {
  source = "../../modules/kafka"

  kafka_mode         = var.kafka_mode
  name_prefix        = local.name
  iam_path           = local.iam_path
  cluster_arn        = aws_ecs_cluster.this.arn
  namespace_id       = aws_service_discovery_private_dns_namespace.this.id
  namespace_name     = local.namespace_name
  subnet_ids         = module.network.task_subnet_ids
  security_group_id  = module.security_groups.kafka_id
  assign_public_ip   = module.network.task_assign_public_ip
  log_retention_days = var.log_retention_days
}

locals {
  db_secret = module.rds.master_user_secret_arn # JSON {"username": ..., "password": ...}, rotated by RDS

  worker_image = "${module.ecr.repository_urls["investigation-worker"]}:${var.image_tag}"
  worker_environment = {
    KAFKA_BOOTSTRAP_SERVERS = module.kafka.bootstrap_servers
    KAFKA_TOPIC             = "incident-events"
    KAFKA_DLQ_TOPIC         = "incident-events.DLQ"
    DB_HOST                 = module.rds.address
    DB_PORT                 = tostring(module.rds.port)
    DB_NAME                 = module.rds.db_name
    DB_SSL                  = "require"
    LLM_PROVIDER            = var.llm_provider
    LOG_LEVEL               = "INFO"
    METRICS_PORT            = "9464"
    TRACING_EXPORT_ENABLED  = "false"
  }
  # Secrets Manager references only; the values are resolved by ECS when a task starts.
  worker_secrets = merge(
    {
      DB_USERNAME        = "${local.db_secret}:username::"
      DB_PASSWORD        = "${local.db_secret}:password::"
      INTERNAL_API_TOKEN = module.secrets.internal_api_token_arn
    },
    var.llm_provider == "anthropic" ? { ANTHROPIC_API_KEY = module.secrets.anthropic_api_key_arn } : {},
  )
  worker_common = {
    image              = local.worker_image
    ecr_repository_arn = module.ecr.repository_arns["investigation-worker"]
    subnet_ids         = module.network.task_subnet_ids
    security_group_ids = [module.security_groups.worker_id]
    assign_public_ip   = module.network.task_assign_public_ip
  }
}

module "incident_service" {
  source = "../../modules/ecs_service"

  name               = "incident-service"
  name_prefix        = local.name
  iam_path           = local.iam_path
  image              = "${module.ecr.repository_urls["incident-service"]}:${var.image_tag}"
  ecr_repository_arn = module.ecr.repository_arns["incident-service"]
  cpu                = 512
  memory             = 1024 # JVM heap = 75% of the task memory (MaxRAMPercentage in the image)
  container_ports    = [8080]
  environment = {
    DB_URL                        = "jdbc:postgresql://${module.rds.address}:${module.rds.port}/${module.rds.db_name}?sslmode=require"
    KAFKA_BOOTSTRAP_SERVERS       = module.kafka.bootstrap_servers
    INVESTIGATION_WORKER_BASE_URL = "http://investigation-worker.${local.namespace_name}:8000"
    MANAGEMENT_PORT               = "8081"
    SPRING_PROFILES_ACTIVE        = var.spring_profiles_active
    TRACING_EXPORT_ENABLED        = "false"
  }
  secrets = {
    DB_USERNAME        = "${local.db_secret}:username::"
    DB_PASSWORD        = "${local.db_secret}:password::"
    JWT_SECRET         = module.secrets.jwt_secret_arn
    INTERNAL_API_TOKEN = module.secrets.internal_api_token_arn
  }
  health_check_command = "curl -fsS http://127.0.0.1:8081/actuator/health/liveness || exit 1"
  log_retention_days   = var.log_retention_days

  cluster_arn        = aws_ecs_cluster.this.arn
  desired_count      = var.incident_service_desired_count
  subnet_ids         = module.network.task_subnet_ids
  security_group_ids = [module.security_groups.incident_service_id]
  assign_public_ip   = module.network.task_assign_public_ip
  target_group_arn   = module.alb.target_group_arn
}

# The image's CMD runs "alembic upgrade head" before uvicorn; migrations/env.py serialises concurrent runs with
# a PostgreSQL advisory lock, so this is safe with several tasks. The one-off "migrate" task below lets the
# deploy workflow run (and check) the migrations explicitly before the services roll.
module "investigation_worker" {
  source = "../../modules/ecs_service"

  name                 = "investigation-worker"
  name_prefix          = local.name
  iam_path             = local.iam_path
  image                = local.worker_common.image
  ecr_repository_arn   = local.worker_common.ecr_repository_arn
  cpu                  = 512
  memory               = 1024 # ~500 MiB measured with both ONNX models loaded (k8s, section 3.5)
  container_ports      = [8000]
  environment          = local.worker_environment
  secrets              = local.worker_secrets
  health_check_command = "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/livez', timeout=3)\""
  log_retention_days   = var.log_retention_days

  cluster_arn                    = aws_ecs_cluster.this.arn
  desired_count                  = var.worker_desired_count
  subnet_ids                     = local.worker_common.subnet_ids
  security_group_ids             = local.worker_common.security_group_ids
  assign_public_ip               = local.worker_common.assign_public_ip
  service_discovery_namespace_id = aws_service_discovery_private_dns_namespace.this.id
}

# One-off: alembic upgrade head (run by the deploy workflow before the services roll).
module "migrate" {
  source = "../../modules/ecs_service"

  name               = "migrate"
  name_prefix        = local.name
  iam_path           = local.iam_path
  image              = local.worker_common.image
  ecr_repository_arn = local.worker_common.ecr_repository_arn
  cpu                = 256
  memory             = 512
  command            = ["alembic", "upgrade", "head"]
  environment        = local.worker_environment
  secrets            = local.worker_secrets
  log_retention_days = var.log_retention_days
  create_service     = false
}

# One-off: load the synthetic evidence (embedding all chunks peaks above 1 GiB, hence 2 GiB).
module "ingest" {
  source = "../../modules/ecs_service"

  name               = "ingest"
  name_prefix        = local.name
  iam_path           = local.iam_path
  image              = local.worker_common.image
  ecr_repository_arn = local.worker_common.ecr_repository_arn
  cpu                = 1024
  memory             = 2048
  command            = ["python", "-m", "app.ingest"]
  environment        = local.worker_environment
  secrets            = local.worker_secrets
  log_retention_days = var.log_retention_days
  create_service     = false
}
