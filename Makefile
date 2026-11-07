.PHONY: up down logs test test-host venv

up:            ## build and start the service in the background
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

test:          ## run the tests inside the container
	docker compose run --rm test

venv:          ## a host venv with the pinned packages
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

test-host:     ## run the tests on the host (make venv first)
	.venv/bin/python -m pytest -q
