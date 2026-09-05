VENV := .venv
VENV_BIN := $(abspath $(VENV)/bin)
UNIT_NAME := facelock-monitor.service
UNIT_DIR := $(HOME)/.config/systemd/user

.PHONY: venv enroll run service-install service-uninstall service-logs clean

venv:
	python3 -m venv $(VENV)
	$(VENV_BIN)/pip install -e .

enroll: venv
	$(VENV_BIN)/facelock-enroll

run: venv
	$(VENV_BIN)/facelock-monitor

service-install: venv
	mkdir -p $(UNIT_DIR)
	sed 's|@VENV_BIN@|$(VENV_BIN)|' packaging/$(UNIT_NAME) > $(UNIT_DIR)/$(UNIT_NAME)
	systemctl --user daemon-reload
	systemctl --user enable --now $(UNIT_NAME)

service-uninstall:
	-systemctl --user disable --now $(UNIT_NAME)
	rm -f $(UNIT_DIR)/$(UNIT_NAME)
	systemctl --user daemon-reload

service-logs:
	journalctl --user -u $(UNIT_NAME) -f

clean:
	rm -rf $(VENV) facelock.egg-info
