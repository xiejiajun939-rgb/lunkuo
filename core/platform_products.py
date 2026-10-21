"""Douyin platform-product import. Parsing is offline; persistence requires an explicit call."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from openpyxl import load_workbook

TABLE = 'douyin_platform_product_daily'
FILENAME = re.compile(r'^商品列表_(.+)_(全部|商品卡)_(\d{4}-\d{2}-\d{2})~(\d{4}-\d{2}-\d{2})\.xlsx$')
STYLE = re.compile(r'(?<![A-Za-z0-9])([A-Za-z]\d{3}[A-Za-z]\d{3})(?![A-Za-z0-9])')
TEXT_COLUMNS = {'统计周期', '商品名称', '商品编码', '载体', '品类', '自卖/合作', '上架时间'}
REQUIRED = {'统计周期', '商品名称', '商品编码', '载体', '成交金额', '成交订单数', '商品曝光次数', '商品点击次数'}

def number(value):
    if value is None or str(value).strip() in {'', '-', '--', '—'}:
        return None
    text = str(value).strip().replace(',', '')
    percent = text.endswith('%')
    try:
        v = Decimal(text.rstrip('%'))
    except InvalidOperation as exc:
        raise ValueError(f'无法识别数值：{value}') from exc
    if not v.is_finite():
        raise ValueError('存在非有限数值')
    return float(v / 100 if percent else v)

def parse_platform_products(file_obj, filename):
    match = FILENAME.fullmatch(Path(filename).name)
    if not match:
        raise ValueError('文件名须为 商品列表_店铺_全部或商品卡_YYYY-MM-DD~YYYY-MM-DD.xlsx')
    shop, scope, start, end = match.groups()
    if start != end:
        raise ValueError('当前仅接收单日导出，不能将多日汇总分摊到每日')
    date.fromisoformat(start)
    workbook = load_workbook(file_obj, read_only=True, data_only=True)
    result, seen = [], set()
    try:
        for sheet in workbook:
            sheet.reset_dimensions()  # The supplied exports incorrectly declare A1:A1.
            it = sheet.iter_rows(values_only=True)
            header = [str(v).strip() if v is not None else '' for v in next(it, [])]
            if not REQUIRED.issubset(header):
                raise ValueError('缺少字段：' + '、'.join(sorted(REQUIRED - set(header))))
            if len(set(header)) != len(header):
                raise ValueError('存在重名字段，不能安全解析')
            for line, values in enumerate(it, 2):
                if not any(v is not None for v in values):
                    continue
                row = dict(zip(header, values))
                pid = row.get('商品编码')
                if isinstance(pid, (int, float)):
                    raise ValueError(f'第{line}行商品编码为数值，长ID可能已丢精度，请以文本导出')
                pid = str(pid or '').strip()
                if not pid.isdigit():
                    raise ValueError(f'第{line}行缺少有效文本商品编码')
                raw_date = row.get('统计周期')
                actual_date = raw_date.date().isoformat() if isinstance(raw_date, datetime) else str(raw_date).strip().replace('/', '-')
                if actual_date != start or str(row.get('载体')).strip() != scope:
                    raise ValueError(f'第{line}行日期或载体与文件名不一致')
                if pid in seen:
                    raise ValueError(f'重复商品编码 {pid}，停止导入以免重复累计')
                seen.add(pid)
                name = str(row.get('商品名称') or '').strip()
                # IDs stay authoritative. Ambiguous or missing style codes remain unmapped.
                codes = set(re.findall(r'[A-Za-z]\d{3}[A-Za-z]\d{3}', name))
                metrics = {k: number(v) for k, v in row.items() if k not in TEXT_COLUMNS and k}
                result.append(dict(report_date=start, shop_name=shop.strip(), scope=scope,
                    product_id=pid, product_name=name, style_code=next(iter(codes)).upper() if len(codes)==1 else None,
                    source_file=Path(filename).name, metrics=metrics))
    finally:
        workbook.close()
    if not result:
        raise ValueError('文件没有商品记录，不执行空覆盖')
    return result

def save_platform_products(client, records):
    """Idempotent single-file replace via one transaction; setup SQL is deployed separately."""
    if not records:
        raise ValueError('没有已校验记录')
    return client.rpc('replace_douyin_platform_file', {'p_rows':records}).execute().data

def render_platform_import():
    import os
    import io
    import streamlit as st
    from supabase import create_client
    st.markdown('### 抖音平台商品数据（全部 / 商品卡）')
    st.caption('单日导出，按日期、平台店铺、范围独立替换；全部包含商品卡，不相加。先预览校验，再确认导入。')
    files = st.file_uploader('平台商品列表 Excel', type=['xlsx'], accept_multiple_files=True, key='platform_products_files')
    if not files:
        return
    previews, errors, grains = [], [], set()
    for file in files:
        try:
            records = parse_platform_products(io.BytesIO(file.getvalue()), file.name)
            grain = tuple(records[0][k] for k in ['report_date', 'shop_name', 'scope'])
            if grain in grains:
                raise ValueError('本批次存在相同日期、店铺、范围的重复文件')
            grains.add(grain)
            previews.append((file.name, records))
            st.write(f'{file.name}：{len(records)} 条，待关联货号 {sum(r["style_code"] is None for r in records)} 条')
        except Exception as exc:
            errors.append(f'{file.name}：{exc}')
    if errors:
        st.error('\n'.join(errors))
        return
    confirmed = st.checkbox('确认替换以上文件对应日期、店铺及范围的数据', key='platform_products_confirm')
    if st.button('确认导入平台商品数据', key='platform_products_save', disabled=not confirmed):
        url = os.environ.get('SUPABASE_URL') or st.secrets.get('SUPABASE_URL')
        secret = os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or st.secrets.get('SUPABASE_SERVICE_ROLE_KEY')
        if not url or not secret:
            st.error('请先部署平台商品数据表，并配置服务端 SUPABASE_URL 和 SUPABASE_SERVICE_ROLE_KEY。')
            return
        client = create_client(url, secret)
        for name, records in previews:
            try:
                count = save_platform_products(client, records)
                st.success(f'{name}：成功保存 {count} 条')
            except Exception:
                st.error(f'{name} 导入失败；此前成功文件仍保留。该文件通过事务保护，不会留下半份数据，可修复后重试。')
                break
