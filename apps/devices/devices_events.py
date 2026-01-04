# apps/devices/devices_events.py
from flask import render_template, request, jsonify
from apps.tools.db import query_db, modify_db
from apps.tools.permissions import get_current_user_info
from apps.devices.route import bp_devices
import datetime

# =========================================================================
# 页面渲染：设备事件列表页
# =========================================================================
@bp_devices.route('/devices_events')
def devices_events_page():
    user = get_current_user_info()
    if not user: return "请先登录", 403

    current_level = user.get('current_level', 0)

    # 1. 权限标记初始化 (用于前端筛选框控制)
    permissions = {
        'lock_hospital': False,
        'lock_dept': False,
        'default_hospital': '',
        'default_dept': ''
    }

    # 权限判断逻辑
    if current_level < 90:
        # 院管/科管/员工：锁定本院
        permissions['lock_hospital'] = True
        permissions['default_hospital'] = user['id_hospital']
    
    if current_level < 50:
        # 科管/员工：锁定本科室
        permissions['lock_dept'] = True
        permissions['default_dept'] = user['id_department']

    # 2. 加载筛选数据
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

    # 科室列表 (如果已锁定医院，则预加载科室)
    target_hid = permissions['default_hospital']
    if target_hid:
         departments = query_db("SELECT id_department, department_name FROM department WHERE id_hospital = ?", (target_hid,))

    return render_template('devices/devices_events.html', 
                           permissions=permissions,
                           hospitals=hospitals,
                           departments=departments,
                           user=user,
                           current_level=current_level)

# =========================================================================
# 接口：获取某设备的事件列表
# =========================================================================
@bp_devices.route('/api/event_list')
def api_event_list():
    # 虽然是读操作，建议也加上基础的隔离检查，防止遍历 device_id
    user = get_current_user_info()
    if not user: return jsonify({"code": 1, "msg": "未登录"})
    
    current_level = user.get('current_level', 0)
    device_id = request.args.get('device_id')
    
    if not device_id: return jsonify({"code": 1, "msg": "缺少设备ID"})
    
    # 简单的权限预检 (查询设备归属)
    if current_level < 90:
        device = query_db("SELECT id_hospital, id_department, use_department_id FROM facility_object WHERE id = ?", (device_id,), one=True)
        if not device: return jsonify({"code": 1, "msg": "设备不存在"})
        
        # 院级隔离
        if str(device['id_hospital']) != str(user['id_hospital']):
             return jsonify({"code": 1, "msg": "无权查看其他医院设备"})
        
        # 科级隔离 (查看权限通常放宽到：管理的 OR 使用的)
        if current_level < 50:
            is_mine = (str(device['id_department']) == str(user['id_department']) or 
                       str(device['use_department_id']) == str(user['id_department']))
            if not is_mine:
                return jsonify({"code": 1, "msg": "无权查看非本科室设备"})

    events = query_db("SELECT * FROM device_events WHERE device_id = ? ORDER BY next_run_time DESC", (device_id,))
    return jsonify({"code": 0, "data": events})

# =========================================================================
# 接口：保存事件 (新增/编辑)
# =========================================================================
@bp_devices.route('/api/event_save', methods=['POST'])
def api_event_save():
    user = get_current_user_info()
    if not user: return jsonify({"code": 1, "msg": "未登录"})

    current_level = user.get('current_level', 0)
    data = request.form
    event_id = data.get('id') 
    device_id = data.get('device_id')

    # 1. 获取设备信息 (用于鉴权 + 数据快照)
    # 必须查出 id_hospital 和 id_department 用于比对
    device = query_db("SELECT id_hospital, hospital_name, id_department, department_name FROM facility_object WHERE id = ?", (device_id,), one=True)
    
    if not device: return jsonify({"code": 1, "msg": "设备不存在"})

    # === 权限验证 (Level) ===
    has_permission = False
    
    # Level >= 90 (SA/GA): 通过
    if current_level >= 90:
        has_permission = True
        
    # 50 <= Level < 90 (HA/HP): 必须是本院设备
    elif current_level >= 50:
        if str(user['id_hospital']) == str(device['id_hospital']):
            has_permission = True
            
    # Level < 50 (DA/DH...): 必须是【管理科室】的设备
    # 注意：规则制定通常属于管理职责，因此只校验 id_department，不校验 use_department_id
    else:
        if str(user['id_department']) == str(device['id_department']):
            has_permission = True

    if not has_permission:
        return jsonify({"code": 1, "msg": "权限不足：您不是该设备的管理科室或上级管理员"})

    # === 数据处理 ===
    event_type = data.get('event_type')
    content = data.get('content')
    cycle_val = data.get('cycle_val', 0)
    cycle_unit = data.get('cycle_unit')
    next_run_time = data.get('next_run_time')

    if not event_type or not next_run_time:
        return jsonify({"code": 1, "msg": "类型和时间必填"})

    if event_id:
        # 更新
        sql = """UPDATE device_events SET 
                 event_type=?,  content=?, cycle_val=?, cycle_unit=?, next_run_time=?
                 WHERE id=?"""
        modify_db(sql, (event_type,  content, cycle_val, cycle_unit, next_run_time, event_id))
    else:
        # 新增
        sql = """INSERT INTO device_events 
                 (device_id, event_type,  content, cycle_val, cycle_unit, next_run_time, creator_id,
                  id_hospital, hospital_name, id_department, department_name) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        modify_db(sql, (
            device_id, event_type,  content, cycle_val, cycle_unit, next_run_time, user['id'],
            device['id_hospital'], device['hospital_name'], device['id_department'], device['department_name']
        ))

    return jsonify({"code": 0, "msg": "保存成功"})

# =========================================================================
# 接口：删除事件
# =========================================================================
@bp_devices.route('/api/event_delete', methods=['POST'])
def api_event_delete():
    user = get_current_user_info()
    if not user: return jsonify({"code": 1, "msg": "未登录"})
    
    current_level = user.get('current_level', 0)
    evt_id = request.form.get('id')
    
    if not evt_id: return jsonify({"code": 1, "msg": "参数缺失"})

    # 1. 查出事件对应的设备ID
    event = query_db("SELECT device_id FROM device_events WHERE id = ?", (evt_id,), one=True)
    if not event: return jsonify({"code": 1, "msg": "事件不存在"})
    
    device_id = event['device_id']
    
    # 2. 查出设备归属 (用于鉴权)
    device = query_db("SELECT id_hospital, id_department FROM facility_object WHERE id = ?", (device_id,), one=True)
    if not device: return jsonify({"code": 1, "msg": "关联设备不存在"})

    # === 权限验证 (逻辑同 Save) ===
    has_permission = False
    
    if current_level >= 90:
        has_permission = True
    elif current_level >= 50:
        if str(user['id_hospital']) == str(device['id_hospital']):
            has_permission = True
    else:
        if str(user['id_department']) == str(device['id_department']):
            has_permission = True

    if not has_permission:
        return jsonify({"code": 1, "msg": "权限不足：无法删除该规则"})

    modify_db("DELETE FROM device_events WHERE id = ?", (evt_id,))
    return jsonify({"code": 0, "msg": "删除成功"})