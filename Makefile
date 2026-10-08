COMPOSE = docker compose -f deploy/docker-compose.yml

.PHONY: up down logs ps config test lint backup clean-services

up:  ## build and start the whole platform
	$(COMPOSE) up -d --build

down:  ## stop the platform (monitored services keep running)
	$(COMPOSE) down

logs:  ## follow the control plane logs
	$(COMPOSE) logs -f --tail=100 sentinel

ps:
	$(COMPOSE) ps

config:  ## validate the compose file
	$(COMPOSE) config -q

test:
	python -m pytest -q

lint:
	ruff check controlplane samples tests panel sentinel benchmark evaluation

backup:  ## copy the SQLite database and service repos
	mkdir -p backups
	tar czf backups/sentinel-$$(date +%Y%m%d-%H%M%S).tgz -C /srv/sentinel .

clean-services:  ## remove every container the platform started for monitored services
	docker ps -aq --filter label=sentinel.monitor=true | xargs -r docker rm -f
