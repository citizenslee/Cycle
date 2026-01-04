from flask import Blueprint, request, jsonify, render_template
from datetime import datetime
from apps.tools.db import query_db, modify_db, get_db, execute_transaction
from apps.tools.permissions import get_current_user_info
from apps.tools.auth import permission_required

bp_materials = Blueprint('materials', __name__, url_prefix='/materials')

# 状态常量
STATUS_PENDING = 0
STATUS_APPROVED = 1
STATUS_REJECTED = 2
STATUS_STOCKED = 3

# ================= 页面渲染 =================

@bp_materials.route('/apply_page')
@permission_required('SA','GA','HA','HP','DA','DH','PA','SE','ST')
def apply_page():
    """ 1. 请购申请页面 (全员可用) """
    user = get_current_user_info()
    return render_template('orders/materials/apply.html', user=user)


@bp_materials.route('/approve_page')
@permission_required('SA','GA','HA','HP','DA','DH','PA','SE','ST')
def approve_page():
    """ 2. 审批页面 (仅 管理员 或 采购员) """
    user = get_current_user_info()
    current_level = user.get('current_level', 0)
    
    # 权限标记：是否能审批 (SA, GA, HA, HP, PA)
    # 注意：这里假设 PA(采购) 的等级可能只有 20 或 40，但它有审批特定的职能
    can_approve = False
    user_roles = user.get('role', '').split(',')
    if current_level >= 50 or 'PA' in user_roles:
        can_approve = True

    hospitals = []
    departments = []
    
    # 筛选框数据加载
    if current_level >= 90:
        # 超管：看所有
        hospitals = query_db("SELECT id_hospital, hospital_name FROM hospital")
        # 部门由前端联动加载，此处略或加载全部
    else:
        # 院管/采购：锁定本院
        hospitals = [{'id_hospital': user['id_hospital'], 'hospital_name': user['hospital_name']}]
        departments = query_db("SELECT id_department, department_name FROM department WHERE id_hospital = ?", (user['id_hospital'],))

    return render_template('orders/materials/approve.html', 
                           user=user, 
                           current_level=current_level,
                           is_purchaser=can_approve, 
                           hospitals=hospitals, 
                           departments=departments)


@bp_materials.route('/stock_table')
@permission_required('SA','GA','HA','HP','PA','DA','DH') # 开放给科室管理查看库存
def stock_table():
    """ 3. 库存列表 """
    user = get_current_user_info()
    current_level = user.get('current_level', 0)
    
    hospitals = []
    if current_level >= 90:
        hospitals = query_db("SELECT id_hospital, hospital_name FROM hospital")
    
    return render_template('orders/materials/stock_table.html', 
                           user=user, 
                           current_level=current_level,
                           hospitals=hospitals)


# ================= API 接口 =================

@bp_materials.route('/api/apply', methods=['POST'])
@permission_required('SA','GA','HA','HP','DA','DH','PA','SE','ST')
def api_apply():
    req_json = request.json 
    if not req_json or not req_json.get('items'):
        return jsonify({"code": 1, "msg": "请至少添加一项物资"})

    user = get_current_user_info()
    reason = req_json.get('reason', '')
    
    operations = []
    sql_insert = """
        INSERT INTO material_requests 
        (material_name, model, spec, apply_qty, unit, estimated_price, 
         dept_name, applicant, user_id, reason, id_hospital, id_department, remark, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
    """
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    for item in req_json['items']:
        if not item.get('name'): continue
        args = (
            item.get('name'), item.get('model', ''), item.get('spec', ''),
            item.get('quantity', 0), item.get('unit', ''), item.get('price', 0),
            user['department_name'], user['username'], str(user['id']),
            reason, user['id_hospital'], user['id_department'], item.get('remark', ''),
            now_str
        )
        operations.append((sql_insert, args))

    success, msg = execute_transaction(operations)
    return jsonify({"code": 0 if success else 1, "msg": f"成功提交 {len(operations)} 项申请" if success else msg})


@bp_materials.route('/api/request_list')
@permission_required('SA','GA','HA','HP','DA','DH','PA','SE','ST')
def api_request_list():
    user = get_current_user_info()
    current_level = user.get('current_level', 0)
    user_roles = user.get('role', '').split(',')

    # 1. 基础参数
    status = request.args.get('status')
    req_hospital_id = request.args.get('search_hospital')
    req_dept_id = request.args.get('search_dept')
    date_range = request.args.get('date_range') 
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 15, type=int)

    where_clauses = ["1=1"]
    args = []

    # 2. 权限隔离逻辑 (核心改造)
    # ----------------------------------------------------
    if current_level >= 90:
        # [层级1] 超管/集团: 可看所有 (根据前端筛选)
        if req_hospital_id:
            where_clauses.append("id_hospital = ?")
            args.append(req_hospital_id)
        if req_dept_id:
            where_clauses.append("id_department = ?")
            args.append(req_dept_id)

    elif current_level >= 50 or 'PA' in user_roles:
        # [层级2] 院管/院长/采购员(PA): 锁定本院，可看全院所有科室
        where_clauses.append("id_hospital = ?")
        args.append(user['id_hospital'])
        
        # 允许筛选院内科室
        if req_dept_id:
            where_clauses.append("id_department = ?")
            args.append(req_dept_id)

    elif current_level >= 20:
        # [层级3] 科管/科长 (DA/DH): 锁定本院 + 锁定本科室
        where_clauses.append("id_hospital = ?")
        args.append(user['id_hospital'])
        where_clauses.append("id_department = ?")
        args.append(user['id_department'])

    else:
        # [层级4] 员工 (SE/ST): 只能看自己提交的
        where_clauses.append("user_id = ?")
        args.append(str(user['id']))
    # ----------------------------------------------------

    # 3. 状态与日期筛选
    if status:
        where_clauses.append("status = ?")
        args.append(status)
    
    if date_range and ' - ' in date_range:
        try:
            start, end = date_range.split(' - ')
            where_clauses.append("created_at BETWEEN ? AND ?")
            args.extend([f"{start} 00:00:00", f"{end} 23:59:59"])
        except: pass

    where_sql = " WHERE " + " AND ".join(where_clauses)

    # 4. 执行查询
    total_res = query_db(f"SELECT COUNT(*) as cnt FROM material_requests {where_sql}", args, one=True)
    total = total_res['cnt'] if total_res else 0

    data_sql = f"SELECT * FROM material_requests {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    data_list = query_db(data_sql, args + [limit, (page - 1) * limit])

    return jsonify({"code": 0, "msg": "", "count": total, "data": data_list})


@bp_materials.route('/api/approve', methods=['POST'])
@permission_required('SA','GA','HA','HP','PA')
def api_approve():
    user = get_current_user_info()
    current_level = user.get('current_level', 0)
    
    req_id = request.form.get('id')
    action = request.form.get('action') 
    reason = request.form.get('reason', '') 

    if not req_id: return jsonify({"code": 1, "msg": "参数缺失"})

    # 1. 权限校验 (防止跨院审批)
    target_req = query_db("SELECT id_hospital FROM material_requests WHERE id=?", (req_id,), one=True)
    if not target_req:
        return jsonify({"code": 1, "msg": "申请单不存在"})
    
    # 非超管必须校验医院ID
    if current_level < 90:
        if str(target_req['id_hospital']) != str(user['id_hospital']):
            return jsonify({"code": 1, "msg": "权限不足：无法审批其他医院的申请"})

    # 2. 执行审批
    new_status = STATUS_APPROVED if action == 'pass' else STATUS_REJECTED
    reason_val = '' if action == 'pass' else reason
    now_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    sql = "UPDATE material_requests SET status=?, approver=?, approval_time=?, reject_reason=? WHERE id=?"
    success, res = modify_db(sql, (new_status, user['username'], now_time, reason_val, req_id))
    
    return jsonify({"code": 0 if success else 1, "msg": "操作成功" if success else str(res)})
    

@bp_materials.route('/api/stock_in', methods=['POST'])
@permission_required('SA','GA','HA','HP','PA')
def api_stock_in():
    user = get_current_user_info()
    current_level = user.get('current_level', 0)

    req_id = request.form.get('id')
    actual_qty = request.form.get('actual_qty', type=int)
    actual_price = request.form.get('actual_price', type=float)

    if not all([req_id, actual_qty, actual_price is not None]):
        return jsonify({"code": 1, "msg": "请填写完整的入库数量和单价"})

    # 1. 校验申请单及权限
    req = query_db("SELECT * FROM material_requests WHERE id = ?", (req_id,), one=True)
    if not req or req['status'] != STATUS_APPROVED:
        return jsonify({"code": 1, "msg": "单据状态错误或不存在"})

    # 权限校验：非超管只能入库本院
    if current_level < 90:
        if str(req['id_hospital']) != str(user['id_hospital']):
            return jsonify({"code": 1, "msg": "权限不足：无法操作其他医院数据"})

    hospital = query_db("SELECT hospital_name FROM hospital WHERE id_hospital = ?", (req['id_hospital'],), one=True)
    h_name = hospital['hospital_name'] if hospital else '未知'
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    db = get_db()
    try:
        # 1. 更新申请单状态 -> 已入库
        db.execute("UPDATE material_requests SET status = ? WHERE id = ?", (STATUS_STOCKED, req_id))
        
        # 2. 库存处理（存在即累加，不存在即新增）
        # 注意：这里以 名称+型号+规格+医院+单价 为唯一标识
        stock = query_db("SELECT id FROM material_stock WHERE name=? AND spec=? AND model=? AND id_hospital=? AND price=?", 
                         (req['material_name'], req['spec'], req['model'], req['id_hospital'], actual_price), one=True)
        
        if stock:
            db.execute("UPDATE material_stock SET quantity = quantity + ?, updated_at = ? WHERE id = ?", 
                       (actual_qty, now_str, stock['id']))
        else:
            db.execute("""INSERT INTO material_stock (name, model, spec, quantity, unit, price, id_hospital, hospital_name, remark, updated_at)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
                       (req['material_name'], req['model'], req['spec'], actual_qty, req['unit'], 
                        actual_price, req['id_hospital'], h_name, req['remark'], now_str))
            
        # 3. 日志流水
        db.execute("""INSERT INTO material_logs (material_name, model, spec, change_qty, price, total_cost, action_type, operator, remark, id_hospital, hospital_name, created_at)
                      VALUES (?, ?, ?, ?, ?, ?, '采购入库', ?, ?, ?, ?, ?)""",
                   (req['material_name'], req['model'], req['spec'], actual_qty, actual_price, 
                    actual_qty * actual_price, user['username'], f"关联单号:{req_id}", 
                    req['id_hospital'], h_name, now_str))

        db.commit()
        return jsonify({"code": 0, "msg": "入库成功"})
    except Exception as e:
        db.rollback()
        return jsonify({"code": 1, "msg": f"数据库错误: {str(e)}"})


@bp_materials.route('/api/stock_manager_list')
@permission_required('SA','GA','HA','HP','DA','DH','PA','SE','ST')
def api_stock_manager_list():
    user = get_current_user_info()
    current_level = user.get('current_level', 0)

    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 15, type=int)
    keyword = request.args.get('keyword', '').strip()
    req_hospital_id = request.args.get('search_hospital')

    where_clauses = ["1=1"]
    params = []

    # 权限：非超管只能看本院
    if current_level >= 90:
        if req_hospital_id:
            where_clauses.append("id_hospital = ?")
            params.append(req_hospital_id)
    else:
        where_clauses.append("id_hospital = ?")
        params.append(user['id_hospital'])

    if keyword:
        where_clauses.append("(name LIKE ? OR model LIKE ? OR spec LIKE ?)")
        l_str = f"%{keyword}%"
        params.extend([l_str, l_str, l_str])

    where_sql = " WHERE " + " AND ".join(where_clauses)
    
    count_res = query_db(f"SELECT COUNT(*) as cnt FROM material_stock {where_sql}", params, one=True)
    sql = f"SELECT * FROM material_stock {where_sql} ORDER BY quantity ASC, id DESC LIMIT ? OFFSET ?"
    data_list = query_db(sql, params + [limit, (page - 1) * limit])

    return jsonify({"code": 0, "count": count_res['cnt'] if count_res else 0, "data": data_list})