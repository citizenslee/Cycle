import os
import logging
from datetime import datetime
from flask import render_template, request, jsonify
from apps.tools.db import query_db, modify_db, execute_transaction
from .route import bp_orders
from apps.tools.auth import permission_required
from apps.tools.permissions import get_current_user_info
from hashids import Hashids

# 配置日志
logger = logging.getLogger(__name__)

# 配置 Hashids
hashids_vendor = Hashids(salt='1994', min_length=5)

# 状态码定义
class OrderStatus:
    INITIATED = "0"          # 已发起
    DISPATCHED = "1"         # 已派单
    ARRIVED = "2"            # 已到达
    COMPLETED = "3"          # 已完成
    INFO_FILLED = "4"        # 已补全信息
    FINISHED = "5"           # 已完结
    SUSPENDED = "11"         # 已挂起
    REJECTED = "13"          # 已驳回

    OUTSOURCED = "12"        # 已发起委外
    VENDOR_ARRIVED = "22"    # 委外供应商已到达
    VENDOR_COMPLETED = "32"  # 委外供应商已完成

    TERMINAL_STATES = ["3", "4", "5", "32"] 
    OUTSOURCING_LOCKED = ["12", "22"]

# -------------------------------------------------------------------------
# 页面渲染: 委外单位管理列表
# -------------------------------------------------------------------------
@bp_orders.route('/outsource_units')
@permission_required('SA','GA','HA','HP','DA','DH','SE','ST')
def outsource_units():
    user = get_current_user_info()
    # 获取等级
    current_level = user.get('current_level', 0)

    hospitals = []
    departments = []

    # 1. 权限逻辑：准备下拉框数据
    if current_level >= 90:
        # [超管] 加载所有数据
        hospitals = query_db("SELECT id_hospital, hospital_name FROM hospital")
        departments = query_db("SELECT id_department, department_name, id_hospital FROM department")
    else:
        # [院管/科管] 锁定本院数据
        hospitals = [{'id_hospital': user['id_hospital'], 'hospital_name': user['hospital_name']}]
        # 加载本院所有科室 (供院管筛选，或科管回显)
        departments = query_db("SELECT id_department, department_name, id_hospital FROM department WHERE id_hospital = ?", (user['id_hospital'],))

    return render_template('orders/outsource_units.html', 
                           user=user, 
                           current_level=current_level,  # <--- 🔥 必须传递此变量
                           hospitals=hospitals,
                           departments=departments)


# -------------------------------------------------------------------------
# 页面渲染：渲染委外派单弹窗 
# -------------------------------------------------------------------------
@bp_orders.route('/outsource/<order_id>')
@permission_required('SA','GA','HA','HP','DA','DH','SE')
def outsource_page(order_id):
    """ 渲染委外派单页面 """
    user = get_current_user_info()
    current_level = user.get('current_level', 0)

    # 1. 获取工单
    order = query_db("SELECT * FROM work_orders WHERE id = ?", (order_id,), one=True)
    if not order:
        return "工单不存在", 404
    
    # 2. 权限校验 (防止越权查看/操作弹窗)
    if current_level < 90:
        if str(order['id_created_hospital']) != str(user['id_hospital']):
            return "无权操作其他医院的工单", 403
            
    if current_level < 50:
        # 职能科室/工程师：只能操作【指派给本科室】的工单
        # work_department 是工单当前的受理科室
        if str(order.get('work_department', '')) != str(user['id_department']):
            return "无权操作非本科室受理的工单", 403

    # 3. 状态校验
    curr_status = str(order['status'])
    if curr_status in OrderStatus.TERMINAL_STATES:
        return f"当前工单已完成(状态:{curr_status})，无法发起委外", 400
    if curr_status in OrderStatus.OUTSOURCING_LOCKED:
        return "该工单已处于委外处理中，请勿重复派单", 400
    if curr_status == OrderStatus.REJECTED:
        return "已驳回工单无法发起委外", 400

    # 4. 获取该工单所属受理科室的可用委外单位
    # 注意：这里查的是工单的受理科室(work_department)下的单位，确保单位匹配
    units = query_db("""
        SELECT id, unit_name, unit_desc FROM outsourcing_units 
        WHERE status = 1 AND id_department = ?
    """, (order['work_department'],))
    return render_template('orders/outsource_process.html', order=order, units=units)


# -------------------------------------------------------------------------
# API: 获取委外单位列表 (带权限过滤)
# -------------------------------------------------------------------------
@bp_orders.route('/api/outsource/list')
@permission_required('SA','GA','HA','HP','DA','DH')
def api_outsource_list():
    user = get_current_user_info()
    current_level = user.get('current_level', 0)

    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 10))
    keyword = request.args.get('keyword')
    
    req_hospital_id = request.args.get('search_hospital')
    req_dept_id = request.args.get('search_dept')

    where_sql = ["1=1"]
    params = []

    # 1. 权限过滤
    target_hospital = None
    target_dept = None

    if current_level >= 90:
        target_hospital = req_hospital_id
        target_dept = req_dept_id
    elif current_level >= 50:
        target_hospital = user['id_hospital'] # 锁定本院
        target_dept = req_dept_id             # 可选科室
    else:
        target_hospital = user['id_hospital'] # 锁定本院
        target_dept = user['id_department']   # 锁定本科室

    # 2. 构建 SQL
    if target_hospital:
        where_sql.append("id_hospital = ?")
        params.append(target_hospital)
    
    if target_dept:
        where_sql.append("id_department = ?")
        params.append(target_dept)

    if keyword:
        where_sql.append("(unit_name LIKE ? OR unit_desc LIKE ?)")
        params.extend([f'%{keyword}%', f'%{keyword}%'])

    where_clause = " WHERE " + " AND ".join(where_sql)
    sql_base = f"SELECT * FROM outsourcing_units {where_clause} ORDER BY id DESC LIMIT ? OFFSET ?"
    sql_count = f"SELECT COUNT(*) as cnt FROM outsourcing_units {where_clause}"
    
    rows = query_db(sql_base, params + [limit, (page-1)*limit])
    count_res = query_db(sql_count, params, one=True)
    
    # 3. 数据加工
    base_url = request.url_root.rstrip('/')
    data_list = []
    for row in rows:
        item = dict(row)
        item['vendor_link'] = f"{base_url}/v/portal/{hashids_vendor.encode(item['id'])}"
        data_list.append(item)

    return jsonify({"code": 0, "msg": "", "count": count_res['cnt'] if count_res else 0, "data": data_list})


# -------------------------------------------------------------------------
# API: 新增/修改委外单位
# -------------------------------------------------------------------------
@bp_orders.route('/api/outsource/save', methods=['POST'])
@permission_required('SA','GA','HA','HP','DA','DH')
def api_outsource_save():
    user = get_current_user_info()
    current_level = user.get('current_level', 0)
    data = request.form
    
    unit_id = data.get('id')
    unit_name = data.get('unit_name')
    unit_desc = data.get('unit_desc')
    status = data.get('status', 1)

    # 1. 确定归属地 (权限强制覆盖)
    final_h_id = ''
    final_d_id = ''

    if current_level >= 90:
        final_h_id = data.get('id_hospital')
        final_d_id = data.get('id_department')
    elif current_level >= 50:
        final_h_id = user['id_hospital']
        final_d_id = data.get('id_department') # 院管可以指定是哪个科室的供应商
    else:
        final_h_id = user['id_hospital']
        final_d_id = user['id_department']

    if not all([final_h_id, final_d_id, unit_name]):
        return jsonify({"code": 1, "msg": "参数不完整或权限受限"})

    # 2. 查表补全名称
    h_info = query_db("SELECT hospital_name FROM hospital WHERE id_hospital=?", (final_h_id,), one=True)
    d_info = query_db("SELECT department_name FROM department WHERE id_department=?", (final_d_id,), one=True)
    
    if not h_info or not d_info:
        return jsonify({"code": 1, "msg": "医院或科室信息无效"})

    # 3. 执行保存
    if unit_id:
        # 修改前检查：防止科管修改其他科室的数据 (虽然前端有过滤，后端需兜底)
        if current_level < 50:
            check = query_db("SELECT id_department FROM outsourcing_units WHERE id=?", (unit_id,), one=True)
            if check and str(check['id_department']) != str(user['id_department']):
                return jsonify({"code": 1, "msg": "权限不足：只能修改本科室的委外单位"})

        sql = """UPDATE outsourcing_units SET 
                 unit_name=?, unit_desc=?, id_department=?, department_name=?, 
                 id_hospital=?, hospital_name=?, status=?
                 WHERE id = ?"""
        args = (unit_name, unit_desc, final_d_id, d_info['department_name'], final_h_id, h_info['hospital_name'], status, unit_id)
    else:
        sql = """INSERT INTO outsourcing_units 
                 (unit_name, unit_desc, id_department, department_name, id_hospital, hospital_name, status) 
                 VALUES (?, ?, ?, ?, ?, ?, ?)"""
        args = (unit_name, unit_desc, final_d_id, d_info['department_name'], final_h_id, h_info['hospital_name'], status)

    success, res = modify_db(sql, args)
    return jsonify({"code": 0, "msg": "保存成功"}) if success else jsonify({"code": 1, "msg": f"保存失败: {res}"})


# -------------------------------------------------------------------------
# API: 删除委外单位
# -------------------------------------------------------------------------
@bp_orders.route('/api/outsource/delete', methods=['POST'])
@permission_required('SA','GA','HA','HP','DA','DH')
def api_outsource_delete():
    user = get_current_user_info()
    current_level = user.get('current_level', 0)
    unit_id = request.form.get('id')
    
    # 1. 权限校验
    check_sql = "SELECT id FROM outsourcing_units WHERE id = ?"
    params = [unit_id]
    
    if current_level < 90:
        check_sql += " AND id_hospital = ?"
        params.append(user['id_hospital'])
        
    if current_level < 50:
        check_sql += " AND id_department = ?"
        params.append(user['id_department'])
        
    if not query_db(check_sql, params, one=True):
        return jsonify({"code": 1, "msg": "数据不存在或无权操作"})

    success, res = modify_db("DELETE FROM outsourcing_units WHERE id = ?", (unit_id,))
    return jsonify({"code": 0, "msg": "删除成功"}) if success else jsonify({"code": 1, "msg": str(res)})


# -------------------------------------------------------------------------
# API: 提交委外派单 (业务核心)
# -------------------------------------------------------------------------
@bp_orders.route('/api/outsource/confirm', methods=['POST'])
@permission_required('SA','GA','HA','HP','DA','DH','SE')
def api_outsource_confirm():
    user = get_current_user_info()
    current_level = user.get('current_level', 0)
    
    data = request.form
    order_id = data.get('order_id')
    unit_id = data.get('unit_id')
    notes = data.get('notes', "无")

    # 1. 获取工单
    order = query_db("SELECT * FROM work_orders WHERE id = ?", (order_id,), one=True)
    if not order: return jsonify({"code": 1, "msg": "工单不存在"})

    # 2. 权限校验 (核心安全逻辑)
    # 规则：只有【当前受理该工单的科室】或者上级管理员，才能将该工单委外
    # work_department = 工单当前的受理科室ID
    if current_level < 90:
        if str(order['id_created_hospital']) != str(user['id_hospital']):
            return jsonify({"code": 1, "msg": "权限不足：无法操作其他医院工单"})

    if current_level < 50:
        # 科室管理员/工程师：必须是本单的受理方
        if str(order.get('work_department', '')) != str(user['id_department']):
             return jsonify({"code": 1, "msg": "权限不足：该工单未指派给您所在的科室"})

    # 3. 状态校验
    curr_status = str(order['status'])
    if curr_status in OrderStatus.TERMINAL_STATES:
        return jsonify({"code": 1, "msg": "工单已结束"})
    if curr_status == OrderStatus.REJECTED:
        return jsonify({"code": 1, "msg": "工单已驳回"})
    if curr_status in OrderStatus.OUTSOURCING_LOCKED:
        return jsonify({"code": 1, "msg": "工单已在委外流程中"})

    # 4. 获取委外单位信息
    unit = query_db("SELECT unit_name FROM outsourcing_units WHERE id = ?", (unit_id,), one=True)
    if not unit: return jsonify({"code": 1, "msg": "无效的委外供应商"})

    # 5. 执行事务
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    target_status = OrderStatus.OUTSOURCED  # 12

    operations = [
        # ① 更新工单状态
        (
            "UPDATE work_orders SET outsource_flag = 1, status = ? WHERE id = ?",
            (target_status, order_id)
        ),
        # ② 记录日志
        (
            """INSERT INTO work_order_logs 
               (work_id, operator_name, action, prev_status, curr_status, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                order_id,
                user['username'],
                '发起委外',
                curr_status,
                target_status,
                f"已委托外部供应商：【{unit['unit_name']}】处理。说明：{notes}",
                now
            )
        ),
        # ③ 创建委外记录
        (
            """INSERT INTO outsourcing_records (
                work_order_id,
                outsourcing_unit_id,
                unit_name,
                outsourcing_unit_by_dept_id,
                outsourcing_unit_by_dept_name,
                remark, status, assigned_at,
                use_department_id, use_department_name,
                demand, location, contact_phone
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order_id,
                unit_id,
                unit['unit_name'],
                order['work_department'], # 发起委外的管理科室
                user['department_name'],  # 这里假设操作人就是管理科室的人，或者根据业务逻辑取 order['work_department_name']
                notes,
                target_status,
                now,
                order['id_created_department'],
                order['created_department_name'],
                order['demand'],
                order['location'],
                order['contact_phone']
            )
        )
    ]

    success, err = execute_transaction(operations)

    if success:
        return jsonify({"code": 0, "msg": "委外派单成功"})
    else:
        return jsonify({"code": 1, "msg": f"执行失败: {err}"})