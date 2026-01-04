# dispatch.py 报单界面
import os
from datetime import datetime
from flask import render_template, request, jsonify,session
# 引入数据库工具
from apps.tools.db import query_db, modify_db
from .route import bp_orders
from .orders_log import record_order_flow
from apps.tools.auth import login_required, permission_required
import json
import os


# -------------------------------------------------------
# 1. 渲染派单选择人员页面 (Iframe 内容)
# -------------------------------------------------------
@bp_orders.route('/dispatch/modal/<work_id>') 
@permission_required('SA','GA','HA','HP','DA','DH')
def dispatch_modal_page(work_id):
    # work_id 现在通过函数参数直接传入，不需要 request.args.get('id')
    if not work_id:
        return "缺少工单ID", 400

    # 1. 查询该工单的受理科室 (work_department)
    sql = "SELECT work_department, work_department_name FROM work_orders WHERE id = ?"
    order_info = query_db(sql, (work_id,), one=True)

    if not order_info:
        return "工单不存在", 404

    dept_id = str(order_info['work_department']) # 转字符串以便匹配 JSON key
    dept_name = order_info['work_department_name']

    # 2. 读取 available_staff.json 文件
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__))) # 回退到项目根目录
    json_path = os.path.join(base_dir,  'available_staff.json')
    staff_list = []
    try:
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                all_staff_data = json.load(f)
                # 获取该科室的人员，如果没有则返回空列表
                staff_list = all_staff_data.get(dept_id, [])
    except Exception as e:
        print(f"读取人员文件失败: {e}")

    # 3. 渲染页面
    return render_template(
        "orders/dispatch_modal.html",
        work_id=work_id,
        dept_name=dept_name,
        staff_list=staff_list
    )


# -------------------------------------------------------
# 2. 提交派单动作 (API)
# -------------------------------------------------------
@bp_orders.route('/api/dispatch_confirm', methods=['POST'])
@permission_required('SA','GA','HA','HP','DA','DH')
def dispatch_confirm():
    try:
        work_id = request.form.get('work_id')
        staff_name = request.form.get('staff_name')
        staff_phone = request.form.get('staff_phone')
        if not work_id or not staff_name:
            return jsonify({"code": 1, "msg": "请选择维修人员"})

        # =======================================================
        # 1. 关键步骤：先查询当前工单的实际状态status
        # =======================================================
        order_info = query_db("SELECT status FROM work_orders WHERE id = ?", (work_id,), one=True)
        if not order_info:
            return jsonify({"code": 1, "msg": "工单不存在或已被删除"})
        
        # 获取当前工单真实状态，作为流转记录的“前一状态”，另外判断是否不需要再派单了。
        real_prev_status = int(order_info['status']) if order_info['status'] is not None else 0
        if real_prev_status in[3,4,5,6]:
            return jsonify({"code": 1, "msg": "本工单已完成，请勿派单"})
        if real_prev_status == 12:
            return jsonify({"code": 1, "msg": "委外处理中，请勿派单"})
        if real_prev_status == 13:
            return jsonify({"code": 1, "msg": "本工单已驳回，请勿派单"})        
        # =======================================================
        # 2. 更新数据库
        # =======================================================
        staff_info = f"{staff_name}"
        sql = """
            UPDATE work_orders 
            SET status = 1, 
                staff = ?
            WHERE id = ?
        """
        success, _ = modify_db(sql, (staff_info, work_id))

        if not success:
            return jsonify({"code": 1, "msg": "派单失败，数据库写入错误"})

        # =======================================================
        # 3. 写入流转记录 (使用 real_prev_status)
        # =======================================================
        record_order_flow(
            work_id=work_id,
            action="手动派单",
            operator=session.get('username'), 
            prev_status=real_prev_status,  # <--- 这里使用实际状态
            curr_status=1,                 # 1 = 已派单/维修中
            details=f"已指派工作人员：{staff_name}进行处理",
            staff=staff_info
        )

        return jsonify({"code": 0, "msg": "派单成功"})

    except Exception as e:
        print(f"Dispatch error: {e}")
        return jsonify({"code": 1, "msg": "服务器内部错误"})