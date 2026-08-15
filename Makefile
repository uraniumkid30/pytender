.PHONY: test lint typecheck quality bench build clean

test:
	pytest --cov=moneytender --cov-report=term-missing

lint:
	ruff check .
	ruff format --check .

typecheck:
	mypy src/moneytender

quality: lint typecheck test

bench:
	pytest benchmarks --benchmark-only --benchmark-sort=mean

build:
	python -m build
	twine check dist/*

clean:
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage *.egg-info src/*.egg-info
