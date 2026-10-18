# Zuschlag.ai developer shortcuts. The full toolchain lives in package.json / pyproject.toml.

COMPOSE := docker compose -f docker-compose.yml -f docker-compose.demo.yml --profile app

.PHONY: demo demo-logs demo-down test

## demo: boot the stack + mock SAP, seed SAP master data, run the RFQ pipeline, print the URL
demo: .env
	$(COMPOSE) up -d --build --wait
	$(COMPOSE) --profile demo run --rm demo

## demo-logs: follow the API and mock SAP logs (personal data is masked)
demo-logs:
	$(COMPOSE) logs -f api mock-sap

## demo-down: stop the demo stack (add `-v` via DOWN_FLAGS=-v to drop its data)
demo-down:
	$(COMPOSE) --profile demo down $(DOWN_FLAGS)

## test: API and web test suites (API integration tests need TEST_DATABASE_URL)
test:
	pnpm test

.env:
	python3 infra/demo/make_env.py
