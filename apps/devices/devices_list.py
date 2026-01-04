# devices_list.py
from flask import render_template, request, jsonify
from apps.tools.db import query_db, modify_db
from apps.tools.permissions import get_current_user_info
from apps.devices.route import bp_devices

# =========================================================================
# 工具函数：路径计算与递归更新 (保持不变)
# =========================================================================

def get_path_for_parent(parent_id):
    """根据父ID获取当前节点的 ancestor_path"""
    if not parent_id or int(parent_id) == 0:
        return "0"
    
    parent = query_db("SELECT ancestor_path FROM facility_object WHERE id = ?", (parent_id,), one=True)
    if parent:
        return f"{parent['ancestor_path']},{parent_id}"
    return "0"

def update_children_paths(node_id, new_path_prefix):
    """递归更新子孙节点的 ancestor_path"""
    children = query_db("SELECT id FROM facility_object WHERE parent_id = ?", (node_id,))
    for child in children:
        child_path = f"{new_path_prefix},{node_id}"
        modify_db("UPDATE facility_object SET ancestor_path = ? WHERE id = ?", (child_path, child['id']))
        update_children_paths(child['id'], child_path)

# =========================================================================
# 页面渲染
# =========================================================================
@bp_devices.route('/devices_list')
def devices_list():
    user = get_current_user_info()
    if not user: return "请先登录", 403

    # 1. 获取当前等级
    current_level = user.get('current_level', 0)

    # 2. 准备数据容器
    hospitals = []
    departments = []

    # 3. 医院列表逻辑
    if current_level >= 90:
        # SA/GA: 看所有医院
        hospitals = query_db("SELECT id_hospital, hospital_name FROM hospital")
    else:
        # HA/HP/DA/DH...: 只能看自己所在的医院
        hospitals = [{
            'id_hospital': user['id_hospital'], 
            'hospital_name': user['hospital_name']
        }]

    # 4. 科室列表逻辑
    # 场景A: 院级管理员 (50<=Level<90)，虽然锁定了医院，但需要筛选科室，所以预加载
    # 场景B: 其他人进入页面时，也可以预加载，前端会根据权限决定是"下拉框"还是"锁定文本框"
    # 这里为了方便，只要确定了医院ID (非超管或超管选了医院)，就加载科室。
    # 对于超管，刚进页面 id_hospital 为空，departments 为空，由前端联动加载。
    target_hid = ''
    if current_level < 90:
        target_hid = user['id_hospital']
    
    if target_hid:
         departments = query_db("SELECT id_department, department_name FROM department WHERE id_hospital = ?", (target_hid,))

    return render_template('devices/devices_list.html', 
                           user=user,
                           hospitals=hospitals,
                           departments=departments,
                           current_level=current_level)

# =========================================================================
# 数据接口 (含权限 + 搜索)
# =========================================================================
@bp_devices.route('/api/tree_list')
def api_tree_list():
    user = get_current_user_info()
    if not user: return jsonify({"code": 1, "msg": "未登录"})

    current_level = user.get('current_level', 0)

    # 获取前端参数
    raw_pid = request.args.get('parent_id')
    parent_id = int(raw_pid) if (raw_pid and raw_pid.isdigit()) else 0
    keyword = request.args.get('keyword', '').strip()
    
    req_hospital = request.args.get('id_hospital')
    req_dept = request.args.get('id_department')

    # === 1. 确定医院范围 ===
    if current_level >= 90:
        # 超管：使用前端传参
        target_hospital = req_hospital
    else:
        # 院管及以下：强制锁定本院
        target_hospital = user['id_hospital']

    # === 2. 核心查询分支 ===
    
    # --- 分支 A：管理层模式 (Level >= 50) ---
    # 包括：SA(100), GA(90), HP(55), HA(50)
    # 特点：可以看到管辖医院下的所有设备，不受“我的科室”限制
    if current_level >= 50:
        sql = "SELECT * FROM facility_object WHERE 1=1"
        args = []
        
        # 医院过滤
        if target_hospital:
            sql += " AND id_hospital = ?"
            args.append(target_hospital)
        
        # 科室过滤 (如果管理员在搜索栏选择了特定科室)
        if req_dept:
            sql += " AND (id_department = ? OR use_department_id = ?)"
            args.extend([req_dept, req_dept])

        # 关键词与层级
        if keyword:
            sql += " AND (name LIKE ? OR model LIKE ?)"
            args.extend([f'%{keyword}%', f'%{keyword}%'])
            sql += " LIMIT 100"
        else:
            sql += " AND parent_id = ?"
            args.append(parent_id)
            
        data = query_db(sql, tuple(args))
        return jsonify({"code": 0, "data": data})

    # --- 分支 B：业务层模式 (Level < 50) ---
    # 包括：DH(30), DA(25), PA(20), SE(10), ST(10)
    # 特点：启用路径隔离（白名单）。只能看到自己科室管理或使用的设备，以及到达这些设备的路径节点。
    else:
        # 1. 找出所有“锚点” (我管的 OR 我用的)
        # 注意：这里忽略前端传的 req_dept，强制使用用户的 id_department
        anchor_sql = """
            SELECT id, parent_id, ancestor_path 
            FROM facility_object 
            WHERE id_hospital = ? AND (id_department = ? OR use_department_id = ?)
        """
        anchors = query_db(anchor_sql, (user['id_hospital'], user['id_department'], user['id_department']))
        
        if not anchors:
            return jsonify({"code": 0, "data": []})

        # 2. 构建白名单 (所有锚点 ID + 它们的所有祖先 ID)
        valid_ids = set()
        for row in anchors:
            valid_ids.add(row['id'])
            if row['ancestor_path'] and row['ancestor_path'] != '0':
                for pid in row['ancestor_path'].split(','):
                    if pid and pid != '0': valid_ids.add(int(pid))
        
        # 3. 执行查询
        if keyword:
            # 搜索模式：先搜全院符合名字的，再用白名单过滤
            search_sql = "SELECT * FROM facility_object WHERE id_hospital = ? AND (name LIKE ? OR model LIKE ?)"
            candidates = query_db(search_sql, (user['id_hospital'], f'%{keyword}%', f'%{keyword}%'))
            data = [c for c in candidates if c['id'] in valid_ids]
        else:
            # 懒加载模式：查子节点，必须在白名单内
            if not valid_ids: return jsonify({"code": 0, "data": []})
            
            # 使用 IN 查询
            placeholders = ','.join(['?'] * len(valid_ids))
            child_sql = f"SELECT * FROM facility_object WHERE parent_id = ? AND id_hospital = ? AND id IN ({placeholders})"
            args = [parent_id, user['id_hospital']] + list(valid_ids)
            data = query_db(child_sql, tuple(args))
            
            # 4. 标记只读节点 (前端展示用)
            # 如果该节点既不是我管的，也不是我用的（说明它是路径上的父级结构），则标记为只读
            for child in data:
                is_mine = (str(child['id_department']) == str(user['id_department']) or 
                           str(child['use_department_id']) == str(user['id_department']))
                if not is_mine: 
                    child['_is_structure_path'] = True

        return jsonify({"code": 0, "data": data})

@bp_devices.route('/api/get_node_path')
def api_get_node_path():
    """
    根据ID获取节点的完整路径字符串 (用于弹窗标题)
    返回格式: "某某医院 - 住院楼 - 1层 - 配电室"
    """
    node_id = request.args.get('id', type=int)
    if not node_id:
        return jsonify({"code": 1, "msg": "ID不能为空"})

    # 1. 查询当前节点信息
    node = query_db("SELECT name, hospital_name, ancestor_path FROM facility_object WHERE id = ?", (node_id,), one=True)
    if not node:
        return jsonify({"code": 1, "msg": "节点不存在"})

    # 2. 解析祖先ID
    path_names = [node['hospital_name'] or ''] # 起始：医院名
    
    ancestor_ids = []
    if node['ancestor_path'] and node['ancestor_path'] != '0':
        parts = node['ancestor_path'].split(',')
        for p in parts:
            if p and p != '0':
                ancestor_ids.append(int(p))
    
    # 3. 如果有祖先，批量查询祖先名称
    if ancestor_ids:
        placeholders = ','.join(['?'] * len(ancestor_ids))
        sql = f"SELECT id, name FROM facility_object WHERE id IN ({placeholders})"
        res = query_db(sql, tuple(ancestor_ids))
        name_map = {r['id']: r['name'] for r in res}
        
        # 按 ancestor_ids 的顺序添加名称
        for aid in ancestor_ids:
            if aid in name_map:
                path_names.append(name_map[aid])

    # 4. 添加自己
    path_names.append(node['name'])
    
    return jsonify({"code": 0, "data": ' - '.join([p for p in path_names if p])})