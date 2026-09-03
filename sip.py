import sys
import traceback
import ctypes

# --- АБСОЛЮТНАЯ ЗАЩИТА ОТ ТИХИХ ВЫЛЕТОВ ---
def exception_hook(exctype, value, tb):
    error_message = "".join(traceback.format_exception(exctype, value, tb))
    print(error_message)
    try:
        ctypes.windll.user32.MessageBoxW(0, error_message, "Критическая ошибка скрипта", 0x10)
    except:
        pass
    sys.exit(1)

sys.excepthook = exception_hook

# --- СТАНДАРТНЫЕ БИБЛИОТЕКИ ---
import json
import os
import socket
import re
import threading
import quopri

# --- ВНЕШНИЕ БИБЛИОТЕКИ С ПРОВЕРКОЙ ---
try:
    import requests
    import psycopg2
    from psycopg2 import OperationalError
    from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QPushButton, QLineEdit, QLabel, 
                                 QTableWidget, QTableWidgetItem, QHeaderView, 
                                 QSystemTrayIcon, QMenu, QDialog, QMessageBox, 
                                 QTabWidget, QFormLayout, QFrame, 
                                 QAbstractItemView, QInputDialog, QGraphicsDropShadowEffect,
                                 QFileDialog)
    from PyQt6.QtGui import QIcon, QColor, QBrush, QPixmap, QPainter, QFont, QCursor
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QSharedMemory, QPropertyAnimation, QEasingCurve, QPoint, QRect
except ImportError as e:
    error_text = f"Не установлена нужная библиотека!\n\nДетали: {e}\n\nВыполните в консоли:\npip install PyQt6 psycopg2-binary requests"
    ctypes.windll.user32.MessageBoxW(0, error_text, "Ошибка импорта", 0x10)
    sys.exit(1)

CONFIG_FILE = "phone_settings.json"

# ==========================================
#      КОНФИГУРАЦИЯ
# ==========================================
def load_config():
    default_config = {
        "phone_ip": "192.168.1.100", 
        "phone_pass": "admin", 
        "phone_ext": "101",
        "local_ip": "0.0.0.0", 
        "syslog_port": 514,
        
        "pg_host": "127.0.0.1", 
        "pg_port": "5432", 
        "pg_dbname": "phonebook_db", 
        "pg_user": "postgres", 
        "pg_pass": "root",
        
        "vnc_pg_host": "172.16.2.2", 
        "vnc_pg_port": "5432", 
        "vnc_pg_dbname": "roman_vnc_free", 
        "vnc_pg_user": "roman_vnc_free", 
        "vnc_pg_pass": "",
        "vnc_owner": "",
        
        "autostart": False, 
        "tray_mode": True,
        "window_geometry": [100, 100, 1250, 750],
        "col_widths_contacts": [200, 150, 150, 150, 200, 100],
        "col_widths_history": [120, 150, 200, 150, 80]
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as file:
                default_config.update(json.load(file))
        except:
            pass
    return default_config

def save_config(configuration):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as file:
        json.dump(configuration, file, indent=4, ensure_ascii=False)

# ==========================================
#      БАЗА ДАННЫХ POSTGRESQL (ЛИЧНАЯ)
# ==========================================
class Database:
    def __init__(self, config):
        self.config = config
        self.connection = None
        self.connect_db()
        self.init_db()

    def connect_db(self):
        try:
            if self.connection and not self.connection.closed:
                return

            self.connection = psycopg2.connect(
                host=self.config.get("pg_host", "127.0.0.1"),
                port=self.config.get("pg_port", "5432"),
                dbname=self.config.get("pg_dbname", "phonebook_db"),
                user=self.config.get("pg_user", "postgres"),
                password=self.config.get("pg_pass", "root"),
                connect_timeout=3
            )
            self.connection.autocommit = True 
        except OperationalError as e:
            print(f"Ошибка подключения к PostgreSQL: {e}")
            self.connection = None

    def ensure_connection(self):
        if self.connection is None or self.connection.closed:
            self.connect_db()

    def init_db(self):
        self.ensure_connection()
        if not self.connection: return

        with self.connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contacts (
                    id SERIAL PRIMARY KEY, 
                    fio VARCHAR(255), 
                    phone VARCHAR(100), 
                    company VARCHAR(255), 
                    dept VARCHAR(255), 
                    note TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id SERIAL PRIMARY KEY, 
                    phone VARCHAR(100), 
                    name VARCHAR(255), 
                    direction VARCHAR(10), 
                    status VARCHAR(50) DEFAULT 'UNKNOWN', 
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def get_contacts(self):
        self.ensure_connection()
        if not self.connection: return []
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id, fio, phone, company, dept, note FROM contacts ORDER BY fio")
            return cursor.fetchall()

    def add_contact(self, data):
        self.ensure_connection()
        if not self.connection: return
        with self.connection.cursor() as cursor:
            cursor.execute("INSERT INTO contacts (fio, phone, company, dept, note) VALUES (%s, %s, %s, %s, %s)", data)

    def delete_contact(self, user_id):
        self.ensure_connection()
        if not self.connection: return
        with self.connection.cursor() as cursor:
            cursor.execute("DELETE FROM contacts WHERE id=%s", (user_id,))

    def add_history(self, phone, name, direction, status):
        self.ensure_connection()
        if not self.connection: return
        with self.connection.cursor() as cursor:
            cursor.execute("INSERT INTO history (phone, name, direction, status) VALUES (%s, %s, %s, %s)", (phone, name, direction, status))

    def get_history(self):
        self.ensure_connection()
        if not self.connection: return []
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id, phone, name, direction, status, timestamp FROM history ORDER BY id DESC LIMIT 300")
            return cursor.fetchall()

    def clear_history(self):
        self.ensure_connection()
        if not self.connection: return
        with self.connection.cursor() as cursor:
            cursor.execute("TRUNCATE TABLE history RESTART IDENTITY")

    def find_contact_info(self, phone):
        clean_phone = ''.join(filter(str.isdigit, str(phone)))
        if not clean_phone: return None
        suffix = clean_phone[-9:] if len(clean_phone) >= 9 else clean_phone
        
        self.ensure_connection()
        if self.connection:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    SELECT fio, company, dept FROM contacts 
                    WHERE replace(replace(phone, '-', ''), ' ', '') LIKE %s
                """, (f"%{suffix}",))
                result = cursor.fetchone()
                if result: return result
            
        vnc_conn = None
        vnc_owner = self.config.get("vnc_owner", "").strip()
        try:
            vnc_conn = psycopg2.connect(
                host=self.config.get("vnc_pg_host"), port=self.config.get("vnc_pg_port"),
                dbname=self.config.get("vnc_pg_dbname"), user=self.config.get("vnc_pg_user"),
                password=self.config.get("vnc_pg_pass"), connect_timeout=2
            )
            with vnc_conn.cursor() as cur:
                query = """
                    SELECT employee, branch, dept 
                    FROM user_computers 
                    WHERE replace(replace(tel, '-', ''), ' ', '') LIKE %s 
                    AND owner = %s
                """
                cur.execute(query, (f"%{suffix}", vnc_owner))
                row = cur.fetchone()
                if row: return row
        except Exception as e:
            pass
        finally:
            if vnc_conn and not vnc_conn.closed:
                vnc_conn.close()
                
        return None

    def is_duplicate(self, phone):
        clean_phone = ''.join(filter(str.isdigit, str(phone)))
        if not clean_phone: 
            return False
            
        suffix = clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone
        
        self.ensure_connection()
        if self.connection:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    SELECT 1 FROM contacts 
                    WHERE REGEXP_REPLACE(phone, '\\D', '', 'g') LIKE %s
                """, (f"%{suffix}",))
                if cursor.fetchone():
                    return True 
                
        vnc_conn = None
        vnc_owner = self.config.get("vnc_owner", "").strip()
        try:
            vnc_conn = psycopg2.connect(
                host=self.config.get("vnc_pg_host"), port=self.config.get("vnc_pg_port"),
                dbname=self.config.get("vnc_pg_dbname"), user=self.config.get("vnc_pg_user"),
                password=self.config.get("vnc_pg_pass"), connect_timeout=2
            )
            with vnc_conn.cursor() as cur:
                query = """
                    SELECT 1 FROM user_computers 
                    WHERE REGEXP_REPLACE(tel, '\\D', '', 'g') LIKE %s 
                    AND owner = %s
                """
                cur.execute(query, (f"%{suffix}", vnc_owner))
                if cur.fetchone():
                    return True 
        except Exception as e:
            pass
        finally:
            if vnc_conn and not vnc_conn.closed:
                vnc_conn.close()
                
        return False

# ==========================================
#      УМНЫЙ SIP ПАРСЕР (SYSLOG)
# ==========================================
class SyslogWorker(QThread):
    connection_status_signal = pyqtSignal(bool, str) 
    call_signal = pyqtSignal(str, str, str) 
    status_signal = pyqtSignal(str)         

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(0.5)
        
        self.active_call_id = None
        self.current_direction = None
        self.current_number = None
        self.is_talking = False

    def run(self):
        ip_address = self.config.get("local_ip", "0.0.0.0")
        port = int(self.config.get("syslog_port", 514))
        try:
            self.socket.bind((ip_address, port))
            self.connection_status_signal.emit(True, f"🟢 Активен (Порт {port})")
        except Exception as error:
            self.connection_status_signal.emit(False, f"🔴 Ошибка порта: {error}")
            return

        while self.running:
            try:
                data, _ = self.socket.recvfrom(65535)
                message = data.decode('utf-8', errors='ignore')
                if len(message) > 10:
                    self.process_sip(message)
            except socket.timeout:
                continue
            except Exception:
                pass

    def process_sip(self, message):
        if "REGISTER sip" in message or "NOTIFY sip" in message or "OPTIONS sip" in message:
            return 

        call_id_match = re.search(r'(?:Call-ID|i):\s?([^\r\n\s]+)', message, re.IGNORECASE)
        if not call_id_match: return
        packet_call_id = call_id_match.group(1).strip()

        my_extensions = [x.strip() for x in self.config.get("phone_ext", "").split(',')]

        if "INVITE sip:" in message:
            from_match = re.search(r'From:.*?sip:(\d+)', message, re.IGNORECASE)
            to_match = re.search(r'To:.*?sip:(\d+)', message, re.IGNORECASE)

            if from_match and to_match:
                sender = from_match.group(1)
                receiver = to_match.group(1)
                
                direction = None
                remote_party = None

                if sender in my_extensions: 
                    direction = "OUT"
                    remote_party = receiver
                elif receiver in my_extensions:
                    direction = "IN"
                    remote_party = sender
                
                if direction:
                    if self.active_call_id != packet_call_id:
                        self.active_call_id = packet_call_id
                        self.current_direction = direction
                        self.current_number = remote_party
                        self.is_talking = False
                        self.call_signal.emit(direction, remote_party, "")
        
        if packet_call_id == self.active_call_id:
            if "SIP/2.0 200 OK" in message and ("CSeq: 1 INVITE" in message or "INVITE" in message):
                if not self.is_talking:
                    self.is_talking = True
                    self.status_signal.emit("ANSWERED")

            is_bye = "BYE sip:" in message
            is_cancel = "CANCEL sip:" in message
            is_reject = "SIP/2.0 603" in message or "SIP/2.0 487" in message or "SIP/2.0 486" in message
            
            if is_bye or is_cancel or is_reject:
                final_status = "END"
                if self.current_direction == "IN" and not self.is_talking:
                    final_status = "MISSED"

                self.call_signal.emit(final_status, self.current_number, self.current_direction)
                self.active_call_id = None
                self.is_talking = False

    def force_reset(self):
        self.active_call_id = None
        self.is_talking = False

# ==========================================
#      КРАСИВОЕ ОКНО (TELEGRAM STYLE)
# ==========================================
class TelegramPopup(QDialog):
    closed_signal = pyqtSignal()

    def __init__(self, parent, call_type, number, name, info):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.width_size, self.height_size = 360, 110
        self.setGeometry(0, 0, self.width_size, self.height_size)
        self.dragging = False
        self.offset = QPoint()
        
        self.watchdog = QTimer(self)
        self.watchdog.timeout.connect(self.user_close)
        self.watchdog.start(60000)
        
        self.seconds = 0
        self.duration_timer = QTimer(self)
        self.duration_timer.timeout.connect(self.tick)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        self.frame = QFrame()
        self.frame.setStyleSheet("""
            QFrame { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #11998e, stop:1 #38ef7d); border-radius: 15px; }
            QLabel { color: white; font-family: 'Segoe UI', sans-serif; }
        """)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 4)
        self.frame.setGraphicsEffect(shadow)
        
        frame_layout = QHBoxLayout(self.frame)
        frame_layout.setSpacing(15)

        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(60, 60)
        self.draw_avatar(name if name else "?")
        frame_layout.addWidget(self.avatar_label)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        
        self.label_name = QLabel(name if name else "Неизвестный")
        self.label_name.setStyleSheet("font-size:13pt; font-weight:bold;")
        
        self.label_phone = QLabel(number)
        self.label_phone.setStyleSheet("font-size:11pt; opacity:0.8;")
        
        status_text = "Входящий звонок..." if call_type=="IN" else "Исходящий звонок..."
        self.label_status = QLabel(status_text)
        self.label_status.setStyleSheet("font-size:10pt; font-style:italic;")
        
        text_layout.addStretch()
        text_layout.addWidget(self.label_name)
        text_layout.addWidget(self.label_phone)
        text_layout.addWidget(self.label_status)
        text_layout.addStretch()
        frame_layout.addLayout(text_layout)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("background:rgba(0,0,0,0.1); color:white; border-radius:12px; border:none; font-weight:bold;")
        close_btn.clicked.connect(self.user_close)
        
        right_layout = QVBoxLayout()
        right_layout.addWidget(close_btn)
        right_layout.addStretch()
        frame_layout.addLayout(right_layout)
        
        main_layout.addWidget(self.frame)
        self.start_animation()

    def draw_avatar(self, text):
        pixmap = QPixmap(60, 60)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor("white")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 60, 60)
        painter.setPen(QColor("#11998e"))
        painter.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        painter.drawText(QRect(0, 0, 60, 60), Qt.AlignmentFlag.AlignCenter, text[0].upper())
        painter.end()
        self.avatar_label.setPixmap(pixmap)

    def start_animation(self):
        screen = QApplication.primaryScreen().availableGeometry()
        end_x = screen.width() - self.width_size - 20
        end_y = screen.height() - self.height_size - 50
        
        self.animation = QPropertyAnimation(self, b"pos")
        self.animation.setDuration(500)
        self.animation.setStartValue(QPoint(end_x, screen.height()))
        self.animation.setEndValue(QPoint(end_x, end_y))
        self.animation.setEasingCurve(QEasingCurve.Type.OutBack)
        self.animation.start()

    def set_answered(self):
        self.watchdog.stop() 
        self.label_status.setText("🟢 00:00")
        self.label_status.setStyleSheet("font-weight:bold; color:white;")
        self.duration_timer.start(1000)

    def tick(self):
        self.seconds += 1
        minutes, seconds = divmod(self.seconds, 60)
        self.label_status.setText(f"🟢 {minutes:02d}:{seconds:02d}")

    def user_close(self):
        self.closed_signal.emit()
        self.close()

    def mousePressEvent(self, event): 
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event): 
        if self.dragging:
            self.move(event.globalPosition().toPoint() - self.offset)

    def mouseReleaseEvent(self, event):
        self.dragging = False

# ==========================================
#      ГЛАВНОЕ ОКНО
# ==========================================
class PhoneApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.db = Database(self.config)
        self.syslog_thread = None
        self.popup_window = None
        
        geo = self.config.get("window_geometry", [100, 100, 1250, 750])
        self.setGeometry(*geo)
        
        self.setup_ui()
        self.reload_syslog()
        self.refresh_data()

    def setup_ui(self):
        self.setWindowTitle("IP Phone Manager Pro (Pure PostgreSQL)")
        self.setStyleSheet("""
            QMainWindow { background: #f0f2f5; }
            QTabWidget::pane { background: white; border-radius: 6px; border: 1px solid #ddd; }
            QTabBar::tab { background: #e4e6eb; color: #555; padding: 10px 20px; font-weight: bold; }
            QTabBar::tab:selected { background: white; color: #2ecc71; border-bottom: 2px solid #2ecc71; }
            QPushButton { background: #2ecc71; color: white; border-radius: 5px; padding: 8px; font-weight: bold; border:none; }
            QPushButton:hover { background: #27ae60; }
            QLineEdit { border: 1px solid #ccc; border-radius: 5px; padding: 6px; }
            QTableWidget { border: none; gridline-color: #f0f0f0; }
            QTableWidget::item:selected { background-color: #00FFFF; color: black; }
        """)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # --- ТОП ПАНЕЛЬ ---
        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Поиск контакта (Имя, Фирма, Телефон)...")
        self.search_input.textChanged.connect(self.refresh_data)
        
        self.btn_manual_dial = QPushButton("⌨️ Набрать номер")
        self.btn_manual_dial.setFixedWidth(150)
        self.btn_manual_dial.setStyleSheet("background: #3498db;") 
        self.btn_manual_dial.clicked.connect(self.show_dial_dialog)

        self.connection_status = QLabel("⚪ Инициализация...")
        self.connection_status.setStyleSheet("color: gray; font-weight: bold; padding: 0 10px;")
        
        settings_button = QPushButton("⚙ Настройки")
        settings_button.setStyleSheet("background:#95a5a6")
        settings_button.clicked.connect(self.show_settings_dialog)
        
        top_layout.addWidget(self.search_input, 1)
        top_layout.addWidget(self.btn_manual_dial)
        top_layout.addWidget(self.connection_status)
        top_layout.addWidget(settings_button)
        main_layout.addLayout(top_layout)

        tabs = QTabWidget()
        
        # --- 1. Вкладка Контакты ---
        contacts_tab = QWidget()
        contacts_layout = QVBoxLayout(contacts_tab)
        
        self.contacts_table = QTableWidget(0, 6)
        self.contacts_table.setHorizontalHeaderLabels(["Имя", "Тел", "Фирма", "Отдел", "Инфо", "Тип"])
        self.contacts_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.contacts_table.horizontalHeader().setStretchLastSection(True) 
        
        # Разрешаем выделение нескольких строк через Ctrl/Shift
        self.contacts_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.contacts_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        
        self.contacts_table.cellDoubleClicked.connect(self.call_selected_contact)
        self.contacts_table.itemSelectionChanged.connect(self.update_action_buttons)
        self.contacts_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.contacts_table.customContextMenuRequested.connect(self.open_contact_menu)

        col_widths = self.config.get("col_widths_contacts", [])
        for i, w in enumerate(col_widths):
            if i < 6: self.contacts_table.setColumnWidth(i, w)
                
        contacts_layout.addWidget(self.contacts_table)
        
        buttons_layout = QHBoxLayout()
        
        # Кнопка звонка
        self.btn_call = QPushButton("📞 Позвонить")
        self.btn_call.setEnabled(False)
        self.btn_call.clicked.connect(self.call_selected_contact)
        
        # Новая кнопка массового удаления
        self.btn_del_sel = QPushButton("🗑 Удалить выделенные")
        self.btn_del_sel.setStyleSheet("background:#e74c3c; color: white; font-weight: bold;")
        self.btn_del_sel.setEnabled(False)
        self.btn_del_sel.clicked.connect(self.delete_selected_contacts)
        
        btn_import_vcf = QPushButton("📥 Импорт (.vcf)")
        btn_import_vcf.setStyleSheet("background:#8e44ad; color: white; font-weight: bold;")
        btn_import_vcf.clicked.connect(self.import_vcf)

        btn_export_vcf = QPushButton("📤 Экспорт (.vcf)")
        btn_export_vcf.setStyleSheet("background:#2980b9; color: white; font-weight: bold;")
        btn_export_vcf.clicked.connect(self.export_vcf)

        add_btn = QPushButton("➕ Новый контакт")
        add_btn.setStyleSheet("background:#f39c12")
        add_btn.clicked.connect(self.show_add_contact_dialog)
        
        buttons_layout.addWidget(self.btn_call)
        buttons_layout.addWidget(self.btn_del_sel)
        buttons_layout.addStretch()
        buttons_layout.addWidget(btn_import_vcf)
        buttons_layout.addWidget(btn_export_vcf)
        buttons_layout.addWidget(add_btn)
        contacts_layout.addLayout(buttons_layout)
        tabs.addTab(contacts_tab, "Контакты")

        # --- 2. Вкладка История ---
        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(["Статус", "Время", "Имя", "Номер", "Call"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        
        hist_widths = self.config.get("col_widths_history", [])
        for i, w in enumerate(hist_widths):
            if i < 5: self.history_table.setColumnWidth(i, w)
                
        history_layout.addWidget(self.history_table)
        
        clear_btn = QPushButton("Очистить историю")
        clear_btn.setStyleSheet("background:#e74c3c")
        clear_btn.clicked.connect(self.clear_history)
        history_layout.addWidget(clear_btn, alignment=Qt.AlignmentFlag.AlignRight)
        tabs.addTab(history_tab, "История")
        
        main_layout.addWidget(tabs)

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.generate_icon())
        tray_menu = QMenu()
        tray_menu.addAction("Открыть", self.showNormal)
        tray_menu.addAction("Выход", self.close_application)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def generate_icon(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QBrush(QColor("#2ecc71")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, 60, 60)
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Arial", 30, QFont.Weight.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "P")
        painter.end()
        return QIcon(pixmap)

    def save_app_state(self):
        geometry = self.geometry()
        self.config.update({
            "window_geometry": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
            "col_widths_contacts": [self.contacts_table.columnWidth(i) for i in range(6)],
            "col_widths_history": [self.history_table.columnWidth(i) for i in range(5)]
        })
        save_config(self.config)

    def refresh_data(self):
        query = self.search_input.text().lower().strip()
        self.contacts_table.setRowCount(0)
        data_list = []
        
        # 1. Загрузка из Личной БД (PostgreSQL)
        try:
            for row in self.db.get_contacts():
                data_list.append((row[1], row[2], row[3], row[4], row[5], "Личный", row[0]))
        except Exception as e:
            print(f"Ошибка загрузки личной БД: {e}")
            
        # 2. Загрузка из базы VNC Manager (С фильтрацией по владельцу)
        vnc_conn = None
        vnc_owner = self.config.get("vnc_owner", "").strip()
        try:
            vnc_conn = psycopg2.connect(
                host=self.config.get("vnc_pg_host"), port=self.config.get("vnc_pg_port", "5432"),
                dbname=self.config.get("vnc_pg_dbname"), user=self.config.get("vnc_pg_user"),
                password=self.config.get("vnc_pg_pass"), connect_timeout=3
            )
            with vnc_conn.cursor() as cur:
                sql_query = """
                    SELECT employee, tel, branch, dept 
                    FROM user_computers 
                    WHERE tel != '' AND tel IS NOT NULL 
                    AND owner = %s
                """
                cur.execute(sql_query, (vnc_owner,))
                for r in cur.fetchall():
                    data_list.append((r[0], r[1], r[2], r[3], "", "VNC", None))
        except Exception as e:
            print(f"Критическая ошибка чтения VNC БД: {e}")
        finally:
            if vnc_conn and not vnc_conn.closed:
                vnc_conn.close()
        
        # 3. Фильтрация и Вывод на экран
        for item in data_list:
            search_str = f"{item[0]} {item[1]} {item[2]} {item[3]}".lower()
            if query and query not in search_str:
                continue
            
            row_idx = self.contacts_table.rowCount()
            self.contacts_table.insertRow(row_idx)
            
            for i in range(5):
                val = str(item[i]) if item[i] else ""
                cell = QTableWidgetItem(val)
                # Сохраняем ID базы данных в первую ячейку как невидимые пользовательские данные
                if i == 0: cell.setData(Qt.ItemDataRole.UserRole, item[6])
                self.contacts_table.setItem(row_idx, i, cell)
            
            type_item = QTableWidgetItem(item[5])
            color = "#2ecc71" if item[5] == "Личный" else "#9b59b6"
            type_item.setForeground(QBrush(QColor(color)))
            font = QFont(); font.setBold(True); type_item.setFont(font)
            self.contacts_table.setItem(row_idx, 5, type_item)

        # Сбросить состояния кнопок после обновления
        self.update_action_buttons()

        # 4. Вывод Истории Звонков
        self.history_table.setRowCount(0)
        try:
            for history_row in self.db.get_history():
                row_idx = self.history_table.rowCount()
                self.history_table.insertRow(row_idx)
                
                status = history_row[4]
                direction = history_row[3]
                
                if status == "MISSED":
                    status_text = "❌ Пропущенный"
                    color = "#e74c3c"
                elif direction == "OUT":
                    status_text = "📤 Исходящий"
                    color = "#2ecc71"
                else:
                    status_text = "📥 Входящий"
                    color = "#2ecc71"
                
                item_status = QTableWidgetItem(status_text)
                item_status.setForeground(QBrush(QColor(color)))
                self.history_table.setItem(row_idx, 0, item_status)
                self.history_table.setItem(row_idx, 1, QTableWidgetItem(str(history_row[5])))
                self.history_table.setItem(row_idx, 2, QTableWidgetItem(history_row[2]))
                self.history_table.setItem(row_idx, 3, QTableWidgetItem(history_row[1]))
                
                call_btn = QPushButton("Call")
                call_btn.setFixedSize(50, 25)
                call_btn.clicked.connect(lambda _, phone=history_row[1]: self.make_call(phone))
                self.history_table.setCellWidget(row_idx, 4, call_btn)
        except Exception as e:
            print(f"Ошибка загрузки истории: {e}")

    # ==========================================
    #      МАССОВОЕ УДАЛЕНИЕ ВЫДЕЛЕННЫХ
    # ==========================================
    def delete_selected_contacts(self):
        # 1. Получаем список уникальных индексов строк, которые выделил пользователь
        selected_rows = set(item.row() for item in self.contacts_table.selectedItems())
        if not selected_rows:
            return

        ids_to_delete = []
        vnc_skipped = 0

        # 2. Перебираем выделенные строки и фильтруем контакты
        for row in selected_rows:
            # ID хранится в 0-й колонке (Имя)
            item_name = self.contacts_table.item(row, 0)
            db_id = item_name.data(Qt.ItemDataRole.UserRole)
            
            # Тип базы хранится в 5-й колонке
            contact_type = self.contacts_table.item(row, 5).text()
            
            if contact_type == "Личный" and db_id:
                ids_to_delete.append(db_id)
            elif contact_type == "VNC":
                vnc_skipped += 1

        # 3. Проверки перед удалением
        if not ids_to_delete:
            QMessageBox.warning(self, "Внимание", 
                f"Вы выбрали только контакты из базы VNC Manager ({vnc_skipped} шт).\n\n"
                "Эти контакты доступны только для чтения и не могут быть удалены через это приложение.")
            return

        message = f"Вы действительно хотите навсегда удалить {len(ids_to_delete)} личных контактов?"
        if vnc_skipped > 0:
            message += f"\n\n(Внимание: {vnc_skipped} контактов VNC будут проигнорированы)"

        reply = QMessageBox.question(self, 'Подтверждение удаления', message,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                     QMessageBox.StandardButton.No)

        # 4. Выполнение транзакций удаления
        if reply == QMessageBox.StandardButton.Yes:
            success_count = 0
            for db_id in ids_to_delete:
                try:
                    self.db.delete_contact(db_id)
                    success_count += 1
                except Exception as e:
                    print(f"Ошибка удаления ID {db_id}: {e}")
            
            self.refresh_data()
            QMessageBox.information(self, "Успех", f"Успешно удалено контактов: {success_count}.")

    def update_action_buttons(self):
        """Интеллектуальное управление кнопками при выделении строк"""
        selected_rows = set(item.row() for item in self.contacts_table.selectedItems())
        count = len(selected_rows)
        
        # Кнопка звонка активна только если выделена РОВНО ОДНА строка
        self.btn_call.setEnabled(count == 1)
        if count == 1:
            name = self.contacts_table.item(list(selected_rows)[0], 0).text()
            self.btn_call.setText(f"📞 Звонок: {name[:10]}...")
        else:
            self.btn_call.setText("📞 Позвонить")

        # Кнопка удаления активна если выделена хотя бы одна строка
        self.btn_del_sel.setEnabled(count > 0)
        if count > 0:
            self.btn_del_sel.setText(f"🗑 Удалить выделенные ({count})")
        else:
            self.btn_del_sel.setText("🗑 Удалить выделенные")

    def open_contact_menu(self, pos):
        item = self.contacts_table.itemAt(pos)
        if not item: return
        row = item.row()
        db_id = self.contacts_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        contact_type = self.contacts_table.item(row, 5).text()
        
        if not db_id or contact_type == "VNC": 
            return 
            
        menu = QMenu()
        del_action = menu.addAction("❌ Удалить этот контакт")
        action = menu.exec(self.contacts_table.viewport().mapToGlobal(pos))
        
        if action == del_action:
            if QMessageBox.question(self, "Удаление", "Точно удалить контакт?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self.db.delete_contact(db_id)
                self.refresh_data()

    def show_dial_dialog(self):
        number, ok = QInputDialog.getText(self, "Ручной набор", "Введите номер телефона:")
        if ok and number: self.make_call(number)

    def call_selected_contact(self):
        # Звоним только если выделена одна строка
        selected_rows = set(item.row() for item in self.contacts_table.selectedItems())
        if len(selected_rows) == 1:
            row = list(selected_rows)[0]
            phone = self.contacts_table.item(row, 1).text()
            self.make_call(phone)

    def make_call(self, number):
        clean_number = ''.join(filter(str.isdigit, str(number)))
        if not clean_number: return
        ip, password = self.config["phone_ip"], self.config["phone_pass"]
        url = f"http://{ip}/cgi-bin/api-make_call?phonenumber={clean_number}&password={password}&account=0"
        threading.Thread(target=lambda: requests.get(url, timeout=3) if ip else None, daemon=True).start()

    def reload_syslog(self):
        if self.syslog_thread:
            self.syslog_thread.running = False
            self.syslog_thread.wait()
        
        self.syslog_thread = SyslogWorker(self.config)
        self.syslog_thread.connection_status_signal.connect(self.update_connection_status)
        self.syslog_thread.call_signal.connect(self.on_incoming_call)
        self.syslog_thread.status_signal.connect(self.on_call_answered)
        self.syslog_thread.start()

    def update_connection_status(self, is_ok, message):
        color = "#2ecc71" if is_ok else "#e74c3c"
        self.connection_status.setText(message)
        self.connection_status.setStyleSheet(f"color: {color}; font-weight: bold; padding: 0 10px;")

    def on_incoming_call(self, status, number, direction):
        if status in ["END", "MISSED"]:
            if self.popup_window:
                self.popup_window.close()
                self.popup_window = None
            
            info = self.db.find_contact_info(number)
            self.db.add_history(number, info[0] if info else "Неизвестный", direction, status)
            self.refresh_data()
            if status == "MISSED":
                self.tray_icon.showMessage("Пропущенный", f"От {number}", QSystemTrayIcon.MessageIcon.Warning)
        else:
            if self.popup_window: self.popup_window.close()
            info = self.db.find_contact_info(number)
            self.popup_window = TelegramPopup(self, status, number, info[0] if info else None, "")
            self.popup_window.closed_signal.connect(lambda: self.syslog_thread.force_reset())
            self.popup_window.show()

    def on_call_answered(self, status):
        if status == "ANSWERED" and self.popup_window:
            self.popup_window.set_answered()

    def show_settings_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Настройки системы")
        dialog.setMinimumWidth(600)
        main_layout = QVBoxLayout(dialog)
        
        tabs = QTabWidget()
        current_cfg = self.config
        
        tab_sip = QWidget()
        lay_sip = QFormLayout(tab_sip)
        input_ip = QLineEdit(current_cfg.get("phone_ip", ""))
        input_pass = QLineEdit(current_cfg.get("phone_pass", ""))
        input_pass.setEchoMode(QLineEdit.EchoMode.Password)
        input_ext = QLineEdit(current_cfg.get("phone_ext", ""))
        input_local_ip = QLineEdit(current_cfg.get("local_ip", ""))
        
        lay_sip.addRow("IP Телефона:", input_ip)
        lay_sip.addRow("Пароль (Web):", input_pass)
        lay_sip.addRow("Мой номер (EXT):", input_ext)
        lay_sip.addRow("Мой IP (Syslog):", input_local_ip)
        tabs.addTab(tab_sip, "📞 Телефония")

        def test_pg_connection(host, port, dbname, user, password, label_widget):
            label_widget.setText("⏳ Проверка...")
            label_widget.setStyleSheet("color: #e67e22; font-weight: bold;")
            QApplication.processEvents() 
            try:
                conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password, connect_timeout=3)
                conn.close()
                label_widget.setText("🟢 Успешно!")
                label_widget.setStyleSheet("color: #27ae60; font-weight: bold;")
            except Exception as e:
                label_widget.setText(f"🔴 Ошибка: {str(e).split(chr(10))[0]}")
                label_widget.setStyleSheet("color: #c0392b; font-weight: bold;")

        tab_db = QWidget()
        lay_db = QVBoxLayout(tab_db)
        
        form_db = QFormLayout()
        input_pg_host = QLineEdit(current_cfg.get("pg_host", "127.0.0.1"))
        input_pg_port = QLineEdit(str(current_cfg.get("pg_port", "5432")))
        input_pg_dbname = QLineEdit(current_cfg.get("pg_dbname", "phonebook_db"))
        input_pg_user = QLineEdit(current_cfg.get("pg_user", "postgres"))
        input_pg_pass = QLineEdit(current_cfg.get("pg_pass", ""))
        input_pg_pass.setEchoMode(QLineEdit.EchoMode.Password)
        
        form_db.addRow("Хост:", input_pg_host)
        form_db.addRow("Порт:", input_pg_port)
        form_db.addRow("Имя БД:", input_pg_dbname)
        form_db.addRow("Пользователь:", input_pg_user)
        form_db.addRow("Пароль:", input_pg_pass)
        lay_db.addLayout(form_db)

        h_test_db = QHBoxLayout()
        btn_test_db = QPushButton("🔄 Проверить БД")
        lbl_status_db = QLabel("Статус неизвестен")
        btn_test_db.clicked.connect(lambda: test_pg_connection(
            input_pg_host.text(), input_pg_port.text(), input_pg_dbname.text(), 
            input_pg_user.text(), input_pg_pass.text(), lbl_status_db
        ))
        h_test_db.addWidget(btn_test_db)
        h_test_db.addWidget(lbl_status_db, 1)
        lay_db.addLayout(h_test_db)
        lay_db.addStretch()
        tabs.addTab(tab_db, "🗄 Личная БД")

        tab_vnc = QWidget()
        lay_vnc = QVBoxLayout(tab_vnc)
        
        f_vnc_pg = QFormLayout()
        in_v_host = QLineEdit(current_cfg.get("vnc_pg_host", "172.16.2.2"))
        in_v_port = QLineEdit(str(current_cfg.get("vnc_pg_port", "5432")))
        in_v_name = QLineEdit(current_cfg.get("vnc_pg_dbname", "roman_vnc_free"))
        in_v_user = QLineEdit(current_cfg.get("vnc_pg_user", "roman_vnc_free"))
        in_v_pass = QLineEdit(current_cfg.get("vnc_pg_pass", ""))
        in_v_pass.setEchoMode(QLineEdit.EchoMode.Password)
        in_v_owner = QLineEdit(current_cfg.get("vnc_owner", ""))
        
        f_vnc_pg.addRow("Host:", in_v_host)
        f_vnc_pg.addRow("Port:", in_v_port)
        f_vnc_pg.addRow("DB Name:", in_v_name)
        f_vnc_pg.addRow("User:", in_v_user)
        f_vnc_pg.addRow("Password:", in_v_pass)
        f_vnc_pg.addRow("Логін в VNC (Owner):", in_v_owner)
        lay_vnc.addLayout(f_vnc_pg)

        h_test_vnc = QHBoxLayout()
        btn_test_vnc = QPushButton("🔄 Проверить VNC")
        lbl_status_vnc = QLabel("Статус неизвестен")
        btn_test_vnc.clicked.connect(lambda: test_pg_connection(
            in_v_host.text(), in_v_port.text(), in_v_name.text(), 
            in_v_user.text(), in_v_pass.text(), lbl_status_vnc
        ))
        h_test_vnc.addWidget(btn_test_vnc)
        h_test_vnc.addWidget(lbl_status_vnc, 1)
        lay_vnc.addLayout(h_test_vnc)
        lay_vnc.addStretch()
        tabs.addTab(tab_vnc, "🖥 База VNC")

        main_layout.addWidget(tabs)
        
        btn_save = QPushButton("💾 Сохранить и Перезапустить Сервисы")
        btn_save.setStyleSheet("background-color: #2980b9; color: white; padding: 10px; font-weight: bold;")
        
        def save_action():
            current_cfg.update({
                "phone_ip": input_ip.text(), "phone_pass": input_pass.text(),
                "phone_ext": input_ext.text(), "local_ip": input_local_ip.text(),
                "pg_host": input_pg_host.text(), "pg_port": input_pg_port.text(),
                "pg_dbname": input_pg_dbname.text(), "pg_user": input_pg_user.text(), "pg_pass": input_pg_pass.text(),
                "vnc_pg_host": in_v_host.text(), "vnc_pg_port": in_v_port.text(), "vnc_pg_dbname": in_v_name.text(),
                "vnc_pg_user": in_v_user.text(), "vnc_pg_pass": in_v_pass.text(),
                "vnc_owner": in_v_owner.text()
            })
            save_config(current_cfg)
            self.db.config = current_cfg
            self.db.connect_db() 
            self.db.init_db()
            self.reload_syslog()
            self.refresh_data()
            dialog.accept()

        btn_save.clicked.connect(save_action)
        main_layout.addWidget(btn_save)
        dialog.exec()
        
    def show_add_contact_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Новый личный контакт")
        layout = QFormLayout(dialog)
        
        inputs = [QLineEdit() for _ in range(5)]
        labels = ["ФИО", "Тел", "Фирма", "Отдел", "Инфо"]
        
        for i, label_text in enumerate(labels):
            layout.addRow(label_text, inputs[i])
            
        save_btn = QPushButton("OK")
        save_btn.setStyleSheet("background: #2ecc71; color: white; padding: 5px; font-weight: bold;")
        
        def save_new_contact():
            data = tuple(x.text() for x in inputs)
            self.db.add_contact(data)
            self.refresh_data()
            dialog.accept()

        save_btn.clicked.connect(save_new_contact)
        layout.addRow(save_btn)
        dialog.exec()
        
    def clear_history(self):
        self.db.clear_history()
        self.refresh_data()

    # ==========================================
    #      ИМПОРТ И ЭКСПОРТ ANDROID (VCF)
    # ==========================================
    def import_vcf(self):
        """Продвинутый парсер: поддерживает Quoted-Printable и захватывает ВСЕ номера телефонов контакта"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл контактов Android", "", "vCard Files (*.vcf);;All Files (*)"
        )
        if not file_path:
            return
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            vcards = content.split('BEGIN:VCARD')
            added_count = 0
            skipped_count = 0
            
            self.connection_status.setText("⏳ Импорт контактов...")
            QApplication.processEvents()
            
            def decode_field(match):
                if not match: 
                    return ""
                params = match.group(1) or ""
                val = match.group(2)
                
                if "QUOTED-PRINTABLE" in params.upper():
                    try:
                        decoded_bytes = quopri.decodestring(val.encode('utf-8'))
                        return decoded_bytes.decode('utf-8').strip()
                    except Exception as e:
                        print(f"Ошибка декодирования QP: {e}")
                        pass
                
                val = re.sub(r'\n[ \t]', '', val)
                return val.strip()

            regex_tpl = r'^{}(;[^:]*)?:([\s\S]*?)(?=^[A-Z0-9\-]+(?:;[^:]*)?:|^END:VCARD)'
            
            for vcard in vcards:
                if 'END:VCARD' not in vcard: 
                    continue
                
                fn_match = re.search(regex_tpl.format("FN"), vcard, re.MULTILINE | re.IGNORECASE)
                fio = decode_field(fn_match) if fn_match else "Без имени (Импорт)"
                
                org_match = re.search(regex_tpl.format("ORG"), vcard, re.MULTILINE | re.IGNORECASE)
                company, dept = "", ""
                org_raw = decode_field(org_match)
                if org_raw:
                    org_parts = org_raw.split(';')
                    company = org_parts[0].strip() if len(org_parts) > 0 else ""
                    dept = org_parts[1].strip() if len(org_parts) > 1 else ""
                    
                note_match = re.search(regex_tpl.format("NOTE"), vcard, re.MULTILINE | re.IGNORECASE)
                note = decode_field(note_match) if note_match else "Android"
                
                # ИЗМЕНЕНИЕ: Ищем ВСЕ номера телефонов в карточке через finditer
                tel_matches = list(re.finditer(regex_tpl.format("TEL"), vcard, re.MULTILINE | re.IGNORECASE))
                
                for tel_match in tel_matches:
                    raw_phone = decode_field(tel_match)
                    if not raw_phone: 
                        continue 
                    
                    clean_phone = ''.join(filter(str.isdigit, raw_phone))
                    if not clean_phone:
                        continue
                    
                    if len(clean_phone) >= 9:
                        formatted_phone = "0" + clean_phone[-9:]
                    else:
                        formatted_phone = clean_phone

                    if self.db.is_duplicate(formatted_phone):
                        skipped_count += 1
                        continue
                    
                    # Записываем в БД каждый найденный номер
                    self.db.add_contact((fio, formatted_phone, company, dept, note))
                    added_count += 1
            
            self.refresh_data()
            self.connection_status.setText(f"🟢 Активен (Порт {self.config.get('syslog_port', 514)})")
            
            report_msg = (
                f"Обработка файла завершена!\n\n"
                f"✅ Успешно добавлено номеров: {added_count}\n"
                f"⏭ Пропущено дубликатов: {skipped_count}\n\n"
                f"ℹ️ Обработаны все дополнительные телефоны внутри карточек."
            )
            QMessageBox.information(self, "Отчет об импорте", report_msg)
            
        except Exception as e:
            self.connection_status.setText("🔴 Ошибка импорта")
            QMessageBox.critical(self, "Ошибка импорта", f"Не удалось прочитать или импортировать VCF файл:\n{e}")

    def export_vcf(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить контакты для Android", "phone_contacts_export.vcf", "vCard Files (*.vcf)"
        )
        if not file_path:
            return
            
        try:
            contacts = self.db.get_contacts()
            
            with open(file_path, 'w', encoding='utf-8') as f:
                for row in contacts:
                    fio = row[1] or ""
                    phone = row[2] or ""
                    company = row[3] or ""
                    dept = row[4] or ""
                    note = row[5] or ""
                    
                    if not phone:
                        continue
                        
                    f.write("BEGIN:VCARD\n")
                    f.write("VERSION:3.0\n") 
                    f.write(f"FN:{fio}\n")
                    f.write(f"TEL;TYPE=CELL:{phone}\n")
                    
                    org_str = f"{company};{dept}".strip(';')
                    if org_str:
                        f.write(f"ORG:{org_str}\n")
                        
                    if note:
                        clean_note = note.replace('\n', ' ').replace('\r', '')
                        f.write(f"NOTE:{clean_note}\n")
                        
                    f.write("END:VCARD\n")
                    
            QMessageBox.information(self, "Экспорт завершен", f"Успешно экспортировано {len(contacts)} контактов!")
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка экспорта", f"Не удалось сохранить контакты:\n{e}")

    def closeEvent(self, event):
        event.ignore()
        self.save_app_state()
        if self.config["tray_mode"]:
            self.hide()
            self.tray_icon.showMessage("IP Phone", "Свернуто в трей", QSystemTrayIcon.MessageIcon.Information, 2000)
        else:
            self.close_application()

    def close_application(self):
        self.save_app_state()
        if self.syslog_thread:
            self.syslog_thread.running = False
        QApplication.quit()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    if not QSharedMemory("IPPhone_Universal_V4").create(1):
        sys.exit(0)
    window = PhoneApp()
    window.show()
    sys.exit(app.exec())