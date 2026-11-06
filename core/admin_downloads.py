"""Generate downloads only when their button is clicked, never at page load."""
from copy import copy
import io
import pandas as pd


def excel_bytes(frame, sheet_name):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        frame.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()


def adjustment_template_bytes():
    output = io.BytesIO()
    template = pd.DataFrame({'订单号': ['16083112505226'], '金额': [-100.00]})
    instructions = pd.DataFrame({'填写说明': [
        '订单号填写平台业务订单号，不是 C 开头的财务单据号',
        '金额必须填写负数',
        '系统会从数据库自动匹配平台、店铺、主播、部门和阿米巴组织',
        '同一订单号可以填写多行，系统会先合计该订单的退差价金额',
        '只有各平台上传金额与上月自媒体综合 C 单完全平账时才会替换',
        '请删除示例行后再上传',
    ]})
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        template.to_excel(writer, sheet_name='退差价匹配', index=False)
        instructions.to_excel(writer, sheet_name='填写说明', index=False)
        writer.book['退差价匹配'].freeze_panes = 'A2'
        writer.book['填写说明'].column_dimensions['A'].width = 68
        for sheet in writer.book.worksheets:
            for cell in sheet[1]:
                font = copy(cell.font)
                font.bold = True
                cell.font = font
    return output.getvalue()
