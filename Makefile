PYTHON ?= python3
VENV := .venv
VENV_BIN := $(abspath $(VENV)/bin)
UNIT_NAME := facelock-monitor.service
UNIT_DIR := $(HOME)/.config/systemd/user

.PHONY: help venv test test-face test-face-cli verify remove-face enroll gui calibrate run install uninstall \
        pam-status pam-enable pam-disable \
        service-install service-uninstall service-start service-stop service-restart service-status service-logs \
        desktop-install desktop-uninstall \
        lint clean

help:
	@echo "FaceLock Management Targets:"
	@echo "  make venv               Create virtual environment and install package"
	@echo "  make gui                Launch graphical face setup wizard with live HUD"
	@echo "  make calibrate          Launch camera diagnostic and biometric calibration assistant"
	@echo "  make test-face          Test live camera face against saved profile (interactive HUD)"
	@echo "  make test-face-cli      Test live camera face against saved profile in terminal mode"
	@echo "  make pam-status         Check status of PAM lock-screen face unlock"
	@echo "  make pam-enable         Enable FaceLock PAM unlock for lock screen (Super+L)"
	@echo "  make pam-disable        Disable FaceLock PAM unlock (restore default password)"
	@echo "  make enroll             Enroll face via terminal (CLI mode)"
	@echo "  make remove-face        Remove saved face profile (interactive menu or NAME=...)"
	@echo "  make run                Run monitor daemon in foreground"
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
	@if [ ! -d "$(VENV)" ]; then $(PYTHON) -m venv $(VENV); fi
	$(VENV_BIN)/pip install -e ".[test]"

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
	rm -rf $(VENV) facelock.egg-info build dist .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
