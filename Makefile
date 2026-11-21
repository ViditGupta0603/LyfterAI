# Run from Git Bash / WSL / macOS / Linux. Without make, see README "Run locally".
COMPOSE := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose")

.PHONY: up down logs ps restart test clean check-env

up: check-env ## Build and start backend (:8000) + frontend (:3000)
	$(COMPOSE) up -d --build
	@echo ""
	@echo "Frontend: http://localhost:3000"
	@echo "Backend:  http://localhost:8000/health"

down: ## Stop containers (data volume is kept)
	$(COMPOSE) down

logs: ## Follow logs of both services
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

restart: down up

test: ## Run the backend test suite inside Docker
	docker build --target test -t lyftr-backend-test ./backend
	docker run --rm lyftr-backend-test

clean: ## Stop containers AND delete the data volume (history + cache)
	$(COMPOSE) down -v

check-env:
	@test -f .env || { echo "Missing .env: copy .env.example to .env and add your API keys."; exit 1; }
