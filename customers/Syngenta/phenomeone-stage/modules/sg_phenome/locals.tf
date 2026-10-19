locals {
  web_sg_name           = "${var.name}-${var.env}-web-sg"
  db_sg_name            = "${var.name}-${var.env}-db-sg"
  alb_sg_name           = "${var.name}-${var.env}-alb-sg"
  vpc_endpoints_sg_name = "${var.name}-${var.env}-vpc-endpoints-sg"

  internet_cidrs = ["0.0.0.0/0"]
  vpc_cidrs      = [data.aws_vpc.existing.cidr_block]

  ssh_cidrs = [
    "172.16.0.0/12",
    "192.168.0.0/16"
  ]
}
