PYTHON ?= python3
VENV := .venv
VENV_BIN := $(abspath $(VENV)/bin)
UNIT_NAME := facelock-monitor.service
UNIT_DIR := $(HOME)/.config/systemd/user
MONITOR_PID_FILE := .facelock-monitor.pid
GUI_PID_FILE     := .facelock-gui.pid
MONITOR_LOG_FILE := facelock-monitor.log
GUI_LOG_FILE     := facelock-gui.log

.PHONY: help venv start stop status test test-face test-face-cli verify remove-face enroll gui calibrate run install uninstall \
        pam-status pam-enable pam-disable \
        service-install service-uninstall service-start service-stop service-restart service-status service-logs \
        desktop-install desktop-uninstall \
        lint clean

help:
	@echo "FaceLock Management Targets:"
	@echo "  make venv               Create virtual environment and install package"
	@echo "  make start              Start GUI and background services locally"
	@echo "  make stop               Stop GUI and background services locally"
	@echo "  make status             Show status of GUI and background services"
	@echo "  make run                Run monitor daemon in foreground"
	@echo "  make gui                Launch graphical face setup wizard with live HUD"
	@echo "  make calibrate          Launch camera diagnostic and biometric calibration assistant"
	@echo "  make test-face          Test live camera face against saved profile (interactive HUD)"
	@echo "  make test-face-cli      Test live camera face against saved profile in terminal mode"
	@echo "  make pam-status         Check status of PAM lock-screen face unlock"
	@echo "  make pam-enable         Enable FaceLock PAM unlock for lock screen (Super+L)"
	@echo "  make pam-disable        Disable FaceLock PAM unlock (restore default password)"
	@echo "  make enroll             Enroll face via terminal (CLI mode)"
	@echo "  make remove-face        Remove saved face profile (interactive menu or NAME=...)"
	@echo "  make test               Run automated unit test suite"
	@echo "  make lint               Check Python syntax and compile all modules"
	@echo "  make install            Install system-wide via install.sh (/opt/facelock)"
	@echo "  make uninstall          Uninstall system-wide installation"
	@echo "  make desktop-install    Install .desktop launcher and icons for current user"
	@echo "  make desktop-uninstall  Remove .desktop launcher and icons for current user"
	@echo "  make service-install    Install & enable systemd --user service (repo-local)"
	@echo "  make service-uninstall  Disable & remove systemd --user service"
	@echo "  make service-start      Start the user service"
	@echo "  make service-stop       Stop the user service"
	@echo "  make service-restart    Restart the user service"
	@echo "  make service-status     Show service status"
	@echo "  make service-logs       Follow real-time service logs in journalctl"
	@echo "  make clean              Remove venv, build artifacts, and cache files"

venv:
	@if [ ! -d "$(VENV)" ] || [ ! -f "$(VENV_BIN)/facelock-monitor" ]; then \
		$(PYTHON) -m venv $(VENV); \
		$(VENV_BIN)/pip install -e ".[test]"; \
	fi

test: venv
	$(VENV_BIN)/python -m unittest discover -s tests

test-face: venv
	$(VENV_BIN)/facelock-test

test-face-cli: venv
	$(VENV_BIN)/facelock-test --no-gui

verify: test-face

pam-status: venv
	$(VENV_BIN)/facelock-pam status

pam-enable: venv
	sudo $(VENV_BIN)/facelock-pam enable

pam-disable: venv
	sudo $(VENV_BIN)/facelock-pam disable

lint: venv
	$(VENV_BIN)/python -m compileall facelock tests

enroll: venv
	$(VENV_BIN)/facelock-enroll

remove-face: venv
	$(VENV_BIN)/facelock-remove $(NAME)

gui: venv
	$(VENV_BIN)/facelock-gui

calibrate: venv
	$(VENV_BIN)/facelock-calibrate

start: venv
	@echo "▶ Starting FaceLock application..."
	@if [ -f $(MONITOR_PID_FILE) ] && kill -0 $$(cat $(MONITOR_PID_FILE)) 2>/dev/null; then \
		echo "  ● Monitor Service is already running (PID: $$(cat $(MONITOR_PID_FILE)))."; \
	elif systemctl --user is-active $(UNIT_NAME) >/dev/null 2>&1; then \
		echo "  ● Monitor Service is already running via systemd."; \
	else \
		setsid $(VENV_BIN)/facelock-monitor </dev/null > $(MONITOR_LOG_FILE) 2>&1 & echo $$! > $(MONITOR_PID_FILE); \
		sleep 0.8; \
		if kill -0 $$(cat $(MONITOR_PID_FILE)) 2>/dev/null; then \
			echo "  ✓ Monitor Service started in background (PID: $$(cat $(MONITOR_PID_FILE)))."; \
			echo "    Log: $(MONITOR_LOG_FILE)"; \
		else \
			echo "  ❌ Monitor Service failed to start. Last log output:"; \
			tail -n 10 $(MONITOR_LOG_FILE) 2>/dev/null || true; \
			rm -f $(MONITOR_PID_FILE); \
		fi; \
	fi
	@if [ -f $(GUI_PID_FILE) ] && kill -0 $$(cat $(GUI_PID_FILE)) 2>/dev/null; then \
		echo "  ● GUI is already running (PID: $$(cat $(GUI_PID_FILE)))."; \
	elif pgrep -x facelock-gui >/dev/null 2>&1; then \
		echo "  ● GUI is already running."; \
	else \
		setsid $(VENV_BIN)/facelock-gui </dev/null > $(GUI_LOG_FILE) 2>&1 & echo $$! > $(GUI_PID_FILE); \
		sleep 0.8; \
		if kill -0 $$(cat $(GUI_PID_FILE)) 2>/dev/null; then \
			echo "  ✓ GUI launched (PID: $$(cat $(GUI_PID_FILE)))."; \
		else \
			echo "  ❌ GUI failed to launch. Last log output:"; \
			tail -n 10 $(GUI_LOG_FILE) 2>/dev/null || true; \
			rm -f $(GUI_PID_FILE); \
		fi; \
	fi
	@echo "Stop anytime: make stop"

stop:
	@echo "⏹ Stopping FaceLock application..."
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
		echo "  ✓ FaceLock GUI stopped."; \
	else \
		echo "  ○ FaceLock GUI was not running."; \
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
		echo "  ✓ FaceLock monitor service stopped."; \
	else \
		echo "  ○ FaceLock monitor service was not running."; \
	fi

status:
	@echo "FaceLock Application Status:"
	@if [ -f $(GUI_PID_FILE) ] && kill -0 $$(cat $(GUI_PID_FILE)) 2>/dev/null; then \
		echo "  ● GUI: RUNNING (PID: $$(cat $(GUI_PID_FILE)))"; \
	elif pgrep -x facelock-gui >/dev/null 2>&1; then \
		echo "  ● GUI: RUNNING (PID: $$(pgrep -x facelock-gui | head -n1))"; \
	else \
		echo "  ○ GUI: STOPPED"; \
	fi
	@if [ -f $(MONITOR_PID_FILE) ] && kill -0 $$(cat $(MONITOR_PID_FILE)) 2>/dev/null; then \
		echo "  ● Monitor Service: RUNNING locally (PID: $$(cat $(MONITOR_PID_FILE)))"; \
	elif systemctl --user is-active $(UNIT_NAME) >/dev/null 2>&1; then \
		echo "  ● Monitor Service: RUNNING via systemd --user"; \
	elif pgrep -x facelock-monitor >/dev/null 2>&1; then \
		echo "  ● Monitor Service: RUNNING (PID: $$(pgrep -x facelock-monitor | head -n1))"; \
	else \
		echo "  ○ Monitor Service: STOPPED"; \
	fi

run: venv
	$(VENV_BIN)/facelock-monitor

install:
	sudo ./install.sh

uninstall:
	@if [ -f /opt/facelock/uninstall.sh ]; then \
		sudo /opt/facelock/uninstall.sh; \
	else \
		echo "No /opt/facelock/uninstall.sh found."; \
	fi

desktop-install: venv
	$(VENV_BIN)/python packaging/install_desktop.py --install --user

desktop-uninstall: venv
	$(VENV_BIN)/python packaging/install_desktop.py --uninstall --user

service-install: venv
	mkdir -p $(UNIT_DIR)
	sed 's|@VENV_BIN@|$(VENV_BIN)|' packaging/$(UNIT_NAME) > $(UNIT_DIR)/$(UNIT_NAME)
	systemctl --user daemon-reload
	systemctl --user enable --now $(UNIT_NAME)

service-uninstall:
	-systemctl --user disable --now $(UNIT_NAME)
	rm -f $(UNIT_DIR)/$(UNIT_NAME)
	systemctl --user daemon-reload

service-start:
	systemctl --user start $(UNIT_NAME)

service-stop:
	systemctl --user stop $(UNIT_NAME)

service-restart:
	systemctl --user restart $(UNIT_NAME)

service-status:
	systemctl --user status $(UNIT_NAME)

service-logs:
	journalctl --user -u $(UNIT_NAME) -f

clean:
	rm -rf $(VENV) facelock.egg-info build dist .pytest_cache .facelock*.pid facelock*.log *.pid *.log
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
