# Kafka for the demo: ONE apache/kafka broker (KRaft, broker + controller) as a Fargate service, plus a one-off
# task definition that creates the topics.
#
# DEMO ONLY: a single broker, replication factor 1, no TLS/auth, and EPHEMERAL storage (Fargate task storage):
# if the task is replaced, topics and unconsumed messages are lost (run the topics task again; incidents keep
# their outbox rows, but events already sent are gone). Deliberately not Amazon MSK, whose smallest cluster
# costs far more than this demo budget.
#
# Alternatives (not implemented here):
#   kafka_mode = "msk"           Amazon MSK / MSK Serverless: managed, multi-AZ, IAM auth. The production choice.
#   kafka_mode = "sqs"           Replace Kafka with SQS (+ DLQ): cheapest managed option, but needs code changes
#                                (outbox relay and consumer) and loses per-key ordering unless FIFO queues are used.
#   EFS-backed broker storage    Survives task restarts, adds EFS cost and latency; still a single broker.

locals {
  bootstrap_servers = "kafka.${var.namespace_name}:9092"
  image             = "apache/kafka:4.1.0" # same image as compose.yaml and k8s/ (Docker Hub)
}

module "broker" {
  source = "../ecs_service"

  name        = "kafka"
  name_prefix = var.name_prefix
  iam_path    = var.iam_path
  image       = local.image
  cpu         = 512
  memory      = 1024
  # The image's entrypoint writes the generated server.properties into /opt/kafka/config, so the root
  # filesystem cannot be read-only here (on Kubernetes an initContainer copies the config to a volume).
  readonly_root_filesystem = false
  container_ports          = [9092]
  environment = {
    CLUSTER_ID                                     = "5L6g3nShT-eMCtK--X86sw"
    KAFKA_NODE_ID                                  = "1"
    KAFKA_PROCESS_ROLES                            = "broker,controller"
    KAFKA_LISTENERS                                = "PLAINTEXT://:9092,CONTROLLER://:9093"
    KAFKA_ADVERTISED_LISTENERS                     = "PLAINTEXT://${local.bootstrap_servers}" # Cloud Map name
    KAFKA_LISTENER_SECURITY_PROTOCOL_MAP           = "CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT"
    KAFKA_INTER_BROKER_LISTENER_NAME               = "PLAINTEXT"
    KAFKA_CONTROLLER_LISTENER_NAMES                = "CONTROLLER"
    KAFKA_CONTROLLER_QUORUM_VOTERS                 = "1@localhost:9093"
    KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR         = "1"
    KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR = "1"
    KAFKA_TRANSACTION_STATE_LOG_MIN_ISR            = "1"
    KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS         = "0"
    KAFKA_AUTO_CREATE_TOPICS_ENABLE                = "false"
    KAFKA_LOG_DIRS                                 = "/var/lib/kafka/data"
    KAFKA_HEAP_OPTS                                = "-Xms512m -Xmx512m"
  }
  log_retention_days = var.log_retention_days

  cluster_arn                        = var.cluster_arn
  desired_count                      = 1
  deployment_minimum_healthy_percent = 0 # a single broker: stop the old one before starting the new one
  subnet_ids                         = var.subnet_ids
  security_group_ids                 = [var.security_group_id]
  assign_public_ip                   = var.assign_public_ip
  service_discovery_namespace_id     = var.namespace_id
}

# One-off: aws ecs run-task --task-definition <family> (idempotent: --if-not-exists).
module "topics" {
  source = "../ecs_service"

  name               = "kafka-topics"
  name_prefix        = var.name_prefix
  iam_path           = var.iam_path
  image              = local.image
  cpu                = 256
  memory             = 512
  create_service     = false
  log_retention_days = var.log_retention_days
  environment        = { LOG_DIR = "/tmp" }
  command = ["sh", "-c", join(" && ", [
    "until /opt/kafka/bin/kafka-topics.sh --bootstrap-server ${local.bootstrap_servers} --list >/dev/null 2>&1; do echo waiting for kafka; sleep 3; done",
    "/opt/kafka/bin/kafka-topics.sh --bootstrap-server ${local.bootstrap_servers} --create --if-not-exists --topic incident-events --partitions 3 --replication-factor 1",
    "/opt/kafka/bin/kafka-topics.sh --bootstrap-server ${local.bootstrap_servers} --create --if-not-exists --topic incident-events.DLQ --partitions 3 --replication-factor 1",
    "/opt/kafka/bin/kafka-topics.sh --bootstrap-server ${local.bootstrap_servers} --describe --topic incident-events",
  ])]
}
