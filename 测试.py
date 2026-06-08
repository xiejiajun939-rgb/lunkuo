import sys
import os
import traceback
import pandas as pd
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QFileDialog, QProgressBar,
                             QTextEdit, QTabWidget, QTableWidget, QTableWidgetItem,
                             QMessageBox, QGroupBox, QComboBox, QSizePolicy,
                             QScrollArea, QFrame, QFormLayout, QGridLayout, QDateEdit,
                             QDialog, QDialogButtonBox, QListWidget, QInputDialog)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDate, QSettings
from PyQt5.QtGui import QFont, QIcon, QDragEnterEvent, QDropEvent, QColor
from openpyxl.utils import get_column_letter


class WorkerThread(QThread):
    progress = pyqtSignal(int)
    message = pyqtSignal(str)
    result = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, refund_path, order_path, output_path, group_id, monthly_targets=None):
        super().__init__()
        self.refund_path = refund_path
        self.order_path = order_path
        self.output_path = output_path
        self.group_id = group_id
        self.monthly_targets = monthly_targets or {}
        self.results = {}
        self.canceled = False

        # 非直播主播列表（用于判断非直播销售）
        self.non_live_anchors = {
            '轮廓平跃女装专卖店', '轮廓聚如女装专卖店', '吉丘古儿官方旗舰店',
            '轮廓飞聚女装专卖店', '女王姐', '墨儿优选', '1305', '害羞的井妹'
        }

    # ---------- 智能列名匹配 ----------
    def _find_refund_columns(self, df):
        # 完全自动化的智能列识别方案 - 基于语义相似度和权重评分
        
        # 扩展的列名关键词库（按语义分类和权重排序）
        refund_patterns = [
            # 高权重：核心退款关键词
            {'keywords': ['退款金额', '实退金额', '应退金额'], 'weight': 10},
            # 中权重：通用退款关键词
            {'keywords': ['退款', '退货款', '售后退款'], 'weight': 8},
            # 低权重：相关退款关键词
            {'keywords': ['财务退款', '退款额', '退款数'], 'weight': 6},
            # 扩展权重：金额相关
            {'keywords': ['金额', '元', '￥', 'RMB'], 'weight': 4},
            # 基础权重：退款相关
            {'keywords': ['退', 'refund', 'money'], 'weight': 2}
        ]
        
        anchor_patterns = [
            # 高权重：核心主播关键词
            {'keywords': ['主播', '直播账号', '达人名称'], 'weight': 10},
            # 中权重：通用主播关键词
            {'keywords': ['主播名称', '直播昵称', '达人'], 'weight': 8},
            # 低权重：相关主播关键词
            {'keywords': ['主播名', '直播人员', '主播账号'], 'weight': 6},
            # 扩展权重：人员相关
            {'keywords': ['人员', '账号', '名称'], 'weight': 4}
        ]
        
        shop_patterns = [
            # 高权重：核心店铺关键词
            {'keywords': ['店铺', '店铺名称', '店名'], 'weight': 10},
            # 中权重：通用店铺关键词
            {'keywords': ['商店', '商家'], 'weight': 8},
            # 低权重：相关店铺关键词
            {'keywords': ['店铺名', '店铺标识'], 'weight': 6},
            # 扩展权重：商业相关
            {'keywords': ['名称', 'ID', '编号'], 'weight': 4}
        ]
        
        def calculate_column_score(column_name, patterns):
            """计算列名与模式集的匹配分数"""
            score = 0
            column_lower = column_name.lower()
            
            for pattern in patterns:
                for keyword in pattern['keywords']:
                    if keyword in column_lower:
                        score += pattern['weight']
                        # 精确匹配加分
                        if keyword == column_lower.strip():
                            score += 5
                        break  # 每个模式只匹配一个关键词
            
            return score
        
        def find_best_column(df, patterns):
            """找到与模式最匹配的列"""
            best_column = None
            best_score = 0
            
            for col in df.columns:
                score = calculate_column_score(str(col), patterns)
                if score > best_score:
                    best_score = score
                    best_column = col
            
            # 如果分数太低，认为没有匹配
            if best_score < 5:
                return None
            
            return best_column
        
        # 智能识别各列
        refund_col = find_best_column(df, refund_patterns)
        anchor_col = find_best_column(df, anchor_patterns)
        shop_col = find_best_column(df, shop_patterns)
        
        # 调试信息：显示识别结果和分数
        if refund_col:
            refund_score = calculate_column_score(str(refund_col), refund_patterns)
            self.message.emit(f"退款列识别：{refund_col} (分数：{refund_score})")
        if anchor_col:
            anchor_score = calculate_column_score(str(anchor_col), anchor_patterns)
            self.message.emit(f"主播列识别：{anchor_col} (分数：{anchor_score})")
        if shop_col:
            shop_score = calculate_column_score(str(shop_col), shop_patterns)
            self.message.emit(f"店铺列识别：{shop_col} (分数：{shop_score})")
        
        return refund_col, anchor_col, shop_col

    def _find_anchor_column(self, df):
        """自动识别主播列"""
        anchor_patterns = [
            # 高权重：核心主播关键词
            {'keywords': ['主播', '直播账号', '达人名称'], 'weight': 10},
            # 中权重：通用主播关键词
            {'keywords': ['主播名称', '直播昵称', '达人'], 'weight': 8},
            # 低权重：相关主播关键词
            {'keywords': ['主播名', '直播人员', '主播账号'], 'weight': 6},
            # 扩展权重：人员相关
            {'keywords': ['人员', '账号', '名称'], 'weight': 4}
        ]
        
        def calculate_column_score(column_name, patterns):
            """计算列名与模式集的匹配分数"""
            score = 0
            column_lower = column_name.lower()
            
            for pattern in patterns:
                for keyword in pattern['keywords']:
                    if keyword in column_lower:
                        score += pattern['weight']
                        # 精确匹配加分
                        if keyword == column_lower.strip():
                            score += 5
                        break  # 每个模式只匹配一个关键词
            
            return score
        
        def find_best_column(df, patterns):
            """找到与模式最匹配的列"""
            best_column = None
            best_score = 0
            
            for col in df.columns:
                score = calculate_column_score(str(col), patterns)
                if score > best_score:
                    best_score = score
                    best_column = col
            
            # 如果分数太低，认为没有匹配
            if best_score < 5:
                return None
            
            return best_column
        
        return find_best_column(df, anchor_patterns)

    def _find_order_columns(self, df):
        mapping = {
            '商店': ['商店', '店铺名称', '店名', '店铺'],
            '均摊金额': ['均摊金额', '实付金额', '成交金额', '实际销售金额'],
            '市场价': ['市场价', '吊牌价', '原价', '标准价'],
            '销退数量': ['销退数量', '退货数量', '退款数量', '退货件数'],
            '销售平台': ['销售平台', '平台', '渠道', '销售渠道'],
            '主播': ['主播', '直播账号', '达人', '主播名称', '直播昵称']
        }
        found = {}
        for std_name, keywords in mapping.items():
            matched = None
            for col in df.columns:
                if any(kw in col for kw in keywords):
                    matched = col
                    break
            if matched is None and std_name != '主播':
                raise KeyError(f"订单表缺少必要列（尝试匹配：{keywords}）")
            found[std_name] = matched
        return found

    # ---------- 加载退款数据 ----------
    def load_refund_data(self):
        if not self.refund_path or not os.path.exists(self.refund_path):
            self.message.emit(f"第{self.group_id}组未提供退款文件，退款按0处理")
            # 返回格式一致的空数据框，包含必要的列
            empty_df = pd.DataFrame(columns=['店铺', '主播', '财务退款'])
            empty_refund_by_shop = pd.DataFrame(columns=['商店', '财务退款'])
            empty_refund_by_shop_anchor = pd.DataFrame(columns=['商店', '主播', '财务退款'])
            empty_non_live_refund = pd.DataFrame(columns=['商店', '非直播退款'])
            return empty_df, empty_refund_by_shop, empty_refund_by_shop_anchor, empty_non_live_refund

        df = pd.read_excel(self.refund_path)
        
        # 调试信息：显示所有列名
        self.message.emit(f"第{self.group_id}组退款表列名: {list(df.columns)}")
        
        refund_col, anchor_col, shop_col = self._find_refund_columns(df)
        
        # 调试信息：显示找到的列
        self.message.emit(f"第{self.group_id}组识别结果 - 退款列: {refund_col}, 主播列: {anchor_col}, 店铺列: {shop_col}")
        
        if refund_col is None:
            self.message.emit(f"警告：第{self.group_id}组退款表中未能识别退款金额列，退款金额将按0处理")
            # 创建一个空的退款数据
            df['财务退款'] = 0.0
        else:
            # 退款金额处理：表格中的正数就是退款金额，不需要转换符号
            raw_vals = pd.to_numeric(df[refund_col], errors='coerce')
            
            # 调试信息：显示原始退款金额统计
            non_zero_count = (raw_vals != 0).sum()
            self.message.emit(f"第{self.group_id}组原始退款数据：总数{len(raw_vals)}，非零值{non_zero_count}，中位数{raw_vals.median():.2f}")
            
            # 直接使用原始值，表格中的正数就是退款金额
            df['财务退款'] = raw_vals.fillna(0)
            
            # 验证退款金额的符号
            positive_count = (df['财务退款'] > 0).sum()
            negative_count = (df['财务退款'] < 0).sum()
            self.message.emit(f"退款金额符号验证：正数{positive_count}条，负数{negative_count}条")

        # 店铺列处理
        if shop_col is None:
            self.message.emit(f"警告：第{self.group_id}组退款表中未能识别店铺列，使用默认店铺名")
            df['店铺'] = '默认店铺'
        else:
            df['店铺'] = df[shop_col].astype(str).str.strip()

        # 主播列处理：空值或无效值归为"非直播"
        if anchor_col:
            df['主播'] = df[anchor_col].astype(str).str.strip()
            df.loc[df['主播'].isin(['', 'nan', 'None', 'NaN']), '主播'] = '非直播'
        else:
            df['主播'] = '非直播'

        # 按店铺+主播汇总退款（用于主播业绩扣减）
        if '店铺' in df.columns and '主播' in df.columns:
            refund_by_shop_anchor = df.groupby(['店铺', '主播'], as_index=False)['财务退款'].sum()
            refund_by_shop_anchor = refund_by_shop_anchor.rename(columns={'店铺': '商店'})
        else:
            self.message.emit(f"警告：第{self.group_id}组退款数据缺少必要列，创建空数据框")
            refund_by_shop_anchor = pd.DataFrame(columns=['商店', '主播', '财务退款'])

        # 按店铺汇总退款（用于其他汇总）
        if '店铺' in df.columns:
            refund_by_shop = df.groupby('店铺', as_index=False)['财务退款'].sum()
            refund_by_shop = refund_by_shop.rename(columns={'店铺': '商店'})
        else:
            self.message.emit(f"警告：第{self.group_id}组退款数据缺少店铺列，创建空数据框")
            refund_by_shop = pd.DataFrame(columns=['商店', '财务退款'])

        # 非直播退款子集（主播为"非直播"或属于非直播列表）
        if '主播' in df.columns:
            non_live_mask = (df['主播'] == '非直播') | (df['主播'].isin(self.non_live_anchors))
            non_live_refund = df[non_live_mask].groupby('店铺', as_index=False)['财务退款'].sum()
            non_live_refund = non_live_refund.rename(columns={'店铺': '商店', '财务退款': '非直播退款'})
        else:
            self.message.emit("警告：退款数据缺少主播列，非直播退款按0处理")
            non_live_refund = pd.DataFrame(columns=['商店', '非直播退款'])

        # 调试信息：显示处理结果
        total_refund = df['财务退款'].sum()
        self.message.emit(f"第{self.group_id}组退款数据处理完成：总退款金额 {total_refund:.2f}，共 {len(df)} 条记录")
        
        return df, refund_by_shop, refund_by_shop_anchor, non_live_refund

    # ---------- 加载订单数据 ----------
    def load_orders_data(self):
        if not self.order_path or not os.path.exists(self.order_path):
            self.message.emit(f"第{self.group_id}组未提供订单文件，销售额按0处理")
            empty_df = pd.DataFrame(columns=[
                '商店', '销退数量', '市场价', '均摊金额', '吊牌价',
                '发货金额', '退货金额', '销售类型', '主播', '退货金额_原',
                '销售金额', '销售平台'
            ])
            return empty_df

        df = pd.read_excel(self.order_path, sheet_name="sheet1")
        col_map = self._find_order_columns(df)

        # 重命名列
        rename_dict = {v: k for k, v in col_map.items() if v is not None}
        if rename_dict:
            df = df.rename(columns=rename_dict)

        # 必要列检查
        required = ['商店', '均摊金额', '市场价', '销退数量']
        for req in required:
            if req not in df.columns:
                raise ValueError(f"订单表缺少列: {req}")

        # 数值转换
        df['均摊金额'] = pd.to_numeric(df['均摊金额'], errors='coerce').fillna(0)
        df['市场价'] = pd.to_numeric(df['市场价'], errors='coerce').fillna(0)
        df['销退数量'] = pd.to_numeric(df['销退数量'], errors='coerce').fillna(0)

        # 派生列
        df['吊牌价'] = df['销退数量'] * df['市场价']
        df['发货金额'] = df['均摊金额'].clip(lower=0)
        df['退货金额'] = (-df['均摊金额']).clip(lower=0)
        df['退货金额_原'] = np.where(df['销退数量'] < 0, df['销退数量'] * df['均摊金额'], 0)
        df['销售金额'] = np.where(df['销退数量'] > 0, df['销退数量'] * df['均摊金额'], 0)

        # 销售平台
        if '销售平台' in df.columns:
            df['销售平台'] = df['销售平台'].fillna('未知平台').astype(str)
        else:
            df['销售平台'] = '未知平台'

        # 主播与销售类型
        if '主播' in df.columns and col_map.get('主播') is not None:
            df['主播'] = df['主播'].astype(str).str.strip()
            df.loc[df['主播'].isin(['', 'nan', 'None']), '主播'] = ''
            
            # 调试信息：显示主播名称分布
            unique_anchors = df['主播'].unique()
            self.message.emit(f"第{self.group_id}组主播列表：{list(unique_anchors)}")
            
            # 检查特定主播是否在非直播列表中
            target_anchors = ['吉丘古儿官方旗舰店', '轮廓平跃女装专卖店', '轮廓飞聚女装专卖店']
            for anchor in target_anchors:
                if anchor in unique_anchors:
                    is_non_live = anchor in self.non_live_anchors
                    self.message.emit(f"主播 '{anchor}' 是否在非直播列表：{is_non_live}")
            
            df['销售类型'] = df['主播'].apply(
                lambda x: '直播销售' if x and x not in self.non_live_anchors else '非直播销售'
            )
            
            # 详细调试：检查指定主播的销售类型
            target_anchors = ['轮廓平跃女装专卖店', '轮廓聚如女装专卖店', '吉丘古儿官方旗舰店', 
                            '轮廓飞聚女装专卖店', '女王姐', '墨儿优选', '1305', '害羞的井妹']
            for anchor in target_anchors:
                if anchor in df['主播'].values:
                    sales_type = df[df['主播'] == anchor]['销售类型'].iloc[0] if not df[df['主播'] == anchor].empty else '未找到'
                    self.message.emit(f"主播 '{anchor}' 的销售类型：{sales_type}")
            
            # 调试信息：显示销售类型分布
            sales_type_counts = df['销售类型'].value_counts()
            self.message.emit(f"第{self.group_id}组销售类型分布：{sales_type_counts.to_dict()}")
            
        else:
            df['主播'] = ''
            df['销售类型'] = '非直播销售'
            self.message.emit(f"第{self.group_id}组订单数据缺少主播列，全部按非直播销售处理")

        self.message.emit(f"第{self.group_id}组订单数据加载成功，共 {len(df)} 条记录")
        return df

    # ---------- 业绩计算 ----------
    def calculate_performance(self, orders_df, refund_by_shop, refund_by_shop_anchor, non_live_refund_df):
        results = {}

        # 1. 商店业绩汇总
        store_perf = orders_df.groupby('商店', as_index=False).agg(
            商店销售额=("均摊金额", "sum"),
            吊牌价总额=("吊牌价", "sum"),
            发货金额=("发货金额", "sum"),
            退货金额=("退货金额", "sum")
        )
        
        # 安全检查：如果退款数据为空或没有'商店'列，创建空数据框
        if not refund_by_shop.empty and '商店' in refund_by_shop.columns:
            store_summary = pd.merge(store_perf, refund_by_shop, on='商店', how='left')
        else:
            self.message.emit(f"警告：第{self.group_id}组退款数据为空或格式错误，财务退款按0处理")
            store_summary = store_perf.copy()
            store_summary['财务退款'] = 0.0
        
        store_summary['财务退款'] = store_summary['财务退款'].fillna(0)
        # 修正：财务退款是正数，应该用减法计算实际销售（退款是支出）
        store_summary['实际销售'] = store_summary['商店销售额'] - store_summary['财务退款']

        all_total = store_summary[['商店销售额', '吊牌价总额', '发货金额', '退货金额', '财务退款', '实际销售']].sum()
        all_total['商店'] = '所有店铺汇总'
        store_summary = pd.concat([store_summary, all_total.to_frame().T], ignore_index=True)

        # 按平台汇总
        for platform, pname in [('抖音小店', '抖音小店汇总'), ('微信小店', '视频号小店汇总')]:
            sub = orders_df[orders_df['销售平台'] == platform]
            if not sub.empty:
                sub_perf = sub.groupby('商店', as_index=False).agg(
                    商店销售额=("均摊金额", "sum"),
                    吊牌价总额=("吊牌价", "sum"),
                    发货金额=("发货金额", "sum"),
                    退货金额=("退货金额", "sum")
                )
                
                # 安全检查：如果退款数据为空或没有'商店'列，创建空数据框
                if not refund_by_shop.empty and '商店' in refund_by_shop.columns:
                    sub_summary = pd.merge(sub_perf, refund_by_shop, on='商店', how='left')
                else:
                    sub_summary = sub_perf.copy()
                    sub_summary['财务退款'] = 0.0
                
                sub_summary['财务退款'] = sub_summary['财务退款'].fillna(0)
                # 修正：财务退款是正数，应该用减法计算实际销售（退款是支出）
                sub_summary['实际销售'] = sub_summary['商店销售额'] - sub_summary['财务退款']
                platform_total = sub_summary[['商店销售额', '吊牌价总额', '发货金额', '退货金额', '财务退款', '实际销售']].sum()
                platform_total['商店'] = pname
                store_summary = pd.concat([store_summary, platform_total.to_frame().T], ignore_index=True)

        results['商店业绩汇总'] = store_summary

        # 2. 销售类型分析（按商店）
        sales_type = orders_df.groupby(['商店', '销售类型'], as_index=False).agg(
            销售额=("均摊金额", "sum"),
            吊牌价总额=("吊牌价", "sum"),
            发货金额=("发货金额", "sum"),
            退货金额=("退货金额", "sum"),
            退货总额=("退货金额_原", "sum"),
            销售总额=("销售金额", "sum")
        )
        # 非直播销售加上对应的非直播退款（退款金额是正数）
        if not non_live_refund_df.empty:
            for idx, row in sales_type.iterrows():
                if row['销售类型'] == '非直播销售':
                    refund_val = non_live_refund_df.loc[non_live_refund_df['商店'] == row['商店'], '非直播退款']
                    if not refund_val.empty:
                        sales_type.at[idx, '销售额'] += refund_val.iloc[0]
        sales_type['退款率'] = (abs(sales_type['退货总额']) / sales_type['销售总额'].replace(0, np.nan)).fillna(0)
        sales_type['折扣率'] = (sales_type['销售额'] / sales_type['吊牌价总额'].replace(0, np.nan)).fillna(0)
        sales_type = sales_type.drop(columns=['退货总额', '销售总额'])
        results['销售类型分析(按商店)'] = sales_type

        # 3. 主播业绩明细
        anchor_sales = pd.DataFrame()
        
        # 详细调试信息：检查订单数据的主播列情况
        self.message.emit(f"订单数据列名：{list(orders_df.columns)}")
        
        # 优先使用"主播名称"列，如果不存在则使用"主播"列
        if '主播名称' in orders_df.columns:
            orders_df['主播'] = orders_df['主播名称']
            self.message.emit("使用'主播名称'列作为主播列")
        elif '主播' in orders_df.columns:
            self.message.emit("使用'主播'列作为主播列")
        
        if '主播' in orders_df.columns:
            self.message.emit(f"主播列存在，主播数量：{orders_df['主播'].nunique()}")
            self.message.emit(f"主播列表：{orders_df['主播'].unique().tolist()}")
        
        # 检查主播列是否存在，如果不存在则尝试自动识别
        if '主播' not in orders_df.columns:
            # 尝试自动识别主播列
            anchor_col = self._find_anchor_column(orders_df)
            if anchor_col:
                orders_df['主播'] = orders_df[anchor_col]
                self.message.emit(f"自动识别主播列：{anchor_col}")
                self.message.emit(f"识别后的主播列表：{orders_df['主播'].unique().tolist()}")
            else:
                self.message.emit("警告：未能识别主播列，主播业绩明细将为空")
                results['主播业绩明细'] = pd.DataFrame(columns=['商店', '主播名称', '销售额', '吊牌价总额', '发货金额', '退货金额', '财务退款', '退款率', '折扣率'])
                return results
        
        # 检查退款数据的主播情况
        if not refund_by_shop_anchor.empty:
            self.message.emit(f"退款数据主播列表：{refund_by_shop_anchor['主播'].unique().tolist()}")
        
        anchor_df = orders_df[orders_df['销售类型'] == '直播销售']
        if not anchor_df.empty:
            self.message.emit(f"直播销售数据行数：{len(anchor_df)}")
            self.message.emit(f"直播销售主播数量：{anchor_df['主播'].nunique()}")
            
            anchor_sales = anchor_df.groupby(['商店', '主播'], as_index=False).agg(
                销售额=("均摊金额", "sum"),
                吊牌价总额=("吊牌价", "sum"),
                发货金额=("发货金额", "sum"),
                退货金额=("退货金额", "sum"),
                退货总额=("退货金额_原", "sum"),
                销售总额=("销售金额", "sum")
            )
            
            self.message.emit(f"主播业绩分组后行数：{len(anchor_sales)}")
            
            # 合并财务退款数据到主播业绩明细（安全检查）
            if not refund_by_shop_anchor.empty and all(col in refund_by_shop_anchor.columns for col in ['商店', '主播']):
                anchor_sales = pd.merge(anchor_sales, refund_by_shop_anchor, on=['商店', '主播'], how='left')
                anchor_sales['财务退款'] = anchor_sales['财务退款'].fillna(0)
            else:
                self.message.emit("警告：退款数据为空或格式错误，主播业绩财务退款按0处理")
                anchor_sales['财务退款'] = 0.0
            
            self.message.emit(f"合并退款后主播业绩行数：{len(anchor_sales)}")
            
            # 修正：直播业绩 = 发货金额 - 退货金额 - 财务退款
            anchor_sales['销售额'] = anchor_sales['发货金额'] - anchor_sales['退货金额'] - anchor_sales['财务退款']
            
            # 显示计算过程
            for idx, row in anchor_sales.iterrows():
                self.message.emit(f"主播 '{row['主播']}' 在店铺 '{row['商店']}' 计算业绩：发货{row['发货金额']:.2f} - 退货{row['退货金额']:.2f} - 退款{row['财务退款']:.2f} = 业绩{row['销售额']:.2f}")
            
            anchor_sales['退款率'] = (abs(anchor_sales['退货总额']) / anchor_sales['销售总额'].replace(0, np.nan)).fillna(0)
            anchor_sales['折扣率'] = (anchor_sales['销售额'] / anchor_sales['吊牌价总额'].replace(0, np.nan)).fillna(0)
            anchor_sales = anchor_sales.drop(columns=['退货总额', '销售总额'])
            
            # 将主播列重命名为主播名称
            anchor_sales = anchor_sales.rename(columns={'主播': '主播名称'})
        else:
            self.message.emit("警告：没有直播销售数据")
            anchor_sales = pd.DataFrame(columns=['商店', '主播名称', '销售额', '吊牌价总额', '发货金额', '退货金额', '财务退款', '退款率', '折扣率'])
        
        self.message.emit(f"最终主播业绩明细行数：{len(anchor_sales)}")
        results['主播业绩明细'] = anchor_sales

        # 4. 非直播业绩统计
        non_live_df = orders_df[orders_df['销售类型'] == '非直播销售']
        if non_live_df.empty:
            non_live_summary = pd.DataFrame(columns=[
                '商店', '非直播销售额', '非直播吊牌价总额', '非直播发货金额', 
                '非直播退货金额', '非直播折扣率', '财务退款', '数据类别'
            ])
        else:
            store_non = non_live_df.groupby('商店', as_index=False).agg(
                非直播销售额=("均摊金额", "sum"),
                非直播吊牌价总额=("吊牌价", "sum"),
                非直播发货金额=("发货金额", "sum"),
                非直播退货金额=("退货金额", "sum")
            )
            
            # 安全检查：合并非直播退款数据
            if not non_live_refund_df.empty and '商店' in non_live_refund_df.columns:
                store_non = pd.merge(store_non, non_live_refund_df, on='商店', how='left')
                store_non['非直播退款'] = store_non['非直播退款'].fillna(0)
            else:
                self.message.emit("警告：非直播退款数据为空或格式错误，非直播退款按0处理")
                store_non['非直播退款'] = 0.0
            
            # 修正：非直播销售额 = 非直播发货金额 - 非直播退货金额 - 非直播的财务退款
            store_non['非直播销售额'] = store_non['非直播发货金额'] - store_non['非直播退货金额'] - store_non['非直播退款']
            store_non = store_non.drop(columns=['非直播退款'])

            # 所有店铺汇总
            total_ship = non_live_df['发货金额'].sum()
            total_return = non_live_df['退货金额'].sum()
            total_refund = non_live_refund_df['非直播退款'].sum()
            total_sales = total_ship - total_return - total_refund
            total_tag = non_live_df['吊牌价'].sum()
            all_non = pd.DataFrame({
                '商店': ['所有店铺'],
                '非直播销售额': [total_sales],
                '非直播吊牌价总额': [total_tag],
                '非直播发货金额': [total_ship],
                '非直播退货金额': [total_return]
            })

            # 按平台汇总
            for platform, pname in [('抖音小店', '抖音小店'), ('微信小店', '视频号小店')]:
                sub = non_live_df[non_live_df['销售平台'] == platform]
                if not sub.empty:
                    shops = sub['商店'].unique()
                    # 安全检查：计算平台非直播退款
                    if not non_live_refund_df.empty and '商店' in non_live_refund_df.columns:
                        sub_refund = non_live_refund_df[non_live_refund_df['商店'].isin(shops)]['非直播退款'].sum()
                    else:
                        sub_refund = 0.0
                    
                    sub_ship = sub['发货金额'].sum()
                    sub_return = sub['退货金额'].sum()
                    sub_sales = sub_ship - sub_return - sub_refund
                    sub_tag = sub['吊牌价'].sum()
                    sub_df = pd.DataFrame({
                        '商店': [pname],
                        '非直播销售额': [sub_sales],
                        '非直播吊牌价总额': [sub_tag],
                        '非直播发货金额': [sub_ship],
                        '非直播退货金额': [sub_return]
                    })
                    store_non = pd.concat([store_non, sub_df], ignore_index=True)

            non_live_summary = pd.concat([store_non, all_non], ignore_index=True)
            non_live_summary['非直播折扣率'] = (non_live_summary['非直播销售额'] / 
                                                non_live_summary['非直播吊牌价总额'].replace(0, np.nan)).fillna(0)

        non_live_summary['数据类别'] = '日数据' if self.group_id == 1 else '月累计数据'
        # 非直播销售额已经包含了非直播退款，不需要再单独显示财务退款
        # 如果需要显示财务退款，应该显示非直播退款部分
        if not non_live_refund_df.empty and '商店' in non_live_refund_df.columns:
            # 只显示非直播退款部分，而不是所有退款
            non_live_summary = pd.merge(non_live_summary, non_live_refund_df.rename(columns={'非直播退款': '财务退款'}), on='商店', how='left')
            non_live_summary['财务退款'] = non_live_summary['财务退款'].fillna(0)
        else:
            non_live_summary['财务退款'] = 0.0
        results['非直播业绩统计'] = non_live_summary

        # 5. 退款分配明细
        if not refund_by_shop_anchor.empty:
            # 只显示主播的退款分配，不重复显示非直播汇总
            # 非直播退款已经在非直播业绩统计中单独显示
            results['退款分配明细'] = refund_by_shop_anchor
        else:
            results['退款分配明细'] = pd.DataFrame(columns=['商店', '主播', '财务退款'])

        return results

    # ---------- 保存结果 ----------
    def save_results(self, results_dict):
        output_dir = os.path.dirname(self.output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with pd.ExcelWriter(self.output_path, engine='openpyxl') as writer:
            for sheet_name, df in results_dict.items():
                if df.empty:
                    continue
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                worksheet = writer.sheets[sheet_name]
                for i, col in enumerate(df.columns, 1):
                    max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
                    col_letter = get_column_letter(i)
                    worksheet.column_dimensions[col_letter].width = min(max_len, 30)

    # ---------- 主运行入口 ----------
    def run(self):
        try:
            self.message.emit(f"开始处理第{self.group_id}组数据...")
            self.progress.emit(5)

            refund_raw, refund_by_shop, refund_by_shop_anchor, non_live_refund = self.load_refund_data()
            self.progress.emit(25)

            orders_df = self.load_orders_data()
            self.progress.emit(50)

            results = self.calculate_performance(orders_df, refund_by_shop, refund_by_shop_anchor, non_live_refund)
            self.progress.emit(80)

            self.save_results(results)
            self.progress.emit(95)

            self.results = results
            self.result.emit(results)
            self.message.emit(f"第{self.group_id}组分析完成！结果保存至: {self.output_path}")
            self.progress.emit(100)

        except Exception as e:
            error_msg = f"第{self.group_id}组处理失败: {str(e)}\n{traceback.format_exc()}"
            self.error.emit(error_msg)


# ------------------------------ UI 组件 ------------------------------
class DropArea(QLabel):
    files_dropped = pyqtSignal(dict)
    cleared = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText("请一次性拖入【财务退款任务单】和【线上销售退货汇总】\n（可只拖一个，缺省数据按 0 处理）")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(140)
        self.setStyleSheet("""
            QLabel {
                border: 3px dashed #6c757d;
                border-radius: 12px;
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                          stop: 0 #f8f9fa, stop: 1 #e9ecef);
                color: #6c757d;
                font-size: 14px;
                font-family: 'Microsoft YaHei';
                padding: 20px;
            }
            QLabel:hover {
                border: 3px dashed #007bff;
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                          stop: 0 #e3f2fd, stop: 1 #bbdefb);
                color: #007bff;
            }
            QLabel[hasFile="true"] {
                border: 3px solid #28a745;
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                          stop: 0 #d4edda, stop: 1 #c3e6cb);
                color: #155724;
            }
            QLabel[hasFile="true"]:hover {
                border: 3px solid #20c997;
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                          stop: 0 #c3e6cb, stop: 1 #b1dfbb);
            }
        """)
        self.setAcceptDrops(True)
        self._paths = {'refund': None, 'order': None}
        self._update_display()

    def _update_display(self):
        lines = []
        if self._paths['refund']:
            lines.append(f"财务退款任务单：{os.path.basename(self._paths['refund'])}")
        if self._paths['order']:
            lines.append(f"线上销售退货汇总：{os.path.basename(self._paths['order'])}")
        if not lines:
            lines = ["请一次性拖入【财务退款任务单】和【线上销售退货汇总】\n（可只拖一个，缺省数据按 0 处理）"]
        self.setText("\n".join(lines))
        self.setProperty('hasFile', bool(lines))
        self.style().polish(self)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.toLocalFile().lower().endswith(('.xlsx', '.xls'))]
        for f in files:
            name = os.path.basename(f)
            if '财务退款任务单' in name:
                self._paths['refund'] = f
            elif '线上销售退货汇总' in name:
                self._paths['order'] = f
        self._update_display()
        self.files_dropped.emit(self._paths)

    def clear_files(self):
        self._paths = {'refund': None, 'order': None}
        self._update_display()
        self.cleared.emit()

    def paths(self):
        return self._paths


class TargetManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("月目标管理")
        self.setGeometry(200, 200, 500, 400)

        layout = QVBoxLayout(self)
        self.target_list = QListWidget()
        layout.addWidget(QLabel("已保存的目标方案:"))
        layout.addWidget(self.target_list)

        btn_layout = QHBoxLayout()
        self.load_btn = QPushButton("加载")
        self.load_btn.setStyleSheet("background-color: #3498db; color: white;")
        self.load_btn.clicked.connect(self.load_target)

        self.delete_btn = QPushButton("删除")
        self.delete_btn.setStyleSheet("background-color: #e74c3c; color: white;")
        self.delete_btn.clicked.connect(self.delete_target)

        self.rename_btn = QPushButton("重命名")
        self.rename_btn.setStyleSheet("background-color: #9b59b6; color: white;")
        self.rename_btn.clicked.connect(self.rename_target)

        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.accept)

        btn_layout.addWidget(self.load_btn)
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(self.rename_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)

        self.load_targets_list()

    def load_targets_list(self):
        self.target_list.clear()
        settings = QSettings("MyCompany", "PerformanceTool")
        target_names = settings.childGroups()
        for name in target_names:
            self.target_list.addItem(name)

    def get_selected_target(self):
        items = self.target_list.selectedItems()
        if not items:
            return None
        return items[0].text()

    def load_target(self):
        target_name = self.get_selected_target()
        if not target_name:
            QMessageBox.warning(self, "警告", "请选择一个目标方案")
            return
        self.parent().load_targets(target_name)
        self.accept()

    def delete_target(self):
        target_name = self.get_selected_target()
        if not target_name:
            QMessageBox.warning(self, "警告", "请选择一个目标方案")
            return
        reply = QMessageBox.question(self, "确认删除",
                                     f"确定要永久删除目标方案 '{target_name}' 吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            settings = QSettings("MyCompany", "PerformanceTool")
            settings.beginGroup(target_name)
            settings.remove("")
            settings.endGroup()
            self.load_targets_list()

    def rename_target(self):
        target_name = self.get_selected_target()
        if not target_name:
            QMessageBox.warning(self, "警告", "请选择一个目标方案")
            return
        new_name, ok = QInputDialog.getText(self, "重命名方案", "请输入新名称:", text=target_name)
        if ok and new_name and new_name != target_name:
            settings = QSettings("MyCompany", "PerformanceTool")
            if new_name in settings.childGroups():
                QMessageBox.warning(self, "错误", f"名称 '{new_name}' 已存在")
                return
            settings.beginGroup(target_name)
            values = settings.value("targets")
            settings.endGroup()
            settings.beginGroup(new_name)
            settings.setValue("targets", values)
            settings.endGroup()
            settings.beginGroup(target_name)
            settings.remove("")
            settings.endGroup()
            self.load_targets_list()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("业绩统计工具 - 智能列名版")
        self.setGeometry(100, 100, 1200, 900)
        
        # 设置应用样式
        self.setStyleSheet("""
            QMainWindow {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                          stop: 0 #f8f9fa, stop: 1 #e9ecef);
            }
            QTabWidget::pane {
                border: 1px solid #dee2e6;
                border-radius: 8px;
                background-color: white;
                margin: 5px;
            }
            QTabWidget::tab-bar {
                alignment: center;
            }
            QTabBar::tab {
                background: #f8f9fa;
                border: 1px solid #dee2e6;
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 8px 16px;
                margin-right: 2px;
                min-width: 100px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #007bff;
                color: white;
                border-color: #007bff;
            }
            QTabBar::tab:hover:!selected {
                background: #e9ecef;
            }
        """)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(25, 25, 25, 25)

        # 标题区域
        title_container = QWidget()
        title_container.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y1: 0,
                                          stop: 0 #007bff, stop: 1 #0056b3);
                border-radius: 12px;
                padding: 15px;
            }
        """)
        title_layout = QVBoxLayout(title_container)
        
        title_label = QLabel("业绩统计工具 - 智能数据分析系统")
        title_font = QFont("Microsoft YaHei", 18, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("color: white; margin: 5px;")
        
        subtitle_label = QLabel("退款按主播分配 | 智能列名识别 | 多维度业绩分析")
        subtitle_font = QFont("Microsoft YaHei", 10)
        subtitle_label.setFont(subtitle_font)
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setStyleSheet("color: rgba(255,255,255,0.9); margin: 2px;")
        
        title_layout.addWidget(title_label)
        title_layout.addWidget(subtitle_label)
        main_layout.addWidget(title_container)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #dee2e6;
                border-radius: 8px;
                background-color: white;
            }
        """)
        main_layout.addWidget(self.tabs)

        self.setup_file_selection_tab()
        self.setup_progress_tab()
        self.setup_results_tab()

        self.status_bar = self.statusBar()
        self.status_bar.setStyleSheet("""
            QStatusBar {
                background: #343a40;
                color: white;
                border-top: 1px solid #495057;
            }
        """)
        self.status_bar.showMessage("系统就绪 - 欢迎使用业绩统计工具")

        self.worker_threads = {1: None, 2: None}
        self.results = {1: None, 2: None}
        self.output_paths = {1: "", 2: ""}
        self.monthly_targets = {}
        self.report_date = QDate.currentDate().toString("yyyy-MM-dd")
        self.target_name = "默认方案"

        self.load_targets()
        
        # 设置窗口最小尺寸
        self.setMinimumSize(1000, 700)

    def setup_file_selection_tab(self):
        tab = QWidget()
        tab.setStyleSheet("""
            QWidget {
                background: white;
            }
        """)
        layout = QGridLayout(tab)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(0, 0)  # 第一组和第二组数据区域
        layout.setRowStretch(1, 0)  # 分析设置区域
        layout.setRowStretch(2, 0)  # 操作按钮区域

        # 第一组数据区域
        group1_container = QWidget()
        group1_container.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                          stop: 0 #f8f9fa, stop: 1 #ffffff);
                border: 1px solid #dee2e6;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        group1_layout = QVBoxLayout(group1_container)
        
        group1_header = QLabel("第一组数据")
        group1_header.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        group1_header.setStyleSheet("color: #495057; margin-bottom: 10px;")
        group1_layout.addWidget(group1_header)
        
        self.drop_area1 = DropArea()
        self.drop_area1.files_dropped.connect(lambda p: self.handle_files_dropped(p, 1))
        group1_layout.addWidget(self.drop_area1)
        
        clear_btn1 = QPushButton("清除第一组")
        clear_btn1.setStyleSheet("""
            QPushButton {
                background: #dc3545;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: #c82333; }
            QPushButton:pressed { background: #bd2130; }
        """)
        clear_btn1.clicked.connect(lambda: self.clear_group(1))
        group1_layout.addWidget(clear_btn1)

        output_group1 = QGroupBox("输出设置")
        output_group1.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #ced4da;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        out_layout1 = QVBoxLayout(output_group1)
        out_layout1.addWidget(QLabel("输出文件路径："))
        hbox1 = QHBoxLayout()
        self.output_path_edit1 = QLineEdit()
        self.output_path_edit1.setPlaceholderText("选择输出文件位置...")
        self.output_path_edit1.setReadOnly(True)
        self.output_path_edit1.setStyleSheet("""
            QLineEdit {
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 6px;
                background: #f8f9fa;
            }
        """)
        browse_btn1 = QPushButton("浏览...")
        browse_btn1.setStyleSheet("""
            QPushButton {
                background: #6c757d;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                min-width: 60px;
            }
            QPushButton:hover { background: #5a6268; }
        """)
        browse_btn1.clicked.connect(lambda: self.browse_output_file(1))
        hbox1.addWidget(self.output_path_edit1)
        hbox1.addWidget(browse_btn1)
        out_layout1.addLayout(hbox1)
        group1_layout.addWidget(output_group1)
        
        layout.addWidget(group1_container, 0, 0)

        # 第二组数据区域
        group2_container = QWidget()
        group2_container.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                          stop: 0 #f8f9fa, stop: 1 #ffffff);
                border: 1px solid #dee2e6;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        group2_layout = QVBoxLayout(group2_container)
        
        group2_header = QLabel("第二组数据")
        group2_header.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        group2_header.setStyleSheet("color: #495057; margin-bottom: 10px;")
        group2_layout.addWidget(group2_header)
        
        self.drop_area2 = DropArea()
        self.drop_area2.files_dropped.connect(lambda p: self.handle_files_dropped(p, 2))
        group2_layout.addWidget(self.drop_area2)
        
        clear_btn2 = QPushButton("清除第二组")
        clear_btn2.setStyleSheet("""
            QPushButton {
                background: #dc3545;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: #c82333; }
            QPushButton:pressed { background: #bd2130; }
        """)
        clear_btn2.clicked.connect(lambda: self.clear_group(2))
        group2_layout.addWidget(clear_btn2)

        output_group2 = QGroupBox("输出设置")
        output_group2.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #ced4da;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        out_layout2 = QVBoxLayout(output_group2)
        out_layout2.addWidget(QLabel("输出文件路径："))
        hbox2 = QHBoxLayout()
        self.output_path_edit2 = QLineEdit()
        self.output_path_edit2.setPlaceholderText("选择输出文件位置...")
        self.output_path_edit2.setReadOnly(True)
        self.output_path_edit2.setStyleSheet("""
            QLineEdit {
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 6px;
                background: #f8f9fa;
            }
        """)
        browse_btn2 = QPushButton("浏览...")
        browse_btn2.setStyleSheet("""
            QPushButton {
                background: #6c757d;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                min-width: 60px;
            }
            QPushButton:hover { background: #5a6268; }
        """)
        browse_btn2.clicked.connect(lambda: self.browse_output_file(2))
        hbox2.addWidget(self.output_path_edit2)
        hbox2.addWidget(browse_btn2)
        out_layout2.addLayout(hbox2)
        group2_layout.addWidget(output_group2)
        
        layout.addWidget(group2_container, 0, 1)

        # 日期和目标设置区域
        date_target_container = QWidget()
        date_target_container.setStyleSheet("""
            QWidget {
                background: white;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        date_target_layout = QVBoxLayout(date_target_container)
        
        date_target_header = QLabel("分析设置")
        date_target_header.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        date_target_header.setStyleSheet("color: #495057; margin-bottom: 15px;")
        date_target_layout.addWidget(date_target_header)
        
        # 目标方案管理
        scheme_layout = QHBoxLayout()
        scheme_layout.addWidget(QLabel("当前方案:"))
        self.target_name_label = QLabel("默认方案")
        self.target_name_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        self.target_name_label.setStyleSheet("color: #007bff; background: #e7f3ff; padding: 4px 8px; border-radius: 4px;")
        scheme_layout.addWidget(self.target_name_label)
        scheme_layout.addStretch()
        self.manage_targets_btn = QPushButton("管理方案")
        self.manage_targets_btn.setStyleSheet("""
            QPushButton {
                background: #6c757d;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: #5a6268; }
        """)
        self.manage_targets_btn.clicked.connect(self.manage_targets)
        scheme_layout.addWidget(self.manage_targets_btn)
        date_target_layout.addLayout(scheme_layout)

        # 日期设置
        date_layout = QHBoxLayout()
        date_layout.addWidget(QLabel("分析日期:"))
        self.date_edit = QDateEdit()
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setStyleSheet("""
            QDateEdit {
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 6px;
                background: white;
            }
        """)
        date_layout.addWidget(self.date_edit)
        date_layout.addStretch()
        date_target_layout.addLayout(date_layout)

        # 目标表格
        target_label = QLabel("店铺月预定目标")
        target_label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        target_label.setStyleSheet("color: #495057; margin: 10px 0 5px 0;")
        date_target_layout.addWidget(target_label)
        
        self.target_table = QTableWidget()
        self.target_table.setRowCount(10)
        self.target_table.setColumnCount(2)
        self.target_table.setHorizontalHeaderLabels(["店铺名称", "月目标(元)"])
        self.target_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #dee2e6;
                border-radius: 4px;
                background: white;
                gridline-color: #dee2e6;
            }
            QHeaderView::section {
                background: #f8f9fa;
                padding: 8px;
                border: 1px solid #dee2e6;
                font-weight: bold;
            }
            QTableWidget::item {
                padding: 6px;
            }
        """)
        shop_names = [
            "轮廓轻奢女装旗舰店", "轮廓平跃女装专卖店", "轮廓女装旗舰店",
            "轮廓聚如女装专卖店", "吉丘古儿官方旗舰店", "轮廓飞聚女装专卖店",
            "吉丘古儿全勋专卖店", "轮廓服饰专营店", "凡鸟时尚女装", "吉丘古儿旗舰店"
        ]
        for i, name in enumerate(shop_names):
            shop_item = QTableWidgetItem(name)
            shop_item.setFlags(shop_item.flags() & ~Qt.ItemIsEditable)
            shop_item.setBackground(QColor(248, 249, 250))
            self.target_table.setItem(i, 0, shop_item)
            target_item = QTableWidgetItem("0")
            self.target_table.setItem(i, 1, target_item)
        self.target_table.resizeColumnsToContents()
        date_target_layout.addWidget(self.target_table)

        # 目标汇总和操作按钮
        summary_container = QWidget()
        summary_container.setStyleSheet("""
            QWidget {
                background: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 6px;
                padding: 15px;
            }
        """)
        summary_layout = QVBoxLayout(summary_container)
        
        summary_info = QHBoxLayout()
        summary_info.addWidget(QLabel("所有店铺目标合计:"))
        self.all_summary = QLabel("0.00")
        self.all_summary.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        self.all_summary.setStyleSheet("color: #28a745;")
        summary_info.addWidget(self.all_summary)
        summary_info.addStretch()
        summary_layout.addLayout(summary_info)

        button_layout = QHBoxLayout()
        update_btn = QPushButton("更新汇总")
        update_btn.setStyleSheet("""
            QPushButton {
                background: #17a2b8;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: #138496; }
        """)
        update_btn.clicked.connect(self.update_target_summary)
        button_layout.addWidget(update_btn)
        
        save_target_btn = QPushButton("保存方案")
        save_target_btn.setStyleSheet("""
            QPushButton {
                background: #28a745;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: #218838; }
        """)
        save_target_btn.clicked.connect(self.save_targets)
        button_layout.addWidget(save_target_btn)
        
        clear_target_btn = QPushButton("清空目标")
        clear_target_btn.setStyleSheet("""
            QPushButton {
                background: #dc3545;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: #c82333; }
        """)
        clear_target_btn.clicked.connect(self.clear_targets)
        button_layout.addWidget(clear_target_btn)
        
        summary_layout.addLayout(button_layout)
        date_target_layout.addWidget(summary_container)
        
        layout.addWidget(date_target_container, 1, 0, 1, 2)

        # 操作按钮区域
        button_container = QWidget()
        button_container.setStyleSheet("""
            QWidget {
                background: white;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        button_layout_main = QVBoxLayout(button_container)
        
        action_buttons = QHBoxLayout()
        
        start_btn = QPushButton("开始分析")
        start_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                          stop: 0 #28a745, stop: 1 #20c997);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 12px 24px;
                font-size: 14px;
                font-weight: bold;
                min-width: 120px;
            }
            QPushButton:hover { 
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                          stop: 0 #218838, stop: 1 #1e9e8a);
            }
            QPushButton:pressed { background: #1e7e34; }
        """)
        start_btn.clicked.connect(self.start_analysis)
        action_buttons.addWidget(start_btn)
        
        self.merge_btn = QPushButton("合并非直播业绩")
        self.merge_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                          stop: 0 #6f42c1, stop: 1 #e83e8c);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 12px 24px;
                font-size: 14px;
                font-weight: bold;
                min-width: 120px;
            }
            QPushButton:hover { 
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                          stop: 0 #5a3598, stop: 1 #d91a72);
            }
            QPushButton:pressed { background: #4a2980; }
            QPushButton:disabled { 
                background: #6c757d; 
                color: #adb5bd;
            }
        """)
        self.merge_btn.setEnabled(False)
        self.merge_btn.clicked.connect(self.merge_non_live_performance)
        action_buttons.addWidget(self.merge_btn)
        
        action_buttons.addStretch()
        button_layout_main.addLayout(action_buttons)
        
        layout.addWidget(button_container, 2, 0, 1, 2)

        self.tabs.addTab(tab, "数据导入")

    def setup_progress_tab(self):
        tab = QWidget()
        tab.setStyleSheet("""
            QWidget {
                background: white;
            }
        """)
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        layout.setContentsMargins(25, 25, 25, 25)

        # 进度控制区域
        control_container = QWidget()
        control_container.setStyleSheet("""
            QWidget {
                background: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        control_layout = QVBoxLayout(control_container)
        
        control_header = QLabel("进度控制")
        control_header.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        control_header.setStyleSheet("color: #495057; margin-bottom: 15px;")
        control_layout.addWidget(control_header)
        
        group_selector_layout = QHBoxLayout()
        group_selector_layout.addWidget(QLabel("当前处理组:"))
        self.group_selector = QComboBox()
        self.group_selector.addItems(["第一组", "第二组"])
        self.group_selector.setStyleSheet("""
            QComboBox {
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 6px;
                background: white;
                min-width: 100px;
            }
        """)
        group_selector_layout.addWidget(self.group_selector)
        group_selector_layout.addStretch()
        control_layout.addLayout(group_selector_layout)

        # 进度条
        progress_label = QLabel("处理进度")
        progress_label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        progress_label.setStyleSheet("color: #495057; margin: 15px 0 5px 0;")
        control_layout.addWidget(progress_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ced4da;
                border-radius: 4px;
                background: white;
                text-align: center;
                height: 20px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y1: 0,
                                          stop: 0 #007bff, stop: 1 #0056b3);
                border-radius: 3px;
            }
        """)
        control_layout.addWidget(self.progress_bar)
        
        layout.addWidget(control_container)

        # 日志区域
        log_container = QWidget()
        log_container.setStyleSheet("""
            QWidget {
                background: white;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        log_layout = QVBoxLayout(log_container)
        
        log_header = QLabel("处理日志")
        log_header.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        log_header.setStyleSheet("color: #495057; margin-bottom: 15px;")
        log_layout.addWidget(log_header)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                border: 1px solid #ced4da;
                border-radius: 4px;
                background: #f8f9fa;
                font-family: Consolas, 'Microsoft YaHei';
                font-size: 10px;
            }
        """)
        log_layout.addWidget(self.log_text)
        
        layout.addWidget(log_container)

        # 操作按钮区域
        button_container = QWidget()
        button_container.setStyleSheet("""
            QWidget {
                background: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        button_layout = QHBoxLayout(button_container)
        
        self.cancel_btn = QPushButton("取消处理")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: #dc3545;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                min-width: 100px;
            }
            QPushButton:hover { background: #c82333; }
            QPushButton:pressed { background: #bd2130; }
            QPushButton:disabled { 
                background: #6c757d; 
                color: #adb5bd;
            }
        """)
        self.cancel_btn.clicked.connect(self.cancel_processing)
        button_layout.addWidget(self.cancel_btn)
        
        button_layout.addStretch()
        
        self.open_result_btn1 = QPushButton("打开第一组结果")
        self.open_result_btn1.setEnabled(False)
        self.open_result_btn1.setStyleSheet("""
            QPushButton {
                background: #17a2b8;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                min-width: 120px;
            }
            QPushButton:hover { background: #138496; }
            QPushButton:pressed { background: #117a8b; }
            QPushButton:disabled { 
                background: #6c757d; 
                color: #adb5bd;
            }
        """)
        self.open_result_btn1.clicked.connect(lambda: self.open_result_file(1))
        button_layout.addWidget(self.open_result_btn1)
        
        self.open_result_btn2 = QPushButton("打开第二组结果")
        self.open_result_btn2.setEnabled(False)
        self.open_result_btn2.setStyleSheet("""
            QPushButton {
                background: #6f42c1;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                min-width: 120px;
            }
            QPushButton:hover { background: #5a3598; }
            QPushButton:pressed { background: #4a2980; }
            QPushButton:disabled { 
                background: #6c757d; 
                color: #adb5bd;
            }
        """)
        self.open_result_btn2.clicked.connect(lambda: self.open_result_file(2))
        button_layout.addWidget(self.open_result_btn2)
        
        layout.addWidget(button_container)

        self.tabs.addTab(tab, "处理进度")

    def setup_results_tab(self):
        tab = QWidget()
        tab.setStyleSheet("""
            QWidget {
                background: white;
            }
        """)
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        layout.setContentsMargins(25, 25, 25, 25)

        # 结果控制区域
        control_container = QWidget()
        control_container.setStyleSheet("""
            QWidget {
                background: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        control_layout = QVBoxLayout(control_container)
        
        control_header = QLabel("结果预览控制")
        control_header.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        control_header.setStyleSheet("color: #495057; margin-bottom: 15px;")
        control_layout.addWidget(control_header)
        
        selector_layout = QHBoxLayout()
        selector_layout.addWidget(QLabel("选择数据组:"))
        self.result_group_selector = QComboBox()
        self.result_group_selector.addItems(["第一组", "第二组"])
        self.result_group_selector.setStyleSheet("""
            QComboBox {
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 6px;
                background: white;
                min-width: 100px;
            }
        """)
        self.result_group_selector.currentIndexChanged.connect(self.update_result_preview)
        selector_layout.addWidget(self.result_group_selector)
        
        selector_layout.addSpacing(20)
        selector_layout.addWidget(QLabel("选择结果表:"))
        self.result_selector = QComboBox()
        self.result_selector.addItems(["商店业绩汇总", "销售类型分析(按商店)", "主播业绩明细", "非直播业绩统计", "退款分配明细"])
        self.result_selector.setStyleSheet("""
            QComboBox {
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 6px;
                background: white;
                min-width: 180px;
            }
        """)
        self.result_selector.currentIndexChanged.connect(self.update_result_preview)
        selector_layout.addWidget(self.result_selector)
        
        selector_layout.addStretch()
        
        # 导出按钮
        export_btn = QPushButton("导出当前结果")
        export_btn.setStyleSheet("""
            QPushButton {
                background: #28a745;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background: #218838; }
            QPushButton:pressed { background: #1e7e34; }
        """)
        export_btn.clicked.connect(self.export_current_result)
        selector_layout.addWidget(export_btn)
        
        control_layout.addLayout(selector_layout)
        layout.addWidget(control_container)

        # 结果表格区域
        table_container = QWidget()
        table_container.setStyleSheet("""
            QWidget {
                background: white;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        table_layout = QVBoxLayout(table_container)
        
        table_header = QLabel("数据预览")
        table_header.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        table_header.setStyleSheet("color: #495057; margin-bottom: 15px;")
        table_layout.addWidget(table_header)
        
        self.result_table = QTableWidget()
        self.result_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #dee2e6;
                border-radius: 4px;
                background: white;
                gridline-color: #dee2e6;
                alternate-background-color: #f8f9fa;
            }
            QHeaderView::section {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                          stop: 0 #f8f9fa, stop: 1 #e9ecef);
                padding: 10px;
                border: 1px solid #dee2e6;
                font-weight: bold;
                color: #495057;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #f1f3f4;
            }
            QTableWidget::item:selected {
                background: #007bff;
                color: white;
            }
        """)
        table_layout.addWidget(self.result_table)
        
        # 统计信息区域
        stats_container = QWidget()
        stats_container.setStyleSheet("""
            QWidget {
                background: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 6px;
                padding: 15px;
            }
        """)
        stats_layout = QHBoxLayout(stats_container)
        
        self.stats_label = QLabel("总计: 0 行数据")
        self.stats_label.setFont(QFont("Microsoft YaHei", 10))
        self.stats_label.setStyleSheet("color: #6c757d;")
        stats_layout.addWidget(self.stats_label)
        
        stats_layout.addStretch()
        
        refresh_btn = QPushButton("刷新预览")
        refresh_btn.setStyleSheet("""
            QPushButton {
                background: #17a2b8;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: #138496; }
        """)
        refresh_btn.clicked.connect(self.update_result_preview)
        stats_layout.addWidget(refresh_btn)
        
        table_layout.addWidget(stats_container)
        layout.addWidget(table_container)

        self.tabs.addTab(tab, "结果预览")

    def clear_group(self, group_id):
        if group_id == 1:
            self.drop_area1.clear_files()
            self.output_path_edit1.clear()
            self.output_paths[1] = ""
        else:
            self.drop_area2.clear_files()
            self.output_path_edit2.clear()
            self.output_paths[2] = ""
        self.log_message(f"第{group_id}组数据已清除")

    def handle_files_dropped(self, paths, group_id):
        refund_path = paths.get('refund')
        order_path = paths.get('order')
        if group_id == 1:
            if not self.output_path_edit1.text():
                first = refund_path or order_path
                if first:
                    self.output_path_edit1.setText(os.path.join(os.path.dirname(first), "第1组综合业绩统计.xlsx"))
        else:
            if not self.output_path_edit2.text():
                first = refund_path or order_path
                if first:
                    self.output_path_edit2.setText(os.path.join(os.path.dirname(first), "第2组综合业绩统计.xlsx"))

    def browse_output_file(self, group_id):
        current = self.output_path_edit1.text() if group_id == 1 else self.output_path_edit2.text()
        file_path, _ = QFileDialog.getSaveFileName(self, f"保存第{group_id}组结果文件", current, "Excel文件 (*.xlsx)")
        if file_path:
            if not file_path.endswith('.xlsx'):
                file_path += '.xlsx'
            if group_id == 1:
                self.output_path_edit1.setText(file_path)
                self.output_paths[1] = file_path
            else:
                self.output_path_edit2.setText(file_path)
                self.output_paths[2] = file_path

    def update_target_summary(self):
        total = 0.0
        for row in range(self.target_table.rowCount()):
            try:
                total += float(self.target_table.item(row, 1).text())
            except:
                pass
        self.all_summary.setText(f"{total:,.2f}")

    def save_targets(self):
        name, ok = QInputDialog.getText(self, "保存目标方案", "请输入方案名称:", text=self.target_name)
        if not ok or not name:
            return
        targets = {}
        for row in range(self.target_table.rowCount()):
            shop = self.target_table.item(row, 0).text()
            try:
                targets[shop] = float(self.target_table.item(row, 1).text())
            except:
                targets[shop] = 0.0
        settings = QSettings("MyCompany", "PerformanceTool")
        settings.beginGroup(name)
        settings.setValue("targets", targets)
        settings.endGroup()
        self.target_name = name
        self.target_name_label.setText(name)
        self.log_message(f"目标方案 '{name}' 已保存")

    def load_targets(self, target_name=None):
        name = target_name or "默认方案"
        settings = QSettings("MyCompany", "PerformanceTool")
        settings.beginGroup(name)
        targets = settings.value("targets", {})
        settings.endGroup()
        if not targets:
            targets = {self.target_table.item(i, 0).text(): 0.0 for i in range(self.target_table.rowCount())}
            settings.beginGroup(name)
            settings.setValue("targets", targets)
            settings.endGroup()
        for row in range(self.target_table.rowCount()):
            shop = self.target_table.item(row, 0).text()
            val = targets.get(shop, 0.0)
            self.target_table.item(row, 1).setText(f"{val}")
        self.target_name = name
        self.target_name_label.setText(name)
        self.update_target_summary()
        self.log_message(f"已加载目标方案: {name}")

    def clear_targets(self):
        for row in range(self.target_table.rowCount()):
            self.target_table.item(row, 1).setText("0")
        self.update_target_summary()

    def manage_targets(self):
        dlg = TargetManagerDialog(self)
        dlg.exec_()

    def start_analysis(self):
        self.report_date = self.date_edit.date().toString("yyyy-MM-dd")
        self.update_target_summary()
        self.monthly_targets = {}
        for row in range(self.target_table.rowCount()):
            shop = self.target_table.item(row, 0).text()
            try:
                self.monthly_targets[shop] = float(self.target_table.item(row, 1).text())
            except:
                self.monthly_targets[shop] = 0.0

        self.output_paths[1] = self.output_path_edit1.text()
        self.output_paths[2] = self.output_path_edit2.text()

        paths1 = self.drop_area1.paths()
        paths2 = self.drop_area2.paths()
        has1 = paths1['refund'] or paths1['order']
        has2 = paths2['refund'] or paths2['order']

        if not has1 and not has2:
            QMessageBox.warning(self, "错误", "请至少输入一组数据")
            return
        if has1 and not self.output_paths[1]:
            QMessageBox.warning(self, "错误", "请指定第一组输出文件路径")
            return
        if has2 and not self.output_paths[2]:
            QMessageBox.warning(self, "错误", "请指定第二组输出文件路径")
            return

        self.log_text.clear()
        self.progress_bar.setValue(0)
        self.tabs.setCurrentIndex(1)
        self.cancel_btn.setEnabled(True)
        self.open_result_btn1.setEnabled(False)
        self.open_result_btn2.setEnabled(False)
        self.merge_btn.setEnabled(False)

        if has1:
            self.log_message("开始处理第一组数据...")
            self.worker_threads[1] = WorkerThread(
                paths1.get('refund'), paths1.get('order'), self.output_paths[1], 1, self.monthly_targets
            )
            self.worker_threads[1].progress.connect(self.progress_bar.setValue)
            self.worker_threads[1].message.connect(self.log_message)
            self.worker_threads[1].result.connect(lambda r: self.handle_result(r, 1))
            self.worker_threads[1].error.connect(self.analysis_error)
            self.worker_threads[1].finished.connect(self.check_all_finished)
            self.worker_threads[1].start()

        if has2:
            if has1:
                self.worker_threads[1].finished.connect(self.start_second_group)
            else:
                self.start_second_group()

    def start_second_group(self):
        paths2 = self.drop_area2.paths()
        self.log_message("开始处理第二组数据...")
        self.worker_threads[2] = WorkerThread(
            paths2.get('refund'), paths2.get('order'), self.output_paths[2], 2, self.monthly_targets
        )
        self.worker_threads[2].progress.connect(self.progress_bar.setValue)
        self.worker_threads[2].message.connect(self.log_message)
        self.worker_threads[2].result.connect(lambda r: self.handle_result(r, 2))
        self.worker_threads[2].error.connect(self.analysis_error)
        self.worker_threads[2].finished.connect(self.check_all_finished)
        self.worker_threads[2].start()

    def check_all_finished(self):
        if all(self.worker_threads[i] is None or not self.worker_threads[i].isRunning() for i in [1, 2]):
            self.cancel_btn.setEnabled(False)
            self.merge_btn.setEnabled(bool(self.results[1] and self.results[2]))
            self.log_message("所有组处理完成！")

    def log_message(self, msg):
        self.log_text.append(msg)
        self.status_bar.showMessage(msg)

    def handle_result(self, result, group_id):
        self.results[group_id] = result
        self.log_message(f"第{group_id}组处理完成！")
        if group_id == 1:
            self.open_result_btn1.setEnabled(True)
        else:
            self.open_result_btn2.setEnabled(True)
        self.update_result_preview()

    def analysis_error(self, msg):
        self.log_text.append(msg)
        self.progress_bar.setValue(0)
        self.cancel_btn.setEnabled(False)
        QMessageBox.critical(self, "处理错误", "处理过程中发生错误，请查看日志。")

    def cancel_processing(self):
        for t in self.worker_threads.values():
            if t and t.isRunning():
                t.terminate()
        self.log_message("处理已取消")

    def open_result_file(self, group_id):
        path = self.output_paths[group_id]
        if os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.warning(self, "错误", f"结果文件不存在: {path}")

    def update_result_preview(self):
        group = self.result_group_selector.currentIndex() + 1
        if not self.results.get(group):
            self.result_table.clear()
            self.stats_label.setText("总计: 0 行数据")
            return
        sheet = self.result_selector.currentText()
        df = self.results[group].get(sheet, pd.DataFrame())
        if df.empty:
            self.result_table.clear()
            self.stats_label.setText("总计: 0 行数据")
            return
        self.result_table.setRowCount(len(df))
        self.result_table.setColumnCount(len(df.columns))
        self.result_table.setHorizontalHeaderLabels(df.columns)
        for i in range(len(df)):
            for j, col in enumerate(df.columns):
                val = df.iloc[i, j]
                if isinstance(val, float):
                    disp = f"{val:.4f}" if abs(val) < 0.01 or abs(val) > 1000 else f"{val:.2f}"
                else:
                    disp = str(val)
                item = QTableWidgetItem(disp)
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                # 设置交替行颜色
                if i % 2 == 0:
                    item.setBackground(QColor(248, 249, 250))
                self.result_table.setItem(i, j, item)
        self.result_table.resizeColumnsToContents()
        self.stats_label.setText(f"总计: {len(df)} 行数据 | {len(df.columns)} 列")

    def export_current_result(self):
        group = self.result_group_selector.currentIndex() + 1
        if not self.results.get(group):
            QMessageBox.warning(self, "导出错误", "当前没有可导出的数据")
            return
        
        sheet = self.result_selector.currentText()
        df = self.results[group].get(sheet, pd.DataFrame())
        if df.empty:
            QMessageBox.warning(self, "导出错误", "当前选择的数据表为空")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            f"导出 {sheet} 数据", 
            f"{sheet}_{group}组_{self.report_date}.csv", 
            "CSV文件 (*.csv);;Excel文件 (*.xlsx)"
        )
        
        if file_path:
            try:
                if file_path.endswith('.csv'):
                    df.to_csv(file_path, index=False, encoding='utf-8-sig')
                else:
                    if not file_path.endswith('.xlsx'):
                        file_path += '.xlsx'
                    df.to_excel(file_path, index=False)
                QMessageBox.information(self, "导出成功", f"数据已成功导出到:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"导出过程中发生错误:\n{str(e)}")

    def merge_non_live_performance(self):
        if not self.results[1] or not self.results[2]:
            QMessageBox.warning(self, "错误", "请先完成两组数据的处理")
            return
        non_live1 = self.results[1].get('非直播业绩统计', pd.DataFrame())
        non_live2 = self.results[2].get('非直播业绩统计', pd.DataFrame())
        if non_live1.empty or non_live2.empty:
            QMessageBox.warning(self, "错误", "缺少非直播业绩数据")
            return
        merged = pd.concat([non_live1, non_live2], ignore_index=True)
        merged['退款率'] = merged.apply(
            lambda r: r['非直播退货金额'] / r['非直播发货金额'] if r['非直播发货金额'] != 0 else 0, axis=1
        )
        all_target = sum(self.monthly_targets.values())
        target_dict = {**self.monthly_targets, '所有店铺': all_target, '抖音小店': 0, '视频号小店': 0}
        merged['月预定目标'] = merged['商店'].map(target_dict).fillna(0)
        merged['目标完成率'] = merged.apply(
            lambda r: r['非直播销售额'] / r['月预定目标'] if r['数据类别'] == '月累计数据' and r['月预定目标'] > 0 else None, axis=1
        )
        merged['报表日期'] = self.report_date
        out_dir = os.path.dirname(self.output_paths[1]) or os.getcwd()
        out_path = os.path.join(out_dir, "非直播业绩对比.xlsx")
        try:
            with pd.ExcelWriter(out_path, engine='xlsxwriter') as writer:
                merged_filled = merged.fillna(0).replace([np.inf, -np.inf], 0)
                merged_filled.to_excel(writer, sheet_name="非直播业绩对比", index=False)
                workbook = writer.book
                ws = writer.sheets["非直播业绩对比"]
                header_fmt = workbook.add_format({'bold': True, 'bg_color': '#3498DB', 'font_color': 'white'})
                for col_num, val in enumerate(merged_filled.columns):
                    ws.write(0, col_num, val, header_fmt)
                for i, col in enumerate(merged_filled.columns):
                    max_len = max(merged_filled[col].astype(str).map(len).max(), len(col)) + 2
                    ws.set_column(i, i, min(max_len, 30))
                ws.freeze_panes(1, 0)
            self.log_message(f"非直播业绩对比已保存: {out_path}")
            QMessageBox.information(self, "成功", f"文件已保存:\n{out_path}")
            os.startfile(out_path)
        except Exception as e:
            self.log_message(f"保存失败: {e}")
            QMessageBox.critical(self, "错误", f"保存失败: {e}")


if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QMainWindow { background-color: #ecf0f1; }
        QGroupBox { font-weight: bold; border: 1px solid #bdc3c7; border-radius: 5px; margin-top: 10px; }
        QTabWidget::pane { border: 1px solid #bdc3c7; border-radius: 5px; }
        QTabBar::tab { background-color: #bdc3c7; padding: 8px 16px; margin: 2px; border-radius: 4px; }
        QTabBar::tab:selected { background-color: #3498db; color: white; }
        QTableWidget { background-color: white; }
    """)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
