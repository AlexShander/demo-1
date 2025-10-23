resource "aws_lb" "this" {
  name               = var.alb_name
  load_balancer_type = "application"
  security_groups    = [var.alb_sg_id]
  subnets            = var.public_subnets

  tags = merge({
    Name = var.alb_name
  }, var.tags)
}

resource "aws_lb_target_group" "this" {
  name        = "${var.alb_name}-tg"
  port        = var.target_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "instance"

  health_check {
    path = var.health_check_path
  }

  tags = merge({
    Name = "${var.alb_name}-tg"
  }, var.tags)
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }

  tags = merge({
    Name = "${var.alb_name}-listener"
  }, var.tags)

  depends_on = [aws_lb.this]
}
