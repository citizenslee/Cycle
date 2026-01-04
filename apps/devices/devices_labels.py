from flask import render_template, request, url_for
from apps.tools.db import query_db
from apps.tools.permissions import get_current_user_info
from apps.devices.route import bp_devices

@bp_devices.route('/labels', methods=['GET'])
def device_labels_list():
    """
    设备标签生成页面 (带分页与高级筛选)
    """
    user = get_current_user_info()
    if not user:
        return render_template('login.html') 

    # 获取当前用户等级
    current_level = user.get('current_level', 0)

    # =========================================================
    # 1. 参数获取 & 默认值设置
    # =========================================================
    page = request.args.get('page', 1, type=int)
    limit = 50  # 固定每页50条
    
    only_has_plan = request.args.get('only_has_plan', '1') 
    keyword = request.args.get('keyword', '').strip()

    # =========================================================
    # 2. 权限标记初始化 (适配新 Level 体系)
    # =========================================================
    permissions = {
        'lock_hospital': False,
        'lock_dept': False,
        'default_hospital': '',
        'default_dept': ''
    }

    # 逻辑 A: 院级及以下 (<90) -> 锁定医院
    if current_level < 90:
        permissions['lock_hospital'] = True
        permissions['default_hospital'] = user['id_hospital']

    # 逻辑 B: 科级及以下 (<50) -> 锁定科室
    if current_level < 50:
        permissions['lock_dept'] = True
        permissions['default_dept'] = user['id_department']

    # =========================================================
    # 3. 加载筛选下拉框数据
    # =========================================================
    hospitals = []
    departments = []
    
    # 医院列表
    if current_level >= 90:
        hospitals = query_db("SELECT id_hospital, hospital_name FROM hospital")
    else:
        hospitals = [{
            'id_hospital': user['id_hospital'], 
            'hospital_name': user['hospital_name']
        }]

    # 确定当前查询使用的 Hospital ID 和 Department ID
    # 优先级：权限强制锁定 > 前端传参 > 空
    
    # 1. 确定医院 ID
    if permissions['lock_hospital']:
        target_hospital_id = user['id_hospital']
    else:
        target_hospital_id = request.args.get('hospital_id', '')

    # 2. 确定科室 ID
    if permissions['lock_dept']:
        target_department_id = user['id_department']
    else:
        target_department_id = request.args.get('department_id', '')

    # 3. 联动加载科室列表 (只要确定了医院，就加载该院科室供筛选)
    if target_hospital_id:
        departments = query_db("SELECT id_department, department_name FROM department WHERE id_hospital = ?", (target_hospital_id,))
    
    # =========================================================
    # 4. 构建 SQL 语句
    # =========================================================
    
    where_clauses = ["f.status = 1"]
    params = []

    # --- 权限与筛选 (使用计算好的 target_id) ---
    if target_hospital_id:
        where_clauses.append("f.id_hospital = ?")
        params.append(target_hospital_id)

    if target_department_id:
        # 注意：这里通常筛选“管理科室”，如果需要包含“使用科室”，请改为 OR 逻辑
        # 例如: where_clauses.append("(f.id_department = ? OR f.use_department_id = ?)")
        where_clauses.append("f.id_department = ?")
        params.append(target_department_id)

    if keyword:
        where_clauses.append("(f.name LIKE ? OR f.model LIKE ?)")
        params.append(f'%{keyword}%')
        params.append(f'%{keyword}%')

    # --- 筛选：只显示有计划的设备 ---
    if only_has_plan == '1':
        where_clauses.append("EXISTS (SELECT 1 FROM device_events de WHERE de.device_id = f.id)")

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    # --- 查询总数 ---
    count_sql = f"SELECT COUNT(*) as total FROM facility_object f {where_sql}"
    count_res = query_db(count_sql, params, one=True)

    # 兼容处理
    total_count = 0
    if count_res:
        if isinstance(count_res, dict):
            total_count = count_res.get('total', 0)
        elif hasattr(count_res, 'keys'): 
            total_count = count_res['total']
        else:
            total_count = count_res[0]

    # --- 查询数据 ---
    data_sql = f"""
        SELECT 
            f.id, 
            f.name, 
            f.model, 
            f.hospital_name, 
            f.department_name,
            f.install_location,
            CASE 
                WHEN EXISTS (SELECT 1 FROM device_events de WHERE de.device_id = f.id LIMIT 1) 
                THEN 1 
                ELSE 0 
            END as has_plan
        FROM facility_object f
        {where_sql}
        ORDER BY f.id DESC
        LIMIT ? OFFSET ?
    """
    
    data_params = params + [limit, (page - 1) * limit]
    devices_raw = query_db(data_sql, data_params)

    # =========================================================
    # 5. 数据后处理
    # =========================================================
    devices = []
    # 建议将域名配置在 config 中，而不是硬编码
    base_url = request.host_url.rstrip('/') + '/devices/check_in/'
    
    for d in devices_raw:
        item = dict(d)
        if item['has_plan'] == 1:
            item['plan_status_text'] = "存在事件"
            item['plan_status_class'] = "text-success"
        else:
            item['plan_status_text'] = "暂无计划"
            item['plan_status_class'] = "text-secondary"
        
        item['qr_link'] = f"{base_url}{item['id']}"
        devices.append(item)

    return render_template(
        'devices/devices_labels.html',
        devices=devices,
        hospitals=hospitals,
        departments=departments,
        permissions=permissions,
        # 将计算后的 target_id 传回前端用于回显选中状态
        selected_hospital_id=target_hospital_id,
        selected_department_id=target_department_id,
        current_level=current_level, # 传递等级给前端以便扩展
        pagination={
            'curr': page,
            'limit': limit,
            'count': total_count,
            'only_has_plan': only_has_plan
        }
    )