# apps/devices/devices_logs.py
from flask import render_template, request, jsonify
from apps.tools.db import query_db
from apps.devices.route import bp_devices

# 1. 页面视图 (不变)
@bp_devices.route('/log_list')
def log_list_page():
    device_id = request.args.get('device_id')
    return render_template('devices/devices_logs.html', device_id=device_id)

# 2. 数据接口 (核心修改：支持筛选)
@bp_devices.route('/api/get_logs')
def get_device_logs():
    device_id = request.args.get('device_id')
    if not device_id:
        return jsonify({'code': 1, 'msg': '缺少必要参数', 'data': []})

    # 获取筛选参数
    date_range = request.args.get('date_range') # 格式 "2025-01-01 - 2025-02-01"
    log_type = request.args.get('log_type')
    show_child = request.args.get('show_child', '1') # 默认 '1' 显示，'0' 隐藏

    conditions = []
    args = []

    # 1. 构建设备范围查询 (自身 vs 包含子集)
    if show_child == '1':
        # 查自己 + 子孙
        conditions.append("""
            (l.device_id = ? 
             OR l.device_id IN (
                SELECT id FROM facility_object 
                WHERE ancestor_path LIKE ? OR ancestor_path LIKE ?
             ))
        """)
        pattern_end = f"%,{device_id}"
        pattern_mid = f"%,{device_id},%"
        args.extend([device_id, pattern_mid, pattern_end])
    else:
        # 只查自己
        conditions.append("l.device_id = ?")
        args.append(device_id)

    # 2. 类型筛选
    if log_type:
        conditions.append("l.type = ?")
        args.append(log_type)

    # 3. 时间筛选
    if date_range and ' - ' in date_range:
        start_str, end_str = date_range.split(' - ')
        conditions.append("l.occur_time BETWEEN ? AND ?")
        # 补全时分秒，确保覆盖全天
        args.extend([start_str + " 00:00:00", end_str + " 23:59:59"])

    # 组合 SQL
    where_clause = " AND ".join(conditions)
    
    sql = f"""
        SELECT 
            l.id,
            l.device_id,
            f.name as device_name,
            l.occur_time,
            l.related_work_order,
            l.work_content,
            l.staff,
            l.type  -- 记得查询 type 字段
        FROM devices_log l
        LEFT JOIN facility_object f ON l.device_id = f.id
        WHERE {where_clause}
        ORDER BY l.occur_time DESC
    """

    try:
        rows = query_db(sql, args=args)
        return jsonify({'code': 0, 'msg': 'success', 'data': rows})
    except Exception as e:
        print(f"Error getting logs: {e}")
        return jsonify({'code': 500, 'msg': '系统错误', 'data': []})