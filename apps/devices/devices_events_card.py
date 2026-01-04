# devices_list.py
from flask import render_template, request, jsonify
from apps.tools.db import query_db, modify_db
from apps.tools.permissions import get_current_user_info
from apps.devices.route import bp_devices

@bp_devices.route('/devices_events_card')
def devices_events_list():
    user = get_current_user_info()
    if not user: return "请先登录", 403

    # 1. 获取当前用户等级
    current_level = user.get('current_level', 0)
    
    # 2. 准备医院数据
    hospitals = []
    if current_level >= 90:
        # SA(100), GA(90): 加载所有医院
        hospitals = query_db("SELECT id_hospital, hospital_name FROM hospital")
    else:
        # HA(50), HP(55), DA(25)...: 只能看到自己所在的医院
        hospitals = [{
            'id_hospital': user['id_hospital'], 
            'hospital_name': user['hospital_name']
        }]

    # 3. 准备科室数据 (仅针对进入页面时就需要加载科室的情况，如 HA/HP)
    departments = []
    # 如果是院级管理员(50<=L<90)，初始加载本院所有科室
    if 50 <= current_level < 90:
         departments = query_db("SELECT id_department, department_name FROM department WHERE id_hospital = ?", (user['id_hospital'],))

    return render_template('devices/devices_events_card.html', 
                           user=user,
                           hospitals=hospitals,
                           departments=departments,
                           current_level=current_level)

@bp_devices.route('/api/get_events')
def get_events():
    user = get_current_user_info()
    if not user: return jsonify({"code": 1, "msg": "登录已过期"})

    current_level = user.get('current_level', 0)

    # 获取前端传参
    hid = request.args.get('id_hospital')
    did = request.args.get('id_department')
    etype = request.args.get('event_type')
    keyword = request.args.get('keyword', '')

    # --- 权限强制过滤 ---
    # 1. 院级及以下 (<90)：强制锁定本院
    if current_level < 90:
        hid = user['id_hospital']
    
    # 2. 科级及以下 (<50)：强制锁定本科室
    if current_level < 50:
        did = user['id_department']

    # --- 构造 SQL ---
    sql = """
        SELECT 
            de.*, 
            fo.name AS device_name, 
            fo.model AS device_model,
            h.hospital_name,
            d.department_name
        FROM device_events de
        LEFT JOIN facility_object fo ON de.device_id = fo.id
        LEFT JOIN hospital h ON de.id_hospital = h.id_hospital
        LEFT JOIN department d ON de.id_department = d.id_department
        WHERE 1=1
    """
    params = []

    if hid:
        sql += " AND de.id_hospital = ?"
        params.append(hid)
    if did:
        sql += " AND de.id_department = ?"
        params.append(did)
    if etype:
        sql += " AND de.event_type = ?"
        params.append(etype)
    if keyword:
        # 搜索设备名或事件内容
        sql += " AND (de.content LIKE ? OR fo.name LIKE ?)"
        params.append(f"%{keyword}%")
        params.append(f"%{keyword}%")

    # 按下次执行时间先后排序
    sql += " ORDER BY de.next_run_time ASC"
    
    events = query_db(sql, params)
    return jsonify({"code": 0, "data": events})