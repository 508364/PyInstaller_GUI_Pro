import sys
import os
import subprocess
import platform
import zipfile
import tempfile
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QFileDialog, QCheckBox, QComboBox,
    QTextEdit, QGroupBox, QGridLayout, QSpinBox, QListWidget,
    QListWidgetItem, QAbstractItemView, QMessageBox, QSplitter,
    QTabWidget, QRadioButton, QScrollArea
)
from PyQt5.QtCore import Qt, QProcess, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon

class PythonExtractThread(QThread):
    # 信号定义
    progress_updated = pyqtSignal(str, str)  # 消息, 级别
    finished = pyqtSignal(bool, str)  # 成功标志, 结果信息
    python_path_updated = pyqtSignal(str, str)  # python路径, 解压目录
    
    def __init__(self, python_zip):
        super().__init__()
        self.python_zip = python_zip
        self.python_path = None
        self.extracted_python_dir = None
    
    def run(self):
        """后台解压Python压缩包"""
        self.progress_updated.emit("开始解压Python压缩包...", "info")
        
        if not os.path.exists(self.python_zip):
            self.progress_updated.emit(f"错误: Python压缩包不存在: {self.python_zip}", "error")
            self.finished.emit(False, "Python压缩包不存在")
            return
        
        try:
            # 创建临时目录，避免中文路径导致的编码问题
            self.extracted_python_dir = tempfile.mkdtemp(prefix='pyinstaller_')
            self.progress_updated.emit(f"正在解压Python到临时目录: {self.extracted_python_dir}", "info")
            
            # 解压压缩包
            with zipfile.ZipFile(self.python_zip, 'r') as zip_ref:
                # 获取文件总数用于进度计算
                total_files = len(zip_ref.infolist())
                extracted_files = 0
                last_progress = -1
                
                for file_info in zip_ref.infolist():
                    zip_ref.extract(file_info, self.extracted_python_dir)
                    extracted_files += 1
                    
                    # 计算当前进度百分比
                    progress = int((extracted_files / total_files) * 100)
                    
                    # 每达到10%的整数倍时更新一次进度
                    if progress % 10 == 0 and progress > last_progress:
                        self.progress_updated.emit(f"解压进度: {progress}% ({extracted_files}/{total_files}文件)", "info")
                        last_progress = progress
            
            # 找到python.exe路径
            self.python_path = os.path.join(self.extracted_python_dir, 'python.exe')
            if not os.path.exists(self.python_path):
                self.progress_updated.emit("错误: 未找到python.exe", "error")
                self.finished.emit(False, "未找到python.exe")
                return
            
            # 修改python39._pth文件，启用site模块并添加必要的路径
            pth_file = os.path.join(self.extracted_python_dir, 'python39._pth')
            if os.path.exists(pth_file):
                with open(pth_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 取消注释import site
                content = content.replace('#import site', 'import site')
                
                # 添加必要的路径配置
                if 'Lib' not in content:
                    # 确保Lib目录和Lib/site-packages都在路径中
                    lines = content.split('\n')
                    updated = False
                    for i, line in enumerate(lines):
                        if line.strip() == '.':
                            # 在当前目录之后添加Lib目录
                            lines.insert(i+1, 'Lib')
                            updated = True
                            break
                    if not updated:
                        # 如果没有找到当前目录，直接添加Lib目录
                        lines.append('Lib')
                    content = '\n'.join(lines)
                
                with open(pth_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                self.progress_updated.emit("已修改python39._pth，启用site模块并添加Lib路径", "info")
            
            self.progress_updated.emit(f"成功解压Python，可执行文件路径: {self.python_path}", "success")
            self.python_path_updated.emit(self.python_path, self.extracted_python_dir)
            self.finished.emit(True, "Python解压成功")
        except Exception as e:
            self.progress_updated.emit(f"解压Python失败: {str(e)}", "error")
            self.finished.emit(False, f"解压Python失败: {str(e)}")

class PyInstallerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.process = None
        self.python_path = None
        self.extracted_python_dir = None
        self.python_thread = None
        self.close_pending = False
        # 检测系统信息
        self.detect_system()
        # 启动后台线程解压Python
        self.start_python_extract()
        # 显示窗口
        self.show()
    
    def detect_system(self):
        """检测系统信息，确定使用哪个Python压缩包"""
        self.system_arch = platform.architecture()[0]
        self.append_log(f"系统架构: {self.system_arch}", "info")
        
        # 获取程序所在目录，确保在被打包成exe后仍能找到压缩包
        if getattr(sys, 'frozen', False):
            # 程序被打包成exe的情况
            if hasattr(sys, '_MEIPASS'):
                # 单文件模式：使用临时解压目录
                program_dir = sys._MEIPASS
            else:
                # 目录模式：使用程序可执行文件目录
                program_dir = os.path.dirname(sys.executable)
        else:
            # 正常运行Python脚本的情况
            program_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 根据系统架构选择对应的Python压缩包
        if self.system_arch == '64bit':
            self.python_zip = os.path.join(program_dir, 'python-3.9.13-embed-amd64.zip')
        else:
            self.python_zip = os.path.join(program_dir, 'python-3.9.13-embed-win32.zip')
        
        self.append_log(f"将使用Python压缩包: {os.path.basename(self.python_zip)}", "info")
    
    def start_python_extract(self):
        """启动后台线程解压Python"""
        # 创建并启动解压线程
        self.python_thread = PythonExtractThread(self.python_zip)
        
        # 连接信号
        self.python_thread.progress_updated.connect(self.append_log)
        self.python_thread.python_path_updated.connect(self.on_python_extracted)
        self.python_thread.finished.connect(self.on_python_extract_finished)
        
        # 启动线程
        self.python_thread.start()
    
    def on_python_extracted(self, python_path, extracted_dir):
        """Python解压完成后的处理"""
        self.python_path = python_path
        self.extracted_python_dir = extracted_dir
    
    def on_python_extract_finished(self, success, message):
        """解压线程完成后的处理"""
        if success:
            self.append_log("Python解压完成，软件已准备就绪", "success")
        else:
            self.append_log(f"Python解压失败: {message}", "error")
        
        # 检查是否有关闭请求
        if self.close_pending:
            self.really_close()
    
    def extract_python(self):
        """已废弃，使用后台线程解压Python"""
        pass
    
    def init_ui(self):
        self.setWindowTitle("PyInstaller GUI - Python打包器")
        self.setGeometry(100, 100, 1200, 800)
        self.setMinimumSize(1000, 600)
        
        # 设置全局字体
        font = QFont("微软雅黑", 9)
        QApplication.setFont(font)
        
        # 设置全局样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f0f0;
                font-family: '微软雅黑', '黑体', sans-serif;
            }
            QGroupBox {
                border: 1px solid #d0d0d0;
                border-radius: 5px;
                margin-top: 10px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
                background-color: #f0f0f0;
            }
            
            /* 卡片悬浮效果 */
            QWidget[card="true"] {
                background-color: white;
                border-radius: 8px;
                padding: 15px;
                border: 1px solid #e0e0e0;
            }
            QWidget[card="true"]:hover {
                border-color: #4CAF50;
                background-color: #f8fff8;
            }
            
            /* 按钮样式 */
            QPushButton {
                background-color: #e0e0e0;
                border: 1px solid #d0d0d0;
                border-radius: 3px;
                padding: 5px 10px;
                font-family: '微软雅黑', '黑体', sans-serif;
            }
            QPushButton:hover {
                background-color: #4CAF50;
                color: white;
                border-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3e8e41;
            }
            
            /* 输入框样式 */
            QLineEdit {
                border: 1px solid #d0d0d0;
                border-radius: 3px;
                padding: 5px;
                background-color: white;
                font-family: '微软雅黑', '黑体', sans-serif;
            }
            QLineEdit:hover {
                border-color: #4CAF50;
                background-color: #f8fff8;
            }
            QLineEdit:focus {
                border-color: #4CAF50;
                background-color: white;
            }
            
            /* 复选框样式 */
            QCheckBox {
                padding: 5px;
                font-family: '微软雅黑', '黑体', sans-serif;
            }
            QCheckBox:hover {
                color: #4CAF50;
            }
            
            /* 单选按钮样式 */
            QRadioButton {
                padding: 5px;
                font-family: '微软雅黑', '黑体', sans-serif;
            }
            QRadioButton:hover {
                color: #4CAF50;
            }
            
            /* 标签样式 */
            QLabel {
                font-family: '微软雅黑', '黑体', sans-serif;
            }
            
            /* 标签页样式 */
            QTabWidget::pane {
                border: 1px solid #d0d0d0;
                background-color: white;
            }
            QTabBar::tab {
                background-color: #e0e0e0;
                border: 1px solid #d0d0d0;
                border-bottom-color: transparent;
                padding: 8px 16px;
                margin-right: 2px;
                font-family: '微软雅黑', '黑体', sans-serif;
            }
            QTabBar::tab:hover {
                background-color: #d0d0d0;
            }
            QTabBar::tab:selected {
                background-color: white;
                border-bottom-color: white;
            }
            
            /* 列表框样式 */
            QListWidget {
                border: 1px solid #d0d0d0;
                border-radius: 3px;
                background-color: white;
                font-family: '微软雅黑', '黑体', sans-serif;
            }
            QListWidget:hover {
                border-color: #4CAF50;
            }
            
            /* 文本编辑框样式 */
            QTextEdit {
                border: 1px solid #d0d0d0;
                border-radius: 3px;
                background-color: white;
                font-family: 'Consolas', 'Courier New', monospace;
            }
            QTextEdit:hover {
                border-color: #4CAF50;
            }
            
            /* 滚动区域样式 */
            QScrollArea {
                background-color: transparent;
            }
        """)
        
        # 主布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # 创建左右分割布局
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        
        # 左侧面板 - 参数设置
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        # 创建标签页
        self.tabs = QTabWidget()
        left_layout.addWidget(self.tabs)
        
        # 基本设置标签 - 包含所有设置
        self.basic_tab = QWidget()
        self.tabs.addTab(self.basic_tab, "基本设置")
        self.setup_basic_tab()
        
        # 附加文件标签
        self.files_tab = QWidget()
        self.tabs.addTab(self.files_tab, "附加文件")
        self.setup_files_tab()
        
        # 附加库标签
        self.additional_libs_tab = QWidget()
        self.tabs.addTab(self.additional_libs_tab, "附加库")
        self.setup_additional_libs_tab()
        
        # 高级设置标签
        self.advanced_tab = QWidget()
        self.tabs.addTab(self.advanced_tab, "高级设置")
        self.setup_advanced_tab()
        
        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.clear_log_btn = QPushButton("清除日志")
        self.clear_log_btn.clicked.connect(self.clear_log)
        button_layout.addWidget(self.clear_log_btn)
        
        self.pack_btn = QPushButton("开始打包")
        self.pack_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 8px 20px;")
        self.pack_btn.clicked.connect(self.start_packaging)
        button_layout.addWidget(self.pack_btn)
        
        left_layout.addLayout(button_layout)
        
        # 右侧面板 - 日志输出
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        log_label = QLabel("打包日志:")
        log_label.setStyleSheet("font-weight: bold; margin-bottom: 5px;")
        right_layout.addWidget(log_label)
        
        # 日志输出
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #f8f8f8; border: 1px solid #d0d0d0; border-radius: 3px;")
        self.log_text.setAcceptRichText(True)
        font = QFont("微软雅黑", 9)
        self.log_text.setFont(font)
        right_layout.addWidget(self.log_text)
        
        # 添加到分割器
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        
        # 设置分割比例
        splitter.setSizes([600, 600])
    
    def setup_basic_tab(self):
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # 创建滚动区域的内容 widget
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setSpacing(15)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 将滚动区域设置为 tab 的主 widget
        main_layout = QVBoxLayout(self.basic_tab)
        main_layout.addWidget(scroll_area)
        scroll_area.setWidget(scroll_content)
        
        # 卡片1: 基本信息
        card1 = QWidget()
        card1.setProperty("card", True)
        card1_layout = QGridLayout(card1)
        card1_layout.setSpacing(10)
        
        # 源文件选择
        card1_layout.addWidget(QLabel("Python脚本:"), 0, 0, 1, 1)
        self.source_edit = QLineEdit()
        card1_layout.addWidget(self.source_edit, 0, 1, 1, 3)
        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self.browse_source)
        card1_layout.addWidget(browse_btn, 0, 4, 1, 1)
        
        # 输出目录
        card1_layout.addWidget(QLabel("输出目录:"), 1, 0, 1, 1)
        self.output_edit = QLineEdit()
        self.output_edit.setText("./dist")
        card1_layout.addWidget(self.output_edit, 1, 1, 1, 3)
        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self.browse_output)
        card1_layout.addWidget(browse_btn, 1, 4, 1, 1)
        
        # 程序名称
        card1_layout.addWidget(QLabel("程序名称:"), 2, 0, 1, 1)
        self.name_edit = QLineEdit()
        card1_layout.addWidget(self.name_edit, 2, 1, 1, 4)
        
        # 图标设置
        card1_layout.addWidget(QLabel("程序图标:"), 3, 0, 1, 1)
        self.icon_edit = QLineEdit()
        card1_layout.addWidget(self.icon_edit, 3, 1, 1, 3)
        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self.browse_icon)
        card1_layout.addWidget(browse_btn, 3, 4, 1, 1)
        
        layout.addWidget(card1)
        
        # 卡片2: 打包模式
        card2 = QWidget()
        card2.setProperty("card", True)
        card2_layout = QVBoxLayout(card2)
        
        # 打包类型（单文件/目录）
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("打包类型:"))
        
        self.single_file_rb = QRadioButton("单文件 (-F)")
        self.single_file_rb.setChecked(True)
        type_layout.addWidget(self.single_file_rb)
        
        self.folder_rb = QRadioButton("目录 (-D)")
        type_layout.addWidget(self.folder_rb)
        type_layout.addStretch()
        card2_layout.addLayout(type_layout)
        
        # 窗口模式
        self.windowed_cb = QCheckBox("窗口模式 (-w)")
        self.windowed_cb.setChecked(True)
        card2_layout.addWidget(self.windowed_cb)
        
        # 调试模式
        # 调试选项已移动到高级设置标签页
        
        layout.addWidget(card2)
        
        # 卡片3: 依赖管理
        card4 = QWidget()
        card4.setProperty("card", True)
        card4_layout = QVBoxLayout(card4)
        
        dep_label = QLabel("依赖管理:")
        dep_label.setStyleSheet("font-weight: bold; margin-bottom: 10px;")
        card4_layout.addWidget(dep_label)
        
        # 拖拽区域
        self.drop_area = QLabel("拖放whl文件或txt依赖文件到此处，或点击按钮添加")
        self.drop_area.setAlignment(Qt.AlignCenter)
        self.drop_area.setStyleSheet("""
            QLabel {
                border: 2px dashed #ccc;
                border-radius: 5px;
                padding: 20px;
                background-color: #f9f9f9;
                min-height: 80px;
            }
            QLabel:hover {
                border-color: #4CAF50;
                background-color: #f0f8f0;
            }
        """)
        self.drop_area.setAcceptDrops(True)
        card4_layout.addWidget(self.drop_area)
        
        # 依赖操作按钮
        dep_btn_layout = QHBoxLayout()
        
        self.install_wheel_btn = QPushButton("安装WHL包")
        self.install_wheel_btn.clicked.connect(self.install_wheel)
        dep_btn_layout.addWidget(self.install_wheel_btn)
        
        self.import_requirements_btn = QPushButton("导入requirements.txt")
        self.import_requirements_btn.clicked.connect(self.import_requirements)
        dep_btn_layout.addWidget(self.import_requirements_btn)
        
        self.detect_deps_btn = QPushButton("自动检测依赖")
        self.detect_deps_btn.clicked.connect(self.detect_dependencies)
        dep_btn_layout.addWidget(self.detect_deps_btn)
        
        self.install_pip_btn = QPushButton("安装PIP包")
        self.install_pip_btn.clicked.connect(self.install_pip_package)
        dep_btn_layout.addWidget(self.install_pip_btn)
        
        dep_btn_layout.addStretch()
        card4_layout.addLayout(dep_btn_layout)
        
        # PIP包输入
        pip_layout = QHBoxLayout()
        pip_layout.addWidget(QLabel("PIP包名称:"))
        self.pip_package_edit = QLineEdit()
        self.pip_package_edit.setPlaceholderText("多个包用空格分隔")
        pip_layout.addWidget(self.pip_package_edit)
        card4_layout.addLayout(pip_layout)
        
        layout.addWidget(card4)
        
        # 自适应空白
        layout.addStretch()
    
    def setup_files_tab(self):
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # 创建滚动区域的内容 widget
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setSpacing(15)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 将滚动区域设置为 tab 的主 widget
        main_layout = QVBoxLayout(self.files_tab)
        main_layout.addWidget(scroll_area)
        scroll_area.setWidget(scroll_content)
        
        # 附加文件列表
        layout.addWidget(QLabel("附加文件和目录:"))
        
        self.files_list = QListWidget()
        self.files_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.files_list.setMinimumHeight(200)
        layout.addWidget(self.files_list)
        
        # 文件操作按钮
        btn_layout = QHBoxLayout()
        
        add_file_btn = QPushButton("添加文件")
        add_file_btn.clicked.connect(self.add_file)
        btn_layout.addWidget(add_file_btn)
        
        add_dir_btn = QPushButton("添加目录")
        add_dir_btn.clicked.connect(self.add_directory)
        btn_layout.addWidget(add_dir_btn)
        
        remove_btn = QPushButton("移除选中项")
        remove_btn.clicked.connect(self.remove_files)
        btn_layout.addWidget(remove_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
    
    def setup_additional_libs_tab(self):
        """设置附加库标签页"""
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # 创建滚动区域的内容 widget
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setSpacing(15)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 将滚动区域设置为 tab 的主 widget
        main_layout = QVBoxLayout(self.additional_libs_tab)
        main_layout.addWidget(scroll_area)
        scroll_area.setWidget(scroll_content)
        
        # 附加库列表卡片
        card1 = QWidget()
        card1.setProperty("card", True)
        card1_layout = QVBoxLayout(card1)
        
        card1_layout.addWidget(QLabel("附加库列表:"))
        
        self.additional_libs_list = QListWidget()
        self.additional_libs_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.additional_libs_list.setMinimumHeight(200)
        card1_layout.addWidget(self.additional_libs_list)
        
        layout.addWidget(card1)
        
        # 添加附加库卡片
        card2 = QWidget()
        card2.setProperty("card", True)
        card2_layout = QVBoxLayout(card2)
        
        card2_layout.addWidget(QLabel("添加附加库:"))
        
        add_lib_layout = QHBoxLayout()
        self.lib_name_edit = QLineEdit()
        self.lib_name_edit.setPlaceholderText("输入库名称，如: psutil, requests")
        add_lib_layout.addWidget(self.lib_name_edit)
        
        add_lib_btn = QPushButton("添加")
        add_lib_btn.clicked.connect(self.add_additional_lib)
        add_lib_layout.addWidget(add_lib_btn)
        
        card2_layout.addLayout(add_lib_layout)
        
        # 批量操作
        batch_layout = QHBoxLayout()
        
        import_libs_btn = QPushButton("从文件导入")
        import_libs_btn.clicked.connect(self.import_additional_libs)
        batch_layout.addWidget(import_libs_btn)
        
        remove_lib_btn = QPushButton("移除选中项")
        remove_lib_btn.clicked.connect(self.remove_additional_libs)
        batch_layout.addWidget(remove_lib_btn)
        
        clear_libs_btn = QPushButton("清空列表")
        clear_libs_btn.clicked.connect(self.clear_additional_libs)
        batch_layout.addWidget(clear_libs_btn)
        
        batch_layout.addStretch()
        card2_layout.addLayout(batch_layout)
        
        layout.addWidget(card2)
        
        # 说明卡片
        card3 = QWidget()
        card3.setProperty("card", True)
        card3_layout = QVBoxLayout(card3)
        
        card3_layout.addWidget(QLabel("说明:"))
        
        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setPlainText("附加库用于解决PyInstaller无法自动检测到的依赖问题。\n\n" +
                               "1. 手动添加: 直接输入库名称并点击添加按钮\n" +
                               "2. 从文件导入: 支持从文本文件(.txt)导入库列表，每行一个库名称\n" +
                               "3. 已添加的库会在打包时自动添加到隐藏导入列表中")
        info_text.setMinimumHeight(100)
        card3_layout.addWidget(info_text)
        
        layout.addWidget(card3)
        
        # 自适应空白
        layout.addStretch()
    
    def setup_advanced_tab(self):
        """设置高级设置标签页"""
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # 创建滚动区域的内容 widget
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setSpacing(15)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 将滚动区域设置为 tab 的主 widget
        main_layout = QVBoxLayout(self.advanced_tab)
        main_layout.addWidget(scroll_area)
        scroll_area.setWidget(scroll_content)
        
        # 调试和优化选项卡片
        card1 = QWidget()
        card1.setProperty("card", True)
        card1_layout = QGridLayout(card1)
        card1_layout.setSpacing(10)
        
        # 调试选项
        card1_layout.addWidget(QLabel("调试选项:"), 0, 0, 1, 2)
        
        self.debug_cb = QCheckBox("启用调试输出")
        card1_layout.addWidget(self.debug_cb, 1, 0, 1, 2)
        
        # 优化级别
        card1_layout.addWidget(QLabel("优化级别:"), 2, 0, 1, 1)
        
        self.optimize_combo = QComboBox()
        self.optimize_combo.addItems(["0 (无优化)", "1 (基本优化)", "2 (完全优化)"])
        card1_layout.addWidget(self.optimize_combo, 2, 1, 1, 1)
        
        # 清理构建文件
        self.clean_cb = QCheckBox("清理构建文件")
        card1_layout.addWidget(self.clean_cb, 3, 0, 1, 2)
        
        # 仅生成spec文件
        self.spec_only_cb = QCheckBox("仅生成spec文件，不打包")
        card1_layout.addWidget(self.spec_only_cb, 4, 0, 1, 2)
        
        layout.addWidget(card1)
        
        # UPX和压缩选项卡片
        card2 = QWidget()
        card2.setProperty("card", True)
        card2_layout = QGridLayout(card2)
        card2_layout.setSpacing(10)
        
        # UPX选项
        card2_layout.addWidget(QLabel("UPX选项:"), 0, 0, 1, 2)
        
        self.noupx_cb = QCheckBox("不使用UPX压缩")
        card2_layout.addWidget(self.noupx_cb, 1, 0, 1, 2)
        
        # UPX排除文件
        card2_layout.addWidget(QLabel("UPX排除文件:"), 2, 0, 1, 1)
        self.upx_exclude_edit = QLineEdit()
        self.upx_exclude_edit.setPlaceholderText("多个文件用逗号分隔")
        card2_layout.addWidget(self.upx_exclude_edit, 2, 1, 1, 1)
        
        # UPX目录
        card2_layout.addWidget(QLabel("UPX目录:"), 3, 0, 1, 1)
        upx_layout = QHBoxLayout()
        self.upx_dir_edit = QLineEdit()
        upx_layout.addWidget(self.upx_dir_edit)
        upx_browse_btn = QPushButton("浏览")
        upx_browse_btn.clicked.connect(self.browse_upx_dir)
        upx_layout.addWidget(upx_browse_btn)
        card2_layout.addLayout(upx_layout, 3, 1, 1, 1)
        
        layout.addWidget(card2)
        
        # 高级选项卡片
        card3 = QWidget()
        card3.setProperty("card", True)
        card3_layout = QGridLayout(card3)
        card3_layout.setSpacing(10)
        
        # 隐藏导入
        card3_layout.addWidget(QLabel("隐藏导入模块:"), 0, 0, 1, 1)
        self.hidden_import_edit = QLineEdit()
        self.hidden_import_edit.setPlaceholderText("多个模块用逗号分隔")
        card3_layout.addWidget(self.hidden_import_edit, 0, 1, 1, 3)
        
        # 排除模块
        card3_layout.addWidget(QLabel("排除模块:"), 1, 0, 1, 1)
        self.exclude_edit = QLineEdit()
        self.exclude_edit.setPlaceholderText("多个模块用逗号分隔")
        card3_layout.addWidget(self.exclude_edit, 1, 1, 1, 3)
        
        # 工作目录
        card3_layout.addWidget(QLabel("工作目录:"), 2, 0, 1, 1)
        workpath_layout = QHBoxLayout()
        self.workpath_edit = QLineEdit()
        self.workpath_edit.setText("./build")
        workpath_layout.addWidget(self.workpath_edit)
        workpath_browse_btn = QPushButton("浏览")
        workpath_browse_btn.clicked.connect(self.browse_workpath)
        workpath_layout.addWidget(workpath_browse_btn)
        card3_layout.addLayout(workpath_layout, 2, 1, 1, 3)
        
        # 附加参数
        card3_layout.addWidget(QLabel("附加参数:"), 3, 0, 1, 1)
        self.extra_args_edit = QLineEdit()
        self.extra_args_edit.setPlaceholderText("直接传递给PyInstaller的附加参数")
        card3_layout.addWidget(self.extra_args_edit, 3, 1, 1, 3)
        
        layout.addWidget(card3)
        
        # 说明卡片
        card4 = QWidget()
        card4.setProperty("card", True)
        card4_layout = QVBoxLayout(card4)
        
        card4_layout.addWidget(QLabel("说明:"))
        
        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setPlainText("高级设置用于配置PyInstaller的高级选项。\n\n" +
                               "1. 调试选项: 启用调试输出，方便调试打包问题\n" +
                               "2. 优化级别: 设置Python解释器的优化级别\n" +
                               "3. UPX选项: 配置UPX压缩相关设置\n" +
                               "4. 隐藏导入: 添加PyInstaller无法自动检测的依赖\n" +
                               "5. 排除模块: 从打包中排除指定模块\n" +
                               "6. 附加参数: 直接传递给PyInstaller的命令行参数")
        info_text.setMinimumHeight(100)
        card4_layout.addWidget(info_text)
        
        layout.addWidget(card4)
        
        # 自适应空白
        layout.addStretch()
    
    def browse_source(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择Python脚本", "", "Python Files (*.py);;All Files (*)")
        if file_path:
            self.source_edit.setText(file_path)
            # 自动填充程序名称
            if not self.name_edit.text():
                self.name_edit.setText(os.path.splitext(os.path.basename(file_path))[0])
    
    def browse_output(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录", ".")
        if dir_path:
            self.output_edit.setText(dir_path)
    
    def browse_icon(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择图标文件", "", "Icon Files (*.ico);;All Files (*)")
        if file_path:
            self.icon_edit.setText(file_path)
    
    def browse_upx_dir(self):
        """浏览UPX目录"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择UPX目录", ".")
        if dir_path:
            self.upx_dir_edit.setText(dir_path)
    
    def browse_workpath(self):
        """浏览工作目录"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择工作目录", ".")
        if dir_path:
            self.workpath_edit.setText(dir_path)
    
    def add_additional_lib(self):
        """添加附加库"""
        lib_name = self.lib_name_edit.text().strip()
        if lib_name:
            # 检查是否已存在
            for i in range(self.additional_libs_list.count()):
                if self.additional_libs_list.item(i).text() == lib_name:
                    QMessageBox.warning(self, "警告", f"库 '{lib_name}' 已存在于列表中！")
                    return
            
            # 添加到列表
            self.additional_libs_list.addItem(lib_name)
            self.lib_name_edit.clear()
    
    def import_additional_libs(self):
        """从文件导入附加库"""
        file_path, _ = QFileDialog.getOpenFileName(self, "选择库列表文件", "", "Text Files (*.txt);;All Files (*)")
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    libs = f.read().split('\n')
                
                added_count = 0
                for lib in libs:
                    lib_name = lib.strip()
                    if lib_name and not lib_name.startswith('#'):
                        # 检查是否已存在
                        exists = False
                        for i in range(self.additional_libs_list.count()):
                            if self.additional_libs_list.item(i).text() == lib_name:
                                exists = True
                                break
                        if not exists:
                            self.additional_libs_list.addItem(lib_name)
                            added_count += 1
                
                QMessageBox.information(self, "成功", f"已从文件导入 {added_count} 个附加库！")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导入附加库失败: {str(e)}")
    
    def remove_additional_libs(self):
        """移除选中的附加库"""
        selected_items = self.additional_libs_list.selectedItems()
        if selected_items:
            for item in selected_items:
                self.additional_libs_list.takeItem(self.additional_libs_list.row(item))
    
    def clear_additional_libs(self):
        """清空附加库列表"""
        if self.additional_libs_list.count() > 0:
            reply = QMessageBox.question(self, "确认", "确定要清空所有附加库吗？",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.additional_libs_list.clear()
    
    def add_file(self):
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择文件", "", "All Files (*)")
        for file_path in file_paths:
            item = QListWidgetItem(file_path)
            self.files_list.addItem(item)
    
    def add_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择目录", ".")
        if dir_path:
            item = QListWidgetItem(dir_path)
            self.files_list.addItem(item)
    
    def remove_files(self):
        for item in self.files_list.selectedItems():
            self.files_list.takeItem(self.files_list.row(item))
    
    def clear_log(self):
        self.log_text.clear()
    
    # 拖拽事件处理
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.endswith('.whl'):
                self.install_wheel_file(file_path)
            elif file_path.endswith('.txt'):
                self.import_requirements_file(file_path)
    
    def install_wheel(self):
        """打开文件选择器安装whl包"""
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择WHL包", "", "WHL Files (*.whl);;All Files (*)")
        for file_path in file_paths:
            self.install_wheel_file(file_path)
    
    def install_wheel_file(self, file_path):
        """安装单个whl包"""
        if not hasattr(self, 'python_path') or not self.python_path:
            QMessageBox.warning(self, "警告", "请先开始打包，以便解压Python环境！")
            return
        
        self.log_text.append(f"正在安装WHL包: {os.path.basename(file_path)}")
        cmd = [self.python_path, "-m", "pip", "install", file_path]
        
        process = QProcess()
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(lambda: self.read_process_output(process))
        process.finished.connect(lambda exit_code: self.on_process_finished(exit_code, "WHL包安装完成"))
        process.start(cmd[0], cmd[1:])
    
    def import_requirements(self):
        """导入requirements.txt文件"""
        file_path, _ = QFileDialog.getOpenFileName(self, "选择requirements.txt文件", "", "Text Files (*.txt);;All Files (*)")
        if file_path:
            self.import_requirements_file(file_path)
    
    def import_requirements_file(self, file_path):
        """导入requirements.txt文件并安装依赖"""
        if not hasattr(self, 'python_path') or not self.python_path:
            QMessageBox.warning(self, "警告", "请先开始打包，以便解压Python环境！")
            return
        
        self.log_text.append(f"正在导入依赖文件: {os.path.basename(file_path)}")
        cmd = [self.python_path, "-m", "pip", "install", "-r", file_path]
        
        process = QProcess()
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(lambda: self.read_process_output(process))
        process.finished.connect(lambda exit_code: self.on_process_finished(exit_code, "依赖安装完成"))
        process.start(cmd[0], cmd[1:])
    
    def detect_dependencies(self):
        """自动检测Python脚本的依赖"""
        source_file = self.source_edit.text().strip()
        if not source_file or not os.path.exists(source_file):
            QMessageBox.warning(self, "警告", "请先选择有效的Python脚本！")
            return
        
        self.log_text.append(f"正在检测脚本依赖: {os.path.basename(source_file)}")
        
        # 确保Python环境已解压
        if not hasattr(self, 'python_path') or not self.python_path:
            self.log_text.append("正在解压Python环境...")
            if not self.extract_python():
                return
        
        # 使用解压的Python安装pipreqs
        cmd = [self.python_path, "-m", "pip", "install", "pipreqs"]
        process = QProcess()
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(lambda: self.read_process_output(process))
        process.finished.connect(lambda exit_code: self.generate_requirements(source_file, exit_code))
        process.start(cmd[0], cmd[1:])
    
    def generate_requirements(self, source_file, exit_code):
        """生成requirements.txt文件"""
        if exit_code == 0:
            # 使用pipreqs生成依赖文件，使用解压的Python
            cmd = [self.python_path, "-m", "pipreqs", os.path.dirname(source_file), "--force"]
            process = QProcess()
            process.setProcessChannelMode(QProcess.MergedChannels)
            process.readyReadStandardOutput.connect(lambda: self.read_process_output(process))
            process.finished.connect(lambda exit_code: self.on_requirements_generated(exit_code, source_file))
            process.start(cmd[0], cmd[1:])
    
    def on_requirements_generated(self, exit_code, source_file):
        """依赖文件生成完成后的处理"""
        if exit_code == 0:
            req_file = os.path.join(os.path.dirname(source_file), "requirements.txt")
            self.log_text.append(f"依赖文件生成成功: {req_file}")
            
            # 自动安装生成的依赖
            self.log_text.append("正在安装检测到的依赖...")
            install_cmd = [self.python_path, "-m", "pip", "install", "-r", req_file]
            install_process = QProcess()
            install_process.setProcessChannelMode(QProcess.MergedChannels)
            
            # 设置环境变量，确保命令行输出为UTF-8
            from PyQt5.QtCore import QProcessEnvironment
            env = QProcessEnvironment.systemEnvironment()
            env.insert("PYTHONIOENCODING", "utf-8")
            env.insert("PYTHONUTF8", "1")
            install_process.setProcessEnvironment(env)
            
            install_process.readyReadStandardOutput.connect(lambda: self.read_process_output(install_process))
            install_process.finished.connect(lambda exit_code: self.on_dependencies_installed(exit_code, req_file, source_file))
            install_process.start(install_cmd[0], install_cmd[1:])
        else:
            self.log_text.append("依赖检测失败")
    
    def on_dependencies_installed(self, exit_code, req_file, source_file):
        """依赖安装完成后的处理"""
        if exit_code == 0:
            self.log_text.append("依赖安装成功！")
            
            # 读取requirements.txt内容，将依赖添加到隐藏导入列表
            try:
                with open(req_file, 'r', encoding='utf-8') as f:
                    dependencies = f.read().split('\n')
                
                # 提取依赖包名称
                dep_names = []
                for dep in dependencies:
                    if dep.strip() and not dep.startswith('#'):
                        # 移除版本号和其他标记，只保留包名
                        dep_name = dep.split('==')[0].split('>=')[0].split('<=')[0].strip()
                        dep_names.append(dep_name)
                
                # 将依赖添加到隐藏导入列表
                if dep_names:
                    current_hidden = self.hidden_import_edit.text().strip()
                    hidden_imports = set(current_hidden.split(',')) if current_hidden else set()
                    
                    # 添加新的依赖包
                    for dep in dep_names:
                        if dep:
                            hidden_imports.add(dep.strip())
                    
                    # 更新隐藏导入输入框
                    self.hidden_import_edit.setText(','.join(hidden_imports))
                    self.log_text.append(f"已将 {len(dep_names)} 个检测到的依赖添加到隐藏导入列表")
            except Exception as e:
                self.log_text.append(f"读取依赖文件失败: {str(e)}")
            
            QMessageBox.information(self, "成功", "依赖检测和安装完成！")
        else:
            self.log_text.append("依赖安装失败！")
            QMessageBox.warning(self, "警告", "依赖安装失败，请查看日志获取详细信息！")
    
    def install_pip_package(self):
        """通过PIP安装包"""
        package_name = self.pip_package_edit.text().strip()
        if not package_name:
            QMessageBox.warning(self, "警告", "请输入要安装的PIP包名称！")
            return
        
        if not hasattr(self, 'python_path') or not self.python_path:
            QMessageBox.warning(self, "警告", "请先开始打包，以便解压Python环境！")
            return
        
        self.log_text.append(f"正在安装PIP包: {package_name}")
        cmd = [self.python_path, "-m", "pip", "install", package_name]
        
        process = QProcess()
        process.setProcessChannelMode(QProcess.MergedChannels)
        
        # 设置环境变量，确保命令行输出为UTF-8
        from PyQt5.QtCore import QProcessEnvironment
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")
        process.setProcessEnvironment(env)
        
        process.readyReadStandardOutput.connect(lambda: self.read_process_output(process))
        process.finished.connect(lambda exit_code: self.on_process_finished(exit_code, f"PIP包 {package_name} 安装完成"))
        process.start(cmd[0], cmd[1:])
    
    def append_log(self, message, level="info"):
        """添加彩色日志输出"""
        # 根据日志级别设置颜色
        color_map = {
            "info": "#333333",
            "success": "#4CAF50",
            "warning": "#FF9800",
            "error": "#F44336",
            "debug": "#2196F3"
        }
        
        color = color_map.get(level, "#333333")
        html = f"<span style='color: {color}; font-family: 微软雅黑, 黑体, sans-serif;'>{message}</span>"
        self.log_text.append(html)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
    
    def read_process_output(self, process):
        """读取进程输出"""
        output = process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self.append_log(output, "debug")
    
    def on_process_finished(self, exit_code, message):
        """进程完成后的处理"""
        if exit_code == 0:
            self.append_log(f"✅ {message}", "success")
        else:
            self.append_log(f"❌ {message} 失败", "error")
    
    def cleanup_python_env(self):
        """清理临时解压的Python环境"""
        if hasattr(self, 'extracted_python_dir') and self.extracted_python_dir and os.path.exists(self.extracted_python_dir):
            try:
                import shutil
                shutil.rmtree(self.extracted_python_dir)
                self.append_log(f"✅ 已清理临时Python环境: {self.extracted_python_dir}", "success")
                self.extracted_python_dir = None
                self.python_path = None
            except Exception as e:
                self.append_log(f"❌ 清理临时Python环境失败: {str(e)}", "error")
    
    def toggle_dark_mode(self):
        """切换深色/浅色模式"""
        self.dark_mode = not self.dark_mode
        self.update_stylesheet()
    
    def update_stylesheet(self):
        """更新样式表"""
        if self.dark_mode:
            # 深色模式样式
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #121212;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QGroupBox {
                    border: 1px solid #333333;
                    border-radius: 5px;
                    margin-top: 10px;
                    background-color: #1e1e1e;
                    color: #ffffff;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px 0 3px;
                    background-color: #121212;
                    color: #ffffff;
                }
                
                /* 卡片悬浮效果 */
                QWidget[card="true"] {
                    background-color: #1e1e1e;
                    border-radius: 8px;
                    padding: 15px;
                    border: 1px solid #333333;
                }
                QWidget[card="true"]:hover {
                    border-color: #4CAF50;
                    background-color: #2a2a2a;
                }
                
                /* 按钮样式 */
                QPushButton {
                    background-color: #333333;
                    border: 1px solid #444444;
                    border-radius: 3px;
                    padding: 5px 10px;
                    color: #ffffff;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QPushButton:hover {
                    background-color: #4CAF50;
                    color: white;
                    border-color: #45a049;
                }
                QPushButton:pressed {
                    background-color: #3e8e41;
                }
                
                /* 输入框样式 */
                QLineEdit {
                    border: 1px solid #333333;
                    border-radius: 3px;
                    padding: 5px;
                    background-color: #2a2a2a;
                    color: #ffffff;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QLineEdit:hover {
                    border-color: #4CAF50;
                    background-color: #333333;
                }
                QLineEdit:focus {
                    border-color: #4CAF50;
                    background-color: #2a2a2a;
                }
                
                /* 复选框样式 */
                QCheckBox {
                    padding: 5px;
                    color: #ffffff;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QCheckBox:hover {
                    color: #4CAF50;
                }
                
                /* 单选按钮样式 */
                QRadioButton {
                    padding: 5px;
                    color: #ffffff;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QRadioButton:hover {
                    color: #4CAF50;
                }
                
                /* 标签样式 */
                QLabel {
                    color: #ffffff;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                
                /* 标签页样式 */
                QTabWidget::pane {
                    border: 1px solid #333333;
                    background-color: #1e1e1e;
                }
                QTabBar::tab {
                    background-color: #333333;
                    border: 1px solid #444444;
                    border-bottom-color: transparent;
                    padding: 8px 16px;
                    margin-right: 2px;
                    color: #ffffff;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QTabBar::tab:hover {
                    background-color: #444444;
                }
                QTabBar::tab:selected {
                    background-color: #1e1e1e;
                    border-bottom-color: #1e1e1e;
                }
                
                /* 列表框样式 */
                QListWidget {
                    border: 1px solid #333333;
                    border-radius: 3px;
                    background-color: #2a2a2a;
                    color: #ffffff;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QListWidget:hover {
                    border-color: #4CAF50;
                }
                
                /* 文本编辑框样式 */
                QTextEdit {
                    border: 1px solid #333333;
                    border-radius: 3px;
                    background-color: #2a2a2a;
                    color: #ffffff;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QTextEdit:hover {
                    border-color: #4CAF50;
                }
                
                /* 滚动区域样式 */
                QScrollArea {
                    background-color: transparent;
                }
                
                /* 滚动条样式 */
                QScrollBar:vertical {
                    background-color: #333333;
                    width: 10px;
                    margin: 0px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical {
                    background-color: #666666;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical:hover {
                    background-color: #888888;
                }
                QScrollBar:horizontal {
                    background-color: #333333;
                    height: 10px;
                    margin: 0px;
                    border-radius: 5px;
                }
                QScrollBar::handle:horizontal {
                    background-color: #666666;
                    border-radius: 5px;
                }
                QScrollBar::handle:horizontal:hover {
                    background-color: #888888;
                }
            """)
            self.log_text.setStyleSheet("background-color: #2a2a2a; border: 1px solid #333333; border-radius: 3px;")
            self.dark_mode_btn.setText("浅色模式")
        else:
            # 浅色模式样式
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #f0f0f0;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QGroupBox {
                    border: 1px solid #d0d0d0;
                    border-radius: 5px;
                    margin-top: 10px;
                    background-color: white;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px 0 3px;
                    background-color: #f0f0f0;
                }
                
                /* 卡片悬浮效果 */
                QWidget[card="true"] {
                    background-color: white;
                    border-radius: 8px;
                    padding: 15px;
                    border: 1px solid #e0e0e0;
                }
                QWidget[card="true"]:hover {
                    border-color: #4CAF50;
                    background-color: #f8fff8;
                }
                
                /* 按钮样式 */
                QPushButton {
                    background-color: #e0e0e0;
                    border: 1px solid #d0d0d0;
                    border-radius: 3px;
                    padding: 5px 10px;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QPushButton:hover {
                    background-color: #4CAF50;
                    color: white;
                    border-color: #45a049;
                }
                QPushButton:pressed {
                    background-color: #3e8e41;
                }
                
                /* 输入框样式 */
                QLineEdit {
                    border: 1px solid #d0d0d0;
                    border-radius: 3px;
                    padding: 5px;
                    background-color: white;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QLineEdit:hover {
                    border-color: #4CAF50;
                    background-color: #f8fff8;
                }
                QLineEdit:focus {
                    border-color: #4CAF50;
                    background-color: white;
                }
                
                /* 复选框样式 */
                QCheckBox {
                    padding: 5px;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QCheckBox:hover {
                    color: #4CAF50;
                }
                
                /* 单选按钮样式 */
                QRadioButton {
                    padding: 5px;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QRadioButton:hover {
                    color: #4CAF50;
                }
                
                /* 标签样式 */
                QLabel {
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                
                /* 标签页样式 */
                QTabWidget::pane {
                    border: 1px solid #d0d0d0;
                    background-color: white;
                }
                QTabBar::tab {
                    background-color: #e0e0e0;
                    border: 1px solid #d0d0d0;
                    border-bottom-color: transparent;
                    padding: 8px 16px;
                    margin-right: 2px;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QTabBar::tab:hover {
                    background-color: #d0d0d0;
                }
                QTabBar::tab:selected {
                    background-color: white;
                    border-bottom-color: white;
                }
                
                /* 列表框样式 */
                QListWidget {
                    border: 1px solid #d0d0d0;
                    border-radius: 3px;
                    background-color: white;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QListWidget:hover {
                    border-color: #4CAF50;
                }
                
                /* 文本编辑框样式 */
                QTextEdit {
                    border: 1px solid #d0d0d0;
                    border-radius: 3px;
                    background-color: white;
                    font-family: '微软雅黑', '黑体', sans-serif;
                }
                QTextEdit:hover {
                    border-color: #4CAF50;
                }
                
                /* 滚动区域样式 */
                QScrollArea {
                    background-color: transparent;
                }
            """)
            self.log_text.setStyleSheet("background-color: #f8f8f8; border: 1px solid #d0d0d0; border-radius: 3px;")
            self.dark_mode_btn.setText("深色模式")
    
    def start_packaging(self):
        # 检查必要参数
        source_file = self.source_edit.text().strip()
        if not source_file:
            QMessageBox.warning(self, "警告", "请选择要打包的Python脚本！")
            return
        
        if not os.path.exists(source_file):
            QMessageBox.warning(self, "警告", "指定的Python脚本不存在！")
            return
        
        # Python环境已经在启动时解压，无需再次解压
        if not self.python_path or not os.path.exists(self.python_path):
            self.append_log("Python环境异常，重新解压...", "warning")
            if not self.extract_python():
                return
        
        # 设置控制台编码为UTF-8
        os.environ['PYTHONIOENCODING'] = 'utf-8'
        os.environ['PYTHONUTF8'] = '1'
        
        # 检查并安装PyInstaller
        self.append_log("检查PyInstaller是否已安装...", "info")
        check_pyinstaller_cmd = [self.python_path, "-m", "pip", "show", "pyinstaller"]
        check_process = QProcess()
        check_process.setProcessChannelMode(QProcess.MergedChannels)
        check_process.start(check_pyinstaller_cmd[0], check_pyinstaller_cmd[1:])
        check_process.waitForFinished()
        
        if check_process.exitCode() != 0:
            self.append_log("PyInstaller未安装，正在安装...", "info")
            # 添加--no-warn-script-location参数去除pip安装警告
            install_cmd = [self.python_path, "-m", "pip", "install", "--no-warn-script-location", "pyinstaller"]
            install_process = QProcess()
            install_process.setProcessChannelMode(QProcess.MergedChannels)
            install_process.readyReadStandardOutput.connect(lambda: self.read_process_output(install_process))
            install_process.finished.connect(lambda exit_code: self.on_pyinstaller_installed(exit_code, source_file))
            install_process.start(install_cmd[0], install_cmd[1:])
            return
        else:
            self.append_log("PyInstaller已安装，开始打包...", "info")
            self.continue_packaging(source_file)
    
    def on_pyinstaller_installed(self, exit_code, source_file):
        """PyInstaller安装完成后的处理"""
        if exit_code == 0:
            self.append_log("PyInstaller安装成功！", "success")
            self.continue_packaging(source_file)
        else:
            self.append_log("PyInstaller安装失败！", "error")
            QMessageBox.critical(self, "错误", "PyInstaller安装失败，请查看日志获取详细信息。")
            self.pack_btn.setEnabled(True)
    
    def continue_packaging(self, source_file):
        """继续打包流程"""
        # 构建PyInstaller命令 - 注意模块名区分大小写，必须使用大写PyInstaller
        cmd = [self.python_path, "-m", "PyInstaller"]
        
        # 基本参数
        if self.single_file_rb.isChecked():
            cmd.append("-F")
        else:
            cmd.append("-D")
        
        if self.windowed_cb.isChecked():
            cmd.append("-w")
        
        if self.name_edit.text().strip():
            cmd.extend(["-n", self.name_edit.text().strip()])
        
        if self.icon_edit.text().strip():
            cmd.extend(["-i", self.icon_edit.text().strip()])
        
        if self.output_edit.text().strip():
            cmd.extend(["--distpath", self.output_edit.text().strip()])
        
        # 高级参数
        if self.clean_cb.isChecked():
            cmd.append("--clean")
        
        if self.spec_only_cb.isChecked():
            # -y 参数用于覆盖现有文件，没有直接生成spec文件的参数
            # 生成spec文件是PyInstaller的默认行为，不需要额外参数
            cmd.append("-y")
        
        if self.debug_cb.isChecked():
            cmd.append("-d")
            cmd.append("all")
        
        # 隐藏导入
        hidden_imports = self.hidden_import_edit.text().strip()
        
        # 添加附加库列表中的库到隐藏导入
        additional_libs = []
        for i in range(self.additional_libs_list.count()):
            lib_name = self.additional_libs_list.item(i).text().strip()
            if lib_name:
                additional_libs.append(lib_name)
        
        # 合并所有隐藏导入
        all_hidden_imports = set()
        
        # 添加手动输入的隐藏导入
        if hidden_imports:
            for imp in hidden_imports.split(","):
                imp = imp.strip()
                if imp:
                    all_hidden_imports.add(imp)
        
        # 添加附加库
        for lib in additional_libs:
            all_hidden_imports.add(lib)
        
        # 添加到命令中
        for imp in all_hidden_imports:
            cmd.extend(["--hidden-import", imp])
        
        # 添加UPX相关选项
        if self.noupx_cb.isChecked():
            cmd.append("--noupx")
        
        upx_exclude = self.upx_exclude_edit.text().strip()
        if upx_exclude:
            for exclude in upx_exclude.split(","):
                cmd.extend(["--upx-exclude", exclude.strip()])
        
        upx_dir = self.upx_dir_edit.text().strip()
        if upx_dir:
            cmd.extend(["--upx-dir", upx_dir])
        
        # 添加优化级别
        optimize_level = self.optimize_combo.currentIndex()
        if optimize_level > 0:
            cmd.extend(["--optimize", str(optimize_level)])
        
        # 排除模块
        exclude_modules = self.exclude_edit.text().strip()
        if exclude_modules:
            for mod in exclude_modules.split(","):
                cmd.extend(["--exclude-module", mod.strip()])
        
        # 工作目录
        if self.workpath_edit.text().strip():
            cmd.extend(["--workpath", self.workpath_edit.text().strip()])
        
        # 附加文件
        for i in range(self.files_list.count()):
            file_path = self.files_list.item(i).text()
            if os.path.isfile(file_path):
                cmd.extend(["--add-data", f"{file_path};."])
            elif os.path.isdir(file_path):
                cmd.extend(["--add-data", f"{file_path};{os.path.basename(file_path)}"])
        
        # 附加参数
        extra_args = self.extra_args_edit.text().strip()
        if extra_args:
            cmd.extend(extra_args.split())
        
        # 添加源文件
        cmd.append(source_file)
        
        # 显示命令
        self.append_log("执行命令:", "info")
        self.append_log(" ".join(cmd), "debug")
        self.append_log("\n开始打包...\n", "info")
        
        # 禁用打包按钮
        self.pack_btn.setEnabled(False)
        
        # 执行命令
        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        
        # 设置环境变量，确保命令行输出为UTF-8
        from PyQt5.QtCore import QProcessEnvironment
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")
        self.process.setProcessEnvironment(env)
        
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.process_finished)
        self.process.start(cmd[0], cmd[1:])
    
    def read_output(self):
        output = self.process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self.append_log(output, "debug")
    
    def process_finished(self, exit_code, exit_status):
        if exit_code == 0:
            self.append_log("\n✅ 打包成功！", "success")
            QMessageBox.information(self, "成功", "打包完成！")
        else:
            self.append_log(f"\n❌ 打包失败，退出码: {exit_code}", "error")
            QMessageBox.critical(self, "错误", "打包失败！请查看日志获取详细信息。")
        
        # 启用打包按钮
        self.pack_btn.setEnabled(True)
    
    def closeEvent(self, event):
        """软件关闭时清理Python环境"""
        self.append_log("软件正在关闭，开始清理Python环境...", "info")
        
        # 禁用窗口关闭，直到清理完成
        event.ignore()
        
        # 检查解压线程是否正在运行
        if self.python_thread and self.python_thread.isRunning():
            self.append_log("等待Python解压完成...", "info")
            self.close_pending = True
        else:
            # 开始清理
            self.really_close()
    
    def really_close(self):
        """执行实际的关闭操作"""
        # 清理临时解压的Python环境
        if hasattr(self, 'extracted_python_dir') and self.extracted_python_dir and os.path.exists(self.extracted_python_dir):
            try:
                import shutil
                shutil.rmtree(self.extracted_python_dir)
                self.append_log(f"✅ 已清理临时Python环境: {self.extracted_python_dir}", "success")
            except Exception as e:
                self.append_log(f"❌ 清理临时Python环境失败: {str(e)}", "error")
        
        self.append_log("软件已关闭", "info")
        # 执行实际的关闭操作
        QApplication.quit()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PyInstallerGUI()
    sys.exit(app.exec_())