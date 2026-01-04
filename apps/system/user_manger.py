from flask import render_template, request, jsonify, redirect, url_for, session
from werkzeug.security import generate_password_hash
from .route import bp_system 
# 1. 引入集中管理的权限工具和常量
from apps.tools.auth import permission_required
from apps.tools.db import query_db, modify_db
from apps.tools.permissions import get_current_user_info, ROLE_LEVELS, get_user_max_level

@bp_system.route('/user_manger')
# 允许进入页面的角色：至少是科级管理以上
@permission_required('SA','GA','HA','HP','DA','DH')
def user_manger():
    user = get_current_user_info()
    if not user: return redirect(url_for('system.login'))
    hospitals = []
    # 2. 直接获取当前用户的等级 (permissions.py 中已计算好)
    current_level = user.get('current_level', 0)
    # 3. 医院列表加载逻辑
    # SA(100), GA(90) 可以看所有医院
    if current_level >= 90:
        hospitals = query_db("SELECT * FROM hospital")
    else:
        # HA/HP/DA/DH 只能看到自己所在的医院
        hospitals = [{
            'id_hospital': user['id_hospital'], 
            'hospital_name': user['hospital_name']
        }]
    return render_template("system/user_manger.html", 
                           user=user, 
                           hospitals=hospitals,
                           current_level=current_level, # 传递等级给前端控制表单
                           ROLE_LEVELS=ROLE_LEVELS)     # 传递全局角色字典给前端


@bp_system.route('/api/user', methods=['GET', 'POST', 'PUT', 'DELETE'])
@permission_required('SA','GA','HA','HP','DA','DH')
def api_user():
    user = get_current_user_info()
    if not user: return jsonify({"code": 1, "msg": "登录已过期"})

    # 获取当前操作者的等级
    current_level = user.get('current_level', 0)

    # --- GET: 查询列表 ---
    if request.method == 'GET':
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        search_hospital_id = request.args.get('id_hospital') 
        search_dept_id = request.args.get('id_department')
        
        offset = (page - 1) * limit
        params = []
        where_clauses = []

        # 权限过滤逻辑
        if current_level >= 90: # SA, GA (超管)
            if search_hospital_id:
                where_clauses.append("u.id_hospital = ?")
                params.append(search_hospital_id)
            if search_dept_id:
                where_clauses.append("u.id_department = ?")
                params.append(search_dept_id)

        elif current_level >= 50: # HA, HP (院级)
            where_clauses.append("u.id_hospital = ?")
            params.append(user['id_hospital']) # 强制只能看本院
            if search_dept_id:
                where_clauses.append("u.id_department = ?")
                params.append(search_dept_id)

        else: # DA, DH (科级 - Level 20/21)
            where_clauses.append("u.id_department = ?")
            params.append(user['id_department']) # 强制只能看本科室

        where_str = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        count_sql = f"SELECT COUNT(*) as total FROM user u {where_str}"
        total_res = query_db(count_sql, tuple(params), one=True)
        total = total_res['total'] if total_res else 0

        data_sql = f"""
            SELECT u.id, u.username, u.role, u.staff_flag,
                    u.id_hospital, u.id_department,
                    h.hospital_name, d.department_name
            FROM user u
            LEFT JOIN hospital h ON u.id_hospital = h.id_hospital
            LEFT JOIN department d ON u.id_department = d.id_department
            {where_str}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        data = query_db(data_sql, tuple(params))
        
        formatted_data = []
        for row in data:
            r = dict(row)
            r['hospital_name'] = r['hospital_name'] or "-"
            r['department_name'] = r['department_name'] or "-"
            formatted_data.append(r)

        return jsonify({"code": 0, "msg": "", "count": total, "data": formatted_data})

    # --- POST: 创建用户 ---
    elif request.method == 'POST':
        data = request.json
        # 接收多角色字符串，例如 "DA,SE"
        target_role_str = data.get('role', '') 
        
        # 1. 权限核心校验：创建的每一个角色，其等级都必须 < 当前操作者的等级
        target_roles = [r.strip() for r in target_role_str.split(',') if r.strip()]
        if not target_roles:
            return jsonify({"code": 1, "msg": "请至少选择一个角色"})
            
        for r in target_roles:
            # 使用从 auth.py 导入的 ROLE_LEVELS
            r_level = ROLE_LEVELS.get(r, 0)
            if r_level >= current_level:
                return jsonify({"code": 1, "msg": f"权限不足：您无法赋予他人 '{r}' 权限"})

        # 2. 归属地注入 (按等级强制注入)
        if current_level < 50: # DA/DH (科级)
            target_hospital_id = user['id_hospital']
            target_dept_id = user['id_department']
        elif current_level < 90: # HA/HP (院级)
            target_hospital_id = user['id_hospital']
            target_dept_id = data.get('id_department')
        else: # SA/GA (超管)
            target_hospital_id = data.get('id_hospital')
            target_dept_id = data.get('id_department')

        if not data.get('password'):
            return jsonify({"code": 1, "msg": "密码不能为空"})
        
        hashed_pwd = generate_password_hash(data.get('password'))
        staff_flag = int(data.get('staff_flag', 0))
        
        sql = "INSERT INTO user (username, password, role, id_hospital, id_department, staff_flag) VALUES (?, ?, ?, ?, ?, ?)"
        success, res = modify_db(sql, (data.get('username'), hashed_pwd, target_role_str, target_hospital_id, target_dept_id, staff_flag))
        
        if not success:
            if "UNIQUE constraint failed" in str(res):
                return jsonify({"code": 1, "msg": "保存失败：用户名已存在"})
            return jsonify({"code": 1, "msg": f"保存失败: {res}"})

        return jsonify({"code": 0, "msg": "创建成功"})

    # --- PUT: 修改用户 ---
    elif request.method == 'PUT':
        data = request.json
        uid = data.get('id')
        new_role_str = data.get('role', '')
        
        # 1. 获取目标用户当前信息 (用于判断是否越权编辑)
        target_user = query_db(
            "SELECT role, id_hospital, id_department FROM user WHERE id = ?",
            (uid,), one=True
        )
        if not target_user: return jsonify({"code": 1, "msg": "用户不存在"})

        # 2. 权限校验 A：目标用户当前的等级 >= 我的等级？ -> 禁止编辑
        # 使用从 auth.py 导入的 get_user_max_level
        target_current_max_level = get_user_max_level(target_user['role'])
        
        if target_current_max_level >= current_level:
            return jsonify({"code": 1, "msg": "权限不足：无法编辑同级或更高级别的用户"})

        # 3. 权限校验 B：我试图赋予的新角色等级 >= 我的等级？ -> 禁止赋予
        new_roles = [r.strip() for r in new_role_str.split(',') if r.strip()]
        if not new_roles: return jsonify({"code": 1, "msg": "请至少选择一个角色"})
        for r in new_roles:
            if ROLE_LEVELS.get(r, 0) >= current_level:
                return jsonify({"code": 1, "msg": f"权限不足：无法赋予 '{r}' 权限"})

        # 4. 范围校验
        if current_level < 50 and target_user['id_department'] != user['id_department']:
             return jsonify({"code": 1, "msg": "权限不足：非本科室用户"})
        if current_level < 90 and target_user['id_hospital'] != user['id_hospital']:
             return jsonify({"code": 1, "msg": "权限不足：非本院用户"})

        # 5. 归属地处理
        if current_level < 50:
            target_hospital_id = user['id_hospital']
            target_dept_id = user['id_department']
        elif current_level < 90:
            target_hospital_id = user['id_hospital']
            target_dept_id = data.get('id_department')
        else:
            target_hospital_id = data.get('id_hospital')
            target_dept_id = data.get('id_department')

        staff_flag = int(data.get('staff_flag', 0))

        update_fields = [
            "username=?", "role=?", "staff_flag=?",
            "id_hospital=?", "id_department=?"
        ]
        update_params = [
            data.get('username'), new_role_str, staff_flag,
            target_hospital_id, target_dept_id
        ]

        if data.get('password'):
            update_fields.append("password=?")
            update_params.append(generate_password_hash(data.get('password')))

        sql = f"UPDATE user SET {','.join(update_fields)} WHERE id=?"
        full_params = update_params + [uid]

        success, res = modify_db(sql, tuple(full_params))
        if not success:
            if "UNIQUE constraint failed" in str(res):
                return jsonify({"code": 1, "msg": "用户名已存在"})
            return jsonify({"code": 1, "msg": f"更新失败: {res}"})

        return jsonify({"code": 0, "msg": "更新成功"})

    # --- DELETE: 删除用户 ---
    elif request.method == 'DELETE':
        id_ = request.json.get('id')
        target_user = query_db("SELECT role, id_hospital, id_department FROM user WHERE id = ?", (id_,), one=True)
        if not target_user: return jsonify({"code": 1, "msg": "用户不存在"})

        # 1. 权限校验：不能删除同级或高级
        target_max_level = get_user_max_level(target_user['role'])
        if target_max_level >= current_level:
             return jsonify({"code": 1, "msg": "权限不足：无法删除该级别的用户"})

        # 2. 范围校验
        if current_level < 50 and target_user['id_department'] != user['id_department']:
             return jsonify({"code": 1, "msg": "权限不足"})
        if current_level < 90 and target_user['id_hospital'] != user['id_hospital']:
             return jsonify({"code": 1, "msg": "权限不足"})

        success, res = modify_db("DELETE FROM user WHERE id=?", (id_,))
        return jsonify({"code": 0 if success else 1, "msg": "删除成功" if success else "失败"})


# 辅助接口：根据医院ID获取科室列表 (用于前端二级联动)
@bp_system.route('/api/get_depts_by_hospital')
def get_depts_by_hospital():
    hid = request.args.get('id_hospital')
    if not hid:
        return jsonify({"code": 0, "data": []})

    sql = """
        SELECT 
            id_department,
            department_name,
            work_flag
        FROM department
        WHERE id_hospital = ?
        ORDER BY department_name
    """
    data = query_db(sql, (hid,))
    return jsonify({"code": 0, "data": data})