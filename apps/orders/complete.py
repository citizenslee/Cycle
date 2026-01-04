
from datetime import datetime
from flask import render_template, request, jsonify
from apps.tools.db import query_db,  execute_transaction
from apps.tools.permissions import get_current_user_info
from apps.tools.auth import permission_required
from apps.tools.deepseekapi import analyze_work_order_performance, recommend_relevant_devices
from .route import bp_orders

# --- 辅助函数 ---
def calc_minutes(t_start, t_end):
    if not all([t_start, t_end]): return 0
    fmt = '%Y-%m-%d %H:%M:%S'
    try:
        t1 = datetime.strptime(t_start, fmt)
        t2 = datetime.strptime(t_end, fmt)
        return int((t2 - t1).total_seconds() / 60)
    except (ValueError, TypeError):
        return 0

def parse_staff_names(staff_str):
    """统一解析人员字符串为列表"""
    if not staff_str: return []
    return [n.strip() for n in staff_str.replace('，', ',').split(',') if n.strip()]



# 主页面外壳
@bp_orders.route('/complete/<order_id>')
@permission_required('SA','GA','HA','HP','DA','DH')
def complete_main(order_id):
    order = query_db("SELECT * FROM work_orders WHERE id = ?", (order_id,), one=True)
    if not order: return "工单不存在", 404
    return render_template('orders/main_complete.html', order=order)

# --- 1.1 渲染步骤1子页面 ---
@bp_orders.route('/complete/step1/<order_id>')
@permission_required('SA','GA','HA','HP','DA','DH')
def settle_step1(order_id):
    # 1. 获取任务类型
    task_types = query_db("SELECT id, task_name, score FROM task_type ORDER BY task_name ASC")
    
    # 2. 获取受理部门ID
    # 注意：query_db 返回的是列表，我们需要先获取结果，再提取字段值
    dept_result = query_db("SELECT work_department FROM work_orders WHERE id = ? ", (order_id,))
    
    # 安全提取部门ID (如果查不到结果，设为 None)
    current_dept_id = dept_result[0]['work_department'] if dept_result else None

    # 3. 获取流转日志
    logs = query_db("SELECT * FROM work_order_logs WHERE work_id = ? ORDER BY created_at ASC", (order_id,))
    
    # 4. 获取维修工 (增加 id_department 筛选 和 staff_flag=1)
    if current_dept_id:
        all_technicians = query_db(
            "SELECT username as title, username as value FROM user WHERE role LIKE '%SE%' AND id_department = ? AND staff_flag = 1", 
            (current_dept_id,)
        )
    else:
        all_technicians = []
    print(all_technicians)
    return render_template('orders/step1_score.html', 
                           order_id=order_id, 
                           task_types=task_types, 
                           all_technicians=all_technicians,
                           logs=logs)

# --- 1.2 AI 执行分析接口 ---
@bp_orders.route('/api/settle/analyze', methods=['POST'])
def api_settle_analyze():
    data = request.json
    order_id = data.get('work_id')
    
    # 1. 获取该工单日志
    logs = query_db("SELECT * FROM work_order_logs WHERE work_id = ? ORDER BY created_at ASC", (order_id,))
    order = query_db("SELECT demand FROM work_orders WHERE id = ?", (order_id,), one=True)
    
    if not order:
        return jsonify({"code": 1, "msg": "工单不存在"})

    # 2. 提取日志中出现过的人员名 (用于 AI 建议关联)
    staff_set = set()
    for log in logs:
        staff_set.update(parse_staff_names(log.get('staff')))

    # 3. 调用 DeepSeek API 分析性能
    ai_result = analyze_work_order_performance(order['demand'], logs)
    
    # 4. 封装建议数据
    task_id = ai_result.get('final_task_type_id')
    suggested = {
        'task_type_id': task_id,
        'task_name': "未匹配",
        'base_score': 0,
        'coefficient': ai_result.get('task_coefficient', 1.0),
        'arrive_score': ai_result.get('arrival_score', 0),
        'repair_score': ai_result.get('repair_score', 0)
    }
    print(staff_set)
    if task_id:
        db_task = query_db("SELECT task_name, score FROM task_type WHERE id = ?", (task_id,), one=True)
        if db_task:
            suggested['task_name'] = db_task['task_name']
            suggested['base_score'] = db_task['score'] or 0

    return jsonify({
        "code": 0,
        "data": {
            "staff_list": list(staff_set),  # 建议移入穿梭框右侧的人员
            "ai_reason": ai_result.get('reasoning', '分析完成'),
            "suggested": suggested
        }
    })


# --- 2.1 渲染步骤2子页面 ---
@bp_orders.route('/complete/step2/<order_id>')
@permission_required('SA','GA','HA','HP','DA','DH')
def settle_step2(order_id):
    order = query_db("SELECT id_created_hospital FROM work_orders WHERE id = ?", (order_id,), one=True)
    # 传递医院ID给前端，用于全院搜索的锁死条件
    return render_template('orders/step2_device.html', 
                           order_id=order_id, 
                           hospital_id=order['id_created_hospital'])

# --- 2.2 AI 推荐接口 (修正排序逻辑) ---
@bp_orders.route('/api/settle/recommend_devices', methods=['POST'])
def api_settle_recommend_devices():
    data = request.json
    work_id = data.get('work_id')
    
    order = query_db("SELECT * FROM work_orders WHERE id = ?", (work_id,), one=True)
    if not order:
        return jsonify({"code": 1, "msg": "工单不存在"})
    
    # 1. 获取全量候选 (数据库通常按 ID 或 Name 排序)
    sql = """
        SELECT id, name, model, install_location, use_department_name
        FROM facility_object 
        WHERE id_hospital = ? AND use_department_id = ?
    """
    candidates = query_db(sql, (order['id_created_hospital'], order['id_created_department']))
    
    if not candidates:
        return jsonify({"code": 0, "data": {"top3": []}})

    # 构建 AI 输入 (省略...)
    order_info = {
        "demand": order['demand'],
        "work_content": order.get('work_content', '') or '',
        "location": order['location']
    }
    
    # 2. 调用 AI 获取 ID 列表 (这里返回的是有序的 [30, 6, 9])
    top3_ids = recommend_relevant_devices(order_info, candidates)
    
    # --- 核心修正点 START ---
    
    # 将候选列表转为字典，方便按 ID 提取
    candidate_map = {c['id']: c for c in candidates}
    
    # 按照 top3_ids 的顺序提取详情
    top3_details = []
    for uid in top3_ids:
        if uid in candidate_map:
            top3_details.append(candidate_map[uid])
            
    # --- 核心修正点 END ---

    return jsonify({
        "code": 0, 
        "data": { "top3": top3_details }
    })

# --- 2.3 全院分页搜索接口 (URL 传参版) ---
@bp_orders.route('/api/settle/search_devices_global/<order_id>', methods=['POST'])
def api_settle_search_devices_global(order_id):
    # 1. 获取分页和搜索关键字
    page = int(request.form.get('page', 1))
    limit = int(request.form.get('limit', 10))
    keyword = request.form.get('keyword', '').strip()
    
    offset = (page - 1) * limit
    order = query_db("SELECT id_created_hospital FROM work_orders WHERE id = ?", (order_id,), one=True)
    
    if not order:
        return jsonify({"code": 1, "msg": "找不到该工单信息", "count": 0, "data": []})
    
    hospital_id = order['id_created_hospital']

    # 3. 构建 SQL
    where_sql = "WHERE id_hospital = ?"
    params = [hospital_id]
    
    if keyword:
        where_sql += " AND (name LIKE ? OR model LIKE ? OR install_location LIKE ? OR use_department_name LIKE ?)"
        search_val = f"%{keyword}%"
        params.extend([search_val, search_val, search_val, search_val])

    # --- 打印调试日志 ---
    print(f"\n[API 访问] 工单: {order_id} | 医院ID: {hospital_id} | 搜索词: {keyword}")

    try:
        # 查询总数
        total_data = query_db(f"SELECT COUNT(*) as cnt FROM facility_object {where_sql}", params, one=True)
        total = total_data['cnt'] if total_data else 0
        
        # 分页查询
        query_params = params + [limit, offset]
        data_sql = f"""
            SELECT *
            FROM facility_object 
            {where_sql} 
            ORDER BY name ASC 
            LIMIT ? OFFSET ?
        """
        devices = query_db(data_sql, query_params)
        
        return jsonify({
            "code": 0,
            "msg": "success",
            "count": total,
            "data": devices
        })
    except Exception as e:
        print(f"❌ 数据库报错: {e}")
        return jsonify({"code": 1, "msg": "数据库查询失败", "count": 0, "data": []})
    


# --- 3.1 渲染步骤3子页面 ---
@bp_orders.route('/complete/step3/<order_id>')
@permission_required('SA','GA','HA','HP','DA','DH')
def settle_step3(order_id):
    return render_template('orders/step3_material.html', order_id=order_id)


# --- 3.2 物资分页搜索接口 (根据 order_id 自动匹配医院库存) ---
@bp_orders.route('/api/settle/search_stock/<order_id>', methods=['POST'])
def api_settle_search_stock(order_id):
    page = int(request.form.get('page', 1))
    limit = int(request.form.get('limit', 10))
    keyword = request.form.get('keyword', '').strip()
    
    offset = (page - 1) * limit

    # 自动获取医院ID
    order = query_db("SELECT id_created_hospital FROM work_orders WHERE id = ?", (order_id,), one=True)
    if not order:
        return jsonify({"code": 1, "msg": "工单不存在"})
    
    hospital_id = order['id_created_hospital']

    where_sql = "WHERE id_hospital = ? AND quantity > 0"
    params = [hospital_id]
    
    if keyword:
        where_sql += " AND (name LIKE ? OR model LIKE ? OR spec LIKE ?)"
        search_val = f"%{keyword}%"
        params.extend([search_val, search_val, search_val])
        
    total = query_db(f"SELECT COUNT(*) as cnt FROM material_stock {where_sql}", params, one=True)['cnt']
    
    data_sql = f"""
        SELECT id, name, model, spec, price, quantity as stock_qty 
        FROM material_stock 
        {where_sql} 
        ORDER BY name ASC 
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    stock = query_db(data_sql, params)
    
    return jsonify({
        "code": 0,
        "msg": "success",
        "count": total,
        "data": stock
    })

# --- 4.1 渲染步骤4子页面 ---
@bp_orders.route('/complete/_confirm/<order_id>')
def settle_confirm(order_id):
    return render_template('orders/step4_confirm.html', order_id=order_id)

# --- 4.2 最终提交 API (核心事务) ---
@bp_orders.route('/api/settle/submit', methods=['POST'])
def api_settle_submit():
    data = request.json
    user = get_current_user_info()
    
    work_id = data.get('work_id')
    scores = data.get('scores', {})
    ai_suggested = data.get('ai_suggested', {})
    staff_str = data.get('staff_str', '')
    device_id = data.get('device_id')
    materials = data.get('materials', [])
    remark = data.get('remark', '')

    # --- 后端审计打印：AI vs 人工对比 ---
    print(f"\n{'='*20} 工单结算终审报告 [ID: {work_id}] {'='*20}")
    print(f"操作员: {user['username']} | 时间: {datetime.now()}")
    print(f"{'考核项':<15} | {'AI 建议':<10} | {'人工核定':<10}")
    print(f"{'-'*45}")
    print(f"{'基础分':<15} | {ai_suggested.get('base_score',0):<10} | {scores.get('base_score'):<10}")
    print(f"{'系数':<15} | {ai_suggested.get('coefficient',1):<10} | {scores.get('coefficient'):<10}")
    print(f"{'最终总分':<15} | {'--':<10} | {scores.get('total_score'):<10}")
    print(f"参与人员: {staff_str}")
    print(f"关联设备ID: {device_id or '无'}")
    print(f"{'='*60}\n")

    # --- 数据库事务开始 ---
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    operations = []

    # 1. 更新工单主表
    update_order_sql = """
        UPDATE work_orders SET 
        status='4', total_score=?, staff=?, with_device=?, task_type=?,
        task_score=?, task_coefficient=?, arrival_score=?, repair_score=?,
        remark=?
        WHERE id=?
    """
    update_params = (
        scores.get('total_score'), staff_str, device_id, scores.get('task_type_id'),
        scores.get('base_score'), scores.get('coefficient'), scores.get('arrive_score'), scores.get('repair_score'),
        remark, work_id
    )
    operations.append((update_order_sql, update_params))

    # 2. 扣减物资库存 & 写入物资日志
    for m in materials:
        # 转换数量格式
        consume_qty = int(m['qty'])       # 消耗的数量 (用于计算总价)
        change_qty = -consume_qty         # 变动的数量 (负数)
        
        # ---------------------------------------------------------
        # 步骤 A: 扣减库存 (保持不变)
        # ---------------------------------------------------------
        stock_update_sql = "UPDATE material_stock SET quantity = quantity - ? WHERE id = ?"
        operations.append((stock_update_sql, (consume_qty, m['id'])))

        # ---------------------------------------------------------
        # 步骤 B: 记日志 (包含 id_use_department)
        # 修改点：
        # 1. INSERT 字段列表增加了 id_use_department
        # 2. SELECT 列表增加了一个子查询 (SELECT id_created_department FROM work_orders WHERE id = ?)
        # ---------------------------------------------------------
        log_mat_sql = """
            INSERT INTO material_logs (
                material_name, 
                model, 
                spec, 
                change_qty, 
                price, 
                total_cost, 
                action_type, 
                work_order_id, 
                operator, 
                created_at, 
                hospital_name, 
                id_hospital,
                id_use_department   -- 【新增字段】
            )
            SELECT 
                name,               -- material_name
                model,              -- model
                spec,               -- spec
                ?,                  -- change_qty (参数1)
                price,              -- price
                (price * ?),        -- total_cost (参数2)
                '工单消耗',          -- action_type
                ?,                  -- work_order_id (参数3)
                ?,                  -- operator (参数4)
                ?,                  -- created_at (参数5)
                hospital_name,      -- hospital_name
                id_hospital,        -- id_hospital
                (SELECT id_created_department FROM work_orders WHERE id = ?) -- 【新增子查询】(参数6)
            FROM material_stock 
            WHERE id = ?            -- (参数7)
        """
        
        # 参数必须严格对应 SQL 中 ? 的顺序
        log_params = (
            change_qty,        # 1. 变动数量
            consume_qty,       # 2. 消耗数量(算钱用)
            work_id,           # 3. 填入 work_order_id 字段
            user['username'],  # 4. 操作人
            current_time,      # 5. 时间
            work_id,           # 6. 【新增】给子查询用的 work_id，用来查部门
            m['id']            # 7. WHERE id = ? (物资ID)
        )
        
        operations.append((log_mat_sql, log_params))

    # 3. 写入工单流转日志
    # ---------------------------------------------------------
    # 步骤 C: 格式化详细信息 (包括物资明细)
    # ---------------------------------------------------------
    material_details_list = []
    total_materials_cost = 0 # 用于累加所有物料的总价

    if materials: # 仅当有物料时才生成物料明细
        for m in materials:
            # 假设 material_logs 中记录的 price 是单价
            # 并且我们之前已经通过 SQL 计算了 total_cost
            # 但这里我们在 Python 中需要的是当前传递过来的 m['price'] 来计算显示的总价
            # 或者，如果我们知道 m 字典里本身就带了 total_cost (通过前面SQL逻辑写入后，如果需要再查出来)
            # 考虑到效率，直接用 price * qty 会更直接
            material_price = float(m.get('price', 0)) # 获取单价，防止price不存在
            consume_qty = int(m['qty'])
            item_total_cost = material_price * consume_qty
            total_materials_cost += item_total_cost # 累加总成本

            material_info = (
                f"  - {m['name']}"
                f"(型号:{m.get('model', '无')}, 规格:{m.get('spec', '无')})"
                f" 数量:{consume_qty} {m.get('unit', '')}" # 假设有 unit 字段
                f", 单价:{material_price:.2f}"
                f", 小计:{item_total_cost:.2f}"
            )
            material_details_list.append(material_info)
        
        material_details_str = "\n".join(material_details_list)
    else:
        material_details_str = "  无"

    # 构建完整的 details 字符串
    log_detail = (
        f"结算完成。\n"
        f"总分: {scores.get('total_score', '无')}\n"
        f"参与人员: {staff_str or '无'}\n"
        f"设备ID: {device_id or '未关联'}\n"
        f"备注: {remark or '无'}\n"
        f"消耗物资明细:\n{material_details_str}\n"
        f"本次物料总计消耗金额: {total_materials_cost:.2f}" # 显示累计的总金额
    )

    log_work_sql = """
        INSERT INTO work_order_logs (work_id, action, operator_name, details, staff, created_at)
        VALUES (?, '完工信息补全', ?, ?, ?, ?)
    """
    
    operations.append((log_work_sql, (work_id, user['username'], log_detail, staff_str, current_time)))
    # 4. 写入设备生命周期日志
    if device_id:
        # 4.1 查询工单信息（直接使用 work_orders 表中的冗余字段，减少 JOIN）
        # 只需要 JOIN hospital 表获取医院名称
        wo_sql = """
            SELECT 
                w.demand,
                w.id_created_hospital,
                h.hospital_name,
                w.id_created_department,
                w.work_content,
                w.work_type,
                w.created_department_name,  -- 直接取发起科室名
                w.work_department,
                w.work_department_name      -- 直接取处理科室名
            FROM work_orders w
            LEFT JOIN hospital h ON w.id_created_hospital = h.id_hospital
            WHERE w.id = ?
        """
        wo_info = query_db(wo_sql, (work_id,), one=True)

        if wo_info:
            # 4.2 拼接日志内容
            # 格式：【任务类型】需求：xxx；处置：xxx
            log_content = f"【{wo_info['work_type']}】需求：{wo_info['demand']}；处置内容：{wo_info['work_content']}"
            # 处理空值
            h_name = wo_info['hospital_name'] or '未知医院'
            start_dept_name = wo_info['created_department_name'] or '未知科室'
            handle_dept_name = wo_info['work_department_name'] or '未知科室'
            log_device_sql = """
                INSERT INTO devices_log (
                    device_id, occur_time, 
                    hospital_name, hospital_id,
                    start_department_name, start_department_id,
                    handle_department_name, handle_department_id,
                    related_work_order, work_content, staff, type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            log_params = (
                device_id, 
                current_time,
                h_name, wo_info['id_created_hospital'],
                start_dept_name, wo_info['id_created_department'],
                handle_dept_name, wo_info['work_department'],
                work_id, 
                log_content, 
                staff_str, 
                wo_info['work_type']
            )
            operations.append((log_device_sql, log_params))

    # 执行事务
    success, msg = execute_transaction(operations)
    if success:
        return jsonify({"code": 0, "msg": "工单已正式完工并存入档案"})
    else:
        return jsonify({"code": 1, "msg": f"提交失败: {msg}"})