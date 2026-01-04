from flask import render_template, request, jsonify, session
from apps.tools.db import query_db, execute_transaction, modify_db
from apps.tools.permissions import get_current_user_info
from apps.devices.route import bp_devices
import datetime

class OrderStatus:
    PENDING = '0'      # 待派单
    DISPATCHED = '1'   # 已派单
    COMPLETED = '5'    # 已完成/已结单

# ---------------------------------------------------------------------
# 1. 巡检打卡页面 (渲染)
# ---------------------------------------------------------------------
@bp_devices.route('/check_in/<int:device_id>')
def check_in_page(device_id):
    # 1. 获取设备信息 (所有人可见)
    sql_device = """
        SELECT f.*, h.hospital_name 
        FROM facility_object f
        LEFT JOIN hospital h ON f.id_hospital = h.id_hospital
        WHERE f.id = ?
    """
    device = query_db(sql_device, (device_id,), one=True)
    if not device:
        return "设备不存在或已被移除", 404

    # 2. 获取当前用户信息
    user = get_current_user_info()
    
    # 3. 判定访问状态
    # 状态枚举: 'guest' (未登录), 'denied' (无权), 'allowed' (允许)
    access_status = 'guest'
    unauthorized_msg = "" # 用于前端弹窗提示具体的错误

    if user:
        if str(user.get('id_hospital')) == str(device.get('id_hospital')):
            access_status = 'allowed'
        else:
            access_status = 'denied'
            # 记录冲突信息供前端提示
            unauthorized_msg = f"当前账号归属【{user.get('hospital_name')}】，无法查看【{device.get('hospital_name')}】的维保记录。"

    # 4. 根据状态获取数据
    pending_orders = []
    recent_logs = []

    if access_status == 'allowed':
        # 只有有权限才查工单和日志
        sql_orders = """
            SELECT id, demand, status, work_type, created_at 
            FROM work_orders 
            WHERE with_device = ? AND status IN ('0', '1')
            ORDER BY created_at DESC
        """
        pending_orders = query_db(sql_orders, (device_id,))
        recent_logs = query_db("SELECT * FROM devices_log WHERE device_id = ? ORDER BY occur_time DESC LIMIT 10", (device_id,))

    return render_template(
        'devices/devices_check_in.html',
        device=device,
        orders=pending_orders,
        logs=recent_logs,
        user=user,
        access_status=access_status,       # 传递状态
        unauthorized_msg=unauthorized_msg  # 传递错误消息
    )

# ---------------------------------------------------------------------
# 2. 巡检签到 API (执行动作)
# ---------------------------------------------------------------------
@bp_devices.route('/api/orders_check_in', methods=['POST'])
def api_orders_check_in():
    user = get_current_user_info()
    if not user:
        return jsonify({"code": 401, "msg": "身份信息已过期，请重新登录"})

    data = request.json or {}
    order_id = data.get('order_id')
    if not order_id:
        return jsonify({"code": 1, "msg": "参数错误：缺少工单ID"})

    # 1. 核心数据校验 (读操作不需要事务，保持原样)
    sql_check = """
                SELECT
                    w.*,
                    t.task_name,
                    t.score,
                    f.name AS device_name,
                    f.id_hospital AS dev_hosp_id
                FROM work_orders w
                LEFT JOIN task_type t ON w.task_type = t.id
                LEFT JOIN facility_object f ON w.with_device = f.id
                WHERE w.id = ?

                    """
    order = query_db(sql_check, (order_id,), one=True)

    if not order:
        return jsonify({"code": 1, "msg": "未找到相关工单记录"})
    
    # 越权校验
    if str(user['id_hospital']) != str(order['dev_hosp_id']):
        return jsonify({"code": 403, "msg": "越权操作：您无法处理非本院工单"})

    if str(order['status']) == OrderStatus.COMPLETED:
        return jsonify({"code": 1, "msg": "该工单已处于完成状态"})

    # 准备事务数据
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username = user['username']
    task_name = order['task_name'] or "日常巡检"
    task_score = order["score"] or 0
    # 定义事务操作列表 [(sql, args), (sql, args), ...]
    operations = []
    work_content = f"工作人员【{username}】到达【{order['device_name']}】现场，完成了本【{task_name}】工单"
    sql_update_order = """
        UPDATE work_orders
        SET
            status = ?,
            staff = ?,
            work_content = ?,
            task_score = ?,
            total_score = ?,
            repair_score = 0,
            arrival_score = 0,
            task_coefficient = 0,
            outsource_flag = 0,
            remark = '',
            feedback = ''
        WHERE id = ?
    """

    operations.append((sql_update_order, (OrderStatus.COMPLETED, username, work_content, task_score, task_score, order_id)))

    # B. 记录工单轨迹日志 (原 record_order_flow 函数逻辑转为 SQL)
    # 注意：请确认你的流转日志表名是 'work_order_flow' 还是其他名称
    sql_flow = """
                    INSERT INTO work_order_logs
                    (
                        work_id,
                        action,
                        operator_name,
                        prev_status,
                        curr_status,
                        staff,
                        details,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """

    operations.append((
        sql_flow,
        (
            order_id,
            '完成工单（设备）',
            username,
            int(order['status']),
            int(OrderStatus.COMPLETED),
            username,
            f"工作人员【{username}】到达【{order['device_name']}】现场，完成了本次【{task_name}】类工单，本次工单赋【{task_score}】分",
            now_str
        )
    ))


    # C. 写入设备全生命周期日志
    sql_device_log = """
        INSERT INTO devices_log (
            device_id,
            occur_time,
            hospital_name,
            hospital_id,
            start_department_name,
            start_department_id,
            handle_department_name,
            handle_department_id,
            work_content,
            staff,
            type,
            related_work_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    operations.append((
        sql_device_log,
        (
            order['with_device'],
            now_str,
            user['hospital_name'],
            user['id_hospital'],
            order['created_department_name'],
            order['id_created_department'],
            user['department_name'],
            user['id_department'],
            f"【{task_name}签到】：工作人员【{username}】完成{task_name}工单（工单号：{order_id}）",
            username,
            task_name,
            order_id
        )
    ))

    # 执行事务
    success, err = execute_transaction(operations)

    if success:
        return jsonify({"code": 0, "msg": "签到成功"})
    else:
        # 记录具体的错误信息以便调试
        print(f"Checkin Transaction Error: {err}")
        return jsonify({"code": 500, "msg": "数据库写入失败，请重试"})
    
# ---------------------------------------------------------------------
# 3. 故障上报页面 (弹窗 Iframe)
# ---------------------------------------------------------------------
@bp_devices.route('/report_fault_page')
def report_fault_page():
    device_id = request.args.get('device_id')
    if not device_id:
        return "参数错误", 400
    
    # 获取设备基础信息，用于回显地点和确定归属医院
    sql = "SELECT id, name, install_location, id_hospital, hospital_name, id_department, department_name FROM facility_object WHERE id = ?"
    device = query_db(sql, (device_id,), one=True)
    
    return render_template('devices/devices_report_form.html', device=device)

# ---------------------------------------------------------------------
# 4. 故障上报提交 API
# ---------------------------------------------------------------------
@bp_devices.route('/api/report_fault', methods=['POST'])
def api_report_fault():
    # 注意：此接口允许未登录访问
    data = request.form
    device_id = data.get('device_id')
    demand = data.get('demand', '用户未填写详情') # 允许为空，给个默认值
    location = data.get('location', '')
    contact_phone = data.get('contact_phone', '')
    
    # 尝试获取当前登录用户（如果有），没有则是匿名
    user = get_current_user_info()
    
    # 1. 再次查询设备信息以确保数据一致性
    device = query_db("SELECT * FROM facility_object WHERE id = ?", (device_id,), one=True)
    if not device:
        return jsonify({"code": 1, "msg": "设备不存在"})

    # 2. 生成工单数据
    # 自动生成工单号 (示例逻辑，你可以用 uuid 或 hashids)
    import time
    import random
    order_id = f"R{int(time.time())}{random.randint(100,999)}" 
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 确定创建人信息
    creator_name = user['username'] if user else "扫码报修用户"
    creator_id = str(user['id']) if user else "0"
    
    # 3. 写入工单表 (Work Orders)
    # 逻辑：
    # - id_created_department: 设备的【使用科室】(即故障发生的科室)
    # - work_department: 设备的【管理科室】(即负责维修的科室)
    sql = """
        INSERT INTO work_orders (
            id, 
            work_type, 
            demand, 
            location, 
            contact_phone, 
            status, 
            
            with_device, 
            device_name,
            
            id_created_hospital, 
            created_hospital_name,
            
            id_created_department, 
            created_department_name,
            
            work_department, 
            work_department_name,
            
            creator_id, 
            creator_name, 
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    
    args = (
        order_id, 
        '故障报修',       # work_type
        demand,          # 需求描述
        location,        # 地点
        contact_phone,   # 联系电话
        OrderStatus.PENDING, # 状态：0 待派单
        
        device['id'],    # with_device
        device['name'],  # device_name
        
        device['id_hospital'], 
        device['hospital_name'],
        
        device['use_department_id'],   # 发起科室 = 设备的使用科室
        device['use_department_name'],
        
        device['id_department'],       # 受理科室 = 设备的管理科室
        device['department_name'],
        
        creator_id,
        creator_name,
        now_str
    )

    success, res = modify_db(sql, args)
    
    if success:
        # 可选：写入日志
        return jsonify({"code": 0, "msg": "上报成功", "order_id": order_id})
    else:
        return jsonify({"code": 1, "msg": f"系统错误: {res}"})