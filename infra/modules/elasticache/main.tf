# OPTIONAL (milestone 4): ElastiCache for incident-service's investigation cache and per-tenant rate limit.
# Off by default in envs/demo (enable_redis = false): incident-service then runs with the cache and the rate limit
# switched off, which it supports by design (the same code path as "Redis down": fail open).
#
# One node, no replica, no snapshots: it holds only a cache and one-minute counters, all rebuildable.
# Engine: Valkey by default (the open-source Redis fork AWS offers at a lower node price than Redis OSS);
# incident-service uses only GET/SET/EVAL/INCR/EXPIRE, which both engines speak identically.
# TLS in transit + encryption at rest; the apps connect with SPRING_DATA_REDIS_SSL_ENABLED=true.
# Reachable only from the given application security groups (6379), never from the internet.

resource "aws_security_group" "this" {
  name        = "${var.name}-redis"
  description = "ElastiCache: only incident-service may connect"
  vpc_id      = var.vpc_id
  tags        = { Name = "${var.name}-redis" }
}

resource "aws_vpc_security_group_ingress_rule" "from_apps" {
  for_each = toset(var.client_security_group_ids)

  security_group_id            = aws_security_group.this.id
  description                  = "Redis/Valkey (TLS) from incident-service"
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
}

# The application security groups allow only listed egress (modules/security_groups): open 6379 to the cache.
resource "aws_vpc_security_group_egress_rule" "apps_to_cache" {
  for_each = toset(var.client_security_group_ids)

  security_group_id            = each.value
  description                  = "Redis/Valkey (TLS) to ElastiCache"
  referenced_security_group_id = aws_security_group.this.id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
}

resource "aws_elasticache_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids
}

#trivy:ignore:AVD-AWS-0050 No snapshots: the cache holds only rebuildable data (finished investigations, 1-minute counters).
resource "aws_elasticache_replication_group" "this" {
  replication_group_id = var.name
  description          = "incident-service cache and rate limit (${var.name})"

  engine               = var.engine
  engine_version       = var.engine_version
  node_type            = var.node_type
  num_cache_clusters   = 1 # no replica: losing the node only empties the cache (the app fails open)
  port                 = 6379
  parameter_group_name = var.parameter_group_name

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.this.id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true

  automatic_failover_enabled = false
  multi_az_enabled           = false
  snapshot_retention_limit   = 0
  auto_minor_version_upgrade = true
  apply_immediately          = true
}
