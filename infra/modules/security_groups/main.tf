# Chained security groups: internet -> ALB -> incident-service -> investigation-worker, and Postgres / Kafka
# reachable only from the application tasks. Every rule is a separate resource so it is explicit and reviewable.
#
#   ALB               in: 80 (+443 with a certificate) from the internet      out: 8080 to incident-service
#   incident-service  in: 8080 from the ALB                                    out: 8000 worker, 5432 RDS, 9092 Kafka, 443 AWS APIs
#   worker            in: 8000 from incident-service only                     out: 5432 RDS, 9092 Kafka, 443 AWS APIs + Claude
#   kafka             in: 9092 from incident-service, worker, itself          out: 443 (image pull, logs)
#   rds               in: 5432 from incident-service and worker               out: none

resource "aws_security_group" "alb" {
  name        = "${var.name}-alb"
  description = "Public ALB in front of incident-service"
  vpc_id      = var.vpc_id
  tags        = { Name = "${var.name}-alb" }
}

resource "aws_security_group" "incident_service" {
  name        = "${var.name}-incident-service"
  description = "incident-service tasks: only the ALB may connect"
  vpc_id      = var.vpc_id
  tags        = { Name = "${var.name}-incident-service" }
}

resource "aws_security_group" "worker" {
  name        = "${var.name}-investigation-worker"
  description = "investigation-worker tasks: internal API only from incident-service"
  vpc_id      = var.vpc_id
  tags        = { Name = "${var.name}-investigation-worker" }
}

resource "aws_security_group" "kafka" {
  name        = "${var.name}-kafka"
  description = "Single Kafka broker task: only the application tasks may connect"
  vpc_id      = var.vpc_id
  tags        = { Name = "${var.name}-kafka" }
}

resource "aws_security_group" "rds" {
  name        = "${var.name}-rds"
  description = "PostgreSQL: only the application tasks may connect"
  vpc_id      = var.vpc_id
  tags        = { Name = "${var.name}-rds" }
}

# ---------------------------------------------------------------- ALB

# Accepted risk: Public, internet-facing API: the ALB must accept HTTP from anywhere (redirected to HTTPS when a certificate is set).
resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP from the internet (redirect to HTTPS when a certificate is configured)"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

# Accepted risk: Public, internet-facing API over HTTPS.
resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  count = var.enable_https ? 1 : 0

  security_group_id = aws_security_group.alb.id
  description       = "HTTPS from the internet"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "alb_to_incident_service" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Forward to incident-service"
  referenced_security_group_id = aws_security_group.incident_service.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}

# ---------------------------------------------------------------- incident-service

resource "aws_vpc_security_group_ingress_rule" "incident_service_from_alb" {
  security_group_id            = aws_security_group.incident_service.id
  description                  = "API traffic from the ALB only"
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}

resource "aws_vpc_security_group_egress_rule" "incident_service_to_worker" {
  security_group_id            = aws_security_group.incident_service.id
  description                  = "Investigation read API"
  referenced_security_group_id = aws_security_group.worker.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

# ---------------------------------------------------------------- worker

resource "aws_vpc_security_group_ingress_rule" "worker_from_incident_service" {
  security_group_id            = aws_security_group.worker.id
  description                  = "Internal read API from incident-service only"
  referenced_security_group_id = aws_security_group.incident_service.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

# ---------------------------------------------------------------- shared egress of the application tasks

locals {
  app_security_groups = {
    incident_service = aws_security_group.incident_service.id
    worker           = aws_security_group.worker.id
  }
  # Every task pulls its image and reads its secrets over HTTPS (ECR, Secrets Manager, CloudWatch Logs); the
  # worker also calls the Claude API. Kafka pulls its image from Docker Hub.
  https_egress_security_groups = merge(local.app_security_groups, { kafka = aws_security_group.kafka.id })
}

resource "aws_vpc_security_group_egress_rule" "app_to_rds" {
  for_each = local.app_security_groups

  security_group_id            = each.value
  description                  = "PostgreSQL"
  referenced_security_group_id = aws_security_group.rds.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_egress_rule" "app_to_kafka" {
  for_each = local.app_security_groups

  security_group_id            = each.value
  description                  = "Kafka"
  referenced_security_group_id = aws_security_group.kafka.id
  ip_protocol                  = "tcp"
  from_port                    = 9092
  to_port                      = 9092
}

# Accepted risk: HTTPS-only egress to AWS APIs (ECR, Secrets Manager, Logs), Docker Hub and the Claude API; their IP ranges are not fixed. Production: NAT/egress proxy or VPC endpoints.
resource "aws_vpc_security_group_egress_rule" "https_out" {
  for_each = local.https_egress_security_groups

  security_group_id = each.value
  description       = "HTTPS to AWS APIs, image registries and the LLM API"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

# ---------------------------------------------------------------- kafka

resource "aws_vpc_security_group_ingress_rule" "kafka_from_apps" {
  for_each = merge(local.app_security_groups, { kafka = aws_security_group.kafka.id })

  security_group_id            = aws_security_group.kafka.id
  description                  = "Kafka clients (the topic-creation task runs with the kafka group)"
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 9092
  to_port                      = 9092
}

# The broker connects to itself through its advertised listener (admin tools, the topics task).
resource "aws_vpc_security_group_egress_rule" "kafka_to_itself" {
  security_group_id            = aws_security_group.kafka.id
  description                  = "Broker to its own advertised listener"
  referenced_security_group_id = aws_security_group.kafka.id
  ip_protocol                  = "tcp"
  from_port                    = 9092
  to_port                      = 9092
}

# ---------------------------------------------------------------- rds (no egress rules at all)

resource "aws_vpc_security_group_ingress_rule" "rds_from_apps" {
  for_each = local.app_security_groups

  security_group_id            = aws_security_group.rds.id
  description                  = "PostgreSQL from the application tasks"
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
