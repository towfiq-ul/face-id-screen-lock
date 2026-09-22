# =============================================================================
# FaceLock - Automated Screen Lock & Face ID Daemon
# =============================================================================

SHELL            := /usr/bin/env bash
.DEFAULT_GOAL    := help
.DELETE_ON_ERROR :

PYTHON           ?= python3
VENV             := .venv
VENV_BIN         := $(abspath $(VENV)/bin)
UNIT_NAME        := facelock-monitor.service
UNIT_DIR         := $(HOME)/.config/systemd/user
MONITOR_PID_FILE := .facelock-monitor.pid
GUI_PID_FILE     := .facelock-gui.pid
MONITOR_LOG_FILE := facelock-monitor.log
GUI_LOG_FILE     := facelock-gui.log
PYTEST_ARGS      ?= -v
NAME             ?=

.PHONY: help venv start stop restart status run gui calibrate info \
        test-face test-face-cli verify enroll remove-face \
        pam-status pam-enable pam-disable \
        test check lint format \
        service-install service-uninstall service-start service-stop service-restart service-status service-logs \
        desktop-install desktop-uninstall install uninstall \
        macos-install macos-uninstall \
        clean clean-logs

##@ 🚀 Help & Diagnostics
help: ## Display this organized help menu
	@awk 'BEGIN {FS = ":.*##"; printf "\n\033[1;36mFaceLock\033[0m - Modern Biometric Lock & Face ID Assistant\n\n\033[1;33mUsage:\033[0m make \033[32m<target>\033[0m [VARIABLE=value]\n"} \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } \
		/^[a-zA-Z0-9_.-]+:.*?##/ { printf "  \033[32m%-22s\033[0m %s\n", $$1, $$2 } \
		END { printf "\n" }' $(MAKEFILE_LIST)

info: ## Display environment info, video devices, and FaceLock status
	@printf "\n\033[1;36mFaceLock Environment & System Info\033[0m\n"
	@printf "  \033[1mSystem Python:\033[0m   %s\n" "$$($(PYTHON) --version 2>&1 || echo 'Not found')"
	@if [ -d "$(VENV)" ]; then \
		printf "  \033[1mVenv Path:\033[0m       $(VENV) ($$($(VENV_BIN)/python --version 2>&1))\n"; \
	else \
		printf "  \033[1mVenv Path:\033[0m       \033[33mNot initialized\033[0m (run 'make venv')\n"; \
	fi
	@printf "  \033[1mVideo Devices:\033[0m   "
	@if ls /dev/video* >/dev/null 2>&1; then \
		ls -d /dev/video* | tr '\n' ' '; echo ""; \
	else \
		printf "\033[33mNo /dev/video* devices found\033[0m\n"; \
	fi
	@printf "  \033[1mDisplay Server:\033[0m  %s (Session: %s)\n\n" "$${DISPLAY:-none}" "$${XDG_SESSION_TYPE:-unknown}"
	@$(MAKE) --no-print-directory status

##@ 🎮 Application Runtime
start: venv ## Start GUI and background monitor daemon locally
	@printf "\033[36m▶ Starting FaceLock application...\033[0m\n"
	@if [ -f $(MONITOR_PID_FILE) ] && kill -0 $$(cat $(MONITOR_PID_FILE)) 2>/dev/null; then \
		printf "  \033[32m●\033[0m Monitor Service is already running (PID: %s).\n" "$$(cat $(MONITOR_PID_FILE))"; \
	elif systemctl --user is-active $(UNIT_NAME) >/dev/null 2>&1; then \
		printf "  \033[32m●\033[0m Monitor Service is already running via systemd.\n"; \
	else \
		setsid $(VENV_BIN)/facelock-monitor </dev/null > $(MONITOR_LOG_FILE) 2>&1 & echo $$! > $(MONITOR_PID_FILE); \
		sleep 0.8; \
		if kill -0 $$(cat $(MONITOR_PID_FILE)) 2>/dev/null; then \
			printf "  \033[32m✓\033[0m Monitor Service started in background (PID: %s).\n" "$$(cat $(MONITOR_PID_FILE))"; \
			printf "    Log: %s\n" "$(MONITOR_LOG_FILE)"; \
		else \
			printf "  \033[31m❌\033[0m Monitor Service failed to start. Last log output:\n"; \
			tail -n 10 $(MONITOR_LOG_FILE) 2>/dev/null || true; \
			rm -f $(MONITOR_PID_FILE); \
		fi; \
	fi
	@if [ -f $(GUI_PID_FILE) ] && kill -0 $$(cat $(GUI_PID_FILE)) 2>/dev/null; then \
		printf "  \033[32m●\033[0m GUI is already running (PID: %s).\n" "$$(cat $(GUI_PID_FILE))"; \
	elif pgrep -x facelock-gui >/dev/null 2>&1; then \
		printf "  \033[32m●\033[0m GUI is already running.\n"; \
	else \
		setsid $(VENV_BIN)/facelock-gui </dev/null > $(GUI_LOG_FILE) 2>&1 & echo $$! > $(GUI_PID_FILE); \
		sleep 0.8; \
		if kill -0 $$(cat $(GUI_PID_FILE)) 2>/dev/null; then \
			printf "  \033[32m✓\033[0m GUI launched (PID: %s).\n" "$$(cat $(GUI_PID_FILE))"; \
		else \
			printf "  \033[31m❌\033[0m GUI failed to launch. Last log output:\n"; \
			tail -n 10 $(GUI_LOG_FILE) 2>/dev/null || true; \
			rm -f $(GUI_PID_FILE); \
		fi; \
	fi
	@printf "Stop anytime: \033[33mmake stop\033[0m\n"

stop: ## Stop GUI and background monitor daemon locally
	@printf "\033[33m⏹ Stopping FaceLock application...\033[0m\n"
	@GUI_STOPPED=0; \
	if [ -f $(GUI_PID_FILE) ]; then \
		PID=$$(cat $(GUI_PID_FILE)); \
		if [ -n "$$PID" ] && kill -0 $$PID 2>/dev/null; then \
			kill -TERM $$PID 2>/dev/null || true; \
			GUI_STOPPED=1; \
		fi; \
		rm -f $(GUI_PID_FILE); \
	fi; \
	if pgrep -x facelock-gui >/dev/null 2>&1; then \
		pkill -x facelock-gui 2>/dev/null || true; \
		GUI_STOPPED=1; \
	fi; \
	if [ $$GUI_STOPPED -eq 1 ]; then \
		printf "  \033[32m✓\033[0m FaceLock GUI stopped.\n"; \
	else \
		printf "  \033[2m○ FaceLock GUI was not running.\033[0m\n"; \
	fi
	@MON_STOPPED=0; \
	if [ -f $(MONITOR_PID_FILE) ]; then \
		PID=$$(cat $(MONITOR_PID_FILE)); \
		if [ -n "$$PID" ] && kill -0 $$PID 2>/dev/null; then \
			kill -TERM $$PID 2>/dev/null || true; \
			for i in 1 2 3 4 5; do \
				if ! kill -0 $$PID 2>/dev/null; then break; fi; \
				sleep 0.3; \
			done; \
			if kill -0 $$PID 2>/dev/null; then kill -9 $$PID 2>/dev/null || true; fi; \
			MON_STOPPED=1; \
		fi; \
		rm -f $(MONITOR_PID_FILE); \
	fi; \
	if pgrep -x facelock-monitor >/dev/null 2>&1; then \
		pkill -x facelock-monitor 2>/dev/null || true; \
		MON_STOPPED=1; \
	fi; \
	if systemctl --user is-active $(UNIT_NAME) >/dev/null 2>&1; then \
		systemctl --user stop $(UNIT_NAME) 2>/dev/null || true; \
		MON_STOPPED=1; \
	fi; \
	if [ $$MON_STOPPED -eq 1 ]; then \
		printf "  \033[32m✓\033[0m FaceLock monitor service stopped.\n"; \
	else \
		printf "  \033[2m○ FaceLock monitor service was not running.\033[0m\n"; \
	fi

restart: ## Restart GUI and background monitor daemon
	@$(MAKE) --no-print-directory stop
	@sleep 0.5
	@$(MAKE) --no-print-directory start

status: ## Show runtime status of GUI, daemon, and PID files
	@printf "\033[1;36mFaceLock Application Status:\033[0m\n"
	@if [ -f $(GUI_PID_FILE) ] && kill -0 $$(cat $(GUI_PID_FILE)) 2>/dev/null; then \
		printf "  \033[32m●\033[0m GUI: \033[1;32mRUNNING\033[0m (PID: %s)\n" "$$(cat $(GUI_PID_FILE))"; \
	elif pgrep -x facelock-gui >/dev/null 2>&1; then \
		printf "  \033[32m●\033[0m GUI: \033[1;32mRUNNING\033[0m (PID: %s)\n" "$$(pgrep -x facelock-gui | head -n1)"; \
	else \
		printf "  \033[2m○ GUI: STOPPED\033[0m\n"; \
	fi
	@if [ -f $(MONITOR_PID_FILE) ] && kill -0 $$(cat $(MONITOR_PID_FILE)) 2>/dev/null; then \
		printf "  \033[32m●\033[0m Monitor Service: \033[1;32mRUNNING locally\033[0m (PID: %s)\n" "$$(cat $(MONITOR_PID_FILE))"; \
	elif systemctl --user is-active $(UNIT_NAME) >/dev/null 2>&1; then \
		printf "  \033[32m●\033[0m Monitor Service: \033[1;32mRUNNING via systemd --user\033[0m\n"; \
	elif pgrep -x facelock-monitor >/dev/null 2>&1; then \
		printf "  \033[32m●\033[0m Monitor Service: \033[1;32mRUNNING\033[0m (PID: %s)\n" "$$(pgrep -x facelock-monitor | head -n1)"; \
	else \
		printf "  \033[2m○ Monitor Service: STOPPED\033[0m\n"; \
	fi

run: venv ## Run monitor daemon in foreground
	$(VENV_BIN)/facelock-monitor

gui: venv ## Launch graphical face setup wizard with live HUD
	$(VENV_BIN)/facelock-gui

calibrate: venv ## Launch camera diagnostic and biometric calibration assistant
	$(VENV_BIN)/facelock-calibrate

##@ 👤 Face Biometrics & Profile Management
enroll: venv ## Enroll face profile via terminal (CLI mode)
	$(VENV_BIN)/facelock-enroll

remove-face: venv ## Remove saved face profile (interactive or NAME=...)
	$(VENV_BIN)/facelock-remove $(NAME)

test-face: venv ## Test live camera face against saved profile (interactive HUD)
	$(VENV_BIN)/facelock-test

test-face-cli: venv ## Test live camera face against saved profile in terminal mode
	$(VENV_BIN)/facelock-test --no-gui

verify: test-face ## Alias for test-face

##@ 🔒 PAM Screen Lock Authentication
pam-status: venv ## Check status of PAM lock-screen face unlock
	$(VENV_BIN)/facelock-pam status

pam-enable: venv ## Enable FaceLock PAM unlock for lock screen (Super+L)
	sudo $(VENV_BIN)/facelock-pam enable

pam-disable: venv ## Disable FaceLock PAM unlock (restore default password)
	sudo $(VENV_BIN)/facelock-pam disable

##@ 🧪 Testing & Code Quality
test: venv ## Run automated unit test suite with pytest
	@if [ -x "$(VENV_BIN)/pytest" ]; then \
		$(VENV_BIN)/pytest $(PYTEST_ARGS) tests; \
	else \
		$(VENV_BIN)/python -m unittest discover -s tests; \
	fi

check: lint test ## Run both lint checks and the automated test suite
	@printf "\033[1;32m✓ All quality checks passed successfully.\033[0m\n"

lint: venv ## Check syntax and byte-compile all Python modules
	@$(VENV_BIN)/python -m compileall -q facelock tests packaging
	@printf "\033[32m✓ All Python modules compiled cleanly.\033[0m\n"

format: venv ## Auto-format code using ruff or black (if installed)
	@if [ -x "$(VENV_BIN)/ruff" ]; then \
		$(VENV_BIN)/ruff format facelock tests packaging; \
	elif [ -x "$(VENV_BIN)/black" ]; then \
		$(VENV_BIN)/black facelock tests packaging; \
	elif command -v ruff >/dev/null 2>&1; then \
		ruff format facelock tests packaging; \
	elif command -v black >/dev/null 2>&1; then \
		black facelock tests packaging; \
	else \
		printf "\033[33mNotice: Neither ruff nor black is installed. Run 'make lint' to verify syntax.\033[0m\n"; \
	fi

##@ ⚙️ Systemd User Service
service-install: venv ## Install & enable systemd --user service (repo-local)
	mkdir -p $(UNIT_DIR)
	sed 's|@VENV_BIN@|$(VENV_BIN)|' packaging/$(UNIT_NAME) > $(UNIT_DIR)/$(UNIT_NAME)
	systemctl --user daemon-reload
	systemctl --user enable --now $(UNIT_NAME)
	@printf "\033[32m✓ Service $(UNIT_NAME) installed and enabled.\033[0m\n"

service-uninstall: ## Disable & remove systemd --user service
	-systemctl --user disable --now $(UNIT_NAME) 2>/dev/null || true
	rm -f $(UNIT_DIR)/$(UNIT_NAME)
	systemctl --user daemon-reload
	@printf "\033[32m✓ Service $(UNIT_NAME) uninstalled.\033[0m\n"

service-start: ## Start the user service
	systemctl --user start $(UNIT_NAME)

service-stop: ## Stop the user service
	systemctl --user stop $(UNIT_NAME)

service-restart: ## Restart the user service
	systemctl --user restart $(UNIT_NAME)

service-status: ## Show systemd service status
	systemctl --user status $(UNIT_NAME)

service-logs: ## Follow real-time service logs in journalctl
	journalctl --user -u $(UNIT_NAME) -f

##@ 📦 Setup, Packaging & Maintenance
venv: ## Create virtual environment and install package in editable mode
	@if [ ! -d "$(VENV)" ] || [ ! -f "$(VENV_BIN)/facelock-monitor" ]; then \
		printf "\033[36mSetting up Python virtual environment in $(VENV)...\033[0m\n"; \
		$(PYTHON) -m venv $(VENV); \
		$(VENV_BIN)/pip install -e ".[test]"; \
		printf "\033[32m✓ Environment ready in $(VENV)\033[0m\n"; \
	fi

desktop-install: venv ## Install .desktop launcher and icons for current user
	$(VENV_BIN)/python packaging/install_desktop.py --install --user

desktop-uninstall: venv ## Remove .desktop launcher and icons for current user
	$(VENV_BIN)/python packaging/install_desktop.py --uninstall --user

install: ## Install system-wide via install.sh (/opt/facelock)
	sudo ./install.sh

uninstall: ## Uninstall system-wide installation
	@if [ -f /opt/facelock/uninstall.sh ]; then \
		sudo /opt/facelock/uninstall.sh; \
	else \
		printf "\033[31mNo /opt/facelock/uninstall.sh found.\033[0m\n"; \
	fi

macos-install: ## Install FaceLock on macOS with launchd LaunchAgent
	./install_macos.sh

macos-uninstall: ## Uninstall FaceLock on macOS
	@if [ -f $(HOME)/.local/opt/facelock/uninstall.sh ]; then \
		$(HOME)/.local/opt/facelock/uninstall.sh; \
	else \
		printf "\033[31mNo ~/.local/opt/facelock/uninstall.sh found.\033[0m\n"; \
	fi

clean: ## Remove venv, build artifacts, and cache files
	rm -rf $(VENV) facelock.egg-info build dist .pytest_cache .coverage htmlcov
	rm -f .facelock*.pid facelock*.log *.pid *.log
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@printf "\033[32m✓ Cleaned build artifacts, caches, and virtual environment.\033[0m\n"

clean-logs: ## Clean runtime logs and PID files without removing virtual environment
	rm -f .facelock*.pid facelock*.log *.pid *.log
	@printf "\033[32m✓ Cleaned runtime logs and PID files.\033[0m\n"
