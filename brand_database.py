import sqlite3
import pandas as pd
import os
import re
import threading
import sys

class BrandDatabase:
    def __init__(self, db_path=None, enable_translation=True):
        """初始化品牌数据库连接
        Args:
            db_path: 数据库路径
            enable_translation: 是否启用翻译功能
        """
        if db_path is None:
            # 默认使用当前目录下的数据库
            # 检查是否在PyInstaller打包环境中运行
            if getattr(sys, 'frozen', False):
                # 在打包环境中，数据库文件与exe文件在同一目录
                base_path = os.path.dirname(sys.executable)
                db_path = os.path.join(base_path, "brand_templates.db")
            else:
                # 在开发环境中，使用当前文件所在目录
                db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                     "brand_templates.db")
        
        self.db_path = db_path
        self.enable_translation = enable_translation  # 翻译开关
        self.conn = None
        # 用于存储每个线程的连接
        self._local = threading.local()
        self.connect()
    
    def _get_thread_connection(self):
        """获取当前线程的数据库连接"""
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(self.db_path)
        return self._local.conn
    
    def connect(self):
        """连接到数据库"""
        try:
            self.conn = sqlite3.connect(self.db_path)
            # 检查数据库是否包含必要的表
            self._ensure_tables_exist()
        except Exception as e:
            raise Exception(f"无法连接到品牌数据库: {str(e)}")
    
    def _ensure_tables_exist(self):
        """确保数据库表存在"""
        conn = self._get_thread_connection()
        cursor = conn.cursor()
        
        # 检查是否存在brands表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='brands'")
        if not cursor.fetchone():
            # 创建brands表
            cursor.execute('''
                CREATE TABLE brands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        
        # 检查是否存在template_fields表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='template_fields'")
        if not cursor.fetchone():
            # 创建template_fields表
            cursor.execute('''
                CREATE TABLE template_fields (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brand_id INTEGER,
                    field_name TEXT NOT NULL,
                    field_type TEXT,
                    is_required INTEGER DEFAULT 0,
                    mapping_rule TEXT,
                    FOREIGN KEY (brand_id) REFERENCES brands (id)
                )
            ''')
        
        conn.commit()
    
    def get_all_brands(self, translate=True):
        """获取所有品牌列表
        Args:
            translate: 是否翻译成中文名称
        """
        try:
            conn = self._get_thread_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM brands ORDER BY name")
            brands = [row[0] for row in cursor.fetchall()]
            
            # 如果数据库中没有品牌，尝试从CSV目录加载
            if not brands:
                brands = self._load_brands_from_csv()
            else:
                # 确保数据库中的品牌与CSV目录中的品牌同步
                csv_brands = self._load_brands_from_csv()
                
                # 添加CSV目录中存在但数据库中不存在的品牌
                for brand in csv_brands:
                    if brand not in brands:
                        self._add_brand_to_db(brand)
                        brands.append(brand)
                
                # 删除数据库中不存在于CSV目录的品牌（临时模板清理）
                for brand in brands[:]:  # 使用副本进行迭代
                    if brand not in csv_brands:
                        self._remove_brand_from_db(brand)
                        brands.remove(brand)
                
                brands = sorted(brands)
            
            # 如果需要翻译，将品牌名称翻译成中文
            if translate:
                return self._translate_brand_names(brands)
            else:
                return brands
        except Exception as e:
            print(f"获取品牌列表失败: {str(e)}")
            return []
    
    def _translate_brand_names(self, brands):
        """将品牌名称翻译成中文"""
        brand_translations = {
            'Ailunce_HD1': '艾朗斯 HD1',
            'AnyTone': '自由通',
            'BTECH_DMR-6X2': 'BTECH DMR-6X2',
            'Baofeng_DM-1701': '宝锋 DM-1701',
            'Baofeng_DM-860': '宝锋 DM-860',
            'DM9100': '鸿凯德DM9100',
            'GD-77': '欧讯 GD-77',
            'Retevis_RT3S_RT90_RT84_RT82': '瑞可达 RT3S/RT90/RT84/RT82',
            'Retevis_RT52': '瑞可达 RT52',
            'TYT': '特易通'
        }
        
        translated_brands = []
        for brand in brands:
            if brand in brand_translations:
                translated_brands.append(brand_translations[brand])
            else:
                translated_brands.append(brand)
        
        return translated_brands
    
    def _load_brands_from_csv(self):
        """从CSV目录加载品牌列表"""
        brands = []
        # 检查是否在PyInstaller打包环境中运行
        if getattr(sys, 'frozen', False):
            # 在打包环境中，CSV目录与exe文件在同一目录
            csv_dir = os.path.join(os.path.dirname(sys.executable), "CSV")
        else:
            # 在开发环境中，使用当前文件所在目录
            csv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "CSV")
        
        if os.path.exists(csv_dir):
            for filename in os.listdir(csv_dir):
                if filename.endswith('.csv'):
                    # 从文件名提取品牌名（去掉.csv后缀）
                    brand_name = filename[:-4]
                    brands.append(brand_name)
                    
                    # 将品牌添加到数据库
                    self._add_brand_to_db(brand_name)
        
        return sorted(brands)
    
    def _add_brand_to_db(self, brand_name):
        """将品牌添加到数据库"""
        try:
            conn = self._get_thread_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO brands (name) VALUES (?)", (brand_name,))
            conn.commit()
        except Exception as e:
            print(f"添加品牌到数据库失败: {str(e)}")
    
    def _remove_brand_from_db(self, brand_name):
        """从数据库中删除品牌"""
        try:
            conn = self._get_thread_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM brands WHERE name = ?", (brand_name,))
            conn.commit()
        except Exception as e:
            print(f"从数据库删除品牌失败: {str(e)}")
    
    def get_template_fields(self, brand_name):
        """获取指定品牌的模板字段"""
        try:
            conn = self._get_thread_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM brands WHERE name = ?", (brand_name,))
            result = cursor.fetchone()
            
            if not result:
                return self._get_template_fields_from_csv(brand_name)
            
            brand_id = result[0]
            cursor.execute("SELECT field_name, field_type, is_required, mapping_rule FROM template_fields WHERE brand_id = ?", (brand_id,))
            fields = cursor.fetchall()
            
            if not fields:
                return self._get_template_fields_from_csv(brand_name)
            
            return [{"name": field[0], "type": field[1], "required": bool(field[2]), "rule": field[3]} for field in fields]
            
        except Exception as e:
            print(f"获取模板字段失败: {str(e)}")
            return self._get_template_fields_from_csv(brand_name)
    
    def _get_template_fields_from_csv(self, brand_name):
        """从CSV文件获取模板字段"""
        # 检查是否在PyInstaller打包环境中运行
        if getattr(sys, 'frozen', False):
            # 在打包环境中，CSV目录与exe文件在同一目录
            csv_path = os.path.join(os.path.dirname(sys.executable), 
                                  "CSV", f"{brand_name}.csv")
        else:
            # 在开发环境中，使用当前文件所在目录
            csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                  "CSV", f"{brand_name}.csv")
        
        if not os.path.exists(csv_path):
            return []
        
        try:
            # 尝试不同的编码格式读取CSV文件
            encodings = ['utf-8', 'gbk', 'gb2312', 'utf-16']
            df = None
            
            for encoding in encodings:
                try:
                    # 读取CSV文件的第一行获取字段名
                    df = pd.read_csv(csv_path, nrows=1, encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue
            
            if df is None:
                # 如果所有编码都失败，使用错误处理模式读取
                df = pd.read_csv(csv_path, nrows=1, encoding='utf-8', on_bad_lines='skip')
            
            fields = []
            
            for col in df.columns:
                fields.append({
                    "name": col,
                    "type": "text",  # 默认类型
                    "required": False,
                    "rule": None
                })
            
            return fields
        except Exception as e:
            print(f"从CSV读取模板字段失败: {str(e)}")
            return []
    
    def convert_data(self, brand_name, source_df):
        """将源数据转换为指定品牌的格式
        
        该方法支持自动识别呼号对应的省份功能：
        - 当源数据中的State/Province字段为空时，如果存在Callsign字段，
          系统会自动通过呼号识别对应省份（仅适用于中国呼号）
        - 对于已有省份信息的记录，保持原有翻译功能
        
        Args:
            brand_name (str): 目标品牌名称
            source_df (pandas.DataFrame): 源数据
            
        Returns:
            pandas.DataFrame: 转换后的数据
            
        Raises:
            Exception: 转换失败时抛出异常
        """
        try:
            # 获取目标品牌的模板字段
            template_fields = self.get_template_fields(brand_name)
            if not template_fields:
                raise Exception(f"未找到品牌 '{brand_name}' 的模板")
            
            # 创建目标DataFrame - 使用向量化操作提高性能
            target_columns = [field["name"] for field in template_fields]
            target_data = {}
            
            # 初始化所有列为空字符串
            for col in target_columns:
                target_data[col] = [""] * len(source_df)
            
            # 特殊处理：自由通品牌的No.字段需要自动填充序号（无论是否启用翻译）
            if brand_name == "AnyTone":
                for field in template_fields:
                    field_name = field["name"]
                    if isinstance(field_name, str) and field_name.lower() == "no.":
                        target_data[field_name] = [str(i + 1) for i in range(len(source_df))]
                        break
            
            # 特殊处理：Ailunce_HD1品牌的Call Type字段需要设置默认值
            if brand_name == "Ailunce_HD1":
                for field in template_fields:
                    field_name = field["name"]
                    if isinstance(field_name, str) and field_name.lower() == "call type":
                        target_data[field_name] = ["Private Call"] * len(source_df)
                        break
            
            # 特殊处理：BTECH_DMR-6X2品牌的No.字段需要自动填充序号（仅在启用翻译时）
            if brand_name == "BTECH_DMR-6X2" and self.enable_translation:
                for field in template_fields:
                    field_name = field["name"]
                    if isinstance(field_name, str) and field_name.lower() == "no.":
                        target_data[field_name] = [str(i + 1) for i in range(len(source_df))]
                        break
            
            # 特殊处理：Baofeng_DM-860品牌的Number字段需要自动填充序号（仅在启用翻译时）
            if brand_name == "Baofeng_DM-860" and self.enable_translation:
                for field in template_fields:
                    field_name = field["name"]
                    if isinstance(field_name, str) and field_name.lower() == "number":
                        target_data[field_name] = [str(i + 1) for i in range(len(source_df))]
                        break
            
            # 特殊处理：Baofeng_DM-860品牌的Type字段需要设置默认值
            if brand_name == "Baofeng_DM-860":
                for field in template_fields:
                    field_name = field["name"]
                    if isinstance(field_name, str) and field_name.lower() == "type":
                        target_data[field_name] = ["Private Call"] * len(source_df)
                        break
            
            # 特殊处理：Baofeng_DM-860品牌的Ring Style字段需要设置默认值
            if brand_name == "Baofeng_DM-860":
                for field in template_fields:
                    field_name = field["name"]
                    if isinstance(field_name, str) and field_name.lower() == "ring style":
                        target_data[field_name] = ["Off"] * len(source_df)
                        break
            
            # 特殊处理：Baofeng_DM-860品牌的Call Receive Tone字段需要设置默认值
            if brand_name == "Baofeng_DM-860":
                for field in template_fields:
                    field_name = field["name"]
                    if isinstance(field_name, str) and field_name.lower() == "call receive tone":
                        target_data[field_name] = ["None"] * len(source_df)
                        break
            
            # 特殊处理：DM9100品牌的序号字段需要自动填充序号（无论是否启用翻译）
            if brand_name == "DM9100":
                for field in template_fields:
                    field_name = field["name"]
                    if isinstance(field_name, str) and field_name == "序号":
                        target_data[field_name] = [str(i + 1) for i in range(len(source_df))]
                        break
    
            # 特殊处理：DM9100品牌的呼叫类型字段需要设置默认值
            if brand_name == "DM9100":
                for field in template_fields:
                    field_name = field["name"]
                    if isinstance(field_name, str) and field_name == "呼叫类型":
                        target_data[field_name] = ["个呼"] * len(source_df)
                        break
    
            # 特殊处理：如意通6900品牌的序号字段需要自动填充序号（无论是否启用翻译）
            if brand_name == "如意通6900 ":
                for field in template_fields:
                    field_name = field["name"]
                    if isinstance(field_name, str) and field_name == "序号":
                        target_data[field_name] = [str(i + 1) for i in range(len(source_df))]
                        break
            
            # 特殊处理：GD-77品牌的Remarks<br/>字段需要设置默认值
            if brand_name == "GD-77":
                for field in template_fields:
                    field_name = field["name"]
                    if isinstance(field_name, str) and "remarks" in field_name.lower():
                        target_data[field_name] = ["<br/>"] * len(source_df)
                        break
            
            # 特殊处理：Retevis_RT52品牌的字段需要设置默认值
            if brand_name == "Retevis_RT52":
                for field in template_fields:
                    field_name = field["name"]
                    if isinstance(field_name, str):
                        # Call Type字段设置默认值为"1"
                        if field_name.lower() == "call type":
                            target_data[field_name] = ["1"] * len(source_df)
                        # Call Alert字段设置默认值为"0"
                        elif field_name.lower() == "call alert":
                            target_data[field_name] = ["0"] * len(source_df)
                        # Remarks字段设置默认值为"1"
                        elif field_name.lower() == "remarks":
                            target_data[field_name] = ["1"] * len(source_df)
            
            # 获取国家翻译字典从数据库
            country_translations = self._get_country_translations()
            
            # 获取省份/州翻译字典从数据库
            province_translations = self._get_province_translations()
            
            # 查找呼号列（如果存在）
            callsign_column = None
            for col in source_df.columns:
                if isinstance(col, str) and col.lower() in ["callsign", "call sign", "呼号"]:
                    callsign_column = col
                    break
            
            # 向量化字段映射（提高性能）
            for field in template_fields:
                field_name = field["name"]
                
                # 确保field_name是字符串类型
                if not isinstance(field_name, str):
                    continue
                
                # 跳过已经处理的字段
                if brand_name == "AnyTone" and field_name.lower() == "no.":
                    continue
                elif brand_name == "Baofeng_DM-860" and field_name.lower() == "number":
                    continue
                elif brand_name == "Baofeng_DM-860" and field_name.lower() == "type":
                    continue
                elif brand_name == "Baofeng_DM-860" and field_name.lower() == "ring style":
                    continue
                elif brand_name == "Baofeng_DM-860" and field_name.lower() == "call receive tone":
                    continue
                elif brand_name == "DM9100" and field_name == "序号":
                    continue
                elif brand_name == "DM9100" and field_name == "呼叫类型":
                    continue
                elif brand_name == "如意通6900 " and field_name == "序号":
                    continue
                elif brand_name == "GD-77" and "remarks" in field_name.lower():
                    continue
                elif brand_name == "Retevis_RT52" and field_name.lower() in ["call type", "call alert", "remarks"]:
                    continue
                
                # ID字段映射 (对讲机ID)
                elif field_name.lower() in ["对讲机id", "radio id", "id", "dmr id", "call id"]:
                    # 尝试从源数据中查找ID字段
                    found = False
                    for src_col in source_df.columns:
                        if isinstance(src_col, str) and src_col.lower() in ["radio_id", "id", "dmr id", "radio id", "call id", "dmrid"]:
                            # 正确处理空值，将NaN转换为空字符串
                            target_data[field_name] = source_df[src_col].fillna('').astype(str).tolist()
                            found = True
                            break
                    # 如果没有找到匹配的列，保持初始化的空值
                    if not found:
                        target_data[field_name] = [""] * len(source_df)
                
                # 名称字段映射 (别名、呼号)
                elif field_name.lower() in ["别名", "name", "alias", "contacts alias"]:
                    # 尝试从源数据中查找别名字字段，优先使用FIRST_NAME
                    found = False
                    for src_col in source_df.columns:
                        if isinstance(src_col, str) and src_col.lower() in ["first_name", "name"]:
                            # 正确处理空值，将NaN转换为空字符串
                            target_data[field_name] = source_df[src_col].fillna('').astype(str).tolist()
                            found = True
                            break
                    # 如果没有找到匹配的列，保持初始化的空值
                    if not found:
                        target_data[field_name] = [""] * len(source_df)
                
                elif field_name.lower() in ["呼号", "callsign", "call sign"]:
                    # 尝试从源数据中查找呼号字段，优先使用CALLSIGN
                    found = False
                    for src_col in source_df.columns:
                        if isinstance(src_col, str) and src_col.lower() in ["callsign", "call sign"]:
                            # 正确处理空值，将NaN转换为空字符串
                            target_data[field_name] = source_df[src_col].fillna('').astype(str).tolist()
                            found = True
                            break
                    # 如果没有找到匹配的列，保持初始化的空值
                    if not found:
                        target_data[field_name] = [""] * len(source_df)
                
                # 地理位置字段映射 (城市、省份、国家)
                elif field_name.lower() in ["城市", "city"]:
                    # 尝试从源数据中查找城市字段
                    found = False
                    for src_col in source_df.columns:
                        if isinstance(src_col, str) and src_col.lower() in ["city"]:
                            # 获取城市数据
                            city_data = source_df[src_col].fillna('').astype(str).tolist()
                            
                            # 如果启用了翻译功能，则翻译城市名称
                            if self.enable_translation:
                                # 翻译城市名称
                                translated_cities = []
                                for i, city in enumerate(city_data):
                                    # 处理空值和特殊值
                                    if city == '' or city.lower() == 'nan':
                                        translated_cities.append('')
                                        continue
                                        
                                    # 标准化城市名称
                                    normalized_city = city.strip()
                                    
                                    # 获取对应的国家和省份信息（如果存在）
                                    country_for_city = None
                                    state_for_city = None
                                    
                                    # 查找国家字段
                                    for country_col in source_df.columns:
                                        if isinstance(country_col, str) and country_col.lower() in ["country", "nation", "国家"]:
                                            country_for_city = source_df.iloc[i][country_col]
                                            break
                                    
                                    # 查找省份字段
                                    for state_col in source_df.columns:
                                        if isinstance(state_col, str) and state_col.lower() in ["state", "province", "省份"]:
                                            state_for_city = source_df.iloc[i][state_col]
                                            break
                                    
                                    # 从地理信息表中查找翻译
                                    translated_city = normalized_city
                                    try:
                                        conn = self._get_thread_connection()
                                        cursor = conn.cursor()
                                        
                                        # 如果有国家和省份信息，优先在特定国家和省份中查找
                                        if country_for_city and state_for_city:
                                            # 标准化国家和省份名称
                                            normalized_country = str(country_for_city).strip()
                                            normalized_state = str(state_for_city).strip()
                                            
                                            # 首先尝试在特定国家和省份中查找
                                            cursor.execute("""
                                                SELECT city_chinese, district_county FROM geographic_info 
                                                WHERE city = ? AND country = ? AND province_state = ? 
                                                AND (city_chinese IS NOT NULL AND city_chinese != '' OR district_county IS NOT NULL AND district_county != '')
                                                LIMIT 1
                                            """, (normalized_city, normalized_country, normalized_state))
                                            result = cursor.fetchone()
                                            if result:
                                                # 优先使用 city_chinese 字段，如果没有则使用 district_county
                                                translated_city = result[0] if result[0] and result[0] != '' else result[1]
                                            else:
                                                # 如果在特定国家和省份中没有找到，尝试在特定国家中查找
                                                cursor.execute("""
                                                    SELECT city_chinese, district_county FROM geographic_info 
                                                    WHERE city = ? AND country = ? 
                                                    AND (city_chinese IS NOT NULL AND city_chinese != '' OR district_county IS NOT NULL AND district_county != '')
                                                    LIMIT 1
                                                """, (normalized_city, normalized_country))
                                                result = cursor.fetchone()
                                                if result:
                                                    translated_city = result[0] if result[0] and result[0] != '' else result[1]
                                                else:
                                                    # 如果在特定国家中没有找到，使用全局查找
                                                    cursor.execute("""
                                                        SELECT city_chinese, district_county FROM geographic_info 
                                                        WHERE city = ? 
                                                        AND (city_chinese IS NOT NULL AND city_chinese != '' OR district_county IS NOT NULL AND district_county != '')
                                                        LIMIT 1
                                                    """, (normalized_city,))
                                                    result = cursor.fetchone()
                                                    if result:
                                                        translated_city = result[0] if result[0] and result[0] != '' else result[1]
                                                    else:
                                                        # 如果没有找到翻译数据，保持原城市名称
                                                        translated_city = normalized_city
                                        else:
                                            # 没有国家和省份信息，使用原始逻辑
                                            # 优先选择city_chinese不为空且不是默认值的记录
                                            cursor.execute("""
                                                SELECT city_chinese, district_county FROM geographic_info 
                                                WHERE city = ? 
                                                AND (city_chinese IS NOT NULL AND city_chinese != '' OR district_county IS NOT NULL AND district_county != '')
                                                LIMIT 1
                                            """, (normalized_city,))
                                            result = cursor.fetchone()
                                            if result:
                                                # 优先使用 city_chinese 字段，如果没有则使用 district_county
                                                translated_city = result[0] if result[0] and result[0] != '' else result[1]
                                            else:
                                                # 如果没有找到翻译数据，保持原城市名称
                                                translated_city = normalized_city
                                    except Exception as e:
                                        # 如果数据库查询失败，保持原城市名称
                                        translated_city = normalized_city
                                    
                                    translated_cities.append(translated_city)
                                target_data[field_name] = translated_cities
                            else:
                                # 如果未启用翻译功能，直接使用原始城市数据
                                target_data[field_name] = city_data
                            found = True
                            break
                    # 如果没有找到匹配的列，保持初始化的空值
                    if not found:
                        target_data[field_name] = [""] * len(source_df)
                
                elif field_name.lower() in ["省份", "state", "province"]:
                    # 尝试从源数据中查找省份/州字段
                    found = False
                    for src_col in source_df.columns:
                        if isinstance(src_col, str) and src_col.lower() in ["state", "province"]:
                            # 获取省份/州数据
                            state_data = source_df[src_col].fillna('').astype(str).tolist()
                            
                            # 如果启用了翻译功能，则翻译省份/州名称
                            if self.enable_translation:
                                # 初始化呼号省份映射器为None
                                CallSignProvinceMapper = None
                                # 如果有呼号列，导入呼号省份映射器
                                if callsign_column:
                                    try:
                                        from call_sign_province_mapper import CallSignProvinceMapper
                                    except ImportError:
                                        pass
                                
                                # 翻译省份/州名称
                                translated_states = []
                                for i, state in enumerate(state_data):
                                    # 处理空值和特殊值
                                    if state == '' or state.lower() == 'nan':
                                        # 如果省份字段为空，尝试通过呼号识别省份（仅适用于中国呼号）
                                        if callsign_column and CallSignProvinceMapper is not None:
                                            callsign = source_df.iloc[i][callsign_column]
                                            if callsign and str(callsign).strip():
                                                # 使用呼号识别省份
                                                province_from_callsign = CallSignProvinceMapper.recognize_province(str(callsign))
                                                if province_from_callsign != '未知省份':
                                                    translated_states.append(province_from_callsign)
                                                    continue
                                        translated_states.append('')
                                        continue
                                        
                                    # 标准化省份/州名称
                                    normalized_state = state.strip()
                                    
                                    # 判断是否为中国呼号，如果是则优先使用呼号识别
                                    if callsign_column and CallSignProvinceMapper is not None:
                                        callsign = source_df.iloc[i][callsign_column]
                                        if callsign and str(callsign).strip() and str(callsign).strip().upper().startswith('B'):
                                            # 中国呼号：优先使用呼号识别
                                            province_from_callsign = CallSignProvinceMapper.recognize_province(str(callsign))
                                            if province_from_callsign != '未知省份':
                                                translated_states.append(province_from_callsign)
                                                continue
                                    
                                    # 非中国呼号：使用英文比对
                                    # 首先尝试从province_translations表中查找翻译
                                    translated_state = normalized_state
                                    found_in_province_translations = False
                                    for country, translations in province_translations.items():
                                        if normalized_state in translations:
                                            translated_state = translations[normalized_state]
                                            found_in_province_translations = True
                                            break
                                    
                                    # 如果在province_translations中没有找到，再尝试从geographic_info表中查找
                                    if not found_in_province_translations:
                                        try:
                                            conn = self._get_thread_connection()
                                            cursor = conn.cursor()
                                            # 优先选择district_county不为空且不是默认值的记录
                                            cursor.execute("""
                                                SELECT province_chinese FROM geographic_info 
                                                WHERE province_state = ? AND province_chinese IS NOT NULL 
                                                AND province_chinese != ''
                                                LIMIT 1
                                            """, (normalized_state,))
                                            result = cursor.fetchone()
                                            if result:
                                                translated_state = result[0]
                                            else:
                                                # 如果没有找到更好的匹配，使用第一个匹配
                                                cursor.execute("SELECT province_chinese FROM geographic_info WHERE province_state = ? LIMIT 1", (normalized_state,))
                                                result = cursor.fetchone()
                                                if result:
                                                    translated_state = result[0]
                                        except Exception as e:
                                            pass
                                    
                                    translated_states.append(translated_state)
                                target_data[field_name] = translated_states
                            else:
                                # 如果未启用翻译功能，直接使用原始省份数据
                                target_data[field_name] = state_data
                            found = True
                            break
                    # 如果没有找到匹配的列，保持初始化的空值
                    if not found:
                        target_data[field_name] = [""] * len(source_df)
                
                elif field_name.lower() in ["国家", "country"]:
                    # 尝试从源数据中查找国家字段
                    found = False
                    for src_col in source_df.columns:
                        if isinstance(src_col, str) and src_col.lower() in ["country", "nation", "国家"]:
                            # 获取国家数据
                            country_data = source_df[src_col].fillna('').astype(str).tolist()
                            
                            # 如果启用了翻译功能，则翻译国家名称
                            if self.enable_translation:
                                # 翻译国家名称
                                translated_countries = []
                                for country in country_data:
                                    # 处理空值和特殊值
                                    if country == '' or country.lower() == 'nan':
                                        translated_countries.append('')
                                        continue
                                        
                                    # 标准化国家名称（去除多余空格，保持原始大小写）
                                    normalized_country = country.strip()
                                    # 保持原始大小写格式，因为翻译字典中就是这种格式
                                    
                                    # 优先检查精确匹配
                                    if normalized_country in country_translations:
                                        translated_countries.append(country_translations[normalized_country])
                                    else:
                                        # 如果没有精确匹配，尝试更智能的模糊匹配
                                        translated = False
                                        # 按照字符串长度降序排列，优先匹配更长的字符串
                                        sorted_keys = sorted(country_translations.keys(), key=len, reverse=True)
                                        for key in sorted_keys:
                                            # 精确匹配或完全包含关系
                                            if normalized_country.lower() == key.lower() or \
                                               normalized_country.lower() in key.lower() and len(normalized_country) > len(key) * 0.5:
                                                translated_countries.append(country_translations[key])
                                                translated = True
                                                break
                                        
                                        # 如果没有找到匹配项，保持原值
                                        if not translated:
                                            translated_countries.append(country)
                                target_data[field_name] = translated_countries
                            else:
                                # 如果未启用翻译功能，直接使用原始国家数据
                                target_data[field_name] = country_data
                            found = True
                            break
                    # 如果没有找到匹配的列，保持初始化的空值
                    if not found:
                        target_data[field_name] = [""] * len(source_df)
                
                # 其他字段，尝试直接映射
                else:
                    if isinstance(field_name, str) and field_name in source_df.columns:
                        # 正确处理空值，将NaN转换为空字符串
                        target_data[field_name] = source_df[field_name].fillna('').astype(str).tolist()
                    # 如果没有找到匹配的列，保持初始化的空值（已默认初始化）
            
            # 创建DataFrame
            target_df = pd.DataFrame(target_data)
            
            # 确保列的顺序正确
            target_df = target_df[target_columns]
            
            return target_df
            
        except Exception as e:
            raise Exception(f"数据转换失败: {str(e)}")
    
    def close(self):
        """关闭数据库连接"""
        # 关闭主线程连接
        if self.conn:
            self.conn.close()
            self.conn = None
        
        # 注意：不能从主线程关闭其他线程的连接
        # 每个线程应该自己管理自己的连接
        # 线程本地连接会在线程结束时自动清理
    
    # 注意：不要使用 __del__ 方法，因为它会在垃圾回收时被调用
    # 而垃圾回收可能发生在任何线程中，导致线程安全问题
    # 应该显式调用 close() 方法来关闭连接
    
    def _get_country_translations(self):
        """从数据库获取国家翻译字典"""
        try:
            conn = self._get_thread_connection()
            cursor = conn.cursor()
            
            # 查询所有国家翻译
            cursor.execute("SELECT english_name, chinese_name FROM country_translations")
            translations = cursor.fetchall()
            
            # 构建字典
            country_translations = {}
            for english, chinese in translations:
                country_translations[english] = chinese
            
            return country_translations
            
        except Exception as e:
            print(f"获取国家翻译字典失败: {str(e)}")
            # 如果数据库查询失败，返回空字典
            return {}
    
    def _get_province_translations(self):
        """从数据库获取省份/州翻译字典"""
        try:
            conn = self._get_thread_connection()
            cursor = conn.cursor()
            
            # 查询所有省份/州翻译，按国家分组
            cursor.execute("SELECT country, english_name, chinese_name FROM province_translations")
            translations = cursor.fetchall()
            
            # 构建嵌套字典 {国家: {英文名: 中文名}}
            province_translations = {}
            for country, english, chinese in translations:
                if country not in province_translations:
                    province_translations[country] = {}
                province_translations[country][english] = chinese
            
            return province_translations
            
        except Exception as e:
            print(f"获取省份/州翻译字典失败: {str(e)}")
            # 如果数据库查询失败，返回空字典
            return {}
    
    def get_geographic_info(self, country=None, province_state=None, city=None, district_county=None):
        """根据条件查询地理信息
        Args:
            country: 国家名称
            province_state: 省/州名称
            city: 城市名称
            district_county: 区/县名称
        Returns:
            匹配的地理信息列表
        """
        try:
            conn = self._get_thread_connection()
            cursor = conn.cursor()
            
            # 构建查询语句
            query = "SELECT country, province_state, city, district_county, street FROM geographic_info WHERE 1=1"
            params = []
            
            if country:
                query += " AND country = ?"
                params.append(country)
            
            if province_state:
                query += " AND province_state = ?"
                params.append(province_state)
            
            if city:
                query += " AND city = ?"
                params.append(city)
            
            if district_county:
                query += " AND district_county = ?"
                params.append(district_county)
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            # 转换为字典列表
            geo_info_list = []
            for row in results:
                geo_info_list.append({
                    "country": row[0],
                    "province_state": row[1],
                    "city": row[2],
                    "district_county": row[3],
                    "street": row[4]
                })
            
            return geo_info_list
            
        except Exception as e:
            print(f"查询地理信息失败: {str(e)}")
            return []
    
    def add_geographic_info(self, country, province_state=None, city=None, district_county=None, street=None):
        """添加地理信息到数据库
        Args:
            country: 国家名称（必需）
            province_state: 省/州名称（可选）
            city: 城市名称（可选）
            district_county: 区/县名称（可选）
            street: 街道名称（可选）
        Returns:
            添加成功返回True，失败返回False
        """
        try:
            conn = self._get_thread_connection()
            cursor = conn.cursor()
            
            # 插入地理信息
            cursor.execute("""
                INSERT INTO geographic_info 
                (country, province_state, city, district_county, street) 
                VALUES (?, ?, ?, ?, ?)
            """, (country, province_state, city, district_county, street))
            
            conn.commit()
            return True
            
        except Exception as e:
            print(f"添加地理信息失败: {str(e)}")
            return False
    
    def update_geographic_info(self, id, country=None, province_state=None, city=None, district_county=None, street=None):
        """更新地理信息
        Args:
            id: 地理信息记录ID
            country: 国家名称（可选）
            province_state: 省/州名称（可选）
            city: 城市名称（可选）
            district_county: 区/县名称（可选）
            street: 街道名称（可选）
        Returns:
            更新成功返回True，失败返回False
        """
        try:
            conn = self._get_thread_connection()
            cursor = conn.cursor()
            
            # 构建更新语句
            update_fields = []
            params = []
            
            if country is not None:
                update_fields.append("country = ?")
                params.append(country)
            
            if province_state is not None:
                update_fields.append("province_state = ?")
                params.append(province_state)
            
            if city is not None:
                update_fields.append("city = ?")
                params.append(city)
            
            if district_county is not None:
                update_fields.append("district_county = ?")
                params.append(district_county)
            
            if street is not None:
                update_fields.append("street = ?")
                params.append(street)
            
            if not update_fields:
                return True  # 没有需要更新的字段
            
            # 添加ID到参数列表
            params.append(id)
            
            # 执行更新
            query = f"UPDATE geographic_info SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(query, params)
            
            conn.commit()
            return True
            
        except Exception as e:
            print(f"更新地理信息失败: {str(e)}")
            return False
    
    def delete_geographic_info(self, id):
        """删除地理信息
        Args:
            id: 地理信息记录ID
        Returns:
            删除成功返回True，失败返回False
        """
        try:
            conn = self._get_thread_connection()
            cursor = conn.cursor()
            
            # 删除地理信息
            cursor.execute("DELETE FROM geographic_info WHERE id = ?", (id,))
            
            conn.commit()
            return True
            
        except Exception as e:
            print(f"删除地理信息失败: {str(e)}")
            return False
    
    def query_province_by_call_sign_code(self, code):
        """根据呼号代码查询对应的省份（仅适用于中国呼号）
        Args:
            code: 呼号代码（前缀），例如"4A"、"8D"等
        Returns:
            省份名称或None（仅适用于中国呼号，非中国呼号返回None）
        """
        try:
            conn = self._get_thread_connection()
            cursor = conn.cursor()
            
            # 查询chinese_call_sign_rules表
            cursor.execute("SELECT district FROM chinese_call_sign_rules WHERE prefix = ?", (code,))
            result = cursor.fetchone()
            
            if result:
                return result[0]
            else:
                return None
                
        except Exception as e:
            print(f"查询呼号代码对应的省份失败: {str(e)}")
            return None

    def _fuzzy_match_city(self, city_name):
        """模糊匹配城市名称，提高翻译覆盖率
        
        Args:
            city_name: 需要翻译的城市名称
            
        Returns:
            翻译后的城市名称，如果无法匹配则返回原名称
        """
        try:
            conn = self._get_thread_connection()
            cursor = conn.cursor()
            
            # 1. 首先尝试精确匹配（包含大小写不敏感）
            cursor.execute("""
                SELECT city_chinese, district_county FROM geographic_info 
                WHERE LOWER(city) = LOWER(?) 
                AND (city_chinese IS NOT NULL AND city_chinese != '' OR district_county IS NOT NULL AND district_county != '')
                LIMIT 1
            """, (city_name,))
            result = cursor.fetchone()
            if result:
                # 优先使用 city_chinese 字段，如果没有则使用 district_county
                return result[0] if result[0] and result[0] != '' else result[1]
            
            # 2. 尝试部分匹配（城市名称包含在数据库记录中）
            cursor.execute("""
                SELECT city, city_chinese, district_county FROM geographic_info 
                WHERE city LIKE ? 
                AND (city_chinese IS NOT NULL AND city_chinese != '' OR district_county IS NOT NULL AND district_county != '')
                LIMIT 1
            """, (f'%{city_name}%',))
            result = cursor.fetchone()
            if result:
                # 优先使用 city_chinese 字段，如果没有则使用 district_county
                return result[1] if result[1] and result[1] != '' else result[2]
            
            # 3. 尝试数据库记录包含在输入的城市名称中
            cursor.execute("""
                SELECT city, city_chinese, district_county FROM geographic_info 
                WHERE ? LIKE '%' || city || '%'
                AND (city_chinese IS NOT NULL AND city_chinese != '' OR district_county IS NOT NULL AND district_county != '')
                LIMIT 1
            """, (city_name,))
            result = cursor.fetchone()
            if result:
                # 优先使用 city_chinese 字段，如果没有则使用 district_county
                return result[1] if result[1] and result[1] != '' else result[2]
            
            # 4. 尝试常见城市名称的模糊匹配
            # 移除常见的后缀和前缀进行匹配
            cleaned_city = city_name.replace(' City', '').replace(' city', '').replace(' Town', '').replace(' town', '').strip()
            if cleaned_city != city_name:
                cursor.execute("""
                    SELECT city_chinese, district_county FROM geographic_info 
                    WHERE LOWER(city) = LOWER(?) 
                    AND (city_chinese IS NOT NULL AND city_chinese != '' OR district_county IS NOT NULL AND district_county != '')
                    LIMIT 1
                """, (cleaned_city,))
                result = cursor.fetchone()
                if result:
                    # 优先使用 city_chinese 字段，如果没有则使用 district_county
                    return result[0] if result[0] and result[0] != '' else result[1]
            
            # 5. 尝试基于发音的模糊匹配（简单的首字母匹配）
            if len(city_name) > 3:
                # 获取城市名称的前几个字符进行匹配
                prefix = city_name[:3].lower()
                cursor.execute("""
                    SELECT city, city_chinese, district_county FROM geographic_info 
                    WHERE LOWER(city) LIKE ? 
                    AND (city_chinese IS NOT NULL AND city_chinese != '' OR district_county IS NOT NULL AND district_county != '')
                    LIMIT 1
                """, (f'{prefix}%',))
                result = cursor.fetchone()
                if result:
                    # 优先使用 city_chinese 字段，如果没有则使用 district_county
                    return result[1] if result[1] and result[1] != '' else result[2]
            
            # 6. 尝试基于常见城市名称的映射
            common_mappings = {
                # 美国城市
                'NYC': 'New York', 'LA': 'Los Angeles', 'SF': 'San Francisco',
                'Chi': 'Chicago', 'Hou': 'Houston', 'Phx': 'Phoenix',
                'Philly': 'Philadelphia', 'SD': 'San Diego', 'Dal': 'Dallas',
                'SJ': 'San Jose', 'Austin': 'Austin', 'Jack': 'Jacksonville',
                'Indy': 'Indianapolis', 'Col': 'Columbus', 'Char': 'Charlotte',
                'Sea': 'Seattle', 'Den': 'Denver', 'Was': 'Washington',
                'Bos': 'Boston', 'El': 'El Paso', 'Det': 'Detroit',
                'Nash': 'Nashville', 'Port': 'Portland', 'LV': 'Las Vegas',
                'Balt': 'Baltimore', 'St': 'St. Louis', 'Riv': 'Riverside',
                
                # 加拿大城市
                'Tor': 'Toronto', 'Van': 'Vancouver', 'Mon': 'Montreal',
                'Cal': 'Calgary', 'Edm': 'Edmonton', 'Ott': 'Ottawa',
                'Winn': 'Winnipeg', 'Que': 'Quebec City', 'Ham': 'Hamilton',
                
                # 中国城市
                'BJ': 'Beijing', 'SH': 'Shanghai', 'GZ': 'Guangzhou',
                'SZ': 'Shenzhen', 'CD': 'Chengdu', 'HZ': 'Hangzhou',
                'WH': 'Wuhan', 'XA': 'XiAn', 'NJ': 'Nanjing',
                'TJ': 'Tianjin', 'CQ': 'Chongqing', 'SY': 'Shenyang',
                'DL': 'Dalian', 'CC': 'Changchun', 'HEB': 'Harbin',
                
                # 其他国家城市
                'Lon': 'London', 'Par': 'Paris', 'Ber': 'Berlin',
                'Mad': 'Madrid', 'Rom': 'Rome', 'Tok': 'Tokyo',
                'Syd': 'Sydney', 'Mel': 'Melbourne', 'Ist': 'Istanbul',
                'Mum': 'Mumbai', 'Del': 'Delhi', 'Ban': 'Bangalore',
                'Sin': 'Singapore', 'BKK': 'Bangkok', 'Seo': 'Seoul'
            }
            
            for short_name, full_name in common_mappings.items():
                if short_name.lower() in city_name.lower():
                    cursor.execute("""
                        SELECT city_chinese, district_county FROM geographic_info 
                        WHERE LOWER(city) = LOWER(?) 
                        AND (city_chinese IS NOT NULL AND city_chinese != '' OR district_county IS NOT NULL AND district_county != '')
                        LIMIT 1
                    """, (full_name,))
                    result = cursor.fetchone()
                    if result:
                        # 优先使用 city_chinese 字段，如果没有则使用 district_county
                        return result[0] if result[0] and result[0] != '' else result[1]
            
        except Exception as e:
            # 如果模糊匹配过程中出错，返回原城市名称
            pass
        
        # 如果所有匹配方法都失败，返回原城市名称
        return city_name
