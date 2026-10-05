terraform {
  required_version = ">= 1.5.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.59"
    }
  }
}

provider "aws" {
  region = var.region

  # Every resource created by this configuration carries these tags, which makes leftovers
  # easy to find in the console and in Cost Explorer after a destroy.
  default_tags {
    tags = {
      Project   = "campusslot"
      ManagedBy = "terraform"
      Purpose   = "devops-capstone"
    }
  }
}
