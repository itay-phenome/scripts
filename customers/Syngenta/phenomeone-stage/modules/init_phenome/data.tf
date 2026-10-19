data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "secret_policy" {
  statement {
    sid    = "AllowReadSecret"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = local.secret_principals
    }

    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret"
    ]

    resources = ["*"]
  }
}
