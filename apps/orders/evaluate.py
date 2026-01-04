from flask import render_template, request, jsonify
from apps.tools.db import query_db, modify_db, execute_transaction
from apps.tools.permissions import get_current_user_info
from apps.tools.auth import login_required
from .route import bp_orders
from datetime import datetime


# --- 渲染评价页面 ---
@bp_orders.route('/evaluate/<order_id>')
@login_required
def evaluate_page(order_id):
    # 1. 查询工单基础信息 (保持不变)
    sql_order = """
        SELECT 
            id, demand, location, work_content, staff, 
            status, created_at, with_device, outsource_flag,
            work_department_name, created_department_name,
            finish_photo
        FROM work_orders WHERE id = ?
    """
    order = query_db(sql_order, (order_id,), one=True)
    if not order:
        return "工单不存在", 404

    # 2. 查询关联设备信息 (保持不变)
    device_info = None
    if order['with_device']:
        sql_dev = "SELECT name, model, install_location FROM facility_object WHERE id = ?"
        device_info = query_db(sql_dev, (order['with_device'],), one=True)

    # 3. 统计物资消耗总费用 (保持不变)
    sql_mat_cost = """
        SELECT SUM(ABS(change_qty) * price) as total_cost, COUNT(*) as kind_count 
        FROM material_logs 
        WHERE work_order_id = ? AND action_type = '工单消耗'
    """
    mat_res = query_db(sql_mat_cost, (order_id,), one=True)
    material_data = {
        'cost': mat_res['total_cost'] if mat_res and mat_res['total_cost'] else 0,
        'count': mat_res['kind_count'] if mat_res else 0
    }

    # 4. 【修改点】查询委外费用 (适配 outsourcing_records 表)
    outsource_data = {'cost': 0, 'company': '无'}
    
    # 只有当工单标记为委外(outsource_flag=1)时才查询
    if order['outsource_flag'] == 1:
        # 修改为查询 outsourcing_records 表
        # 使用 unit_name 作为公司名，final_amount 作为最终费用
        sql_out = """
            SELECT unit_name, final_amount 
            FROM outsourcing_records 
            WHERE work_order_id = ?
        """
        out_res = query_db(sql_out, (order_id,), one=True)
        
        if out_res:
            outsource_data = {
                # 如果 final_amount 为空(未结算)，则显示 0
                'cost': out_res['final_amount'] or '尚未核价',
                'company': out_res['unit_name'] or '未知单位'
            }

    return render_template('orders/evaluate.html', 
                           order=order, 
                           device=device_info, 
                           material=material_data,
                           outsource=outsource_data)


# --- 提交评价接口 ---
@bp_orders.route('/api/evaluate/submit', methods=['POST'])
@login_required
def api_evaluate_submit():
    data = request.json
    user = get_current_user_info()
    
    work_id = data.get('work_id')
    # 确保转换为整数
    try:
        stars = int(data.get('stars', 3))
    except ValueError:
        stars = 3
        
    # 去除首尾空格
    feedback = data.get('feedback', '').strip()

    # --- 【新增校验】 ---
    # 逻辑：3星对应0分，低于0分即 < 3星 (1星、2星)
    if stars < 3 and not feedback:
        return jsonify({"code": 1, "msg": "给出差评（低于3星）时，必须填写具体反馈理由"})

    # 1. 转换分值
    # 1星->-2, 2星->-1, 3星->0, 4星->1, 5星->2
    score_mapping = {1: -2, 2: -1, 3: 0, 4: 1, 5: 2}
    final_score = score_mapping.get(stars, 0)

    # 2. 校验工单状态 (防止重复评价)
    check_sql = "SELECT status FROM work_orders WHERE id = ?"
    curr_order = query_db(check_sql, (work_id,), one=True)
    if not curr_order:
        return jsonify({"code": 1, "msg": "工单不存在"})
    
    if str(curr_order['status']) != '4':
        return jsonify({"code": 1, "msg": "当前工单状态不可评价"})

    # 3. 开启事务更新 (保持原有逻辑不变)
    operations = []
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # A. 更新工单表
    update_sql = """
        UPDATE work_orders 
        SET status = '5', evaluate_score = ?, feedback = ?
        WHERE id = ?
    """
    operations.append((update_sql, (final_score, feedback, work_id)))

    # B. 写入流转日志
    log_sql = """
        INSERT INTO work_order_logs (work_id, action, operator_name, prev_status, curr_status, details, created_at)
        VALUES (?, '科室评价', ?, 4, 5, ?, ?)
    """
    log_detail = f"用户评分: {stars}星 (得分: {final_score})。反馈: {feedback}"
    operations.append((log_sql, (work_id, user['username'], log_detail, current_time)))

    success, msg = execute_transaction(operations)

    if success:
        return jsonify({"code": 0, "msg": "评价提交成功，工单已归档"})
    else:
        return jsonify({"code": 1, "msg": f"提交失败: {msg}"})
