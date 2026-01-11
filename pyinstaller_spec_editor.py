import sys
import os
import zipfile
import tempfile
import shutil
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QFileDialog, QCheckBox, QComboBox,
    QTextEdit, QGroupBox, QGridLayout, QListWidget,
    QListWidgetItem, QAbstractItemView, QMessageBox, QInputDialog,
    QScrollArea
)
from PyQt5.QtCore import Qt, QProcess, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon

class PythonExtractThread(QThread):
    # 信号定义
    progress_updated = pyqtSignal(str)  # 消息
    finished = pyqtSignal(bool, str)  # 成功标志, 结果信息
    python_path_updated = pyqtSignal(str, str)  # python路径, 解压目录
    
    def __init__(self, python_zip):
        super().__init__()
        self.python_zip = python_zip
        self.python_path = None
        self.extracted_python_dir = None
    
    def run(self):
        """后台解压Python压缩包"""
        self.progress_updated.emit("开始解压Python压缩包...")
        
        if not os.path.exists(self.python_zip):
            self.progress_updated.emit(f"错误: Python压缩包不存在: {self.python_zip}")
            self.finished.emit(False, "Python压缩包不存在")
            return
        
        try:
            # 创建临时目录，避免中文路径导致的编码问题
            self.extracted_python_dir = tempfile.mkdtemp(prefix='pyinstaller_')
            self.progress_updated.emit(f"正在解压Python到临时目录: {self.extracted_python_dir}")
            
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
                        self.progress_updated.emit(f"解压进度: {progress}% ({extracted_files}/{total_files}文件)")
                        last_progress = progress
            
            # 找到python.exe路径
            self.python_path = os.path.join(self.extracted_python_dir, 'python.exe')
            if not os.path.exists(self.python_path):
                self.progress_updated.emit("错误: 未找到python.exe")
                self.finished.emit(False, "未找到python.exe")
                return
            
            # 修改python39._pth文件，启用site模块
            pth_file = os.path.join(self.extracted_python_dir, 'python39._pth')
            if os.path.exists(pth_file):
                with open(pth_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 取消注释import site
                content = content.replace('#import site', 'import site')
                
                # 添加Lib目录到路径
                if 'Lib' not in content:
                    lines = content.split('\n')
                    updated = False
                    for i, line in enumerate(lines):
                        if line.strip() == '.':
                            lines.insert(i+1, 'Lib')
                            updated = True
                            break
                    if not updated:
                        lines.append('Lib')
                    content = '\n'.join(lines)
                
                with open(pth_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                self.progress_updated.emit("已修改python39._pth，启用site模块并添加Lib路径")
            
            self.progress_updated.emit(f"成功解压Python，可执行文件路径: {self.python_path}")
            self.python_path_updated.emit(self.python_path, self.extracted_python_dir)
            self.finished.emit(True, "Python解压成功")
        except Exception as e:
            self.progress_updated.emit(f"解压Python失败: {str(e)}")
            self.finished.emit(False, f"解压Python失败: {str(e)}")

class PyInstallerSpecEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.process = None
        self.python_path = None
        self.extracted_python_dir = None
        self.python_thread = None
        self.close_pending = False
        self.spec_data = {
            'analysis': {
                'scripts': [],
                'pathex': [],
                'binaries': [],
                'datas': [],
                'hiddenimports': [],
                'hookspath': [],
                'runtime_hooks': [],
                'excludes': [],
                'noarchive': False,
                'optimize': 0
            },
            'pyz': {
                'cipher': None
            },
            'exe': {
                'name': '',
                'debug': False,
                'console': True,
                'icon': None,
                'upx': True,
                'runtime_tmpdir': '.'
            },
            'collect': {
                'name': ''
            }
        }
        self.detect_system()
        # 启动后台线程解压Python
        self.start_python_extract()
        # 显示窗口
        self.show()

    def detect_system(self):
        """检测系统架构，选择对应的Python压缩包"""
        import platform
        self.system_arch = platform.architecture()[0]
        print(f"系统架构: {self.system_arch}")
        
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
        
        print(f"使用Python压缩包: {os.path.basename(self.python_zip)}")

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
            self.append_log("Python解压完成，软件已准备就绪")
        else:
            self.append_log(f"Python解压失败: {message}")
        
        # 检查是否有关闭请求
        if self.close_pending:
            self.really_close()
    
    def extract_python(self):
        """已废弃，使用后台线程解压Python"""
        pass
    
    def append_log(self, message):
        """添加日志输出"""
        print(message)

    def init_ui(self):
        """初始化UI界面"""
        self.setWindowTitle("PyInstaller Spec编辑器")
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
            /* 卡片样式 */
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
            /* 列表样式 */
            QListWidget {
                border: 1px solid #d0d0d0;
                border-radius: 3px;
                font-family: '微软雅黑', '黑体', sans-serif;
            }
        """)
        
        # 主布局
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        
        # 标题
        title_label = QLabel("PyInstaller Spec文件编辑器")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px 0;")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        main_layout.addWidget(scroll_area)
        
        # 滚动内容
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(15)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        scroll_area.setWidget(scroll_content)
        
        # Analysis类卡片
        analysis_card = self.create_analysis_card()
        scroll_layout.addWidget(analysis_card)
        
        # PYZ类卡片
        pyz_card = self.create_pyz_card()
        scroll_layout.addWidget(pyz_card)
        
        # EXE类卡片
        exe_card = self.create_exe_card()
        scroll_layout.addWidget(exe_card)
        
        # COLLECT类卡片
        collect_card = self.create_collect_card()
        scroll_layout.addWidget(collect_card)
        
        scroll_layout.addStretch()
        
        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.close)
        btn_layout.addWidget(cancel_btn)
        
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.save_spec)
        btn_layout.addWidget(save_btn)
        
        save_build_btn = QPushButton("保存并打包")
        save_build_btn.clicked.connect(self.save_and_build)
        btn_layout.addWidget(save_build_btn)
        
        main_layout.addLayout(btn_layout)

    def create_analysis_card(self):
        """创建Analysis类卡片"""
        card = QWidget()
        card.setProperty("card", True)
        layout = QVBoxLayout(card)
        
        # 标题
        title = QLabel("Analysis类 - 分析Python脚本及其依赖")
        title.setStyleSheet("font-weight: bold; font-size: 12px; margin-bottom: 10px;")
        layout.addWidget(title)
        
        # 脚本文件
        scripts_group = QGroupBox("主脚本文件 (scripts)")
        scripts_layout = QVBoxLayout(scripts_group)
        scripts_layout.addWidget(QLabel("主脚本列表，包含应用程序的入口脚本："))
        
        scripts_list_layout = QHBoxLayout()
        self.scripts_list = QListWidget()
        self.scripts_list.setMinimumHeight(100)
        scripts_list_layout.addWidget(self.scripts_list)
        
        scripts_btn_layout = QVBoxLayout()
        add_script_btn = QPushButton("添加脚本")
        add_script_btn.clicked.connect(self.add_script)
        scripts_btn_layout.addWidget(add_script_btn)
        
        remove_script_btn = QPushButton("移除选中")
        remove_script_btn.clicked.connect(self.remove_script)
        scripts_btn_layout.addWidget(remove_script_btn)
        
        scripts_btn_layout.addStretch()
        scripts_list_layout.addLayout(scripts_btn_layout)
        scripts_layout.addLayout(scripts_list_layout)
        layout.addWidget(scripts_group)
        
        # 搜索路径
        pathex_group = QGroupBox("额外模块搜索路径 (pathex)")
        pathex_layout = QVBoxLayout(pathex_group)
        pathex_layout.addWidget(QLabel("Python解释器的额外搜索路径，用于查找模块："))
        
        pathex_list_layout = QHBoxLayout()
        self.pathex_list = QListWidget()
        self.pathex_list.setMinimumHeight(100)
        pathex_list_layout.addWidget(self.pathex_list)
        
        pathex_btn_layout = QVBoxLayout()
        add_pathex_btn = QPushButton("添加路径")
        add_pathex_btn.clicked.connect(self.add_pathex)
        pathex_btn_layout.addWidget(add_pathex_btn)
        
        remove_pathex_btn = QPushButton("移除选中")
        remove_pathex_btn.clicked.connect(self.remove_pathex)
        pathex_btn_layout.addWidget(remove_pathex_btn)
        
        pathex_btn_layout.addStretch()
        pathex_list_layout.addLayout(pathex_btn_layout)
        pathex_layout.addLayout(pathex_list_layout)
        layout.addWidget(pathex_group)
        
        # 隐藏导入
        hidden_imports_group = QGroupBox("隐式导入模块 (hiddenimports)")
        hidden_imports_layout = QVBoxLayout(hidden_imports_group)
        hidden_imports_layout.addWidget(QLabel("动态导入的模块，PyInstaller无法自动检测到的依赖："))
        
        hidden_imports_list_layout = QHBoxLayout()
        self.hidden_imports_list = QListWidget()
        self.hidden_imports_list.setMinimumHeight(100)
        hidden_imports_list_layout.addWidget(self.hidden_imports_list)
        
        hidden_imports_btn_layout = QVBoxLayout()
        add_hidden_btn = QPushButton("添加模块")
        add_hidden_btn.clicked.connect(self.add_hidden_import)
        hidden_imports_btn_layout.addWidget(add_hidden_btn)
        
        remove_hidden_btn = QPushButton("移除选中")
        remove_hidden_btn.clicked.connect(self.remove_hidden_import)
        hidden_imports_btn_layout.addWidget(remove_hidden_btn)
        
        hidden_imports_btn_layout.addStretch()
        hidden_imports_list_layout.addLayout(hidden_imports_btn_layout)
        hidden_imports_layout.addLayout(hidden_imports_list_layout)
        layout.addWidget(hidden_imports_group)
        
        return card

    def create_pyz_card(self):
        """创建PYZ类卡片"""
        card = QWidget()
        card.setProperty("card", True)
        layout = QVBoxLayout(card)
        
        # 标题
        title = QLabel("PYZ类 - 创建Python字节码归档文件")
        title.setStyleSheet("font-weight: bold; font-size: 12px; margin-bottom: 10px;")
        layout.addWidget(title)
        
        # 加密设置
        cipher_group = QGroupBox("加密设置 (cipher)")
        cipher_layout = QVBoxLayout(cipher_group)
        cipher_layout.addWidget(QLabel("用于加密Python字节码的密钥，留空表示不加密："))
        
        self.cipher_edit = QLineEdit()
        self.cipher_edit.setPlaceholderText("输入加密密钥，需要tinyaes库支持")
        cipher_layout.addWidget(self.cipher_edit)
        layout.addWidget(cipher_group)
        
        return card

    def create_exe_card(self):
        """创建EXE类卡片"""
        card = QWidget()
        card.setProperty("card", True)
        layout = QVBoxLayout(card)
        
        # 标题
        title = QLabel("EXE类 - 生成可执行文件")
        title.setStyleSheet("font-weight: bold; font-size: 12px; margin-bottom: 10px;")
        layout.addWidget(title)
        
        # 基本设置
        basic_group = QGroupBox("基本设置")
        basic_layout = QGridLayout(basic_group)
        
        basic_layout.addWidget(QLabel("程序名称 (name):"), 0, 0)
        self.exe_name_edit = QLineEdit()
        basic_layout.addWidget(self.exe_name_edit, 0, 1)
        
        basic_layout.addWidget(QLabel("程序图标 (icon):"), 1, 0)
        icon_layout = QHBoxLayout()
        self.icon_edit = QLineEdit()
        icon_layout.addWidget(self.icon_edit)
        browse_icon_btn = QPushButton("浏览")
        browse_icon_btn.clicked.connect(self.browse_icon)
        icon_layout.addWidget(browse_icon_btn)
        basic_layout.addLayout(icon_layout, 1, 1)
        
        self.console_cb = QCheckBox("控制台程序 (console)")
        self.console_cb.setChecked(True)
        basic_layout.addWidget(self.console_cb, 2, 0, 1, 2)
        
        self.debug_cb = QCheckBox("调试模式 (debug)")
        basic_layout.addWidget(self.debug_cb, 3, 0, 1, 2)
        
        self.upx_cb = QCheckBox("使用UPX压缩 (upx)")
        self.upx_cb.setChecked(True)
        basic_layout.addWidget(self.upx_cb, 4, 0, 1, 2)
        layout.addWidget(basic_group)
        
        # 临时文件位置
        tmpdir_group = QGroupBox("临时文件位置 (runtime_tmpdir)")
        tmpdir_layout = QVBoxLayout(tmpdir_group)
        
        tmpdir_info = QLabel("runtime_tmpdir项用于指定打包后的程序临时文件解压位置：")
        tmpdir_info.setWordWrap(True)
        tmpdir_layout.addWidget(tmpdir_info)
        
        tmpdir_note = QLabel("- 默认(None)：解压在系统用户临时文件文件夹\n- '.'：解压在程序目录下\n- 其他路径：解压在指定路径")
        tmpdir_note.setStyleSheet("color: #666; margin-left: 10px;")
        tmpdir_layout.addWidget(tmpdir_note)
        
        tmpdir_edit_layout = QHBoxLayout()
        tmpdir_edit_layout.addWidget(QLabel("临时文件位置:"))
        self.runtime_tmpdir_edit = QLineEdit()
        self.runtime_tmpdir_edit.setText('.')
        tmpdir_edit_layout.addWidget(self.runtime_tmpdir_edit)
        tmpdir_layout.addLayout(tmpdir_edit_layout)
        layout.addWidget(tmpdir_group)
        
        return card

    def create_collect_card(self):
        """创建COLLECT类卡片"""
        card = QWidget()
        card.setProperty("card", True)
        layout = QVBoxLayout(card)
        
        # 标题
        title = QLabel("COLLECT类 - 收集所有文件到目录（仅onedir模式）")
        title.setStyleSheet("font-weight: bold; font-size: 12px; margin-bottom: 10px;")
        layout.addWidget(title)
        
        # 目录名称
        collect_group = QGroupBox("目录设置")
        collect_layout = QGridLayout(collect_group)
        
        collect_layout.addWidget(QLabel("输出文件夹名 (name):"), 0, 0)
        self.collect_name_edit = QLineEdit()
        collect_layout.addWidget(self.collect_name_edit, 0, 1)
        layout.addWidget(collect_group)
        
        return card

    def add_script(self):
        """添加脚本文件"""
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择Python脚本", "", "Python Files (*.py);;All Files (*)")
        for file_path in file_paths:
            if file_path not in [self.scripts_list.item(i).text() for i in range(self.scripts_list.count())]:
                self.scripts_list.addItem(file_path)

    def remove_script(self):
        """移除选中的脚本文件"""
        for item in self.scripts_list.selectedItems():
            self.scripts_list.takeItem(self.scripts_list.row(item))

    def add_pathex(self):
        """添加搜索路径"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择模块搜索路径", ".")
        if dir_path and dir_path not in [self.pathex_list.item(i).text() for i in range(self.pathex_list.count())]:
            self.pathex_list.addItem(dir_path)

    def remove_pathex(self):
        """移除选中的搜索路径"""
        for item in self.pathex_list.selectedItems():
            self.pathex_list.takeItem(self.pathex_list.row(item))

    def add_hidden_import(self):
        """添加隐藏导入模块"""
        module_name, ok = QInputDialog.getText(self, "添加隐藏导入", "输入模块名:")
        if ok and module_name:
            if module_name not in [self.hidden_imports_list.item(i).text() for i in range(self.hidden_imports_list.count())]:
                self.hidden_imports_list.addItem(module_name)

    def remove_hidden_import(self):
        """移除选中的隐藏导入模块"""
        for item in self.hidden_imports_list.selectedItems():
            self.hidden_imports_list.takeItem(self.hidden_imports_list.row(item))

    def browse_icon(self):
        """浏览图标文件"""
        file_path, _ = QFileDialog.getOpenFileName(self, "选择图标文件", "", "Icon Files (*.ico);;All Files (*)")
        if file_path:
            self.icon_edit.setText(file_path)

    def save_spec(self):
        """保存spec文件"""
        file_path, _ = QFileDialog.getSaveFileName(self, "保存Spec文件", "", "Spec Files (*.spec);;All Files (*)")
        if file_path:
            try:
                spec_content = self.generate_spec_content()
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(spec_content)
                QMessageBox.information(self, "成功", f"Spec文件已保存到: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存Spec文件失败: {str(e)}")

    def generate_spec_content(self):
        """生成spec文件内容"""
        # 收集数据
        scripts = [self.scripts_list.item(i).text() for i in range(self.scripts_list.count())]
        pathex = [self.pathex_list.item(i).text() for i in range(self.pathex_list.count())]
        hiddenimports = [self.hidden_imports_list.item(i).text() for i in range(self.hidden_imports_list.count())]
        
        # 生成spec文件内容
        spec_content = f"""# -*- mode: python ; coding: utf-8 -*-

block_cipher = {repr(self.cipher_edit.text() if self.cipher_edit.text() else None)}


a = Analysis(
    {repr(scripts)},
    pathex={repr(pathex)},
    binaries=[],
    datas=[],
    hiddenimports={repr(hiddenimports)},
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name={repr(self.exe_name_edit.text() if self.exe_name_edit.text() else 'app')},
    debug={str(self.debug_cb.isChecked()).lower()},
    bootloader_ignore_signals=False,
    strip=False,
    upx={str(self.upx_cb.isChecked()).lower()},
    upx_exclude=[],
    runtime_tmpdir={repr(self.runtime_tmpdir_edit.text() if self.runtime_tmpdir_edit.text() else None)},
    console={str(self.console_cb.isChecked()).lower()},
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon={repr(self.icon_edit.text() if self.icon_edit.text() else None)},
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx={str(self.upx_cb.isChecked()).lower()},
    upx_exclude=[],
    name={repr(self.collect_name_edit.text() if self.collect_name_edit.text() else 'app')},
)
"""
        return spec_content

    def save_and_build(self):
        """保存并打包"""
        # 保存spec文件
        temp_spec_path = os.path.join(tempfile.gettempdir(), 'temp.spec')
        spec_content = self.generate_spec_content()
        with open(temp_spec_path, 'w', encoding='utf-8') as f:
            f.write(spec_content)
        
        # 执行打包
        cmd = [self.python_path, '-m', 'PyInstaller', temp_spec_path]
        
        QMessageBox.information(self, "开始打包", f"正在执行打包命令：\n{' '.join(cmd)}\n\n打包过程可能需要几分钟，请稍候...")
        
        # 执行命令
        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        
        # 设置环境变量
        from PyQt5.QtCore import QProcessEnvironment
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")
        self.process.setEnvironment(env)
        
        # 连接信号
        self.process.finished.connect(self.on_build_finished)
        self.process.start(cmd[0], cmd[1:])

    def on_build_finished(self, exit_code, exit_status):
        """打包完成后的处理"""
        output = self.process.readAllStandardOutput().data().decode('utf-8', errors='replace')
        if exit_code == 0:
            QMessageBox.information(self, "成功", "打包完成！\n\n可执行文件已生成在dist目录中。")
        else:
            QMessageBox.critical(self, "错误", f"打包失败，退出码: {exit_code}\n\n输出信息:\n{output}")

    def closeEvent(self, event):
        """关闭窗口时清理临时文件"""
        self.append_log("软件正在关闭，开始清理Python环境...")
        
        # 禁用窗口关闭，直到清理完成
        event.ignore()
        
        # 检查解压线程是否正在运行
        if self.python_thread and self.python_thread.isRunning():
            self.append_log("等待Python解压完成...")
            self.close_pending = True
        else:
            # 开始清理
            self.really_close()
    
    def really_close(self):
        """执行实际的关闭操作"""
        # 清理临时解压的Python环境
        if hasattr(self, 'extracted_python_dir') and self.extracted_python_dir and os.path.exists(self.extracted_python_dir):
            try:
                shutil.rmtree(self.extracted_python_dir)
                self.append_log(f"✅ 已清理临时Python环境: {self.extracted_python_dir}")
            except Exception as e:
                self.append_log(f"❌ 清理临时Python环境失败: {str(e)}")
        
        self.append_log("软件已关闭")
        # 执行实际的关闭操作
        QApplication.quit()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PyInstallerSpecEditor()
    sys.exit(app.exec_())
