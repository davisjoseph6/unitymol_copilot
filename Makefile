
.PHONY: info

info:
	clear
	@printf "\ninfo:: Experimentations with UnityMol copilot\n\n"
	@printf "info:: common targets: purge, run\n\n"
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
	uv run agent.py)

