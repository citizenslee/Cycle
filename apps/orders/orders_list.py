# orders_list.py
from flask import render_template, request, jsonify
from apps.tools.auth import permission_required
from apps.tools.db import query_db, modify_db
from .orders_log import record_order_flow
from .route import bp_orders
from apps.tools.permissions import get_current_user_info

# ------------------------------------------------
# 1. 页面渲染 (入口)
# ------------------------------------------------
@bp_orders.route('/list')
@permission_required('SA','GA','HA','HP','DA','DH','SE','ST','PA')
def list_page():
    user = get_current_user_info()
    
    # 1. 获取关键信息
    current_level = user.get('current_level', 0)
    user_hospital_id = user.get('id_hospital')
    user_dept_id = user.get('id_department')
    user_work_flag = int(user.get('work_flag', 0)) # 0:临床(需求方), 1:职能(受理方)

    # 2. 初始化权限配置 (默认全开)
    permissions = {
        'lock_hospital': False,
        'lock_init_dept': False,     
        'lock_accept_dept': False,   
        'default_hospital': '',      
        'default_init_dept': '',     
        'default_accept_dept': ''    
    }

    hospitals = []
    departments = []

    # -----------------------------------------------------------
    # 3. 权限判定逻辑 (从高到低)
    # -----------------------------------------------------------
    
    # [层级 1] 超级管理员 / 集团管理员 (Level >= 90)
    if current_level >= 90:
        # 解锁所有，加载所有数据
        hospitals = query_db("SELECT id_hospital, hospital_name FROM hospital")
        # 超管默认不加载科室，由前端选择医院后联动加载，防止下拉框数据量爆炸
        departments = [] 

    # [层级 2] 院长 / 医院管理员 (50 <= Level < 90)
    elif current_level >= 50:
        # 锁定医院，解锁所有科室筛选
        permissions['lock_hospital'] = True
        permissions['default_hospital'] = user_hospital_id
        
        # 加载本院数据
        hospitals = [{ 'id_hospital': user['id_hospital'], 'hospital_name': user['hospital_name'] }]
        departments = query_db("SELECT id_department, department_name, work_flag FROM department WHERE id_hospital = ?", (user_hospital_id,))

    # [层级 3] 科长 / 科室管理员 / 员工 (Level < 50)
    else:
        # 基础：锁定医院
        permissions['lock_hospital'] = True
        permissions['default_hospital'] = user_hospital_id
        
        hospitals = [{ 'id_hospital': user['id_hospital'], 'hospital_name': user['hospital_name'] }]
        departments = query_db("SELECT id_department, department_name, work_flag FROM department WHERE id_hospital = ?", (user_hospital_id,))

        # 细分：根据科室职能判定
        if user_work_flag == 1:
            # === 职能科室 (维修/受理方) ===
            # 逻辑：他们负责处理工单。
            # 限制：只能看【受理科室】是自己的单子 (lock_accept_dept)
            # 允许：筛选【发起科室】(看是谁报修的)
            permissions['lock_accept_dept'] = True
            permissions['default_accept_dept'] = user_dept_id
            permissions['lock_init_dept'] = False # 显式声明解锁

        else:
            # === 临床科室 (需求/发起方) ===
            # 逻辑：他们发起工单。
            # 限制：只能看【发起科室】是自己的单子 (lock_init_dept)
            # 允许：筛选【受理科室】(看是指派给谁修的)
            permissions['lock_init_dept'] = True
            permissions['default_init_dept'] = user_dept_id
            permissions['lock_accept_dept'] = False # 显式声明解锁

    return render_template(
        "orders/list.html", 
        user=user,
        permissions=permissions,
        hospitals=hospitals,
        departments=departments,
        current_level=current_level
    )


# --- 2. API 工单列表数据接口 ---
@bp_orders.route('/api/list', methods=['GET'])
@permission_required('SA','GA','HA','HP','DA','DH','SE','ST','PA')
def get_workorders_data():
    user = get_current_user_info()
    current_level = user.get('current_level', 0)
    user_hospital_id = user.get('id_hospital')
    user_dept_id = user.get('id_department')
    user_work_flag = int(user.get('work_flag', 0))

    # 参数获取
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 15, type=int)
    offset = (page - 1) * limit
    
    # 筛选条件
    search_id = request.args.get('id', '').strip()
    search_status_str = request.args.get('status', '').strip()
    search_work_type_str = request.args.get('work_type', '').strip() # 新增：工作类型
    
    req_hospital = request.args.get('search_hospital', '').strip()
    req_init_dept = request.args.get('search_init_dept', '').strip()
    req_accept_dept = request.args.get('search_accept_dept', '').strip()
    daterange = request.args.get('daterange', '').strip()

    # -------------------------------------------------------
    # 权限控制逻辑 (与 View 保持一致)
    # -------------------------------------------------------
    
    target_hospital_id = None
    final_init_dept = req_init_dept
    final_accept_dept = req_accept_dept

    # 1. 医院权限
    if current_level >= 90:
        target_hospital_id = req_hospital # 超管可用参数
    else:
        target_hospital_id = user_hospital_id # 强制本院

    # 2. 科室权限 (仅针对 Level < 50)
    if current_level < 50:
        if user_work_flag == 1:
            # 职能科室：强制锁定受理科室，发起科室允许前端筛选
            final_accept_dept = user_dept_id
            # final_init_dept 保持前端传来的 req_init_dept
        else:
            # 临床科室：强制锁定发起科室，受理科室允许前端筛选
            final_init_dept = user_dept_id
            # final_accept_dept 保持前端传来的 req_accept_dept

    # -------------------------------------------------------
    # SQL 构建
    # -------------------------------------------------------
    base_sql = "FROM work_orders WHERE 1=1"
    args = []

    # 1. 医院
    if target_hospital_id:
        base_sql += " AND id_created_hospital = ?"
        args.append(target_hospital_id)

    # 2. 发起科室
    if final_init_dept:
        base_sql += " AND id_created_department = ?"
        args.append(final_init_dept)

    # 3. 受理科室
    if final_accept_dept:
        base_sql += " AND work_department = ?"
        args.append(final_accept_dept)

    # 4. 工作类型 (新增)
    if search_work_type_str:
        # 前端传 "维修,巡检" -> IN ('维修', '巡检')
        wt_list = [s.strip() for s in search_work_type_str.split(',') if s.strip()]
        if wt_list:
            placeholders = ','.join(['?'] * len(wt_list))
            base_sql += f" AND work_type IN ({placeholders})"
            args.extend(wt_list)

    # 5. 状态
    if search_status_str:
        status_list = [s.strip() for s in search_status_str.split(',') if s.strip()]
        if status_list:
            placeholders = ','.join(['?'] * len(status_list))
            base_sql += f" AND status IN ({placeholders})"
            args.extend(status_list)

    # 6. ID模糊搜索
    if search_id:
        base_sql += " AND id LIKE ?"
        args.append(f'%{search_id}%')

    # 7. 日期
    if daterange:
        try:
            parts = daterange.split(' - ')
            if len(parts) == 2:
                base_sql += " AND created_at >= ? AND created_at <= ?"
                args.append(parts[0].strip() + " 00:00:00")
                args.append(parts[1].strip() + " 23:59:59")
        except:
            pass

    # 执行查询
    count_sql = f"SELECT COUNT(*) as total {base_sql}"
    total_res = query_db(count_sql, tuple(args), one=True)
    total_count = total_res['total'] if total_res else 0

    data_sql = f"SELECT * {base_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    args.extend([limit, offset])
    data_list = query_db(data_sql, tuple(args))

    return jsonify({
        "code": 0, "msg": "success", "count": total_count, "data": data_list
    })




@bp_orders.route('/api/work_order/reject', methods=['POST'])
@permission_required('SA','GA','HA','HP','DA','DH','SE','PA')
def api_work_order_reject():
    """ 
    驳回工单接口 
    """
    user = get_current_user_info()
    if not user: return jsonify({"code": 403, "msg": "登录失效"})

    current_level = user.get('current_level', 0)
    work_id = request.form.get('work_id')
    reason = request.form.get('reason')

    if not work_id or not reason:
        return jsonify({"code": 1, "msg": "参数不完整"})

    # 1. 查询工单信息 (包含状态和归属地)
    order_info = query_db("SELECT status, id_created_hospital, work_department FROM work_orders WHERE id = ?", (work_id,), one=True)
    if not order_info:
        return jsonify({"code": 1, "msg": "工单不存在"})

    # 2. 【新增】驳回权限校验
    # 防止A医院的人驳回B医院的单子
    if current_level < 90:
        if str(order_info['id_created_hospital']) != str(user['id_hospital']):
            return jsonify({"code": 1, "msg": "权限不足：无法操作其他医院工单"})
    
    # 防止非相关科室驳回 (仅职能科室可驳回，且必须是单子指派的科室)
    # 如果你是科级用户(Level < 50)，且工单指派的科室不是你所在的科室 -> 禁止操作
    if current_level < 50:
        # work_department 存储的是受理科室ID
        if str(order_info.get('work_department', '')) != str(user['id_department']):
             return jsonify({"code": 1, "msg": "权限不足：该工单未指派给您所在的科室"})

    # 3. 状态校验
    prev_status = int(order_info['status'])
    if prev_status in [3, 4, 5, 6]:  
        return jsonify({"code": 1, "msg": "当前工单状态无法驳回（可能已完成）"})
    if prev_status == 13:
        return jsonify({"code": 1, "msg": "本工单已驳回，请勿重复"})       
    
    # 4. 执行驳回
    target_status = 13 
    
    success, res = modify_db("UPDATE work_orders SET status = ? WHERE id = ?", (target_status, work_id))

    if success:
        log_details = f"工单被驳回。驳回原因：{reason}"
        record_order_flow(
            work_id=work_id,
            action="驳回",
            operator=user['username'], 
            curr_status=target_status,
            prev_status=prev_status,
            details=log_details
        )
        return jsonify({"code": 0, "msg": "驳回成功"})
    else:
        return jsonify({"code": 1, "msg": f"操作失败: {res}"})