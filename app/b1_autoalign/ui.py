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
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from serial.tools import list_ports

from .automation import AutomationManager
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
            elif kind == "mark_az_bottom":
                self.client.mark_az_bottom()
                message = "Current AZ position marked as lower limit/zero"
            elif kind == "mark_az_top":
                self.client.mark_az_top()
                message = "Current AZ position stored as upper limit"
            elif kind == "clear_az_limits":
                self.client.clear_az_limits()
                message = "Both AZ limits cleared"
            elif kind == "hold_mode":
                self.client.set_hold_mode(payload["mode"])
                message = f"Motor hold mode stored: {payload['mode']}"
            elif kind == "hold_delay":
                self.client.set_hold_delay(payload["milliseconds"])
                message = f"Timed hold delay stored: {payload['milliseconds']} ms"
            elif kind == "direction_inversion":
                self.client.set_direction_inversion(payload["alt_inverted"], payload["az_inverted"])
                message = (
                    f"Motor direction stored: ALT {'reversed' if payload['alt_inverted'] else 'normal'}, "
                    f"AZ {'reversed' if payload['az_inverted'] else 'normal'}"
                )
            elif kind == "release_drivers":
                self.client.release_drivers()
                message = "Both idle motor drivers released"
            elif kind == "calibration":
                self.client.set_calibration(payload["axis"], payload["value"])
                message = f"{payload['axis']} calibration stored: {payload['value']:.4f} steps/arcmin"
            else:
                raise ValueError(f"Unknown action: {kind}")
            self.action_succeeded.emit(message)
            self.poll()
        except Exception as exc:
            self.error.emit("action", str(exc))


class AutomationWorker(QObject):
    report_ready = pyqtSignal(object)
    solution_ready = pyqtSignal(object)
    error = pyqtSignal(str, str)

    @pyqtSlot(object)
    def refresh(self, request: object) -> None:
        config = dict(request)
        try:
            manager = AutomationManager(config["host"], config["port"])
            self.report_ready.emit(asdict(manager.detect(config["backend"])))
        except Exception as exc:
            self.error.emit("automation refresh", str(exc))

    @pyqtSlot(object)
    def capture_and_solve(self, request: object) -> None:
        config = dict(request)
        try:
            manager = AutomationManager(config["host"], config["port"])
            solution = manager.capture_and_solve(
                config["backend"],
                camera=config["camera"],
                exposure=config["exposure"],
                scale_low=config["scale_low"] or None,
                scale_high=config["scale_high"] or None,
                center_ra_deg=config["center_ra"] if config["pointing_hint"] else None,
                center_dec_deg=config["center_dec"] if config["pointing_hint"] else None,
                search_radius_deg=config["search_radius"],
                downsample=config["downsample"],
            )
            self.solution_ready.emit(asdict(solution))
        except Exception as exc:
            self.error.emit("capture and solve", str(exc))


class MainWindow(QMainWindow):
    request_connect = pyqtSignal(str)
    request_disconnect = pyqtSignal()
    request_poll = pyqtSignal()
    request_action = pyqtSignal(object)
    request_automation_refresh = pyqtSignal(object)
    request_capture_solve = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("B1-Mordred", "B1-AutoAlign")
        self.is_connected = False
        self.full_control = False
        self.poll_in_flight = False
        self._shutting_down = False
        self._last_poll_error: Optional[str] = None
        self._automation_ready = False
        self.control_widgets: list[QWidget] = []
        self.axis_position_values: dict[str, QLabel] = {}

        self.setWindowTitle("B1-AutoAlign Control Center")
        self.setMinimumSize(980, 680)
        self.resize(1120, 760)
        self._build_ui()
        self._apply_style()
        self._start_worker()
        self._start_automation_worker()
        self.refresh_ports()
        self._set_controls_enabled(False)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(750)
        self.poll_timer.timeout.connect(self._request_status)
        self.poll_timer.start()
        QTimer.singleShot(750, self._refresh_automation)

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

    def _start_automation_worker(self) -> None:
        self.automation_thread = QThread(self)
        self.automation_worker = AutomationWorker()
        self.automation_worker.moveToThread(self.automation_thread)
        self.request_automation_refresh.connect(self.automation_worker.refresh)
        self.request_capture_solve.connect(self.automation_worker.capture_and_solve)
        self.automation_worker.report_ready.connect(self._on_automation_report)
        self.automation_worker.solution_ready.connect(self._on_solution)
        self.automation_worker.error.connect(self._on_automation_error)
        self.automation_thread.start()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel("B1-AutoAlign")
        title.setObjectName("Title")
        subtitle = QLabel("Polar-alignment base control, capture & plate solving")
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
            ("AZ limits", "az_limits"),
            ("Motor direction", "direction"),
            ("Motor holding", "holding"),
            ("Auto limits", "auto_limits"),
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
        group.setMinimumHeight(195)
        layout = QGridLayout(group)
        position_caption = QLabel("Current position")
        position_caption.setObjectName("FieldCaption")
        position_value = QLabel("— steps")
        position_value.setObjectName("PositionReadout")
        position_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        position_value.setMinimumHeight(48)
        position_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.axis_position_values[axis] = position_value
        amount = QDoubleSpinBox()
        amount.setDecimals(3)
        amount.setRange(0.001, maximum)
        amount.setValue(float(self.settings.value(f"{axis.lower()}Amount", 1.0)))
        amount.setSuffix(" arcmin")
        negative = QPushButton(f"− {axis}")
        positive = QPushButton(f"+ {axis}")
        negative.clicked.connect(lambda _checked=False, a=axis, s=amount: self._move_arcmin(a, -s.value()))
        positive.clicked.connect(lambda _checked=False, a=axis, s=amount: self._move_arcmin(a, s.value()))
        layout.addWidget(position_caption, 0, 0, 1, 2)
        layout.addWidget(position_value, 1, 0, 1, 2)
        layout.addWidget(QLabel("Relative amount"), 2, 0, 1, 2)
        layout.addWidget(amount, 3, 0, 1, 2)
        layout.addWidget(negative, 4, 0)
        layout.addWidget(positive, 4, 1)
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
        motion_tab_root = QVBoxLayout(motion_tab)
        motion_tab_root.setContentsMargins(0, 0, 0, 0)
        motion_scroll = QScrollArea()
        motion_scroll.setWidgetResizable(True)
        motion_scroll.setFrameShape(QFrame.Shape.NoFrame)
        motion_content = QWidget()
        motion_root = QVBoxLayout(motion_content)
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
        motion_scroll.setWidget(motion_content)
        motion_tab_root.addWidget(motion_scroll)
        tabs.addTab(motion_tab, "Motion")

        setup_tab = QWidget()
        setup_tab_root = QVBoxLayout(setup_tab)
        setup_tab_root.setContentsMargins(0, 0, 0, 0)
        setup_scroll = QScrollArea()
        setup_scroll.setWidgetResizable(True)
        setup_scroll.setFrameShape(QFrame.Shape.NoFrame)
        setup_content = QWidget()
        setup_root = QVBoxLayout(setup_content)
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

        az_management = QGroupBox("AZ reference and limits")
        az_management_layout = QGridLayout(az_management)
        az_bottom_button = QPushButton("Mark current AZ as lower/zero")
        az_top_button = QPushButton("Mark current AZ as upper")
        az_clear_button = QPushButton("Clear both AZ limits")
        az_bottom_button.clicked.connect(self._mark_az_bottom)
        az_top_button.clicked.connect(self._mark_az_top)
        az_clear_button.clicked.connect(self._clear_az_limits)
        az_management_layout.addWidget(az_bottom_button, 0, 0)
        az_management_layout.addWidget(az_top_button, 0, 1)
        az_management_layout.addWidget(az_clear_button, 1, 0, 1, 2)
        self.control_widgets.extend([az_bottom_button, az_top_button, az_clear_button])
        setup_root.addWidget(az_management)

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

        direction = QGroupBox("Motor direction — commissioning only")
        direction_layout = QGridLayout(direction)
        self.alt_direction_inverted = QCheckBox("Reverse ALT direction")
        self.az_direction_inverted = QCheckBox("Reverse AZ direction")
        direction_apply = QPushButton("Store directions")
        direction_apply.clicked.connect(self._set_direction_inversion)
        direction_note = QLabel(
            "Only change an axis at its physical lower safe boundary. Changing polarity resets that axis "
            "to zero and clears its recorded upper limit(s)."
        )
        direction_note.setWordWrap(True)
        direction_layout.addWidget(self.alt_direction_inverted, 0, 0)
        direction_layout.addWidget(self.az_direction_inverted, 0, 1)
        direction_layout.addWidget(direction_apply, 0, 2)
        direction_layout.addWidget(direction_note, 1, 0, 1, 3)
        self.control_widgets.extend(
            [self.alt_direction_inverted, self.az_direction_inverted, direction_apply]
        )
        setup_root.addWidget(direction)

        holding = QGroupBox("Motor holding — validate thermals under load")
        holding_form = QFormLayout(holding)
        hold_row = QHBoxLayout()
        self.hold_mode_combo = QComboBox()
        self.hold_mode_combo.addItem("Release after motion", 0)
        self.hold_mode_combo.addItem("Timed hold", 1)
        self.hold_mode_combo.addItem("Always hold (v0.2 default)", 2)
        hold_set = QPushButton("Store mode")
        hold_set.clicked.connect(
            lambda: self._send_action({"kind": "hold_mode", "mode": self.hold_mode_combo.currentData()})
        )
        hold_row.addWidget(self.hold_mode_combo, 1)
        hold_row.addWidget(hold_set)
        holding_form.addRow("Mode", hold_row)
        delay_row = QHBoxLayout()
        self.hold_delay_input = QSpinBox()
        self.hold_delay_input.setRange(0, 600_000)
        self.hold_delay_input.setValue(5000)
        self.hold_delay_input.setSuffix(" ms")
        delay_set = QPushButton("Store delay")
        delay_set.clicked.connect(
            lambda: self._send_action({"kind": "hold_delay", "milliseconds": self.hold_delay_input.value()})
        )
        release_button = QPushButton("Release idle drivers now")
        release_button.clicked.connect(self._release_drivers)
        delay_row.addWidget(self.hold_delay_input, 1)
        delay_row.addWidget(delay_set)
        delay_row.addWidget(release_button)
        holding_form.addRow("Timed delay", delay_row)
        self.control_widgets.extend(
            [self.hold_mode_combo, hold_set, self.hold_delay_input, delay_set, release_button]
        )
        setup_root.addWidget(holding)
        setup_root.addStretch()
        setup_scroll.setWidget(setup_content)
        setup_tab_root.addWidget(setup_scroll)
        tabs.addTab(setup_tab, "Reference & calibration")

        automation_tab = QWidget()
        automation_tab_root = QVBoxLayout(automation_tab)
        automation_tab_root.setContentsMargins(0, 0, 0, 0)
        automation_scroll = QScrollArea()
        automation_scroll.setWidgetResizable(True)
        automation_scroll.setFrameShape(QFrame.Shape.NoFrame)
        automation_content = QWidget()
        automation_root = QVBoxLayout(automation_content)
        automation_root.setContentsMargins(4, 8, 4, 4)

        backend_group = QGroupBox("Capture and plate-solver backend")
        backend_form = QFormLayout(backend_group)
        self.backend_combo = QComboBox()
        self.backend_combo.addItem("Automatic (prefer Ekos)", "auto")
        self.backend_combo.addItem("Ekos / KStars", "ekos")
        self.backend_combo.addItem("Standalone INDI + Astrometry.net", "standalone")
        saved_backend = str(self.settings.value("automationBackend", "auto"))
        saved_index = self.backend_combo.findData(saved_backend)
        self.backend_combo.setCurrentIndex(max(0, saved_index))
        self.backend_combo.currentIndexChanged.connect(self._refresh_automation)
        backend_form.addRow("Mode", self.backend_combo)

        endpoint_row = QHBoxLayout()
        self.indi_host = QLineEdit(str(self.settings.value("indiHost", "localhost")))
        self.indi_host.setPlaceholderText("localhost")
        self.indi_port = QSpinBox()
        self.indi_port.setRange(1, 65535)
        self.indi_port.setValue(int(self.settings.value("indiPort", 7624)))
        endpoint_row.addWidget(self.indi_host, 1)
        endpoint_row.addWidget(self.indi_port)
        backend_form.addRow("INDI server", endpoint_row)

        refresh_automation = QPushButton("Detect backends")
        refresh_automation.clicked.connect(self._refresh_automation)
        self.refresh_automation_button = refresh_automation
        backend_form.addRow("", refresh_automation)
        automation_root.addWidget(backend_group)

        readiness = QGroupBox("Readiness")
        readiness_layout = QGridLayout(readiness)
        readiness_fields = (
            ("KStars / Ekos", "ekos"),
            ("Camera", "camera"),
            ("Local solver", "solver"),
            ("INDI PAC", "pac"),
            ("Selected", "selected"),
        )
        self.automation_values: dict[str, QLabel] = {}
        for row, (caption, key) in enumerate(readiness_fields):
            label = QLabel(caption)
            label.setObjectName("FieldCaption")
            value = QLabel("checking…")
            value.setWordWrap(True)
            self.automation_values[key] = value
            readiness_layout.addWidget(label, row, 0)
            readiness_layout.addWidget(value, row, 1)
        readiness_layout.setColumnStretch(1, 1)
        automation_root.addWidget(readiness)

        test_group = QGroupBox("Capture & solve test — no motor movement")
        test_form = QFormLayout(test_group)
        self.camera_combo = QComboBox()
        test_form.addRow("INDI camera", self.camera_combo)
        self.exposure_input = QDoubleSpinBox()
        self.exposure_input.setRange(0.01, 600.0)
        self.exposure_input.setDecimals(2)
        self.exposure_input.setValue(float(self.settings.value("captureExposure", 2.0)))
        self.exposure_input.setSuffix(" s")
        test_form.addRow("Exposure", self.exposure_input)
        scale_row = QHBoxLayout()
        self.scale_low_input = QDoubleSpinBox()
        self.scale_high_input = QDoubleSpinBox()
        for spin in (self.scale_low_input, self.scale_high_input):
            spin.setRange(0.0, 100.0)
            spin.setDecimals(3)
            spin.setSpecialValueText("auto")
            spin.setSuffix(" ″/px")
        self.scale_low_input.setValue(float(self.settings.value("scaleLow", 0.0)))
        self.scale_high_input.setValue(float(self.settings.value("scaleHigh", 0.0)))
        scale_row.addWidget(self.scale_low_input)
        scale_row.addWidget(QLabel("to"))
        scale_row.addWidget(self.scale_high_input)
        test_form.addRow("Scale hint", scale_row)
        pointing_row = QHBoxLayout()
        self.pointing_hint = QCheckBox("use")
        self.pointing_hint.setChecked(str(self.settings.value("pointingHint", "false")).lower() == "true")
        self.center_ra_input = QDoubleSpinBox()
        self.center_ra_input.setRange(0.0, 360.0)
        self.center_ra_input.setDecimals(4)
        self.center_ra_input.setValue(float(self.settings.value("centerRa", 0.0)))
        self.center_ra_input.setPrefix("RA ")
        self.center_ra_input.setSuffix("°")
        self.center_dec_input = QDoubleSpinBox()
        self.center_dec_input.setRange(-90.0, 90.0)
        self.center_dec_input.setDecimals(4)
        self.center_dec_input.setValue(float(self.settings.value("centerDec", 0.0)))
        self.center_dec_input.setPrefix("Dec ")
        self.center_dec_input.setSuffix("°")
        self.search_radius_input = QDoubleSpinBox()
        self.search_radius_input.setRange(0.1, 180.0)
        self.search_radius_input.setDecimals(1)
        self.search_radius_input.setValue(float(self.settings.value("searchRadius", 15.0)))
        self.search_radius_input.setPrefix("±")
        self.search_radius_input.setSuffix("°")
        pointing_row.addWidget(self.pointing_hint)
        pointing_row.addWidget(self.center_ra_input)
        pointing_row.addWidget(self.center_dec_input)
        pointing_row.addWidget(self.search_radius_input)
        test_form.addRow("Pointing hint", pointing_row)
        self.downsample_input = QSpinBox()
        self.downsample_input.setRange(1, 8)
        self.downsample_input.setValue(int(self.settings.value("downsample", 2)))
        test_form.addRow("Downsample", self.downsample_input)
        self.capture_solve_button = QPushButton("Capture and solve once")
        self.capture_solve_button.setObjectName("PrimaryButton")
        self.capture_solve_button.setEnabled(False)
        self.capture_solve_button.clicked.connect(self._capture_and_solve)
        test_form.addRow("", self.capture_solve_button)
        automation_root.addWidget(test_group)

        lock_notice = QLabel(
            "AUTOMATIC CORRECTION LOCKED — this milestone validates image acquisition and plate solving only. "
            "It never moves ALT or AZ."
        )
        lock_notice.setObjectName("AutomationLock")
        lock_notice.setWordWrap(True)
        automation_root.addWidget(lock_notice)
        automation_root.addStretch()
        automation_scroll.setWidget(automation_content)
        automation_tab_root.addWidget(automation_scroll)
        tabs.addTab(automation_tab, "Automation")
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
            QLabel#AutomationLock {
                background: #4b3513; border: 1px solid #79551b; border-radius: 5px;
                padding: 8px; color: #ffd27a; font-weight: 700;
            }
            QLabel#FieldCaption { color: #8f9bb0; }
            QLabel#PositionReadout {
                background: #10141b; border: 1px solid #3a4354; border-radius: 6px;
                padding: 6px 8px; color: #f5f7ff; font-size: 18px; font-weight: 700;
            }
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
        self.axis_position_values["ALT"].setText(f"{data['alt_steps']:,} steps")
        self.axis_position_values["AZ"].setText(f"{data['az_steps']:,} steps")
        if data["alt_min"] is None:
            self.status_values["alt_limits"].setText("unavailable on legacy firmware")
        else:
            maximum = "not set" if data["alt_max"] is None else f"{data['alt_max']:,}"
            self.status_values["alt_limits"].setText(f"{data['alt_min']:,} … {maximum} steps")
        if data["az_min"] is None:
            self.status_values["az_limits"].setText("not set" if self.full_control else "unavailable")
        else:
            maximum = "not set" if data["az_max"] is None else f"{data['az_max']:,}"
            self.status_values["az_limits"].setText(f"{data['az_min']:,} … {maximum} steps")
        if data["alt_direction_inverted"] is None or data["az_direction_inverted"] is None:
            self.status_values["direction"].setText("unavailable")
        else:
            self.status_values["direction"].setText(
                f"ALT {'reversed' if data['alt_direction_inverted'] else 'normal'}, "
                f"AZ {'reversed' if data['az_direction_inverted'] else 'normal'}"
            )
            if not self.alt_direction_inverted.hasFocus():
                self.alt_direction_inverted.setChecked(data["alt_direction_inverted"])
            if not self.az_direction_inverted.hasFocus():
                self.az_direction_inverted.setChecked(data["az_direction_inverted"])
        if data["hold_mode"] is None:
            self.status_values["holding"].setText("unavailable")
        else:
            hold_names = {0: "release", 1: "timed", 2: "always"}
            drivers = (
                f"drivers AZ {'on' if data['az_driver_enabled'] else 'off'}, "
                f"ALT {'on' if data['alt_driver_enabled'] else 'off'}"
            )
            self.status_values["holding"].setText(
                f"{hold_names.get(data['hold_mode'], 'unknown')} ({data['hold_delay_ms']} ms); {drivers}"
            )
            if not self.hold_mode_combo.hasFocus():
                index = self.hold_mode_combo.findData(data["hold_mode"])
                if index >= 0:
                    self.hold_mode_combo.setCurrentIndex(index)
            if not self.hold_delay_input.hasFocus():
                self.hold_delay_input.setValue(data["hold_delay_ms"])
        if data["limits_ready"] is None:
            self.status_values["auto_limits"].setText("unavailable")
        else:
            self.status_values["auto_limits"].setText(
                "READY" if data["limits_ready"] else "LOCKED — record ALT and AZ ranges"
            )
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

    def _mark_az_bottom(self) -> None:
        if self._confirm(
            "Set AZ lower limit?",
            "Confirm that the AZ mechanism is at its physical lower safe travel limit. "
            "The current AZ coordinate becomes zero.",
        ):
            self._send_action({"kind": "mark_az_bottom"})

    def _mark_az_top(self) -> None:
        if self._confirm(
            "Set AZ upper limit?",
            "The current positive AZ position will become the upper soft limit. "
            "Record the lower AZ limit first.",
        ):
            self._send_action({"kind": "mark_az_top"})

    def _clear_az_limits(self) -> None:
        if self._confirm(
            "Clear both AZ limits?",
            "This disables automatic-correction readiness until both AZ limits are recorded again.",
        ):
            self._send_action({"kind": "clear_az_limits"})

    def _release_drivers(self) -> None:
        if self._confirm(
            "Release motor holding?",
            "Both drivers will be de-energized. Confirm that the 25 kg load is mechanically supported "
            "and cannot back-drive either axis.",
        ):
            self._send_action({"kind": "release_drivers"})

    def _set_direction_inversion(self) -> None:
        if self._confirm(
            "Change motor directions?",
            "For every axis whose setting changes, confirm that the mechanism is at its physical lower "
            "safe boundary. The firmware will set that axis coordinate to zero and clear its previous "
            "upper limit(s). Re-record the safe travel range before automatic correction.",
        ):
            self._send_action({
                "kind": "direction_inversion",
                "alt_inverted": self.alt_direction_inverted.isChecked(),
                "az_inverted": self.az_direction_inverted.isChecked(),
            })

    def _set_calibration(self, axis: str, value: float) -> None:
        self._send_action({"kind": "calibration", "axis": axis, "value": value})

    def _automation_config(self) -> dict:
        return {
            "backend": str(self.backend_combo.currentData()),
            "host": self.indi_host.text().strip() or "localhost",
            "port": self.indi_port.value(),
            "camera": self.camera_combo.currentText().strip(),
            "exposure": self.exposure_input.value(),
            "scale_low": self.scale_low_input.value(),
            "scale_high": self.scale_high_input.value(),
            "pointing_hint": self.pointing_hint.isChecked(),
            "center_ra": self.center_ra_input.value(),
            "center_dec": self.center_dec_input.value(),
            "search_radius": self.search_radius_input.value(),
            "downsample": self.downsample_input.value(),
        }

    @pyqtSlot()
    def _refresh_automation(self) -> None:
        self._automation_ready = False
        self.refresh_automation_button.setEnabled(False)
        self.capture_solve_button.setEnabled(False)
        self.automation_values["selected"].setText("checking…")
        self.request_automation_refresh.emit(self._automation_config())

    @pyqtSlot(object)
    def _on_automation_report(self, report: object) -> None:
        data = dict(report)
        ekos = dict(data["ekos"])
        solver = dict(data["solver"])
        cameras = [dict(camera)["name"] for camera in data["cameras"]]
        current_camera = self.camera_combo.currentText()
        self.camera_combo.clear()
        self.camera_combo.addItems(cameras)
        if current_camera in cameras:
            self.camera_combo.setCurrentText(current_camera)

        if ekos["running"]:
            version = ekos["version"] or "running"
            self.automation_values["ekos"].setText(f"{version} — {ekos['detail']}")
        else:
            self.automation_values["ekos"].setText(ekos["detail"])
        camera_text = ", ".join(cameras) if cameras else "no INDI camera detected"
        if ekos["camera"]:
            camera_text = f"Ekos: {ekos['camera']}" + (f"; INDI: {camera_text}" if cameras else "")
        self.automation_values["camera"].setText(camera_text)
        self.automation_values["solver"].setText(solver["detail"])
        pac_devices = list(data["pac_devices"])
        self.automation_values["pac"].setText(
            ", ".join(pac_devices) if pac_devices else "not exposed by the connected INDI version/device"
        )
        selected = data["selected_backend"]
        selected_name = {"ekos": "Ekos / KStars", "standalone": "Standalone INDI", "none": "not ready"}[selected]
        self.automation_values["selected"].setText(f"{selected_name} — {data['detail']}")
        self._automation_ready = bool(data["ready"])
        self.refresh_automation_button.setEnabled(True)
        self.capture_solve_button.setEnabled(self._automation_ready)
        self._log(f"Automation check: {data['detail']}")
        for warning in data["warnings"]:
            self._log(f"Automation: {warning}")

    @pyqtSlot()
    def _capture_and_solve(self) -> None:
        if not self._automation_ready:
            return
        self.capture_solve_button.setEnabled(False)
        self.refresh_automation_button.setEnabled(False)
        self._log("Starting one capture-and-solve test; motor correction remains locked")
        self.request_capture_solve.emit(self._automation_config())

    @pyqtSlot(object)
    def _on_solution(self, solution: object) -> None:
        data = dict(solution)
        orientation = "" if data["orientation_deg"] is None else f", orientation {data['orientation_deg']:.3f}°"
        self._log(
            f"Plate solution via {data['backend']}: RA {data['ra_deg']:.6f}°, "
            f"Dec {data['dec_deg']:.6f}°{orientation}"
        )
        if data["image_path"]:
            self._log(f"Captured image: {data['image_path']}")
        self.refresh_automation_button.setEnabled(True)
        self.capture_solve_button.setEnabled(self._automation_ready)

    @pyqtSlot(str, str)
    def _on_automation_error(self, context: str, message: str) -> None:
        self.refresh_automation_button.setEnabled(True)
        self.capture_solve_button.setEnabled(self._automation_ready)
        self._log(f"{context.capitalize()} error: {message}")
        if context == "capture and solve":
            QMessageBox.warning(self, "Capture and solve failed", message)

    @pyqtSlot(str)
    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{stamp}] {message}")

    def _save_settings(self) -> None:
        self.settings.setValue("port", self.port_combo.currentText().strip())
        self.settings.setValue("altAmount", self.alt_amount.value())
        self.settings.setValue("azAmount", self.az_amount.value())
        self.settings.setValue("rawSteps", self.raw_steps.value())
        self.settings.setValue("automationBackend", self.backend_combo.currentData())
        self.settings.setValue("indiHost", self.indi_host.text().strip() or "localhost")
        self.settings.setValue("indiPort", self.indi_port.value())
        self.settings.setValue("captureExposure", self.exposure_input.value())
        self.settings.setValue("scaleLow", self.scale_low_input.value())
        self.settings.setValue("scaleHigh", self.scale_high_input.value())
        self.settings.setValue("pointingHint", self.pointing_hint.isChecked())
        self.settings.setValue("centerRa", self.center_ra_input.value())
        self.settings.setValue("centerDec", self.center_dec_input.value())
        self.settings.setValue("searchRadius", self.search_radius_input.value())
        self.settings.setValue("downsample", self.downsample_input.value())

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
        if self.automation_thread.isRunning():
            self.automation_thread.quit()
            self.automation_thread.wait(10000)

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
