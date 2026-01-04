# department_manger.py
from flask import render_template, request, jsonify, redirect, url_for
from .route import bp_system 
from apps.tools.auth import permission_required
from apps.tools.db import query_db, modify_db
from apps.tools.permissions import get_current_user_info

# 页面路由
@bp_system.route('/department_manger')
# 只允许 院级(50) 及以上角色访问
@permission_required('SA','GA','HA','HP')
def department_manger():
    user = get_current_user_info()
    if not user: return redirect(url_for('system.login'))

    # 获取当前用户最高等级 (由 get_current_user_info 直接提供)
    # 如果你尚未更新 permissions.py，这里 user.get('current_level', 0) 会是 0
    current_level = user.get('current_level', 0)
    
    hospitals = []
    
    # SA(100), GA(90) 加载所有医院
    if current_level >= 90:
        sql = "SELECT * FROM hospital"
        hospitals = query_db(sql)
    else:
        # HA(50), HP(50) 只保留当前医院
        hospitals = [{
            'id_hospital': user['id_hospital'], 
            'hospital_name': user['hospital_name']
        }]

    return render_template("system/department_manger.html", 
                           user=user, 
                           hospitals=hospitals,
                           current_level=current_level)

# API：科室管理
@bp_system.route('/api/department', methods=['GET', 'POST', 'PUT', 'DELETE'])
@permission_required('SA','GA','HA','HP')
def api_department():
    user = get_current_user_info()
    if not user: return jsonify({"code": 1, "msg": "登录已过期"})

    current_level = user.get('current_level', 0)

    # --- GET: 查询 ---
    if request.method == 'GET':
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        search_hospital_id = request.args.get('id_hospital') 
        
        offset = (page - 1) * limit
        params = []
        where_clauses = []

        # 权限控制
        if current_level >= 90:
            # 超管：自由搜索
            if search_hospital_id:
                where_clauses.append("d.id_hospital = ?")
                params.append(search_hospital_id)
        else:
            # 院管：强制锁定本院
            where_clauses.append("d.id_hospital = ?")
            params.append(user['id_hospital'])
        
        where_str = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        count_sql = f"SELECT COUNT(*) as total FROM department d {where_str}"
        total_res = query_db(count_sql, tuple(params), one=True)
        total = total_res['total'] if total_res else 0

        data_sql = f"""
            SELECT d.*, h.hospital_name 
            FROM department d 
            LEFT JOIN hospital h ON d.id_hospital = h.id_hospital 
            {where_str} 
            ORDER BY d.id_hospital, d.id_department_in_hospital
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        data = query_db(data_sql, tuple(params))
        return jsonify({"code": 0, "msg": "", "count": total, "data": data})

    # --- POST: 新增 ---
    elif request.method == 'POST':
        data = request.json
        
        # 确定所属医院
        if current_level >= 90:
            target_hospital_id = data.get('id_hospital')
        else:
            # 院管强制使用自己的ID
            target_hospital_id = user['id_hospital']
        
        if not target_hospital_id:
             return jsonify({"code": 1, "msg": "必须选择所属医院"})

        # 自动编号逻辑
        max_sql = "SELECT MAX(id_department_in_hospital) as max_id FROM department WHERE id_hospital = ?"
        max_res = query_db(max_sql, (target_hospital_id,), one=True)
        
        current_max = max_res['max_id'] if max_res and max_res['max_id'] is not None else 0
        new_inner_id = current_max + 1
        
        try:
            # 生成URL: 医院ID(3位) + 内部编号(4位)
            new_url = f"{int(target_hospital_id):03d}{new_inner_id:04d}"
        except ValueError:
            return jsonify({"code": 1, "msg": "医院ID格式异常，无法生成科室编码"})

        insert_sql = """
            INSERT INTO department 
            (id_hospital, id_department_in_hospital, department_name, department_url, description, work_flag) 
            VALUES (?, ?, ?, ?, ?, ?)
        """
        success, res = modify_db(insert_sql, (
            target_hospital_id,
            new_inner_id,
            data.get('department_name'),
            new_url,
            data.get('description'),
            data.get('work_flag', 1)
        ))
        return jsonify({"code": 0 if success else 1, "msg": "添加成功" if success else f"失败: {res}"})

    # --- PUT: 修改 ---
    elif request.method == 'PUT':
        data = request.json
        dept_id = data.get('id_department')

        # 安全检查：如果不是超管，需要检查该科室是否属于该院管
        if current_level < 90:
            check = query_db("SELECT id_hospital FROM department WHERE id_department=?", (dept_id,), one=True)
            if not check or str(check['id_hospital']) != str(user['id_hospital']):
                return jsonify({"code": 1, "msg": "权限不足：无法修改其他医院的科室"})

        sql = """
            UPDATE department 
            SET department_name=?, description=?, work_flag=? 
            WHERE id_department=?
        """
        success, res = modify_db(sql, (
            data.get('department_name'),
            data.get('description'),
            data.get('work_flag'),
            dept_id
        ))
        return jsonify({"code": 0 if success else 1, "msg": "修改成功" if success else "失败"})

    # --- DELETE: 删除 ---
    elif request.method == 'DELETE':
        id_ = request.json.get('id_department')

        # 1. 获取科室信息（用于校验存在性和权限）
        target_dept = query_db("SELECT id_hospital FROM department WHERE id_department=?", (id_,), one=True)
        
        if not target_dept:
            return jsonify({"code": 1, "msg": "科室不存在或已被删除"})

        # 2. 权限检查：如果不是超管(90+)，只能删除本院科室
        if current_level < 90:
            if str(target_dept['id_hospital']) != str(user['id_hospital']):
                return jsonify({"code": 1, "msg": "权限不足：无法删除其他医院的科室"})

        # 3. 关联检查：该科室下是否存在用户
        check_user = query_db("SELECT COUNT(*) as count FROM user WHERE id_department=?", (id_,), one=True)
        
        if check_user and check_user['count'] > 0:
            return jsonify({
                "code": 1, 
                "msg": f"操作失败：该科室下仍绑定了 {check_user['count']} 名用户，无法删除。请先移除这些用户。"
            })

        # 4. 执行删除
        sql = "DELETE FROM department WHERE id_department=?"
        success, res = modify_db(sql, (id_,))
        return jsonify({"code": 0 if success else 1, "msg": "删除成功" if success else "失败"})