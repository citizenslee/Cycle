import json
from flask import render_template, request, jsonify
from apps.tools.db import query_db, modify_db
from apps.tools.permissions import get_current_user_info
from apps.devices.route import bp_devices
from apps.devices.devices_list import get_path_for_parent, update_children_paths 

# =========================================================================
# 渲染：设备表单 (新增/编辑)
# =========================================================================
@bp_devices.route('/device_form')
def device_form():
    user = get_current_user_info()
    if not user: return "请先登录", 403

    current_level = user.get('current_level', 0)
    user_work_flag = int(user.get('work_flag', 0)) # 0:临床, 1:职能

    obj_id = request.args.get('id')
    parent_id = int(request.args.get('parent_id', 0))
    
    # -----------------------------------------------------------
    # 1. 挂载权限预校验 (针对临床科室 Level < 50 & Flag=0)
    # -----------------------------------------------------------
    # 逻辑：临床科室只能在"使用科室"为本科室的设备下挂载子设备
    parent_obj = None
    if parent_id > 0:
        parent_obj = query_db("SELECT * FROM facility_object WHERE id = ?", (parent_id,), one=True)
        if parent_obj:
            is_clinical_user = (current_level < 50) and (user_work_flag == 0)
            if is_clinical_user:
                # 校验父级的使用科室是否等于当前用户科室
                if str(parent_obj.get('use_department_id')) != str(user['id_department']):
                    return f"权限不足：父设备[{parent_obj['name']}]的使用权非本科室，无法挂载子设备。", 403

    # -----------------------------------------------------------
    # 2. 初始化数据对象
    # -----------------------------------------------------------
    obj_data = {}
    if obj_id:
        # === 编辑模式 ===
        obj_data = query_db("SELECT * FROM facility_object WHERE id = ?", (obj_id,), one=True)
        if not obj_data: return "设备不存在", 404
        obj_data = dict(obj_data)
    else:
        # === 新增模式 ===
        def_h = request.args.get('default_hospital', '') 
        obj_data = {
            'id': '', 
            'parent_id': parent_id,
            'id_hospital': def_h, 
            'status': 1, 
            'extra_json': '{}',
            'id_department': '', 
            'use_department_id': '',
            'category': ''
        }
        
        # 继承父级属性 (医院、管理科室、使用科室)
        if parent_obj:
            obj_data['id_hospital'] = parent_obj['id_hospital']
            obj_data['id_department'] = parent_obj['id_department']
            obj_data['use_department_id'] = parent_obj['use_department_id']

    # JSON 解析容错
    try:
        obj_data['extra_data_dict'] = json.loads(obj_data.get('extra_json', '{}'))
    except:
        obj_data['extra_data_dict'] = {}

    # -----------------------------------------------------------
    # 3. 权限规则 (Rules)
    # -----------------------------------------------------------
    rules = {
        'lock_hospital': False, 
        'lock_mgmt': False, 
        'lock_use': False, 
        'hospital_list': [], 
        'dept_list': []
    }
    
    # === A. 医院权限 (Level < 90 锁定) ===
    if current_level >= 90:
        # 超管/集团：可选所有
        rules['hospital_list'] = query_db("SELECT id_hospital, hospital_name FROM hospital")
    else:
        # 院管/科管/员工：锁定本院
        rules['lock_hospital'] = True
        # 如果是新增且没有继承父级，强制设为本院
        if not obj_data.get('id_hospital'):
            obj_data['id_hospital'] = user['id_hospital']
        
        rules['hospital_list'] = [{'id_hospital': user['id_hospital'], 'hospital_name': user['hospital_name']}]

    # === B. 科室权限 (Level < 50 锁定) ===
    if current_level < 50:
        if user_work_flag == 1: 
            # 职能科室 (维修方) -> 锁定管理科室
            rules['lock_mgmt'] = True
            # 如果是新增且未继承，强制设为本科室
            if not obj_data.get('id_department'):
                obj_data['id_department'] = user['id_department']
        else: 
            # 临床科室 (使用方) -> 锁定使用科室
            rules['lock_use'] = True
            # 如果是新增且未继承，强制设为本科室
            if not obj_data.get('use_department_id'):
                obj_data['use_department_id'] = user['id_department']

    # 4. 加载科室列表 (根据当前数据中的医院ID，实现联动基础)
    # 注意：如果是新增顶级且是超管，刚进来 id_hospital 可能为空，此时不加载科室
    current_hid = obj_data.get('id_hospital')
    if current_hid:
        rules['dept_list'] = query_db("SELECT id_department, department_name FROM department WHERE id_hospital = ?", (current_hid,))

    return render_template('devices/device_form.html', obj=obj_data, rules=rules, user=user)


# =========================================================================
# 接口：保存设备
# =========================================================================
@bp_devices.route('/api/device_save', methods=['POST'])
def api_device_save():
    user = get_current_user_info()
    if not user: return jsonify({"code": 1, "msg": "未登录"})
    
    current_level = user.get('current_level', 0)
    user_work_flag = int(user.get('work_flag', 0))

    data = request.json
    
    # 提取字段
    oid = data.get('id')
    parent_id = int(data.get('parent_id') or 0)
    name = data.get('name')
    category = data.get('category', '')
    
    # 关键归属字段
    id_hospital = data.get('id_hospital')
    id_mgmt = data.get('id_department')
    id_use = data.get('use_department_id')
    
    # 清理 JSON 字段
    clean_extra = {k: v for k, v in data.get('extra_json', {}).items() if k.strip()}
    extra_str = json.dumps(clean_extra, ensure_ascii=False)

    # -----------------------------------------------------------
    # 安全校验 (后端二次验证，防止前端篡改 locked 字段)
    # -----------------------------------------------------------
    
    # 1. 医院权限校验 (Level < 90)
    if current_level < 90:
        if str(id_hospital) != str(user['id_hospital']):
             return jsonify({"code": 1, "msg": "权限不足：无法操作其他医院的设备"})

    # 2. 科室权限校验 (Level < 50)
    if current_level < 50:
        if user_work_flag == 1:
            # 职能科室：只能录入【管理科室】为本科室的设备
            if str(id_mgmt) != str(user['id_department']):
                return jsonify({"code": 1, "msg": "职能科室只能录入管理科室为本科室的设备"})
        else:
            # 临床科室：只能录入【使用科室】为本科室的设备
            if str(id_use) != str(user['id_department']):
                return jsonify({"code": 1, "msg": "临床科室只能录入使用科室为本科室的设备"})

    # 3. 补充名称信息 (用于冗余存储)
    h_name_res = query_db("SELECT hospital_name FROM hospital WHERE id_hospital=?", (id_hospital,), one=True)
    h_name = h_name_res['hospital_name'] if h_name_res else ""
    
    mgmt_name = ""
    if id_mgmt:
        r = query_db("SELECT department_name FROM department WHERE id_department=?", (id_mgmt,), one=True)
        if r: mgmt_name = r['department_name']

    use_name = ""
    if str(id_use) == '0': 
        use_name = "全院通用"
    elif id_use:
        r = query_db("SELECT department_name FROM department WHERE id_department=?", (id_use,), one=True)
        if r: use_name = r['department_name']

    # -----------------------------------------------------------
    # DB 操作
    # -----------------------------------------------------------
    if not oid:
        # INSERT
        ancestor_path = get_path_for_parent(parent_id)
        sql = """INSERT INTO facility_object 
                 (parent_id, name, model, category, id_hospital, hospital_name, 
                  id_department, department_name, use_department_id, use_department_name,
                  install_location, extra_json, ancestor_path)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        modify_db(sql, (parent_id, name, data.get('model'), category, id_hospital, h_name, 
                        id_mgmt, mgmt_name, id_use, use_name, 
                        data.get('install_location'), extra_str, ancestor_path))
    else:
        # UPDATE
        old = query_db("SELECT parent_id FROM facility_object WHERE id=?", (oid,), one=True)
        sql = """UPDATE facility_object SET name=?, model=?, category=?, id_department=?, department_name=?, 
                 use_department_id=?, use_department_name=?, install_location=?, extra_json=?
                 WHERE id=?"""
        modify_db(sql, (name, data.get('model'), category, id_mgmt, mgmt_name, id_use, use_name, 
                        data.get('install_location'), extra_str, oid))
        
        # 路径更新 (如果更改了父节点)
        if old and old['parent_id'] != parent_id:
            new_ancestor_path = get_path_for_parent(parent_id)
            # 更新自己
            modify_db("UPDATE facility_object SET parent_id=?, ancestor_path=? WHERE id=?", (parent_id, new_ancestor_path, oid))
            # 递归更新子孙
            new_prefix = f"{new_ancestor_path},{oid}"
            update_children_paths(oid, new_prefix)

    return jsonify({"code": 0, "msg": "保存成功"})