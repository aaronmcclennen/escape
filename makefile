ifndef VERMUTEN_CONFIG
override VERMUTEN_CONFIG = demo.json
endif

test:
	python3 -m unittest discover -s tests -p "*test*.py"

run: test
	export VERMUTEN_CONFIG=$(VERMUTEN_CONFIG) && gunicorn app:app

win-run: test
	set VERMUTEN_CONFIG=$(VERMUTEN_CONFIG) && waitress-serve --listen="127.0.0.1:5000" app:app

apply-formatting:
	black ./