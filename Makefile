.PHONY: test lint run migrate coverage

test:
	uv run coverage run manage.py test tests --settings=config.settings.test
	uv run coverage report --fail-under=100

coverage: test

lint:
	uv run ruff check .
	uv run ruff format --check .

run:
	uv run manage.py runserver

migrate:
	uv run manage.py migrate
