.PHONY: install format lint test

install:
\tpip install -e .

format:
\tblack romulus_core scripts tests

lint:
\truff check romulus_core scripts tests

test:
\tpytest -q

