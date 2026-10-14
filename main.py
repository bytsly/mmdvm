import sys
import os
import pandas as pd
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QLabel, QPushButton, QComboBox, 
                            QFileDialog, QMessageBox)
from brand_database import BrandDatabase

# 设置Qt平台插件路径
plugin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.venv', 'Lib', 'site-packages', 'PyQt5', 'Qt5', 'plugins')
if os.path.exists(plugin_path):
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = plugin_path

class ContactConverter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("数字联系人生成器")
        self.resize(500, 300)
        
        # 初始化品牌数据库
        self.db = BrandDatabase()
        # 自动设置文件路径为 up/user.csv
        self.selected_file_path = "up/user.csv"
        
        # 初始化UI
        self.initUI()
        # 加载品牌模板
        self.loadBrandTemplates()
        
    def initUI(self):
        # 主窗口组件
        central_widget = QWidget()
        layout = QVBoxLayout()
        
        # 数据来源显示
        self.source_label = QLabel("数据来源: up/user.csv")
        
        # 品牌选择
        self.brand_label = QLabel("对讲机品牌:")
        self.brand_combo = QComboBox()
        
        # 转换按钮
        self.convert_btn = QPushButton("转换")
        self.convert_btn.clicked.connect(self.convertContacts)
        
        # 添加到布局
        layout.addWidget(self.source_label)
        layout.addWidget(self.brand_label)
        layout.addWidget(self.brand_combo)
        layout.addWidget(self.convert_btn)
        
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)
    
    def loadBrandTemplates(self):
        """从数据库加载品牌模板"""
        try:
            # 从数据库获取所有品牌
            brands = self.db.get_all_brands()
            if brands:
                self.brand_combo.addItems(brands)
                print(f"成功加载品牌模板: {brands}")  # 调试信息
            else:
                QMessageBox.warning(self, "警告", "数据库中未找到品牌模板")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载模板失败: {str(e)}")
    
    def checkSourceFile(self):
        """检查源文件是否存在"""
        if not os.path.exists(self.selected_file_path):
            QMessageBox.critical(self, "错误", f"源文件不存在: {self.selected_file_path}")
            return False
        return True
    
    def convertContacts(self):
        """执行转换"""
        # 检查源文件是否存在
        if not self.checkSourceFile():
            return
        
        brand = self.brand_combo.currentText()
        
        if not brand:
            QMessageBox.warning(self, "警告", "请选择对讲机品牌")
            return
        
        try:
            self.convertLocalFile(self.selected_file_path, brand)
            QMessageBox.information(self, "完成", "转换成功完成")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"转换失败: {str(e)}")
    
    def convertLocalFile(self, file_path, brand):
        """转换本地文件"""
        try:
            # 读取源文件
            source_df = pd.read_csv(file_path)
            
            # 使用数据库模板进行转换
            converted_df = self.convertToTemplateFormat(source_df, brand)
            
            if converted_df is None:
                raise Exception("转换失败：无法将数据转换为目标格式")
            
            # 保存转换后的文件
            output_path = f"output_{brand}.csv"
            if brand == "DM9100":
                # 清理GBK不支持的字符
                cleaned_df = converted_df.copy()
                for col in cleaned_df.columns:
                    if cleaned_df[col].dtype == 'object':
                        cleaned_df[col] = cleaned_df[col].astype(str).str.replace('[^\x00-\xff]', '', regex=True)
                cleaned_df.to_csv(output_path, index=False, encoding='gbk')
            else:
                converted_df.to_csv(output_path, index=False, encoding='utf-8-sig')
            
        except Exception as e:
            raise Exception(f"转换失败: {str(e)}")
    
    def convertToTemplateFormat(self, source_df, brand):
        """根据品牌数据库模板格式转换数据"""
        try:
            # 使用新的品牌数据库转换方法
            converted_df = self.db.convert_data(brand, source_df)
            return converted_df
            
        except Exception as e:
            print(f"品牌数据库转换错误 ({brand}): {str(e)}")
            return None
    
    def _apply_transformation(self, value, rule):
        """应用字段转换规则"""
        # 这里可以添加更复杂的转换逻辑
        # 目前只实现简单的规则
        if rule == "uppercase":
            return str(value).upper()
        elif rule == "lowercase":
            return str(value).lower()
        elif rule == "strip":
            return str(value).strip()
        else:
            return value

if __name__ == "__main__":
    app = QApplication(sys.argv)
    converter = ContactConverter()
    converter.show()
    sys.exit(app.exec_())