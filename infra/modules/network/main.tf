# VPC across two Availability Zones: public subnets (ALB, and the Fargate tasks when there is no NAT gateway)
# and private subnets (RDS; the Fargate tasks too when enable_nat_gateway = true).
#
# NAT trade-off (enable_nat_gateway):
#   false (default, cheapest): no NAT gateway. Fargate tasks still need outbound HTTPS (pull images from ECR,
#     read Secrets Manager, ship logs, call the Claude API), so they run in the PUBLIC subnets with a public IP.
#     Their security groups allow NO inbound traffic except from the chained security groups (ALB -> API ->
#     worker), and outbound only on the ports they need. RDS stays in the private subnets either way.
#   true: one NAT gateway (single AZ, demo) and all tasks move to the private subnets without public IPs.
#     Costs an hourly charge plus per-GB processing (see infra/README.md); production would use one per AZ.
#   (VPC interface endpoints for ECR/Secrets Manager/Logs would avoid both, but cost more than one NAT here.)

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)
}

#trivy:ignore:AVD-AWS-0178 VPC flow logs off for the demo (cost); enable them (to CloudWatch or S3) in production.
resource "aws_vpc" "this" {
  cidr_block           = var.cidr_block
  enable_dns_support   = true
  enable_dns_hostnames = true # Cloud Map private DNS names (kafka.<namespace>) need both

  tags = { Name = var.name }
}

# No rules: nothing can use the VPC's default security group by accident.
resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id

  tags = { Name = "${var.name}-default-unused" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = { Name = var.name }
}

resource "aws_subnet" "public" {
  count = var.az_count

  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.cidr_block, 8, count.index)
  availability_zone = local.azs[count.index]
  # Public IPs are requested explicitly per ECS service (assign_public_ip), never by default.
  map_public_ip_on_launch = false

  tags = { Name = "${var.name}-public-${local.azs[count.index]}", tier = "public" }
}

resource "aws_subnet" "private" {
  count = var.az_count

  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.cidr_block, 8, count.index + 10)
  availability_zone = local.azs[count.index]

  tags = { Name = "${var.name}-private-${local.azs[count.index]}", tier = "private" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = { Name = "${var.name}-public" }
}

resource "aws_route_table_association" "public" {
  count = var.az_count

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_eip" "nat" {
  count = var.enable_nat_gateway ? 1 : 0

  domain = "vpc"
  tags   = { Name = "${var.name}-nat" }
}

resource "aws_nat_gateway" "this" {
  count = var.enable_nat_gateway ? 1 : 0

  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id

  tags       = { Name = var.name }
  depends_on = [aws_internet_gateway.this]
}

# Private subnets get a default route only through the NAT gateway; without it they have no internet access.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  dynamic "route" {
    for_each = var.enable_nat_gateway ? [1] : []
    content {
      cidr_block     = "0.0.0.0/0"
      nat_gateway_id = aws_nat_gateway.this[0].id
    }
  }

  tags = { Name = "${var.name}-private" }
}

resource "aws_route_table_association" "private" {
  count = var.az_count

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}
