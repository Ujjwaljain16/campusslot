# Builds both images in parallel with one command. CI uses it, and so can a developer:
#   SHA=local docker buildx bake
variable "SHA" {
  default = "local"
}

variable "PREFIX" {
  default = "ghcr.io/ujjwaljain16/campusslot"
}

group "default" {
  targets = ["backend", "frontend"]
}

target "backend" {
  context    = "./backend"
  tags       = ["${PREFIX}-backend:${SHA}"]
  args       = { GIT_SHA = SHA }
  cache-from = ["type=gha,scope=backend"]
  cache-to   = ["type=gha,mode=max,scope=backend"]
}

target "frontend" {
  context    = "./frontend"
  tags       = ["${PREFIX}-frontend:${SHA}"]
  args       = { GIT_SHA = SHA }
  cache-from = ["type=gha,scope=frontend"]
  cache-to   = ["type=gha,mode=max,scope=frontend"]
}
