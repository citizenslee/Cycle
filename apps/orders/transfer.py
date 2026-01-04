# transfer.py 转单界面
import os
from datetime import datetime
from flask import render_template, request, jsonify, session
from apps.tools.db import query_db, modify_db
from .route import bp_orders
from .orders_log import record_order_flow
from apps.tools.auth import login_required

# -------------------------------------------------------
# 1. 渲染转单弹窗
# -------------------------------------------------------
@bp_orders.route('/transfer/<work_id>')

def transfer_page(work_id):
    # 1. 获取工单信息（包含医院ID）
    order_info = query_db(
        """
        SELECT 
            work_department,
            work_department_name,
            id_created_hospital
        FROM work_orders
        WHERE id = ?
        """,
        (work_id,),
        one=True
    )

    if not order_info:
        return "工单不存在", 404

    current_dept_id = order_info['work_department']
    current_dept_name = order_info['work_department_name']
    hospital_id = order_info['id_created_hospital']
    print(current_dept_id,current_dept_name,hospital_id)
    candidates = []
    if hospital_id:
        # 2. 查询同医院下可转入的职能科室
        sql_candidates = """
            SELECT 
                id_department,
                department_name
            FROM department
            WHERE id_hospital = ?
            AND work_flag = 1
        """
        params = [hospital_id]
        if current_dept_id:
            sql_candidates += " AND id_department != ?"
            params.append(current_dept_id)
        candidates = query_db(sql_candidates, tuple(params))
    return render_template(
        "orders/transfer_modal.html",
        work_id=work_id,
        current_dept_name=current_dept_name,
        candidates=candidates
    )

# -------------------------------------------------------
# 2. 提交转单动作 (API)
# -------------------------------------------------------
@bp_orders.route('/api/transfer_confirm', methods=['POST'])

def transfer_confirm():
    try:
        work_id = request.form.get('work_id')
        target_dept_id = request.form.get('target_dept_id')
        reason = request.form.get('reason')

        if not work_id or not target_dept_id or not reason:
            return jsonify({"code": 1, "msg": "参数不完整：请选择科室并填写原因"})

        # 1. 获取目标科室名称 (用于存入 work_department_name)
        target_dept = query_db(
            "SELECT department_name FROM department WHERE id_department = ?", 
            (target_dept_id,), 
            one=True
        )
        if not target_dept:
            return jsonify({"code": 1, "msg": "目标科室不存在"})
        
        target_dept_name = target_dept['department_name']

        # 2. 获取当前状态 (用于日志 prev_status)
        curr_order = query_db("SELECT status, work_department_name FROM work_orders WHERE id=?", (work_id,), one=True)
        prev_status = curr_order['status'] if curr_order else 0
        old_dept_name = curr_order['work_department_name'] if curr_order else "原科室"

        # 3. 更新数据库
        # 逻辑：转单后，对于新科室来说是“新单子”。
        # 所以 status 重置为 0 (待派单)，清空 staff (维修人) 和 dispatched_at
        sql_update = """
            UPDATE work_orders 
            SET work_department = ?, 
                work_department_name = ?,
                status = 0,
                staff = NULL,
                contact_phone = contact_phone -- 保持联系人电话不变(或者是空操作)
            WHERE id = ?
        """
        success, _ = modify_db(sql_update, (target_dept_id, target_dept_name, work_id))

        if not success:
            return jsonify({"code": 1, "msg": "转单失败，数据库错误"})

        # 4. 记录流转日志
        log_detail = f"从【{old_dept_name}】转单至【{target_dept_name}】。原因：{reason}"
        
        record_order_flow(
            work_id=work_id,
            action="转单",
            operator=session.get('username'),
            prev_status=prev_status,
            curr_status=0, # 转单后重置为0
            details=log_detail
        )

        return jsonify({"code": 0, "msg": "转单成功"})

    except Exception as e:
        print(f"Transfer error: {e}")
        return jsonify({"code": 1, "msg": "服务器内部错误"})