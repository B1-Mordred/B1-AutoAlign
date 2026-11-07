"""PyQt6 desktop interface for B1-AutoAlign."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QMetaObject, QObject, QSettings, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from serial.tools import list_ports

from .protocol import B1AutoAlignClient


DEFAULT_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"


class SerialWorker(QObject):
    connected = pyqtSignal(object)
    disconnected = pyqtSignal()
    snapshot_ready = pyqtSignal(object)
    action_succeeded = pyqtSignal(str)
    error = pyqtSignal(str, str)
    trace = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._polling = False
        self.client = B1AutoAlignClient(trace=self._trace)

    def _trace(self, message: str) -> None:
        if not self._polling:
            self.trace.emit(message)

    @pyqtSlot(str)
    def connect_device(self, port: str) -> None:
        try:
            identity = self.client.connect(port)
            self.connected.emit(asdict(identity))
            self.poll()
        except Exception as exc:
            self.client.close()
            self.error.emit("connect", str(exc))
            self.disconnected.emit()

    @pyqtSlot()
    def disconnect_device(self) -> None:
        self.client.close()
        self.disconnected.emit()

    @pyqtSlot()
    def poll(self) -> None:
        if not self.client.connected:
            return
        self._polling = True
        try:
            self.snapshot_ready.emit(asdict(self.client.snapshot()))
        except Exception as exc:
            self.error.emit("poll", str(exc))
        finally:
            self._polling = False

    @pyqtSlot(object)
    def execute(self, request: object) -> None:
        payload = dict(request)
        kind = payload.pop("kind")
        try:
            if kind == "move_arcmin":
                self.client.move_arcminutes(payload["axis"], payload["amount"])
                message = f"{payload['axis']} move sent: {payload['amount']:+.3f} arcmin"
            elif kind == "move_steps":
                self.client.move_steps(payload["axis"], payload["steps"])
                message = f"{payload['axis']} raw move accepted: {payload['steps']:+d} steps"
            elif kind == "stop":
                self.client.stop()
                message = "STOP sent to both axes"
            elif kind == "zero":
                self.client.zero_both()
                message = "Both logical positions set to zero"
            elif kind == "mark_bottom":
                self.client.mark_alt_bottom()
                message = "Current ALT position marked as bottom/zero"
            elif kind == "mark_top":
                self.client.mark_alt_top()
                message = "Current ALT position stored as upper limit"
            elif kind == "clear_top":
                self.client.clear_alt_top()
                message = "ALT upper limit cleared"
            elif kind == "calibration":
                self.client.set_calibration(payload["axis"], payload["value"])
                message = f"{payload['axis']} calibration stored: {payload['value']:.4f} steps/arcmin"
            else:
                raise ValueError(f"Unknown action: {kind}")
            self.action_succeeded.emit(message)
            self.poll()
        except Exception as exc:
            self.error.emit("action", str(exc))


class MainWindow(QMainWindow):
    request_connect = pyqtSignal(str)
    request_disconnect = pyqtSignal()
    request_poll = pyqtSignal()
    request_action = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("B1-Mordred", "B1-AutoAlign")
        self.is_connected = False
        self.full_control = False
        self.poll_in_flight = False
        self._shutting_down = False
        self._last_poll_error: Optional[str] = None
        self.control_widgets: list[QWidget] = []

        self.setWindowTitle("B1-AutoAlign Control Center")
        self.setMinimumSize(980, 680)
        self.resize(1120, 760)
        self._build_ui()
        self._apply_style()
        self._start_worker()
        self.refresh_ports()
        self._set_controls_enabled(False)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(750)
        self.poll_timer.timeout.connect(self._request_status)
        self.poll_timer.start()

    def _start_worker(self) -> None:
        self.worker_thread = QThread(self)
        self.worker = SerialWorker()
        self.worker.moveToThread(self.worker_thread)
        self.request_connect.connect(self.worker.connect_device)
        self.request_disconnect.connect(self.worker.disconnect_device)
        self.request_poll.connect(self.worker.poll)
        self.request_action.connect(self.worker.execute)
        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.snapshot_ready.connect(self._on_snapshot)
        self.worker.action_succeeded.connect(self._on_action_success)
        self.worker.error.connect(self._on_error)
        self.worker.trace.connect(self._log)
        self.worker_thread.start()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel("B1-AutoAlign")
        title.setObjectName("Title")
        subtitle = QLabel("Polar-alignment base control & calibration")
        subtitle.setObjectName("Subtitle")
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        title_row.addLayout(title_box)
        title_row.addStretch()
        self.connection_badge = QLabel("DISCONNECTED")
        self.connection_badge.setObjectName("BadgeOff")
        self.connection_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_row.addWidget(self.connection_badge)
        root.addLayout(title_row)

        connection_group = QGroupBox("Connection")
        connection_layout = QHBoxLayout(connection_group)
        connection_layout.addWidget(QLabel("Serial port"))
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setMinimumWidth(430)
        connection_layout.addWidget(self.port_combo, 1)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_ports)
        connection_layout.addWidget(refresh_button)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("PrimaryButton")
        self.connect_button.clicked.connect(self._toggle_connection)
        connection_layout.addWidget(self.connect_button)
        root.addWidget(connection_group)

        self.safety_banner = QLabel(
            "Motion is locked until a controller identifying as B1-AutoAlign is connected."
        )
        self.safety_banner.setObjectName("SafetyBanner")
        self.safety_banner.setWordWrap(True)
        root.addWidget(self.safety_banner)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_status_panel())
        splitter.addWidget(self._build_control_panel())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, 1)

        log_group = QGroupBox("Activity log")
        log_group.setMaximumHeight(145)
        log_layout = QVBoxLayout(log_group)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        self.log_view.setMinimumHeight(70)
        font = QFont("Monospace")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.log_view.setFont(font)
        log_layout.addWidget(self.log_view)
        root.addWidget(log_group)

        self.setCentralWidget(central)

    def _build_status_panel(self) -> QWidget:
        group = QGroupBox("Controller status")
        layout = QGridLayout(group)
        layout.setColumnStretch(1, 1)
        labels = [
            ("Product", "product"),
            ("Firmware", "version"),
            ("Motion", "motion"),
            ("Last fault", "fault"),
            ("ALT position", "alt_position"),
            ("AZ position", "az_position"),
            ("ALT limits", "alt_limits"),
            ("ALT calibration", "alt_cal"),
            ("AZ calibration", "az_cal"),
        ]
        self.status_values: dict[str, QLabel] = {}
        for row, (caption, key) in enumerate(labels):
            caption_label = QLabel(caption)
            caption_label.setObjectName("FieldCaption")
            value_label = QLabel("—")
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.status_values[key] = value_label
            layout.addWidget(caption_label, row, 0)
            layout.addWidget(value_label, row, 1)
        layout.setRowStretch(len(labels), 1)
        return group

    def _axis_group(self, axis: str, maximum: float) -> QGroupBox:
        group = QGroupBox(f"{axis} jog")
        layout = QGridLayout(group)
        amount = QDoubleSpinBox()
        amount.setDecimals(3)
        amount.setRange(0.001, maximum)
        amount.setValue(float(self.settings.value(f"{axis.lower()}Amount", 1.0)))
        amount.setSuffix(" arcmin")
        negative = QPushButton(f"− {axis}")
        positive = QPushButton(f"+ {axis}")
        negative.clicked.connect(lambda _checked=False, a=axis, s=amount: self._move_arcmin(a, -s.value()))
        positive.clicked.connect(lambda _checked=False, a=axis, s=amount: self._move_arcmin(a, s.value()))
        layout.addWidget(QLabel("Relative amount"), 0, 0, 1, 2)
        layout.addWidget(amount, 1, 0, 1, 2)
        layout.addWidget(negative, 2, 0)
        layout.addWidget(positive, 2, 1)
        self.control_widgets.extend([amount, negative, positive])
        if axis == "ALT":
            self.alt_amount = amount
        else:
            self.az_amount = amount
        return group

    def _build_control_panel(self) -> QWidget:
        panel = QWidget()
        root = QVBoxLayout(panel)
        root.setContentsMargins(0, 0, 0, 0)

        stop_button = QPushButton("STOP BOTH AXES")
        stop_button.setObjectName("StopButton")
        stop_button.setMinimumHeight(48)
        stop_button.clicked.connect(lambda: self._send_action({"kind": "stop"}))
        self.stop_button = stop_button
        self.control_widgets.append(stop_button)
        root.addWidget(stop_button)

        tabs = QTabWidget()
        motion_tab = QWidget()
        motion_root = QVBoxLayout(motion_tab)
        motion_root.setContentsMargins(4, 8, 4, 4)
        axes = QHBoxLayout()
        axes.addWidget(self._axis_group("ALT", 140.0))
        axes.addWidget(self._axis_group("AZ", 320.0))
        motion_root.addLayout(axes)

        raw_group = QGroupBox("Raw-step jog — commissioning only")
        raw_layout = QGridLayout(raw_group)
        self.raw_steps = QSpinBox()
        self.raw_steps.setRange(1, 100_000)
        self.raw_steps.setValue(int(self.settings.value("rawSteps", 10)))
        raw_layout.addWidget(QLabel("Magnitude"), 0, 0)
        raw_layout.addWidget(self.raw_steps, 0, 1)
        raw_buttons = []
        for column, (caption, axis, sign) in enumerate((
            ("− ALT", "ALT", -1), ("+ ALT", "ALT", 1),
            ("− AZ", "AZ", -1), ("+ AZ", "AZ", 1),
        )):
            button = QPushButton(caption)
            button.clicked.connect(
                lambda _checked=False, a=axis, s=sign: self._move_steps(a, s * self.raw_steps.value())
            )
            raw_layout.addWidget(button, 1, column)
            raw_buttons.append(button)
        self.control_widgets.extend([self.raw_steps, *raw_buttons])
        motion_root.addWidget(raw_group)
        motion_root.addStretch()
        tabs.addTab(motion_tab, "Motion")

        setup_tab = QWidget()
        setup_root = QVBoxLayout(setup_tab)
        setup_root.setContentsMargins(4, 8, 4, 4)
        management = QGroupBox("Reference and limits")
        management_layout = QGridLayout(management)
        zero_button = QPushButton("Zero both counters")
        bottom_button = QPushButton("Mark current ALT as bottom")
        top_button = QPushButton("Mark current ALT as top")
        clear_button = QPushButton("Clear ALT top limit")
        zero_button.clicked.connect(self._zero_both)
        bottom_button.clicked.connect(self._mark_bottom)
        top_button.clicked.connect(self._mark_top)
        clear_button.clicked.connect(self._clear_top)
        management_layout.addWidget(zero_button, 0, 0)
        management_layout.addWidget(bottom_button, 0, 1)
        management_layout.addWidget(top_button, 1, 0)
        management_layout.addWidget(clear_button, 1, 1)
        self.control_widgets.extend([zero_button, bottom_button, top_button, clear_button])
        setup_root.addWidget(management)

        calibration = QGroupBox("Steps per arcminute")
        form = QFormLayout(calibration)
        alt_row = QHBoxLayout()
        self.alt_cal_input = QDoubleSpinBox()
        self.alt_cal_input.setDecimals(4)
        self.alt_cal_input.setRange(0.0001, 99_999.0)
        self.alt_cal_input.setValue(100.0)
        alt_set = QPushButton("Store ALT")
        alt_set.clicked.connect(lambda: self._set_calibration("ALT", self.alt_cal_input.value()))
        alt_row.addWidget(self.alt_cal_input, 1)
        alt_row.addWidget(alt_set)
        az_row = QHBoxLayout()
        self.az_cal_input = QDoubleSpinBox()
        self.az_cal_input.setDecimals(4)
        self.az_cal_input.setRange(0.0001, 99_999.0)
        self.az_cal_input.setValue(11.0)
        az_set = QPushButton("Store AZ")
        az_set.clicked.connect(lambda: self._set_calibration("AZ", self.az_cal_input.value()))
        az_row.addWidget(self.az_cal_input, 1)
        az_row.addWidget(az_set)
        form.addRow("ALT", alt_row)
        form.addRow("AZ", az_row)
        self.control_widgets.extend([self.alt_cal_input, alt_set, self.az_cal_input, az_set])
        setup_root.addWidget(calibration)
        setup_root.addStretch()
        tabs.addTab(setup_tab, "Reference & calibration")
        root.addWidget(tabs, 1)
        return panel

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #161a22; color: #e9edf5; }
            QGroupBox {
                border: 1px solid #343b4a; border-radius: 8px; margin-top: 10px;
                padding: 10px; font-weight: 600;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #aeb9cc; }
            QLabel#Title { font-size: 26px; font-weight: 700; color: #f5f7ff; }
            QLabel#Subtitle { color: #8f9bb0; }
            QLabel#BadgeOff, QLabel#BadgeOn, QLabel#BadgeLegacy {
                border-radius: 10px; padding: 6px 12px; min-width: 110px; font-weight: 700;
            }
            QLabel#BadgeOff { background: #343b4a; color: #c7cfdd; }
            QLabel#BadgeOn { background: #173f32; color: #77e5b5; }
            QLabel#BadgeLegacy { background: #4b3513; color: #ffd27a; }
            QLabel#SafetyBanner {
                background: #232a38; border-left: 4px solid #6599ff;
                border-radius: 5px; padding: 10px; color: #cbd5e8;
            }
            QLabel#FieldCaption { color: #8f9bb0; }
            QPushButton {
                background: #2b3342; border: 1px solid #414b5f; border-radius: 6px;
                padding: 7px 12px;
            }
            QPushButton:hover { background: #354158; }
            QPushButton:disabled { color: #666f80; background: #202530; border-color: #2c3340; }
            QPushButton#PrimaryButton { background: #3768d9; border-color: #4b7bec; font-weight: 600; }
            QPushButton#StopButton { background: #a72d3b; border-color: #d74b59; font-size: 15px; font-weight: 800; }
            QPushButton#StopButton:hover { background: #c33747; }
            QPushButton#StopButton:disabled { background: #49272f; border-color: #65313b; color: #98717a; }
            QTabWidget::pane { border: 1px solid #343b4a; border-radius: 6px; }
            QTabBar::tab { background: #202633; padding: 8px 18px; margin-right: 2px; }
            QTabBar::tab:selected { background: #32415d; color: #f5f7ff; }
            QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
                background: #10141b; border: 1px solid #3a4354; border-radius: 5px;
                padding: 5px; selection-background-color: #3768d9;
            }
            QSplitter::handle { background: #2b3240; width: 3px; }
        """)

    @pyqtSlot()
    def refresh_ports(self) -> None:
        previous = self.port_combo.currentText().strip()
        saved = str(self.settings.value("port", DEFAULT_PORT))
        ports = {str(path) for path in Path("/dev/serial/by-id").glob("*")}
        ports.update(port.device for port in list_ports.comports())
        if saved:
            ports.add(saved)
        self.port_combo.clear()
        self.port_combo.addItems(sorted(ports))
        target = previous or saved
        self.port_combo.setCurrentText(target)

    @pyqtSlot()
    def _toggle_connection(self) -> None:
        if self.is_connected:
            self.request_disconnect.emit()
            return
        port = self.port_combo.currentText().strip()
        if not port:
            QMessageBox.warning(self, "No serial port", "Select or enter a serial device first.")
            return
        self.connect_button.setEnabled(False)
        self._log(f"Connecting to {port} at 19200 baud…")
        self.request_connect.emit(port)

    @pyqtSlot(object)
    def _on_connected(self, identity: object) -> None:
        data = dict(identity)
        self.is_connected = True
        self.full_control = bool(data["full_control"])
        self.connect_button.setEnabled(True)
        self.connect_button.setText("Disconnect")
        self.port_combo.setEnabled(False)
        self.status_values["product"].setText(data["product"])
        self.status_values["version"].setText(data["version"])
        self._set_controls_enabled(self.full_control)
        if self.full_control:
            self.connection_badge.setObjectName("BadgeOn")
            self.connection_badge.setText("B1 CONTROL")
            self.safety_banner.setText(
                "Full control enabled. Soft limits remain open-loop; support the load during commissioning."
            )
            self._log(f"Connected: {data['product']} {data['version']} — full control enabled")
        else:
            self.connection_badge.setObjectName("BadgeLegacy")
            self.connection_badge.setText("READ ONLY")
            self.safety_banner.setText(
                f"Detected {data['product']} {data['version']}. Read-only mode: motion and :Q# are blocked "
                "because legacy V1.13.16 stop behavior is unsafe."
            )
            self._log(f"Connected: {data['product']} {data['version']} — legacy read-only mode")
        self.connection_badge.style().unpolish(self.connection_badge)
        self.connection_badge.style().polish(self.connection_badge)

    @pyqtSlot()
    def _on_disconnected(self) -> None:
        self.is_connected = False
        self.full_control = False
        self.poll_in_flight = False
        self.connect_button.setEnabled(True)
        self.connect_button.setText("Connect")
        self.port_combo.setEnabled(True)
        self.connection_badge.setObjectName("BadgeOff")
        self.connection_badge.setText("DISCONNECTED")
        self.connection_badge.style().unpolish(self.connection_badge)
        self.connection_badge.style().polish(self.connection_badge)
        self.safety_banner.setText(
            "Motion is locked until a controller identifying as B1-AutoAlign is connected."
        )
        self._set_controls_enabled(False)
        self._log("Disconnected")

    @pyqtSlot(object)
    def _on_snapshot(self, snapshot: object) -> None:
        data = dict(snapshot)
        self.poll_in_flight = False
        self._last_poll_error = None
        moving = []
        if data["moving_alt"]:
            moving.append("ALT")
        if data["moving_az"]:
            moving.append("AZ")
        self.status_values["motion"].setText(", ".join(moving) if moving else "stationary")
        self.status_values["fault"].setText(data["fault"])
        self.status_values["alt_position"].setText(f"{data['alt_steps']:,} steps")
        self.status_values["az_position"].setText(f"{data['az_steps']:,} steps")
        if data["alt_min"] is None:
            self.status_values["alt_limits"].setText("unavailable on legacy firmware")
        else:
            maximum = "not set" if data["alt_max"] is None else f"{data['alt_max']:,}"
            self.status_values["alt_limits"].setText(f"{data['alt_min']:,} … {maximum} steps")
        if data["alt_calibration"] is None:
            self.status_values["alt_cal"].setText("—")
            self.status_values["az_cal"].setText("—")
        else:
            self.status_values["alt_cal"].setText(f"{data['alt_calibration']:.4f} steps/arcmin")
            self.status_values["az_cal"].setText(f"{data['az_calibration']:.4f} steps/arcmin")
            if not self.alt_cal_input.hasFocus():
                self.alt_cal_input.setValue(data["alt_calibration"])
            if not self.az_cal_input.hasFocus():
                self.az_cal_input.setValue(data["az_calibration"])

    @pyqtSlot(str)
    def _on_action_success(self, message: str) -> None:
        self._log(message)

    @pyqtSlot(str, str)
    def _on_error(self, context: str, message: str) -> None:
        self.poll_in_flight = False
        if context == "poll":
            if message != self._last_poll_error:
                self._log(f"Status error: {message}")
                self._last_poll_error = message
            return
        self._log(f"{context.capitalize()} error: {message}")
        if context == "connect":
            QMessageBox.critical(
                self,
                "Connection failed",
                f"Could not open or identify the controller.\n\n{message}\n\n"
                "Close Ekos/INDI if it currently owns the serial port.",
            )
        else:
            QMessageBox.warning(self, "Command rejected", message)

    def _request_status(self) -> None:
        if self.is_connected and not self.poll_in_flight:
            self.poll_in_flight = True
            self.request_poll.emit()

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in self.control_widgets:
            widget.setEnabled(enabled)

    def _send_action(self, payload: dict) -> None:
        if not self.full_control:
            return
        self.request_action.emit(payload)

    def _move_arcmin(self, axis: str, amount: float) -> None:
        self._send_action({"kind": "move_arcmin", "axis": axis, "amount": amount})

    def _move_steps(self, axis: str, steps: int) -> None:
        self._send_action({"kind": "move_steps", "axis": axis, "steps": steps})

    def _confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(
            self,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) == QMessageBox.StandardButton.Yes

    def _zero_both(self) -> None:
        if self._confirm("Zero both counters?", "This changes both logical coordinates without moving the mechanics."):
            self._send_action({"kind": "zero"})

    def _mark_bottom(self) -> None:
        if self._confirm(
            "Set ALT bottom?",
            "Confirm that the mechanism is at its physical lowest safe ALT position. The current ALT coordinate becomes zero.",
        ):
            self._send_action({"kind": "mark_bottom"})

    def _mark_top(self) -> None:
        if self._confirm(
            "Set ALT top limit?",
            "The current positive ALT position will become the upper soft limit.",
        ):
            self._send_action({"kind": "mark_top"})

    def _clear_top(self) -> None:
        if self._confirm(
            "Clear ALT top limit?",
            "This removes upper soft-limit protection until a new top is recorded.",
        ):
            self._send_action({"kind": "clear_top"})

    def _set_calibration(self, axis: str, value: float) -> None:
        self._send_action({"kind": "calibration", "axis": axis, "value": value})

    @pyqtSlot(str)
    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{stamp}] {message}")

    def _save_settings(self) -> None:
        self.settings.setValue("port", self.port_combo.currentText().strip())
        self.settings.setValue("altAmount", self.alt_amount.value())
        self.settings.setValue("azAmount", self.az_amount.value())
        self.settings.setValue("rawSteps", self.raw_steps.value())

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self.poll_timer.stop()
        self._save_settings()
        if self.worker_thread.isRunning():
            QMetaObject.invokeMethod(
                self.worker,
                "disconnect_device",
                Qt.ConnectionType.BlockingQueuedConnection,
            )
            self.worker_thread.quit()
            self.worker_thread.wait(2000)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.shutdown()
        event.accept()


def create_application(argv: list[str]) -> tuple[QApplication, MainWindow]:
    application = QApplication(argv)
    application.setApplicationName("B1-AutoAlign")
    application.setOrganizationName("B1-Mordred")
    window = MainWindow()
    application.aboutToQuit.connect(window.shutdown)
    return application, window
