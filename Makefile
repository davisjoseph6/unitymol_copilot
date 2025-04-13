
.PHONY: info

info:
	clear
	@printf "\ninfo:: Experimentations with UnityMol copilot\n\n"
	@printf "info:: common targets: purge, run, test\n\n"
	@/bin/ls -GF
	@printf "\n"
	@git status

purge:
	$(info )
	$(info info:: cleaning common clutter)
	@rm -rf __pycache__

run:
	$(info )
	$(info info:: start up copilot)
	@( source ~/.venv/myenv/bin/activate ; \
	python3 main.py --host localhost --port 5555 --model deepseek-coder-v2:16b)

test:
	$(info )
	$(info info:: perform test on copilot)
	@( source ~/.venv/myenv/bin/activate ; \
	python3 test.py)

